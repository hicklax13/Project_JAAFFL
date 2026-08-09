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
from statistics import mean, stdev
from typing import TYPE_CHECKING, Protocol

from jaaffl.config import EngineParams
from jaaffl.engine.optimize import roster_capacity
from jaaffl.engine.risk import median_sigma_by_position
from jaaffl.engine.simulate import (
    DraftAgent,
    ScoreAgent,
    SeasonOutcomes,
    SimContext,
    optimal_lineup_value,
    sample_season_outcomes,
    simulate_draft,
    win_probability,
)

if TYPE_CHECKING:
    from jaaffl.engine.context import DraftContext


def sim_context_from_draft_context(dc: DraftContext) -> SimContext:
    """Adapt a precompute :class:`DraftContext` into a :class:`SimContext`, so E2 can tune on REAL
    projections + FFC ADP. σ is read per-player from ``projections``; everything else maps 1:1.

    ``value`` is the **pre-shrinkage** μ (``PlayerProjection.mu_raw``), NOT ``dc.mu``. R1
    reliability shrinkage is applied at precompute into ``dc.mu`` — which is exactly what
    ``recommend()`` scores — and :class:`~jaaffl.engine.simulate.ScoreAgent` applies it AGAIN from
    ``params.reliability_shrinkage``. Copying ``dc.mu`` here therefore compressed K and DST by
    ``0.4**2 = 0.16`` while the live engine used ``0.4``. Measured on the real board 2026-08-09,
    median value over replacement: **DST 2.50x · K 2.50x · QB/RB/TE/WR 1.00x**, where 2.50 is
    exactly ``1 / 0.4``, and the identity ``eff == baseline + r*r_pre*(raw − baseline)`` held to
    1.4e-14 over 300 players.

    **Three channels were wrong, not one**, because ``value`` is read by all of them:

    * our DECISIONS — ``ScoreAgent`` scored μ shrunk twice where ``recommend()`` shrinks once;
    * the OBJECTIVE — ``optimal_lineup_value`` and ``sample_season_outcomes`` both read ``value``,
      so a kicker was scored 2.5x closer to replacement than he projects. ``ScoreAgent``'s own
      docstring states the intended contract: "our DECISIONS defer high-variance positions while
      the OBJECTIVE scores raw μ";
    * the OPPONENTS — ``VbdOnlyAgent`` / ``NeedBasedAgent`` / ``SoftmaxVbdAgent`` all rank by
      ``value_over_replacement(pid, ctx.value, ...)``, so every simulated rival ranked K and DST
      through OUR engine's risk adjustment.

    It also un-breaks E2's search: ``run_study`` samples ``reliability_k``/``reliability_dst`` over
    ``[0.1, 1.0]``, but with the committed 0.4 already baked in the effective factor spanned
    ``[0.04, 0.40]`` and could never reach 1.0 (no shrinkage at all).

    The baselines need no adjustment and are carried unchanged: R1 pulls μ *toward* the replacement
    baseline, so the value at the replacement rank is a fixed point and the within-position order is
    preserved. Verified on the real board — baselines recomputed from un-shrunk μ match
    ``dc.baselines`` at all six positions — and pinned by
    ``test_sim_context_baselines_are_unmoved_by_carrying_raw_mu``.

    ``demo_sim_context`` has always built ``value`` from a raw curve, so the FIXTURE pool was
    already correct and **no test on it could ever have seen this**: there is no ``recommend()`` on
    that path to disagree with. That is how it survived to Tier 11, having been listed as
    uninvestigated in Tier 8 and measured-but-not-fixed in Tier 10.
    """
    sigma = {pid: proj.sigma for pid, proj in dc.projections.items()}
    return SimContext(
        value={pid: proj.mu_raw for pid, proj in dc.projections.items()},
        position=dict(dc.position),
        baselines=dict(dc.baselines),
        slots=list(dc.starting_slots),
        roster_size=sum(slot.count for slot in dc.settings.roster_slots),
        adp=dict(dc.adp_mean),
        adp_stdev=dict(dc.adp_sd),
        sigma=sigma,
        cliff_bonus=dict(dc.cliff_bonus),
        roster_capacity=roster_capacity(dc.settings),
        # A measured board FACT, always carried. Only an agent constructed with
        # `centre_sigma=True` reads it, so carrying it changes nothing on its own — and every arm
        # can then share ONE context, which is what keeps the common random numbers common.
        sigma_median=median_sigma_by_position(sigma, dc.position),
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


class SimObjective(Protocol):
    """Scores ONE finished draft. Takes every roster (not just ours) so a rank-based objective can
    see the field, and the ``seed`` so a stochastic objective stays reproducible."""

    def __call__(
        self,
        rosters: Sequence[Sequence[str]],
        *,
        our_slot: int,
        ctx: SimContext,
        seed: int,
    ) -> float: ...


def mean_lineup_value_objective(
    rosters: Sequence[Sequence[str]], *, our_slot: int, ctx: SimContext, seed: int
) -> float:
    """The legacy objective: our final roster's optimal-9 value under the deterministic ``mu``.

    **Sigma-blind, therefore risk-blind.** It cannot reward ``lambda*sigma`` — any risk aversion
    just moves the ranking away from the very ``mu`` it pays out on, so lambda can be penalised and
    never rewarded. Kept because it is the interpretable points-scale view (and the number every
    pre-Tier-4 E2 run reported), but it must not be the sole gate: see
    :class:`WinProbabilityObjective`.
    """
    return optimal_lineup_value(rosters[our_slot], ctx)


class WinProbabilityObjective:
    """``P(our roster posts the highest realized season total of the 12)`` over ``n_draws`` sampled
    seasons — the objective that can actually price risk (plan §3.9 names playoff/championship odds
    as "the true objective that lambda only proxies").

    The sampled block is built once per ``(ctx, seed)`` and reused across all 12 slots, so a player
    realizes the same season everywhere — common random numbers, which is what keeps the 12-slot
    paired gate sensitive enough to see a param change rather than sampling noise. The cache holds a
    strong reference to ``ctx`` so its ``id`` cannot be recycled under it.
    """

    def __init__(self, *, n_draws: int = 400) -> None:
        self._n_draws = n_draws
        self._cache: dict[tuple[int, int], tuple[SimContext, SeasonOutcomes]] = {}

    def _outcomes(self, ctx: SimContext, seed: int) -> SeasonOutcomes:
        key = (id(ctx), seed)
        cached = self._cache.get(key)
        if cached is None or cached[0] is not ctx:
            cached = (ctx, sample_season_outcomes(ctx, n_draws=self._n_draws, seed=seed))
            self._cache[key] = cached
        return cached[1]

    def __call__(
        self, rosters: Sequence[Sequence[str]], *, our_slot: int, ctx: SimContext, seed: int
    ) -> float:
        return win_probability(rosters, self._outcomes(ctx, seed), ctx, our_slot=our_slot)


def evaluate_agent(
    agent: DraftAgent,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    objective: SimObjective | None = None,
) -> list[float]:
    """Per-slot mean score of ``agent`` across ``seeds`` — one entry per draft slot. Placing the
    agent at each seat in turn avoids slot-specific overfit.

    ``objective`` defaults to :func:`mean_lineup_value_objective` (the legacy, sigma-blind measure);
    pass :class:`WinProbabilityObjective` for the risk-pricing gate. Callers should report both.
    """
    score = objective or mean_lineup_value_objective
    per_slot: list[float] = []
    for slot in range(teams):
        values = [
            score(
                simulate_draft(
                    ctx, our_slot=slot, our_agent=agent, opponents=opponents, seed=seed, teams=teams
                ),
                our_slot=slot,
                ctx=ctx,
                seed=seed,
            )
            for seed in seeds
        ]
        per_slot.append(mean(values))
    return per_slot


def evaluate_agent_objectives(
    agent: DraftAgent,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    objectives: Mapping[str, SimObjective | None],
) -> dict[str, list[float]]:
    """Per-slot mean score under EVERY named objective, from ONE simulated draft per (slot, seed).

    :func:`evaluate_agent` scores a single objective, so E6 — which reports two — ran the whole
    tournament twice over the same seeds and threw the first set of rosters away. Two objectives on
    one draft is not an optimisation, it is what makes replicate blocks affordable: five disjoint
    blocks at the old cost is exactly the standard Tier 6 set for E2 and E6 never met.

    A ``None`` objective means :func:`mean_lineup_value_objective`, matching
    :func:`evaluate_agent`'s default, so a caller can pass the E6 pair as
    ``{"win probability": WinProbabilityObjective(...), "mean lineup value": None}``.
    """
    scored: dict[str, SimObjective] = {
        name: objective or mean_lineup_value_objective for name, objective in objectives.items()
    }
    per_slot: dict[str, list[float]] = {name: [] for name in scored}
    for slot in range(teams):
        totals: dict[str, list[float]] = {name: [] for name in scored}
        for seed in seeds:
            rosters = simulate_draft(
                ctx, our_slot=slot, our_agent=agent, opponents=opponents, seed=seed, teams=teams
            )
            for name, objective in scored.items():
                totals[name].append(objective(rosters, our_slot=slot, ctx=ctx, seed=seed))
        for name, values in totals.items():
            per_slot[name].append(mean(values))
    return per_slot


def evaluate_params(
    params: EngineParams,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    objective: SimObjective | None = None,
) -> list[float]:
    """Per-slot evaluation of a ``ScoreAgent(params)`` — the E2 objective input."""
    return evaluate_agent(
        ScoreAgent(params),
        ctx,
        opponents=opponents,
        seeds=seeds,
        teams=teams,
        objective=objective,
    )


def objective_value(
    params: EngineParams,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    objective: SimObjective | None = None,
) -> float:
    """The scalar Optuna maximizes: the mean per-slot score across all 12 slots."""
    return mean(
        evaluate_params(
            params, ctx, opponents=opponents, seeds=seeds, teams=teams, objective=objective
        )
    )


def pooled_per_slot(replicates: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    """Per-slot ``(mean, sample sd)`` across replicate evaluations run on DISJOINT seed blocks.

    Pooling R blocks of S seeds is exactly an ``R*S``-seed evaluation (``evaluate_agent`` already
    averages over seeds), so this buys power AND the dispersion estimate in one pass. A single run
    cannot supply the latter: the spread across the 12 slots confounds real slot heterogeneity with
    sampling error, and only re-running the SAME slot under fresh seeds separates them.
    """
    if not replicates:
        return [], []
    columns = list(zip(*replicates, strict=True))
    means = [mean(column) for column in columns]
    sds = [stdev(column) if len(column) > 1 else 0.0 for column in columns]
    return means, sds


def promotion_decision(
    tuned_per_slot: Sequence[float],
    baseline_per_slot: Sequence[float],
    *,
    tol: float = 1e-9,
    slot_noise: Sequence[float] | None = None,
    z: float = 1.96,
) -> dict:
    """The no-regression gate. Adopt tuned params only if they beat the baseline on a one-sided
    Wilcoxon signed-rank test across the 12 slots (p < 0.05) AND no slot regresses.

    ``slot_noise`` is the per-slot sampling SD of the PAIRED difference, from
    :func:`pooled_per_slot`. Supplied, the second leg asks whether a slot is **significantly**
    worse (``diff < -z*sd``) instead of merely negative as a point estimate. Omitted, the leg keeps
    its original strict form exactly, so no past decision changes silently.

    Why the option exists (measured 2026-07-27, real board, 5 blocks x 8 seeds x 800 draws): the
    per-slot SD of a paired difference is **0.0013-0.0089** (individual slots to 0.0148), while
    every vector this gate has ever rejected on this leg failed by **0.0009-0.0016** — five to ten
    times INSIDE the noise. ``alpha=0`` passed the leg in **1 of 5** seed blocks while its mean
    effect was positive in **5 of 5**. The leg was not discriminating, it was sampling.

    The failure is structural, not a matter of being slightly too strict: ``min`` over 12 slots is
    an extreme-order statistic, so requiring it to be non-negative as a point estimate demands that
    the worst of twelve noisy estimates land above zero — which a real, positive effect fails most
    of the time. ``min_slot_diff`` is still reported either way; only its authority changes.

    ⚠️ ``slot_noise`` is deliberately ONE BLOCK's sd, not the standard error of the pooled mean
    (``sd/sqrt(R)``), so at R=5 the band is ~2.24x wider than a test at the pooled scale. That is
    the permissive direction for a NON-REGRESSION leg — it makes the gate slower to call a slot
    "significantly worse" — which is the error this leg should prefer, given it was rejecting real
    effects five to ten times inside the noise. Every caller (E2, E6, the risk-term arms) passes the
    same quantity, so the three gates stay comparable.
    """
    diffs = [t - b for t, b in zip(tuned_per_slot, baseline_per_slot, strict=True)]
    min_diff = min(diffs)
    if slot_noise is None:
        non_negative = min_diff >= -tol
    else:
        non_negative = all(
            diff >= -(z * sd) - tol for diff, sd in zip(diffs, slot_noise, strict=True)
        )
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


# The two E6 objective names. Exported because `scripts/run_tournament.py` formats championship
# probabilities to 4 decimals and points to 1, and keying that on a string literal it does not own
# would silently print win probabilities as "0.1" if the name here ever changed.
WIN_PROBABILITY = "win probability"
MEAN_LINEUP_VALUE = "mean lineup value"


def tournament_verdict(objectives: Mapping[str, Mapping]) -> dict[str, dict]:
    """Per baseline, which objectives the reference agent beats it on and which it loses on.

    **Fail-closed:** an objective that did not measure a given baseline at all counts as a LOSS for
    that baseline, not as a neutral. This is a safety gate, and "we never checked" must never read
    as "we passed". :func:`run_tournament` always measures every baseline under every objective, so
    the case is unreachable from there; it matters only to a direct caller.

    E6 reported each objective in its own paragraph and never combined them, so an agent that
    scores MORE points than plain VBD while winning the championship 5.5x LESS often produced two
    unremarkable-looking lines and no alarm. A split decision is the single most informative thing
    a two-objective tournament can say — Tier 5 found ``kappa`` buying championship odds by giving
    up points, and Tier 9 found the shipped ``lambda_slot_override`` doing the reverse — so it is
    computed here rather than left to a reader.

    Objective names are sorted so the output is stable across runs.
    """
    baselines: set[str] = set()
    for report in objectives.values():
        baselines.update(report["vs_baselines"])
    verdict: dict[str, dict] = {}
    for baseline in sorted(baselines):
        beats_on = sorted(
            name
            for name, report in objectives.items()
            if report["vs_baselines"].get(baseline, {}).get("beats")
        )
        loses_on = sorted(name for name in objectives if name not in beats_on)
        verdict[baseline] = {
            "beats_on": beats_on,
            "loses_on": loses_on,
            "split": bool(beats_on and loses_on),
            "beats_all": not loses_on,
        }
    return verdict


def run_tournament(
    ctx: SimContext,
    *,
    contenders: Mapping[str, DraftAgent],
    opponents: Sequence[DraftAgent],
    seed_blocks: Sequence[Sequence[int]],
    teams: int = 12,
    reference: str | None = None,
    objectives: Mapping[str, SimObjective | None] | None = None,
    draws: int = 400,
) -> dict:
    """E6 efficacy proof (design §9.3 / §3.9): every named contender at all 12 slots against a
    common field, compared to ``reference`` (default: the first — our agent) on EVERY objective.
    The project's OWN validation, never a vendor/literature claim.

    ``seed_blocks`` are DISJOINT seed blocks, not a flat seed list. Pooling R blocks of S seeds is
    exactly an R*S-seed evaluation AND yields the per-slot sampling SD of the paired difference,
    which is fed to :func:`promotion_decision` as ``slot_noise``. Before Tier 9 this took a flat
    ``seeds`` and passed no noise, so ``beats`` used the strict point-estimate min-slot leg that
    Tier 6 measured as "not discriminating, it was sampling" — on a single block, which is the
    standard E2 has met since Tier 6 and E6 never has. **Every E6 number this project published
    before Tier 9 came from one block.**

    Every objective is scored from ONE simulated draft per (slot, seed), and the report carries a
    :func:`tournament_verdict`: an agent can beat a baseline on points while losing to it on
    championship probability, and E6 used to print those as two unrelated paragraphs.

    ``draws`` sizes the DEFAULT :class:`WinProbabilityObjective` only. Supplying ``objectives``
    replaces that default wholesale, so ``draws`` is then unused — build the objective with the
    draw count you want. Blocks should be EQUAL length: pooling is a mean of per-block means, which
    equals the mean over all seeds only when the blocks are the same size.
    """
    if not contenders:
        raise ValueError("run_tournament needs at least one contender")
    if not seed_blocks or any(not block for block in seed_blocks):
        raise ValueError("run_tournament needs at least one non-empty seed block")
    scored: Mapping[str, SimObjective | None] = objectives or {
        WIN_PROBABILITY: WinProbabilityObjective(n_draws=draws),
        MEAN_LINEUP_VALUE: None,
    }
    # objective -> agent -> block -> per-slot scores
    raw: dict[str, dict[str, list[list[float]]]] = {name: {} for name in scored}
    for agent_name, agent in contenders.items():
        for name in scored:
            raw[name][agent_name] = []
        for block in seed_blocks:
            block_scores = evaluate_agent_objectives(
                agent, ctx, opponents=opponents, seeds=block, teams=teams, objectives=scored
            )
            for name, values in block_scores.items():
                raw[name][agent_name].append(values)

    ref = reference or next(iter(contenders))
    report: dict[str, dict] = {}
    for name in scored:
        pooled = {
            agent_name: pooled_per_slot(blocks)[0] for agent_name, blocks in raw[name].items()
        }
        ref_blocks = raw[name][ref]
        vs_baselines: dict[str, dict] = {}
        for agent_name, blocks in raw[name].items():
            if agent_name == ref:
                continue
            # The noise that matters is the sd of the PAIRED difference, per baseline — not one
            # number for the objective. Pooling it across baselines would average away the very
            # heterogeneity the second leg exists to test against.
            diffs = [
                [r - b for r, b in zip(ref_block, block, strict=True)]
                for ref_block, block in zip(ref_blocks, blocks, strict=True)
            ]
            _, slot_noise = pooled_per_slot(diffs)
            decision = promotion_decision(
                pooled[ref],
                pooled[agent_name],
                slot_noise=slot_noise if len(seed_blocks) > 1 else None,
            )
            vs_baselines[agent_name] = {
                "mean_diff": decision["mean_diff"],
                "min_slot_diff": decision["min_slot_diff"],
                "p_value": decision["p_value"],
                "beats": decision["promote"],
                "slot_noise": slot_noise,
            }
        report[name] = {
            "per_slot": pooled,
            "mean": {agent_name: mean(values) for agent_name, values in pooled.items()},
            "vs_baselines": vs_baselines,
        }
    return {
        "reference": ref,
        "blocks": len(seed_blocks),
        "objectives": report,
        "verdict": tournament_verdict(report),
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
    objective: SimObjective | None = None,
) -> EngineParams:
    """Optuna TPE study (``direction='maximize'``) over the canonical ranges; return the best
    :class:`EngineParams`. Sampling stays INSIDE the §10.3 bands (do not widen).

    ``base`` should be the vector the engine actually runs (``config/engine.json``), not bare
    ``EngineParams()`` — every field the trial does not set is carried from it, and the default's
    empty ``lambda_schedule`` would silently seed a risk-free vector.
    """
    import optuna

    base = base or EngineParams()
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # NOT named `objective` — that would shadow this function's own `objective` parameter and pass
    # the trial callback down as the scorer.
    def _trial(trial: optuna.Trial) -> float:
        kappa = trial.suggest_float("kappa", 0.5, 0.8)
        alpha = trial.suggest_float("alpha", 0.3, 0.5)
        lam = [
            trial.suggest_float(f"lam{i}", lo, hi) if lo != hi else lo
            for i, (_rounds, (lo, hi)) in enumerate(LAMBDA_BANDS)
        ]
        # NOT searched: `caps.modifier_abs_max` bounds the positional modifiers, and
        # `recommend._positional_modifiers` returns {} unconditionally, so no pick can ever move
        # with it. Searching it spent one of six dimensions on a provably inert knob — Tier 4's
        # "tuned a term that cannot change a pick", and it diluted the power available to kappa,
        # alpha and the lambda bands. Carried from `base` so a future implementation re-enables it
        # by restoring one line.
        cap = float((base.caps or {}).get("modifier_abs_max", 5.0))
        reliability = {
            "K": trial.suggest_float("reliability_k", 0.1, 1.0),
            "DST": trial.suggest_float("reliability_dst", 0.1, 1.0),
        }
        params = params_from_trial(kappa, alpha, lam, cap, base=base, reliability=reliability)
        return objective_value(
            params, ctx, opponents=opponents, seeds=seeds, teams=teams, objective=objective
        )

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(_trial, n_trials=n_trials)
    best = study.best_params
    lam = [best.get(f"lam{i}", lo) for i, (_r, (lo, _hi)) in enumerate(LAMBDA_BANDS)]
    reliability = {"K": best["reliability_k"], "DST": best["reliability_dst"]}
    return params_from_trial(
        best["kappa"],
        best["alpha"],
        lam,
        float((base.caps or {}).get("modifier_abs_max", 5.0)),
        base=base,
        reliability=reliability,
    )
