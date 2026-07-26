#!/usr/bin/env python
"""E6 — offline efficacy tournament (plan §9.3 / §3.9, Track L). The project's OWN validation gate.

Places our ScoreAgent (under the committed config) and the VBD-only / ADP-only baselines at every
one of the 12 draft slots against a common opponent field, simulates each draft to completion, and
scores each final roster by its flex-aware optimal starting-lineup value. Reports the per-agent mean
and, for each baseline, a one-sided Wilcoxon (our agent ≥ baseline, non-negative at every slot).

Honesty caveat (ADR 0003): no peer-reviewed optimal live snake-draft solver exists — this offline
tournament, not any vendor/literature claim, is how efficacy is judged. Needs ``engine-stretch``
(scipy for the Wilcoxon). ``--smoke`` uses a deterministic fixture pool; a full run wants a
precompute-backed SimContext (real projections/ADP), offline.

Usage::

    .venv/Scripts/python.exe scripts/run_tournament.py --smoke --seeds 4
"""

from __future__ import annotations

import argparse

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.calibrate.tune import WinProbabilityObjective, run_tournament
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SoftmaxVbdAgent,
    VbdOnlyAgent,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E6: offline efficacy tournament.")
    parser.add_argument("--smoke", action="store_true", help="Fixture pool (default).")
    parser.add_argument("--seeds", type=int, default=4, help="Number of draft seeds per slot.")
    parser.add_argument("--draws", type=int, default=400, help="Sampled seasons per scored draft.")
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.error("only --smoke is wired; a full tournament needs a precompute SimContext.")

    ctx = demo_sim_context()
    # The vector the engine RUNS. E6 used bare EngineParams(), whose empty lambda_schedule made
    # "ours" a risk-free agent — so the tournament never tested the shipped risk schedule at all.
    params = committed_engine_params()
    contenders = {
        "ours": ScoreAgent(params),
        "vbd_only": VbdOnlyAgent(),
        "adp_only": AdpNoiseAgent(),
    }
    field = [SoftmaxVbdAgent(), NeedBasedAgent()]
    seeds = list(range(1, args.seeds + 1))

    # Scored twice. Win probability is the objective that can price risk; mean lineup value is the
    # sigma-BLIND measure every previous E6 number was reported in, kept so the two are comparable.
    for label, objective in (
        ("win probability", WinProbabilityObjective(n_draws=args.draws)),
        ("mean lineup value", None),
    ):
        report = run_tournament(
            ctx, contenders=contenders, opponents=field, seeds=seeds, objective=objective
        )
        digits = 4 if objective is not None else 1
        print(f"[E6] {label} (per agent, across 12 slots):")
        for name, value in sorted(report["mean"].items(), key=lambda kv: -kv[1]):
            print(f"[E6]   {name:9s} {value:>9.{digits}f}")
        for name, cmp in report["vs_baselines"].items():
            verdict = "BEATS" if cmp["beats"] else "no significant edge over"
            print(
                f"[E6]   ours {verdict} {name}: mean_diff={cmp['mean_diff']:+.{digits}f}  "
                f"min_slot_diff={cmp['min_slot_diff']:+.{digits}f}  p={cmp['p_value']:.4f}"
            )
    print("[E6] fixture pool (--smoke); a full efficacy claim needs a precompute-backed pool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
