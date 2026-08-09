"""The weekly, correlated, absence-aware season model (Tier 11) — its own guards.

``simulate.sample_season_outcomes`` draws ONE independent season total per player. This module's
job is to put a week axis and a joint distribution under the objective without moving any player's
season marginal, so that a difference between the two objectives is attributable to STRUCTURE and
never to a changed scale. Every guard below exists because some part of that sentence could quietly
stop being true.
"""

from __future__ import annotations

import math

import pytest

from jaaffl.calibrate.pools import demo_sim_context
from jaaffl.domain import Position
from jaaffl.engine.weekly import (
    FORESIGHT_ABSENCE,
    FORESIGHT_REALIZED,
    REGULAR_SEASON_WEEKS,
    SAME_TEAM_RHO,
    ZERO_PRODUCTION_RATE,
    WeeklyModel,
    weekly_lineup_totals,
)


def _model(**kw) -> WeeklyModel:
    ctx = demo_sim_context()
    return WeeklyModel.from_context(ctx, **kw)


def test_weekly_totals_reproduce_the_season_marginal() -> None:
    """THE comparability guarantee: summing the weekly draws must reproduce each player's
    ``(mu, sigma)``.

    Without it the weekly objective is on a different scale from the season objective and no
    comparison between them means anything — which is exactly the trap Tier 9 fell into when the
    fixture and the real board turned out to disagree.
    """
    ctx = _realistic_ctx()
    model = WeeklyModel.from_context(ctx)
    assert not model.degenerate, (
        "a clamped player's season sigma EXCEEDS the board's, so the guarantee this test names "
        f"is false for {len(model.degenerate)} players it does not sample"
    )
    outcomes = model.sample(n_draws=40_000, seed=7)
    totals = outcomes.season_totals()
    for pid in ("rb0", "wr10", "te3", "k3", "dst2", "qb8"):
        i = outcomes.index[pid]
        assert totals[:, i].mean() == pytest.approx(ctx.value[pid], rel=0.03), pid
        assert totals[:, i].std() == pytest.approx(ctx.sigma[pid], rel=0.06), pid


def test_a_bye_week_is_a_hard_zero() -> None:
    """``bye_stack`` has nothing to attach to without this — it is the whole week axis in one
    assertion. Byes come from ``league/schedule.py``, a calendar fact, never a projection."""
    model = _model(bye_week={"rb0": 5, "wr0": 5})
    outcomes = model.sample(n_draws=64, seed=1)
    for pid in ("rb0", "wr0"):
        i = outcomes.index[pid]
        assert (outcomes.weekly[:, 4, i] == 0.0).all(), f"{pid} played in his bye week"
        # ...and he is NOT silently zeroed everywhere else.
        assert (outcomes.weekly[:, :, i] != 0.0).any()


def test_same_team_qb_and_pass_catcher_are_correlated_but_two_receivers_are_not() -> None:
    """The measured structure, pinned — on the PRODUCTION SHOCK, in weeks everyone played.

    nflverse 2023-2025, conditional on both playing: QB x WR +0.268, QB x TE +0.232, WR x WR +0.010,
    different-team control -0.013. A single shared "team factor" — the obvious way to write this —
    would give WR x WR the same +0.27 it gives QB x WR, and this test is what refutes it. The entire
    same-team structure in the data is the quarterback.
    """
    import numpy as np

    ctx = demo_sim_context()
    team = {"qb0": "KC", "wr0": "KC", "wr1": "KC", "rb0": "SF"}
    model = _model(team=team)
    # VACUITY GUARD. A player whose sigma cannot absorb the absence process gets production_sd 0,
    # and a constant is correlated with nothing — the first draft of this test used exactly such a
    # pair and measured +0.03 against an expected +0.27.
    for pid in ("qb0", "wr0", "wr1", "rb0"):
        assert pid not in model.degenerate, f"{pid} has no production variance; test is vacuous"

    outcomes = model.sample(n_draws=20_000, seed=3)
    present = outcomes.available

    def shock_corr(a: str, b: str) -> float:
        """Correlation of the PRODUCTION SHOCK — measured where both players actually played,
        matching how ``SAME_TEAM_RHO`` was estimated."""
        i, j = outcomes.index[a], outcomes.index[b]
        both = present[:, 0, i] & present[:, 0, j]
        x = outcomes.weekly[both, 0, i]
        y = outcomes.weekly[both, 0, j]
        return float(np.corrcoef(x, y)[0, 1])

    expected = SAME_TEAM_RHO[frozenset({Position.QB, Position.WR})]
    assert shock_corr("qb0", "wr0") == pytest.approx(expected, abs=0.05)
    assert abs(shock_corr("wr0", "wr1")) < 0.06
    assert abs(shock_corr("qb0", "rb0")) < 0.06  # different teams -> independent
    assert ctx.position["qb0"] is Position.QB


