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

from jaaffl.calibrate.tune import evaluate_params, promotion_decision, run_study
from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import AdpNoiseAgent, NeedBasedAgent, SimContext, VbdOnlyAgent


def _demo_settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="demo",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=2, starting=True),
            RosterSlot(
                slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1, starting=True
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E2: tune engine params via simulated drafts.")
    parser.add_argument(
        "--smoke", action="store_true", help="Fixture pool (default); never writes."
    )
    parser.add_argument("--trials", type=int, default=15, help="Optuna trials.")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if not args.smoke:
        parser.error(
            "only --smoke is wired; a real promotable study needs a precompute SimContext."
        )

    ctx = _demo_context()
    baseline = EngineParams()  # the frozen §10.3 defaults
    train_opponents = [AdpNoiseAgent(), VbdOnlyAgent()]
    heldout_opponents = [NeedBasedAgent()]  # held-out opponent — never the training mix
    train_seeds, heldout_seeds = [1, 2], [7, 8]  # held-out seeds too

    print(f"[E2] Optuna study: {args.trials} trials, seed {args.seed} ...", file=sys.stderr)
    tuned = run_study(
        ctx, n_trials=args.trials, seed=args.seed, opponents=train_opponents, seeds=train_seeds
    )

    tuned_slots = evaluate_params(tuned, ctx, opponents=heldout_opponents, seeds=heldout_seeds)
    base_slots = evaluate_params(baseline, ctx, opponents=heldout_opponents, seeds=heldout_seeds)
    decision = promotion_decision(tuned_slots, base_slots)

    lam = [entry["lambda"] for entry in tuned.lambda_schedule]
    print(f"[E2] tuned:    kappa={tuned.kappa:.3f} alpha={tuned.alpha:.3f} lambda={lam}")
    print(
        f"[E2] held-out: mean_diff={decision['mean_diff']:+.2f} pts/slot  "
        f"min_slot_diff={decision['min_slot_diff']:+.2f}  p={decision['p_value']:.4f}"
    )
    print(f"[E2] promotion gate -> {'PROMOTE' if decision['promote'] else 'KEEP baseline'}")
    print(
        "[E2] --smoke: fixture pool, config/engine.json NOT written (a real study needs "
        "precompute-backed real projections/ADP; run offline)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
