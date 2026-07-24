"""build_board_state: enrich the folded DraftState with drafted-player names for the board.

The dashboard board + pick-log need each pick's display name/position/team. Picks in the folded
DraftState carry only ``player_id`` (a frozen contract), so the names are sourced from the raw
``pick_made`` event payloads (the same place ``resolve_pick_ids`` reads them) — a pure join, no I/O.
"""

from __future__ import annotations

from jaaffl.domain import DraftPick, DraftState
from jaaffl.ingest.board import build_board_state
from jaaffl.ingest.log import LoggedEvent


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


def _state(picks: list[DraftPick], **kw) -> DraftState:
    return DraftState(
        league_id="L", current_overall_pick=len(picks) + 1, my_team_id="t0", picks=picks, **kw
    )


def test_board_pick_carries_name_position_team_from_event() -> None:
    events = [
        _pick_event(1, "t1", player_name="Christian McCaffrey", position="RB", player_team="SF")
    ]
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="gsis:cmc")]
    )

    board = build_board_state(state, events)

    assert len(board.picks) == 1
    pick = board.picks[0]
    assert pick.overall == 1
    assert pick.round == 1
    assert pick.team_id == "t1"
    assert pick.player_id == "gsis:cmc"
    assert pick.name == "Christian McCaffrey"
    assert pick.position == "RB"
    assert pick.nfl_team == "SF"


def test_board_state_preserves_clock_and_identity() -> None:
    events = [_pick_event(1, "t1", player_name="X", position="RB", player_team="SF")]
    state = DraftState(
        league_id="L",
        current_overall_pick=2,
        on_the_clock_team_id="t2",
        my_team_id="t0",
        picks=[DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="gsis:x")],
        complete=False,
    )

    board = build_board_state(state, events)

    assert board.league_id == "L"
    assert board.current_overall_pick == 2
    assert board.on_the_clock_team_id == "t2"
    assert board.my_team_id == "t0"
    assert board.complete is False


def test_board_pick_without_matching_event_has_no_name() -> None:
    # A pick present in state but with no name-bearing event (e.g. a draft_state re-sync snapshot):
    # the id is still shown; name/position/team degrade to None rather than raising.
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:9")]
    )

    board = build_board_state(state, [])

    pick = board.picks[0]
    assert pick.player_id == "cbs:9"
    assert pick.name is None
    assert pick.position is None
    assert pick.nfl_team is None
