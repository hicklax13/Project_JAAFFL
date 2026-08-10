"""Engine orchestrator (§3.7): the canonical Score(p) → ranked Recommendation.

The load-bearing invariant is that every RecommendedPick's ``score`` reconstructs EXACTLY from its
``ScoreComponents`` (the anti-black-box guarantee, §6.5) — no term is hidden.
"""

from __future__ import annotations

import dataclasses

import pytest

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.recommend import recommend
from tests.engine_fixtures import (
    draft_state,
    engine_params,
    jaaffl_settings,
    make_context,
)


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


def test_recommendation_carries_the_roster_and_recompute_footer_fields() -> None:
    """§6.3 anatomy #6 — the overlay foot renders `Roster n/17 · RB … · WR …` + `recompute Nms`.

    The overlay is a pure consumer that receives ONLY a Recommendation (never a DraftState), so
    the engine has to supply both. Deriving a roster from pick numbers client-side would infer
    draft structure, which config/league.json (`infer_from_team_count: false`) forbids.
    """
    ctx = make_context(_board())
    state = draft_state(
        27,
        picks=[
            DraftPick(overall=3, round=1, pick_in_round=3, team_id="t0", player_id="rb0"),
            DraftPick(overall=22, round=2, pick_in_round=10, team_id="t0", player_id="wr1"),
            DraftPick(overall=5, round=1, pick_in_round=5, team_id="t1", player_id="rb1"),
        ],
    )
    rec = recommend(state, ctx, ctx.params, limit=5)

    assert rec.roster_filled == 2  # only MY picks — t1's rb1 is somebody else's
    assert rec.roster_size == 17  # 9 starters + 8 bench, the league constitution
    assert rec.roster_by_position == {"RB": 1, "WR": 1}
    assert rec.recompute_ms is not None
    assert rec.recompute_ms > 0.0


def test_mc_vona_is_the_default_off_and_reports_the_analytic_method() -> None:
    """Regression guard: `use_mc_vona` used to appear ONLY on the signature line and was never
    referenced, so `?mc=true` was a silent no-op. The method now has to be stated either way."""
    ctx = make_context(_board())
    rec = recommend(draft_state(3), ctx, ctx.params, limit=5)
    assert rec.vona_method == "analytic"
    assert "analytic VONA" in (rec.reasoning or "")


def test_mc_vona_changes_the_numbers_and_says_which_method_produced_them() -> None:
    """MC and analytic estimate the SAME quantity by different opponent models — the analytic form
    multiplies independent survivals, MC couples them. They must therefore disagree, and the
    response must say which one the owner is looking at."""
    ctx = make_context(_board())
    state = draft_state(3)
    analytic = recommend(state, ctx, ctx.params, limit=25)
    mc = recommend(state, ctx, ctx.params, limit=25, use_mc_vona=True)

    assert mc.vona_method == "monte_carlo"
    assert "MC VONA" in (mc.reasoning or "")

    lhs = {p.player_id: p.components.vona for p in analytic.ranked if p.components}
    rhs = {p.player_id: p.components.vona for p in mc.ranked if p.components}
    shared = set(lhs) & set(rhs)
    assert shared, "the two runs must rank overlapping players to be comparable"
    assert any(abs(lhs[pid] - rhs[pid]) > 1e-6 for pid in shared), (
        "MC VONA is indistinguishable from analytic — the flag is still a no-op"
    )


def test_mc_vona_is_reproducible_run_to_run() -> None:
    """Two identical MC requests must agree, or the owner sees the board flicker between
    refreshes."""
    ctx = make_context(_board())
    state = draft_state(3)
    first = recommend(state, ctx, ctx.params, limit=10, use_mc_vona=True)
    second = recommend(state, ctx, ctx.params, limit=10, use_mc_vona=True)
    assert [p.player_id for p in first.ranked] == [p.player_id for p in second.ranked]
    assert [p.components.vona for p in first.ranked if p.components] == [
        p.components.vona for p in second.ranked if p.components
    ]


def test_mc_vona_degrades_to_analytic_without_a_readable_draft_order() -> None:
    """No draft order → no honest picks-between count. Fall back to analytic and SAY analytic
    rather than reporting a Monte-Carlo number computed against a fabricated snake."""
    ctx = make_context(_board(), settings=jaaffl_settings(draft_order=None))
    rec = recommend(draft_state(3), ctx, ctx.params, limit=5, use_mc_vona=True)
    assert rec.vona_method == "analytic"


