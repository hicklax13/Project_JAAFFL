"""E2 — engine-param tuning via simulated drafts (plan §9.2).

:func:`evaluate_params` / :func:`objective_value` score a param vector by a :class:`ScoreAgent`'s
final optimal starting-lineup value across all 12 draft slots vs behavioral opponents (the per-slot
sweep is a controlled experiment, NOT the live order). :func:`run_study` is an Optuna TPE search
over the canonical §10.3 ranges. :func:`promotion_decision` is the **no-regression gate**: adopt a
vector only on a one-sided Wilcoxon win across slots AND non-negative at every slot.

Objective + gate are pure/scipy (base install); ``run_study`` needs the ``engine-stretch`` extra
(optuna) — imported lazily so nothing here forces it.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import TYPE_CHECKING

from jaaffl.config import EngineParams
from jaaffl.engine.simulate import (
    DraftAgent,
    ScoreAgent,
    SimContext,
    optimal_lineup_value,
    simulate_draft,
)

if TYPE_CHECKING:
    from jaaffl.engine.context import DraftContext


def sim_context_from_draft_context(dc: DraftContext) -> SimContext:
    """Adapt a precompute :class:`DraftContext` into a :class:`SimContext`, so E2 can tune on REAL
    projections + FFC ADP. σ is read per-player from ``projections``; everything else maps 1:1."""
    return SimContext(
        value=dict(dc.mu),
        position=dict(dc.position),
        baselines=dict(dc.baselines),
        slots=list(dc.starting_slots),
        roster_size=sum(slot.count for slot in dc.settings.roster_slots),
        adp=dict(dc.adp_mean),
        adp_stdev=dict(dc.adp_sd),
        sigma={pid: proj.sigma for pid, proj in dc.projections.items()},
        cliff_bonus=dict(dc.cliff_bonus),
    )


def cap_sim_pool(ctx: SimContext, cap: int, *, per_position: int = 20) -> SimContext:
    """Trim a (real) pool to the top ``cap`` by value PLUS the top ``per_position`` of EACH
    position. A plain value cap drops K/DST (low μ), but the sim needs them to fill K/DST slots and
    for reliability shrinkage to bite — this keep-back preserves every rosterable position."""
    by_value = sorted(ctx.value, key=lambda pid: ctx.value[pid], reverse=True)
    keep = set(by_value[:cap])
    by_position: dict = defaultdict(list)
    for pid in by_value:
        by_position[ctx.position[pid]].append(pid)
    for players in by_position.values():
        keep.update(players[:per_position])

    def trim(mapping: Mapping) -> dict:
        return {pid: value for pid, value in mapping.items() if pid in keep}

    return dataclasses.replace(
        ctx,
        value=trim(ctx.value),
        position=trim(ctx.position),
        adp=trim(ctx.adp),
        adp_stdev=trim(ctx.adp_stdev),
        sigma=trim(ctx.sigma),
        cliff_bonus=trim(ctx.cliff_bonus),
    )


# Canonical λ round-bands (§10.3): (round-range, (lo, hi)). A degenerate band (lo==hi) is fixed.
LAMBDA_BANDS: list[tuple[tuple[int, int], tuple[float, float]]] = [
    ((1, 2), (0.2, 0.4)),
    ((3, 6), (0.1, 0.3)),
    ((7, 9), (0.0, 0.0)),
    ((10, 13), (-0.4, -0.2)),
    ((14, 17), (-0.5, -0.3)),
]


def evaluate_agent(
    agent: DraftAgent,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
) -> list[float]:
    """Per-slot mean optimal starting-lineup value of ``agent`` across ``seeds`` — one entry per
    draft slot. Placing the agent at each seat in turn avoids slot-specific overfit."""
    per_slot: list[float] = []
    for slot in range(teams):
        values = [
            optimal_lineup_value(
                simulate_draft(
                    ctx, our_slot=slot, our_agent=agent, opponents=opponents, seed=seed, teams=teams
                )[slot],
                ctx,
            )
            for seed in seeds
        ]
        per_slot.append(mean(values))
    return per_slot


def evaluate_params(
    params: EngineParams,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
) -> list[float]:
    """Per-slot evaluation of a ``ScoreAgent(params)`` — the E2 objective input."""
    return evaluate_agent(ScoreAgent(params), ctx, opponents=opponents, seeds=seeds, teams=teams)


def objective_value(
    params: EngineParams,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
) -> float:
    """The scalar Optuna maximizes: mean starting-lineup value across all 12 slots."""
    return mean(evaluate_params(params, ctx, opponents=opponents, seeds=seeds, teams=teams))


def promotion_decision(
    tuned_per_slot: Sequence[float], baseline_per_slot: Sequence[float], *, tol: float = 1e-9
) -> dict:
    """The no-regression gate. Adopt tuned params only if they beat the baseline on a one-sided
    Wilcoxon signed-rank test across the 12 slots (p < 0.05) AND are non-negative at EVERY slot."""
    diffs = [t - b for t, b in zip(tuned_per_slot, baseline_per_slot, strict=True)]
    min_diff = min(diffs)
    non_negative = min_diff >= -tol
    if all(abs(d) <= tol for d in diffs):
        p_value = 1.0  # no difference at all → Wilcoxon is undefined; never promote
    else:
        from scipy.stats import wilcoxon

        try:
            p_value = float(
                wilcoxon(tuned_per_slot, baseline_per_slot, alternative="greater").pvalue
            )
        except ValueError:  # e.g. all-zero differences slipped through
            p_value = 1.0
    return {
        "promote": bool(non_negative and p_value < 0.05),
        "p_value": p_value,
        "min_slot_diff": min_diff,
        "mean_diff": mean(diffs),
    }


def run_tournament(
    ctx: SimContext,
    *,
    contenders: Mapping[str, DraftAgent],
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    reference: str | None = None,
) -> dict:
    """E6 efficacy proof (design §9.3 / §3.9): evaluate each named contender across all 12 slots vs
    a common opponent field, then compare each other contender to the ``reference`` (default: the
    first — our agent) via the one-sided Wilcoxon gate. The project's OWN validation (our agent vs
    VBD-only and ADP-only baselines), never a vendor/literature claim. ``beats`` = the reference is
    significantly >= that baseline AND non-negative at every slot."""
    per_slot = {
        name: evaluate_agent(agent, ctx, opponents=opponents, seeds=seeds, teams=teams)
        for name, agent in contenders.items()
    }
    ref = reference or next(iter(contenders))
    vs_baselines = {}
    for name, values in per_slot.items():
        if name == ref:
            continue
        decision = promotion_decision(per_slot[ref], values)
        vs_baselines[name] = {
            "mean_diff": decision["mean_diff"],
            "min_slot_diff": decision["min_slot_diff"],
            "p_value": decision["p_value"],
            "beats": decision["promote"],
        }
    return {
        "per_slot": per_slot,
        "mean": {name: mean(values) for name, values in per_slot.items()},
        "reference": ref,
        "vs_baselines": vs_baselines,
    }


def params_from_trial(
    kappa: float,
    alpha: float,
    lam_values: Sequence[float],
    modifier_cap: float,
    *,
    base: EngineParams,
    reliability: Mapping[str, float] | None = None,
) -> EngineParams:
    """Build an :class:`EngineParams` from a trial's (κ, α, λ-per-band, cap, and optional
    per-position ``reliability`` shrinkage), carrying every other field from ``base`` (so a tuned
    vector is a minimal, valid edit of the current config)."""
    lambda_schedule = [
        {"rounds": list(rounds), "lambda": lam}
        for (rounds, _range), lam in zip(LAMBDA_BANDS, lam_values, strict=True)
    ]
    data = base.model_dump()
    caps = dict(data.get("caps") or {})
    caps["modifier_abs_max"] = modifier_cap
    data.update(kappa=kappa, alpha=alpha, lambda_schedule=lambda_schedule, caps=caps)
    if reliability:
        data["reliability_shrinkage"] = {
            **(data.get("reliability_shrinkage") or {}),
            **reliability,
        }
    return EngineParams.model_validate(data)


def run_study(
    ctx: SimContext,
    *,
    n_trials: int,
    seed: int,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    base: EngineParams | None = None,
    teams: int = 12,
) -> EngineParams:
    """Optuna TPE study (``direction='maximize'``) over the canonical ranges; return the best
    :class:`EngineParams`. Sampling stays INSIDE the §10.3 bands (do not widen)."""
    import optuna

    base = base or EngineParams()
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        kappa = trial.suggest_float("kappa", 0.5, 0.8)
        alpha = trial.suggest_float("alpha", 0.3, 0.5)
        lam = [
            trial.suggest_float(f"lam{i}", lo, hi) if lo != hi else lo
            for i, (_rounds, (lo, hi)) in enumerate(LAMBDA_BANDS)
        ]
        cap = trial.suggest_float("modifier_cap", 3.0, 5.0)
        reliability = {
            "K": trial.suggest_float("reliability_k", 0.1, 1.0),
            "DST": trial.suggest_float("reliability_dst", 0.1, 1.0),
        }
        params = params_from_trial(kappa, alpha, lam, cap, base=base, reliability=reliability)
        return objective_value(params, ctx, opponents=opponents, seeds=seeds, teams=teams)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params
    lam = [best.get(f"lam{i}", lo) for i, (_r, (lo, _hi)) in enumerate(LAMBDA_BANDS)]
    reliability = {"K": best["reliability_k"], "DST": best["reliability_dst"]}
    return params_from_trial(
        best["kappa"], best["alpha"], lam, best["modifier_cap"], base=base, reliability=reliability
    )
