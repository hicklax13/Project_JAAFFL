"""E2 — engine-param tuning (plan §9.2). Objective + promotion gate are pure/scipy; the Optuna
study is guarded by importorskip so CI's base install stays green.

The promotion gate NEVER regresses: a tuned vector is adopted only if it beats the frozen baseline
on a one-sided Wilcoxon across the 12 slots AND is non-negative at every slot.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from jaaffl.calibrate.tune import (
    WinProbabilityObjective,
    evaluate_params,
    objective_value,
    promotion_decision,
)
from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SimContext,
    VbdOnlyAgent,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _small_settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="L",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=1, starting=True),
            RosterSlot(
                slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1, starting=True
            ),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=1,
                starting=False,
            ),
        ],
    )


def _small_ctx() -> SimContext:
    """A modest pool (roster_size 5, ~120 players) — enough for a 12×5 = 60-pick draft, fast."""
    value, position, adp, adp_stdev = {}, {}, {}, {}
    plan = [(Position.RB, 40), (Position.WR, 40), (Position.QB, 20), (Position.TE, 20)]
    idx = 0
    for pos, count in plan:
        for k in range(count):
            pid = f"{pos.value.lower()}{k}"
            value[pid] = float(200 - idx)
            position[pid] = pos
            adp[pid] = float(idx + 1)
            adp_stdev[pid] = 6.0
            idx += 1
    return SimContext(
        value=value,
        position=position,
        baselines={p: 30.0 for p in Position},
        slots=expand_starting_slots(_small_settings()),
        roster_size=5,
        adp=adp,
        adp_stdev=adp_stdev,
    )


def _sigma_ctx() -> SimContext:
    """``_small_ctx`` plus PER-PLAYER sigma, so a season can actually be sampled from it."""
    ctx = _small_ctx()
    return dataclasses.replace(
        ctx, sigma={pid: 10.0 + 0.5 * (i % 23) for i, pid in enumerate(sorted(ctx.value))}
    )


def test_evaluate_params_returns_one_value_per_slot() -> None:
    per_slot = evaluate_params(EngineParams(), _small_ctx(), opponents=[VbdOnlyAgent()], seeds=[1])
    assert len(per_slot) == 12
    assert all(v > 0 for v in per_slot)


def test_deterministic_objective_is_seed_blind_against_a_deterministic_field() -> None:
    """The Tier-4 defect, pinned as a regression. ``NeedBasedAgent`` never consumes its ``rng``, so
    with the sigma-blind scorer the WHOLE held-out evaluation is a constant function of the seed:
    ``--eval-seeds`` bought nothing and the gate's Wilcoxon ran on one frozen scenario."""
    ctx = _sigma_ctx()
    one = evaluate_params(EngineParams(), ctx, opponents=[NeedBasedAgent()], seeds=[1001])
    six = evaluate_params(
        EngineParams(), ctx, opponents=[NeedBasedAgent()], seeds=list(range(1001, 1007))
    )
    assert one == six  # bit-identical: zero simulation variance


def test_win_probability_objective_restores_seed_variance_to_a_deterministic_field() -> None:
    """...and the stochastic scorer fixes it on its own. Even when every opponent is deterministic
    (so the DRAFT is frozen), each seed now draws a different season, so ``--eval-seeds`` is a real
    estimate rather than the same number repeated."""
    ctx = _sigma_ctx()
    objective = WinProbabilityObjective(n_draws=200)
    one = evaluate_params(
        EngineParams(), ctx, opponents=[NeedBasedAgent()], seeds=[1001], objective=objective
    )
    six = evaluate_params(
        EngineParams(),
        ctx,
        opponents=[NeedBasedAgent()],
        seeds=list(range(1001, 1007)),
        objective=objective,
    )
    assert one != six
    assert all(0.0 <= v <= 1.0 for v in one + six)


def test_objective_value_is_the_mean_across_slots() -> None:
    ctx = _small_ctx()
    params = EngineParams()
    per_slot = evaluate_params(params, ctx, opponents=[VbdOnlyAgent()], seeds=[1])
    scalar = objective_value(params, ctx, opponents=[VbdOnlyAgent()], seeds=[1])
    assert scalar == pytest.approx(sum(per_slot) / len(per_slot))


def test_promotion_decision_adopts_a_clear_improvement() -> None:
    decision = promotion_decision([10.0] * 12, [5.0] * 12)
    assert decision["promote"] is True
    assert decision["p_value"] < 0.05


def test_promotion_decision_refuses_a_tie() -> None:
    assert promotion_decision([5.0] * 12, [5.0] * 12)["promote"] is False


def test_promotion_decision_refuses_on_a_single_slot_regression() -> None:
    # Better on 11 slots but worse on one → non-negative-at-every-slot fails → no promotion.
    tuned = [10.0] * 11 + [1.0]
    baseline = [5.0] * 12
    assert promotion_decision(tuned, baseline)["promote"] is False


def test_committed_engine_json_validates_against_engine_params() -> None:
    payload = json.loads((_REPO_ROOT / "config" / "engine.json").read_text(encoding="utf-8"))
    EngineParams.model_validate(payload)  # the committed artifact must always load


def test_evaluate_agent_scores_any_agent_across_slots() -> None:
    from jaaffl.calibrate.tune import evaluate_agent

    per_slot = evaluate_agent(VbdOnlyAgent(), _small_ctx(), opponents=[VbdOnlyAgent()], seeds=[1])
    assert len(per_slot) == 12
    assert all(v > 0 for v in per_slot)


