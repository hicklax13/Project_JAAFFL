"""TIER 3 / TASK 1 — the real capture, driven the whole way to a rendered recommendation.

``test_e2e_cbs_pipeline.py`` pins this seam with events hand-written in Python "shaped exactly
like" the goldens. That is the failure mode this project keeps re-learning: it looks like it
tests the pipeline, but ``parse.ts`` is not in the loop, so the Python dicts could drift from
what the parser actually emits and every assertion would stay green.

This test consumes ``apps/extension/tests/fixtures/cbs/full-draft.events.json`` — the literal
output of ``parse.ts`` over every frame of a complete real 12x14 CBS draft, regenerated and
drift-guarded by ``apps/extension/tests/replay.test.ts`` — and drives it through the REAL
ingest path: ``handle_event`` -> durable append -> ``fold_state`` -> ``resolve_pick_ids`` ->
``recommend()``. Nothing about the event stream is hand-authored here.

What is asserted is DATA, not health signals: a NAMED player really drafted in a real frame is
absent from the board, and the recommendation that comes back carries a non-zero ``vona``. The
Tier-1 bug returned HTTP 200 with three ranked picks and a full decomposition while every
``vona`` was 0.00, because an empty crosswalk resolved 0/179 ADP — a dead opponent model behind
a healthy status code.

Scope, stated plainly: the crosswalk mapping, the names, the positions and the NFL teams are
REAL (``cbs_replay_players.json``, exported from the seeded crosswalk by
``scripts/export_replay_players.py``). ``mu``/``sigma`` here are NOT real projections — they are
a monotone stand-in derived from observed draft position, because a committed projection
snapshot would drift and this test is about the WIRING. Real mu/sigma are built and tested in
``test_projections.py`` / ``test_xep.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaaffl.domain import DraftEvent, Position
from jaaffl.engine.recommend import recommend
from jaaffl.ingest import handle_event
from jaaffl.ingest.log import DraftLog
from jaaffl.ingest.resolve import resolve_pick_ids
from tests.engine_fixtures import engine_params, jaaffl_settings, make_context

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs" / "full-draft.events.json"
PLAYERS = Path(__file__).resolve().parent / "fixtures" / "cbs_replay_players.json"

TEAMS = 12
CAPTURE_ROUNDS = 14


@pytest.fixture(scope="module")
def replay_events() -> list[DraftEvent]:
    """parse.ts's own output over the real capture, as DraftEvent contract models."""
    raw = json.loads(EVENTS.read_text(encoding="utf-8"))
    return [DraftEvent.model_validate(e) for e in raw]


@pytest.fixture(scope="module")
def replay_players() -> dict[str, dict]:
    """cbs id -> {canonical_id, name, position, nfl_team} for the ids in the capture."""
    return json.loads(PLAYERS.read_text(encoding="utf-8"))["players"]


def _ingest_all(events: list[DraftEvent], db_path: Path):
    """Drive every event through the REAL ingest entry point and return the folded state."""
    draft_log = DraftLog(db_path)
    result = None
    for event in events:
        result = handle_event(event, draft_log, captured_at="2026-07-25T01:16:02.000Z")
    assert result is not None
    return result.state, draft_log


def _through_pick(events: list[DraftEvent], overall: int) -> list[DraftEvent]:
    """The prefix of the stream ending with the FRAME that reported ``overall``.

    Dropping only the later ``pick_made`` events would leave the trailing ticker
    ``draft_state`` frames in place, and those carry ``current_overall_pick`` — the state
    would report the draft sitting on pick 169 with 24 picks folded. Truncating the whole
    stream keeps the clock and the board consistent, the way a mid-draft join really looks.
    """
    prefix: list[DraftEvent] = []
    seen_target = False
    for event in events:
        if seen_target and event.event_type == "pick_made":
            break  # the next frame's first pick — stop before it
        prefix.append(event)
        if event.event_type == "pick_made" and (event.pick_number or 0) >= overall:
            seen_target = True
    return prefix


def _resolver(replay_players: dict[str, dict]):
    """The crosswalk lookup, as an injected pure function (no network, no sqlite)."""
    return lambda cbs_id: (replay_players.get(cbs_id) or {}).get("canonical_id")


@pytest.fixture(scope="module")
def folded_full(replay_events, tmp_path_factory):
    """Ingest the WHOLE capture once (fsync-per-event is slow; share it across tests)."""
    db = tmp_path_factory.mktemp("replay-full") / "replay.sqlite"
    return _ingest_all(replay_events, db)


@pytest.fixture(scope="module")
def folded_midbraft(replay_events, tmp_path_factory):
    """Ingest through the end of round 2 (pick 24) — a realistic on-the-clock moment."""
    db = tmp_path_factory.mktemp("replay-mid") / "replay.sqlite"
    return _ingest_all(_through_pick(replay_events, 24), db)


