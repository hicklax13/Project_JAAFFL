"""TIER 3 / TASK 3 — does the draft-day fallback give the same advice as the live path?

Plan §5.11 **A7** says manual-paste events must be "byte-identical to live capture". That
criterion was written against the SYNTHETIC parse.ts vocabulary, where a pick carried its own
name/position/team. The real decoded protocol does not:

    live   ->  {"player_id": "cbs:3162723", "cbs_player_id": "3162723"}      ID-only
    paste  ->  {"player_name": "...", "position": "...", "player_team": "..."}  NAME-only

The identity fields are DISJOINT, so byte-identity is unachievable — and manufacturing it would
mean inventing a CBS id for a pasted name, precisely the guess ``resolve_pick_ids`` refuses to
make. Surfaced, not silently reconciled (config/league.json ``agent_usage_contract``).

A7's real intent — the fallback must not change the advice — is testable at the point the two
paths genuinely converge: AFTER id resolution. Both become canonical ids on a folded
``DraftState``, and from there the engine cannot tell them apart. That is what this pins, on the
first two rounds of a real captured draft.
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
CBS = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs"
PLAYERS = Path(__file__).resolve().parent / "fixtures" / "cbs_replay_players.json"

TEAMS = 12
PASTED_PICKS = 24  # the manual-paste fixture covers the first two rounds
MY_TEAM_ID = "1"


def _events(name: str) -> list[DraftEvent]:
    return [
        DraftEvent.model_validate(e) for e in json.loads((CBS / name).read_text(encoding="utf-8"))
    ]


@pytest.fixture(scope="module")
def players() -> dict[str, dict]:
    return json.loads(PLAYERS.read_text(encoding="utf-8"))["players"]


def _fold(events: list[DraftEvent], db_path: Path):
    draft_log = DraftLog(db_path)
    result = None
    for event in events:
        result = handle_event(event, draft_log, captured_at="2026-07-25T01:16:02.000Z")
    assert result is not None
    return result.state, draft_log


def _name_resolver(players: dict[str, dict]):
    """(name, nfl_team, position) -> canonical id, backed by the same crosswalk slice the
    live path uses — so any difference in outcome is about the PATH, not about the data."""
    index = {
        (info["name"].casefold(), info["position"]): info["canonical_id"]
        for info in players.values()
    }
    return lambda name, team, pos: index.get((name.casefold(), pos))


def _cbs_resolver(players: dict[str, dict]):
    return lambda cbs_id: (players.get(cbs_id) or {}).get("canonical_id")


def _through_pick(events: list[DraftEvent], overall: int) -> list[DraftEvent]:
    """The prefix ending with the FRAME that reported ``overall``.

    Filtering out only the later ``pick_made`` events would leave every trailing ticker
    ``draft_state`` in place — and those carry ``current_overall_pick``, so the state would
    end up on pick 169 (draft over) with 24 picks folded, while the paste path sits on 25.
    The engine would then be asked about two different rounds and the comparison would be
    meaningless.
    """
    prefix: list[DraftEvent] = []
    seen_target = False
    for event in events:
        if seen_target and event.event_type == "pick_made":
            break
        prefix.append(event)
        if event.event_type == "pick_made" and (event.pick_number or 0) >= overall:
            seen_target = True
    return prefix


@pytest.fixture(scope="module")
def live_state(players, tmp_path_factory):
    """The live path: real frames, ID-only picks, resolved through the cbs crosswalk."""
    events = _through_pick(_events("full-draft.events.json"), PASTED_PICKS)
    state, log = _fold(events, tmp_path_factory.mktemp("live") / "draft.sqlite")
    resolved = resolve_pick_ids(
        state,
        log.events(state.league_id),
        resolver=lambda *a: None,
        cbs_resolver=_cbs_resolver(players),
    )
    return resolved.model_copy(update={"my_team_id": MY_TEAM_ID})


@pytest.fixture(scope="module")
def paste_state(players, tmp_path_factory):
    """The fallback path: the same 24 picks typed as names, resolved by name."""
    events = _events("manual-paste.events.json")
    state, log = _fold(events, tmp_path_factory.mktemp("paste") / "draft.sqlite")
    resolved = resolve_pick_ids(
        state,
        log.events(state.league_id),
        resolver=_name_resolver(players),
        cbs_resolver=None,  # a pasted pick has no CBS id to resolve
    )
    return resolved.model_copy(update={"my_team_id": MY_TEAM_ID})


class TestTheTwoPathsDisagreeOnBytesAndAgreeOnMeaning:
    def test_the_raw_events_are_not_byte_identical_and_cannot_be(self) -> None:
        live = next(e for e in _events("full-draft.events.json") if e.event_type == "pick_made")
        paste = next(e for e in _events("manual-paste.events.json") if e.event_type == "pick_made")
        assert live.data != paste.data  # A7 as literally written does not hold
        assert "player_id" in live.data and "player_id" not in paste.data
        assert "player_name" in paste.data and "player_name" not in live.data

    def test_both_paths_resolve_the_same_24_picks_to_the_same_players(
        self, live_state, paste_state
    ) -> None:
        live_board = {p.overall: p.player_id for p in live_state.picks}
        paste_board = {p.overall: p.player_id for p in paste_state.picks}
        assert sorted(live_board) == list(range(1, PASTED_PICKS + 1))
        assert live_board == paste_board

    def test_both_paths_agree_on_which_team_made_each_pick(self, live_state, paste_state) -> None:
        assert {p.overall: p.team_id for p in live_state.picks} == {
            p.overall: p.team_id for p in paste_state.picks
        }

    def test_both_paths_leave_the_clock_on_the_same_pick(self, live_state, paste_state) -> None:
        # The precondition for comparing recommendations at all. Asserted explicitly so a
        # future desync fails HERE, naming the cause, instead of surfacing as an unexplained
        # score difference three tests later (which is exactly how it first showed up).
        assert live_state.current_overall_pick == paste_state.current_overall_pick == 25
        assert live_state.complete is False and paste_state.complete is False

    def test_neither_path_leaves_a_pick_unresolved(self, live_state, paste_state) -> None:
        # If either side silently failed to resolve, the boards could still "match" as two
        # equally broken sets. Assert both are genuinely canonical.
        for state in (live_state, paste_state):
            unresolved = [p for p in state.picks if not p.player_id or ":" not in p.player_id]
            assert unresolved == []
            assert all(not p.player_id.startswith("cbs:") for p in state.picks)


def _board(players: dict[str, dict], league_id: str):
    """Identical candidate pool for both paths — see test_cbs_replay for the mu/adp caveat."""
    events = _events("full-draft.events.json")
    order = {e.data["cbs_player_id"]: e.pick_number for e in events if e.event_type == "pick_made"}
    specs = [
        {
            "pid": info["canonical_id"],
            "pos": Position[info["position"]],
            "mu": float(300 - order[cbs_id]),
            "sigma": 40.0,
            "adp": float(order[cbs_id]),
            "ecr": float(order[cbs_id]),
        }
        for cbs_id, info in players.items()
        if cbs_id in order and info["position"] in Position.__members__
    ]
    settings = jaaffl_settings(
        league_id=league_id, draft_order=[str(i) for i in range(1, TEAMS + 1)]
    )
    return make_context(specs, params=engine_params(candidate_cap=200), settings=settings)


class TestTheRecommendationIsTheSame:
    """A7's actual promise: falling back to paste must not change the advice."""

    @staticmethod
    def _rec(state, players):
        ctx = _board(players, state.league_id)
        return recommend(state, ctx, ctx.params)

    def test_the_best_pick_is_the_same_player(self, live_state, paste_state, players) -> None:
        live = self._rec(live_state, players)
        paste = self._rec(paste_state, players)
        assert live.best is not None and paste.best is not None
        assert live.best.player_id == paste.best.player_id

    def test_the_whole_ranked_list_is_the_same(self, live_state, paste_state, players) -> None:
        live = self._rec(live_state, players)
        paste = self._rec(paste_state, players)
        assert [p.player_id for p in live.ranked] == [p.player_id for p in paste.ranked]

    def test_the_decomposition_matches_term_for_term(
        self, live_state, paste_state, players
    ) -> None:
        live = self._rec(live_state, players).best
        paste = self._rec(paste_state, players).best
        assert live is not None and paste is not None
        assert live.score == pytest.approx(paste.score)
        for term in ("mlv", "vona", "risk_penalty", "cliff_bonus", "best_available_next"):
            assert getattr(live.components, term) == pytest.approx(
                getattr(paste.components, term)
            ), f"{term} diverges between the live and paste paths"

    def test_the_vona_is_non_zero_on_both_paths(self, live_state, paste_state, players) -> None:
        # Equality is worthless if both are the degenerate all-zero answer.
        for state in (live_state, paste_state):
            best = self._rec(state, players).best
            assert abs(best.components.vona) > 0.0
