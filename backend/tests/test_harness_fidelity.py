"""The harness must be able to MEASURE the vector it is tuning.

The fourth instance of this project's recurring defect, and every one of them was invisible for
the same reason: the thing that looked healthy (a map SIZE, a roster COUNT, a green suite) is not
the thing that matters.

* **Tier 4** — both fixture pools were params-blind: kappa, alpha AND lambda switched off together
  left a bit-identical roster in 96/96 cells, so the Optuna study maximised a constant.
* **Tier 5** — alpha multiplied a ``cliff_bonus`` map with 293 entries, every one of them 0.0.
* **Tier 6** — the three positional modifiers were advertised in the config and priced by nothing.
* **Tier 8** — ``ScoreAgent``, the agent every E2/E6 number is produced by, read neither
  ``lambda_slot_override`` nor ``punt_guard``. Measured 2026-08-07 over 12 slots x 5 seeds:
  sign-flipping the override changed **0 of 60** rosters and disabling the punt guard changed
  **0 of 60**, while doubling ``lambda_schedule`` and zeroing ``alpha`` each changed **60 of 60**.
  So Tier 7's closing instruction — get E2/E6 evidence with ``--replicates >= 3`` before touching
  ``lambda_slot_override`` — was impossible to satisfy.
* **Tier 9** — E6 itself, i.e. the GATE rather than the pool or the agent.
  ``scripts/run_tournament.py`` had no ``--replicates``, so every E6 number this project has
  published (including Tier 8's 5.5x championship inversion) came from a SINGLE seed block, and
  ``run_tournament`` passed no ``slot_noise`` so its ``beats`` gate used the strict min-slot leg
  Tier 6 measured as "not discriminating, it was sampling". The engine defect that hid behind it —
  ``lambda_slot_override`` paying **+18.69** for a zero-MLV tight end in **round 3**, not round 15,
  because a one-slot position can never be ``NORMAL`` — was sitting in the numbers for a whole tier.

* **Tier 10** — the OBJECTIVE, and the ranking underneath it. ``mean_lineup_value_objective``
  scores the optimal nine under fixed ``mu``, so it prices a bench player at exactly **0** — 8 of
  this league's 17 picks. It therefore could not see that once the starting nine is full every
  remaining candidate scores exactly ``0.0`` (MLV 0, ``kappa*max(0,VONA)`` clamped because
  ``expected_best_available`` is never negative, cliff 0 below replacement, ``lambda`` 0 for a
  SURPLUS position) and the ranking degenerated to ``context.mu`` insertion order. Measured on the
  real board: **180 of 180** candidates tied at round 14 and the #1 recommendation was **81.4**
  projected points worse than the best player it tied with. Under ``override_off`` that objective
  reported the engine as the BEST points-scorer in the field while it drafted half its roster in
  dictionary order.

* **Tier 11** — the OBJECTIVE again, in a different way, and this time pre-empted rather than
  discovered. Tier 11 adds a week axis, so before quoting any number from it the same question has
  to be asked of the new objective: can it SEE a bye conflict? a same-team stack? a handcuff? Two
  of those three come out yes and one comes out **no**, and the no is a measurement rather than an
  omission — see ``test_the_weekly_objective_cannot_see_a_handcuff``.

This test asks the only question that catches all five: change the knob, does any pick move?
Tier 10 adds the sixth question, which no knob can ask: change nothing but the ORDER the pool
arrives in — does any pick move? Tier 11 adds the seventh, asked of the objective rather than the
agent: change the ROSTER in a way the term would care about — does the objective's number move?
"""

from __future__ import annotations

import pytest

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.config import EngineParams
from jaaffl.domain import Position
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    simulate_draft,
)

SEEDS = (1001, 1002, 1003, 1004, 1005)
TEAMS = 12


