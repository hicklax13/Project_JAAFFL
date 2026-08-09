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
    pooled_per_slot,
    promotion_decision,
)
from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Player, Position, RosterSlot
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
    common field. Structure + Wilcoxon on BOTH objectives, not a fixture-pool win claim."""
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
        seed_blocks=[[1, 2]],
        draws=8,
    )
    assert report["reference"] == "score"
    assert report["blocks"] == 1
    assert set(report["objectives"]) == {"win probability", "mean lineup value"}
    for objective in report["objectives"].values():
        assert set(objective["mean"]) == {"score", "vbd", "adp"}
        assert len(objective["per_slot"]["score"]) == 12
        assert set(objective["vs_baselines"]) == {"vbd", "adp"}
        for comparison in objective["vs_baselines"].values():
            assert {"p_value", "mean_diff", "min_slot_diff", "beats"} <= comparison.keys()
    assert set(report["verdict"]) == {"vbd", "adp"}


def test_run_tournament_pools_disjoint_seed_blocks() -> None:
    """Every E6 number this project has published came from ONE seed block, Tier 8's 5.5x
    championship inversion included. Tier 6 proved a single block samples its own noise and gave
    E2 --replicates; E6 never got them, so its gate has always used the leg Tier 6 discredited."""
    from jaaffl.calibrate.tune import run_tournament

    report = run_tournament(
        _small_ctx(),
        contenders={"score": ScoreAgent(EngineParams()), "vbd": VbdOnlyAgent()},
        opponents=[VbdOnlyAgent(), AdpNoiseAgent()],
        seed_blocks=[[1, 2], [3, 4]],
        draws=8,
    )
    assert report["blocks"] == 2
    for objective in report["objectives"].values():
        for comparison in objective["vs_baselines"].values():
            assert len(comparison["slot_noise"]) == 12
            assert all(sd >= 0.0 for sd in comparison["slot_noise"])


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
        # `mu_raw` deliberately DIFFERS from `mu` here: the adapter must read the pre-shrinkage
        # view, and a stub where the two coincide would pass either way (Tier 11).
        projections={
            "rb0": SimpleNamespace(sigma=40.0, mu_raw=210.0),
            "wr0": SimpleNamespace(sigma=35.0, mu_raw=185.0),
        },
    )
    sc = sim_context_from_draft_context(dc)
    assert sc.value == {"rb0": 210.0, "wr0": 185.0}  # mu_raw, NOT dc.mu
    assert sc.adp_stdev == {"rb0": 5.0, "wr0": 6.0}
    assert sc.sigma == {"rb0": 40.0, "wr0": 35.0}
    assert sc.cliff_bonus == {"rb0": 4.0}
    assert sc.roster_size == sum(s.count for s in settings.roster_slots)


def _shrunk_draft_context():
    """A REAL DraftContext whose K is shrunk by R1, built through ``assemble_projections``.

    Deliberately not a hand-written fixture: the defect being pinned lives in the seam between
    precompute (which shrinks) and the harness (which shrinks again), so the test has to drive the
    production blend rather than assert against numbers a fixture declared.
    """
    from jaaffl.engine.context import DraftContext
    from jaaffl.engine.projections import assemble_projections
    from jaaffl.league.replacement import replacement_values
    from tests.engine_fixtures import jaaffl_settings

    # The REAL league roster, not `_small_settings()` — that one has no K slot, so
    # `replacement_values` yields no K baseline, R1 falls back to shrinking toward the player's own
    # μ, and the shrink is a no-op. The vacuity guard in the test below caught exactly that.
    settings = jaaffl_settings()
    params = EngineParams.model_validate(
        {
            "flex_split": {"RB": 8, "WR": 4},
            "caps": {"mu_refinement_pct": 0.15},
            "reliability_shrinkage": {"K": 0.4, "DST": 0.4},
        }
    )
    points = {f"k{i}": 150.0 - 3.0 * i for i in range(20)}
    points.update({f"rb{i}": 260.0 - 4.0 * i for i in range(20)})
    points.update({f"wr{i}": 250.0 - 3.5 * i for i in range(20)})

    def _pos(pid: str) -> Position:
        return Position.K if pid[0] == "k" else Position.RB if pid[:2] == "rb" else Position.WR

    position = {pid: _pos(pid) for pid in points}
    projections = assemble_projections(
        {"cbs": points},
        position,
        params,
        settings,
        sigma_floor={Position.K: 5.0, Position.RB: 40.0, Position.WR: 35.0},
    )
    mu = {pid: proj.mu for pid, proj in projections.items()}
    players = {pid: Player(player_id=pid, name=pid, position=position[pid]) for pid in projections}
    flex = (8, 4)
    baselines = replacement_values(settings, mu, players, flex_split=flex)
    slots = expand_starting_slots(settings)
    return DraftContext(
        settings=settings,
        params=params,
        projections=projections,
        mu=mu,
        position=position,
        baselines=baselines,
        flex_split=flex,
        tiers={},
        cliff_bonus={},
        adp_mean={pid: float(i + 1) for i, pid in enumerate(points)},
        adp_sd=dict.fromkeys(points, 8.0),
        ecr={},
        starting_slots=slots,
        players=players,
    )


def test_score_agent_effective_value_equals_recommend_context_mu() -> None:
    """THE harness-fidelity invariant for VALUE, and the reason Tier 11 exists.

    ``recommend()`` scores ``context.mu`` — μ with R1 applied ONCE, at precompute.
    ``ScoreAgent._effective_value`` applies R1 itself from ``params.reliability_shrinkage``, so the
    context it is handed must carry the PRE-shrinkage μ or the harness and the shipped engine
    disagree about what a player is worth.

    Before Tier 11 ``sim_context_from_draft_context`` copied ``dc.mu`` (already shrunk) into
    ``SimContext.value``, so every ``--real`` measurement this project has published came from an
    agent whose K/DST μ was compressed by ``0.4**2 = 0.16`` against the live engine's ``0.4``.
    Measured on the real board 2026-08-09: median value over replacement 2.50x closer to
    replacement at DST and K (exactly ``1 / 0.4``), 1.00x at QB/RB/TE/WR.

    ``demo_sim_context`` builds ``value`` from a RAW curve, so the fixture pool was always correct
    and **no test on it could ever have seen this** — there is no ``recommend()`` on that path to
    disagree with. That is why it survived ten tiers.
    """
    from jaaffl.calibrate.tune import sim_context_from_draft_context

    dc = _shrunk_draft_context()
    ctx = sim_context_from_draft_context(dc)
    effective = ScoreAgent(dc.params)._effective_value(ctx)  # noqa: SLF001 - the invariant under test

    assert dc.projections["k0"].mu != pytest.approx(dc.projections["k0"].mu_raw), (
        "this fixture must actually exercise a shrunk position, or the assertion below is vacuous"
    )
    for pid, live_mu in dc.mu.items():
        assert effective[pid] == pytest.approx(live_mu), pid


def test_the_harness_scores_the_objective_on_raw_mu_not_the_shrunk_view() -> None:
    """The other half of the contract ``ScoreAgent`` documents: "our DECISIONS defer high-variance
    positions while the OBJECTIVE scores raw μ".

    ``optimal_lineup_value`` and ``sample_season_outcomes`` both read ``SimContext.value``, and so
    does every behavioural opponent's ``value_over_replacement``. Carrying ``dc.mu`` there put the
    objective AND all eleven simulated opponents on our own K/DST risk adjustment.
    """
    from jaaffl.calibrate.tune import sim_context_from_draft_context

    dc = _shrunk_draft_context()
    ctx = sim_context_from_draft_context(dc)
    shrunk = [pid for pid, proj in dc.projections.items() if proj.mu != pytest.approx(proj.mu_raw)]
    assert shrunk, "no player is actually shrunk here, so the assertion below proves nothing"
    for pid, proj in dc.projections.items():
        assert ctx.value[pid] == pytest.approx(proj.mu_raw), pid
    # ... and for the shrunk ones that is a DIFFERENT number from what the live path scores.
    for pid in shrunk:
        assert ctx.value[pid] != pytest.approx(dc.mu[pid]), pid


def test_sim_context_baselines_are_unmoved_by_carrying_raw_mu() -> None:
    """R1 pulls μ TOWARD the replacement baseline, so the value AT the replacement rank is a fixed
    point and the within-position order is preserved — the baselines are identical either way.

    Measured on the real board 2026-08-09: baselines recomputed from un-shrunk μ match
    ``DraftContext.baselines`` to 4 dp at all six positions. Pinned here because Task 2 now depends
    on it; a change to ``replacement_values`` that breaks the fixed point would silently rescale
    every VOR in the harness rather than failing.
    """
    from jaaffl.calibrate.tune import sim_context_from_draft_context
    from jaaffl.league.replacement import replacement_values

    dc = _shrunk_draft_context()
    ctx = sim_context_from_draft_context(dc)
    recomputed = replacement_values(
        dc.settings, dict(ctx.value), dc.players, flex_split=dc.flex_split
    )
    for pos, baseline in dc.baselines.items():
        assert recomputed[pos] == pytest.approx(baseline), pos


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


# --- The min-slot leg vs the measured Monte-Carlo noise floor (Tier 6) -------------------------


def test_pooled_per_slot_reports_the_mean_and_spread_across_replicate_blocks() -> None:
    """Replicating the whole paired comparison over disjoint seed blocks is what makes the gate's
    own sampling error visible; one run cannot separate slot heterogeneity from noise."""
    means, sds = pooled_per_slot([[1.0, 10.0], [3.0, 10.0], [2.0, 10.0]])

    assert means == pytest.approx([2.0, 10.0])
    assert sds[0] == pytest.approx(1.0)  # sample sd of 1,3,2
    assert sds[1] == pytest.approx(0.0)  # identical across blocks -> no noise


def test_the_min_slot_leg_tolerates_a_regression_inside_the_measured_noise() -> None:
    """MEASURED on the real board: the per-slot SD of a paired difference is 0.0013-0.0089, while
    the gate has been rejecting at margins of 0.0009-0.0016 — 5-10x BELOW its own noise floor.
    `alpha=0` promoted in only 1 of 5 seed blocks despite a positive mean in all 5.

    With the noise supplied, a slot counts as a regression only if it is SIGNIFICANTLY negative.
    """
    baseline = [0.10] * 12
    tuned = [0.11] * 11 + [0.0991]  # one slot 0.0009 low - the alpha=0.3 margin
    noise = [0.007] * 12  # the measured per-slot SD

    strict = promotion_decision(tuned, baseline)
    aware = promotion_decision(tuned, baseline, slot_noise=noise)

    assert strict["promote"] is False, "today's leg rejects on a margin far inside the noise"
    assert aware["promote"] is True
    assert aware["min_slot_diff"] == pytest.approx(-0.0009)  # still REPORTED, just not fatal


def test_the_min_slot_leg_still_rejects_a_slot_that_is_genuinely_worse() -> None:
    """The tolerance must not swallow a real regression: a slot far outside the noise still fails,
    otherwise the leg would stop protecting anything at all."""
    baseline = [0.10] * 12
    tuned = [0.11] * 11 + [0.05]  # one slot 0.05 low, ~7 SD out
    noise = [0.007] * 12

    assert promotion_decision(tuned, baseline, slot_noise=noise)["promote"] is False


def test_run_study_does_not_spend_a_search_dimension_on_the_inert_modifier_cap() -> None:
    """`caps.modifier_abs_max` bounds the positional modifiers — and `_positional_modifiers`
    returns `{}` unconditionally, so NOTHING reads it. Verified: the only readers of `params.caps`
    are `projections.py` (a different key, `mu_refinement_pct`) and a docstring.

    Tuning it is Tier 4's "tuned a term that cannot move a pick" again, and it is not free: TPE was
    fitting SIX dimensions on two training seeds over thirty trials, and one of them was provably
    inert — diluting the power on the coefficients that do matter.
    """
    pytest.importorskip("optuna")
    from jaaffl.calibrate.tune import run_study

    base = EngineParams(caps={"modifier_abs_max": 4.25, "mu_refinement_pct": 0.15})

    tuned = run_study(
        _small_ctx(), n_trials=2, seed=0, opponents=[VbdOnlyAgent()], seeds=[1], base=base
    )

    assert tuned.caps["modifier_abs_max"] == 4.25, "an inert knob must be carried, not searched"
    assert tuned.caps["mu_refinement_pct"] == 0.15


def test_evaluate_agent_objectives_simulates_each_draft_once(monkeypatch) -> None:
    """E6 scored the SAME drafts once per objective. Two objectives meant two full tournaments,
    which is why --replicates never looked affordable. One draft, every objective."""
    import jaaffl.calibrate.tune as tune_mod
    from jaaffl.calibrate.tune import evaluate_agent_objectives, mean_lineup_value_objective

    calls = 0
    real = tune_mod.simulate_draft

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(tune_mod, "simulate_draft", counting)
    scores = evaluate_agent_objectives(
        VbdOnlyAgent(),
        _small_ctx(),
        opponents=[VbdOnlyAgent()],
        seeds=[1, 2],
        objectives={"a": mean_lineup_value_objective, "b": mean_lineup_value_objective},
    )
    assert calls == 12 * 2  # slots x seeds -- NOT x objectives
    assert set(scores) == {"a", "b"}
    assert len(scores["a"]) == 12


def test_evaluate_agent_objectives_agrees_with_evaluate_agent() -> None:
    """The one-draft path must be numerically identical to the per-objective path it replaces."""
    from jaaffl.calibrate.tune import (
        evaluate_agent,
        evaluate_agent_objectives,
        mean_lineup_value_objective,
    )

    ctx = _small_ctx()
    single = evaluate_agent(VbdOnlyAgent(), ctx, opponents=[VbdOnlyAgent()], seeds=[1, 2])
    many = evaluate_agent_objectives(
        VbdOnlyAgent(),
        ctx,
        opponents=[VbdOnlyAgent()],
        seeds=[1, 2],
        objectives={"pts": mean_lineup_value_objective},
    )
    assert many["pts"] == single


def test_tournament_verdict_flags_a_split_decision() -> None:
    """The defect that let Tier 9's finding sit unexamined for a tier: E6 printed
    '+44.3 points p=0.0017' and '-0.0805 win prob p=1.0000' eight lines apart and never said
    the two disagree. A split is the headline, not a footnote."""
    from jaaffl.calibrate.tune import tournament_verdict

    report = {
        "win probability": {"vs_baselines": {"vbd_only": {"beats": False}}},
        "mean lineup value": {"vs_baselines": {"vbd_only": {"beats": True}}},
    }
    verdict = tournament_verdict(report)
    assert verdict["vbd_only"]["split"] is True
    assert verdict["vbd_only"]["beats_all"] is False
    assert verdict["vbd_only"]["beats_on"] == ["mean lineup value"]
    assert verdict["vbd_only"]["loses_on"] == ["win probability"]


def test_tournament_verdict_reports_a_clean_sweep() -> None:
    from jaaffl.calibrate.tune import tournament_verdict

    report = {
        "win probability": {"vs_baselines": {"vbd_only": {"beats": True}}},
        "mean lineup value": {"vs_baselines": {"vbd_only": {"beats": True}}},
    }
    verdict = tournament_verdict(report)
    assert verdict["vbd_only"]["beats_all"] is True
    assert verdict["vbd_only"]["split"] is False
    assert verdict["vbd_only"]["loses_on"] == []


def _load_e6_script():
    """Import scripts/run_tournament.py by path -- it is not an installed package."""
    import importlib.util

    path = _REPO_ROOT / "scripts" / "run_tournament.py"
    spec = importlib.util.spec_from_file_location("e6_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e6_cli_exposes_replicates_and_a_real_pool() -> None:
    """E6 accepted only --smoke/--seeds/--draws, so every E6 number ever published is a single
    seed block -- the standard E2 has met since Tier 6."""
    args = (
        _load_e6_script()
        .build_parser()
        .parse_args(["--smoke", "--seeds", "8", "--replicates", "5"])
    )
    assert args.replicates == 5
    assert args.seeds == 8
    assert hasattr(args, "real")
    assert hasattr(args, "pool_cap")


def test_e6_cli_runs_multiple_blocks_end_to_end(capsys) -> None:
    """The smallest possible real run: the whole script path, two disjoint blocks. Asserts the
    VERDICT block prints -- tournament_verdict is unit-tested, but the branch that turns a split
    into a line a human reads is the part that was missing, so it needs its own cover."""
    module = _load_e6_script()
    assert module.main(["--smoke", "--seeds", "1", "--draws", "8", "--replicates", "2"]) == 0
    out = capsys.readouterr().out
    assert "[E6] VERDICT:" in out
    assert "2 blocks x 1 seeds" in out
    assert any(marker in out for marker in ("SPLIT vs", "BEATS", "does NOT beat"))


def test_run_tournament_feeds_the_measured_noise_to_the_gate(monkeypatch) -> None:
    """Mutation-proof. Setting ``slot_noise=None`` inside run_tournament left the whole suite
    green, because the report carries the noise whether or not the GATE ever sees it. "The noise
    is in the dict" is not the property that matters; "the noise reached promotion_decision" is —
    that second leg is the one Tier 6 proved was sampling its own noise."""
    import jaaffl.calibrate.tune as tune_mod

    seen: list = []
    real = tune_mod.promotion_decision

    def spy(tuned, baseline, **kwargs):
        seen.append(kwargs.get("slot_noise"))
        return real(tuned, baseline, **kwargs)

    monkeypatch.setattr(tune_mod, "promotion_decision", spy)
    kwargs = {
        "contenders": {"score": ScoreAgent(EngineParams()), "vbd": VbdOnlyAgent()},
        "opponents": [VbdOnlyAgent(), AdpNoiseAgent()],
        "draws": 8,
    }

    report = tune_mod.run_tournament(_small_ctx(), seed_blocks=[[1, 2], [3, 4]], **kwargs)
    assert seen, "promotion_decision was never called"
    for objective in report["objectives"].values():
        for comparison in objective["vs_baselines"].values():
            assert comparison["slot_noise"] in seen  # the reported noise IS the gated noise
    assert all(noise is not None and len(noise) == 12 for noise in seen)

    seen.clear()
    tune_mod.run_tournament(_small_ctx(), seed_blocks=[[1, 2]], **kwargs)
    assert seen and all(noise is None for noise in seen), (
        "a single block cannot estimate its own noise, so the strict leg must be kept"
    )


def test_run_tournament_pools_every_block_not_just_the_first() -> None:
    """Mutation-proof. Replacing the pooled mean with ``blocks[0]`` — discarding 4 of 5 replicate
    blocks — also left the suite green. The pooled per-slot score must be the mean of the blocks."""
    from jaaffl.calibrate.tune import MEAN_LINEUP_VALUE, run_tournament

    ctx = _small_ctx()
    kwargs = {
        "contenders": {"score": ScoreAgent(EngineParams()), "vbd": VbdOnlyAgent()},
        "opponents": [VbdOnlyAgent(), AdpNoiseAgent()],
        "draws": 8,
    }
    first = run_tournament(ctx, seed_blocks=[[1, 2]], **kwargs)
    second = run_tournament(ctx, seed_blocks=[[3, 4]], **kwargs)
    both = run_tournament(ctx, seed_blocks=[[1, 2], [3, 4]], **kwargs)

    a = first["objectives"][MEAN_LINEUP_VALUE]["per_slot"]["score"]
    b = second["objectives"][MEAN_LINEUP_VALUE]["per_slot"]["score"]
    pooled = both["objectives"][MEAN_LINEUP_VALUE]["per_slot"]["score"]
    assert a != b, "the two blocks must differ, or this test proves nothing"
    assert pooled == pytest.approx([(x + y) / 2 for x, y in zip(a, b, strict=True)])


def test_run_tournament_rejects_degenerate_inputs() -> None:
    """`--seeds 0` reaches here, and an empty block used to die in statistics.mean."""
    from jaaffl.calibrate.tune import run_tournament

    contenders = {"score": ScoreAgent(EngineParams())}
    opponents = [VbdOnlyAgent()]
    with pytest.raises(ValueError):
        run_tournament(_small_ctx(), contenders=contenders, opponents=opponents, seed_blocks=[])
    with pytest.raises(ValueError):
        run_tournament(_small_ctx(), contenders=contenders, opponents=opponents, seed_blocks=[[]])
    with pytest.raises(ValueError):
        run_tournament(_small_ctx(), contenders={}, opponents=opponents, seed_blocks=[[1]])
