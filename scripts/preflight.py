#!/usr/bin/env python
"""Pre-draft preflight: can the board fill every STARTING slot, and is the engine's scoring live?

Run this the morning of the draft. It builds the REAL DraftContext through the same
``build_registry_context_source`` wiring the live service uses, then FAILS (exit 1) if either
guard trips: a startable position with no draftable players, or a startable position where the
tier-cliff term can never price a drop.

Why this exists: two positions were silently missing from the live board and were found only by
accident. nflverse's ff_playerids spells kicker ``PK`` while the domain spells it ``K``, so all
151 rostered kickers were dropped by an un-aliased position gate; and that table carries no
team-defense rows at all, so there were zero DSTs. In both cases the loader logged a large but
normal-looking skip count (~8,000 IDP rows), which is exactly why neither was noticed. The board
looked healthy and was not.

The tier-cliff check is the same failure one layer up, and it ran undetected for longer: on the
live 2026 board ``cliff_bonus`` held 447 entries and every single one was 0.0, so ``α·CliffBonus``
contributed 0.00 to every recommendation while the map SIZE looked entirely healthy. A count is
not a diagnostic. K and DST are exempt from failing — they are stream positions whose boards
really are flat — so only a dead cliff at a position you must actually draft for value stops the
check.

A hard failure is SAFE here and nowhere else: hours before the draft there is still time to fix
it. The equivalent check inside ``engine.precompute`` only logs a warning, because that code can
re-run mid-draft after a service restart, where an incomplete board still beats no board.

NETWORK step: pulls the free nflverse + FFC feeds (the same ones a real precompute pulls).

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/preflight.py
    .venv/Scripts/python.exe scripts/preflight.py --league-id jaaffl-2026
    .venv/Scripts/python.exe scripts/preflight.py --seed      # re-seed the crosswalk first
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from jaaffl.config import Settings, get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import DraftPick, DraftState, Position
from jaaffl.engine.context import DraftContext
from jaaffl.engine.precompute import build_registry_context_source
from jaaffl.engine.recommend import recommend
from jaaffl.league.coverage import (
    board_coverage_gaps,
    inert_cliff_positions,
    startable_positions,
    teams_missing_bye_weeks,
)

# A PROBE order, never an inference of the real one. config/league.json fixes teams=12 and records
# that the real order is decided in person and entered into CBS; preflight runs hours before that
# exists. Its only job is to prove the WIRING can produce a survival model — which is precisely
# what nothing checked until Tier 12.
_PROBE_ORDER = [str(i) for i in range(1, 13)]


def survival_probe(context: DraftContext, *, my_team_id: str | None) -> tuple[str | None, int]:
    """Ask the real ``recommend()`` whether a survival model is reachable at all.

    Returns ``(survival_basis, candidates_with_positive_vona)``. ``kappa * max(0, VONA)`` is the
    engine's entire scarcity term, and measured 2026-08-10 on the real board, with no order
    reaching the engine it was exactly 0.00 for every candidate in every one of 17 rounds — while
    the response looked completely healthy. Passes the probe order on the STATE, so nothing is
    written to the cached context.
    """
    state = DraftState(
        league_id="preflight",
        current_overall_pick=13,
        my_team_id=my_team_id,
        draft_order=_PROBE_ORDER,
        picks=[
            DraftPick(overall=o, round=1, pick_in_round=o, team_id=_PROBE_ORDER[o - 1])
            for o in range(1, 13)
        ],
    )
    rec = recommend(state, context, context.params, limit=50)
    positive = sum(1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0)
    return rec.survival_basis, positive


def survival_gate_failed(basis: str | None, positive: int) -> bool:
    """Should preflight stop the draft over this probe result?

    A named predicate rather than an inline condition in ``main`` purely so it is testable: the
    probe itself was covered and the DECISION was not, which is the same shape of blind spot this
    tier exists to close (mutating the inline condition to ``if False:`` left every probe test
    green while the real script wrongly exited 0 on an empty slot). Both halves matter — ``basis``
    alone would pass a run where the survival model was reachable but priced nothing.
    """
    return basis != "my_slot" or positive == 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--league-id",
        default="jaaffl-2026",
        help="League to build a context for (default: jaaffl-2026).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=settings.jaaffl_data_dir,
        help="App data dir holding app.sqlite (default: jaaffl_data_dir).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Re-seed the crosswalk from nflverse first (people + team defenses).",
    )
    args = parser.parse_args(argv)

    warehouse = Warehouse(args.data_dir)
    warehouse.init()
    crosswalk = Crosswalk(warehouse.app_sqlite)

    if args.seed:
        from jaaffl.providers.nflverse import NflreadpyProvider

        seeded = NflreadpyProvider(crosswalk=crosswalk).seed_crosswalk()
        print(f"[preflight] seeded {seeded} players (people + team defenses)")

    print(f"[preflight] building the real draft context for {args.league_id} ...")
    source = build_registry_context_source(
        Settings(jaaffl_data_dir=args.data_dir), warehouse=warehouse, crosswalk=crosswalk
    )
    context = source(args.league_id)
    if context is None:
        print(
            "[preflight] FAIL: no context could be built (empty universe or no projections).",
            file=sys.stderr,
        )
        return 1

    board = {pid: context.position[pid] for pid in context.mu if pid in context.position}
    counts = collections.Counter(str(position) for position in board.values())
    required = {str(position) for position in startable_positions(context.settings)}

    print(f"[preflight] draftable players on the board: {len(board)}")
    for position in sorted(counts, key=lambda p: (p not in required, p)):
        tag = "start" if position in required else "bench-only"
        print(f"[preflight]   {position:<4} {counts[position]:>5}  ({tag})")

    gaps = board_coverage_gaps(context.settings, board)
    if gaps:
        missing = ", ".join(str(position) for position in gaps)
        print(f"[preflight] FAIL: no draftable players at {missing}", file=sys.stderr)
        print(
            "[preflight] the engine cannot recommend or roster these — check the provider"
            " position codes (a source may have renamed one) before drafting.",
            file=sys.stderr,
        )
        return 1

    # Second guard: is the tier-cliff term alive? `cliff_bonus` shipped POPULATED and useless —
    # 447 entries on the live 2026 board, every one 0.0, so `alpha * CliffBonus` was 0.00 on every
    # pick. K and DST are exempt from FAILING: they are stream positions (`punt_guard` holds them
    # until R16/R17) whose boards really are flat, so demanding a cliff there would manufacture
    # urgency the data does not support. The puntable set is read from the engine params rather
    # than hard-coded, the same single source `recommend.py` reads.
    live = sum(1 for bonus in context.cliff_bonus.values() if bonus > 0.0)
    print(f"[preflight] tier-cliff term: {live} priced drops over {len(context.tiers)} tiered")
    puntable = {Position(key) for key in context.params.punt_guard.get("stream_round", {})}
    inert = inert_cliff_positions(
        context.settings, context.tiers, context.cliff_bonus, context.position
    )
    if flat := [position for position in inert if position not in puntable]:
        names = ", ".join(str(position) for position in flat)
        print(f"[preflight] FAIL: no tier cliff can ever be priced at {names}", file=sys.stderr)
        print(
            "[preflight] alpha multiplies CliffBonus, so it is inert there and the overlay's"
            " tier-cliff bar cannot move — check that projections carry real spread at those"
            " positions before drafting.",
            file=sys.stderr,
        )
        return 1
    for position in inert:
        print(f"[preflight]   note: {position} prices no tier cliff (stream position — expected).")

    # Third guard: did the bye-week join actually cover the board? REPORT-ONLY on purpose — a
    # missing bye never stops you drafting, it only costs the overlay's `bye N` chip, so failing
    # here would block a draft over a cosmetic gap. It is surfaced because the failure is silent
    # and wholesale: one unmapped team code takes that team's entire roster with it.
    on_board = {pid: context.players[pid] for pid in context.mu if pid in context.players}
    covered = sum(1 for pid in on_board if pid in context.bye_week)
    print(f"[preflight] bye weeks: {covered} of {len(on_board)} board players carry one")
    if stale := teams_missing_bye_weeks(on_board, context.bye_week):
        print(
            # ASCII only: this prints to the owner's cp1252 console, where a dash renders as a
            # replacement char (observed while proving this guard fires).
            f"[preflight]   note: no bye resolved for {', '.join(stale)}"
            " - the schedule and player feeds may have diverged (see league/schedule.py).",
        )

    # Fourth guard (TIER 12): can the engine compute a survival model AT ALL? Everything above
    # checks the BOARD; this checks the WIRING, through the real recommend(). It fails hard for
    # the same reason the missing kickers did: a dead scarcity term is invisible in a healthy
    # response, and the morning of the draft is when there is still time to fix it.
    my_team_id = get_settings().jaaffl_my_team_id
    basis, positive = survival_probe(context, my_team_id=my_team_id)
    print(
        f"[preflight] survival probe (PROBE order, not the real one): basis={basis}"
        f" - {positive} candidates with vona > 0"
    )
    if survival_gate_failed(basis, positive):
        print(
            f"[preflight] FAIL: the engine cannot compute a survival model"
            f" (JAAFFL_MY_TEAM_ID={my_team_id!r}).",
            file=sys.stderr,
        )
        print(
            "[preflight] set JAAFFL_MY_TEAM_ID in .env to your CBS team number ('1'..'12')."
            " Without a survival model every VONA is 0.00 and the engine ranks on MLV alone -"
            " a healthy-looking response carrying a dead scarcity term.",
            file=sys.stderr,
        )
        return 1

    print(f"[preflight] OK: every startable position ({', '.join(sorted(required))}) is fillable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
