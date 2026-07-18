"""Owner-provided JAAFFL2025 scoring (custom, non-PPR) — the authoritative league map.

Encoded verbatim from the owner's CBS League-Settings + Constitution (2026-07-17). Distinctives:
**passing = 1 pt / 50 yds (0.02/yd)**, **no offensive turnover penalty**, all TDs 6, non-PPR
(receptions score 0). Kicker FG base 3 with cumulative distance bonuses (+1 at 50, +1 more at 60 →
50-59 nets 4, 60+ nets 5). DST scores a SINGLE points-allowed bracket (**allow 0-9 → +6**, else 0)
and NO yards-allowed tier, plus sack 1 / INT 2 / fumble recovery 2 / safety 2 / def+ST TD 6.

Stat keys are JAAFFL-canonical; the ingest/context layer maps provider columns (nflverse
``passing_tds`` → ``passing_td``) onto them. Only CBS live-frame parsing stays capture-blocked now —
the scoring VALUES are owner-confirmed. Do NOT edit config/league.json's roster (immutable); a
captured CBS ``league_settings`` may still override this map (defense-in-depth).

Omitted (no per-player data on the $0 tier; inert): individual fumble-recovery / kick-return TDs.
"""

from __future__ import annotations

from jaaffl.domain import Position, ScoringBonus, ScoringBracket, ScoringRule, ScoringTier

_DST = [Position.DST]
_K = [Position.K]


def jaaffl_scoring() -> tuple[list[ScoringRule], list[ScoringTier], list[ScoringBonus]]:
    """Return ``(rules, tiers, bonuses)`` for the owner-provided JAAFFL2025 scoring (non-PPR)."""
    rules = [
        # Offense — non-PPR (no ``reception`` rule); NO offensive turnover penalty; all TDs 6.
        ScoringRule(stat="passing_yards", points_per_unit=0.02),  # 1 pt / 50 yds
        ScoringRule(stat="passing_td", points_per_unit=6.0),
        ScoringRule(stat="rushing_yards", points_per_unit=0.1),  # 1 pt / 10 yds
        ScoringRule(stat="rushing_td", points_per_unit=6.0),
        ScoringRule(stat="receiving_yards", points_per_unit=0.1),
        ScoringRule(stat="receiving_td", points_per_unit=6.0),
        ScoringRule(stat="two_point", points_per_unit=2.0),  # pass/rush/rec conversions
        # Kicker — FG base 3 (linear); PAT 1. Distance bonuses below.
        ScoringRule(stat="fg_made", points_per_unit=3.0, applies_to=_K),
        ScoringRule(stat="xp_made", points_per_unit=1.0, applies_to=_K),
        # DST — event scoring.
        ScoringRule(stat="sack", points_per_unit=1.0, applies_to=_DST),
        ScoringRule(stat="dst_int", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="fumble_recovery", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="safety", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="dst_td", points_per_unit=6.0, applies_to=_DST),
        ScoringRule(stat="return_td", points_per_unit=6.0, applies_to=_DST),
    ]
    tiers = [
        # DST points-allowed: a SINGLE bracket — allow 0-9 → +6, allow 10+ → 0 (no bracket matches).
        # JAAFFL scores NO yards-allowed tier.
        ScoringTier(
            stat="dst_points_allowed",
            applies_to=_DST,
            brackets=[ScoringBracket(lower=0, upper=10, points=6)],
        ),
    ]
    bonuses = [
        # Cumulative FG distance bonuses: ≥50 → +1, ≥60 → +1 more (a 60+ FG earns BOTH → +2).
        ScoringBonus(stat="fg_made_50plus", threshold=50, points=1.0, applies_to=_K),
        ScoringBonus(stat="fg_made_60plus", threshold=60, points=1.0, applies_to=_K),
    ]
    return rules, tiers, bonuses