def test_mc_vona_honours_the_mc_rollouts_budget_knob(monkeypatch) -> None:
    """MC is NOT free: measured p95 ≈ 1.14 s at the shipped mc_rollouts=2000 on the pick-1 worst
    case, against the plan's <2 s MC budget (analytic stays ≈9 ms). `mc_rollouts` therefore has to
    be a real lever — it is how the owner trades estimate precision for latency.

    ⚠️ This asserted a RATIO between two wall-clock samples (`dear_ms > cheap_ms * 3.0`) until
    2026-08-10, when it failed once during a full suite run while the machine was loaded by
    background servers and subprocess tests — and passed 12/12 in isolation immediately after. A
    test that can fail on machine load is noise in CI, and noise gets trained away.

    So it now asserts the LEVER instead of the latency: that `mc_rollouts` actually arrives at
    `simulate.mc_expected_best_available` as `n_sims`. That is the property the knob IS, it is
    deterministic, and it is strictly STRONGER than the timing version — the old assertion could
    only infer the knob was connected from a ratio it hoped was signal, and with `dear` mutated
    down to `cheap`'s count it survived 4 runs in 6 before the margin was widened.

    The cost claim in the first paragraph stays as a recorded measurement rather than an
    assertion. Nothing wall-clock guards it now, and that is deliberate: MC is opt-in
    (`mc_enabled: false` in config/engine.json) and off the draft-night path entirely, while the
    budget that does matter — the <200 ms ANALYTIC recompute — is held by
    `tests/test_engine_latency.py` and `tests/test_cold_start_latency.py`.
    """
    import jaaffl.engine.simulate as simulate

    ctx = make_context(_board())
    state = draft_state(3)

    seen: list[int] = []
    real = simulate.mc_expected_best_available

    def spy(*args, n_sims: int, **kwargs):
        seen.append(n_sims)
        return real(*args, n_sims=n_sims, **kwargs)

    # `_mc_expected_best` imports the symbol INSIDE the function, so patching the module attribute
    # is what the call actually resolves.
    monkeypatch.setattr(simulate, "mc_expected_best_available", spy)

    lo = recommend(state, ctx, engine_params(mc_rollouts=100), limit=5, use_mc_vona=True)
    hi = recommend(state, ctx, engine_params(mc_rollouts=1000), limit=5, use_mc_vona=True)

    assert lo.vona_method == "monte_carlo" and hi.vona_method == "monte_carlo"
    assert seen, "the simulator was never reached — MC VONA silently fell back to analytic"
    assert set(seen) == {100, 1000}, (
        f"mc_rollouts does not reach the simulator — the budget knob is inert (n_sims seen: {seen})"
    )
    assert "100 rollouts" in (lo.reasoning or "")
    assert "1000 rollouts" in (hi.reasoning or "")


def test_the_analytic_hot_path_never_imports_the_simulator() -> None:
    """The <200ms analytic budget must not pay for MC merely existing: `simulate` is imported
    lazily, only when ?mc=true actually asks for it. (numpy is NOT part of this claim — tiers.py
    and opponents.py legitimately vectorize on the hot path.)"""
    import sys

    sys.modules.pop("jaaffl.engine.simulate", None)
    ctx = make_context(_board())
    recommend(draft_state(3), ctx, ctx.params, limit=5)  # default analytic path
    assert "jaaffl.engine.simulate" not in sys.modules


def test_the_analytic_hot_path_never_imports_the_weekly_model() -> None:
    """Same claim for Tier 11's ``engine.weekly``. It is a CALIBRATION object — it allocates a
    ``(draws, weeks, players)`` array and exists to score finished rosters, never to rank a pick —
    so the live recommendation must not pay for it existing. ``calibrate.tune`` imports it inside
    the objective methods for exactly this reason."""
    import sys

    sys.modules.pop("jaaffl.engine.weekly", None)
    ctx = make_context(_board())
    recommend(draft_state(3), ctx, ctx.params, limit=5)
    assert "jaaffl.engine.weekly" not in sys.modules


def test_ranked_picks_carry_their_projection_provenance() -> None:
    """`PlayerProjection.sources` records exactly which $0 sources backed each player's mu, and
    after Tier 1 the live board still has ~70 players with ECR ONLY — no real projection, mu still
    on the `300 − rank` fallback curve. That never left the backend, so the owner could not tell a
    modeled projection from a rank-derived guess. It has to ride the pick."""
    specs = [
        {
            "pid": "backed",
            "pos": Position.WR,
            "mu": 260.0,
            "sigma": 30.0,
            "adp": 1.0,
            "ecr": 1.0,
            "sources": {"xep": 265.0, "ecr": 255.0},
        },
        {
            "pid": "fallback",
            "pos": Position.WR,
            "mu": 240.0,
            "sigma": 30.0,
            "adp": 2.0,
            "ecr": 2.0,
            "sources": {"ecr": 240.0},
        },
    ]
    rec = recommend(draft_state(1), make_context(specs), engine_params(), limit=5)
    by_id = {p.player_id: p for p in rec.ranked}

    # Sorted, so the rendered chip is stable between recomputes rather than dict-order dependent.
    assert by_id["backed"].projection_sources == ["ecr", "xep"]
    assert by_id["fallback"].projection_sources == ["ecr"]


