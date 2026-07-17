"""resolve_pick_ids: fill canonical player_ids for name-only (manual-paste) picks."""

from __future__ import annotations

import pytest

from jaaffl.domain import DraftPick, DraftState
from jaaffl.ingest.log import LoggedEvent
from jaaffl.ingest.resolve import resolve_pick_ids


def _pick_event(overall: int, team_id: str, **data) -> LoggedEvent:
    return LoggedEvent(
        seq=overall,
        league_id="L",
        event_type="pick_made",
        pick_number=overall,
        data={"overall": overall, "round": 1, "pick_in_round": overall, "team_id": team_id, **data},
        source="paste",
        captured_at="t",
    )


def _state(picks: list[DraftPick]) -> DraftState:
    return DraftState(
        league_id="L", current_overall_pick=len(picks) + 1, my_team_id="t0", picks=picks
    )


def test_resolves_name_only_pick_to_canonical() -> None:
    events = [
        _pick_event(1, "t1", player_name="Christian McCaffrey", position="RB", player_team="SF")
    ]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])

    def resolver(name, team, pos):
        return "gsis:cmc" if (name, team, pos) == ("Christian McCaffrey", "SF", "RB") else None

    out = resolve_pick_ids(state, events, resolver)
    assert out.picks[0].player_id == "gsis:cmc"


def test_leaves_already_resolved_picks_untouched() -> None:
    events = [_pick_event(1, "t1", player_name="X", position="RB", player_team="SF")]
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:9")]
    )
    calls: list = []

    def resolver(*a):
        calls.append(a)
        return "gsis:nope"

    out = resolve_pick_ids(state, events, resolver)
    assert out.picks[0].player_id == "cbs:9"
    assert calls == []  # resolver never consulted for a pick that already carries an id
    assert out is state  # nothing changed -> same object


def test_unresolved_name_stays_none() -> None:
    events = [_pick_event(1, "t1", player_name="Ghost", position="RB", player_team="ZZ")]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])
    out = resolve_pick_ids(state, events, lambda *a: None)
    assert out.picks[0].player_id is None


def test_maps_source_position_codes() -> None:
    events = [
        _pick_event(1, "t1", player_name="San Francisco", position="DEF", player_team="SF"),
        _pick_event(2, "t2", player_name="Some Kicker", position="PK", player_team="SF"),
    ]
    state = _state(
        [
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t2"),
        ]
    )
    seen: dict[str, str] = {}

    def resolver(name, team, pos):
        seen[name] = pos
        return None

    resolve_pick_ids(state, events, resolver)
    assert seen == {"San Francisco": "DST", "Some Kicker": "K"}


def test_name_only_pick_without_name_in_events_is_skipped() -> None:
    events = [_pick_event(1, "t1")]  # pick_made with no player_name
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])
    out = resolve_pick_ids(state, events, lambda *a: pytest.fail("resolver must not be called"))
    assert out.picks[0].player_id is None
