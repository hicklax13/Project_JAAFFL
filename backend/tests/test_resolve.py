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


def test_leaves_canonical_id_picks_untouched() -> None:
    """A pick that already carries a CANONICAL id (gsis:, never cbs:) is never re-resolved by
    either the name resolver or the cbs resolver -- the double-resolution guard."""
    events = [_pick_event(1, "t1", player_name="X", position="RB", player_team="SF")]
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="gsis:9")]
    )
    calls: list = []

    def resolver(*a):
        calls.append(a)
        return "gsis:nope"

    out = resolve_pick_ids(state, events, resolver, lambda cbs_id: "gsis:nope")
    assert out.picks[0].player_id == "gsis:9"
    assert calls == []  # resolver never consulted for a pick that already carries a canonical id
    assert out is state  # nothing changed -> same object


# --- cbs: id resolution (real capture path -- protocol §3, picks are ID-only) ---------


def test_resolves_cbs_id_pick_via_cbs_resolver() -> None:
    """parse.ts emits player_id='cbs:<id>' for a live CBS pick. A cbs: id is NOT canonical (it
    is a raw source id, same as a name-only pick is unresolved) so it must go through the
    injected cbs_resolver, keyed on the crosswalk's ('cbs', source_id)."""
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:3162723")]
    )
    seen: list[str] = []

    def cbs_resolver(cbs_id: str) -> str | None:
        seen.append(cbs_id)
        return "gsis:gibbs" if cbs_id == "3162723" else None

    out = resolve_pick_ids(state, [], lambda *a: None, cbs_resolver)
    assert out.picks[0].player_id == "gsis:gibbs"
    assert seen == ["3162723"]  # the "cbs:" prefix is stripped before the lookup


def test_cbs_id_pick_degrades_honestly_when_unresolved() -> None:
    """No crosswalk link yet for this CBS id: stays unresolved (never guessed) and the pick is
    NOT dropped from state -- exactly the honesty contract the name-only miss path already has."""
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:999999")]
    )
    out = resolve_pick_ids(state, [], lambda *a: None, lambda cbs_id: None)
    assert len(out.picks) == 1  # never dropped
    assert out.picks[0].player_id == "cbs:999999"  # left as-is: not nulled, not guessed


def test_cbs_id_pick_without_injected_resolver_stays_unresolved() -> None:
    """cbs_resolver is optional (default None) so every existing name-only call site in this
    file (and any other caller that predates this feature) keeps compiling and behaving as
    before -- omitting it just means no cbs: id can resolve on that call."""
    state = _state(
        [DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:42")]
    )
    out = resolve_pick_ids(state, [], lambda *a: None)  # no cbs_resolver passed
    assert out.picks[0].player_id == "cbs:42"


def test_cbs_and_name_misses_both_surfaced_in_unresolved_overalls() -> None:
    """A cbs: miss must show up in unresolved_overalls exactly like a name-only miss does. A cbs:
    id stays non-None on a miss, so 'unresolved' can no longer be read off `player_id is None`."""
    from structlog.testing import capture_logs

    events = [_pick_event(1, "t1", player_name="Ghost", position="RB", player_team="ZZ")]
    state = _state(
        [
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t2", player_id="cbs:7"),
        ]
    )
    with capture_logs() as logs:
        out = resolve_pick_ids(state, events, lambda *a: None, lambda cbs_id: None)
    assert [p.player_id for p in out.picks] == [None, "cbs:7"]
    warns = [e for e in logs if e["event"] == "drafted_pick_name_resolution_incomplete"]
    assert len(warns) == 1
    assert warns[0]["unresolved"] == 2
    assert warns[0]["unresolved_overalls"] == [1, 2]


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


def test_mixed_batch_preserves_order_and_only_fills_unresolved() -> None:
    """A realistic mid-draft state: one resolvable name-only pick, one unresolvable, one already
    canonical. Each is preserved in order; the already-canonical pick's resolver is never
    consulted (see the dedicated cbs: tests above for the cbs: miss/hit/no-resolver cases)."""
    events = [
        _pick_event(1, "t1", player_name="Resolvable", position="RB", player_team="SF"),
        _pick_event(2, "t2", player_name="Ghost", position="WR", player_team="ZZ"),
        _pick_event(3, "t3", player_name="Ignored", position="RB", player_team="SF"),
    ]
    state = _state(
        [
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t2"),
            DraftPick(overall=3, round=1, pick_in_round=3, team_id="t3", player_id="gsis:9"),
        ]
    )
    seen: list[str] = []

    def resolver(name, team, pos):
        seen.append(name)
        return "gsis:r" if name == "Resolvable" else None

    out = resolve_pick_ids(state, events, resolver)
    assert [p.player_id for p in out.picks] == ["gsis:r", None, "gsis:9"]
    assert "Ignored" not in seen  # already-canonical pick never consulted


def test_uses_nfl_team_key_when_player_team_absent() -> None:
    events = [_pick_event(1, "t1", player_name="Someone", position="RB", nfl_team="SF")]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])
    seen: dict[str, str | None] = {}

    def resolver(name, team, pos):
        seen["team"] = team
        return None

    resolve_pick_ids(state, events, resolver)
    assert seen["team"] == "SF"


def test_unresolved_picks_are_surfaced_at_warning_with_overalls() -> None:
    """The honesty backstop: an unresolved drafted pick (a player that will reappear on the board)
    is logged at WARNING with the offending overalls — never a silent swallow."""
    from structlog.testing import capture_logs

    events = [
        _pick_event(1, "t1", player_name="Found", position="RB", player_team="SF"),
        _pick_event(2, "t2", player_name="Ghost", position="RB", player_team="ZZ"),
    ]
    state = _state(
        [
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t2"),
        ]
    )

    def resolver(name, team, pos):
        return "gsis:found" if name == "Found" else None

    with capture_logs() as logs:
        resolve_pick_ids(state, events, resolver)
    warns = [e for e in logs if e["event"] == "drafted_pick_name_resolution_incomplete"]
    assert len(warns) == 1
    assert warns[0]["log_level"] == "warning"
    assert (warns[0]["resolved"], warns[0]["unresolved"]) == (1, 1)
    assert warns[0]["unresolved_overalls"] == [2]
