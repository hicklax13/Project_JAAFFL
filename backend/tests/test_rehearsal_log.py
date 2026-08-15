"""TIER 12 — the rehearsal must produce EVIDENCE, not impressions.

A CBS draft is one-shot and on someone else's clock: watching the overlay during one yields a
feeling about how it went. This yields a file. One JSONL line per recommendation actually served,
from BOTH the push (/recs/ws) and pull (GET /recommendation) paths, so a single draft answers —
with numbers — was survival live, how long did each recompute take against the <200 ms budget, was
every drafted player masked off the board, and did every CBS id resolve.

OFF unless ``JAAFFL_REHEARSAL_LOG`` is set, and fail-soft when on: draft night must not acquire a
new failure mode in exchange for a log.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from jaaffl.api import create_app
from jaaffl.config import Settings
from tests.test_api import _primed_engine, pick_payload


def _app(tmp_path: Path, **over):
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            **over,
        ),
        rec_engine=_primed_engine(),
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestItIsOffByDefault:
    def test_no_file_is_written_when_the_setting_is_unset(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert list(tmp_path.rglob("*.jsonl")) == []


class TestItRecordsWhatTheRehearsalNeeds:
    def test_the_push_path_writes_a_line_per_recommendation(self, tmp_path: Path) -> None:
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        rows = _lines(out)
        assert len(rows) == 1
        assert rows[0]["path"] == "push"

    def test_the_pull_path_writes_one_too_and_says_so(self, tmp_path: Path) -> None:
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert [r["path"] for r in _lines(out)] == ["push", "pull"]

    def test_every_field_the_report_reads_is_present(self, tmp_path: Path) -> None:
        """Pins the contract between the sink and scripts/rehearsal_report.py, so a field rename
        cannot silently blank a column of the evidence table."""
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        row = _lines(out)[0]
        assert set(row) >= {
            "ts",
            "path",
            "league_id",
            "overall",
            "survival_basis",
            "vona_method",
            "recompute_ms",
            "draft_order_len",
            "my_team_id",
            "ranked_n",
            "positive_vona_n",
            "picks_total",
            "picks_masked",
            "picks_unresolved",
            "unresolved_ids",
            "top",
        }
        assert set(row["top"]) >= {"player_id", "name", "vona", "mlv", "projected_points"}

    def test_it_counts_the_picks_the_engine_actually_masked(self, tmp_path: Path) -> None:
        """The question a rehearsal has to answer: did a drafted player stay on my board? A pick
        is masked only when its id is a real candidate — an unresolved name-only pick or an
        unresolved 'cbs:<id>' one is still on the owner's board and can be recommended again."""
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1, player_id="rb0"))
        client.post("/draft/events", json=pick_payload(2, player_id="cbs:9999999"))
        row = _lines(out)[-1]
        assert row["picks_total"] == 2
        assert row["picks_masked"] == 1
        assert row["picks_unresolved"] == 1
        assert row["unresolved_ids"] == ["cbs:9999999"]

    def test_the_pull_row_carries_components_even_when_the_caller_stripped_them(
        self, tmp_path: Path
    ) -> None:
        """positive_vona_n reads ScoreComponents. GET /recommendation?include_components=false
        returns a stripped copy, and recording THAT would report 0 candidates with a live
        scarcity term on every pull — a silent zero in the exact column this tier exists for."""
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        client.get(
            "/recommendation",
            params={"league_id": "L1", "team_id": "t0", "include_components": "false"},
        )
        pull = [r for r in _lines(out) if r["path"] == "pull"][-1]
        assert pull["positive_vona_n"] > 0
        assert pull["top"]["mlv"] is not None


class TestItNeverBreaksTheHotPath:
    def test_an_unwritable_path_does_not_fail_the_recommendation(self, tmp_path: Path) -> None:
        """A directory where a file should be: open() raises. Draft night must not acquire a new
        failure mode in exchange for a log."""
        bad = tmp_path / "not-a-file.jsonl"
        bad.mkdir(parents=True)
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=bad))
        client.post("/draft/events", json=pick_payload(1))
        res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert res.status_code == 200


# --- An EMPTY JAAFFL_REHEARSAL_LOG must mean OFF, not "write to the current directory" --------
#
# `jaaffl_rehearsal_log: Path | None = None`, and pydantic coerces the empty string to `Path('')`,
# which IS `Path('.')`. `RehearsalLog.enabled` tested `self._path is not None`, so an empty setting
# read as ENABLED and every recommendation then tried to open a DIRECTORY for append:
#
#     [warning] rehearsal_log_write_failed  path=.
#     PermissionError: [Errno 13] Permission denied: '.'
#
# Observed 2026-08-15 while auditing the dashboard path. Fail-soft caught it, so nothing crashed —
# but the sink reported itself enabled while writing nothing, which is the one outcome this file's
# own docstring says must never happen quietly.
#
# ⚠️ This is the SAME bug class Tier 12 already fixed for `JAAFFL_MY_TEAM_ID`: `KEY=` in the
# owner's real `.env` parses as a VALUE, not as absent, so `is not None` is the wrong test.
# `api/app.py:164` and `:304` use truthiness for exactly this reason. The rehearsal sink was
# missed, and the owner's `.env` already carries one bare `KEY=` line, so the shape is not
# hypothetical.

from jaaffl.api.rehearsal import RehearsalLog  # noqa: E402


class TestAnEmptySettingMeansOff:
    def test_the_empty_string_resolves_to_no_path_at_all(self) -> None:
        assert Settings(jaaffl_rehearsal_log="").jaaffl_rehearsal_log is None

    def test_a_bare_dot_is_not_a_log_file(self) -> None:
        """Defence in depth: even handed `Path('.')` directly, the sink must stay off. A directory
        is never a valid append target, and this is what the empty string coerces to."""
        assert RehearsalLog(Path(".")).enabled is False

    def test_none_is_still_off_and_a_real_path_is_still_on(self, tmp_path: Path) -> None:
        assert RehearsalLog(None).enabled is False
        assert RehearsalLog(tmp_path / "run.jsonl").enabled is True

    def test_an_empty_setting_logs_no_write_failure_on_the_hot_path(self, tmp_path: Path) -> None:
        """End to end, and asserted on the SYMPTOM rather than on survival. Fail-soft already made
        this harmless, so a status-200 check passes with the bug intact; what actually happened is
        a PermissionError traceback per recommendation, on a live clock."""
        from structlog.testing import capture_logs

        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=""))
        with capture_logs() as logs:
            assert client.post("/draft/events", json=pick_payload(1)).status_code == 200
        failures = [e for e in logs if e.get("event") == "rehearsal_log_write_failed"]
        assert not failures, f"a disabled sink still tried to write: {failures}"
        assert not list(Path.cwd().glob("*.jsonl")), "must not litter the CWD"
