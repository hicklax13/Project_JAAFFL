"""Append-only draft-event log + crash-safe fold (plan §2.3/§2.6).

The log is the only unrebuildable data in the system: append is durable (WAL +
synchronous=FULL, committed before return) and de-duped at the storage layer; fold_state
is a pure deterministic left-fold, so identical logs yield identical DraftState anywhere.
"""

from pathlib import Path

import pytest

from jaaffl.domain import DraftEvent
from jaaffl.ingest.log import LoggedEvent, append_event, fold_state, open_log, read_events


def pick_event(overall: int, team: str = "T1", player: str | None = None) -> DraftEvent:
    data = {
        "overall": overall,
        "round": (overall - 1) // 12 + 1,
        "pick_in_round": (overall - 1) % 12 + 1,
        "team_id": team,
    }
    if player:
        data["player_id"] = player
    return DraftEvent(
        event_type="pick_made", league_id="L1", pick_number=overall, source="ws", data=data
    )


def append(conn, event: DraftEvent, *, source: str | None = "ws") -> int | None:
    return append_event(
        conn,
        event,
        pick_number=event.pick_number,
        source=source,
        captured_at="2026-08-30T18:00:00Z",
    )


@pytest.fixture
def conn(tmp_path: Path):
    connection = open_log(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def test_append_returns_monotonic_seq(conn) -> None:
    seqs = [append(conn, pick_event(n)) for n in (1, 2, 3)]
    assert seqs == sorted(seqs)
    assert all(isinstance(s, int) for s in seqs)


def test_duplicate_pick_is_deduped_at_storage(conn) -> None:
    """Cross-probe de-dup: first write wins; later probes' duplicates return None."""
    assert append(conn, pick_event(5), source="ws") is not None
    assert append(conn, pick_event(5), source="dom") is None
    events = read_events(conn, "L1")
    assert len(events) == 1
    assert events[0].source == "ws"  # provenance of the winning probe


def test_non_pick_events_are_never_deduped(conn) -> None:
    settings = DraftEvent(event_type="league_settings", league_id="L1", data={})
    assert append(conn, settings, source=None) is not None
    assert append(conn, settings, source=None) is not None  # each snapshot is legitimate
    assert len(read_events(conn, "L1")) == 2


def test_read_events_is_league_scoped_and_seq_ordered(conn) -> None:
    append(conn, pick_event(1))
    other = DraftEvent(
        event_type="pick_made",
        league_id="L2",
        pick_number=1,
        data={"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "X1"},
    )
    append(conn, other)
    append(conn, pick_event(2))
    events = read_events(conn, "L1")
    assert [e.pick_number for e in events] == [1, 2]
    assert all(e.league_id == "L1" for e in events)


def test_replay_survives_process_restart(tmp_path: Path) -> None:
    """Crash-safety core: a NEW connection (simulating a restarted process) folds the log
    to the exact pre-crash DraftState."""
    db = tmp_path / "app.sqlite"
    conn1 = open_log(db)
    for n in (1, 2, 3):
        append(conn1, pick_event(n, team=f"T{n}"))
    before = fold_state(read_events(conn1, "L1"))
    conn1.close()  # process dies

    conn2 = open_log(db)  # restart
    after = fold_state(read_events(conn2, "L1"))
    conn2.close()
    assert after == before
    assert after.current_overall_pick == 4
    assert [p.overall for p in after.picks] == [1, 2, 3]


def logged(event_type: str, data: dict, *, seq: int, pick: int | None = None) -> LoggedEvent:
    return LoggedEvent(
        seq=seq,
        league_id="L1",
        event_type=event_type,
        pick_number=pick,
        data=data,
        source="ws",
        captured_at="2026-08-30T18:00:00Z",
    )


def test_fold_is_deterministic_and_pure() -> None:
    events = [
        logged("league_settings", {"my_team_id": "T7"}, seq=1),
        logged("on_the_clock", {"current_overall_pick": 1, "team_id": "T1"}, seq=2, pick=1),
        logged(
            "pick_made",
            {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1", "player_id": "cbs:100"},
            seq=3,
            pick=1,
        ),
    ]
    assert fold_state(events) == fold_state(events)


def test_fold_reducer_semantics() -> None:
    events = [
        logged("league_settings", {"my_team_id": "T7"}, seq=1),
        logged("on_the_clock", {"current_overall_pick": 1, "team_id": "T1"}, seq=2, pick=1),
        logged(
            "pick_made",
            {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1", "player_id": "cbs:100"},
            seq=3,
            pick=1,
        ),
        logged("on_the_clock", {"current_overall_pick": 2, "team_id": "T2"}, seq=4, pick=2),
    ]
    state = fold_state(events)
    assert state.league_id == "L1"
    assert state.my_team_id == "T7"
    assert state.on_the_clock_team_id == "T2"
    assert state.current_overall_pick == 2
    assert [p.overall for p in state.picks] == [1]
    assert state.complete is False


def test_fold_pick_made_is_idempotent_per_overall() -> None:
    pick = {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1", "player_id": "cbs:1"}
    events = [
        logged("pick_made", pick, seq=1, pick=1),
        logged("pick_made", pick, seq=2, pick=1),  # slower probe replays the same pick
    ]
    state = fold_state(events)
    assert len(state.picks) == 1
    assert state.current_overall_pick == 2


def test_fold_pick_made_removes_player_from_available() -> None:
    events = [
        logged(
            "draft_state",
            {
                "league_id": "L1",
                "current_overall_pick": 1,
                "available_player_ids": ["cbs:1", "cbs:2"],
            },
            seq=1,
        ),
        logged(
            "pick_made",
            {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1", "player_id": "cbs:1"},
            seq=2,
            pick=1,
        ),
    ]
    state = fold_state(events)
    assert state.available_player_ids == ["cbs:2"]


def test_fold_draft_state_ticker_does_not_wipe_previously_folded_picks() -> None:
    """REGRESSION, real-capture verified (docs/research/cbs-draft-protocol.md): the REAL CBS
    protocol's ``draft_state`` event (``parse.ts::cbsDraftStateEvent``) fires on almost every
    frame and carries ONLY current_overall_pick/round/on_the_clock_team_id/on_deck_team_id --
    never ``picks``. These two events are the exact shape of the committed golden fixture
    ``apps/extension/tests/fixtures/cbs/picks-completed.autopick.json``, whose parsed values are
    pinned by apps/extension/tests/parse.test.ts ("numbers an autopick 1" / "carries current
    pick / round / on-the-clock ... from an in-progress frame": pick_made overall=1 team_id="1"
    cbs_player_id="3162723", followed by draft_state current_overall_pick=2 on_the_clock="2"
    on_deck="3"). A ticker-only draft_state folded after a pick_made must NOT be treated as a
    resync-to-empty: replaying a full real draft (165 real picks, 75 real draft_state ticks)
    through the pre-fix reducer folded ``state.picks`` to ZERO -- the engine's drafted-player
    mask (jaaffl.engine.recommend) depends entirely on ``state.picks`` surviving this."""
    events = [
        logged(
            "pick_made",
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": "1",
                "player_id": "cbs:3162723",
            },
            seq=1,
            pick=1,
        ),
        logged(
            "draft_state",
            {
                "league_id": "L1",
                "current_overall_pick": 2,
                "round": 1,
                "on_the_clock_team_id": "2",
                "on_deck_team_id": "3",
            },
            seq=2,
        ),
    ]
    state = fold_state(events)
    assert [p.overall for p in state.picks] == [1]
    assert state.picks[0].player_id == "cbs:3162723"
    assert state.current_overall_pick == 2
    assert state.on_the_clock_team_id == "2"


def test_fold_draft_state_is_authoritative_resync() -> None:
    events = [
        logged("league_settings", {"my_team_id": "T7"}, seq=1),
        logged(
            "pick_made",
            {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T9"},
            seq=2,
            pick=1,
        ),
        # Reconnect: the room re-syncs a full snapshot that supersedes local folding.
        logged(
            "draft_state",
            {
                "league_id": "L1",
                "current_overall_pick": 26,
                "on_the_clock_team_id": "T3",
                "picks": [
                    {
                        "overall": 25,
                        "round": 3,
                        "pick_in_round": 1,
                        "team_id": "T12",
                        "player_id": "cbs:9",
                    }
                ],
            },
            seq=3,
        ),
    ]
    state = fold_state(events)
    assert state.current_overall_pick == 26
    # ⚠️ TIER 12 CONTRACT CHANGE (code review): a resync UNIONS by `overall` rather than replacing.
    # This test asserted `== [25]` — the snapshot wiping the locally folded pick 1 — and that is
    # what the reviewer measured as a live data-loss path: one pick delta winning the race against
    # the connect snapshot made the snapshot look "older" and discarded it, folding 1 pick instead
    # of 99 and leaving snapshot-only picks unmasked (Tier 3's exact defect).
    #
    # A real resync is built from `fullstate.teams` (parse.ts::cbsSnapshotPicks), i.e. the WHOLE
    # board, so on the real path a union and a replacement are identical — they differ only when
    # the snapshot is not a superset, which is exactly the racing case. The residual cost of a
    # union is that a pick the room later RETRACTS would survive locally, masking a player who is
    # really available. Nothing in docs/research/cbs-draft-protocol.md evidences CBS retracting a
    # pick mid-draft, and that cost is one masked player against losing 99 and re-recommending
    # players who are already gone.
    assert [p.overall for p in state.picks] == [1, 25]
    assert state.on_the_clock_team_id == "T3"
    assert state.my_team_id == "T7"  # snapshot without my_team_id must not erase it


def test_fold_draft_complete_marks_terminal() -> None:
    events = [
        logged(
            "pick_made",
            {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1"},
            seq=1,
            pick=1,
        ),
        logged("draft_complete", {}, seq=2),
    ]
    assert fold_state(events).complete is True


def test_fold_empty_log_raises() -> None:
    with pytest.raises(ValueError):
        fold_state([])


def test_fold_never_infers_draft_order() -> None:
    """The immutable contract: order comes only from the room (draft_state/on_the_clock/
    pick payloads). A fold over picks from a NON-snake order must reproduce exactly the
    order observed, never a synthesized 1..12/12..1 pattern."""
    weird_order = ["T5", "T11", "T2"]  # in-person order, not a snake from team count
    events = [
        logged(
            "pick_made", {"overall": n, "round": 1, "pick_in_round": n, "team_id": t}, seq=n, pick=n
        )
        for n, t in enumerate(weird_order, start=1)
    ]
    state = fold_state(events)
    assert [p.team_id for p in state.picks] == weird_order


def test_payload_pick_number_mismatch_never_stored(conn) -> None:
    """A pick_made whose envelope pick_number disagrees with data.overall is corrupt —
    append_event must refuse it (fail loud, §2.3 payload validity)."""
    bad = DraftEvent(
        event_type="pick_made",
        league_id="L1",
        pick_number=7,
        source="ws",
        data={"overall": 8, "round": 1, "pick_in_round": 8, "team_id": "T8"},
    )
    with pytest.raises(ValueError):
        append_event(
            conn, bad, pick_number=bad.pick_number, source="ws", captured_at="2026-08-30T18:00:00Z"
        )
    assert read_events(conn, "L1") == []


ROOM_ORDER = [str(i) for i in range(1, 13)]


def test_fold_binds_the_order_the_room_reported() -> None:
    """parse.ts emits league_settings{draft_order} from fullstatedelta.order (Tier 3's capture
    decode). The fold read only my_team_id off that event, so the order was decoded and then
    thrown away — and resolve_league_settings returns None by construction, so the engine could
    never compute a survival model on the live path."""
    events = [
        logged(
            "league_settings",
            {"league_id": "L1", "team_count": 12, "draft_order": ROOM_ORDER},
            seq=1,
        )
    ]
    assert fold_state(events).draft_order == ROOM_ORDER


def test_fold_refuses_an_order_that_disagrees_with_team_count() -> None:
    """opponents._my_overall_picks uses len(draft_order) AS the team count, so an 11-entry order
    silently corrupts every 'my next pick' for the rest of the draft. config/league.json is
    immutable and fixes teams=12: surface the conflict, never adopt it."""
    events = [
        logged(
            "league_settings",
            {"league_id": "L1", "team_count": 12, "draft_order": ROOM_ORDER[:11]},
            seq=1,
        )
    ]
    assert fold_state(events).draft_order is None


def test_fold_still_never_synthesizes_an_order() -> None:
    """A settings event with a team_count and no order must not mint one."""
    events = [logged("league_settings", {"league_id": "L1", "team_count": 12}, seq=1)]
    assert fold_state(events).draft_order is None


def test_a_later_settings_event_does_not_erase_a_known_order() -> None:
    """CBS attaches fullstatedelta to picks/completed frames, so the settings event repeats all
    draft long — and the extension de-dups a non-pick event by its whole data blob, so a variant
    without the order does reach the fold."""
    events = [
        logged(
            "league_settings",
            {"league_id": "L1", "team_count": 12, "draft_order": ROOM_ORDER},
            seq=1,
        ),
        logged("league_settings", {"league_id": "L1", "my_team_id": "7"}, seq=2),
    ]
    folded = fold_state(events)
    assert folded.draft_order == ROOM_ORDER
    assert folded.my_team_id == "7"


def test_a_non_numeric_team_count_cannot_brick_the_fold() -> None:
    """⚠️ Found in code review. fold_state was a TOTAL function; Tier 12's length guard made it
    raise on a non-numeric team_count. /draft/events accepts an arbitrary data dict and appends it
    DURABLY, and fold_state is on the hot path of /draft/events, /recommendation, /state AND
    /analytics — so one malformed event would have taken the league down for the rest of the
    draft, on every request, unrecoverably. A new draft-night failure mode where none existed."""
    for bad in ("twelve", [12], {"n": 12}, None):
        events = [
            logged(
                "league_settings",
                {"league_id": "L1", "team_count": bad, "draft_order": ROOM_ORDER},
                seq=1,
            )
        ]
        state = fold_state(events)  # must not raise
        assert state.draft_order == ROOM_ORDER, f"team_count={bad!r} lost the order"