def test_projection_provenance_is_absent_rather_than_faked_when_unknown() -> None:
    """A context with no recorded sources must yield None — an empty list would read as "we
    checked and there are none", which is a different and false claim."""
    specs = [{"pid": "p", "pos": Position.WR, "mu": 200.0, "sigma": 20.0, "adp": 1.0}]
    rec = recommend(draft_state(1), make_context(specs), engine_params(), limit=1)
    assert rec.ranked[0].projection_sources is None


# --- Tier 10: the live ranking must be a decision, not context.mu insertion order -------------


def _full_lineup() -> tuple[list[DraftPick], object]:
    """A pick log filling OUR nine starting slots, and the params under which the remaining
    below-replacement candidates all score exactly 0.0 — a filled slot makes every position
    SURPLUS, so the surplus ceiling is the only lambda any candidate can receive.

    ⚠️ Honest limit on this fixture, measured 2026-08-09: ``_board()`` yields exactly ONE tier per
    position, so ``cliff_bonuses`` returns 0.0 for all 133 players — ``alpha`` multiplies an
    identically-zero map, which is the Tier 5 defect in miniature. The tie is therefore EASIER to
    produce here than on the real board, where the cliff term is live (19 priced drops at the last
    preflight). The real board's tie is established independently — 180 of 180 candidates at round
    14, measured through ``recommend()`` itself — and holds there because ``cliff_bonuses`` is
    computed from EMPTY-roster MLV (``engine/context.py``), which is 0 for a below-replacement
    player however the board is tiered.
    """
    mine = ["qb0", "rb0", "wr0", "wr1", "wr2", "wr3", "te0", "k0", "dst0"]
    picks = [
        DraftPick(overall=i + 1, round=i + 1, pick_in_round=1, team_id="t0", player_id=pid)
        for i, pid in enumerate(mine)
    ]
    params = engine_params(
        lambda_slot_override={"last_startable_slot_floor": 0.0, "surplus_stash_ceiling": 0.0}
    )
    return picks, params


def test_ranking_does_not_depend_on_context_insertion_order() -> None:
    """Tier 10: with the starting nine full, MLV is 0, kappa*max(0,VONA) clamps to 0, the cliff is
    0 below replacement and lambda is 0 for a SURPLUS position — every below-replacement candidate
    scores EXACTLY 0.0. `picks.sort` is stable, so the ranking WAS `context.mu` insertion order.
    Measured on the real board: 180 of 180 candidates tied at round 14, and the engine's #1 was
    81.4 projected points worse than the best player it tied with.

    Only `mu`'s insertion order is varied — not the specs — so nothing else can explain a diff.
    """
    picks, params = _full_lineup()
    context = make_context(_board(), params=params)
    flipped = dataclasses.replace(context, mu=dict(reversed(list(context.mu.items()))))
    state = draft_state(len(picks) + 1, picks=picks)
    forward = recommend(state, context, params)
    backward = recommend(state, flipped, params)
    # Anti-vacuity: two matching rankings prove nothing if the fixture stopped producing a tie.
    tied = [p for p in forward.ranked if p.score == pytest.approx(0.0, abs=1e-9)]
    assert len(tied) > 1, "fixture no longer produces a tie — the test would prove nothing"
    assert [p.player_id for p in forward.ranked] == [p.player_id for p in backward.ranked]


def test_tied_scores_rank_by_value_over_replacement() -> None:
    """Order-independence alone would be satisfied by sorting on player id — arbitrary but stable.
    Within the block the score cannot separate, the engine must prefer the player the board rates
    higher."""
    picks, params = _full_lineup()
    context = make_context(_board(), params=params)
    state = draft_state(len(picks) + 1, picks=picks)
    rec = recommend(state, context, params)
    zero = [p for p in rec.ranked if p.score == pytest.approx(0.0, abs=1e-9)]
    assert len(zero) > 1, "fixture no longer produces a tie — the test would prove nothing"
    vor = [p.projected_points - p.components.replacement_baseline for p in zero]
    assert vor == sorted(vor, reverse=True)