def _rosters(params: EngineParams) -> list[tuple[str, ...]]:
    """Every (slot, seed) roster our agent drafts under ``params``, as comparable tuples."""
    ctx = demo_sim_context()
    return [
        tuple(
            simulate_draft(
                ctx,
                our_slot=slot,
                our_agent=ScoreAgent(params),
                opponents=[NeedBasedAgent(), AdpNoiseAgent()],
                seed=seed,
                teams=TEAMS,
            )[slot]
        )
        for slot in range(TEAMS)
        for seed in SEEDS
    ]


def _mutate(base: EngineParams, **changes: object) -> EngineParams:
    return EngineParams.model_validate({**base.model_dump(), **changes})


@pytest.mark.parametrize(
    ("knob", "changes"),
    [
        (
            "lambda_slot_override",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": -2.0,
                    "surplus_stash_ceiling": 2.0,
                }
            },
        ),
        # Tier 9: the two halves are also measured SEPARATELY — surplus alone buys +0.0060 win
        # probability, floor alone +0.0566 but −6.9 points, both together +0.1003 — so the
        # "not separable" finding rests on arms the combined case above cannot keep visible.
        (
            "lambda_slot_override.surplus_stash_ceiling",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": 0.4,
                    "surplus_stash_ceiling": 0.0,
                }
            },
        ),
        (
            "lambda_slot_override.last_startable_slot_floor",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": 0.0,
                    "surplus_stash_ceiling": -0.4,
                }
            },
        ),
        ("punt_guard", {"punt_guard": {"enabled": False, "stream_round": {}}}),
        # Controls: knobs the harness was already measured to price, so a null result above
        # cannot be blamed on the experiment.
        ("alpha", {"alpha": 0.0}),
        (
            "lambda_schedule",
            {
                "lambda_schedule": [
                    {"rounds": [1, 2], "lambda": 0.6},
                    {"rounds": [3, 6], "lambda": 0.4},
                    {"rounds": [7, 9], "lambda": 0.0},
                    {"rounds": [10, 13], "lambda": -0.6},
                    {"rounds": [14, 17], "lambda": -0.8},
                ]
            },
        ),
    ],
)
def test_the_harness_can_see_every_knob_it_tunes(knob: str, changes: dict) -> None:
    """Drive each knob to an extreme and require at least one simulated pick to move."""
    base = committed_engine_params()
    before, after = _rosters(base), _rosters(_mutate(base, **changes))
    moved = sum(1 for a, b in zip(before, after, strict=True) if a != b)
    assert moved > 0, (
        f"{knob} cannot change a single pick across {len(before)} simulated drafts — "
        "the harness is blind to it, so no measurement of it means anything"
    )


class _ReversedPool:
    """The SHIPPED agent, handed the same pool in the opposite order. No scoring logic here."""

    def __init__(self, inner: ScoreAgent) -> None:
        self._inner = inner

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        return self._inner.pick(list(available)[::-1], my_roster, ctx, rng)


def test_the_harness_measures_a_decision_not_an_ordering() -> None:
    """Every knob above can be measurable and the measurement still be worthless if the PICK is
    decided by the order the pool arrives in.

    Measured on the real board 2026-08-09, presenting the identical pool reversed moved **23.5%**
    of our picks under the committed config and **45.8%** with ``lambda_slot_override`` zeroed,
    because once the starting nine is full every candidate scores exactly 0.0 and ``min()`` returns
    whichever one happened to come first. The bench that produced averaged **-121.6** VBD per
    player against plain VBD's -38.0, and that gap was the whole of the residual Tier 9 could not
    explain.
    """
    base = committed_engine_params()
    ctx = demo_sim_context()
    moved = 0
    for slot in range(TEAMS):
        for seed in SEEDS:
            rosters = [
                simulate_draft(
                    ctx,
                    our_slot=slot,
                    our_agent=agent,
                    opponents=[NeedBasedAgent(), AdpNoiseAgent()],
                    seed=seed,
                    teams=TEAMS,
                )[slot]
                for agent in (ScoreAgent(base), _ReversedPool(ScoreAgent(base)))
            ]
            moved += rosters[0] != rosters[1]
    assert moved == 0, (
        f"{moved} of {TEAMS * len(SEEDS)} simulated rosters change when the pool is merely "
        "REVERSED — the agent is ranking by list order, so every number measured from it is an "
        "artifact of how the pool was enumerated"
    )


