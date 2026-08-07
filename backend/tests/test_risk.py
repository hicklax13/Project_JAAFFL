"""Stage-3 risk term (§3.5): the λ schedule + slot override.

λ > 0 tilts toward floor (bank a starter early); λ < 0 tilts toward ceiling (swing on a bench
stash late). The slot override DOMINATES the phase: filling your last open startable slot forces a
floor tilt; surplus/stash forces a ceiling tilt.
"""

from __future__ import annotations

import pytest

from jaaffl.engine.risk import SlotState, lambda_weight
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


def test_centred_sigma_is_inert_when_no_median_is_supplied() -> None:
    """The safety property: an absent median must be bit-identical to today's raw sigma."""
    from jaaffl.engine.risk import risk_penalty

    assert risk_penalty(0.4, 88.85) == pytest.approx(0.4 * 88.85)
    assert risk_penalty(0.4, 88.85, sigma_median=None) == pytest.approx(0.4 * 88.85)


def test_centred_sigma_prices_volatility_relative_to_the_position() -> None:
    """Measured on the real board (Tier 8): sigma's median spans 20.0 at K to 106.3 at QB, and K
    and DST have ZERO within-position variance, so `lambda * sigma` is a positional bias term worth
    up to 0.8 * 106.3 = 85 points rather than a risk assessment. Centring on the position median
    makes it mean "more or less volatile than typical for his position".

    At R15 on the real board a surplus RB (sigma 94.40, median 59.0) collected +37.76 while a
    kicker filling the last open startable slot (sigma 20.0, median 20.0) was charged -8.00 — a
    45.76-point swing that overturned a 44.80-point value verdict. Centred, those become +14.16 and
    exactly 0.00.
    """
    from jaaffl.engine.risk import risk_penalty

    assert risk_penalty(-0.4, 94.40, sigma_median=59.0) == pytest.approx(-14.16)
    assert risk_penalty(0.4, 20.0, sigma_median=20.0) == pytest.approx(0.0)


def test_a_surplus_stash_is_not_a_stash_when_every_pick_is_spoken_for() -> None:
    """The feasibility gate: the surplus ceiling pays for OPTION value, and a pick you must spend
    on a required slot carries none. Inert whenever a stash is still affordable."""
    from jaaffl.engine.risk import lambda_weight

    params = engine_params()
    # 3 picks left, 3 unfilled slots -> spending this one leaves 2 picks for 3 slots.
    assert lambda_weight(15, SlotState.SURPLUS, params, can_stash=False) == pytest.approx(0.0)
    assert lambda_weight(15, SlotState.SURPLUS, params, can_stash=True) == pytest.approx(-0.4)
    # The gate never touches a candidate who is FILLING a slot.
    assert lambda_weight(15, SlotState.LAST_OPEN_STARTABLE, params, can_stash=False) == (
        pytest.approx(0.4)
    )