def _realistic_ctx():
    """A tiny pool with the REAL board's mu/sigma ratios, which the demo fixture does not have.

    Measured 2026-08-09, median mu/sigma per position — real board vs demo fixture:
    QB 1.59 / 1.64 · RB 2.06 / 2.72 · WR **2.41 / 3.90** · TE **2.21 / 5.20** · K 4.04 / 4.56.
    The fixture's synthetic value curve is far steeper against the same (real) sigma anchors, which
    is why the absence process eats almost all of its receivers' production variance. Tests that
    depend on the SIZE of the weekly variance therefore use this instead of the fixture.
    """
    import dataclasses

    ctx = demo_sim_context()
    ratios = {
        Position.QB: 1.59,
        Position.RB: 2.06,
        Position.WR: 2.41,
        Position.TE: 2.21,
        Position.K: 4.04,
        Position.DST: 4.29,
    }
    sigma = {pid: ctx.value[pid] / ratios[ctx.position[pid]] for pid in ctx.value}
    return dataclasses.replace(ctx, sigma=sigma)


def test_the_absence_aware_correlation_falls_out_at_the_independently_measured_level() -> None:
    """An OUT-OF-SAMPLE check on the assembled model, and the reason to trust it.

    ``SAME_TEAM_RHO`` is calibrated on the CONDITIONAL correlation (weeks both players played). The
    ABSENCE-AWARE correlation — what a lineup records, zeros included — was measured *separately*
    and is an input nowhere: QB x WR **+0.1793**, QB x TE +0.1496.

    The model is never told that number. It emerges, because independent absence attenuates the
    shock. Run on the REAL board 2026-08-09 the attenuation is 0.737 over 66 same-team QB/WR pairs,
    so ``0.2681 x 0.737 = 0.1975`` against a measured +0.1793 — two independent estimates of the
    same quantity, agreeing to 0.02, with the model told only one of them.

    Uses ``_realistic_ctx`` because the demo fixture cannot carry this: there the attenuation is
    0.171 and the same check would read +0.046. That is a fixture limitation, pinned by
    ``test_players_whose_sigma_cannot_absorb_the_absence_process_are_reported``.
    """
    import numpy as np

    ctx = _realistic_ctx()
    model = WeeklyModel.from_context(ctx, team={"qb0": "KC", "wr0": "KC"})
    assert not model.degenerate, "a realistic mu/sigma must not degenerate anywhere"
    outcomes = model.sample(n_draws=40_000, seed=17)
    i, j = outcomes.index["qb0"], outcomes.index["wr0"]
    observed = float(np.corrcoef(outcomes.weekly[:, 0, i], outcomes.weekly[:, 0, j])[0, 1])
    assert observed == pytest.approx(0.1793, abs=0.06), (
        f"absence-aware QBxWR came out at {observed:+.4f}; the independently measured value is "
        "+0.1793 and the model was never told it"
    )


