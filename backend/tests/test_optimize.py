"""Stage-1 flex-aware Marginal Lineup Value (§3.3): the value currency of the engine.

MLV_p = L*(B(R ∪ {p})) − L*(B(R)), where L* is the best position-legal assignment of a roster
(empty slots filled by replacement phantoms) to the 9 starting slots. Greedy is the fast default;
``linear_sum_assignment`` (Hungarian) is the verification path — they must agree.
"""

from __future__ import annotations

import random

import pytest

from jaaffl.domain import Position
from jaaffl.engine.optimize import (
    expand_starting_slots,
    lineup_value,
    lineup_value_hungarian,
    marginal_lineup_value,
)
from tests.engine_fixtures import jaaffl_settings

BASELINES = {
    Position.QB: 100.0,
    Position.RB: 90.0,
    Position.WR: 80.0,
    Position.TE: 70.0,
    Position.K: 60.0,
    Position.DST: 65.0,
}


def _slots():
    return expand_starting_slots(jaaffl_settings())


def test_expand_starting_slots_is_nine_with_wr_rb_flex() -> None:
    slots = _slots()
    assert len(slots) == 9  # 9 starters, bench excluded
    wr_only = [s for s in slots if s.eligible == frozenset({Position.WR})]
    flex = [s for s in slots if s.eligible == frozenset({Position.WR, Position.RB})]
    assert len(wr_only) == 3  # 3 dedicated WR slots
    assert len(flex) == 1  # exactly one WR/RB flex
    assert flex[0].eligible == frozenset({Position.WR, Position.RB})  # no TE/QB/K/DST
    # Single-eligible slots for the one-per-team positions.
    for pos in (Position.QB, Position.RB, Position.TE, Position.K, Position.DST):
        assert sum(1 for s in slots if s.eligible == frozenset({pos})) == 1


@pytest.mark.parametrize(
    ("pos", "mu"),
    [
        (Position.QB, 300.0),
        (Position.RB, 220.0),
        (Position.WR, 210.0),
        (Position.TE, 160.0),
        (Position.K, 130.0),
        (Position.DST, 140.0),
    ],
)
def test_empty_roster_mlv_is_classic_vor(pos: Position, mu: float) -> None:
    """Empty roster ⇒ MLV_p = μ_p − baseline(pos(p)) — the VOR reduction, for every position."""
    slots = _slots()
    got = marginal_lineup_value("p", [], {"p": mu}, {"p": pos}, BASELINES, slots)
    assert got == pytest.approx(mu - BASELINES[pos])


def test_second_qb_auto_defers_to_zero() -> None:
    """A 2nd (worse) QB adds nothing to the starting lineup — MLV ≈ 0 with no need-multiplier."""
    slots = _slots()
    mu = {"qb1": 300.0, "qb2": 280.0}
    pos = {"qb1": Position.QB, "qb2": Position.QB}
    assert marginal_lineup_value("qb2", ["qb1"], mu, pos, BASELINES, slots) == pytest.approx(0.0)


def test_upgrade_qb_scores_only_the_delta() -> None:
    """A BETTER QB2 is worth exactly the upgrade over the incumbent, not its full μ."""
    slots = _slots()
    mu = {"qb1": 280.0, "qb2": 300.0}
    pos = {"qb1": Position.QB, "qb2": Position.QB}
    assert marginal_lineup_value("qb2", ["qb1"], mu, pos, BASELINES, slots) == pytest.approx(20.0)


def test_fourth_wr_is_priced_against_the_flex_phantom() -> None:
    """With 3 WR slots full, a 4th WR competes for the flex phantom max(RB, WR)."""
    slots = _slots()
    # RB_base (90) > WR_base (80) ⇒ flex phantom is 90.
    mu = {"wr1": 200.0, "wr2": 190.0, "wr3": 185.0, "wr4": 150.0}
    pos = {p: Position.WR for p in mu}
    got = marginal_lineup_value("wr4", ["wr1", "wr2", "wr3"], mu, pos, BASELINES, slots)
    assert got == pytest.approx(150.0 - 90.0)  # μ_wr4 − max(RB_base, WR_base)


def test_pure_bench_stash_scores_zero() -> None:
    """A player who cracks no starting slot adds 0 to the starting lineup — its value is VONA."""
    slots = _slots()
    mu = {"rb1": 300.0, "stash": 10.0}  # stash below every baseline ⇒ never starts
    pos = {"rb1": Position.RB, "stash": Position.RB}
    assert marginal_lineup_value("stash", ["rb1"], mu, pos, BASELINES, slots) == pytest.approx(0.0)


def test_greedy_matches_hungarian_on_random_rosters() -> None:
    """The greedy fast path must equal the Hungarian optimum on 1000 random rosters (§3.3)."""
    slots = _slots()
    pool = list(BASELINES)
    rng = random.Random(0)
    for _ in range(1000):
        n = rng.randint(0, 14)
        mu, pos, ids = {}, {}, []
        for i in range(n):
            pid = f"p{i}"
            mu[pid] = rng.uniform(0.0, 320.0)
            pos[pid] = rng.choice(pool)
            ids.append(pid)
        greedy = lineup_value(ids, mu, pos, BASELINES, slots)
        hungarian = lineup_value_hungarian(ids, mu, pos, BASELINES, slots)
        assert greedy == pytest.approx(hungarian), (ids, {k: round(v, 1) for k, v in mu.items()})


