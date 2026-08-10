"""TIER 12 — a live room is not an ordered stream, and a mock may not misbehave on cue.

Three things a ticking CBS room does that a clean replay does not: deliver frames out of order
(two content scripts plus a REST mirror all race — see ``lib/transport.ts``, which queues over the
socket AND mirrors over REST), deliver the same pick twice, and resend the whole board after a
reconnect.

Testing those against a live draft means hoping the room misbehaves while the owner watches, once.
Testing them against the Tier-3 capture means they are covered on every CI run. The rehearsal
REPORTS whether disorder occurred; it does not establish that it is handled — this does.

Driven through the SAME real capture the resync tests use: ``late-join.events.json`` is parse.ts's
own output over a real mid-draft join, and it carries 54 ``league_settings`` events bearing the
room's entered order (CBS attaches ``fullstatedelta`` to its ``picks/completed`` frames, so the
settings event repeats all draft long).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from jaaffl.domain import DraftEvent, DraftEventType
from jaaffl.ingest.log import LoggedEvent, fold_state

REPO_ROOT = Path(__file__).resolve().parents[2]
CBS = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs"


def _logged(events: list[DraftEvent]) -> list[LoggedEvent]:
    """The capture as the append-only log would hold it — fold_state's actual input."""
    return [
        LoggedEvent(
            seq=i,
            league_id=event.league_id,
            event_type=event.event_type,
            pick_number=event.pick_number,
            data=event.data,
            source=str(event.source) if event.source else None,
            captured_at="2026-07-25T15:45:18.000Z",
        )
        for i, event in enumerate(events, start=1)
    ]


@pytest.fixture(scope="module")
def capture() -> list[LoggedEvent]:
    raw = json.loads((CBS / "late-join.events.json").read_text(encoding="utf-8"))
    return _logged([DraftEvent.model_validate(e) for e in raw])


def test_the_capture_really_carries_the_rooms_order(capture) -> None:
    """Guards every test below from being vacuous. If a future fixture drops the order-bearing
    league_settings frames, the reconnect test would silently prove nothing."""
    bearing = [
        ev
        for ev in capture
        if ev.event_type == DraftEventType.LEAGUE_SETTINGS and ev.data.get("draft_order")
    ]
    assert len(bearing) > 1, "fixture carries no league_settings order — the tests below are void"


def test_the_pick_SET_is_identical_when_the_DELTAS_race_each_other(capture) -> None:
    """Deltas arriving out of order must not change the SET of picks — ``fold_state`` appends
    idempotently per ``overall``, so this holds for any permutation of them.

    ⚠️ The resync is held in place rather than shuffled, and that is the honest model, not a
    convenience. CBS's ``subscribe/response`` snapshot is BY DEFINITION the first frame of a
    connection; a stream where the only copy of it arrives last cannot happen. Shuffling it there
    measured a 3-pick loss that is purely an artifact of the impossible arrangement (those three
    exist nowhere else in this capture — that is Tier 3's finding). The reachable disorder is a
    DUPLICATE resync arriving late, which has a measured trigger and is pinned below.

    ⚠️ Also deliberately not asserted: ``current_overall_pick``. A ticker ``draft_state`` is
    absolutely authoritative over the clock by design — CBS can pause or rewind a room — so an
    arbitrary last ticker legitimately reports an arbitrary clock, and the next tick corrects it.
    """
    ordered = fold_state(capture)
    head = [
        ev for ev in capture if ev.event_type == DraftEventType.DRAFT_STATE and "picks" in ev.data
    ]
    tail = [
        ev
        for ev in capture
        if not (ev.event_type == DraftEventType.DRAFT_STATE and "picks" in ev.data)
    ]
    random.Random(20260810).shuffle(tail)
    scrambled = fold_state([*head, *tail])
    assert {p.overall for p in scrambled.picks} == {p.overall for p in ordered.picks}


def test_a_duplicated_pick_frame_does_not_duplicate_the_pick(capture) -> None:
    """The extension de-dups by pick_number and SQLite has a unique index, but a FOLD that
    accepted a repeat would put the same player on the board twice and shift every later round."""
    once = fold_state(capture)
    twice = fold_state([ev for ev in capture for _ in (0, 1)])
    assert [p.overall for p in twice.picks] == [p.overall for p in once.picks]
    assert twice.current_overall_pick == once.current_overall_pick


