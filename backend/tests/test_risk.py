"""Stage-3 risk term (§3.5): the λ schedule + slot override.

λ > 0 tilts toward floor (bank a starter early); λ < 0 tilts toward ceiling (swing on a bench
stash late). The slot override DOMINATES the phase: filling your last open startable slot forces a
floor tilt; surplus/stash forces a ceiling tilt.
"""

from __future__ import annotations

import pytest

from jaaffl.engine.recommend import SlotState, lambda_weight
from tests.engine_fixtures import engine_params


@pytest.mark.parametrize(
    ("round_no", "expected"),
    [
        (1, 0.3),
        (2, 0.3),
        (3, 0.2),
        (6, 0.2),
        (7, 0.0),
        (9, 0.0),
        (10, -0.3),
        (13, -0.3),
        (14, -0.4),
        (17, -0.4),
    ],
)
def test_phase_schedule_maps_round_to_lambda(round_no: int, expected: float) -> None:
    assert lambda_weight(round_no, SlotState.NORMAL, engine_params()) == pytest.approx(expected)


def test_last_open_startable_forces_floor_tilt_over_phase() -> None:
    """Override test: an R11 pick filling the last WR starter slot is forced positive despite the
    R10–13 ceiling default (−0.3)."""
    got = lambda_weight(11, SlotState.LAST_OPEN_STARTABLE, engine_params())
    assert got == pytest.approx(0.4)  # last_startable_slot_floor from lambda_slot_override


def test_surplus_forces_ceiling_tilt_over_phase() -> None:
    """A surplus/stash in R2 is forced negative despite the R1–2 floor default (+0.3)."""
    got = lambda_weight(2, SlotState.SURPLUS, engine_params())
    assert got == pytest.approx(-0.4)  # surplus_stash_ceiling from lambda_slot_override


def test_out_of_schedule_round_defaults_to_neutral() -> None:
    """A round beyond the schedule (e.g. a malformed state) is neutral, never a crash."""
    assert lambda_weight(99, SlotState.NORMAL, engine_params()) == pytest.approx(0.0)
