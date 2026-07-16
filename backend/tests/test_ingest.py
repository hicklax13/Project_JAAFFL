"""handle_event pipeline (plan §2.6 ordering invariant): normalize -> durable append ->
fold -> result. Append happens BEFORE any downstream work; duplicates ack idempotently."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from jaaffl.domain import DraftEvent
from jaaffl.ingest import handle_event, normalize_league_settings
from jaaffl.ingest.log import DraftLog


@pytest.fixture
def log(tmp_path: Path) -> DraftLog:
    return DraftLog(tmp_path / "app.sqlite")


def pick(overall: int, *, pick_number: int | None = None) -> DraftEvent:
    return DraftEvent(
        event_type="pick_made",
        league_id="L1",
        pick_number=pick_number,
        source="ws",
        data={
            "overall": overall,
            "round": 1,
            "pick_in_round": overall,
            "team_id": f"T{overall}",
            "player_id": f"cbs:{overall}",
        },
    )


def test_handle_event_appends_then_folds(log: DraftLog) -> None:
    result = handle_event(pick(1, pick_number=1), log)
    assert result.seq is not None
    assert result.deduped is False
    assert result.state.current_overall_pick == 2
    assert [p.overall for p in result.state.picks] == [1]


def test_handle_event_duplicate_pick_acks_idempotently(log: DraftLog) -> None:
    first = handle_event(pick(1, pick_number=1), log)
    dup = handle_event(pick(1, pick_number=1), log)
    assert dup.seq is None
    assert dup.deduped is True
    assert dup.state == first.state  # no state change, no re-broadcast trigger


def test_handle_event_derives_pick_number_from_overall(log: DraftLog) -> None:
    """§5.8: pick_number is required-when-present for pick_made — when a probe omits the
    envelope key, ingestion derives it from data.overall so storage de-dup still holds."""
    handle_event(pick(3, pick_number=None), log)
    dup = handle_event(pick(3, pick_number=3), log)
    assert dup.deduped is True


def test_handle_event_on_the_clock_dedups_on_current_pick(log: DraftLog) -> None:
    otc = DraftEvent(
        event_type="on_the_clock",
        league_id="L1",
        source="dom",
        data={"current_overall_pick": 5, "team_id": "T5"},
    )
    assert handle_event(otc, log).deduped is False
    assert handle_event(otc, log).deduped is True  # re-rendered DOM must not spam the log


def test_handle_event_rejects_malformed_pick_before_append(log: DraftLog) -> None:
    bad = DraftEvent(
        event_type="pick_made", league_id="L1", pick_number=1, data={"overall": 1}
    )  # missing round/pick_in_round/team_id
    with pytest.raises(ValidationError):
        handle_event(bad, log)
    with pytest.raises(ValueError):
        log.state("L1")  # nothing was appended


def test_normalize_league_settings_reports_as_read_never_corrects() -> None:
    """agent_usage_contract: conflicts with the immutable league are surfaced, never
    silently 'fixed' — a 10-team payload normalizes to team_count=10."""
    settings = normalize_league_settings({"league_id": "L-weird", "team_count": 10})
    assert settings.team_count == 10


def test_normalize_league_settings_validates_shape() -> None:
    with pytest.raises(ValidationError):
        normalize_league_settings({"league_id": "L1", "team_count": 0})