class TestTheRealCaptureFoldsToTheRealBoard:
    def test_every_pick_of_the_draft_survives_ingest(self, folded_full) -> None:
        state, _log = folded_full
        # 12 x 14 = 168. A ticker draft_state wiping folded picks (the PR #28 bug) would
        # show up here as a collapse toward zero, on real frames rather than a synthetic pair.
        assert [p.overall for p in state.picks] == list(range(1, TEAMS * CAPTURE_ROUNDS + 1))

    def test_the_draft_is_marked_complete_without_a_phantom_169th_pick(self, folded_full) -> None:
        state, _log = folded_full
        assert state.complete is True
        assert max(p.overall for p in state.picks) == TEAMS * CAPTURE_ROUNDS

    def test_picks_arrive_id_only_and_need_the_crosswalk(self, folded_full) -> None:
        state, _log = folded_full
        # Before resolution every pick is a raw CBS source id — never a canonical one.
        assert all(p.player_id and p.player_id.startswith("cbs:") for p in state.picks)

    def test_truncating_mid_draft_leaves_the_clock_and_the_board_agreeing(
        self, folded_midbraft
    ) -> None:
        state, _log = folded_midbraft
        assert [p.overall for p in state.picks] == list(range(1, 25))
        # The trailing ticker of pick 24's own frame puts pick 25 on the clock.
        assert state.current_overall_pick == 25


# The owner's own team slot in the capture: outbound pick/request frames carry
# teamid "1" (that frame IS this client asking to draft). CBS never puts the viewer's own
# team on an inbound frame, which is exactly the gap TestTheSurvivalModelNeedsMySlot pins.
MY_TEAM_ID = "1"


def _resolved(folded, replay_players, *, my_team_id: str | None = MY_TEAM_ID):
    state, log = folded
    resolved = resolve_pick_ids(
        state,
        log.events(state.league_id),
        resolver=lambda *a: None,
        cbs_resolver=_resolver(replay_players),
    )
    # In production this is applied by the API layer from ?team_id= (jaaffl.api.app). The
    # folded state cannot carry it: no CBS frame names the viewer's own team.
    return resolved.model_copy(update={"my_team_id": my_team_id})


class TestResolutionAgainstTheRealCrosswalk:
    def test_most_real_picks_resolve_to_canonical_ids(self, folded_full, replay_players) -> None:
        resolved = _resolved(folded_full, replay_players)
        canonical = [p for p in resolved.picks if not (p.player_id or "").startswith("cbs:")]
        # Tier 1's bug was 0/179. Anything near zero here means the crosswalk is dead again.
        assert len(canonical) >= 140

    def test_an_unlinked_id_degrades_honestly_instead_of_guessing(
        self, folded_full, replay_players
    ) -> None:
        resolved = _resolved(folded_full, replay_players)
        unresolved = [p for p in resolved.picks if (p.player_id or "").startswith("cbs:")]
        # The known gap is K/DST (nflverse labels kickers PK; DSTs are "<City> Defense").
        # They must keep their cbs: id — never be dropped, never be guessed onto a wrong player.
        assert unresolved, "expected the known K/DST crosswalk gap to still be visible"
        assert len(unresolved) + len(
            [p for p in resolved.picks if not (p.player_id or "").startswith("cbs:")]
        ) == len(resolved.picks)


def _board(replay_events, replay_players, league_id: str):
    """A candidate pool of the REAL players in the capture, keyed by their canonical ids.

    mu/adp are a monotone stand-in over OBSERVED draft position (earlier pick -> higher
    value), not real projections: a committed projection snapshot would drift, and real
    mu/sigma have their own tests. What this board exists to prove is that a real CBS id
    reaches the engine's canonical id space at all — the thing that silently failed in Tier 1.
    """
    order = {
        e.data["player_id"]: e.pick_number for e in replay_events if e.event_type == "pick_made"
    }
    specs = []
    for cbs_id, info in replay_players.items():
        observed = order.get(f"cbs:{cbs_id}")
        if observed is None or info["position"] not in Position.__members__:
            continue
        specs.append(
            {
                "pid": info["canonical_id"],
                "pos": Position[info["position"]],
                "mu": float(300 - observed),
                "sigma": 40.0,
                "adp": float(observed),
                "ecr": float(observed),
            }
        )
    settings = jaaffl_settings(
        league_id=league_id, draft_order=[str(i) for i in range(1, TEAMS + 1)]
    )
    return make_context(specs, params=engine_params(candidate_cap=200), settings=settings)


