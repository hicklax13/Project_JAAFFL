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

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.calibrate.tune import (
    WinProbabilityObjective,
    cap_sim_pool,
    evaluate_params,
    promotion_decision,
    run_study,
    sim_context_from_draft_context,
)
from jaaffl.config import EngineParams, get_settings
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    SimContext,
    SoftmaxVbdAgent,
    VbdOnlyAgent,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _cap_pool(ctx: SimContext, cap: int) -> SimContext:
    """Trim to the draftable pool, keeping K/DST (needed for reliability + K/DST slots)."""
    return cap_sim_pool(ctx, cap)


def _real_context(cap: int) -> SimContext:
    """Build a precompute-backed SimContext (real projections + FFC ADP). NETWORK + slow."""
    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import build_registry_context_source
    from jaaffl.providers.nflverse import NflreadpyProvider

    settings = get_settings()
    if not settings.jaaffl_season:
        raise SystemExit("[E2] set jaaffl_season for --real")
    warehouse = Warehouse(settings.jaaffl_data_dir)
    crosswalk = Crosswalk(warehouse.app_sqlite)
    print(
        "[E2] seeding nflverse universe + building the real DraftContext ...",
        file=sys.stderr,
    )
    NflreadpyProvider(crosswalk=crosswalk).seed_crosswalk()
    source = build_registry_context_source(
        settings,
        warehouse=warehouse,
        crosswalk=crosswalk,
        season=settings.jaaffl_season,
    )
    dc = source(settings.jaaffl_league_id)
    if dc is None:
        raise SystemExit("[E2] precompute returned no context (empty universe/projections)")
    ctx = sim_context_from_draft_context(dc)
    print(
        f"[E2] real pool: {len(ctx.value)} players -> capped to top {cap}",
        file=sys.stderr,
    )
    return _cap_pool(ctx, cap)


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
    ctx = _real_context(args.pool_cap) if real else demo_sim_context()
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

    def _slots(params: EngineParams, obj: object | None) -> list[float]:
        return evaluate_params(
            params, ctx, opponents=heldout_opponents, seeds=heldout_seeds, objective=obj
        )

    # The gate runs on win probability; mean lineup value is reported alongside because it is the
    # interpretable points-scale view AND the number every pre-Tier-4 run published.
    tuned_slots, base_slots = _slots(tuned, objective), _slots(baseline, objective)
    tuned_pts, base_pts = _slots(tuned, None), _slots(baseline, None)
    decision = promotion_decision(tuned_slots, base_slots)
    points = promotion_decision(tuned_pts, base_pts)

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
