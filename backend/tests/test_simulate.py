"""Draft simulator (E2/E6 substrate, §9.2): agents + a full 17-round snake to completion.

Our ScoreAgent (params-sensitive) plays behavioral opponents; simulate_draft returns all 12 final
rosters, scored by optimal_lineup_value (the flex-aware optimal 9). Pure numpy — no new heavy deps —
but it lives in `engine.simulate`; tests importorskip nothing (numpy is in the base `engine` extra).
"""

from __future__ import annotations

import numpy as np

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SimContext,
    VbdOnlyAgent,
    optimal_lineup_value,
    simulate_draft,
    simulate_drafts,
)


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="L",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=3, starting=True),
            RosterSlot(
                slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1, starting=True
            ),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1, starting=True),
            RosterSlot(slot="K", eligible_positions=[Position.K], count=1, starting=True),
            RosterSlot(slot="DST", eligible_positions=[Position.DST], count=1, starting=True),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=8,
                starting=False,
            ),
        ],
    )


def _big_ctx(n: int = 260) -> SimContext:
    """A synthetic pool large enough for a 12×17 = 204-pick draft, ADP == value rank."""
    value, position, adp, adp_stdev, baselines = {}, {}, {}, {}, {}
    # Ensure enough of each rosterable position; K/DST just enough for 12 each.
    plan = (
        [(Position.RB, 90)]
        + [(Position.WR, 90)]
        + [(Position.QB, 30)]
        + [(Position.TE, 25)]
        + [(Position.K, 15)]
        + [(Position.DST, 15)]
    )
    idx = 0
    for pos, count in plan:
        for k in range(count):
            pid = f"{pos.value.lower()}{k}"
            value[pid] = float(300 - idx)  # strictly decreasing global value
            position[pid] = pos
            adp[pid] = float(idx + 1)
            adp_stdev[pid] = 8.0
            idx += 1
    for pos in (Position.QB, Position.RB, Position.WR, Position.TE, Position.K, Position.DST):
        baselines[pos] = 40.0
    from jaaffl.engine.optimize import expand_starting_slots

    return SimContext(
        value=value,
        position=position,
        baselines=baselines,
        slots=expand_starting_slots(_settings()),
        roster_size=17,
        adp=adp,
        adp_stdev=adp_stdev,
    )


def test_optimal_lineup_value_scores_the_flex_aware_optimal_nine() -> None:
    ctx = _big_ctx()
    roster = ["rb0", "rb1", "wr0", "wr1", "wr2", "wr3", "qb0", "te0", "k0", "dst0"]
    from jaaffl.engine.optimize import lineup_value

    expected = lineup_value(roster, ctx.value, ctx.position, ctx.baselines, ctx.slots)
    assert optimal_lineup_value(roster, ctx) == expected


def test_vbd_only_agent_takes_the_highest_value_over_replacement() -> None:
    ctx = _big_ctx()
    # All baselines equal, so VBD ranks by raw value; rb5 (value 295) beats wr0 (210) and qb0 (120).
    assert VbdOnlyAgent().pick(["rb5", "wr0", "qb0"], [], ctx) == "rb5"


def test_need_based_agent_fills_an_empty_starting_slot_first() -> None:
    ctx = _big_ctx()
    # Roster already has the RB and all it needs except a QB starter; a high-value WR is available
    # but the agent should take the QB to fill the empty QB slot.
    roster = ["rb0", "wr0", "wr1", "wr2", "rb1", "te0", "k0", "dst0"]  # no QB yet
    pick = NeedBasedAgent().pick(["wr3", "qb0"], roster, ctx)
    assert pick == "qb0"


