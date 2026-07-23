#!/usr/bin/env python
"""E1 — measure the RB/WR flex split from live FFC ADP (plan §12.3 item 1, Track J).

Highest-value pre-draft calibration. Ranks RB+WR by non-PPR 12-team FFC ADP, takes the top
``12 dedicated RB + 36 dedicated WR + 12 flex`` startable, and reads the flex composition off the
overflow (see ``jaaffl.calibrate.flex_split.measure_flex_split`` — unit-tested offline). Writes the
result to ``EngineParams.flex_split`` in ``config/engine.json``.

NETWORK step, run pre-draft: pulls the free nflverse player universe (positions) + FFC ADP. The
current draft season is the only queryable FFC year.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/calibrate_flex_split.py --season 2026          # dry-run
    .venv/Scripts/python.exe scripts/calibrate_flex_split.py --season 2026 --write  # persist
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from jaaffl.calibrate.flex_split import flex_pool_counts, measure_flex_split
from jaaffl.config import get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import LeagueSettings
from jaaffl.league.constitution import resolve_league_settings
from jaaffl.providers.ffc import FantasyFootballCalculatorProvider
from jaaffl.providers.nflverse import NflreadpyProvider

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _dedicated_counts(league: LeagueSettings) -> tuple[int, int, int]:
    """Derive the league-wide dedicated RB / WR / flex slot counts from the (immutable) roster:
    ``team_count × per-team slot count``. For this league: 12·RB1 = 12, 12·WR3 = 36, 12·flex1 = 12."""
    slots = {s.slot: s.count for s in league.roster_slots}
    n = league.team_count
    return n * slots.get("RB", 1), n * slots.get("WR", 3), n * slots.get("WR/RB", 1)


def _write_flex_split(config_path: Path, split: dict[str, int]) -> None:
    """Replace only the ``flex_split`` value in engine.json, leaving the rest byte-for-byte."""
    text = config_path.read_text(encoding="utf-8")
    replacement = f'"flex_split": {{ "RB": {split["RB"]}, "WR": {split["WR"]} }}'
    new_text, count = re.subn(
        r'"flex_split"\s*:\s*\{[^}]*\}', replacement, text, count=1
    )
    if count != 1:
        raise SystemExit(f"could not locate a flex_split entry in {config_path}")
    config_path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E1: measure the RB/WR flex split from FFC ADP."
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Draft season (default: jaaffl_season).",
    )
    parser.add_argument(
        "--league-id", default=None, help="League id (default: jaaffl_league_id)."
    )
    parser.add_argument(
        "--config", type=Path, default=_REPO_ROOT / "config" / "engine.json"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist flex_split to the config (default: dry-run).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    season = args.season or settings.jaaffl_season
    if not season:
        parser.error("no season: pass --season or set jaaffl_season")
    league = resolve_league_settings(args.league_id or settings.jaaffl_league_id)
    dedicated_rb, dedicated_wr, flex_slots = _dedicated_counts(league)

    warehouse = Warehouse(settings.jaaffl_data_dir)
    crosswalk = Crosswalk(warehouse.app_sqlite)

    print(
        f"[E1] seeding the nflverse player universe (season {season}) ...",
        file=sys.stderr,
    )
    nflverse = NflreadpyProvider(crosswalk=crosswalk)
    nflverse.seed_crosswalk()
    universe = {p.player_id: p for p in nflverse.players(season)}
    print(f"[E1] universe: {len(universe)} players", file=sys.stderr)

    print("[E1] pulling FFC ADP (non-PPR, 12-team) ...", file=sys.stderr)
    ffc = FantasyFootballCalculatorProvider(settings, crosswalk)
    adp = ffc.adp(season)
    print(
        f"[E1] FFC ADP resolved to canonical ids: {len(adp)} players", file=sys.stderr
    )

    rows = [
        (universe[cid].position, rec.adp)
        for cid, rec in adp.items()
        if cid in universe and rec.adp is not None
    ]
    pool = dedicated_rb + dedicated_wr + flex_slots
    rb_in_top, wr_in_top = flex_pool_counts(
        rows,
        dedicated_rb=dedicated_rb,
        dedicated_wr=dedicated_wr,
        flex_slots=flex_slots,
    )
    split = measure_flex_split(
        rows,
        dedicated_rb=dedicated_rb,
        dedicated_wr=dedicated_wr,
        flex_slots=flex_slots,
    )

    print(f"[E1] top-{pool} RB/WR pool composition: RB {rb_in_top}, WR {wr_in_top}")
    print(
        f"[E1] of {len(rows)} resolved RB/WR "
        f"-> flex split RB {split['RB']} / WR {split['WR']} "
        f"(dedicated RB {dedicated_rb}, WR {dedicated_wr}, flex {flex_slots})"
    )

    if args.write:
        _write_flex_split(args.config, split)
        print(f"[E1] wrote flex_split to {args.config}")
    else:
        print("[E1] dry-run — pass --write to persist to config/engine.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
