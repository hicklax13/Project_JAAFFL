"""Stage 4a of the engine: Monte Carlo draft simulation.

Roll the rest of the draft forward many times using the opponent model, so each candidate
pick can be scored by the expected quality of the *final* rosters it leads to — optionally
extended to season/playoff-odds simulation rather than point totals alone.
"""

from __future__ import annotations

from jaaffl.domain import DraftState, LeagueSettings


def simulate_drafts(
    state: DraftState,
    settings: LeagueSettings,
    projections: dict[str, dict[str, float]],
    pick_probs: dict[str, float],
    *,
    n_sims: int = 1000,
) -> dict[str, float]:
    """Return ``candidate player_id -> expected end-of-draft roster value``.

    TODO(stage 5): for each simulation, sample opponents' picks from ``pick_probs``, let the
    roster optimizer complete our roster, and average the resulting roster value per
    candidate first pick.
    """
    raise NotImplementedError("stage 5: Monte Carlo draft simulation")
