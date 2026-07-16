"""Offline CBS 'Standard' (non-PPR) scoring defaults (league/defaults.py).

Pins the two CBS distinctives the deep-research verified (2026-07-16): passing TD = 6 (not 4) and
a DST that scores BOTH points-allowed AND yards-allowed brackets. Non-PPR ⇒ receptions score 0.
Values are the published default (TODO(capture): the live room may be commissioner-customized).
"""

from __future__ import annotations

from jaaffl.domain import Position
from jaaffl.league import league_points
from jaaffl.league.defaults import cbs_standard_scoring


def test_receptions_score_zero_in_standard() -> None:
    rules, tiers, bonuses = cbs_standard_scoring()
    line = {"receptions": 10, "receiving_yards": 100, "receiving_td": 1}
    pts = league_points(line, rules, Position.WR, tiers=tiers, bonuses=bonuses)
    assert pts == 100 * 0.1 + 1 * 6  # 16.0 — the 10 catches add nothing (non-PPR)


def test_cbs_passing_td_is_six_not_four() -> None:
    rules, tiers, bonuses = cbs_standard_scoring()
    line = {"passing_yards": 300, "passing_td": 3, "interception": 1}
    pts = league_points(line, rules, Position.QB, tiers=tiers, bonuses=bonuses)
    assert pts == 300 * 0.04 + 3 * 6 - 2  # 12 + 18 − 2 = 28.0


def test_dst_scores_both_points_and_yards_allowed() -> None:
    rules, tiers, bonuses = cbs_standard_scoring()
    # 3 pts allowed → +8 (1–6 bracket); 280 yds allowed → +2 (250–299 bracket); 4 sacks → +4.
    line = {"dst_points_allowed": 3, "dst_yards_allowed": 280, "sack": 4}
    pts = league_points(line, rules, Position.DST, tiers=tiers, bonuses=bonuses)
    assert pts == 8 + 2 + 4  # 14.0


def test_kicker_50plus_field_goal_nets_five() -> None:
    rules, tiers, bonuses = cbs_standard_scoring()
    # One 45-yd FG (3) + one 52-yd FG (3 linear + 2 bonus = 5) + PAT (1) = 9.
    line = {"fg_made": 2, "fg_made_50plus": 1, "xp_made": 1}
    pts = league_points(line, rules, Position.K, tiers=tiers, bonuses=bonuses)
    assert pts == 2 * 3 + 1 * 2 + 1 * 1  # 6 + 2 + 1 = 9.0
