"""Offline CBS "Standard" (non-PPR) scoring defaults — the validation fallback behind TODO(capture).

The REAL CBS scoring map is capture-blocked (the live room may be commissioner-customized — CBS
allows per-league overrides). These are CBS's **published Standard defaults**, verified 2026-07-16
against CBS's own article and its point-structure table (they agree):
  - https://www.cbssports.com/fantasy/football/news/what-is-a-standard-scoring-league/
  - https://help.football.cbssports.com/s/article/How-do-we-set-up-scoring-ranges
Two CBS distinctives most "standard" tables get wrong: **passing TD = 6** (not 4), and a DST that
scores BOTH points-allowed AND yards-allowed brackets. Non-PPR ⇒ receptions score 0 (no rule).

Stat keys are JAAFFL-canonical; the ingest/context layer maps provider columns (nflverse
``passing_tds`` → ``passing_td``, etc.) onto them. When a live CBS scoring-page capture lands
(owner-manual), replace these via ``CbsOnPageProvider.league_settings()`` — do NOT edit
config/league.json (immutable).

TODO(capture): blocked-kick value and missed-FG/PAT penalties are not in the CBS default table —
left out until a live capture confirms them.
"""

from __future__ import annotations

from jaaffl.domain import Position, ScoringBonus, ScoringBracket, ScoringRule, ScoringTier

_DST = [Position.DST]
_K = [Position.K]


def cbs_standard_scoring() -> tuple[list[ScoringRule], list[ScoringTier], list[ScoringBonus]]:
    """Return ``(rules, tiers, bonuses)`` for CBS Standard (non-PPR)."""
    rules = [
        # Offense — no ``reception`` rule (non-PPR); all TDs are 6.
        ScoringRule(stat="passing_yards", points_per_unit=0.04),  # 1 pt / 25 yds
        ScoringRule(stat="passing_td", points_per_unit=6.0),  # CBS: 6, not 4
        ScoringRule(stat="interception", points_per_unit=-2.0),  # thrown
        ScoringRule(stat="rushing_yards", points_per_unit=0.1),  # 1 pt / 10 yds
        ScoringRule(stat="rushing_td", points_per_unit=6.0),
        ScoringRule(stat="receiving_yards", points_per_unit=0.1),
        ScoringRule(stat="receiving_td", points_per_unit=6.0),
        ScoringRule(stat="fumble_lost", points_per_unit=-2.0),
        ScoringRule(stat="two_point", points_per_unit=2.0),  # pass/rush/rec conversions
        # Kicker — FG 0–49 = 3 (linear), 50+ adds a +2 bonus (net 5); PAT = 1.
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
        ScoringTier(
            stat="dst_points_allowed",
            applies_to=_DST,
            brackets=[
                ScoringBracket(lower=0, upper=1, points=12),  # shutout
                ScoringBracket(lower=1, upper=7, points=8),
                ScoringBracket(lower=7, upper=14, points=6),
                ScoringBracket(lower=14, upper=21, points=4),
                ScoringBracket(lower=21, upper=28, points=2),
                ScoringBracket(lower=28, upper=None, points=0),
            ],
        ),
        ScoringTier(
            stat="dst_yards_allowed",
            applies_to=_DST,
            brackets=[
                ScoringBracket(lower=0, upper=50, points=12),
                ScoringBracket(lower=50, upper=100, points=10),
                ScoringBracket(lower=100, upper=150, points=8),
                ScoringBracket(lower=150, upper=200, points=6),
                ScoringBracket(lower=200, upper=250, points=4),
                ScoringBracket(lower=250, upper=300, points=2),
                ScoringBracket(lower=300, upper=None, points=0),
            ],
        ),
    ]
    bonuses = [
        ScoringBonus(stat="fg_made_50plus", threshold=50, points=2.0, applies_to=_K),  # +2 → net 5
    ]
    return rules, tiers, bonuses
