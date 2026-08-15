#!/usr/bin/env python
"""Turn a Tier-12 rehearsal log into an evidence table with a verdict per criterion.

Reads the JSONL that ``backend/src/jaaffl/api/rehearsal.py`` wrote during ONE live CBS draft and
answers, with numbers rather than impressions: was the survival model live, did every recompute
meet the <200 ms budget, was every drafted player masked off the board, did every CBS id resolve,
and what did the overlay's foot say.

**n = 1.** One draft, one seat, one evening. Every verdict below is about that one run.

Stdlib only, so it runs anywhere the log does.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/rehearsal_report.py data/rehearsal/mock-1.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

LATENCY_BUDGET_MS = 200.0
# config/league.json is immutable at 12 teams, and opponents._my_overall_picks uses
# len(draft_order) AS the team count — so any other length silently corrupts every "my next pick".
TEAM_COUNT = 12

# Every criterion the rehearsal protocol claims to test. Named here so an EMPTY log can fail all
# of them by name rather than producing an empty (and therefore clean-looking) report.
CRITERIA = (
    "recommendations served",
    "survival is live",
    "the order was read from the room",
    "recompute under 200ms",
    "every drafted player masked",
    "vona_method stated",
    "the scarcity term is live",
)


@dataclass(frozen=True)
class Verdict:
    name: str
    passed: bool
    detail: str


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    # int(q * len) overshoots for small n and returns the max, making p95 a duplicate of the
    # max column. The verdict reads `max` directly, so this only ever affected the detail string.
    return ordered[max(0, min(len(ordered) - 1, int(q * (len(ordered) - 1))))]


def evaluate(rows: list[dict]) -> list[Verdict]:
    """Every criterion as a pass/fail with the numbers behind it.

    An EMPTY log fails every check rather than passing them vacuously — a rehearsal that recorded
    nothing is the one outcome that must never read as clean.
    """
    if not rows:
        return [Verdict(name, False, "no rows: the rehearsal log is empty") for name in CRITERIA]

    bases = {row.get("survival_basis") for row in rows}
    orders = {row.get("draft_order_len", 0) for row in rows}
    latencies = [float(row["recompute_ms"]) for row in rows if row.get("recompute_ms") is not None]
    unresolved = sorted({pid for row in rows for pid in row.get("unresolved_ids", [])})
    methods = {row.get("vona_method") for row in rows}
    # The scarcity term is only EXPECTED to be live where survival was; judging it on degraded
    # rows would just re-report the survival verdict under a second name.
    live_rows = [row for row in rows if row.get("survival_basis") == "my_slot"]
    positive = [row.get("positive_vona_n", 0) for row in live_rows]

    # --- the prelude, and why these two verdicts are not set-equality anymore ----------------
    # CBS attaches the entered round-1 order to `fullstatedelta`, which rides on `picks/completed`
    # frames (apps/extension/src/lib/parse.ts:123). parse.ts pushes that frame's PICK events
    # (line 332) BEFORE its ORDER event (line 347), and LEAGUE_SETTINGS is not in
    # `_STATE_ADVANCING` (backend/src/jaaffl/api/app.py:43), so folding the order does not itself
    # recompute. The opening recompute of EVERY draft therefore runs before the order exists.
    #
    # Those opening rows are the PRELUDE and their degradation is structural. The failure that
    # matters is degradation AFTER the order has arrived. The old checks — `bases == {"my_slot"}`
    # and `orders == {12}` — collapsed the rows into a set, threw the SEQUENCE away, and so could
    # not tell the two apart: measured on a live server at 2a69c40, a healthy 7-row run failed
    # both. Reading the rows in order also buys a property nothing tested before: once the order
    # has been read, it must never be lost again.
    first_live = next(
        (i for i, row in enumerate(rows) if row.get("draft_order_len") == TEAM_COUNT), None
    )
    settled = rows[first_live:] if first_live is not None else []
    prelude_n = first_live if first_live is not None else len(rows)
    bad_lengths = sorted({o for o in orders if o not in (0, TEAM_COUNT)})
    order_lost = sum(1 for row in settled if row.get("draft_order_len") != TEAM_COUNT)
    degraded_after = sorted(
        {
            row.get("survival_basis") or "null"
            for row in settled
            if row.get("survival_basis") != "my_slot"
        }
    )
    prelude_note = (
        f"{prelude_n} prelude row(s) before the order arrived - structural, the order rides on "
        f"the first pick frame"
        if prelude_n
        else "no prelude: the order was already present on the first row"
    )

    if not settled:
        survival_detail = (
            "the order NEVER reached the engine, so survival was degraded for the WHOLE run: "
            f"{sorted(b or 'null' for b in bases)}"
        )
        order_detail = f"the order NEVER reached the engine: draft_order_len seen {sorted(orders)}"
    else:
        survival_detail = (
            f"degraded on {len(degraded_after)} basis value(s) AFTER the order arrived: "
            f"{degraded_after}"
            if degraded_after
            else f"my_slot on every row from the order onward ({len(settled)} of {len(rows)}); "
            f"{prelude_note}"
        )
        if bad_lengths:
            order_detail = (
                f"draft_order_len was neither 0 nor {TEAM_COUNT} on some row: {bad_lengths} - a "
                f"wrong-length order corrupts every 'my next pick'"
            )
        elif order_lost:
            order_detail = f"the order was LOST after arriving, on {order_lost} row(s)"
        else:
            order_detail = (
                f"len {TEAM_COUNT} from row {first_live + 1} of {len(rows)} onward; {prelude_note}"
            )

    latency_detail = (
        f"n={len(latencies)} median={statistics.median(latencies):.1f}ms "
        f"p95={_pct(latencies, 0.95):.1f}ms max={max(latencies):.1f}ms "
        f"budget={LATENCY_BUDGET_MS:.0f}ms"
        if latencies
        else "no timings recorded"
    )
    masked_detail = (
        f"unresolved (still on the board, can be recommended again): {unresolved}"
        if unresolved
        else (
            f"{max(row.get('picks_masked', 0) for row in rows)} of "
            f"{max(row.get('picks_total', 0) for row in rows)} picks masked"
        )
    )
    scarcity_detail = (
        f"candidates with vona>0 across {len(live_rows)} live recomputes: "
        f"min={min(positive)} max={max(positive)}"
        if positive
        else "no recompute ever had a live survival model"
    )

    return [
        Verdict(
            "recommendations served",
            True,
            f"{len(rows)} rows ({sum(1 for r in rows if r.get('path') == 'push')} push / "
            f"{sum(1 for r in rows if r.get('path') == 'pull')} pull)",
        ),
        Verdict(
            "survival is live",
            bool(settled) and not degraded_after,
            survival_detail,
        ),
        Verdict(
            "the order was read from the room",
            bool(settled) and not bad_lengths and not order_lost,
            order_detail,
        ),
        # The MAX, not the median: one 250 ms recompute while the clock runs is exactly what the
        # budget exists to catch, and a median hides it behind every other row.
        Verdict(
            "recompute under 200ms",
            bool(latencies) and max(latencies) < LATENCY_BUDGET_MS,
            latency_detail,
        ),
        Verdict("every drafted player masked", not unresolved, masked_detail),
        Verdict(
            "vona_method stated",
            methods == {"analytic"},
            f"vona_method values seen: {sorted(m or 'null' for m in methods)}",
        ),
        Verdict(
            "the scarcity term is live",
            bool(positive) and min(positive) > 0,
            scarcity_detail,
        ),
    ]


def _overlay_foot(row: dict) -> str:
    """What the overlay's foot rendered for this row.

    DERIVED, not observed — the backend cannot see the DOM. The chip is a pure function of
    ``survival_basis`` (``apps/extension/src/overlay/overlay.ts::renderSync``, pinned by
    ``apps/extension/tests/overlay.test.ts``), so this reproduces that ONE rule and nothing else.
    The owner's screenshot is the ground-truth cross-check.
    """
    chip = {
        "degraded_no_order": " · VONA degraded · draft order not read yet",
        "degraded_no_slot": " · VONA degraded · no draft slot set",
    }.get(row.get("survival_basis") or "", "")
    return f"recompute {round(row.get('recompute_ms') or 0)}ms{chip}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("log", type=Path, help="The JSONL written by JAAFFL_REHEARSAL_LOG.")
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"[rehearsal] no log at {args.log}", file=sys.stderr)
        return 1
    rows = [json.loads(line) for line in args.log.read_text(encoding="utf-8").splitlines() if line]

    print(f"[rehearsal] {args.log}  ({len(rows)} recommendations)   n = 1 - ONE live draft\n")
    header = (
        f"{'rnd':>4} {'ovr':>4} {'path':>5} {'basis':>18} {'ms':>7} "
        f"{'vona>0':>7} {'masked':>10}  top"
    )
    print(header)
    for row in rows:
        overall = row.get("overall") or 0
        masked = f"{row.get('picks_masked', 0)}/{row.get('picks_total', 0)}"
        print(
            f"{(overall - 1) // 12 + 1:>4} {overall:>4} {str(row.get('path')):>5} "
            f"{str(row.get('survival_basis')):>18} {row.get('recompute_ms') or 0:>7.1f} "
            f"{row.get('positive_vona_n', 0):>7} {masked:>10}  "
            f"{(row.get('top') or {}).get('name')}"
        )

    print("\n[rehearsal] verdicts")
    verdicts = evaluate(rows)
    for verdict in verdicts:
        print(f"  {'PASS' if verdict.passed else 'FAIL'}  {verdict.name:<32} {verdict.detail}")

    if rows:
        # ASCII only below the table: this prints to the owner's cp1252 console.
        print(f"\n[rehearsal] overlay foot, DERIVED from the last row: {_overlay_foot(rows[-1])}")
    failures = [verdict.name for verdict in verdicts if not verdict.passed]
    print(f"\n[rehearsal] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
