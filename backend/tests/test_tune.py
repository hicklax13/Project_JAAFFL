"""E2 — engine-param tuning (plan §9.2). Objective + promotion gate are pure/scipy; the Optuna
study is guarded by importorskip so CI's base install stays green.

The promotion gate NEVER regresses: a tuned vector is adopted only if it beats the frozen baseline
on a one-sided Wilcoxon across the 12 slots AND is non-negative at every slot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaaffl.calibrate.tune import evaluate_params, objective_value, promotion_decision
from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import AdpNoiseAgent, ScoreAgent, SimContext, VbdOnlyAgent

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


def test_evaluate_params_returns_one_value_per_slot() -> None:
    per_slot = evaluate_params(EngineParams(), _small_ctx(), opponents=[VbdOnlyAgent()], seeds=[1])
    assert len(per_slot) == 12
    assert all(v > 0 for v in per_slot)


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


def test_smoke_study_returns_a_valid_in_range_param_vector() -> None:
    pytest.importorskip("optuna")
    from jaaffl.calibrate.tune import run_study

    best = run_study(
        _small_ctx(), n_trials=5, seed=0, opponents=[AdpNoiseAgent(), VbdOnlyAgent()], seeds=[1]
    )
    assert isinstance(best, EngineParams)
    assert 0.5 <= best.kappa <= 0.8
    assert 0.3 <= best.alpha <= 0.5
