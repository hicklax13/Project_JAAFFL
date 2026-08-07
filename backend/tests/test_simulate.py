"""Draft simulator (E2/E6 substrate, §9.2): agents + a full 17-round snake to completion.

Our ScoreAgent (params-sensitive) plays behavioral opponents; simulate_draft returns all 12 final
rosters, scored by optimal_lineup_value (the flex-aware optimal 9). Pure numpy — no new heavy deps —
but it lives in `engine.simulate`; tests importorskip nothing (numpy is in the base `engine` extra).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SimContext,
    VbdOnlyAgent,
    mc_expected_best_available,
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


def test_score_agent_reliability_shrinkage_defers_a_high_variance_dst() -> None:
    from jaaffl.engine.optimize import expand_starting_slots

    # A DST outvalues an RB on raw μ, but reliability shrinkage (R1) pulls the noisy DST toward its
    # replacement so our agent takes the RB and defers the DST (the "don't draft K/DST early" fix).
    ctx = SimContext(
        value={"rb_a": 190.0, "dst_a": 200.0},
        position={"rb_a": Position.RB, "dst_a": Position.DST},
        baselines=dict.fromkeys(Position, 50.0),
        slots=expand_starting_slots(_settings()),
        roster_size=17,
    )
    no_rel = EngineParams(kappa=0.0, alpha=0.0, lambda_schedule=[], reliability_shrinkage={})
    assert (
        ScoreAgent(no_rel).pick(["rb_a", "dst_a"], [], ctx) == "dst_a"
    )  # DST MLV 150 > RB MLV 140
    shrink = EngineParams(
        kappa=0.0, alpha=0.0, lambda_schedule=[], reliability_shrinkage={"DST": 0.1}
    )
    # DST eff = 50 + 0.1·(200−50) = 65 → MLV 15 << RB MLV 140.
    assert ScoreAgent(shrink).pick(["rb_a", "dst_a"], [], ctx) == "rb_a"


def test_score_agent_defaults_its_candidate_cap_to_the_configured_one() -> None:
    """E2 tunes `EngineParams`, so the simulated agent must deliberate over the same candidate
    set the shipped `recommend()` does. `ScoreAgent` hardcoded 50 while `config/engine.json` says
    180 and `evaluate_params` never passed one — so E2's numbers described a non-shipping agent."""
    assert ScoreAgent(EngineParams(candidate_cap=137))._cap == 137
    assert ScoreAgent(EngineParams(candidate_cap=137), candidate_cap=9)._cap == 9  # explicit wins


def test_score_agent_ranks_candidates_by_mlv_so_it_can_fill_a_k_or_dst_slot() -> None:
    """`recommend()` caps by MLV; `ScoreAgent` capped by RAW VALUE. K and DST have low raw value but
    high MLV the moment their dedicated slot is empty, so a value-ranked cap hides them entirely —
    the simulated agent could not draft a DST at all, which silently made `reliability_shrinkage`
    (a parameter `run_study` tunes) unable to affect a single pick."""
    from jaaffl.engine.optimize import expand_starting_slots

    # Twelve deep WRs outrank the only DST on raw value; with a cap of 3 a value-ranked agent never
    # sees dst_a. On MLV, dst_a (fills an empty dedicated slot) beats a fourth-best WR.
    value = {f"wr{i}": 150.0 - i for i in range(12)} | {"dst_a": 90.0}
    position = {pid: (Position.DST if pid == "dst_a" else Position.WR) for pid in value}
    ctx = SimContext(
        value=value,
        position=position,
        baselines=dict.fromkeys(Position, 40.0),
        slots=expand_starting_slots(_settings()),
        roster_size=17,
    )
    params = EngineParams(kappa=0.0, alpha=0.0, lambda_schedule=[], reliability_shrinkage={})
    roster = ["wr0", "wr1", "wr2", "wr3"]  # WR slots + flex already full → another WR adds nothing
    agent = ScoreAgent(params, candidate_cap=3)
    assert agent.pick(sorted(value), roster, ctx) == "dst_a"


