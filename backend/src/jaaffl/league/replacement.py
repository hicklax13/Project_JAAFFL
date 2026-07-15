"""Replacement-level baselines (VBD/VORP) derived from league roster construction.

Replacement level for a position is roughly the quality of the best still-available player
once every team has filled its dedicated starting slots at that position. Value over
replacement (VORP) then measures how much a player beats that baseline in *league* points.
"""

from __future__ import annotations

from collections import defaultdict

from jaaffl.domain import LeagueSettings, Player, Position


def starter_demand(settings: LeagueSettings) -> dict[Position, int]:
    """League-wide count of *dedicated* starting slots per position.

    Dedicated (single-eligible-position) starting slots are summed across all teams. Flex
    slots (multiple eligible positions) are intentionally excluded here — allocating flex
    demand to the right positions depends on projected values and is handled in the engine
    (Stage 5). This function gives the exact dedicated baseline that flex allocation builds on.
    """
    demand: dict[Position, int] = defaultdict(int)
    for slot in settings.roster_slots:
        if not slot.starting:
            continue
        if len(slot.eligible_positions) == 1:
            demand[slot.eligible_positions[0]] += slot.count * settings.team_count
    return dict(demand)


def replacement_values(
    settings: LeagueSettings,
    projected_points: dict[str, float],
    players: dict[str, Player],
) -> dict[Position, float]:
    """Return the replacement-level league points per position.

    TODO(stage 5): rank players by projected league points within each position, then take
    the value at the replacement rank (dedicated demand + allocated flex share).
    """
    raise NotImplementedError("stage 5: compute replacement values from projections + flex")
