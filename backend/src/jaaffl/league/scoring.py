"""Convert projected stat lines into league fantasy points under the league's exact scoring.

The heart of "league-specific value": a raw consensus rank ignores your custom CBS scoring,
this does not. Stat keys in ``stat_line`` must match ``ScoringRule.stat`` (normalize upstream
in the ingest/crosswalk layer).
"""

from __future__ import annotations

from collections.abc import Mapping

from jaaffl.domain import Position, ScoringRule


def league_points(
    stat_line: Mapping[str, float],
    scoring: list[ScoringRule],
    position: Position,
) -> float:
    """Return the fantasy points a stat line earns under ``scoring`` for ``position``.

    Bonus thresholds and per-position modifiers beyond ``applies_to`` are a Stage-5
    extension; this covers the linear points-per-unit case that dominates CBS scoring.
    """
    total = 0.0
    for rule in scoring:
        if rule.applies_to is not None and position not in rule.applies_to:
            continue
        total += stat_line.get(rule.stat, 0.0) * rule.points_per_unit
    return total
