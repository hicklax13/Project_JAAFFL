#!/usr/bin/env python
"""E6 — offline efficacy tournament (plan §9.3 / §3.9, Track L). The project's OWN validation gate.

Places our ScoreAgent (under the committed config) and the VBD-only / ADP-only baselines at every
one of the 12 draft slots against a common opponent field, simulates each draft to completion, and
scores each final roster on ALL FOUR objectives — championship probability and deterministic
starting-lineup points on the season axis, plus the Tier 11 weekly pair (18 real weeks, real byes,
a measured zero-production process and a measured same-team correlation, lineups set ex ante).
Reports the per-agent mean, a one-sided Wilcoxon against each baseline, and a **verdict** naming
the objectives our agent wins and loses on.

Honesty caveat (ADR 0003): no peer-reviewed optimal live snake-draft solver exists — this offline
tournament, not any vendor/literature claim, is how efficacy is judged. Needs ``engine-stretch``
(scipy for the Wilcoxon).

⚠️ **E6 numbers published before Tier 9 are not comparable to these.** Until Tier 9 this script
accepted only ``--smoke --seeds --draws``: it had no ``--replicates``, so every E6 figure this
project ever reported — including Tier 8's 5.5× championship inversion — came from a **single seed
block**, and ``run_tournament`` passed no ``slot_noise`` so its gate used the strict min-slot leg
Tier 6 measured as "not discriminating, it was sampling". The seed scheme also changed to the 1001+
disjoint blocks E2 and ``measure_risk_term.py`` use, so the three CLIs are comparable to each other.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/run_tournament.py --smoke --seeds 8 --replicates 5
    .venv/Scripts/python.exe scripts/run_tournament.py --real  --seeds 8 --replicates 5
"""

from __future__ import annotations

import argparse

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context, real_sim_context
from jaaffl.calibrate.tune import WEEKLY_WIN_PROBABILITY, WIN_PROBABILITY, run_tournament
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SoftmaxVbdAgent,
    VbdOnlyAgent,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="E6: offline efficacy tournament.")
    parser.add_argument("--smoke", action="store_true", help="Fixture pool (default).")
    parser.add_argument("--real", action="store_true", help="Precompute pool (network, slow).")
    parser.add_argument("--seeds", type=int, default=8, help="Draft seeds per block.")
    parser.add_argument(
        "--replicates",
        type=int,
        default=5,
        help=(
            "Evaluate over N DISJOINT seed blocks. >1 measures the gate's own per-slot noise and "
            "switches the min-slot leg from a point estimate to a significance test. Every E6 "
            "number published before Tier 9 used a single block."
        ),
    )
    parser.add_argument("--draws", type=int, default=800, help="Sampled seasons per scored draft.")
    parser.add_argument("--pool-cap", type=int, default=300, help="--real pool size cap.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    real = args.real and not args.smoke
    ctx = real_sim_context(args.pool_cap) if real else demo_sim_context()

    # The vector the engine RUNS. E6 used bare EngineParams(), whose empty lambda_schedule made
    # "ours" a risk-free agent — so the tournament never tested the shipped risk schedule at all.
    params = committed_engine_params()
    contenders = {
        "ours": ScoreAgent(params),
        "vbd_only": VbdOnlyAgent(),
        "adp_only": AdpNoiseAgent(),
    }
    field = [SoftmaxVbdAgent(), NeedBasedAgent()]
    blocks = [
        list(range(1001 + i * 1000, 1001 + i * 1000 + args.seeds))
        for i in range(max(1, args.replicates))
    ]

    report = run_tournament(
        ctx, contenders=contenders, opponents=field, seed_blocks=blocks, draws=args.draws
    )
    pool = "real" if real else "fixture"
    print(
        f"[E6] {pool} pool ({len(ctx.value)} players) · {len(blocks)} blocks x {args.seeds} seeds "
        f"x 12 slots · {args.draws} sampled seasons/draft"
    )
    for label, objective in report["objectives"].items():
        digits = 4 if label in (WIN_PROBABILITY, WEEKLY_WIN_PROBABILITY) else 1
        print(f"[E6] {label} (per agent, across 12 slots):")
        for name, value in sorted(objective["mean"].items(), key=lambda kv: -kv[1]):
            print(f"[E6]   {name:9s} {value:>9.{digits}f}")
        for name, cmp in objective["vs_baselines"].items():
            verdict = "BEATS" if cmp["beats"] else "no significant edge over"
            print(
                f"[E6]   ours {verdict} {name}: mean_diff={cmp['mean_diff']:+.{digits}f}  "
                f"min_slot_diff={cmp['min_slot_diff']:+.{digits}f}  p={cmp['p_value']:.4f}"
            )
            if len(blocks) > 1 and cmp["slot_noise"]:
                noise = sorted(cmp["slot_noise"])
                print(
                    f"[E6]     per-slot noise of that paired diff over {len(blocks)} blocks: "
                    f"median {noise[len(noise) // 2]:.{digits}f}  max {noise[-1]:.{digits}f}"
                )

    print("[E6] VERDICT:")
    for baseline, verdict in report["verdict"].items():
        if verdict["beats_all"]:
            print(f"[E6]   ours BEATS {baseline} on BOTH objectives.")
        elif verdict["split"]:
            print(
                f"[E6]   /!\\ SPLIT vs {baseline}: ours WINS on {', '.join(verdict['beats_on'])} "
                f"and LOSES on {', '.join(verdict['loses_on'])}. A one-sided number is how this "
                f"project keeps fooling itself — do not quote either leg alone."
            )
        else:
            print(f"[E6]   ours does NOT beat {baseline} on any objective.")
    if not real:
        print("[E6] fixture pool; a full efficacy claim needs --real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