def test_adp_noise_agent_with_zero_noise_takes_the_lowest_adp() -> None:
    ctx = _big_ctx()
    zero_noise = SimContext(
        value=ctx.value,
        position=ctx.position,
        baselines=ctx.baselines,
        slots=ctx.slots,
        roster_size=ctx.roster_size,
        adp=ctx.adp,
        adp_stdev={p: 0.0 for p in ctx.adp_stdev},
    )
    # Agents are stateless; simulate_draft owns the seeded rng and passes it to pick().
    pick = AdpNoiseAgent().pick(["wr5", "rb0", "qb0"], [], zero_noise, np.random.default_rng(0))
    assert pick == "rb0"  # rb0 has adp 1 (lowest); zero noise → deterministic argmin


def _scarcity_ctx() -> SimContext:
    """rb_a and wr_a have equal value, but RB cliffs to rb_b while WR is deep (wr_b close).
    So VONA(rb_a) >> VONA(wr_a) — a κ-weighted agent should prefer the scarcer RB."""
    from jaaffl.engine.optimize import expand_starting_slots

    value = {"rb_a": 200.0, "rb_b": 100.0, "wr_a": 200.0, "wr_b": 190.0}
    position = {
        "rb_a": Position.RB,
        "rb_b": Position.RB,
        "wr_a": Position.WR,
        "wr_b": Position.WR,
    }
    baselines = {p: 50.0 for p in Position}
    return SimContext(
        value=value,
        position=position,
        baselines=baselines,
        slots=expand_starting_slots(_settings()),
        roster_size=17,
    )


def test_score_agent_reduces_to_greedy_mlv_when_weights_are_zero() -> None:
    ctx = _big_ctx()
    params = EngineParams(kappa=0.0, alpha=0.0, lambda_schedule=[])
    # On an empty roster MLV = value − baseline (VBD), so zero-weight Score == best VBD == rb5.
    assert ScoreAgent(params).pick(["rb5", "wr0", "qb0"], [], ctx) == "rb5"


def test_score_agent_vona_prefers_the_scarcer_position() -> None:
    ctx = _scarcity_ctx()
    high_kappa = EngineParams(kappa=1.0, alpha=0.0, lambda_schedule=[])
    # Equal MLV, but rb_a's within-position cliff (VONA) dwarfs wr_a's → the RB wins under κ.
    assert ScoreAgent(high_kappa).pick(["rb_a", "rb_b", "wr_a", "wr_b"], [], ctx) == "rb_a"
    # With κ=0 the tie is MLV-only (equal) — first in deterministic order; not rb_a-forced.
    no_vona = EngineParams(kappa=0.0, alpha=0.0, lambda_schedule=[])
    assert ScoreAgent(no_vona).pick(["wr_a", "rb_a"], [], ctx) in {"wr_a", "rb_a"}


def test_simulate_draft_produces_twelve_complete_disjoint_rosters() -> None:
    ctx = _big_ctx()
    rosters = simulate_draft(
        ctx, our_slot=3, our_agent=VbdOnlyAgent(), opponents=[VbdOnlyAgent()], seed=7
    )
    assert len(rosters) == 12
    assert all(len(r) == ctx.roster_size for r in rosters)
    drafted = [pid for r in rosters for pid in r]
    assert len(drafted) == len(set(drafted)) == 12 * ctx.roster_size  # no player twice


def test_simulate_drafts_ranks_candidates_by_expected_roster_value() -> None:
    # MC-VONA rollout: taking the elite rb0 first should beat taking the much weaker rb80 first.
    ctx = _big_ctx()
    result = simulate_drafts(
        ctx, my_roster=[], candidates=["rb0", "rb80"], picks_between=11, n_sims=6, seed=1
    )
    assert set(result) == {"rb0", "rb80"}
    assert result["rb0"] > result["rb80"]


def test_simulate_drafts_is_deterministic_for_a_seed() -> None:
    ctx = _big_ctx()
    kw = dict(my_roster=[], candidates=["rb0"], picks_between=11, n_sims=4, seed=3)
    assert simulate_drafts(ctx, **kw) == simulate_drafts(ctx, **kw)
