"""Engine orchestrator: turn live draft state into a ranked recommendation.

Wires the four stages together. The live recommendation score blends projected season
points, replacement-adjusted scarcity, injury-adjusted availability, and simulated
playoff odds. 2027 outputs, when added, are labeled ESTIMATED (ADR 0003).
"""

from __future__ import annotations

from collections.abc import Sequence

from jaaffl.domain import DraftState, LeagueSettings, Recommendation
from jaaffl.providers import FantasyDataProvider


def recommend(
    state: DraftState,
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    *,
    season: int,
    n_sims: int = 1000,
) -> Recommendation:
    """Produce a ranked :class:`Recommendation` for the team on the clock.

    Pipeline (see the per-module docstrings):
      1. ``engine.projections.build_projections`` — ensemble stat lines.
      2. ``league.scoring`` + ``league.replacement`` — league points, replacement/VORP, scarcity.
      3. ``engine.opponents.pick_probabilities`` — who's gone before our next turn.
      4. ``engine.simulate`` + ``engine.optimize`` — expected end-of-draft roster value.

    Depends only on the provider *protocol*, never on concrete adapters.
    """
    raise NotImplementedError("stage 5: assemble the four-stage recommendation")