# ---------------------------------------------------------------------------------------------
# Tier 11: the same question, asked of the OBJECTIVE. Each of the three modifiers
# `recommend._positional_modifiers` has declared for six tiers gets a verdict, and the verdict is
# a test rather than a paragraph.
# ---------------------------------------------------------------------------------------------

_WEEKLY_DRAWS = 4000


def _weekly_ctx(**overrides):
    """The fixture pool with the REAL board's mu/sigma ratios, plus explicit byes/teams.

    The demo pool cannot carry a weekly model faithfully: its synthetic value curve is far steeper
    against the same real sigma anchors (median mu/sigma at WR 3.9 against the real board's 2.4), so
    the absence process eats almost all of its receivers' production variance. Measured 2026-08-09,
    8 of its 178 players degenerate to zero weekly variance where 0 of 305 do on the real board.
    """
    import dataclasses

    ratios = {
        Position.QB: 1.59,
        Position.RB: 2.06,
        Position.WR: 2.41,
        Position.TE: 2.21,
        Position.K: 4.04,
        Position.DST: 4.29,
    }
    ctx = demo_sim_context()
    return dataclasses.replace(
        ctx,
        sigma={pid: ctx.value[pid] / ratios[ctx.position[pid]] for pid in ctx.value},
        **overrides,
    )


def _weekly_points(roster, ctx, *, seed: int = 21) -> float:
    from jaaffl.engine.weekly import WeeklyModel, weekly_lineup_totals

    model = WeeklyModel.from_context(ctx)
    assert not model.degenerate, "a degenerate player has no weekly variance and no correlation"
    outcomes = model.sample(n_draws=_WEEKLY_DRAWS, seed=seed)
    return float(weekly_lineup_totals(roster, outcomes, ctx).mean())


def test_the_weekly_objective_can_see_a_bye_conflict() -> None:
    """``bye_stack`` — VERDICT: **MEASURABLE**.

    Two rosters with IDENTICAL season marginals; one stacks all three starting receivers on the
    same bye week. If the objective cannot separate them it has no week axis, whatever the code
    says. ``mean_lineup_value_objective`` scores both identically by construction, because it never
    asks what week it is — which is asserted here so the comparison is not vacuous.
    """
    from jaaffl.calibrate.tune import mean_lineup_value_objective

    roster = ["qb0", "rb0", "rb1", "wr0", "wr1", "wr2", "te0", "k0", "dst0", "wr3"]
    spread = _weekly_ctx(bye_week={"wr0": 5, "wr1": 8, "wr2": 11, "wr3": 14})
    stacked = _weekly_ctx(bye_week={"wr0": 5, "wr1": 5, "wr2": 5, "wr3": 14})

    season_spread = mean_lineup_value_objective([roster], our_slot=0, ctx=spread, seed=1)
    season_stacked = mean_lineup_value_objective([roster], our_slot=0, ctx=stacked, seed=1)
    assert season_spread == pytest.approx(season_stacked), (
        "the season objective must be blind to this, or the comparison below proves nothing"
    )
    assert _weekly_points(roster, spread) > _weekly_points(roster, stacked) + 1.0


