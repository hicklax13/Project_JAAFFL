"""Owner-provided JAAFFL2025 scoring (league/defaults.py) — custom, non-PPR.

Authoritative owner rules (2026-07-17): passing 0.02/yd (1 per 50); NO offensive turnover penalty;
all TDs 6; non-PPR (rec 0); K FG base 3 + CUMULATIVE distance bonuses (+1 at 50, +1 more at 60); DST
scores a SINGLE points-allowed bracket (0-9 = 6) and NO yards-allowed tier.
"""

from __future__ import annotations

from jaaffl.domain import Position
from jaaffl.league import league_points
from jaaffl.league.defaults import jaaffl_scoring


def test_receptions_score_zero_non_ppr() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"receptions": 10, "receiving_yards": 100, "receiving_td": 1}
    pts = league_points(line, rules, Position.WR, tiers=tiers, bonuses=bonuses)
    assert pts == 100 * 0.1 + 1 * 6  # 16.0 — the 10 catches add nothing (non-PPR)


def test_passing_is_one_point_per_50_and_no_interception_penalty() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"passing_yards": 300, "passing_td": 3, "interception": 1}  # INT must NOT be penalized
    pts = league_points(line, rules, Position.QB, tiers=tiers, bonuses=bonuses)
    assert pts == 300 * 0.02 + 3 * 6  # 6 + 18 = 24.0 (interception scores nothing)


def test_no_offensive_fumble_lost_penalty() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"rushing_yards": 100, "rushing_td": 1, "fumble_lost": 2}
    pts = league_points(line, rules, Position.RB, tiers=tiers, bonuses=bonuses)
    assert pts == 100 * 0.1 + 1 * 6  # 16.0 — offensive fumbles are not penalized


def test_dst_single_points_allowed_bracket_and_no_yards_tier() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    # Allow 7 → +6 (single 0-9 bracket); dst_yards_allowed has NO tier; 4 sacks +4; 1 INT +2.
    line = {"dst_points_allowed": 7, "dst_yards_allowed": 280, "sack": 4, "dst_int": 1}
    pts = league_points(line, rules, Position.DST, tiers=tiers, bonuses=bonuses)
    assert pts == 6 + 4 + 2  # 12.0 (yards-allowed is ignored — JAAFFL scores no yards tier)


def test_dst_points_allowed_boundary() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    kw = {"tiers": tiers, "bonuses": bonuses}
    assert league_points({"dst_points_allowed": 9}, rules, Position.DST, **kw) == 6.0  # under 10
    assert league_points({"dst_points_allowed": 10}, rules, Position.DST, **kw) == 0.0  # 10+ → 0


def test_kicker_distance_bonuses_are_cumulative() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    kw = {"tiers": tiers, "bonuses": bonuses}
    # 55-yd FG: 50plus only → 3 + 1 = 4.  62-yd FG: 50plus AND 60plus → 3 + 1 + 1 = 5.
    assert league_points({"fg_made": 1, "fg_made_50plus": 1}, rules, Position.K, **kw) == 4.0
    assert (
        league_points(
            {"fg_made": 1, "fg_made_50plus": 1, "fg_made_60plus": 1}, rules, Position.K, **kw
        )
        == 5.0
    )
