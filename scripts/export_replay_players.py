#!/usr/bin/env python
"""Export the crosswalk slice the CBS replay test needs, so CI can resolve ids OFFLINE.

``backend/tests/test_cbs_replay.py`` drives every frame of a real captured draft through the
pipeline. CBS picks are ID-ONLY (docs/research/cbs-draft-protocol.md section 3), so the test
cannot mask a drafted player without a ``cbs:<id>`` -> canonical-id crosswalk — and the real
crosswalk is seeded from the network (the free DynastyProcess table, via precompute). This
script freezes just the rows those ids need into a committed fixture.

What lands in the fixture is public, non-personal data: NFL player names, positions, and teams,
keyed by CBS's own numeric player id. The raw captures' personal data (owner ids, team display
names, the owner's email) is never read here — only the CBS player ids are, and those are not
personal data (protocol doc section 5).

Usage (from the repo root, after a precompute run has seeded the crosswalk)::

    .venv/Scripts/python.exe scripts/export_replay_players.py
    .venv/Scripts/python.exe scripts/export_replay_players.py --db data/app.sqlite
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "app.sqlite"
FIXTURE_DIR = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs"
DEFAULT_OUT = REPO_ROOT / "backend" / "tests" / "fixtures" / "cbs_replay_players.json"

# The committed replay corpora whose CBS ids must resolve.
EVENT_FILES = ["full-draft.events.json"]
SNAPSHOT_FILES = ["late-join.snapshot.json", "subscribe-complete.json"]
DELTA_FILES = ["full-draft.deltas.jsonl", "late-join.deltas.jsonl"]


def _strip(body: str) -> str:
    return body.rstrip("\x00").strip()


def cbs_ids_from_events(path: Path) -> set[str]:
    """parse.ts's own output: pick_made events carry ``cbs_player_id``."""
    ids: set[str] = set()
    for event in json.loads(path.read_text(encoding="utf-8")):
        cbs_id = (event.get("data") or {}).get("cbs_player_id")
        if cbs_id:
            ids.add(str(cbs_id))
    return ids


def cbs_ids_from_snapshot(path: Path) -> set[str]:
    """A subscribe/response's per-team board: ``fullstate.teams.<id>.players.<playerid>``."""
    envelope = json.loads(path.read_text(encoding="utf-8"))
    frame = json.loads(_strip(envelope["payload"]["body"]))
    teams = ((frame.get("payload") or {}).get("fullstate") or {}).get("teams") or {}
    return {
        str(record.get("id") or pid)
        for team in teams.values()
        for pid, record in ((team or {}).get("players") or {}).items()
    }


def cbs_ids_from_deltas(path: Path) -> set[str]:
    """A JSONL replay sequence: every ``payload.picks[].playerid``."""
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        frame = json.loads(_strip(json.loads(line)["payload"]["body"]))
        for pick in (frame.get("payload") or {}).get("picks") or []:
            if pick.get("playerid") is not None:
                ids.add(str(pick["playerid"]))
    return ids


def collect_ids() -> set[str]:
    ids: set[str] = set()
    for name in EVENT_FILES:
        path = FIXTURE_DIR / name
        if path.exists():
            ids |= cbs_ids_from_events(path)
    for name in SNAPSHOT_FILES:
        path = FIXTURE_DIR / name
        if path.exists():
            ids |= cbs_ids_from_snapshot(path)
    for name in DELTA_FILES:
        path = FIXTURE_DIR / name
        if path.exists():
            ids |= cbs_ids_from_deltas(path)
    return ids


def lookup(db: Path, ids: set[str]) -> dict[str, dict]:
    conn = sqlite3.connect(db)
    try:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            "SELECT x.source_id, x.canonical_id, p.name, p.position, p.nfl_team"
            "  FROM id_crosswalk x JOIN players p ON p.player_id = x.canonical_id"
            f" WHERE x.source = 'cbs' AND x.source_id IN ({placeholders})",
            sorted(ids),
        ).fetchall()
    finally:
        conn.close()
    return {
        str(source_id): {
            "canonical_id": canonical_id,
            "name": name,
            "position": position,
            "nfl_team": nfl_team,
        }
        for source_id, canonical_id, name, position, nfl_team in rows
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[replay-players] warehouse not found: {args.db}", file=sys.stderr)
        print("[replay-players] run a precompute first so the crosswalk is seeded", file=sys.stderr)
        return 1

    ids = collect_ids()
    if not ids:
        print("[replay-players] no CBS ids found in the committed replay fixtures", file=sys.stderr)
        return 1
    players = lookup(args.db, ids)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "_comment": (
            "Crosswalk slice for backend/tests/test_cbs_replay.py -- CBS player id -> canonical "
            "id + public NFL name/position/team. Generated by scripts/export_replay_players.py "
            "from the seeded crosswalk so the replay test resolves ids with no network. Contains "
            "no personal data: CBS player ids and NFL player names are public."
        ),
        "source": "id_crosswalk (source='cbs') joined to players -- seeded from DynastyProcess",
        "cbs_ids_in_fixtures": len(ids),
        "resolved": len(players),
        "players": dict(sorted(players.items(), key=lambda kv: int(kv[0]))),
    }
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")

    missing = len(ids) - len(players)
    print(f"[replay-players] wrote {args.out.relative_to(REPO_ROOT)}")
    print(f"[replay-players] {len(players)}/{len(ids)} CBS ids resolved ({missing} unlinked)")
    if missing:
        print(
            "[replay-players] unlinked ids are expected to be K/DST: nflverse labels kickers 'PK' "
            "and team defenses as '<City> Defense', neither of which the free crosswalk links.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