def test_marginal_value_accepts_precomputed_base() -> None:
    """The hot path caches L*(B(R)); passing base_value must match computing it inline."""
    slots = _slots()
    mu = {"rb1": 250.0, "rb2": 240.0}
    pos = {"rb1": Position.RB, "rb2": Position.RB}
    base = lineup_value(["rb1"], mu, pos, BASELINES, slots)
    inline = marginal_lineup_value("rb2", ["rb1"], mu, pos, BASELINES, slots)
    cached = marginal_lineup_value("rb2", ["rb1"], mu, pos, BASELINES, slots, base_value=base)
    assert cached == pytest.approx(inline)


# --- Tier 7: a replacement phantom needs a pick left to fill it -----------------------------
#
# Pre-Tier-7, `lineup_value` credited a phantom for EVERY empty starting slot unconditionally --
# as though a replacement-level player were guaranteed, free, forever, including after the draft
# had ended. Measured on the real 510-player board, that made a roster with no QB worth exactly as
# much as one with a replacement QB, so the E2/E6 objective saw 5.9% of a 260.77-point gap and the
# engine drafted 13 tight ends while three starting slots stayed unfillable.


def test_lineup_value_default_is_unchanged_by_the_capacity_parameter() -> None:
    """`picks_remaining=None` must be bit-identical to the pre-Tier-7 behaviour."""
    slots = _slots()
    mu = {"qb1": 120.0, "rb1": 150.0}
    pos = {"qb1": Position.QB, "rb1": Position.RB}
    assert lineup_value(["qb1", "rb1"], mu, pos, BASELINES, slots) == lineup_value(
        ["qb1", "rb1"], mu, pos, BASELINES, slots, picks_remaining=None
    )


def test_an_unfilled_slot_earns_no_phantom_when_no_picks_remain() -> None:
    """The draft is over: an empty required slot yields nothing, not replacement value."""
    slots = _slots()
    unlimited = lineup_value([], {}, {}, BASELINES, slots, picks_remaining=None)
    exhausted = lineup_value([], {}, {}, BASELINES, slots, picks_remaining=0)
    assert unlimited == pytest.approx(715.0)  # 100 + 90 + 3*80 + 90 + 70 + 60 + 65
    assert exhausted == 0.0


def test_capacity_credits_the_most_valuable_empty_slots_first() -> None:
    """One pick, nine empty slots: you would fill the best one, so only that phantom survives."""
    slots = _slots()
    assert lineup_value([], {}, {}, BASELINES, slots, picks_remaining=1) == pytest.approx(100.0)
    assert lineup_value([], {}, {}, BASELINES, slots, picks_remaining=2) == pytest.approx(190.0)


def test_a_sub_replacement_starter_beats_an_empty_slot_once_picks_run_out() -> None:
    """A below-replacement QB you can START is worth more than a phantom you cannot field."""
    slots = _slots()
    mu = {"qb1": 40.0}  # far below the 100.0 QB baseline
    pos = {"qb1": Position.QB}
    assert lineup_value(["qb1"], mu, pos, BASELINES, slots, picks_remaining=0) == pytest.approx(
        40.0
    )
    assert lineup_value([], {}, {}, BASELINES, slots, picks_remaining=0) == 0.0


def test_mlv_of_a_surplus_body_is_negative_when_a_required_slot_is_at_risk() -> None:
    """The headline. Taking a body you cannot start SPENDS the pick that would have filled a slot.

    Tier 6 walked a full 12x17 draft from seat 6 and the engine returned {RB:1, TE:13, WR:3} --
    three unfillable starting slots -- because MLV scored a thirteenth tight end and a
    desperately-needed quarterback identically at 0.00.
    """
    slots = _slots()
    mu = {"qb1": 120.0, "qb2": 110.0}
    pos = {"qb1": Position.QB, "qb2": Position.QB}
    assert marginal_lineup_value(
        "qb2", ["qb1"], mu, pos, BASELINES, slots, picks_remaining=1
    ) == pytest.approx(-90.0)


def test_mlv_is_unchanged_while_picks_outnumber_the_slots_they_must_fill() -> None:
    """The safety property: capacity is INERT until it binds, so the early rounds are untouched.

    With 9 starting slots this means rounds 1-14 of a 17-round draft are bit-identical.
    """
    slots = _slots()
    mu = {"qb1": 120.0, "rb1": 150.0, "rb2": 140.0}
    pos = {"qb1": Position.QB, "rb1": Position.RB, "rb2": Position.RB}
    for k in range(10, 18):
        assert marginal_lineup_value(
            "rb2", ["qb1", "rb1"], mu, pos, BASELINES, slots, picks_remaining=k
        ) == pytest.approx(marginal_lineup_value("rb2", ["qb1", "rb1"], mu, pos, BASELINES, slots))


def test_roster_capacity_counts_every_slot_a_position_is_eligible_for() -> None:
    """K and DST fit only their own starting slot — the JAAFFL bench is (QB, RB, WR, TE).

    Measured 2026-08-07: the simulated opponent field drafted 33 of 33 draftable kickers for 12
    teams, holding up to five each, into slots this roster does not have.
    """
    from jaaffl.engine.optimize import roster_capacity

    capacity = roster_capacity(jaaffl_settings())
    assert capacity[Position.K] == 1
    assert capacity[Position.DST] == 1
    assert capacity[Position.QB] == 9  # 1 dedicated starter + the 8 shared bench slots
    assert capacity[Position.WR] == 12  # 3 dedicated + the WR/RB flex + 8 bench


def test_roster_capacity_never_reports_a_position_the_roster_cannot_hold() -> None:
    from jaaffl.engine.optimize import roster_capacity

    assert Position.LB not in roster_capacity(jaaffl_settings())