def test_softmax_vbd_agent_is_stochastic_but_still_prefers_value() -> None:
    """The training opponent that lets `AdpNoiseAgent` move to the HELD-OUT set while keeping the
    two sets disjoint. It must actually consume its rng — a second deterministic opponent would
    reproduce the `--eval-seeds`-is-inert bug on the training side."""
    from jaaffl.engine.simulate import SoftmaxVbdAgent

    ctx = _big_ctx()
    agent = SoftmaxVbdAgent()
    pool = ["rb0", "rb1", "rb2", "rb30", "wr40", "qb20"]

    picks = {agent.pick(pool, [], ctx, np.random.default_rng(seed)) for seed in range(40)}
    assert len(picks) > 1, "a deterministic training opponent leaves the study seed-blind"

    counts: dict[str, int] = {}
    for seed in range(400):
        choice = agent.pick(pool, [], ctx, np.random.default_rng(seed))
        counts[choice] = counts.get(choice, 0) + 1
    # Near-indifferent between adjacent-ranked players (a 1-point VBD gap), but it does not reach:
    # rb30 is 30 points of VBD worse and qb20 is 200 worse.
    assert counts.get("rb0", 0) + counts.get("rb1", 0) + counts.get("rb2", 0) > 380
    assert counts.get("qb20", 0) == 0

    # No rng -> deterministic argmax, matching every other agent's convention.
    assert agent.pick(pool, [], ctx) == "rb0"


def test_softmax_vbd_agent_survives_large_vbd_without_overflow() -> None:
    """Raw VBD reaches the hundreds; `exp(600/4)` overflows to inf and poisons the weights."""
    from jaaffl.engine.simulate import SoftmaxVbdAgent

    ctx = _big_ctx()
    huge = dataclasses.replace(ctx, value={pid: v * 50.0 for pid, v in ctx.value.items()})
    choice = SoftmaxVbdAgent().pick(["rb0", "rb1", "wr0"], [], huge, np.random.default_rng(0))
    assert choice in {"rb0", "rb1", "wr0"}


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


def _rb_candidates() -> tuple[list[str], dict[Position, list[str]], dict[str, float]]:
    """RB0-11 as the position pool, MLV strictly decreasing so depletion is legible."""
    ctx = _big_ctx()
    available = list(ctx.value)
    by_pos = {Position.RB: [f"rb{i}" for i in range(12)]}
    mlv = {pid: ctx.value[pid] for pid in available}
    return available, by_pos, mlv


def test_mc_expected_best_available_falls_as_opponents_pick_more() -> None:
    """MC-VONA substrate (§3.9): E[best surviving MLV at a position] must DROP as more opponent
    picks land between now and my next turn — that decay is the whole scarcity signal."""
    ctx = _big_ctx()
    available, by_pos, mlv = _rb_candidates()
    kwargs = {"available": available, "candidates_by_position": by_pos, "mlv": mlv, "n_sims": 60}

    shallow = mc_expected_best_available(ctx, picks_between=1, seed=7, **kwargs)
    deep = mc_expected_best_available(ctx, picks_between=14, seed=7, **kwargs)
    assert deep[Position.RB] < shallow[Position.RB]


def test_mc_expected_best_available_is_reproducible_from_its_seed() -> None:
    """Same seed → same number. An estimator that drifts run-to-run cannot be calibrated."""
    ctx = _big_ctx()
    available, by_pos, mlv = _rb_candidates()
    kwargs = {
        "available": available,
        "candidates_by_position": by_pos,
        "mlv": mlv,
        "picks_between": 8,
        "n_sims": 40,
    }
    assert mc_expected_best_available(ctx, seed=3, **kwargs) == mc_expected_best_available(
        ctx, seed=3, **kwargs
    )


def test_mc_expected_best_available_actually_consumes_its_rng() -> None:
    """Different seeds must give different answers, or the Monte Carlo is decoration — exactly the
    failure mode the E2 harness has with its deterministic NeedBasedAgent held-out opponent."""
    ctx = _big_ctx()
    available, by_pos, mlv = _rb_candidates()
    kwargs = {
        "available": available,
        "candidates_by_position": by_pos,
        "mlv": mlv,
        "picks_between": 10,
        "n_sims": 25,
    }
    assert mc_expected_best_available(ctx, seed=1, **kwargs) != mc_expected_best_available(
        ctx, seed=2, **kwargs
    )