def test_the_weekly_objective_can_see_a_same_team_stack() -> None:
    """A quarterback paired with his own receivers — VERDICT: **MEASURABLE**.

    Not one of the three declared modifiers, but the mechanism the measured correlation exists to
    carry, so it is pinned here too. Two rosters with identical marginals; one puts the QB and three
    receivers on the same team. Correlation is the only thing that can separate them, and it
    separates them on VARIANCE rather than mean — which is why a championship objective can see it
    and a points objective cannot.
    """
    import numpy as np

    from jaaffl.engine.weekly import WeeklyModel, weekly_lineup_totals

    roster = ["qb0", "rb0", "rb1", "wr0", "wr1", "wr2", "te0", "k0", "dst0"]
    spread = {"qb0": "KC", "wr0": "SF", "wr1": "BUF", "wr2": "DAL"}
    stacked = {"qb0": "KC", "wr0": "KC", "wr1": "KC", "wr2": "KC"}
    sds = []
    for team in (spread, stacked):
        ctx = _weekly_ctx(nfl_team=team)
        model = WeeklyModel.from_context(ctx)
        totals = weekly_lineup_totals(roster, model.sample(n_draws=_WEEKLY_DRAWS, seed=31), ctx)
        sds.append(float(np.std(totals)))
    assert sds[1] > sds[0] * 1.02, (
        f"stacking a QB with his own receivers moved the season SD from {sds[0]:.1f} to "
        f"{sds[1]:.1f} — the measured same-team correlation is not reaching the objective"
    )


def test_the_weekly_objective_cannot_see_a_handcuff() -> None:
    """``handcuff_synergy`` — VERDICT: **NOT MEASURABLE**, and the reason is measured, not assumed.

    A handcuff is a REGIME effect. Measured on nflverse ff_opportunity 2023-2025, the second running
    back on a team scores **x1.96 / x1.61 / x2.38** as much in the weeks the first is absent
    (+4.31 / +2.83 / +7.05 points per week, each 4-7 standard errors clear of the present-week
    mean). The mechanism is real and large.

    But the UNCONDITIONAL same-team RB x RB correlation is **-0.0211 (se 0.0156, not significant)**,
    and a jointly-Gaussian model calibrated to that implies a conditional lift of
    ``-rho * phi(c)/Phi(c) ~= +0.03`` standard deviations. So no correlation table, however careful,
    can carry a handcuff: the two are different objects, and adding a week axis did not change that.

    Consequence: a bench RB behind OUR OWN starter is worth exactly what any other bench RB of equal
    mu is worth, so ``handcuff_synergy`` stays unimplemented — this project does not ship a
    coefficient its own harness cannot price.

    This test pins the NEGATIVE so a later tier cannot quietly implement the modifier on the
    assumption that the week axis fixed it. Making it measurable needs a workload-transfer process
    (production redistributed to a group's survivors when a member is absent), which is named in
    ``ROADMAP.md`` and deliberately NOT built here on a guess.
    """
    from jaaffl.engine.weekly import WeeklyModel

    # Tested on the MECHANISM rather than through a roster's total, deliberately. Comparing two
    # bench backs costs a Monte-Carlo standard error of a few points and the effect being looked for
    # is smaller than that, so a roster-level null would be "no resolution" dressed up as "no
    # effect". The statistic below is the one measured on the real data, over 10^5 player-weeks.
    ctx = _weekly_ctx(
        nfl_team={"rb0": "SF", "rb1": "SF", "rb2": "SF"},
        # Byes, because under the honest bye-only information set they are the ONLY thing a
        # bench player can cover — without them the "he is worth something" leg is vacuous.
        bye_week={"rb0": 5, "rb1": 9, "wr0": 7, "wr1": 11, "wr2": 13, "qb0": 6, "te0": 10},
    )
    model = WeeklyModel.from_context(ctx)
    outcomes = model.sample(n_draws=_WEEKLY_DRAWS, seed=41)
    starter, backup = outcomes.index["rb0"], outcomes.index["rb1"]

    starter_out = ~outcomes.available[:, :, starter]
    backup_in = outcomes.available[:, :, backup]
    when_starter_out = outcomes.weekly[:, :, backup][starter_out & backup_in]
    when_starter_in = outcomes.weekly[:, :, backup][~starter_out & backup_in]

    assert when_starter_out.size > 1000 and when_starter_in.size > 1000
    ratio = float(when_starter_out.mean() / when_starter_in.mean())
    assert ratio == pytest.approx(1.0, abs=0.05), (
        f"the backup scores {ratio:.2f}x as much when the starter is out; this model draws absence "
        "independently, so a ratio away from 1.0 means a workload-transfer process was added and "
        "the verdict in this docstring needs re-measuring against the real x1.6-x2.4"
    )

    # ...and a bench player IS worth something here, so the null above is about the HANDCUFF and not
    # about the objective pricing every bench player at nothing.
    #
    # A BACKUP QUARTERBACK, deliberately. Under the honest bye-only information set a bench player's
    # entire value is bye coverage, and qb1 is the only man who can fill the single QB slot in
    # qb0's bye week — so he is worth something for a reason that is easy to state. Two earlier
    # drafts of this leg were wrong: one used a "bench" back who walked straight into the flex
    # (measuring the value gradient), and the next used a third RB whom the per-week ranking
    # correctly never starts (measuring zero). The season-objective guard rules out the first.
    from jaaffl.calibrate.tune import mean_lineup_value_objective

    nine = ["qb0", "rb0", "rb1", "wr0", "wr1", "wr2", "te0", "k0", "dst0"]
    ten = [*nine, "qb1"]
    season_gain = mean_lineup_value_objective(
        [ten], our_slot=0, ctx=ctx, seed=1
    ) - mean_lineup_value_objective([nine], our_slot=0, ctx=ctx, seed=1)
    assert season_gain == pytest.approx(0.0), (
        f"qb1 improves the starting nine by {season_gain:.2f}, so he is not a bench player and "
        "this assertion would be measuring the value gradient"
    )
    assert _weekly_points(ten, ctx) - _weekly_points(nine, ctx) > 5.0