def test_players_whose_sigma_cannot_absorb_the_absence_process_are_reported() -> None:
    """The clamp must never be silent.

    ``s**2 = (sigma**2/n - q(1-q)m**2)/(1-q)`` can solve negative when the board's sigma is small
    relative to mu — the absence process alone would then exceed the season variance the marginal
    must preserve. Those players are clamped to a deterministic weekly score, which also makes them
    uncorrelated with everyone, and a silently variance-free player is exactly the degradation this
    project keeps finding six tiers late.

    Measured 2026-08-09: **0 of 305** on the real board; **8 of 178** on this fixture (6 TE, 2 WR),
    whose synthetic value curve is steeper against the same real sigma anchors — median mu/sigma at
    WR is 3.9 here against 2.4 on the real board. That is a FIXTURE limitation, recorded rather than
    papered over.
    """
    model = _model()
    ctx = demo_sim_context()
    assert model.degenerate, (
        "the fixture used to degenerate 8 players; if it no longer does, say so"
    )
    assert len(model.degenerate) < len(ctx.value) // 10
    for pid in model.degenerate:
        assert model.production_sd[pid] == 0.0
        assert ctx.sigma[pid] > 0.0  # they DO carry a season sigma; it just cannot absorb absence


def test_a_non_psd_correlation_table_raises_rather_than_being_repaired() -> None:
    """A silent nearest-PSD projection is an unmeasured model change wearing a numerical-hygiene
    costume. Measured on the real board the worst minimum eigenvalue is 0.1698, so this never fires
    in practice — which is exactly why it must fail loudly if it ever does."""
    ctx = demo_sim_context()
    impossible = dict(SAME_TEAM_RHO)
    impossible[frozenset({Position.WR})] = -0.9  # 3+ receivers cannot all be -0.9 correlated
    # Match OUR message, not "not positive definite": `numpy.linalg.LinAlgError` subclasses
    # ValueError and its own text is "Matrix is not positive definite", so the obvious matcher
    # passes against numpy even with this guard deleted. Mutation caught exactly that.
    with pytest.raises(ValueError, match="min eigenvalue"):
        WeeklyModel.from_context(
            ctx, team={f"wr{i}": "KC" for i in range(4)}, same_team_rho=impossible
        )


def test_zero_production_weeks_happen_at_the_measured_rate() -> None:
    """The absence process, pinned to what was measured rather than to a feel: QB 0.173, RB 0.173,
    WR 0.234, TE 0.289 zero-production weeks; K and DST 0.0 because ``ff_opportunity`` covers skill
    positions only and fabricating a rate is the defect this project keeps finding."""
    model = _model()
    outcomes = model.sample(n_draws=4_000, seed=11)
    ctx = demo_sim_context()
    for pid, pos in (("rb0", Position.RB), ("te0", Position.TE), ("k0", Position.K)):
        i = outcomes.index[pid]
        rate = float((~outcomes.available[:, :, i]).mean())
        assert rate == pytest.approx(ZERO_PRODUCTION_RATE[pos], abs=0.02), pid
    assert ctx.position["k0"] is Position.K


def test_the_weekly_axis_is_the_real_calendar() -> None:
    """18 weeks — the span ``league/xep.py`` calls MAX_FANTASY_WEEK, not a number chosen here."""
    from jaaffl.league.xep import MAX_FANTASY_WEEK

    assert REGULAR_SEASON_WEEKS == MAX_FANTASY_WEEK
    assert _model().sample(n_draws=4, seed=0).weekly.shape[1] == REGULAR_SEASON_WEEKS


def test_sigma_week_is_the_inverse_of_the_transform_xep_already_ships() -> None:
    """``league/xep.py`` builds season sigma as ``pstdev(weekly residuals) * sqrt(17)``. Decomposing
    it back as ``sigma / sqrt(n)`` is therefore not an invention — it is that transform, inverted.
    With no absence process the identity is exact."""
    ctx = demo_sim_context()
    model = WeeklyModel.from_context(ctx, zero_production_rate=dict.fromkeys(Position, 0.0))
    weeks = REGULAR_SEASON_WEEKS
    assert model.production_sd["rb0"] == pytest.approx(ctx.sigma["rb0"] / math.sqrt(weeks))
    assert model.production_mean["rb0"] == pytest.approx(ctx.value["rb0"] / weeks)


# --------------------------------------------------------------------------------------------
# The ex-ante lineup rule
# --------------------------------------------------------------------------------------------


def _roster(ctx, counts: dict[Position, int]) -> list[str]:
    out: list[str] = []
    for pos, n in counts.items():
        ranked = sorted(
            (p for p in ctx.value if ctx.position[p] is pos), key=lambda p: -ctx.value[p]
        )
        out.extend(ranked[:n])
    return out