def test_mc_expected_best_available_degrades_to_replacement_when_the_pool_empties() -> None:
    """No survivor at a position → the positional replacement baseline, matching the analytic
    estimator's own fallback rather than 0.0 or a crash."""
    ctx = _big_ctx()
    available = [f"rb{i}" for i in range(3)]
    by_pos = {Position.RB: list(available)}
    mlv = {pid: ctx.value[pid] for pid in available}
    out = mc_expected_best_available(
        ctx,
        available=available,
        candidates_by_position=by_pos,
        mlv=mlv,
        picks_between=3,  # every RB is gone before my turn
        n_sims=10,
        seed=0,
    )
    assert out[Position.RB] == pytest.approx(ctx.baselines[Position.RB])


def test_mc_expected_best_available_matches_the_adp_agent_model_with_no_noise() -> None:
    """The vectorized sampler IS AdpNoiseAgent's model, not a lookalike. With σ=0 both reduce to
    argmin(adp), so a no-noise rollout must agree with the agent's own deterministic sequence —
    pinning the two together so the MC path cannot silently diverge from the opponent model."""
    base = _big_ctx()
    ctx = SimContext(
        value=base.value,
        position=base.position,
        baselines=base.baselines,
        slots=base.slots,
        roster_size=base.roster_size,
        adp=base.adp,
        adp_stdev=dict.fromkeys(base.adp, 0.0),  # no noise → both are pure argmin(adp)
    )
    available = list(ctx.value)
    picks_between = 6

    agent, remaining = AdpNoiseAgent(), set(available)
    for _ in range(picks_between):
        remaining.discard(agent.pick(sorted(remaining), (), ctx, None))

    by_pos = {Position.RB: [f"rb{i}" for i in range(12)]}
    mlv = {pid: ctx.value[pid] for pid in available}
    out = mc_expected_best_available(
        ctx,
        available=available,
        candidates_by_position=by_pos,
        mlv=mlv,
        picks_between=picks_between,
        n_sims=1,
        seed=0,
    )
    expected = max(mlv[pid] for pid in by_pos[Position.RB] if pid in remaining)
    assert out[Position.RB] == pytest.approx(expected)


def test_no_simulated_team_drafts_a_player_it_cannot_roster() -> None:
    """The opponent field was manufacturing a famine no engine could survive.

    Measured 2026-08-07 on the fixture pool: the vbd-only field took **15 of 15** kickers and
    **15 of 15** defenses for 12 teams and rostered 13 players illegally. On the real 581-player
    board it took **33 of 33** draftable kickers. Once an agent's dedicated need is met it falls
    through to greedy VBD, and late in the draft VBD favours streaming positions — a remaining
    kicker sits within a few points of his baseline while a 200th-ranked receiver is 60 below his.

    That artifact, not the scoring rule, is what Tier 6, Tier 7 and Tier 8's own first pass all
    diagnosed as "the engine cannot draft a kicker": swept over 12 seats x 2 opponent fields, the
    shipped engine is 24/24 illegal against this field and **0/24 against opponents that draft
    legal rosters**, taking its kicker at median R16.
    """
    from collections import Counter

    from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
    from jaaffl.engine.simulate import ScoreAgent, VbdOnlyAgent, simulate_draft

    ctx = demo_sim_context()
    rosters = simulate_draft(
        ctx,
        our_slot=5,
        our_agent=ScoreAgent(committed_engine_params()),
        opponents=[VbdOnlyAgent()],
        seed=2002,
    )
    illegal = [
        (team, position.value, held, ctx.roster_capacity[position])
        for team, roster in enumerate(rosters)
        for position, held in Counter(ctx.position[pid] for pid in roster).items()
        if held > ctx.roster_capacity[position]
    ]
    assert illegal == [], f"(team, position, held, capacity) rostered illegally: {illegal}"
