"""Local-first warehouse: the three-store role split (plan §2.2–§2.5, §2.8–§2.10).

Of everything the system holds, only the live pick stream is unrebuildable — so the stores
are split by the *durability class* of the data each owns:

* **SQLite** (``app.sqlite``) — ACID app state + the append-only ``draft_event_log`` (crown
  jewels, kept forever). WAL + ``synchronous=FULL``.
* **Parquet** (``parquet/``) — immutable upstream snapshots (nflverse, FFC). Rebuildable.
* **DuckDB** (``warehouse.duckdb``) — materialized analytics. **DISPOSABLE**: ``make
  warehouse`` (→ :func:`rebuild_warehouse`) rebuilds it from Parquet + SQLite, so deleting
  it is never data loss. ``app.sqlite`` is the only file whose loss is unrecoverable.

The warehouse OPENS the SAME ``app.sqlite`` that Stage-1 ingest writes — reusing
``ingest.log.open_log``'s pragmas and ``draft_event_log`` DDL — and only ADDS tables. It is
never a writer of the log; that single-writer role stays in ``ingest/log.py``.

Schema stays graduation-friendly (plan §2.9): the JSON payload/text columns map 1:1 to
PostgreSQL ``jsonb`` and the monotonic-``seq`` log maps 1:1 to a Redis Stream, so this can
graduate to Postgres + Redis Streams later without changing callers. Single-user default
per ADR 0002.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jaaffl.config import get_settings
from jaaffl.domain import DraftState, LeagueSettings
from jaaffl.ingest.log import open_log, read_events

if TYPE_CHECKING:
    import duckdb
    import polars as pl

# App-state tables the warehouse ADDS to app.sqlite. The Stage-1 ``draft_event_log`` is
# owned by ``ingest/log.py`` and created by ``open_log`` — it is deliberately absent here.
# Every statement is idempotent; this is migration version 1 (see ``_MIGRATIONS``). STRICT
# tables + explicit CHECKs mirror plan §2.3 verbatim.
_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS league_snapshots (
    snapshot_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id    TEXT NOT NULL,
    kind         TEXT NOT NULL
                   CHECK (kind IN ('settings','projections','injuries','draft_board','other')),
    payload      TEXT NOT NULL CHECK (json_valid(payload)),
    content_hash TEXT NOT NULL,
    source       TEXT,
    captured_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX IF NOT EXISTS ix_snap_league_time
    ON league_snapshots(league_id, kind, captured_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_snap_dedup
    ON league_snapshots(league_id, kind, content_hash);

CREATE TABLE IF NOT EXISTS players (
    player_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    position   TEXT NOT NULL CHECK (position IN ('QB','RB','WR','TE','K','DST','DL','LB','DB')),
    nfl_team   TEXT,
    name_norm  TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX IF NOT EXISTS ix_players_match ON players(position, nfl_team, name_norm);

CREATE TABLE IF NOT EXISTS id_crosswalk (
    source         TEXT NOT NULL
                     CHECK (source IN ('gsis','pfr','cbs','ffc','fantasypros',
                                       'sleeper','espn','yahoo','nflverse')),
    source_id      TEXT NOT NULL,
    canonical_id   TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    method         TEXT NOT NULL CHECK (method IN ('deterministic','fuzzy','manual')),
    confidence     REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    match_features TEXT CHECK (match_features IS NULL OR json_valid(match_features)),
    resolved_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (source, source_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_crosswalk_canonical ON id_crosswalk(canonical_id);

CREATE TABLE IF NOT EXISTS manager_tendencies (
    league_id  TEXT NOT NULL, team_id TEXT NOT NULL, position TEXT NOT NULL,
    reaches    INTEGER NOT NULL DEFAULT 0, picks INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (league_id, team_id, position)
) STRICT, WITHOUT ROWID;
"""

# (version, DDL) applied in order; each recorded once in ``schema_migrations``. Add a
# ``(2, ...)`` tuple for the next additive change — never edit an applied migration.
_MIGRATIONS: list[tuple[int, str]] = [(1, _MIGRATION_1)]