class TestTheRenderedRecommendation:
    """The far end of the pipe: what the owner would actually be shown."""

    def test_a_named_drafted_player_is_masked_from_the_board(
        self, folded_midbraft, replay_events, replay_players
    ) -> None:
        resolved = _resolved(folded_midbraft, replay_players)
        ctx = _board(replay_events, replay_players, resolved.league_id)
        rec = recommend(resolved, ctx, ctx.params)
        ranked = {p.player_id for p in rec.ranked}

        # Name the players, so a failure says WHO leaked back onto the board.
        by_canonical = {v["canonical_id"]: v["name"] for v in replay_players.values()}
        still_offered = [
            by_canonical.get(p.player_id, p.player_id)
            for p in resolved.picks
            if p.player_id and not p.player_id.startswith("cbs:") and p.player_id in ranked
        ]
        assert still_offered == [], f"drafted players still recommended: {still_offered}"

        # And prove the assertion above is not vacuous: real, NAMED players were in fact
        # drafted in these frames and are known to the board.
        drafted_named = [
            by_canonical[p.player_id]
            for p in resolved.picks
            if p.player_id in by_canonical and p.player_id in ctx.mu
        ]
        assert len(drafted_named) >= 20, f"only {len(drafted_named)} named picks reached the board"
        assert rec.ranked, "no candidates ranked at all"

    def test_the_recommendation_carries_a_real_non_zero_vona(
        self, folded_midbraft, replay_events, replay_players
    ) -> None:
        resolved = _resolved(folded_midbraft, replay_players)
        ctx = _board(replay_events, replay_players, resolved.league_id)
        rec = recommend(resolved, ctx, ctx.params)

        assert rec.best is not None
        vonas = [p.components.vona for p in rec.ranked]
        # THE Tier-1 regression: 200 OK, full decomposition, vona 0.00 on every row.
        assert any(abs(v) > 0.0 for v in vonas), f"every vona is zero: {vonas[:5]}"
        assert abs(rec.best.components.vona) > 0.0, "the BEST pick's vona is zero"

    def test_the_survival_model_actually_conditions_on_the_board(
        self, folded_midbraft, replay_events, replay_players
    ) -> None:
        """Non-zero VONA must come from a real survival computation, not from noise.

        With my slot known, the players most likely to be gone by my next pick should carry
        the most urgency — so at least some picks must show a STRICTLY positive vona.
        """
        resolved = _resolved(folded_midbraft, replay_players)
        ctx = _board(replay_events, replay_players, resolved.league_id)
        rec = recommend(resolved, ctx, ctx.params)
        positive = [p for p in rec.ranked if p.components.vona > 0.0]
        assert positive, "no pick shows positive VONA — the survival model is inert"
        # E[best available next] must differ from this pick's own MLV for at least some picks;
        # equality everywhere is the signature of "everyone survives with probability 1".
        assert any(
            abs(p.components.mlv - (p.components.best_available_next or 0.0)) > 1e-9
            for p in rec.ranked
        )

    def test_without_my_slot_vona_collapses_and_that_is_load_bearing(
        self, folded_midbraft, replay_events, replay_players
    ) -> None:
        """DRAFT-NIGHT GAP, pinned deliberately.

        No CBS frame names the viewer's own team, so ``parse.ts`` cannot emit ``my_team_id``
        and the folded state never has one. ``_my_overall_picks`` then raises, survival
        degrades to "everyone available" (a documented fallback), and the BEST pick's VONA
        goes to exactly 0 — a number that reads like a computed result but is not one.

        ``GET /recommendation?team_id=`` supplies it; the ``/recs/ws`` push path that feeds
        the overlay does NOT. This test exists so that gap is visible rather than inferred.
        """
        resolved = _resolved(folded_midbraft, replay_players, my_team_id=None)
        ctx = _board(replay_events, replay_players, resolved.league_id)
        rec = recommend(resolved, ctx, ctx.params)
        assert rec.best is not None
        assert rec.best.components.vona == 0.0
        assert rec.best.components.best_available_next == pytest.approx(rec.best.components.mlv)

    def test_the_best_pick_reconciles_to_the_sum_of_its_terms(
        self, folded_midbraft, replay_events, replay_players
    ) -> None:
        """§6.5's anti-black-box guarantee, checked on real-capture-derived state."""
        resolved = _resolved(folded_midbraft, replay_players)
        ctx = _board(replay_events, replay_players, resolved.league_id)
        best = recommend(resolved, ctx, ctx.params).best
        assert best is not None
        c = best.components
        expected = (
            c.mlv
            + ctx.params.kappa * max(0.0, c.vona)
            - c.risk_penalty
            + c.cliff_bonus
            + sum(c.modifiers.values())
        )
        assert best.score == pytest.approx(expected, abs=1e-6)
