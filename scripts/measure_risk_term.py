#!/usr/bin/env python
"""Tier 8 — measure the ``lambda_slot_override`` positional-bias arms on BOTH objectives.

Tier 7 asked for E2/E6 evidence before touching ``lambda_slot_override``. That evidence could not
exist: ``ScoreAgent`` did not read the coefficient (0 of 60 simulated rosters moved when it was
sign-flipped). Tier 8 fixed that; this script is the measurement it unblocked.

Every arm is the SHIPPED ``ScoreAgent`` with a flag, never a subclass, and every arm shares ONE
``SimContext`` so the sampled seasons stay common random numbers — without which the 12-slot paired
comparison is far too noisy to see an effect this size.

Arms::

    baseline        the committed config, unchanged
    override_off    lambda_slot_override zeroed (config-only; the arm Tier 7 implied)
    centred         lambda * (sigma - median sigma at that position)
    gated           the surplus ceiling withheld once every pick is spoken for
    centred+gated   both

Reports win probability AND expected points for each, with the one-sided Wilcoxon p-value and the
per-slot noise from disjoint replicate blocks. **Recommends nothing on its own** — a knob is worth
changing only if BOTH objectives support it, which is the trade Tier 5 found for kappa and the
reason this project keeps fooling itself with one-sided numbers.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/measure_risk_term.py --smoke
    .venv/Scripts/python.exe scripts/measure_risk_term.py --real --replicates 5 --draws 800
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context, real_sim_context
from jaaffl.calibrate.tune import (
    WinProbabilityObjective,
    evaluate_agent,
    pooled_per_slot,
    promotion_decision,
)
from jaaffl.config import EngineParams
from jaaffl.engine.simulate import AdpNoiseAgent, NeedBasedAgent, ScoreAgent

# The `--real` pool loader used to live here as a private `_real_context`. It now lives in
# `jaaffl.calibrate.pools.real_sim_context`, because E6 needs the same pool and a rule implemented
# twice is the exact defect Tier 8 removed from the risk rule.


def _override_off(base: EngineParams) -> EngineParams:
    return EngineParams.model_validate(
        {
            **base.model_dump(),
            "lambda_slot_override": {
                "last_startable_slot_floor": 0.0,
                "surplus_stash_ceiling": 0.0,
            },
        }
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="Fixture pool (fast).")
    ap.add_argument("--real", action="store_true", help="Precompute-backed pool (network, slow).")
    ap.add_argument("--eval-seeds", type=int, default=8)
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--draws", type=int, default=800)
    ap.add_argument("--pool-cap", type=int, default=300)
    ap.add_argument("--out", type=Path, default=None, help="Write the full table as JSON.")
    args = ap.parse_args(argv)

    ctx = real_sim_context(args.pool_cap) if (args.real and not args.smoke) else demo_sim_context()
    base = committed_engine_params()
    off = _override_off(base)

    arms: dict[str, ScoreAgent] = {
        "baseline": ScoreAgent(base),
        "override_off": ScoreAgent(off),
        "centred": ScoreAgent(base, centre_sigma=True),
        "gated": ScoreAgent(base, gate_surplus_stash=True),
        "centred+gated": ScoreAgent(base, centre_sigma=True, gate_surplus_stash=True),
    }
    opponents = [NeedBasedAgent(), AdpNoiseAgent()]
    blocks = [
        list(range(1001 + i * 1000, 1001 + i * 1000 + args.eval_seeds))
        for i in range(max(1, args.replicates))
    ]
    objective = WinProbabilityObjective(n_draws=args.draws)

    print(
        f"[risk] {len(arms)} arms x {len(blocks)} disjoint blocks x {args.eval_seeds} seeds "
        f"x 12 slots, {args.draws} sampled seasons/draft",
        file=sys.stderr,
    )

    def replicates(agent: ScoreAgent, obj: object | None) -> list[list[float]]:
        return [
            evaluate_agent(agent, ctx, opponents=opponents, seeds=block, objective=obj)
            for block in blocks
        ]

    measured: dict[str, dict] = {}
    for name, agent in arms.items():
        print(f"[risk]   {name} ...", file=sys.stderr)
        measured[name] = {"win": replicates(agent, objective), "pts": replicates(agent, None)}

    def compare(arm: str, key: str) -> dict:
        """One-sided Wilcoxon in the direction 'is the ARM better than the baseline?'."""
        arm_mean, _ = pooled_per_slot(measured[arm][key])
        base_mean, _ = pooled_per_slot(measured["baseline"][key])
        diffs = [
            [a - b for a, b in zip(ar, br, strict=True)]
            for ar, br in zip(measured[arm][key], measured["baseline"][key], strict=True)
        ]
        _, noise = pooled_per_slot(diffs)
        decision = promotion_decision(
            arm_mean, base_mean, slot_noise=noise if len(blocks) > 1 else None
        )
        return {"mean": sum(arm_mean) / len(arm_mean), **decision}

    rows = {
        arm: {"win": compare(arm, "win"), "pts": compare(arm, "pts")}
        for arm in arms
        if arm != "baseline"
    }
    base_win, _ = pooled_per_slot(measured["baseline"]["win"])
    base_pts, _ = pooled_per_slot(measured["baseline"]["pts"])

    print(f"\n{'=' * 104}")
    print(
        f"{'arm':<16} {'win prob':>9} {'d/slot':>9} {'min slot':>9} {'p':>7}   "
        f"{'points':>9} {'d/slot':>9} {'p':>7}   both?"
    )
    print(
        f"{'baseline':<16} {sum(base_win) / 12:>9.4f} {'—':>9} {'—':>9} {'—':>7}   "
        f"{sum(base_pts) / 12:>9.2f} {'—':>9} {'—':>7}"
    )
    for arm, r in rows.items():
        both = "YES" if (r["win"]["promote"] and r["pts"]["promote"]) else "no"
        print(
            f"{arm:<16} {r['win']['mean']:>9.4f} {r['win']['mean_diff']:>+9.4f} "
            f"{r['win']['min_slot_diff']:>+9.4f} {r['win']['p_value']:>7.4f}   "
            f"{r['pts']['mean']:>9.2f} {r['pts']['mean_diff']:>+9.2f} "
            f"{r['pts']['p_value']:>7.4f}   {both}"
        )
    print(
        "\nA knob is worth changing only if BOTH objectives support it. Tier 5 measured kappa\n"
        "buying championship probability by GIVING UP points; a one-sided number is how this\n"
        "project keeps fooling itself. Nothing here is written to config/engine.json."
    )
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "baseline": {"win": sum(base_win) / 12, "pts": sum(base_pts) / 12},
                    "arms": rows,
                    "blocks": blocks,
                    "draws": args.draws,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
