"""Local warehouse: the three-store role split (plan §2.2–§2.5, §2.8–§2.10).

SQLite = ACID app state + the append-only log (crown jewels); Parquet = immutable
upstream snapshots (rebuildable); DuckDB = materialized analytics (DISPOSABLE — a
``make warehouse`` rebuild reproduces it from Parquet + SQLite). These tests pin that
split: init adds tables without touching the Stage-1 log, snapshots de-dup by content
hash, and deleting ``warehouse.duckdb`` + ``parquet/`` is never data loss.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from jaaffl.data.warehouse import Warehouse, rebuild_warehouse
from jaaffl.domain import DraftPick, DraftState, LeagueSettings


@pytest.fixture
def wh(tmp_path: Path) -> Warehouse:
    w = Warehouse(tmp_path)
    w.init()
    return w


def _sqlite_tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _snapshot_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT league_id, kind, payload, content_hash"
            " FROM league_snapshots ORDER BY snapshot_id"
        ).fetchall()
    finally:
        conn.close()


def _seed_player(path: Path, player_id: str = "gsis:1", name: str = "CeeDee Lamb") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO players (player_id, name, position, name_norm) VALUES (?, ?, 'WR', ?)",
            (player_id, name, name.lower()),
        )
        conn.commit()
    finally:
        conn.close()


def settings(league_id: str = "L1", **extra) -> LeagueSettings:
    raw = {"league_id": league_id, "team_count": 12, "draft_type": "snake", **extra}
    return LeagueSettings(league_id=league_id, team_count=12, raw=raw)


# --- init + schema -------------------------------------------------------------------


def test_init_creates_directory_layout(tmp_path: Path) -> None:
    Warehouse(tmp_path).init()
    assert (tmp_path / "app.sqlite").exists()
    assert (tmp_path / "warehouse.duckdb").exists()
    assert (tmp_path / "parquet" / "nflverse").is_dir()
    assert (tmp_path / "parquet" / "ffc").is_dir()
    assert (tmp_path / "snapshots").is_dir()


def test_init_adds_app_state_tables(wh: Warehouse) -> None:
    tables = _sqlite_tables(wh.app_sqlite)
    assert {
        "league_snapshots",
        "players",
        "id_crosswalk",
        "manager_tendencies",
        "schema_migrations",
    } <= tables


def test_init_does_not_touch_the_stage1_log(wh: Warehouse) -> None:
    """The warehouse OPENS the same app.sqlite and ADDS tables; it is never a writer of
    the draft_event_log (single-writer stays in ingest/log.py)."""
    tables = _sqlite_tables(wh.app_sqlite)
    assert "draft_event_log" in tables  # open_log created it
    conn = sqlite3.connect(wh.app_sqlite)
    try:
        assert conn.execute("SELECT COUNT(*) FROM draft_event_log").fetchone()[0] == 0
    finally:
        conn.close()


def test_init_is_idempotent(tmp_path: Path) -> None:
    w = Warehouse(tmp_path)
    w.init()
    w.init()  # must not raise
    assert w.duckdb_tables() >= {"projections", "adp"}


def test_init_creates_duckdb_analytics_tables(wh: Warehouse) -> None:
    assert wh.duckdb_tables() >= {"projections", "adp"}


def test_init_records_all_schema_migrations(wh: Warehouse) -> None:
    conn = sqlite3.connect(wh.app_sqlite)
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [r[0] for r in rows]
    finally:
        conn.close()
    # v1 = Stage-3 app-state; v2 = Stage-4 name_resolutions (resolve_name);
    # v3 = Stage-4 cbs_page_snapshots (CbsOnPageProvider read surface).
    assert versions == [1, 2, 3]


def test_duckdb_can_attach_and_read_app_sqlite(wh: Warehouse) -> None:
    """DuckDB reads identity live from the ATTACHed app.sqlite — no data duplicated (§2.4)."""
    _seed_player(wh.app_sqlite)
    con = wh._duckdb_connect()
    try:
        rows = con.execute("SELECT player_id FROM app.players").fetchall()
    finally:
        con.close()
    assert rows == [("gsis:1",)]


def test_base_app_import_does_not_require_the_data_extra() -> None:
    """The base ($0) install must start the API without the `data` extra. Importing the app
    (which now imports the warehouse) must NOT eagerly import rapidfuzz/duckdb/polars — those
    are deferred to actual materialization / fuzzy matching, not module load. A fresh
    subprocess is used so pytest's own already-imported modules don't mask a regression."""
    import subprocess
    import sys

    code = (
        "import sys, jaaffl.api.app; "
        "print(','.join(sorted(m for m in ('rapidfuzz', 'duckdb', 'polars') if m in sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", f"data-extra modules imported at app load: {out.stdout!r}"


# --- snapshot_league -----------------------------------------------------------------


def test_snapshot_league_persists_a_settings_row(wh: Warehouse) -> None:
    snap_id = wh.snapshot_league(settings("L1"))
    assert snap_id is not None
    rows = _snapshot_rows(wh.app_sqlite)
    assert len(rows) == 1
    league_id, kind, payload, content_hash = rows[0]
    assert league_id == "L1"
    assert kind == "settings"
    assert len(content_hash) == 64 and all(c in "0123456789abcdef" for c in content_hash)


def test_snapshot_league_dedups_byte_identical_repush(wh: Warehouse) -> None:
    first = wh.snapshot_league(settings("L1"))
    second = wh.snapshot_league(settings("L1"))  # same payload
    assert first is not None
    assert second is None  # ux_snap_dedup dropped the identical re-push
    assert len(_snapshot_rows(wh.app_sqlite)) == 1


def test_snapshot_league_keeps_distinct_payloads(wh: Warehouse) -> None:
    wh.snapshot_league(settings("L1", name="Original"))
    wh.snapshot_league(settings("L1", name="Renamed"))  # a real change → new snapshot
    assert len(_snapshot_rows(wh.app_sqlite)) == 2


def test_snapshot_league_stores_the_raw_cbs_payload(wh: Warehouse) -> None:
    wh.snapshot_league(settings("L1", scoring_format="Standard"))
    payload = _snapshot_rows(wh.app_sqlite)[0][2]
    assert '"scoring_format":"Standard"' in payload.replace(" ", "")


def test_snapshot_league_content_hash_matches_stored_payload(wh: Warehouse) -> None:
    wh.snapshot_league(settings("L1"))
    _, _, payload, content_hash = _snapshot_rows(wh.app_sqlite)[0]
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == content_hash


# --- parquet helpers -----------------------------------------------------------------


def test_write_parquet_writes_under_data_parquet(wh: Warehouse) -> None:
    df = pl.DataFrame({"player_id": ["gsis:1"], "mu": [220.5]})
    path = wh.write_parquet("nflverse/player_stats_2026", df)
    assert path == wh.parquet_dir / "nflverse" / "player_stats_2026.parquet"
    assert path.exists()


def test_scan_parquet_roundtrips_via_duckdb(wh: Warehouse) -> None:
    df = pl.DataFrame({"player_id": ["gsis:1", "gsis:2"], "mu": [220.5, 180.0]})
    wh.write_parquet("nflverse/player_stats_2026", df)
    scanned = wh.scan_parquet("nflverse/player_stats_2026").sort("player_id")
    assert scanned.to_dicts() == df.sort("player_id").to_dicts()


def test_parquet_name_rejects_traversal(wh: Warehouse) -> None:
    with pytest.raises(ValueError):
        wh.write_parquet("../escape", pl.DataFrame({"a": [1]}))


# --- rebuildability (make warehouse) -------------------------------------------------


def test_rebuild_reproduces_duckdb_and_never_loses_sqlite(wh: Warehouse) -> None:
    """DoD: delete warehouse.duckdb + parquet/, run `make warehouse`, get identical
    materialized output for fixed inputs; app.sqlite is the ONLY unrecoverable loss."""
    # Durable app state (crown jewels) lives in SQLite.
    wh.snapshot_league(settings("L1"))
    _seed_player(wh.app_sqlite)
    fixed = pl.DataFrame({"player_id": ["gsis:1"], "mu": [220.5]})
    wh.write_parquet("nflverse/player_stats_2026", fixed)

    tables_before = wh.duckdb_tables()
    scan_before = wh.scan_parquet("nflverse/player_stats_2026").to_dicts()
    sqlite_bytes = wh.app_sqlite.read_bytes()

    # Disposable stores deleted — simulating `make warehouse` clean.
    wh.warehouse_duckdb.unlink()
    (wh.parquet_dir / "nflverse" / "player_stats_2026.parquet").unlink()
    assert not wh.warehouse_duckdb.exists()

    # Fixed upstream re-provided (Stage 4 re-pull); rebuild from Parquet + SQLite.
    wh.write_parquet("nflverse/player_stats_2026", fixed)
    rebuild_warehouse(wh.data_dir)

    assert wh.warehouse_duckdb.exists()
    assert wh.duckdb_tables() == tables_before
    assert wh.scan_parquet("nflverse/player_stats_2026").to_dicts() == scan_before
    # app.sqlite untouched by the rebuild; its rows survived the disposable-store wipe.
    assert wh.app_sqlite.read_bytes() == sqlite_bytes
    assert len(_snapshot_rows(wh.app_sqlite)) == 1


# --- snapshot_draft_state ------------------------------------------------------------


def _draft_state(league_id: str = "L1") -> DraftState:
    return DraftState(
        league_id=league_id,
        current_overall_pick=3,
        picks=[
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="T1", player_id="gsis:1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="T2", player_id="gsis:2"),
        ],
        complete=True,
    )


def test_snapshot_draft_state_writes_a_per_draft_export(wh: Warehouse) -> None:
    out = wh.snapshot_draft_state(_draft_state("L1"), captured_at="2026-08-30T18:00:00Z")
    assert out.is_dir()
    assert out.parent == wh.snapshots_dir
    assert (out / "final_state.json").exists()
    assert (out / "events.parquet").exists()


def test_snapshot_draft_state_sanitizes_league_id(wh: Warehouse) -> None:
    """A league_id can never escape the snapshots dir (no path traversal in derived names)."""
    out = wh.snapshot_draft_state(_draft_state("../../etc/L1"), captured_at="2026-08-30T18:00:00Z")
    assert wh.snapshots_dir in out.parents
