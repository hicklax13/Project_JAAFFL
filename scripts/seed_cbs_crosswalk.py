#!/usr/bin/env python
"""Seed the CBS id -> canonical player crosswalk from a real record-mode capture (protocol doc
§5, ``docs/research/cbs-draft-protocol.md``).

CBS's live draft-room ``picks/completed`` frames are ID-only: no name, position, or NFL team
rides along with a pick (see ``jaaffl.ingest.resolve.resolve_pick_ids``, which needs exactly this
seeded crosswalk to mask a real CBS-sourced pick from the candidate pool). This script mines the
id -> identity mapping from the SAME record-mode capture's page content (player-list rows, player
page links, snippet links -- ``jaaffl.data.cbs_extract`` owns the actual regex extraction; this
script owns the raw-capture file walking + crosswalk resolution) and seeds ``id_crosswalk`` rows
via :meth:`Crosswalk.resolve_or_link`.

Reads the git-ignored raw captures under ``apps/extension/fixtures/cbs/*.jsonl`` (owner
record-mode session) by default -- the same directory ``scripts/redact_cbs_fixtures.py`` reads.
Frames are one JSON envelope per line, ``{"kind": ..., "payload": {...}}``; the player HTML lives
in ``dom-snapshot`` envelopes' ``payload.html`` and ``fetch``/``xhr`` envelopes' ``payload.body``
(never in the ``ws-message``/``ws-send`` draft-protocol frames, which is why parsing those isn't
needed here). A line that fails ``json.loads`` (a known split-write-race corruption -- protocol
doc §1) is not skipped: its manually-unescaped raw text is regexed too, since the extraction
regexes work fine over raw (still JSON-escaped) text once the escapes are undone.

Re-runnable: id_crosswalk links persist (``ON CONFLICT ... DO UPDATE`` inside
:meth:`Crosswalk.link`, honoring manual > deterministic > fuzzy precedence), and a fuzzy result is
cached for O(1) re-lookup, so running this again after a new capture only adds/upgrades links.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/seed_cbs_crosswalk.py                  # dry-run (default)
    .venv/Scripts/python.exe scripts/seed_cbs_crosswalk.py --write          # persist
    .venv/Scripts/python.exe scripts/seed_cbs_crosswalk.py --raw-dir PATH --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from jaaffl.config import get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.data.cbs_extract import CbsPlayer, extract_cbs_players


def _unescape_line(line: str) -> str:
    """Best-effort manual unescape for a raw capture line that failed ``json.loads`` -- undoes
    the same escapes JSON parsing would have (protocol doc §1's known split-write-race
    corruption), so the embedded HTML still matches the same literal-quote regexes a cleanly
    parsed line would."""
    return (
        line.replace('\\"', '"')
        .replace("\\/", "/")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def iter_capture_texts(raw_dir: Path) -> Iterator[str]:
    """Yield every dom-snapshot HTML / fetch|xhr response body found in ``raw_dir``'s ``*.jsonl``
    captures -- the only text blobs protocol doc §5's three id->identity sources ever appear in."""
    for path in sorted(raw_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    envelope = json.loads(line)
                except json.JSONDecodeError:
                    yield _unescape_line(line)
                    continue
                payload = envelope.get("payload")
                if not isinstance(payload, dict):
                    continue
                kind = envelope.get("kind")
                if kind == "dom-snapshot":
                    html = payload.get("html")
                    if isinstance(html, str):
                        yield html
                elif kind in ("fetch", "xhr"):
                    body = payload.get("body")
                    if isinstance(body, str):
                        yield body


def _yield_summary(players: dict[str, CbsPlayer]) -> str:
    total = len(players)
    named = sum(1 for p in players.values() if p.name)
    with_pos_team = sum(1 for p in players.values() if p.position and p.nfl_team)
    pct_named = (named / total) if total else 0.0
    pct_pt = (with_pos_team / total) if total else 0.0
    return (
        f"{total} distinct CBS id(s) -- {named} named ({pct_named:.0%}), "
        f"{with_pos_team} with position+team ({pct_pt:.0%})"
    )


def _resolve_dry_run(crosswalk: Crosswalk, players: dict[str, CbsPlayer]) -> str:
    """Read-only preview: no crosswalk writes. ``Crosswalk.resolve`` is a pure indexed lookup, so
    this only reports links already persisted by a PRIOR ``--write`` run."""
    already_linked = 0
    not_yet_linked = 0
    no_position = 0
    for cbs_id, player in players.items():
        if crosswalk.resolve("cbs", cbs_id) is not None:
            already_linked += 1
        elif player.position is None:
            no_position += 1
        else:
            not_yet_linked += 1
    return (
        f"{already_linked} already linked, "
        f"{not_yet_linked} not yet linked (would attempt with --write), "
        f"{no_position} unresolvable (no position extracted, can never be attempted)"
    )


def _resolve_write(crosswalk: Crosswalk, players: dict[str, CbsPlayer]) -> str:
    """Persist: seed/upgrade an ``id_crosswalk`` link for every triple that has a position
    (``resolve_or_link`` requires one) via Stage A/B (deterministic hit, else fuzzy name+pos+team
    match at/above τ). A miss is never guessed -- it stays unresolved for a later manual/deter-
    ministic pass."""
    linked = 0
    newly_linked = 0
    unresolved = 0
    no_position = 0
    for cbs_id, player in players.items():
        if player.position is None:
            no_position += 1
            continue
        already = crosswalk.resolve("cbs", cbs_id) is not None
        canonical = crosswalk.resolve_or_link(
            "cbs", cbs_id, name=player.name, position=player.position, nfl_team=player.nfl_team
        )
        if canonical is None:
            unresolved += 1
            continue
        linked += 1
        if not already:
            newly_linked += 1
    return (
        f"{linked} linked ({newly_linked} newly linked this run), "
        f"{unresolved} unresolved (no fuzzy match at/above threshold), "
        f"{no_position} unresolvable (no position extracted, never attempted)"
    )


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=settings.jaaffl_recordings_dir,
        help="Directory of raw *.jsonl record-mode captures (default: jaaffl_recordings_dir).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=settings.jaaffl_data_dir,
        help="App data dir holding app.sqlite (default: jaaffl_data_dir).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist crosswalk links via resolve_or_link (default: dry-run preview only).",
    )
    args = parser.parse_args(argv)

    if not args.raw_dir.is_dir():
        print(f"[seed-cbs] raw capture dir not found: {args.raw_dir}", file=sys.stderr)
        print(
            "[seed-cbs] (expected on a machine without the git-ignored raw session)",
            file=sys.stderr,
        )
        return 1
    raw_files = sorted(args.raw_dir.glob("*.jsonl"))
    if not raw_files:
        print(f"[seed-cbs] no *.jsonl captures in {args.raw_dir}", file=sys.stderr)
        return 1

    print(f"[seed-cbs] scanning {len(raw_files)} raw capture file(s) in {args.raw_dir} ...")
    players = extract_cbs_players(iter_capture_texts(args.raw_dir))
    print(f"[seed-cbs] extraction yield: {_yield_summary(players)}")
    if not players:
        print("[seed-cbs] nothing extracted -- capture shape may have changed", file=sys.stderr)
        return 1

    warehouse = Warehouse(args.data_dir)
    crosswalk = Crosswalk(warehouse.app_sqlite)

    if args.write:
        print(f"[seed-cbs] resolution (--write): {_resolve_write(crosswalk, players)}")
        print(f"[seed-cbs] wrote crosswalk links to {warehouse.app_sqlite}")
    else:
        print(f"[seed-cbs] resolution preview (dry-run): {_resolve_dry_run(crosswalk, players)}")
        print("[seed-cbs] dry-run -- pass --write to persist new crosswalk links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