# DuckDB materialized-analytics schema (plan §2.4). DISPOSABLE — rebuilt by `make warehouse`
# from Parquet + the ATTACHed app.sqlite. Empty until Stage 5 fills them; the schema exists
# now so rebuilds are structurally identical for fixed inputs.
_DUCKDB_TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS projections (
        player_id       VARCHAR   NOT NULL,
        season          INTEGER   NOT NULL,
        source          VARCHAR   NOT NULL,
        scoring_version VARCHAR   NOT NULL,
        stat_line       JSON,
        mu              DOUBLE    NOT NULL,
        sigma           DOUBLE,
        floor           DOUBLE,
        ceiling         DOUBLE,
        computed_at     TIMESTAMP NOT NULL DEFAULT now(),
        PRIMARY KEY (player_id, season, source, scoring_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS adp (
        player_id     VARCHAR NOT NULL,
        season        INTEGER NOT NULL,
        scoring       VARCHAR NOT NULL DEFAULT 'standard',
        teams         INTEGER NOT NULL DEFAULT 12,
        adp           DOUBLE  NOT NULL,
        stdev         DOUBLE,
        high          INTEGER,
        low           INTEGER,
        times_drafted INTEGER,
        bye           INTEGER,
        captured_at   DATE    NOT NULL,
        PRIMARY KEY (player_id, season, scoring, teams, captured_at)
    )
    """,
]


def _now_iso() -> str:
    """ISO-8601 UTC with millisecond precision (matches the SQLite ``strftime`` default)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any not-yet-recorded migrations, each stamped once in ``schema_migrations``."""
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL) STRICT;"
    )
    applied = {v for (v,) in conn.execute("SELECT version FROM schema_migrations")}
    for version, ddl in _MIGRATIONS:
        if version in applied:
            continue
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _now_iso()),
        )
        conn.commit()


def open_app_db(path: str | Path) -> sqlite3.Connection:
    """Open app.sqlite with the Stage-1 durability pragmas AND the warehouse app-state
    tables.

    Reuses ``ingest.log.open_log`` (WAL + ``synchronous=FULL`` + the ``draft_event_log``
    DDL) so there is ONE connection-open path and ONE owner of the log schema; the warehouse
    only adds tables via :func:`_run_migrations`. Shared by :class:`Warehouse` and
    :class:`~jaaffl.data.crosswalk.Crosswalk` so both see a consistent, fully-pragma'd db.
    """
    conn = open_log(path)  # pragmas + draft_event_log (single writer stays in ingest/log)
    _run_migrations(conn)
    return conn


class Warehouse:
    """Handle to the local data stores under ``JAAFFL_DATA_DIR``."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else get_settings().jaaffl_data_dir

    # --- paths -----------------------------------------------------------------------
    @property
    def app_sqlite(self) -> Path:
        return self.data_dir / "app.sqlite"

    @property
    def warehouse_duckdb(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    # --- lifecycle -------------------------------------------------------------------
    def init(self) -> None:
        """Create the store layout, the SQLite app-state schema (reusing the Stage-1 log
        pragmas), and the DuckDB analytics schema. Idempotent."""
        for d in (
            self.data_dir,
            self.parquet_dir / "nflverse",
            self.parquet_dir / "ffc",
            self.snapshots_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        open_app_db(self.app_sqlite).close()  # create/upgrade app.sqlite schema, then release
        self.materialize()  # (re)create the DuckDB analytics schema

    def materialize(self) -> None:
        """(Re)create the DISPOSABLE DuckDB analytics schema from Parquet + SQLite. Pure
        function of the inputs — no network, no wall-clock in the shape it produces."""
        con = self._duckdb_connect()
        try:
            for ddl in _DUCKDB_TABLES:
                con.execute(ddl)
        finally:
            con.close()

    # --- SQLite app state ------------------------------------------------------------
    def snapshot_league(self, settings: LeagueSettings) -> int | None:
        """Persist a ``kind='settings'`` snapshot of the raw CBS payload so historical
        analysis is owned locally (and Stage-4 ``CbsOnPageProvider`` reads it, not the
        network). De-dups byte-identical re-pushes via ``ux_snap_dedup`` (content hash):
        returns the new ``snapshot_id``, or ``None`` when a duplicate is dropped."""
        payload = json.dumps(
            settings.raw or settings.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        conn = open_app_db(self.app_sqlite)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO league_snapshots"
                " (league_id, kind, payload, content_hash, source)"
                " VALUES (?, 'settings', ?, ?, ?)",
                (settings.league_id, payload, content_hash, settings.platform),
            )
            conn.commit()
            return cur.lastrowid if cur.rowcount else None
        finally:
            conn.close()

    def snapshot_draft_state(
        self,
        state: DraftState,
        *,
        settings: LeagueSettings | None = None,
        captured_at: str | None = None,
    ) -> Path:
        """Write a per-draft export ``snapshots/draft_{league_id}_{ts}/`` (the offline
        backtest corpus, plan §2.8): ``final_state.json``, ``events.parquet`` (this draft's
        log rows), and ``league_settings.json`` when known. The ``league_id`` is sanitized to
        a single safe path component so it can never escape ``snapshots/``."""
        ts = re.sub(r"[^0-9A-Za-z]", "", captured_at or _now_iso())
        out = self.snapshots_dir / f"draft_{_safe_component(state.league_id)}_{ts}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "final_state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
        if settings is not None:
            (out / "league_settings.json").write_text(
                settings.model_dump_json(indent=2), encoding="utf-8"
            )
        self._export_events_parquet(state.league_id, out / "events.parquet")
        # TODO(stage 5): recommendations.jsonl once engine.recommend emits Recommendations.
        return out

    def _export_events_parquet(self, league_id: str, path: Path) -> None:
        import polars as pl

        conn = open_log(self.app_sqlite)
        try:
            events = read_events(conn, league_id)
        finally:
            conn.close()
        schema = {
            "seq": pl.Int64,
            "league_id": pl.Utf8,
            "event_type": pl.Utf8,
            "pick_number": pl.Int64,
            "data": pl.Utf8,
            "source": pl.Utf8,
            "captured_at": pl.Utf8,
        }
        rows = [
            {
                "seq": e.seq,
                "league_id": e.league_id,
                "event_type": e.event_type,
                "pick_number": e.pick_number,
                "data": json.dumps(e.data, sort_keys=True),
                "source": e.source,
                "captured_at": e.captured_at,
            }
            for e in events
        ]
        pl.DataFrame(rows, schema=schema).write_parquet(path)

    # --- Parquet (rebuildable upstream) ----------------------------------------------
    def write_parquet(self, name: str, df: pl.DataFrame) -> Path:
        """Write ``df`` to ``parquet/{name}.parquet`` (creating subdirs). ``name`` is a
        relative, traversal-free path (e.g. ``'nflverse/player_stats_2026'``)."""
        path = self._parquet_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        return path

    def scan_parquet(self, name: str) -> pl.DataFrame:
        """Scan ``parquet/{name}.parquet`` through DuckDB (zero-copy; plan §2.4)."""
        path = self._parquet_path(name)
        con = self._duckdb_connect()
        try:
            return con.execute("SELECT * FROM read_parquet(?)", [str(path)]).pl()
        finally:
            con.close()

    def _parquet_path(self, name: str) -> Path:
        parts = Path(name).parts
        if Path(name).is_absolute() or any(p == ".." for p in parts):
            raise ValueError(f"unsafe parquet name: {name!r}")
        path = self.parquet_dir.joinpath(*parts)
        return path if path.suffix == ".parquet" else path.with_name(path.name + ".parquet")

    # --- DuckDB ----------------------------------------------------------------------
    def _duckdb_connect(self) -> duckdb.DuckDBPyConnection:
        """Open ``warehouse.duckdb`` with the sqlite extension loaded and ``app.sqlite``
        ATTACHed as ``app`` (no data duplicated; plan §2.4). The attach is ``READ_ONLY`` so
        DuckDB can NEVER write app.sqlite — the single-writer role stays with ingest/log.py,
        and a ``make warehouse`` rebuild can't contend for a write lock during a live draft."""
        import duckdb

        con = duckdb.connect(str(self.warehouse_duckdb))
        with contextlib.suppress(duckdb.Error):
            con.execute("INSTALL sqlite")  # bundled in the wheel / offline: LOAD still works
        con.execute("LOAD sqlite")
        app_lit = str(self.app_sqlite).replace("\\", "/").replace("'", "''")
        con.execute(f"ATTACH '{app_lit}' AS app (TYPE SQLITE, READ_ONLY)")
        return con

    def duckdb_tables(self) -> set[str]:
        """Base-table names in ``warehouse.duckdb``'s own catalog (excludes ATTACHed app)."""
        con = self._duckdb_connect()
        try:
            rows = con.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_catalog = current_database() AND table_schema = 'main'"
            ).fetchall()
        finally:
            con.close()
        return {r[0] for r in rows}


def _safe_component(value: str) -> str:
    """Collapse a value to one filesystem-safe path component (no separators, no ``..``)."""
    cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", value).strip("._") or "unknown"
    return cleaned.replace("..", "_")


def rebuild_warehouse(data_dir: str | Path | None = None) -> Path:
    """Rebuild the DISPOSABLE ``warehouse.duckdb`` from Parquet + SQLite — what ``make
    warehouse`` runs. Removes ONLY ``warehouse.duckdb`` (never ``app.sqlite``, the one
    unrecoverable store) and re-materializes, proving DuckDB is disposable."""
    wh = Warehouse(data_dir)
    wh.warehouse_duckdb.unlink(missing_ok=True)
    wh.init()
    return wh.warehouse_duckdb


if __name__ == "__main__":  # `python -m jaaffl.data.warehouse` == `make warehouse`
    print(f"rebuilt {rebuild_warehouse()}")