def test_run_tournament_ranks_our_agent_against_baselines() -> None:
    """E6 (efficacy): our ScoreAgent vs VBD-only and ADP-only baselines, each at every slot vs a
    common field, compared per-slot. Structure + Wilcoxon, not a fixture-pool win claim."""
    from jaaffl.calibrate.tune import run_tournament

    contenders = {
        "score": ScoreAgent(EngineParams()),
        "vbd": VbdOnlyAgent(),
        "adp": AdpNoiseAgent(),
    }
    report = run_tournament(
        _small_ctx(),
        contenders=contenders,
        opponents=[VbdOnlyAgent(), AdpNoiseAgent()],
        seeds=[1, 2],
    )
    assert set(report["mean"]) == {"score", "vbd", "adp"}
    assert report["reference"] == "score"
    assert set(report["vs_baselines"]) == {"vbd", "adp"}
    for comparison in report["vs_baselines"].values():
        assert {"p_value", "mean_diff", "min_slot_diff", "beats"} <= comparison.keys()


def test_cap_sim_pool_keeps_low_value_positions() -> None:
    """A plain top-N value cap drops K/DST (low μ) — but the sim needs them to fill K/DST slots and
    for reliability shrinkage to bite. Per-position keep-back preserves them."""
    from jaaffl.calibrate.tune import cap_sim_pool

    value = {f"rb{i}": float(300 - i) for i in range(30)}
    value.update({f"dst{i}": float(50 - i) for i in range(3)})
    position = {p: (Position.RB if p.startswith("rb") else Position.DST) for p in value}
    ctx = SimContext(
        value=value,
        position=position,
        baselines=dict.fromkeys(Position, 40.0),
        slots=[],
        roster_size=17,
    )
    capped = cap_sim_pool(ctx, 2, per_position=2)
    assert {"rb0", "rb1", "dst0", "dst1"} <= set(capped.value)  # a low-value DST survives the cap


def test_params_from_trial_sets_reliability_shrinkage() -> None:
    from jaaffl.calibrate.tune import params_from_trial

    p = params_from_trial(
        0.6,
        0.4,
        [0.3, 0.2, 0.0, -0.3, -0.4],
        4.0,
        reliability={"K": 0.5, "DST": 0.3},
        base=EngineParams(),
    )
    assert p.reliability_shrinkage["K"] == 0.5
    assert p.reliability_shrinkage["DST"] == 0.3
    assert p.kappa == 0.6  # the other tuned fields are still set


def test_sim_context_from_draft_context_maps_the_fields() -> None:
    """The DraftContext -> SimContext adapter that lets the E2 study run on real precompute data."""
    from types import SimpleNamespace

    from jaaffl.calibrate.tune import sim_context_from_draft_context

    settings = _small_settings()
    dc = SimpleNamespace(
        settings=settings,
        mu={"rb0": 200.0, "wr0": 180.0},
        position={"rb0": Position.RB, "wr0": Position.WR},
        baselines={Position.RB: 30.0, Position.WR: 28.0},
        starting_slots=expand_starting_slots(settings),
        adp_mean={"rb0": 1.0, "wr0": 3.0},
        adp_sd={"rb0": 5.0, "wr0": 6.0},
        cliff_bonus={"rb0": 4.0},
        projections={"rb0": SimpleNamespace(sigma=40.0), "wr0": SimpleNamespace(sigma=35.0)},
    )
    sc = sim_context_from_draft_context(dc)
    assert sc.value == {"rb0": 200.0, "wr0": 180.0}
    assert sc.adp_stdev == {"rb0": 5.0, "wr0": 6.0}
    assert sc.sigma == {"rb0": 40.0, "wr0": 35.0}
    assert sc.cliff_bonus == {"rb0": 4.0}
    assert sc.roster_size == sum(s.count for s in settings.roster_slots)


def test_run_study_actually_uses_the_objective_it_is_given() -> None:
    """`run_study`'s Optuna callback was itself named `objective`, shadowing the parameter — so the
    study passed its own trial function down as the scorer and blew up with a TypeError the moment
    a caller supplied a real objective. Caught only by running the CLI end to end."""
    pytest.importorskip("optuna")
    from jaaffl.calibrate.tune import run_study

    seen: list[int] = []

    def counting_objective(rosters, *, our_slot, ctx, seed):  # noqa: ANN001, ANN202
        seen.append(our_slot)
        return float(len(rosters[our_slot]))

    run_study(
        _small_ctx(),
        n_trials=1,
        seed=0,
        opponents=[VbdOnlyAgent()],
        seeds=[1],
        objective=counting_objective,
    )
    assert sorted(set(seen)) == list(range(12))  # every slot scored, by OUR objective


def test_smoke_study_returns_a_valid_in_range_param_vector() -> None:
    pytest.importorskip("optuna")
    from jaaffl.calibrate.tune import run_study

    best = run_study(
        _small_ctx(), n_trials=5, seed=0, opponents=[AdpNoiseAgent(), VbdOnlyAgent()], seeds=[1]
    )
    assert isinstance(best, EngineParams)
    assert 0.5 <= best.kappa <= 0.8
    assert 0.3 <= best.alpha <= 0.5
