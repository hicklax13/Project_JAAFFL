"""Stage 3 of the engine: opponent pick-probability model.

Turns ADP, expert-consensus dispersion, and manager-specific tendencies from prior CBS
drafts into a probability distribution over who is taken before your next pick — not a
single deterministic guess.
"""

from __future__ import annotations

from jaaffl.domain import DraftState, LeagueSettings


def pick_probabilities(
    state: DraftState,
    settings: LeagueSettings,
    adp: dict[str, float],
    *,
    horizon: int | None = None,
) -> dict[str, float]:
    """Return ``player_id -> P(taken before your next pick)`` over the next ``horizon`` picks.

    TODO(stage 5): model each upcoming team's pick from ADP + ECR dispersion + that manager's
    historical positional tendencies; default ``horizon`` to picks until your next turn.
    """
    raise NotImplementedError("stage 5: opponent pick-probability model")
