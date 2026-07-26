"""TIER 3 / TASK 2 — late-join resync, folded from a real mid-draft capture.

The owner's 2026-07-25 record-mode session began AFTER the draft was underway. Its delta
stream covers overalls 4..168; picks 1, 2 and 3 were never sent as deltas and exist only in
the ``subscribe/response`` snapshot CBS sends on connect. Nothing consumed that snapshot, so
replaying the capture left three genuinely drafted players unmasked — and therefore
recommendable, by name, to the owner, in the middle of a real draft.

This drives the real late-join stream (``late-join.events.json`` — parse.ts's own output over
the snapshot frame followed by every delta frame, drift-guarded in
``apps/extension/tests/resync.test.ts``) through ``fold_state`` and checks the board that
comes out, not the fact that ingest returned without raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaaffl.domain import DraftEvent, DraftEventType
from jaaffl.ingest import handle_event
from jaaffl.ingest.log import DraftLog

REPO_ROOT = Path(__file__).resolve().parents[2]
CBS = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs"

TEAMS = 12
CAPTURE_ROUNDS = 14
CAPTURE_PICKS = TEAMS * CAPTURE_ROUNDS  # 168
# Picks the mid-draft join never received as deltas.
SNAPSHOT_ONLY = [1, 2, 3]


def _events(name: str) -> list[DraftEvent]:
    return [
        DraftEvent.model_validate(e) for e in json.loads((CBS / name).read_text(encoding="utf-8"))
    ]


def _fold(events: list[DraftEvent], db_path: Path):
    draft_log = DraftLog(db_path)
    result = None
    for event in events:
        result = handle_event(event, draft_log, captured_at="2026-07-25T15:45:18.000Z")
    assert result is not None
    return result.state


def _is_resync(event: DraftEvent) -> bool:
    """A full-board resync, as opposed to the ticker draft_state most frames carry."""
    return event.event_type == DraftEventType.DRAFT_STATE and "picks" in event.data


@pytest.fixture(scope="module")
def late_join_events() -> list[DraftEvent]:
    return _events("late-join.events.json")


@pytest.fixture(scope="module")
def folded_with_snapshot(late_join_events, tmp_path_factory):
    db = tmp_path_factory.mktemp("resync-with") / "draft.sqlite"
    return _fold(late_join_events, db)


@pytest.fixture(scope="module")
def folded_deltas_only(late_join_events, tmp_path_factory):
    """The same join WITHOUT the snapshot — i.e. the behaviour before this change."""
    db = tmp_path_factory.mktemp("resync-without") / "draft.sqlite"
    return _fold([e for e in late_join_events if not _is_resync(e)], db)


@pytest.fixture(scope="module")
def from_snapshot(tmp_path_factory):
    """A complete 168-pick board delivered as ONE subscribe resync, no deltas."""
    db = tmp_path_factory.mktemp("full-snap") / "draft.sqlite"
    return _fold(_events("subscribe-complete.events.json"), db)


@pytest.fixture(scope="module")
def from_deltas(tmp_path_factory):
    """The same geometry rebuilt the slow way, from every pick delta."""
    db = tmp_path_factory.mktemp("full-delta") / "draft.sqlite"
    return _fold(_events("full-draft.events.json"), db)


class TestTheGapIsReal:
    """Pin the defect on real data before pinning the fix."""

    def test_the_delta_stream_alone_is_missing_the_first_three_picks(
        self, folded_deltas_only
    ) -> None:
        overalls = [p.overall for p in folded_deltas_only.picks]
        assert len(overalls) == CAPTURE_PICKS - len(SNAPSHOT_ONLY)
        assert [o for o in SNAPSHOT_ONLY if o in overalls] == []
        assert min(overalls) == 4

    def test_those_picks_are_real_players_that_would_be_recommended_again(
        self, late_join_events, folded_deltas_only
    ) -> None:
        resync = next(e for e in late_join_events if _is_resync(e))
        missing_ids = {
            p["player_id"] for p in resync.data["picks"] if p["overall"] in SNAPSHOT_ONLY
        }
        assert len(missing_ids) == len(SNAPSHOT_ONLY)
        folded_ids = {p.player_id for p in folded_deltas_only.picks}
        # Not masked anywhere in the deltas-only board: drafted, but still on offer.
        assert missing_ids & folded_ids == set()


class TestTheSnapshotClosesIt:
    def test_snapshot_plus_deltas_recovers_the_whole_draft(self, folded_with_snapshot) -> None:
        assert [p.overall for p in folded_with_snapshot.picks] == list(range(1, CAPTURE_PICKS + 1))

    def test_the_recovered_picks_carry_real_ids_teams_and_rounds(
        self, folded_with_snapshot
    ) -> None:
        recovered = [p for p in folded_with_snapshot.picks if p.overall in SNAPSHOT_ONLY]
        assert len(recovered) == len(SNAPSHOT_ONLY)
        for pick in recovered:
            assert pick.player_id.startswith("cbs:")
            assert pick.round == 1
            assert pick.pick_in_round == pick.overall
            assert pick.team_id  # CBS's own team_id for the roster entry, not a guess

    def test_a_snapshot_alone_is_a_complete_join(self, late_join_events, tmp_path) -> None:
        """One event, no deltas at all: the board is whatever CBS said it was."""
        resync = next(e for e in late_join_events if _is_resync(e))
        state = _fold([resync], tmp_path / "snapshot-only.sqlite")
        assert [p.overall for p in state.picks] == SNAPSHOT_ONLY
        assert state.current_overall_pick == 4  # the pick that was on the clock at join

    def test_the_snapshot_agrees_with_the_deltas_where_they_overlap(
        self, folded_with_snapshot, folded_deltas_only
    ) -> None:
        """The two sources must not contradict each other on any shared pick."""
        by_overall = {p.overall: p for p in folded_with_snapshot.picks}
        for pick in folded_deltas_only.picks:
            assert by_overall[pick.overall].player_id == pick.player_id
            assert by_overall[pick.overall].team_id == pick.team_id


class TestAFullBoardSnapshotJoinsWithNoDeltasAtAll:
    """The strongest form of the resync claim: arrive with the draft already over.

    ⚠️ Honest scope. ``subscribe-complete.json`` and ``full-draft.deltas.jsonl`` come from two
    DIFFERENT mock drafts in the capture set (measured: their overall->team_id mapping agrees
    168/168, but the players picked agree only 26/168 — same entered order, different draft).
    So this asserts the two code paths produce STRUCTURALLY identical DraftStates, not the
    same players. Exact per-player equivalence on one draft is covered by
    ``TestTheSnapshotClosesIt.test_the_snapshot_agrees_with_the_deltas_where_they_overlap``,
    where snapshot and deltas do come from the same session.
    """

    def test_one_snapshot_event_rebuilds_the_entire_board(self, from_snapshot) -> None:
        assert [p.overall for p in from_snapshot.picks] == list(range(1, CAPTURE_PICKS + 1))

    def test_it_lands_on_the_same_shape_as_replaying_every_delta(
        self, from_snapshot, from_deltas
    ) -> None:
        assert len(from_snapshot.picks) == len(from_deltas.picks)
        assert from_snapshot.complete == from_deltas.complete
        assert from_snapshot.current_overall_pick == from_deltas.current_overall_pick
        snap = {(p.overall, p.team_id, p.round, p.pick_in_round) for p in from_snapshot.picks}
        delta = {(p.overall, p.team_id, p.round, p.pick_in_round) for p in from_deltas.picks}
        # Same entered draft order => identical overall -> (team, round, pick) structure.
        assert snap == delta


class TestATickerStillNeverWipesTheBoard:
    """The resync path must not reopen the PR-#28 bug it sits next to."""

    def test_the_54_ticker_frames_after_the_snapshot_leave_it_intact(
        self, folded_with_snapshot, late_join_events
    ) -> None:
        tickers = [
            e
            for e in late_join_events
            if e.event_type == DraftEventType.DRAFT_STATE and "picks" not in e.data
        ]
        assert len(tickers) >= 50, "expected the real ticker storm in this capture"
        # 168 picks survived all of them.
        assert len(folded_with_snapshot.picks) == CAPTURE_PICKS

    def test_exactly_one_event_in_the_stream_claims_to_be_a_resync(self, late_join_events) -> None:
        # If ticker frames ever started carrying `picks`, every tick would replace the whole
        # board — which is precisely how fullstatedelta.teams would have behaved.
        assert sum(1 for e in late_join_events if _is_resync(e)) == 1


class TestTheDraftOverSentinel:
    def test_the_draft_ends_complete_with_no_phantom_pick(self, folded_with_snapshot) -> None:
        assert folded_with_snapshot.complete is True
        assert max(p.overall for p in folded_with_snapshot.picks) == CAPTURE_PICKS
        # opick overran to 169; that is the "no picks left" sentinel, not a 169th pick.
        assert folded_with_snapshot.current_overall_pick == CAPTURE_PICKS + 1
        assert all(p.overall <= CAPTURE_PICKS for p in folded_with_snapshot.picks)