def test_the_order_survives_a_full_replay(capture) -> None:
    """A reconnect replays the whole durable stream. The room's order must still be there
    afterwards — which is why a mid-draft backend restart is a scripted step of the rehearsal."""
    folded = fold_state(capture)
    assert folded.draft_order is not None
    assert len(folded.draft_order) == 12


def test_the_order_survives_frames_arriving_out_of_order(capture) -> None:
    """The order rides on repeated league_settings frames, so a scrambled stream must not end on
    a variant that lacks it."""
    scrambled_input = list(capture)
    random.Random(4).shuffle(scrambled_input)
    assert fold_state(scrambled_input).draft_order == fold_state(capture).draft_order


def test_a_stale_resync_arriving_late_does_not_roll_the_board_back(capture) -> None:
    """The realistic version of the shuffle above, and the reason for the staleness guard.

    ``lib/transport.ts::send`` queues an event for WS flush on reconnect AND mirrors it over REST
    immediately, and a ``draft_state`` carries no ``pick_number`` — so ``_dedup_pick_number``
    returns None and the storage layer cannot de-dup it. The same subscribe/response snapshot
    therefore legitimately arrives twice on a reconnect, with the second copy landing after every
    pick that came in between. Replaying it wholesale folded 9 picks where the ordered stream
    folds 168.
    """
    resync = [
        ev for ev in capture if ev.event_type == DraftEventType.DRAFT_STATE and "picks" in ev.data
    ]
    assert len(resync) == 1, "fixture no longer carries exactly one resync — rewrite this test"
    ordered = fold_state(capture)
    replayed = fold_state([*capture, resync[0]])  # the duplicate, arriving last
    assert len(replayed.picks) == len(ordered.picks)
    assert replayed.current_overall_pick == ordered.current_overall_pick


def test_a_FIRST_resync_is_still_authoritative(capture) -> None:
    """The guard must not break the thing the resync exists for: joining late, with an empty
    board, must still adopt the whole snapshot (Tier 3's finding — three real drafted players
    were unmasked and recommendable without it)."""
    resync = next(
        ev for ev in capture if ev.event_type == DraftEventType.DRAFT_STATE and "picks" in ev.data
    )
    assert fold_state([resync]).picks, "a resync onto an empty board must be adopted"


def _state_event(seq: int, *, overall: int, picks: list[int]) -> LoggedEvent:
    return LoggedEvent(
        seq=seq,
        league_id="cbs-live",
        event_type=DraftEventType.DRAFT_STATE,
        pick_number=None,
        data={
            "current_overall_pick": overall,
            "picks": [
                {
                    "overall": o,
                    "round": 1,
                    "pick_in_round": o,
                    "team_id": str(o),
                    "player_id": f"gsis:p{o}",
                }
                for o in picks
            ],
        },
        source="ws",
        captured_at="2026-07-25T15:45:18.000Z",
    )


def test_a_resync_with_the_same_MAX_but_more_picks_is_still_adopted() -> None:
    """The staleness guard compares MAX overall, so `<=` instead of `<` would silently reject a
    resync that fills gaps without extending the board — which is Tier 3's defect in miniature
    (its snapshot was the ONLY source of three real drafted players, and without them they stayed
    recommendable mid-draft).

    No committed capture has this shape, so it is built here. Mutating the guard to `<=` passed
    every other test in this file; that is exactly the blind spot this tier exists to close.
    """
    have = _state_event(1, overall=6, picks=[1, 3, 5])
    fills_gaps = _state_event(2, overall=6, picks=[1, 2, 3, 4, 5])
    folded = fold_state([have, fills_gaps])
    assert sorted(p.overall for p in folded.picks) == [1, 2, 3, 4, 5]


def test_a_resync_that_EXTENDS_the_board_is_adopted() -> None:
    have = _state_event(1, overall=4, picks=[1, 2, 3])
    later = _state_event(2, overall=7, picks=[1, 2, 3, 4, 5, 6])
    folded = fold_state([have, later])
    assert sorted(p.overall for p in folded.picks) == [1, 2, 3, 4, 5, 6]
    assert folded.current_overall_pick == 7
