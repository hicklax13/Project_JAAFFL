#!/usr/bin/env python
"""Pre-draft preflight: can the board actually fill every STARTING slot?

Run this the morning of the draft. It builds the REAL DraftContext through the same
``build_registry_context_source`` wiring the live service uses, then reports how many draftable
players (players carrying a projection) exist at each position and FAILS (exit 1) if any startable
position is missing.

Why this exists: two positions were silently missing from the live board and were found only by
accident. nflverse's ff_playerids spells kicker ``PK`` while the domain spells it ``K``, so all
151 rostered kickers were dropped by an un-aliased position gate; and that table carries no
team-defense rows at all, so there were zero DSTs. In both cases the loader logged a large but
normal-looking skip count (~8,000 IDP rows), which is exactly why neither was noticed. The board
looked healthy and was not.

A hard failure is SAFE here and nowhere else: hours before the draft there is still time to fix
it. The equivalent check inside ``engine.precompute`` only logs a warning, because that code can
re-run mid-draft after a service restart, where an incomplete board still beats no board.

NETWORK step: pulls the free nflverse + FFC feeds (the same ones a real precompute pulls).

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/preflight.py
    .venv/Scripts/python.exe scripts/preflight.py --league-id jaaffl-2026
    .venv/Scripts/python.exe scripts/preflight.py --seed      # re-seed the crosswalk first
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from jaaffl.config import Settings, get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.engine.precompute import build_registry_context_source
from jaaffl.league.coverage import board_coverage_gaps, startable_positions


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--league-id",
        default="jaaffl-2026",
        help="League to build a context for (default: jaaffl-2026).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=settings.jaaffl_data_dir,
        help="App data dir holding app.sqlite (default: jaaffl_data_dir).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Re-seed the crosswalk from nflverse first (people + team defenses).",
    )
    args = parser.parse_args(argv)

    warehouse = Warehouse(args.data_dir)
    warehouse.init()
    crosswalk = Crosswalk(warehouse.app_sqlite)

    if args.seed:
        from jaaffl.providers.nflverse import NflreadpyProvider

        seeded = NflreadpyProvider(crosswalk=crosswalk).seed_crosswalk()
        print(f"[preflight] seeded {seeded} players (people + team defenses)")

    print(f"[preflight] building the real draft context for {args.league_id} ...")
    source = build_registry_context_source(
        Settings(jaaffl_data_dir=args.data_dir), warehouse=warehouse, crosswalk=crosswalk
    )
    context = source(args.league_id)
    if context is None:
        print(
            "[preflight] FAIL: no context could be built (empty universe or no projections).",
            file=sys.stderr,
        )
        return 1

    board = {pid: context.position[pid] for pid in context.mu if pid in context.position}
    counts = collections.Counter(str(position) for position in board.values())
    required = {str(position) for position in startable_positions(context.settings)}

    print(f"[preflight] draftable players on the board: {len(board)}")
    for position in sorted(counts, key=lambda p: (p not in required, p)):
        tag = "start" if position in required else "bench-only"
        print(f"[preflight]   {position:<4} {counts[position]:>5}  ({tag})")

    gaps = board_coverage_gaps(context.settings, board)
    if gaps:
        missing = ", ".join(str(position) for position in gaps)
        print(f"[preflight] FAIL: no draftable players at {missing}", file=sys.stderr)
        print(
            "[preflight] the engine cannot recommend or roster these — check the provider"
            " position codes (a source may have renamed one) before drafting.",
            file=sys.stderr,
        )
        return 1

    print(f"[preflight] OK: every startable position ({', '.join(sorted(required))}) is fillable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
