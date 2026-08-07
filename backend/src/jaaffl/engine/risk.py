"""The shipped risk / slot-state / punt rule (§3.5 + §6.C.5), in ONE place.

This module exists because the rule was implemented twice and the copies diverged.
``recommend.py`` applied ``lambda_slot_override`` and the ``punt_guard``;
``simulate.py::ScoreAgent`` — the agent every E2/E6 number is produced by — applied neither,
reading only ``lambda_schedule`` through a private ``_phase_lambda``.

Measured 2026-08-07 over 12 slots x 5 seeds, rosters compared bit-for-bit: sign-flipping
``lambda_slot_override`` changed **0 of 60** simulated rosters and disabling ``punt_guard`` changed
**0 of 60**, while doubling ``lambda_schedule`` and zeroing ``alpha`` each changed **60 of 60**.
Two shipped config keys were therefore unmeasurable, and Tier 7's closing instruction — obtain
E2/E6 evidence with ``--replicates >= 3`` before touching ``lambda_slot_override`` — could not be
followed by anyone.

Tier 4 found this same class of defect in this same agent (``candidate_cap`` 50 against the shipped
180; ranking by raw value where the engine ranks by MLV) and fixed candidate SELECTION while
leaving the SCORE FUNCTION diverging. One rule implemented twice diverges; the fix is to implement
it once. ``tests/test_harness_fidelity.py`` is the guard that keeps it that way.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from enum import StrEnum

from jaaffl.config import EngineParams
from jaaffl.domain import Position
from jaaffl.engine.optimize import StartingSlot


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

    ⚠️ Known defect, measured and NOT fixed here (Tier 8): because ``slot_state`` is a property of
    POSITION and σ is overwhelmingly positional (median 20.0 at K, 25.0 at DST, 106.3 at QB, with
    *zero* within-position variance at K and DST), ``λ_slot · σ`` acts as a positional bias term
    worth up to ``0.8·σ ≈ 85`` points — and the override assigns OPPOSITE signs to the two
    candidates being compared. Observed on the real board at R15: a surplus RB with MLV −44.80 beat
    a kicker filling the last open startable slot with MLV 0.00, a 45.76-point risk swing
    overturning a 44.80-point value verdict. The λ *schedule* does not have this problem nearly as
    badly, because it applies the same sign to every candidate in a round and so is common-mode.
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


def seat_roster(
    my_roster: Sequence[str],
    position: Mapping[str, Position],
    slots: Sequence[StartingSlot],
) -> list[bool]:
    """Greedily seat rostered players into starting slots (maximize seated) → filled-per-slot."""
    remaining: Counter[Position] = Counter(position[p] for p in my_roster if p in position)
    filled = [False] * len(slots)
    for i, slot in enumerate(slots):  # dedicated (single-eligible) slots first
        if len(slot.eligible) == 1:
            pos = next(iter(slot.eligible))
            if remaining.get(pos, 0) > 0:
                filled[i] = True
                remaining[pos] -= 1
    for i, slot in enumerate(slots):  # then flex slots from whatever is left
        if len(slot.eligible) > 1 and not filled[i]:
            for pos in slot.eligible:
                if remaining.get(pos, 0) > 0:
                    filled[i] = True
                    remaining[pos] -= 1
                    break
    return filled


def open_startable_by_position(
    filled: Sequence[bool], slots: Sequence[StartingSlot]
) -> dict[Position, int]:
    """How many open (unfilled) starting slots each position is still eligible to fill."""
    counts: dict[Position, int] = {}
    for i, slot in enumerate(slots):
        if not filled[i]:
            for pos in slot.eligible:
                counts[pos] = counts.get(pos, 0) + 1
    return counts


def slot_state_for(pos: Position, open_startable: Mapping[Position, int]) -> SlotState:
    """Classify ``pos`` against the open startable slots it could still fill."""
    open_count = open_startable.get(pos, 0)
    if open_count == 0:
        return SlotState.SURPLUS
    if open_count == 1:
        return SlotState.LAST_OPEN_STARTABLE
    return SlotState.NORMAL


def puntable_positions(params: EngineParams) -> frozenset[Position]:
    """Positions the punt guard may demote — the ``punt_guard.stream_round`` keys.

    Read from config rather than hard-coded, so making (say) TE streamable is a config change and
    not a code change, and so ``recommend``, ``ScoreAgent`` and ``preflight`` share one source.
    """
    return frozenset(Position(key) for key in params.punt_guard.get("stream_round", {}))


def has_open_non_puntable_slot(
    filled: Sequence[bool], slots: Sequence[StartingSlot], puntable: frozenset[Position]
) -> bool:
    """Is any unfilled starting slot one the punt guard is NOT allowed to defer?"""
    return any(not filled[i] and not (slot.eligible <= puntable) for i, slot in enumerate(slots))


def is_punted(
    pos: Position,
    round_no: int,
    params: EngineParams,
    *,
    has_open_non_puntable: bool,
) -> bool:
    """Punt guard (R1): hold K/DST out of the #1 spot before their stream round, unless the rest of
    the startable roster is already full. It **re-ranks, never changes the score**."""
    stream_round = int(params.punt_guard.get("stream_round", {}).get(pos.value, 0))
    return bool(
        params.punt_guard.get("enabled")
        and pos in puntable_positions(params)
        and round_no < stream_round
        and has_open_non_puntable
    )
