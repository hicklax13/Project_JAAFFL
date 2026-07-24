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

from collections.abc import Sequence
from statistics import mean

from jaaffl.config import EngineParams
from jaaffl.engine.simulate import (
    DraftAgent,
    ScoreAgent,
    SimContext,
    optimal_lineup_value,
    simulate_draft,
)

# Canonical λ round-bands (§10.3): (round-range, (lo, hi)). A degenerate band (lo==hi) is fixed.
LAMBDA_BANDS: list[tuple[tuple[int, int], tuple[float, float]]] = [
    ((1, 2), (0.2, 0.4)),
    ((3, 6), (0.1, 0.3)),
    ((7, 9), (0.0, 0.0)),
    ((10, 13), (-0.4, -0.2)),
    ((14, 17), (-0.5, -0.3)),
]


def evaluate_params(
    params: EngineParams,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
) -> list[float]:
    """Per-slot mean optimal starting-lineup value of a ``ScoreAgent(params)`` across ``seeds`` —
    one entry per draft slot. Placing our agent at each seat avoids slot-specific overfit."""
    agent = ScoreAgent(params)
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


def params_from_trial(
    kappa: float,
    alpha: float,
    lam_values: Sequence[float],
    modifier_cap: float,
    *,
    base: EngineParams,
) -> EngineParams:
    """Build an :class:`EngineParams` from a trial's (κ, α, λ-per-band, cap), carrying every other
    field from ``base`` (so a tuned vector is a minimal, valid edit of the current config)."""
    lambda_schedule = [
        {"rounds": list(rounds), "lambda": lam}
        for (rounds, _range), lam in zip(LAMBDA_BANDS, lam_values, strict=True)
    ]
    data = base.model_dump()
    caps = dict(data.get("caps") or {})
    caps["modifier_abs_max"] = modifier_cap
    data.update(kappa=kappa, alpha=alpha, lambda_schedule=lambda_schedule, caps=caps)
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
        params = params_from_trial(kappa, alpha, lam, cap, base=base)
        return objective_value(params, ctx, opponents=opponents, seeds=seeds, teams=teams)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params
    lam = [best.get(f"lam{i}", lo) for i, (_r, (lo, _hi)) in enumerate(LAMBDA_BANDS)]
    return params_from_trial(best["kappa"], best["alpha"], lam, best["modifier_cap"], base=base)
