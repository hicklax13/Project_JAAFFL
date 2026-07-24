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

from jaaffl.calibrate.tune import run_tournament
from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import AdpNoiseAgent, ScoreAgent, SimContext, VbdOnlyAgent


def _demo_context() -> SimContext:
    """A deterministic fixture pool with a steep RB scarcity gradient (so VONA/risk pay)."""
    value, position, adp, adp_stdev, sigma = {}, {}, {}, {}, {}
    plan = [(Position.RB, 45), (Position.WR, 55), (Position.QB, 24), (Position.TE, 24)]
    idx = 0
    for pos, count in plan:
        for k in range(count):
            pid = f"{pos.value.lower()}{k}"
            decay = 3.2 if pos is Position.RB else 1.6
            value[pid] = max(20.0, 260.0 - decay * idx)
            position[pid] = pos
            adp[pid] = float(idx + 1)
            adp_stdev[pid] = 7.0
            sigma[pid] = 35.0 if pos in (Position.RB, Position.WR) else 25.0
            idx += 1
    settings = LeagueSettings(
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
    return SimContext(
        value=value,
        position=position,
        baselines={p: 40.0 for p in Position},
        slots=expand_starting_slots(settings),
        roster_size=8,
        adp=adp,
        adp_stdev=adp_stdev,
        sigma=sigma,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E6: offline efficacy tournament.")
    parser.add_argument("--smoke", action="store_true", help="Fixture pool (default).")
    parser.add_argument("--seeds", type=int, default=4, help="Number of draft seeds per slot.")
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.error("only --smoke is wired; a full tournament needs a precompute SimContext.")

    ctx = _demo_context()
    contenders = {
        "ours": ScoreAgent(EngineParams()),
        "vbd_only": VbdOnlyAgent(),
        "adp_only": AdpNoiseAgent(),
    }
    report = run_tournament(
        ctx,
        contenders=contenders,
        opponents=[AdpNoiseAgent(), VbdOnlyAgent()],
        seeds=list(range(1, args.seeds + 1)),
    )

    print("[E6] mean optimal starting-lineup value (per agent, across 12 slots):")
    for name, value in sorted(report["mean"].items(), key=lambda kv: -kv[1]):
        print(f"[E6]   {name:9s} {value:7.1f}")
    print(f"[E6] reference agent: {report['reference']}")
    for name, cmp in report["vs_baselines"].items():
        verdict = "BEATS" if cmp["beats"] else "no significant edge over"
        print(
            f"[E6] ours {verdict} {name}: mean_diff={cmp['mean_diff']:+.1f} pts/slot  "
            f"min_slot_diff={cmp['min_slot_diff']:+.1f}  p={cmp['p_value']:.4f}"
        )
    print("[E6] fixture pool (--smoke); a full efficacy claim needs a precompute-backed pool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
