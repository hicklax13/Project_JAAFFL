#!/usr/bin/env python
"""Measure the per-position projection σ that anchors the engine's risk band (§3.1 step 3).

``engine/precompute.py::_DEFAULT_SIGMA_FLOOR`` used to be a flat ~50-for-everyone v1 placeholder.
This script is where its replacement comes from, so the constants are auditable rather than magic:
it projects each season's nflverse xEP forward one year, scores both the projection and the
realized season under the OWNER-VERIFIED JAAFFL map, and reports the error distribution by
position. The SD column is the drift σ; the bias column is what picks the μ estimator.

It also settles ``league/xep.py``'s season-sum-vs-rate choice with data: the season SUM is
near-unbiased while ``per-game rate × 17`` systematically overshoots, on every year-pair tested.

READ-ONLY. It prints a table and writes nothing — the constants are copied over by hand after a
human reads the numbers, exactly like the other E-track calibration CLIs.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/measure_projection_sigma.py
    .venv/Scripts/python.exe scripts/measure_projection_sigma.py --pairs 2024:2025 2023:2024
"""

from __future__ import annotations

import argparse
import collections
import statistics
import sys
from dataclasses import dataclass

from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.league.defaults import jaaffl_scoring
from jaaffl.league.xep import GAMES_HORIZON, MAX_FANTASY_WEEK, MIN_GAMES, expected_points_source

_POSITIONS = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True, slots=True)
class Errors:
    """Realized-minus-projected league points for one position under one estimator."""

    season_sum: list[float]
    rate_times_horizon: list[float]


def _settings() -> LeagueSettings:
    """A minimal LeagueSettings carrying only what scoring needs — the roster is irrelevant here
    and config/league.json is immutable, so nothing is read from it."""
    rules, tiers, bonuses = jaaffl_scoring()
    return LeagueSettings(
        league_id="sigma-measurement",
        team_count=12,
        roster_slots=[RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1)],
        scoring=rules,
        scoring_tiers=tiers,
        scoring_bonuses=bonuses,
    )


def _season(year: int, settings: LeagueSettings):
    """``(position, xEP projection, realized points)`` for one season, keyed canonically.

    Realized points are folded with the SAME row splitter and scorer the projection uses
    (``league.xep`` internals, reached into deliberately), so projection and outcome can never
    drift apart through a second, subtly different scoring path.
    """
    import nflreadpy as nfl

    from jaaffl.league import xep

    frame = nfl.load_ff_opportunity(seasons=[year])
    position = {
        f"gsis:{row['player_id']}": Position(row["position"])
        for row in frame.iter_rows(named=True)
        if row.get("player_id") and row.get("position") in _POSITIONS
    }
    projected = expected_points_source(frame, settings=settings, position=position, drift_sigma={})

    realized: dict[str, float] = collections.defaultdict(float)
    for row in frame.iter_rows(named=True):
        pid = f"gsis:{row.get('player_id')}"
        week = row.get("week")
        if pid not in position or week is None or not 1 <= int(week) <= MAX_FANTASY_WEEK:
            continue
        _, actual = xep._stat_lines(row)  # noqa: SLF001 — deliberate: one scorer, not two
        realized[pid] += xep._points(actual, settings, position[pid])  # noqa: SLF001
    return position, projected, dict(realized)


def measure(year_from: int, year_to: int, settings: LeagueSettings) -> dict[str, Errors]:
    position_a, projected, _ = _season(year_from, settings)
    _, _, realized_b = _season(year_to, settings)
    out: dict[str, Errors] = {}
    for pos in _POSITIONS:
        sums, rates = [], []
        for pid, points in projected.points.items():
            if position_a[pid].value != pos or pid not in realized_b:
                continue  # absent from the next season's universe entirely → not projectable
            sums.append(realized_b[pid] - points)
            rates.append(realized_b[pid] - points / projected.games[pid] * GAMES_HORIZON)
        out[pos] = Errors(season_sum=sums, rate_times_horizon=rates)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=["2024:2025", "2023:2024"],
        help="FROM:TO season pairs to measure (default: the two used for the shipped constants)",
    )
    args = parser.parse_args(argv)

    settings = _settings()
    per_position: dict[str, list[float]] = collections.defaultdict(list)
    print(f"min_games={MIN_GAMES}  games_horizon={GAMES_HORIZON}  weeks<= {MAX_FANTASY_WEEK}\n")
    for pair in args.pairs:
        year_from, year_to = (int(part) for part in pair.split(":"))
        print(f"=== {year_from} xEP  ->  realized {year_to} ===")
        for pos, err in measure(year_from, year_to, settings).items():
            s, r = err.season_sum, err.rate_times_horizon
            if not s:
                print(f"  {pos}: no overlapping players")
                continue
            sd = statistics.pstdev(s)
            per_position[pos].append(sd)
            print(
                f"  {pos}: n={len(s):3d}"
                f" | season-sum bias={statistics.mean(s):7.1f} sd={sd:6.1f}"
                f" | rate*{GAMES_HORIZON} bias={statistics.mean(r):7.1f}"
                f" sd={statistics.pstdev(r):6.1f}"
            )
        print()

    print("=== drift σ to paste into engine/precompute.py::_DEFAULT_SIGMA_FLOOR ===")
    for pos in _POSITIONS:
        if per_position[pos]:
            print(f"  Position.{pos}: {statistics.mean(per_position[pos]):.1f},")
    print("\n(K/DST are NOT measurable here — ffopportunity has no DST rows.)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
