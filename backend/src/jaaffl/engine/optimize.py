"""Stage 4b of the engine: constrained roster optimization (OR-Tools CP-SAT).

Given player values and the league's exact roster rules (slots, flex eligibility, position
caps, optional stacking/contingency constraints), pick the roster that maximizes value.
"""

from __future__ import annotations

from jaaffl.domain import LeagueSettings


def optimize_roster(
    player_values: dict[str, float],
    player_positions: dict[str, str],
    settings: LeagueSettings,
    *,
    already_rostered: list[str] | None = None,
) -> list[str]:
    """Return the value-maximizing set of ``player_id``s that fills the roster legally.

    TODO(stage 5): build a CP-SAT model — binary pick vars, slot-eligibility constraints
    (incl. flex/superflex), and roster-size caps — and maximize total value.
    """
    raise NotImplementedError("stage 5: CP-SAT roster optimization")
