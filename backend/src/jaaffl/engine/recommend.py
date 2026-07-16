"""Engine orchestrator: turn live draft state into a ranked recommendation.

Wires the four stages together. The live recommendation score blends projected season
points, replacement-adjusted scarcity, injury-adjusted availability, and simulated
playoff odds. 2027 outputs, when added, are labeled ESTIMATED (ADR 0003).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from jaaffl.config import EngineParams
from jaaffl.domain import DraftState, LeagueSettings, Recommendation
from jaaffl.providers import FantasyDataProvider


class SlotState(StrEnum):
    """Where a candidate sits relative to your startable need at its position (§3.5)."""

    LAST_OPEN_STARTABLE = "last_open_startable"  # p fills your final open startable slot at its pos
    SURPLUS = "surplus"  # depth/stash beyond startable need
    NORMAL = "normal"


def lambda_weight(round_no: int, slot_state: SlotState, params: EngineParams) -> float:
    """Risk λ for the risk term ``−λ·σ̂`` (design §6.C.5).

    The phase default comes from ``params.lambda_schedule`` (floor-tilt λ>0 early, ceiling-tilt
    λ<0 late); the **slot override dominates** — filling your last open startable slot forces the
    floor tilt, a surplus/stash forces the ceiling tilt (``params.lambda_slot_override``).
    """
    if slot_state is SlotState.LAST_OPEN_STARTABLE:
        return float(params.lambda_slot_override["last_startable_slot_floor"])
    if slot_state is SlotState.SURPLUS:
        return float(params.lambda_slot_override["surplus_stash_ceiling"])
    for entry in params.lambda_schedule:
        low, high = entry["rounds"]
        if low <= round_no <= high:
            return float(entry["lambda"])
    return 0.0  # out-of-schedule round → neutral (never a crash)


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
