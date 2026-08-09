#!/usr/bin/env python
"""E2 — tune the engine params (κ, α, λ-schedule, caps) via simulated drafts (plan §9.2, Track J).

Runs an Optuna TPE study whose objective is our ScoreAgent's mean optimal starting-lineup value
across all 12 draft slots vs behavioral opponents, then applies the **no-regression promotion gate**
on HELD-OUT opponents + seeds: the tuned vector is adopted only if it beats the frozen baseline on a
one-sided Wilcoxon across the slots AND is non-negative at every slot (else the config is kept).

Needs the ``engine-stretch`` extra (optuna, scipy). Default mode ``--smoke`` uses a deterministic
FIXTURE pool — it proves the whole harness end-to-end (study → held-out eval → gate) fast, and never
writes (a synthetic pool would tune to synthetic structure). A real, promotable study needs a
precompute-backed SimContext (real projections + ADP) and runs offline; wire that as ``--real``.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/tune_engine_params.py --smoke --trials 15 --seed 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jaaffl.calibrate.pools import (
    committed_engine_params,
    demo_sim_context,
    real_sim_context,
)
from jaaffl.calibrate.tune import (
    WinProbabilityObjective,
    evaluate_params,
    pooled_per_slot,
    promotion_decision,
    run_study,
)
from jaaffl.config import EngineParams
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    SoftmaxVbdAgent,
    VbdOnlyAgent,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


# E2 carried its OWN `_real_context` until Tier 9 — a third copy of the same loader, in the one CLI
# that can WRITE `config/engine.json`. Nothing had diverged yet, but "a rule implemented twice
# diverges silently" applies hardest here: had E2's cap or per-position keep-back drifted from
# E6's, the study would have tuned on one real pool while the tournament validated on another, and
# no test compares them. All three now call `pools.real_sim_context`.


def _write_engine_params(config_path: Path, tuned: EngineParams) -> None:
    """Persist the tuned vector to config/engine.json (bump version), from the model dump."""
    import json

    payload = tuned.model_dump()
    payload["version"] = int(payload.get("version", 1)) + 1
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E2: tune engine params via simulated drafts.")
    parser.add_argument("--smoke", action="store_true", help="Fixture pool (fast; never writes).")
    parser.add_argument(
        "--real", action="store_true", help="Precompute-backed pool (network, slow)."
    )
    parser.add_argument("--trials", type=int, default=15, help="Optuna trials.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--train-seeds",
        type=int,
        default=2,
        help="Draft seeds/trial (study cost scales with this).",
    )
    parser.add_argument(
        "--eval-seeds",
        type=int,
        default=2,
        help="Held-out seeds — gate power (one-shot, cheap).",
    )
    parser.add_argument(
        "--replicates",
        type=int,
        default=1,
        help=(
            "Repeat the held-out evaluation over N DISJOINT seed blocks. >1 measures the gate's"
            " own per-slot sampling noise, so the min-slot leg can reject only a SIGNIFICANT"
            " regression. At 1 the leg keeps its original strict form."
        ),
    )
    parser.add_argument("--pool-cap", type=int, default=300, help="Top-N players (--real).")
    parser.add_argument(
        "--draws",
        type=int,
        default=400,
        help="Sampled seasons per scored draft (win-probability objective).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist to config/engine.json IF promoted (--real).",
    )
    parser.add_argument("--config", type=Path, default=_REPO_ROOT / "config" / "engine.json")
    args = parser.parse_args(argv)

    real = args.real and not args.smoke
    ctx = real_sim_context(args.pool_cap) if real else demo_sim_context()
    # The vector the ENGINE runs, not bare EngineParams() — whose empty lambda_schedule silently
    # made every previous E2 baseline a RISK-FREE agent, so the gate never saw the shipped lambda.
    baseline = committed_engine_params()

    # Train and held-out opponent sets stay disjoint BY TYPE, and both are now stochastic.
    # AdpNoiseAgent moves to the held-out side so `--eval-seeds` varies the draft and the ADP-based
    # survival model is scored against ADP-following opponents it was never tuned against; the
    # training mix keeps a stochastic member (SoftmaxVbdAgent) so it does not collapse to a single
    # deterministic archetype.
    train_opponents = [VbdOnlyAgent(), SoftmaxVbdAgent()]
    heldout_opponents = [NeedBasedAgent(), AdpNoiseAgent()]
    train_seeds = list(range(1, args.train_seeds + 1))
    heldout_seeds = list(range(1001, 1001 + args.eval_seeds))  # disjoint from the training seeds
    objective = WinProbabilityObjective(n_draws=args.draws)

    print(
        f"[E2] study: {args.trials} trials, seed {args.seed}, "
        f"{len(train_seeds)}x train / {len(heldout_seeds)}x eval seeds, "
        f"{args.draws} sampled seasons/draft ...",
        file=sys.stderr,
    )
    tuned = run_study(
        ctx,
        n_trials=args.trials,
        seed=args.seed,
        opponents=train_opponents,
        seeds=train_seeds,
        base=baseline,
        objective=objective,
    )

    # Disjoint held-out blocks. Pooling R blocks of S seeds IS an R*S-seed evaluation (per-slot
    # scores are seed means), and the spread ACROSS blocks is the only way to see the gate's own
    # sampling error — within one block, slot heterogeneity and noise are confounded.
    blocks = [
        list(range(1001 + i * 1000, 1001 + i * 1000 + args.eval_seeds))
        for i in range(max(1, args.replicates))
    ]

    def _slots(params: EngineParams, obj: object | None) -> list[list[float]]:
        return [
            evaluate_params(params, ctx, opponents=heldout_opponents, seeds=block, objective=obj)
            for block in blocks
        ]

    def _gate(tuned_reps: list[list[float]], base_reps: list[list[float]]) -> tuple[dict, list]:
        tuned_mean, _ = pooled_per_slot(tuned_reps)
        base_mean, _ = pooled_per_slot(base_reps)
        # The noise of the paired DIFFERENCE, not of either arm: common random numbers cancel most
        # of each arm's variance, so using an arm's own spread would wildly overstate it.
        diffs = [
            [t - b for t, b in zip(tr, br, strict=True)]
            for tr, br in zip(tuned_reps, base_reps, strict=True)
        ]
        _, noise = pooled_per_slot(diffs)
        use = noise if len(blocks) > 1 else None
        return promotion_decision(tuned_mean, base_mean, slot_noise=use), (use or [])

    # The gate runs on win probability; mean lineup value is reported alongside because it is the
    # interpretable points-scale view AND the number every pre-Tier-4 run published.
    tuned_reps, base_reps = _slots(tuned, objective), _slots(baseline, objective)
    tuned_pt_reps, base_pt_reps = _slots(tuned, None), _slots(baseline, None)
    tuned_slots, _ = pooled_per_slot(tuned_reps)
    base_slots, _ = pooled_per_slot(base_reps)
    tuned_pts, _ = pooled_per_slot(tuned_pt_reps)
    base_pts, _ = pooled_per_slot(base_pt_reps)
    decision, slot_noise = _gate(tuned_reps, base_reps)
    points, _ = _gate(tuned_pt_reps, base_pt_reps)

    lam = [round(entry["lambda"], 3) for entry in tuned.lambda_schedule]
    rel = {k: round(v, 3) for k, v in tuned.reliability_shrinkage.items()}
    base_lam = [round(entry["lambda"], 3) for entry in baseline.lambda_schedule]
    print(f"[E2] baseline: kappa={baseline.kappa:.3f} alpha={baseline.alpha:.3f} lambda={base_lam}")
    print(f"[E2] tuned:    kappa={tuned.kappa:.3f} alpha={tuned.alpha:.3f} lambda={lam}")
    print(f"[E2] tuned:    reliability_shrinkage={rel}")
    print(
        f"[E2] held-out win prob:  {sum(base_slots) / len(base_slots):.4f} -> "
        f"{sum(tuned_slots) / len(tuned_slots):.4f}   "
        f"mean_diff={decision['mean_diff']:+.4f}  "
        f"min_slot_diff={decision['min_slot_diff']:+.4f}  p={decision['p_value']:.4f}"
    )
    print(
        f"[E2] held-out points:    {sum(base_pts) / len(base_pts):.2f} -> "
        f"{sum(tuned_pts) / len(tuned_pts):.2f}   "
        f"mean_diff={points['mean_diff']:+.2f} pts/slot  "
        f"min_slot_diff={points['min_slot_diff']:+.2f}  p={points['p_value']:.4f}"
    )
    if slot_noise:
        worst = max(
            (-(t - b) / sd if sd > 0 else 0.0)
            for t, b, sd in zip(tuned_slots, base_slots, slot_noise, strict=True)
        )
        print(
            f"[E2] per-slot noise (sd of the paired diff over {len(blocks)} blocks): "
            f"median {sorted(slot_noise)[len(slot_noise) // 2]:.4f}  max {max(slot_noise):.4f}  "
            f"-> worst slot is {worst:.2f} sd below baseline"
        )
    else:
        print(
            "[E2] min-slot leg is STRICT (single block). Measured 2026-07-27, the per-slot noise"
            " floor is 0.0013-0.0089 while this leg has rejected at 0.0009-0.0016 — pass"
            " --replicates 5 to gate on a SIGNIFICANT regression instead of a noisy point estimate."
        )
    print(
        f"[E2] promotion gate (win prob) -> {'PROMOTE' if decision['promote'] else 'KEEP baseline'}"
    )

    if decision["promote"] and real and args.write:
        _write_engine_params(args.config, tuned)
        print(f"[E2] wrote tuned params to {args.config}")
    elif real:
        print("[E2] --real dry-run: not writing (pass --write to persist a PROMOTED vector).")
    else:
        print("[E2] --smoke: fixture pool, config/engine.json NOT written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
