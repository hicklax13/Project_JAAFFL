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
import dataclasses
import sys
from pathlib import Path

from jaaffl.calibrate.tune import (
    evaluate_params,
    promotion_decision,
    run_study,
    sim_context_from_draft_context,
)
from jaaffl.config import EngineParams, get_settings
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    SimContext,
    VbdOnlyAgent,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _demo_settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="demo",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=2, starting=True),
            RosterSlot(
                slot="WR/RB",
                eligible_positions=[Position.WR, Position.RB],
                count=1,
                starting=True,
            ),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1, starting=True),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=2,
                starting=False,
            ),
        ],
    )


def _demo_context() -> SimContext:
    """A deterministic fixture pool with a steep RB cliff (so risk/VONA params actually bite)."""
    value, position, adp, adp_stdev, sigma = {}, {}, {}, {}, {}
    plan = [(Position.RB, 45), (Position.WR, 55), (Position.QB, 24), (Position.TE, 24)]
    idx = 0
    for pos, count in plan:
        for k in range(count):
            pid = f"{pos.value.lower()}{k}"
            # Steeper decay for RB → a real scarcity gradient the ScoreAgent's VONA can exploit.
            decay = 3.2 if pos is Position.RB else 1.6
            value[pid] = max(20.0, 260.0 - decay * idx)
            position[pid] = pos
            adp[pid] = float(idx + 1)
            adp_stdev[pid] = 7.0
            sigma[pid] = 35.0 if pos in (Position.RB, Position.WR) else 25.0
            idx += 1
    return SimContext(
        value=value,
        position=position,
        baselines={p: 40.0 for p in Position},
        slots=expand_starting_slots(_demo_settings()),
        roster_size=8,
        adp=adp,
        adp_stdev=adp_stdev,
        sigma=sigma,
    )


def _cap_pool(ctx: SimContext, cap: int) -> SimContext:
    """Keep the top-``cap`` players by value. A real universe is thousands deep, but only the
    draftable top matters for a 12×17 sim (K/DST fall out and are phantom-filled uniformly)."""
    keep = set(sorted(ctx.value, key=lambda p: ctx.value[p], reverse=True)[:cap])
    trim = lambda mapping: {p: v for p, v in mapping.items() if p in keep}  # noqa: E731
    return dataclasses.replace(
        ctx,
        value=trim(ctx.value),
        position=trim(ctx.position),
        adp=trim(ctx.adp),
        adp_stdev=trim(ctx.adp_stdev),
        sigma=trim(ctx.sigma),
        cliff_bonus=trim(ctx.cliff_bonus),
    )


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
        "--write",
        action="store_true",
        help="Persist to config/engine.json IF promoted (--real).",
    )
    parser.add_argument("--config", type=Path, default=_REPO_ROOT / "config" / "engine.json")
    args = parser.parse_args(argv)

    real = args.real and not args.smoke
    ctx = _real_context(args.pool_cap) if real else _demo_context()
    baseline = EngineParams()  # the frozen §10.3 defaults
    train_opponents = [AdpNoiseAgent(), VbdOnlyAgent()]
    heldout_opponents = [NeedBasedAgent()]  # held-out opponent — never the training mix
    train_seeds = list(range(1, args.train_seeds + 1))
    heldout_seeds = list(range(1001, 1001 + args.eval_seeds))  # disjoint from the training seeds

    print(
        f"[E2] study: {args.trials} trials, seed {args.seed}, "
        f"{len(train_seeds)}x train / {len(heldout_seeds)}x eval seeds ...",
        file=sys.stderr,
    )
    tuned = run_study(
        ctx,
        n_trials=args.trials,
        seed=args.seed,
        opponents=train_opponents,
        seeds=train_seeds,
    )

    tuned_slots = evaluate_params(tuned, ctx, opponents=heldout_opponents, seeds=heldout_seeds)
    base_slots = evaluate_params(baseline, ctx, opponents=heldout_opponents, seeds=heldout_seeds)
    decision = promotion_decision(tuned_slots, base_slots)

    lam = [round(entry["lambda"], 3) for entry in tuned.lambda_schedule]
    print(f"[E2] tuned:    kappa={tuned.kappa:.3f} alpha={tuned.alpha:.3f} lambda={lam}")
    print(
        f"[E2] held-out: mean_diff={decision['mean_diff']:+.2f} pts/slot  "
        f"min_slot_diff={decision['min_slot_diff']:+.2f}  p={decision['p_value']:.4f}"
    )
    print(f"[E2] promotion gate -> {'PROMOTE' if decision['promote'] else 'KEEP baseline'}")

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