def test_the_default_lineup_setter_cannot_foresee_a_zero_production_week() -> None:
    """THE information-set guard, and it caught a real leak in this tier's own first draft.

    ``WeeklyOutcomes.available`` folds the bye calendar together with the DRAWN zero-production
    event. Ranking on it lets the manager know on Saturday exactly who will produce nothing on
    Sunday — which this module explicitly says is not knowable, because "zero production" counts a
    healthy receiver who saw no targets. The first version of ``weekly_lineup_totals`` did rank on
    it while its own docstring claimed "no hindsight anywhere", and code review measured roughly
    three quarters of the reported bench value coming from the leak.

    The default must therefore see ``plays`` (the bye calendar) and nothing else. Constructed so the
    two answers are forced apart: the higher-mu starter posts a zero-production week, so a foresight
    rule benches him and the honest rule starts him and eats it.
    """
    import dataclasses

    import numpy as np

    from jaaffl.engine.weekly import (
        FORESIGHT_ABSENCE,
        FORESIGHT_BYE,
        WeeklyOutcomes,
    )

    ctx = dataclasses.replace(demo_sim_context(), value={"qb0": 300.0, "qb1": 100.0})
    weekly = np.array([[[0.0, 40.0]]])  # qb0 produced nothing; qb1 posted 40
    available = np.array([[[False, True]]])  # ...and qb0's zero IS a zero-production week
    outcomes = WeeklyOutcomes(
        order=("qb0", "qb1"),
        index={"qb0": 0, "qb1": 1},
        weekly=weekly,
        available=available,
        plays=np.ones_like(weekly, dtype=bool),  # neither is on a bye
    )
    honest = weekly_lineup_totals(["qb0", "qb1"], outcomes, ctx, foresight=FORESIGHT_BYE)
    foresees = weekly_lineup_totals(["qb0", "qb1"], outcomes, ctx, foresight=FORESIGHT_ABSENCE)
    assert honest[0] == pytest.approx(0.0), "the default rule peeked at the zero-production draw"
    assert foresees[0] == pytest.approx(40.0)


def test_a_player_on_a_bye_is_never_started_even_under_the_honest_rule() -> None:
    """The bye IS knowable, so the honest rule must still route around it — otherwise "no
    foresight" would have collapsed into "no week axis"."""
    import dataclasses

    import numpy as np

    from jaaffl.engine.weekly import FORESIGHT_BYE, WeeklyOutcomes

    ctx = dataclasses.replace(demo_sim_context(), value={"qb0": 300.0, "qb1": 100.0})
    weekly = np.array([[[0.0, 40.0]]])
    outcomes = WeeklyOutcomes(
        order=("qb0", "qb1"),
        index={"qb0": 0, "qb1": 1},
        weekly=weekly,
        available=np.array([[[False, True]]]),
        plays=np.array([[[False, True]]]),  # qb0 is on his BYE, which the manager knows
    )
    assert weekly_lineup_totals(["qb0", "qb1"], outcomes, ctx, foresight=FORESIGHT_BYE)[
        0
    ] == pytest.approx(40.0)


def test_ex_ante_lineup_never_benefits_from_hindsight() -> None:
    """Starters are chosen BEFORE the week is played, by mu among the players available that week,
    and scored on what they realized. So the ex-ante total can never exceed the hindsight total on
    the same draw. That inequality is the whole reason this objective is a LOWER bound on bench
    value rather than the upper bound ``roster_season_values`` gives."""
    ctx = demo_sim_context()
    roster = _roster(
        ctx,
        {
            Position.QB: 2,
            Position.RB: 3,
            Position.WR: 4,
            Position.TE: 2,
            Position.K: 1,
            Position.DST: 1,
        },
    )
    outcomes = _model().sample(n_draws=200, seed=5)
    ex_ante = weekly_lineup_totals(roster, outcomes, ctx, foresight=FORESIGHT_ABSENCE)
    hindsight = weekly_lineup_totals(roster, outcomes, ctx, foresight=FORESIGHT_REALIZED)
    assert (ex_ante <= hindsight + 1e-9).all()
    assert (ex_ante < hindsight - 1e-9).any(), "hindsight is worth nothing here — check the fixture"


