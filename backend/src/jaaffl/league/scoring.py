"""Convert projected stat lines into league fantasy points under the league's exact scoring.

The heart of "league-specific value": a raw consensus rank ignores your custom CBS scoring,
this does not. Stat keys in ``stat_line`` must match ``ScoringRule.stat`` (normalize upstream
in the ingest/crosswalk layer).

Three additive passes (design §3.2):
  1. **linear** ``ScoringRule`` — points per unit of a stat (existing core; non-PPR ⇒ no
     ``reception`` rule, so a catch is worth 0).
  2. **tiered** ``ScoringTier`` — bracketed, non-linear stats, matched by ``[lower, upper)``.
     CBS "Standard" scores DST on BOTH ``dst_points_allowed`` AND ``dst_yards_allowed``, and the
     two tiers **sum** (design §6.D).
  3. **threshold** ``ScoringBonus`` — points per qualifying event, e.g. a K's 50+ yard FG. The
     ``stat`` is a pre-bucketed COUNT (ingest buckets by distance); ``threshold`` documents the
     edge; ``points`` is per event.

A tier/bonus fires only when its ``stat`` is present in the line (position is implicit via stat
presence, design §3.0) AND — when the rule carries ``applies_to`` — the player's position is
listed (defensive, consistent with the linear pass, and resolving the §1.4.1/§3.0 ``applies_to``
inconsistency by supporting both).

TODO(capture): the REAL CBS "Standard" bracket/bonus values are UNVERIFIED (capture-blocked, see
docs/owner-manual-todo.md). This evaluator is value-agnostic; the offline defaults live in
``league.defaults`` and the live map arrives via ``CbsOnPageProvider.league_settings()``.
"""

from __future__ import annotations

from collections.abc import Mapping

from jaaffl.domain import Position, ScoringBonus, ScoringRule, ScoringTier


def _applies(applies_to: list[Position] | None, position: Position) -> bool:
    """A rule with no ``applies_to`` is league-wide; else it fires only for listed positions."""
    return applies_to is None or position in applies_to


def league_points(
    stat_line: Mapping[str, float],
    scoring: list[ScoringRule],
    position: Position,
    *,
    tiers: list[ScoringTier] | None = None,
    bonuses: list[ScoringBonus] | None = None,
) -> float:
    """Return the fantasy points a stat line earns under ``scoring`` for ``position``.

    ``tiers``/``bonuses`` are keyword-only and default to none, so the linear 3-arg call is
    unchanged. Evaluation is ``linear + tiers + bonuses`` (design §3.2).
    """
    total = 0.0

    for rule in scoring:  # linear points-per-unit
        if not _applies(rule.applies_to, position):
            continue
        total += stat_line.get(rule.stat, 0.0) * rule.points_per_unit

    for tier in tiers or []:  # bracketed, matched by value ∈ [lower, upper); open-ended upper=None
        if tier.stat not in stat_line or not _applies(tier.applies_to, position):
            continue
        value = stat_line[tier.stat]
        for bracket in tier.brackets:
            if value >= bracket.lower and (bracket.upper is None or value < bracket.upper):
                total += bracket.points
                break

    for bonus in bonuses or []:  # threshold bonuses: count of qualifying events × points
        if not _applies(bonus.applies_to, position):
            continue
        total += stat_line.get(bonus.stat, 0.0) * bonus.points

    return total
