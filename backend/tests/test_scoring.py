"""Stage-5 scoring evaluator (§3.2): linear rules + bracketed tiers + threshold bonuses.

The bracket VALUES here are illustrative shapes (like ``test_scaffold_contracts``); they pin the
evaluator's *structure*, not the real CBS numbers. The real CBS "Standard" map is capture-blocked
(TODO(capture)); the offline validation defaults live in ``league/defaults.py`` and are exercised
separately. Non-PPR (Rec = 0) is enforced by there simply being no reception rule.
"""

from __future__ import annotations

from jaaffl.domain import Position, ScoringBonus, ScoringBracket, ScoringRule, ScoringTier
from jaaffl.league import league_points


def _dst_points_allowed_tier() -> ScoringTier:
    # CBS-shaped points-allowed ladder: fewer points allowed → more fantasy points.
    return ScoringTier(
        stat="dst_points_allowed",
        applies_to=[Position.DST],
        brackets=[
            ScoringBracket(lower=0, upper=1, points=10),
            ScoringBracket(lower=1, upper=7, points=7),
            ScoringBracket(lower=7, upper=14, points=4),
            ScoringBracket(lower=14, upper=21, points=1),
            ScoringBracket(lower=21, upper=28, points=0),
            ScoringBracket(lower=28, upper=35, points=-1),
            ScoringBracket(lower=35, upper=None, points=-4),
        ],
    )


def _dst_yards_allowed_tier() -> ScoringTier:
    return ScoringTier(
        stat="dst_yards_allowed",
        applies_to=[Position.DST],
        brackets=[
            ScoringBracket(lower=0, upper=100, points=5),
            ScoringBracket(lower=100, upper=350, points=2),
            ScoringBracket(lower=350, upper=None, points=-3),
        ],
    )


def _k_50plus_bonus() -> ScoringBonus:
    # `stat` is a COUNT of qualifying events (ingest pre-buckets FGs by distance); `threshold`
    # documents the 50-yd edge; `points` is awarded per qualifying FG.
    return ScoringBonus(stat="fg_made_50plus", threshold=50, points=2, applies_to=[Position.K])


def test_linear_only_matches_existing_behavior() -> None:
    """The extended signature (tiers/bonuses default None) must not change linear scoring."""
    scoring = [
        ScoringRule(stat="rushing_yards", points_per_unit=0.1),
        ScoringRule(stat="rushing_td", points_per_unit=6.0),
    ]
    assert league_points({"rushing_yards": 100, "rushing_td": 2}, scoring, Position.RB) == 22.0


def test_dst_scores_both_points_and_yards_allowed_tiers() -> None:
    """CBS 'Standard' DST scores on BOTH points-allowed AND yards-allowed — the two tiers sum."""
    tiers = [_dst_points_allowed_tier(), _dst_yards_allowed_tier()]
    # 3 points allowed → +7 (1..7 bracket); 280 yards allowed → +2 (100..350 bracket) plus a sack.
    stat_line = {"dst_points_allowed": 3, "dst_yards_allowed": 280, "sack": 4}
    scoring = [ScoringRule(stat="sack", points_per_unit=1.0, applies_to=[Position.DST])]
    assert league_points(stat_line, scoring, Position.DST, tiers=tiers) == 7 + 2 + 4


def test_bracket_lower_inclusive_upper_exclusive() -> None:
    tier = _dst_points_allowed_tier()
    # value == a bracket's lower belongs to THAT bracket (inclusive); == upper falls to the next.
    assert league_points({"dst_points_allowed": 7}, [], Position.DST, tiers=[tier]) == 4  # [7,14)
    assert league_points({"dst_points_allowed": 14}, [], Position.DST, tiers=[tier]) == 1  # [14,21)


def test_open_ended_top_bracket_catches_all_above_lower() -> None:
    tier = _dst_points_allowed_tier()
    assert league_points({"dst_points_allowed": 45}, [], Position.DST, tiers=[tier]) == -4
    assert league_points({"dst_points_allowed": 35}, [], Position.DST, tiers=[tier]) == -4


def test_tier_skipped_when_its_stat_is_absent() -> None:
    tier = _dst_yards_allowed_tier()
    # No dst_yards_allowed in the stat line → that tier contributes nothing (no crash, no default).
    assert league_points({"dst_points_allowed": 3}, [], Position.DST, tiers=[tier]) == 0.0


def test_threshold_bonus_awards_points_per_qualifying_event() -> None:
    bonus = _k_50plus_bonus()
    # 3 made 50+ FGs × 2 pts = 6, on top of the linear FG points.
    scoring = [ScoringRule(stat="fg_made", points_per_unit=3.0, applies_to=[Position.K])]
    stat_line = {"fg_made": 25, "fg_made_50plus": 3}
    assert league_points(stat_line, scoring, Position.K, bonuses=[bonus]) == 25 * 3.0 + 3 * 2


def test_tier_respects_applies_to_when_position_mismatches() -> None:
    """A DST-only tier must not fire for a non-DST player even if the stat is present (defensive:
    honors the applies_to the model carries, consistent with linear rules)."""
    tier = _dst_points_allowed_tier()  # applies_to=[DST]
    assert league_points({"dst_points_allowed": 3}, [], Position.K, tiers=[tier]) == 0.0


def test_bonus_respects_applies_to_when_position_mismatches() -> None:
    bonus = _k_50plus_bonus()  # applies_to=[K]
    assert league_points({"fg_made_50plus": 3}, [], Position.DST, bonuses=[bonus]) == 0.0


def test_linear_tiers_and_bonuses_combine() -> None:
    """A full mixed evaluation: linear + one tier + one bonus in a single call."""
    scoring = [ScoringRule(stat="fg_made", points_per_unit=3.0, applies_to=[Position.K])]
    tier = ScoringTier(
        stat="k_missed",
        applies_to=[Position.K],
        brackets=[
            ScoringBracket(lower=0, upper=1, points=1),
            ScoringBracket(lower=1, upper=None, points=-1),
        ],
    )
    bonus = _k_50plus_bonus()
    stat_line = {"fg_made": 20, "k_missed": 2, "fg_made_50plus": 1}
    # 20*3 (linear) + (-1) (k_missed≥1 bracket) + 1*2 (bonus) = 61
    assert league_points(stat_line, scoring, Position.K, tiers=[tier], bonuses=[bonus]) == 61.0