def test_the_weekly_objective_cannot_see_strength_of_schedule() -> None:
    """``sos`` — VERDICT: **NOT MEASURABLE**, and nothing in this tier changed that.

    A week axis is necessary for strength of schedule and nowhere near sufficient: pricing it needs
    a per-opponent defensive-strength signal, and neither the board (``DraftContext``) nor the
    weekly model carries one. ``WeeklyModel`` knows a player's team only in order to group his
    correlation, and knows nothing at all about who he plays in week 7.

    Pinned as a structural fact rather than a measurement: there is no opponent axis to attach a
    coefficient to, so a tuned ``sos`` would be tuned to noise — Tier 4's defect exactly.

    Checked by scanning the FIELD NAMES of both the model and the context rather than probing two
    spellings, so any opponent/defense/schedule data arriving on either side trips it.
    """
    import dataclasses

    from jaaffl.engine.weekly import WeeklyModel

    ctx = _weekly_ctx()
    names = {f.name for f in dataclasses.fields(WeeklyModel)} | {
        f.name for f in dataclasses.fields(ctx)
    }
    smells = {n for n in names if any(w in n for w in ("opponent", "defense", "schedule", "sos"))}
    assert not smells, f"opponent-quality data appeared ({smells}); re-measure the sos verdict"
    # ...and the one team-ish field that DOES exist is used only to group correlation.
    assert "nfl_team" in names
    WeeklyModel.from_context(ctx)