def test_the_ex_ante_lineup_starts_the_higher_mu_player_even_when_he_scored_less() -> None:
    """The one assertion that separates "ex ante" from "hindsight" at a DEDICATED slot.

    ``test_ex_ante_lineup_never_benefits_from_hindsight`` does not: mutation showed that ranking
    every dedicated slot by the realized week still leaves the two totals different (the flex rule
    reads the mode separately), so that test passed against a fully-hindsight selection. This one
    hand-builds the outcome so the LOWER-mu quarterback posts the better week — an ex-ante lineup
    must take the higher-mu one and eat the worse score.
    """
    import dataclasses

    import numpy as np

    from jaaffl.engine.weekly import WeeklyOutcomes

    ctx = dataclasses.replace(demo_sim_context(), value={"qb0": 300.0, "qb1": 100.0})
    order = ("qb0", "qb1")
    weekly = np.array([[[5.0, 90.0]]])  # 1 draw, 1 week: the cheap QB posts 90, the dear one 5
    outcomes = WeeklyOutcomes(
        order=order,
        index={"qb0": 0, "qb1": 1},
        weekly=weekly,
        available=np.ones_like(weekly, dtype=bool),
        plays=np.ones_like(weekly, dtype=bool),
    )
    ex_ante = weekly_lineup_totals(list(order), outcomes, ctx, foresight=FORESIGHT_ABSENCE)
    hindsight = weekly_lineup_totals(list(order), outcomes, ctx, foresight=FORESIGHT_REALIZED)
    assert ex_ante[0] == pytest.approx(5.0), "ex ante must start qb0 on mu and take his 5 points"
    assert hindsight[0] == pytest.approx(90.0), "hindsight must start qb1, who actually scored"


def test_with_no_byes_no_absence_and_no_variance_the_weekly_total_matches_lineup_value() -> None:
    """The reduction pin: at sigma = 0, q = 0 and no byes, the weekly sum must equal
    ``optimal_lineup_value``. It makes the new objective a strict GENERALISATION of the one it sits
    beside rather than a different scale that happens to look similar.
    """
    import dataclasses

    from jaaffl.engine.simulate import optimal_lineup_value

    ctx = dataclasses.replace(demo_sim_context(), sigma={})
    model = WeeklyModel.from_context(ctx, zero_production_rate=dict.fromkeys(Position, 0.0))
    outcomes = model.sample(n_draws=3, seed=2)
    roster = _roster(
        ctx,
        {
            Position.QB: 1,
            Position.RB: 2,
            Position.WR: 3,
            Position.TE: 1,
            Position.K: 1,
            Position.DST: 1,
        },
    )
    totals = weekly_lineup_totals(roster, outcomes, ctx, foresight=FORESIGHT_ABSENCE)
    assert totals == pytest.approx(optimal_lineup_value(roster, ctx), rel=1e-9)


def test_a_bench_player_is_worth_strictly_more_than_zero() -> None:
    """The bracketing this tier exists to narrow.

    ``mean_lineup_value_objective`` prices a 10th player at exactly 0.00 — 8 of this league's 17
    picks — because he cracks no starting slot under fixed mu. Under the weekly rule he covers byes
    and zero-production weeks, so he is worth strictly more than nothing WITHOUT any hindsight.
    """
    ctx = demo_sim_context()
    outcomes = _model(bye_week={"rb0": 5, "rb1": 9}).sample(n_draws=600, seed=13)
    nine = _roster(
        ctx,
        {
            Position.QB: 1,
            Position.RB: 2,
            Position.WR: 3,
            Position.TE: 1,
            Position.K: 1,
            Position.DST: 1,
        },
    )
    with_bench = [*nine, "rb2"]
    base = weekly_lineup_totals(nine, outcomes, ctx).mean()
    more = weekly_lineup_totals(with_bench, outcomes, ctx).mean()
    assert more > base + 1.0, f"the bench RB added only {more - base:.2f} points"
