"""Tier 7 regression: the engine must draft a roster it can actually START.

Tier 6 walked a full 12x17 draft on the real 510-player board from seat 6, picks made by the live
``recommend()``, and got::

    R1:TE R2:WR R3:WR R4:WR R5:TE R6:TE R7:TE R8:TE R9:TE R10:RB R11:TE R12:TE R13:TE R14:TE
    R15:TE R16:TE R17:TE   ->   {RB: 1, TE: 13, WR: 3}

Seventeen of seventeen picks made, and **four of the nine starting slots unfillable** (QB, K, DST
and the WR/RB flex, which the 1 RB + 3 WR drain before it is reached). Identical under both
best-available and need-based opponents, so it was never an artifact of one opponent model.

Two mechanisms, both measured, neither of them the ``max(0, ·)`` that Tier 6 recorded:

1. ``league/replacement.py`` floors remaining startable demand at 0, so once a position saturates
   the baseline is ``_value_at_rank(ranked, 1)`` — **the best available player himself** — and his
   MLV is exactly ``0.0000`` by construction. Measured QB ``mu_best - baseline`` by round:
   ``R1 +51.15 · R2 +9.40 · R3 +0.32 · R4 0.0000 · R5 0.0000 …``
2. With every value signal at 0, ``lambda_slot_override`` decides: a SURPLUS candidate gets
   ``lambda = -0.4``, worth **+18.69** at the clamp-saturated ``sigma = 46.72``, while the
   LAST_OPEN_STARTABLE candidate gets ``+0.4``. At R17 the kicker's MLV had NOT collapsed — it was
   **+13.16** — and he still lost, because ``13.16 < 18.69``.

This test pins the outcome rather than either mechanism, so it keeps its meaning if the internals
move again. It runs on the offline fixture pool so CI stays network-free; the real-board check is
recorded in the Tier 7 PR body, which walks the same draft against live nflverse data.

**What is NOT yet fixed, measured on the real board 2026-07-27.** After both Tier 7 fixes the
walk from seat 6 returns::

    best-available opponents -> {DST:1, K:1, QB:1, RB:2, TE:8, WR:4}   LEGAL, all 9 slots
    need-based    opponents -> {DST:1, QB:2, RB:1, TE:9, WR:4}         K still missing

The residual is mechanism 2, untouched here because it is a live owner-adopted coefficient. At
R16 the engine took a second quarterback (Russell Wilson, MLV **-72.06**, sigma **170.08**) over
the best kicker (MLV **+2.58**, sigma 20.0): the surplus-stash ``lambda = -0.4`` pays
``+68.03`` for that variance while the last-open-startable ``+0.4`` charges the kicker ``-8.00``,
so the kicker loses by 1.4 points on risk alone. A surplus quarterback has no option value at all
— you can start only one, and the flex is WR/RB — so paying him a variance bonus is the next
defect in line. Fixing it needs E2/E6 evidence with ``--replicates >= 3``, which is Tier 8's job;
``config/engine.json`` stays owner-adopted and is not edited on simulator evidence.
"""

from __future__ import annotations

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    simulate_draft,
)
from jaaffl.league.coverage import unfillable_starting_slots

OUR_SLOT = 5  # seat 6, 0-indexed — the seat Tier 6 measured


def test_the_engine_drafts_a_roster_it_can_actually_start() -> None:
    """The headline. Every one of the nine starting slots must be fillable."""
    ctx = demo_sim_context()
    rosters = simulate_draft(
        ctx,
        our_slot=OUR_SLOT,
        our_agent=ScoreAgent(committed_engine_params()),
        opponents=[NeedBasedAgent(), AdpNoiseAgent()],
        seed=1001,
    )
    unfillable = unfillable_starting_slots(rosters[OUR_SLOT], ctx.position, ctx.slots)
    assert unfillable == [], f"cannot field a lineup; empty starting slots: {unfillable}"


def test_it_holds_against_greedy_opponents_too() -> None:
    """Tier 6 measured the identical broken roster under BOTH opponent models, so pin both."""
    from jaaffl.engine.simulate import VbdOnlyAgent

    ctx = demo_sim_context()
    rosters = simulate_draft(
        ctx,
        our_slot=OUR_SLOT,
        our_agent=ScoreAgent(committed_engine_params()),
        opponents=[VbdOnlyAgent()],
        seed=2002,
    )
    unfillable = unfillable_starting_slots(rosters[OUR_SLOT], ctx.position, ctx.slots)
    assert unfillable == [], f"cannot field a lineup; empty starting slots: {unfillable}"