class TestInstanceEight_TheFixtureSuppliedWhatTheWiringDropped:
    """Five tiers asked "change the knob, does a pick move?". Tier 10 asked "change the pool
    ORDER, does a pick move?". Tier 11 asked "change the roster, does the OBJECTIVE move?".

    Tier 12 asks the question none of those can: **does the engine get this input from the WIRING,
    or from the fixture?** ``engine_fixtures.make_context()`` defaults to
    ``jaaffl_settings(draft_order=teams(12))``, so every engine test in this suite — including
    Tier 3's own ``test_my_team_slot.py``, via ``test_api._primed_engine()`` — handed the engine a
    draft order that ``resolve_league_settings`` has never produced and, by its own docstring,
    never will. ``test_precompute.py`` even PINS ``ctx.settings.draft_order is None``. The
    production behaviour was asserted in one file, fixtured around in another, and nothing
    compared them.
    """

    def test_the_default_test_fixture_supplies_an_order_the_live_wiring_cannot(self) -> None:
        from jaaffl.league.constitution import resolve_league_settings
        from tests.engine_fixtures import make_context

        fixture = make_context([{"pid": "rb0", "pos": Position.RB, "mu": 300.0}])
        assert fixture.settings.draft_order is not None, "fixture no longer supplies an order"
        assert resolve_league_settings("cbs-live").draft_order is None
        # The gap itself, asserted. If a future change makes the constitution carry an order this
        # fails and the ROADMAP's instance-eight note has to be rewritten — the correct outcome,
        # not a nuisance.

    def test_the_survival_model_is_reachable_from_the_state_alone(self) -> None:
        """The routing this tier added: given a LIVE-WIRING context (no order on the settings) the
        engine still reaches 'my_slot', because the ROOM's order arrives on the DraftState."""
        from jaaffl.domain import DraftState
        from jaaffl.engine.recommend import recommend
        from jaaffl.league.constitution import resolve_league_settings
        from tests.engine_fixtures import make_context

        specs = [
            {
                "pid": f"rb{i}",
                "pos": Position.RB,
                "mu": 300.0 - 5 * i,
                "adp": float(i + 1),
                "sd": 6.0,
                "ecr": float(i + 1),
            }
            for i in range(24)
        ]
        ctx = make_context(specs, settings=resolve_league_settings("cbs-live"))
        state = DraftState(
            league_id="cbs-live",
            current_overall_pick=13,
            my_team_id="7",
            draft_order=[str(i) for i in range(1, 13)],
        )
        assert recommend(state, ctx, ctx.params, limit=10).survival_basis == "my_slot"

    def test_the_calibration_harness_never_reads_a_draft_order(self) -> None:
        """Tier 11 superseded every real-board number when the harness changed. This tier's fix
        must NOT: ``calibrate/tune.py`` builds a ``SimContext`` and ``simulate.py`` derives its own
        slot schedule, so neither reads ``settings.draft_order``.

        Asserted structurally rather than assumed, because "this cannot possibly move the numbers"
        is precisely how Tier 10's config/code coupling was missed. If this fails, STOP: the tier
        does move the tournament numbers and the ROADMAP block must say so and re-measure.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "jaaffl" / "calibrate"
        offenders = [
            path.name
            for path in sorted(root.rglob("*.py"))
            if "draft_order" in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"calibrate reads draft_order in {offenders}"


class TestInstanceNine_TheLatencyTestMeasuredTheWrongMOMENT:
    """The rehearsal instrumentation, not a unit test, found that the FIRST recompute of a draft
    cost 205 ms against every later one's 6 ms — because ``engine/opponents.py`` and
    ``engine/optimize.py`` import numpy and scipy lazily, inside the hot path.

    ``test_engine_latency.py`` measures **p95 over repeated calls in an already-warm process** and
    calls that "the pick-1 worst case". One 268 ms sample among nineteen 0.5 ms ones does not move
    p95 at all, and by the time it runs some earlier test has usually imported scipy anyway. The
    defect lived entirely in call #1, which is the owner's first pick.

    The structural fix is pinned in ``tests/test_cold_start_latency.py`` (a fresh interpreter, and
    an "imports nothing" invariant rather than a millisecond threshold). This asserts the seam.
    """

    def test_precompute_is_where_the_hot_paths_imports_get_paid(self) -> None:
        import inspect

        from jaaffl.engine import precompute

        source = inspect.getsource(precompute)
        assert "warm_hot_path()" in source, (
            "precompute no longer warms the hot path's lazy imports; the first pick of the draft "
            "pays ~265ms of scipy/numpy import against a <200ms budget and a live clock"
        )
