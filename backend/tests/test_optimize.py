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


def test_value_over_replacement_is_the_unfloored_mlv() -> None:
    """VOR is what MLV reduces to on an empty roster — this module's own reduction guarantee —
    and it keeps ordering candidates below replacement, where MLV clamps every one of them to
    exactly 0.0. That clamp is what left the engine ranking 180 tied candidates by dict order."""
    from jaaffl.engine.optimize import value_over_replacement

    slots = expand_starting_slots(jaaffl_settings())
    mu = {"good": 300.0, "weak": 60.0, "weaker": 10.0}
    position = dict.fromkeys(mu, Position.WR)
    baselines = {Position.WR: 100.0}

    # Empty roster: MLV IS VOR for an above-replacement player (the reduction guarantee).
    assert marginal_lineup_value("good", [], mu, position, baselines, slots) == pytest.approx(
        value_over_replacement("good", mu, position, baselines)
    )

    # With the WR slots taken by better players, MLV floors BOTH weak players to exactly 0.0 —
    # and VOR still separates them by 50 points.
    full = ["good"] * 4
    mlvs = {
        pid: marginal_lineup_value(pid, full, mu, position, baselines, slots)
        for pid in ("weak", "weaker")
    }
    assert mlvs["weak"] == mlvs["weaker"] == 0.0
    assert value_over_replacement("weak", mu, position, baselines) == -40.0
    assert value_over_replacement("weaker", mu, position, baselines) == -90.0


# --- Unresolved roster ids: the crash that ended the 2026-08-15 live rehearsal ---------------
#
# CBS pick frames are ID-ONLY. When `ingest/resolve.py` cannot map a `cbs:<id>` to a canonical
# player it keeps the raw string and leaves the player on the board — deliberate, and fine while
# the id sits on an OPPONENT's roster. But `recommend.py:248` passes MY roster straight into
# `lineup_value`, which indexed `position[pid]` with no guard, so an unresolved id on my OWN
# roster raised KeyError out of the ASGI handler and killed every later recommendation.
#
# Observed live, not theorised: at pick 167 of the 2026-08-15 mock the owner drafted the Lions
# DST, CBS sent `cbs:1910`, and the /draft/ws handler died with `KeyError: 'cbs:1910'`. All 32
# defenses were (and are) absent from the CBS crosswalk, so on draft night this is guaranteed the
# moment a defense is drafted — and the roster never shrinks, so the engine stays dead.
#
# Skipping is the only implementable repair: an unresolved id carries no position, so it cannot be
# assigned to a slot or priced. The slot it should have filled simply reads empty, which the
# phantom logic already handles. Five other call sites in the engine already spell this guard
# `if pid in context.position` (recommend.py:190/401, risk.py:132, analytics.py:254,
# precompute.py:239); optimize.py never got it.

UNRESOLVED = "cbs:1910"  # the Detroit Lions DST, verbatim from the live crash


def _known_roster() -> tuple[list[str], dict[str, float], dict[str, Position]]:
    ids = ["qb1", "rb1", "wr1", "te1"]
    mu = {"qb1": 300.0, "rb1": 220.0, "wr1": 210.0, "te1": 160.0}
    position = {
        "qb1": Position.QB,
        "rb1": Position.RB,
        "wr1": Position.WR,
        "te1": Position.TE,
    }
    return ids, mu, position


def test_an_unresolved_roster_id_does_not_crash_the_lineup() -> None:
    """The live failure, reduced. Before the guard this raised KeyError: 'cbs:1910'."""
    ids, mu, position = _known_roster()
    clean = lineup_value(ids, mu, position, BASELINES, _slots())
    dirty = lineup_value([*ids, UNRESOLVED], mu, position, BASELINES, _slots())
    assert dirty == clean


def test_the_hungarian_verification_path_survives_the_same_id() -> None:
    """The greedy is the hot path, but the Hungarian path takes the same roster and indexed the
    same two dicts unguarded (optimize.py:206). Fixing only the greedy would move the crash."""
    ids, mu, position = _known_roster()
    clean = lineup_value_hungarian(ids, mu, position, BASELINES, _slots())
    dirty = lineup_value_hungarian([*ids, UNRESOLVED], mu, position, BASELINES, _slots())
    assert dirty == clean


def test_greedy_and_hungarian_still_agree_with_an_unresolved_id() -> None:
    """The agreement property this module rests on must survive the guard, or the two paths have
    silently diverged on exactly the input that caused the outage."""
    ids, mu, position = _known_roster()
    roster = [*ids, UNRESOLVED]
    assert lineup_value(roster, mu, position, BASELINES, _slots()) == pytest.approx(
        lineup_value_hungarian(roster, mu, position, BASELINES, _slots())
    )


def test_an_id_present_in_position_but_missing_from_mu_is_also_survived() -> None:
    """Half-resolved is still unusable: the crash site reads BOTH dicts on the same line."""
    ids, mu, position = _known_roster()
    position_with = {**position, UNRESOLVED: Position.DST}  # position known, mu absent
    clean = lineup_value(ids, mu, position, BASELINES, _slots())
    assert lineup_value([*ids, UNRESOLVED], mu, position_with, BASELINES, _slots()) == clean


def test_the_dropped_id_is_logged_rather_than_silently_swallowed() -> None:
    """A roster player vanishing from the lineup with no trace is how this stays invisible for
    another twelve tiers. The id must be named."""
    from structlog.testing import capture_logs

    ids, mu, position = _known_roster()
    with capture_logs() as logs:
        lineup_value([*ids, UNRESOLVED], mu, position, BASELINES, _slots())
    dropped = [entry for entry in logs if "unresolved" in entry.get("event", "")]
    assert dropped, f"no warning naming the dropped id; got {logs}"
    assert UNRESOLVED in str(dropped[0])


def test_marginal_lineup_value_survives_an_unresolved_roster_id() -> None:
    """The caller the live path actually uses (recommend.py) goes through marginal_lineup_value."""
    ids, mu, position = _known_roster()
    mu_c = {**mu, "wr2": 205.0}
    pos_c = {**position, "wr2": Position.WR}
    value = marginal_lineup_value("wr2", [*ids, UNRESOLVED], mu_c, pos_c, BASELINES, _slots())
    assert value >= 0.0
