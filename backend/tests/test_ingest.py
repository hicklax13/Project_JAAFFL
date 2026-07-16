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


def _snapshot_count(db: Path, league_id: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM league_snapshots WHERE league_id = ?", (league_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def _settings_event(**data) -> DraftEvent:
    return DraftEvent(
        event_type="league_settings",
        league_id="L1",
        data={"team_count": 12, "draft_type": "snake", **data},
    )


def test_handle_event_snapshots_league_settings_before_append(tmp_path: Path) -> None:
    """§2.6: a league_settings event persists a league_snapshots row AND still appends to
    the log (the store Stage-4 CbsOnPageProvider reads, not the network)."""
    from jaaffl.data.warehouse import Warehouse

    wh = Warehouse(tmp_path)
    log = DraftLog(tmp_path / "app.sqlite")
    result = handle_event(_settings_event(), log, warehouse=wh)
    assert result.seq is not None  # still appended
    assert _snapshot_count(wh.app_sqlite, "L1") == 1


def test_handle_event_snapshot_dedups_identical_settings(tmp_path: Path) -> None:
    from jaaffl.data.warehouse import Warehouse

    wh = Warehouse(tmp_path)
    log = DraftLog(tmp_path / "app.sqlite")
    handle_event(_settings_event(), log, warehouse=wh)
    handle_event(_settings_event(), log, warehouse=wh)  # byte-identical re-push
    assert _snapshot_count(wh.app_sqlite, "L1") == 1  # snapshot de-duped
    assert len(log.events("L1")) == 2  # but each settings event is a legitimate log row


def test_handle_event_without_warehouse_still_appends(log: DraftLog) -> None:
    """Backward-compatible: no warehouse wired → no snapshot, ingest still works."""
    result = handle_event(_settings_event(), log)
    assert result.seq is not None


def test_handle_event_snapshot_is_skipped_for_non_settings(tmp_path: Path) -> None:
    from jaaffl.data.warehouse import Warehouse, open_app_db

    wh = Warehouse(tmp_path)
    open_app_db(wh.app_sqlite).close()  # app startup ensures the app-state schema exists
    log = DraftLog(tmp_path / "app.sqlite")
    handle_event(pick(1, pick_number=1), log, warehouse=wh)
    assert _snapshot_count(wh.app_sqlite, "L1") == 0  # picks are not league snapshots


def _complete() -> DraftEvent:
    return DraftEvent(event_type="draft_complete", league_id="L1", data={})


def test_handle_event_exports_draft_snapshot_on_complete(tmp_path: Path) -> None:
    """§2.8 offline backtest corpus: a draft_complete event exports final_state.json +
    events.parquet under snapshots/. (recommendations.jsonl is deferred to Stage 5.)"""
    from jaaffl.data.warehouse import Warehouse

    wh = Warehouse(tmp_path)
    wh.init()
    log = DraftLog(tmp_path / "app.sqlite")
    handle_event(pick(1, pick_number=1), log, warehouse=wh)
    handle_event(_complete(), log, warehouse=wh, captured_at="2026-07-16T00:00:00.000Z")
    dirs = list(wh.snapshots_dir.glob("draft_L1_*"))
    assert len(dirs) == 1
    assert (dirs[0] / "final_state.json").exists()
    assert (dirs[0] / "events.parquet").exists()


def test_handle_event_no_draft_export_without_warehouse(log: DraftLog) -> None:
    result = handle_event(_complete(), log)  # no warehouse -> no export, still folds
    assert result.state.complete is True


def test_handle_event_draft_export_only_on_first_complete(tmp_path: Path) -> None:
    """draft_complete has no pick_number so it never dedups — and the 3-probe capture can send
    several. The export must fire ONCE (on the first), not once per probe/re-send."""
    from jaaffl.data.warehouse import Warehouse

    wh = Warehouse(tmp_path)
    wh.init()
    log = DraftLog(tmp_path / "app.sqlite")
    handle_event(pick(1, pick_number=1), log, warehouse=wh)
    handle_event(_complete(), log, warehouse=wh, captured_at="2026-07-16T00:00:00.000Z")
    handle_event(_complete(), log, warehouse=wh, captured_at="2026-07-16T01:00:00.000Z")
    assert len(list(wh.snapshots_dir.glob("draft_L1_*"))) == 1


def test_normalize_league_settings_preserves_raw_payload() -> None:
    """The raw CBS payload round-trips into LeagueSettings.raw so the snapshot owns it
    verbatim (Stage-4 CbsOnPageProvider reads league_snapshots, not the network)."""
    raw = {"league_id": "L1", "team_count": 12, "draft_type": "snake", "cbs_extra": "keep-me"}
    settings = normalize_league_settings(raw)
    assert settings.raw == raw


def test_normalize_league_settings_reports_as_read_never_corrects() -> None:
    """agent_usage_contract: conflicts with the immutable league are surfaced, never
    silently 'fixed' — a 10-team payload normalizes to team_count=10."""
    settings = normalize_league_settings({"league_id": "L-weird", "team_count": 10})
    assert settings.team_count == 10


def test_normalize_league_settings_validates_shape() -> None:
    with pytest.raises(ValidationError):
        normalize_league_settings({"league_id": "L1", "team_count": 0})
