#!/usr/bin/env python
"""E3 — validate projection quality against realized JAAFFL points (plan §12.3 item 3, Track J).

Recomputes each player's REALIZED season points under the owner's JAAFFL scoring map from free
nflverse weekly stats, then scores a projection against them with ``jaaffl.calibrate.projections``
(MAE / RMSE / Spearman — the pure toolkit is unit-tested offline).

The $0 tier archives no past multi-source projections, so this runs the honest baseline free data
allows: a PERSISTENCE projection (prior-year points predict this year's). It exercises the
validation toolkit end-to-end and sets the bar any real blend must clear; feed archived projections
into ``compare_projection_sources`` once they exist.

NETWORK step: pulls two seasons of nflverse weekly stats. Skill positions (QB/RB/WR/TE) only —
K/DST are streamed and out of scope for projection validation.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/validate_projections.py --season 2024
"""

from __future__ import annotations

import argparse
import sys

from jaaffl.calibrate.projections import regression_metrics
from jaaffl.domain import Position
from jaaffl.league.defaults import jaaffl_scoring
from jaaffl.league.scoring import league_points
from jaaffl.providers.nflverse import NflreadpyProvider

# nflverse weekly column -> JAAFFL scoring stat key (the draft-relevant offensive drivers).
_STAT_MAP = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_td",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_td",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_td",
}
_TWO_POINT_COLS = (
    "passing_2pt_conversions",
    "rushing_2pt_conversions",
    "receiving_2pt_conversions",
)
_SKILL = {"QB", "RB", "WR", "TE"}


def season_points(provider: NflreadpyProvider, season: int, rules) -> tuple[dict, dict]:
    """Return ``({player_id: realized JAAFFL points}, {player_id: position})`` for ``season`` —
    weekly nflverse stats summed to season totals and scored under the JAAFFL map."""
    import polars as pl

    df = provider.historical_stats(season)
    present = [c for c in (*_STAT_MAP, *_TWO_POINT_COLS) if c in df.columns]
    agg = df.group_by("player_id").agg(
        pl.col("position").drop_nulls().first().alias("position"),
        *[pl.col(c).sum().alias(c) for c in present],
    )
    points: dict[str, float] = {}
    positions: dict[str, str] = {}
    for row in agg.iter_rows(named=True):
        pos = str(row.get("position") or "").upper()
        if pos not in _SKILL:
            continue
        stat_line = {
            jkey: float(row.get(ncol) or 0.0) for ncol, jkey in _STAT_MAP.items() if ncol in row
        }
        two_point = sum(float(row.get(c) or 0.0) for c in _TWO_POINT_COLS if c in row)
        if two_point:
            stat_line["two_point"] = two_point
        points[row["player_id"]] = league_points(stat_line, rules, Position(pos))
        positions[row["player_id"]] = pos
    return points, positions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E3: validate a projection vs realized JAAFFL points."
    )
    parser.add_argument("--season", type=int, required=True, help="Target (realized) season.")
    parser.add_argument(
        "--min-points",
        type=float,
        default=50.0,
        help="Prior-year points floor (draftable filter).",
    )
    args = parser.parse_args(argv)

    rules, _tiers, _bonuses = jaaffl_scoring()
    provider = NflreadpyProvider()

    print(
        f"[E3] recomputing realized JAAFFL points: {args.season - 1} (projection) "
        f"and {args.season} (actual) ...",
        file=sys.stderr,
    )
    prior, _ = season_points(provider, args.season - 1, rules)
    actual, positions = season_points(provider, args.season, rules)

    projection = {p: pts for p, pts in prior.items() if pts >= args.min_points and p in actual}
    if not projection:
        print("[E3] no overlapping players above the floor", file=sys.stderr)
        return 1

    overall = regression_metrics(projection, actual)
    print(
        f"[E3] persistence {args.season - 1}->{args.season} (>= {args.min_points:g} prior pts): "
        f"n={overall.n}  MAE={overall.mae:.1f}  RMSE={overall.rmse:.1f}  "
        f"Spearman={overall.spearman:.3f}"
    )
    for pos in ("QB", "RB", "WR", "TE"):
        proj_pos = {p: v for p, v in projection.items() if positions.get(p) == pos}
        actual_pos = {p: actual[p] for p in proj_pos}
        if len(proj_pos) >= 5:
            m = regression_metrics(proj_pos, actual_pos)
            print(
                f"[E3]   {pos}: n={m.n}  MAE={m.mae:.1f}  RMSE={m.rmse:.1f}  "
                f"Spearman={m.spearman:.3f}"
            )
    print(
        "[E3] baseline only (persistence); a real blend must beat these via "
        "compare_projection_sources once archived projections exist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
