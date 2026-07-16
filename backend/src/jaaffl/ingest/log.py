"""Append-only draft-event log + crash-safe fold (plan §2.3 / §2.6).

Of everything the system holds, only the live pick stream is unrebuildable — so it gets
ACID durability with an append-before-compute discipline: ``append_event`` commits (WAL +
``synchronous=FULL``, fsync'd) BEFORE any downstream work is scheduled, and ``fold_state``
is a pure, deterministic left-fold — no I/O, no wall clock — so identical logs yield
identical ``DraftState`` on any machine, including after a kill -9 restart.

Note: the ``source`` CHECK uses the wire vocabulary (``ws|framework|dom|paste``, §5.8);
plan §2.3's DDL spelled the paste fallback ``'manual'`` — reconciled here to one
vocabulary end-to-end.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from jaaffl.domain import DraftEvent, DraftEventType, DraftPick, DraftState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_event_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id   TEXT    NOT NULL,
    event_type  TEXT    NOT NULL
                  CHECK (event_type IN ('league_settings','draft_state',
                                        'on_the_clock','pick_made','draft_complete')),
    pick_number INTEGER,
    payload     TEXT    NOT NULL CHECK (json_valid(payload)),
    source      TEXT    CHECK (source IN ('ws','framework','dom','paste')),
    captured_at TEXT    NOT NULL,
    ingested_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_event_pick
    ON draft_event_log(league_id, event_type, pick_number) WHERE pick_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_event_league_seq
    ON draft_event_log(league_id, seq);
"""


class LoggedEvent(NamedTuple):
    seq: int
    league_id: str
    event_type: str
    pick_number: int | None
    data: dict
    source: str | None
    captured_at: str


def open_log(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the app SQLite db with the §2.3 durability pragmas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    return conn


def append_event(
    conn: sqlite3.Connection,
    event: DraftEvent,
    *,
    pick_number: int | None,
    source: str | None,
    captured_at: str,
) -> int | None:
    """Durably append ONE normalized event; return its seq, or None if de-duped.

    ``INSERT OR IGNORE`` against ``ux_event_pick``: the three probes may deliver the same
    numbered event — first write wins. Commits (``synchronous=FULL``) BEFORE returning, so
    the pick is on disk before any engine work is scheduled.
    """
    overall = event.data.get("overall")
    if (
        event.event_type == DraftEventType.PICK_MADE
        and pick_number is not None
        and overall is not None
        and overall != pick_number
    ):
        raise ValueError(
            f"corrupt pick event: envelope pick_number={pick_number} != data.overall={overall}"
        )
    cur = conn.execute(
        "INSERT OR IGNORE INTO draft_event_log"
        " (league_id, event_type, pick_number, payload, source, captured_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            event.league_id,
            str(event.event_type),
            pick_number,
            json.dumps(event.data, sort_keys=True),
            source,
            captured_at,
        ),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def read_events(
    conn: sqlite3.Connection, league_id: str, *, through_seq: int | None = None
) -> list[LoggedEvent]:
    """All events for a league in ascending seq order (full history for replay)."""
    sql = (
        "SELECT seq, league_id, event_type, pick_number, payload, source, captured_at"
        " FROM draft_event_log WHERE league_id = ?"
    )
    params: list = [league_id]
    if through_seq is not None:
        sql += " AND seq <= ?"
        params.append(through_seq)
    sql += " ORDER BY seq"
    return [
        LoggedEvent(seq, lid, etype, pick, json.loads(payload), source, captured)
        for seq, lid, etype, pick, payload, source, captured in conn.execute(sql, params)
    ]


class DraftLog:
    """Path-bound convenience over the log functions.

    Opens a fresh connection per operation: ingest is low-rate (≤ ~1 pick / few seconds),
    WAL makes opens cheap, and per-call connections are trivially safe across FastAPI's
    threadpool without shared-connection locking.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        event: DraftEvent,
        *,
        pick_number: int | None,
        source: str | None,
        captured_at: str,
    ) -> int | None:
        conn = open_log(self._path)
        try:
            return append_event(
                conn, event, pick_number=pick_number, source=source, captured_at=captured_at
            )
        finally:
            conn.close()

    def events(self, league_id: str) -> list[LoggedEvent]:
        conn = open_log(self._path)
        try:
            return read_events(conn, league_id)
        finally:
            conn.close()

    def state(self, league_id: str) -> DraftState:
        """Fold the full log for a league; raises ValueError when the log is empty."""
        return fold_state(self.events(league_id))


def fold_state(events: Iterable[LoggedEvent]) -> DraftState:
    """Pure, deterministic left-fold of the log into a DraftState. No I/O, no clock.

    Reducer semantics (§2.6): league_settings binds identity; draft_state is an
    authoritative full re-sync; on_the_clock advances the clock; pick_made appends
    idempotently per ``overall``; draft_complete marks terminal. Draft order is only ever
    what the room reported — never synthesized from team count.
    """
    state: DraftState | None = None
    for ev in events:
        if state is None:
            state = DraftState(league_id=ev.league_id, current_overall_pick=1)
        if ev.event_type == DraftEventType.LEAGUE_SETTINGS:
            my_team = ev.data.get("my_team_id")
            if my_team:
                state = state.model_copy(update={"my_team_id": my_team})
        elif ev.event_type == DraftEventType.DRAFT_STATE:
            snap = DraftState.model_validate({"league_id": ev.league_id, **ev.data})
            update: dict = {
                "picks": snap.picks,
                "current_overall_pick": snap.current_overall_pick,
                "on_the_clock_team_id": snap.on_the_clock_team_id,
                "available_player_ids": snap.available_player_ids,
            }
            if snap.my_team_id:
                update["my_team_id"] = snap.my_team_id
            state = state.model_copy(update=update)
        elif ev.event_type == DraftEventType.ON_THE_CLOCK:
            state = state.model_copy(
                update={
                    "on_the_clock_team_id": ev.data.get("team_id"),
                    "current_overall_pick": int(ev.data["current_overall_pick"]),
                }
            )
        elif ev.event_type == DraftEventType.PICK_MADE:
            pick = DraftPick.model_validate(ev.data)
            if all(p.overall != pick.overall for p in state.picks):
                available = state.available_player_ids
                if available is not None and pick.player_id:
                    available = [a for a in available if a != pick.player_id]
                state = state.model_copy(
                    update={
                        "picks": [*state.picks, pick],
                        "current_overall_pick": max(state.current_overall_pick, pick.overall + 1),
                        "available_player_ids": available,
                    }
                )
        elif ev.event_type == DraftEventType.DRAFT_COMPLETE:
            state = state.model_copy(update={"complete": True})
    if state is None:
        raise ValueError("fold_state: empty event log")
    return state
