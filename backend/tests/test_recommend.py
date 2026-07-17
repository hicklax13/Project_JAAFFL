"""Engine orchestrator (§3.7): the canonical Score(p) → ranked Recommendation.

The load-bearing invariant is that every RecommendedPick's ``score`` reconstructs EXACTLY from its
``ScoreComponents`` (the anti-black-box guarantee, §6.5) — no term is hidden.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.recommend import recommend
from tests.engine_fixtures import draft_state, engine_params, make_context


def _board() -> list[dict]:
    """A plausible board: elite RB/WR with big spread, compressed high-μ QBs, streamable K/DST."""
    specs: list[dict] = []
    plan = [
        (Position.RB, 30, 300.0, 6.0, 30.0),
        (Position.WR, 45, 280.0, 4.0, 32.0),
        (Position.QB, 15, 340.0, 3.0, 25.0),  # high μ but compressed → low MLV (baseline high too)
        (Position.TE, 15, 200.0, 5.0, 22.0),
        (Position.K, 14, 150.0, 3.0, 12.0),
        (Position.DST, 14, 160.0, 3.0, 14.0),
    ]
    overall = 1
    for pos, n, top, step, sigma in plan:
        for i in range(n):
            specs.append(
                {
                    "pid": f"{pos.value.lower()}{i}",
                    "pos": pos,
                    "mu": top - step * i,
                    "sigma": sigma,
                    "adp": float(overall),
                    "sd": 8.0,
                    "ecr": float(overall),
                }
            )
            overall += 1
    return specs


def test_score_reconstructs_exactly_from_components() -> None:
    """Every ranked pick: score = MLV + κ·max(0,VONA) − risk_penalty + cliff_bonus + Σ modifiers."""
    ctx = make_context(_board())
    params = ctx.params
    rec = recommend(draft_state(25), ctx, params)
    assert rec.ranked  # non-empty
    for pick in rec.ranked:
        c = pick.components
        assert c is not None
        rebuilt = (
            c.mlv
            + params.kappa * max(0.0, c.vona)
            - c.risk_penalty
            + c.cliff_bonus
            + sum(c.modifiers.values())
        )
        assert pick.score == pytest.approx(rebuilt, abs=1e-9)


def test_ranked_demotes_punted_kdst_and_sorts_by_score_within_groups() -> None:
    """At round 3 every K/DST is punted: non-K/DST rank first, then K/DST, each group desc."""
    ctx = make_context(_board())
    rec = recommend(draft_state(25), ctx, ctx.params)
    is_kdst = [ctx.position[p.player_id] in {Position.K, Position.DST} for p in rec.ranked]
    first_kdst = next((i for i, flag in enumerate(is_kdst) if flag), len(is_kdst))
    assert all(is_kdst[first_kdst:])  # once punted K/DST begin, the rest are all K/DST
    non_kdst_scores = [p.score for p, flag in zip(rec.ranked, is_kdst, strict=True) if not flag]
    kdst_scores = [p.score for p, flag in zip(rec.ranked, is_kdst, strict=True) if flag]
    assert non_kdst_scores == sorted(non_kdst_scores, reverse=True)
    assert kdst_scores == sorted(kdst_scores, reverse=True)


def test_every_pick_carries_a_fully_populated_components() -> None:
    ctx = make_context(_board())
    rec = recommend(draft_state(25), ctx, ctx.params, limit=5)
    assert len(rec.ranked) == 5
    for pick in rec.ranked:
        c = pick.components
        assert c is not None
        assert c.vona_horizon == ctx.params.vona_horizon_picks
        assert c.best_available_next is not None
        assert c.reliability is not None
        assert pick.projected_points is not None and pick.vorp is not None
        assert pick.rationale


def test_picked_players_are_masked_from_the_board() -> None:
    ctx = make_context(_board())
    taken = DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="rb0")
    rec = recommend(draft_state(2, my_team_id="t0", picks=[taken]), ctx, ctx.params)
    assert all(pick.player_id != "rb0" for pick in rec.ranked)


def test_empty_roster_r1_top_pick_is_skill_not_qb() -> None:
    """The strategy the engine PRODUCES (never hard-codes): R1 is an elite RB/WR, not a QB."""
    ctx = make_context(_board())
    rec = recommend(draft_state(1), ctx, ctx.params)
    assert ctx.position[rec.best.player_id] in {Position.RB, Position.WR}


def test_punt_guard_keeps_kicker_out_of_number_one_before_stream_round() -> None:
    """R1 belt: even a (noise-)inflated K is demoted below real starters until its stream round."""
    specs = [
        {"pid": "wr_stud", "pos": Position.WR, "mu": 260.0, "sigma": 30.0, "adp": 2.0, "sd": 6.0},
        {"pid": "k_inflated", "pos": Position.K, "mu": 400.0, "sigma": 5.0, "adp": 1.0, "sd": 6.0},
    ]
    ctx = make_context(specs)
    rec = recommend(draft_state(1), ctx, ctx.params)  # round 1 ≪ K stream round 17
    assert ctx.position[rec.best.player_id] == Position.WR
    k_rank = next(i for i, p in enumerate(rec.ranked) if p.player_id == "k_inflated")
    assert k_rank > 0  # the K exists but is demoted out of #1


def test_reasoning_carries_resolved_engine_params() -> None:
    ctx = make_context(_board())
    rec = recommend(draft_state(1), ctx, engine_params())
    assert (
        "κ=" in rec.reasoning
        and "flex_split=" in rec.reasoning
        and "EngineParams v" in rec.reasoning
    )


def test_ranked_picks_are_enriched_with_player_identity() -> None:
    """The UI is a pure consumer: each RecommendedPick must carry its display identity
    (name/position/team) from the context player universe so a pick is self-describing (§6.2)."""
    ctx = make_context(_board())
    rec = recommend(draft_state(1), ctx, ctx.params, limit=5)
    best = rec.ranked[0]
    assert best.name == ctx.players[best.player_id].name
    assert best.position == ctx.players[best.player_id].position
    assert best.nfl_team == ctx.players[best.player_id].nfl_team
    for pick in rec.ranked:
        assert pick.position is not None  # needed for the pos chip + MLV colouring
