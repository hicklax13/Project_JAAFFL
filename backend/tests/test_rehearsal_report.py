"""The report IS the deliverable of the rehearsal, so its verdicts are tested like code.

The failure this file exists to prevent is the one the whole tier is about: a report that reads
"OK" over a run that proved nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    """Import the standalone (stdlib-only) report script by path.

    Registered in ``sys.modules`` BEFORE ``exec_module``: the script uses ``@dataclass`` under
    ``from __future__ import annotations``, and ``dataclasses`` resolves those string annotations
    through ``sys.modules[cls.__module__].__dict__``. Without the registration that lookup returns
    None and collection dies with an AttributeError rather than a test failure. Run as a script
    the module is ``__main__`` and already registered, so this only bites the importlib path.
    """
    path = REPO_ROOT / "scripts" / "rehearsal_report.py"
    spec = importlib.util.spec_from_file_location("rehearsal_report", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report_script = _load_script()
evaluate = report_script.evaluate


def _row(**over) -> dict:
    row = {
        "ts": "2026-08-10T12:00:00.000+00:00",
        "path": "push",
        "league_id": "cbs-live",
        "overall": 7,
        "survival_basis": "my_slot",
        "vona_method": "analytic",
        "recompute_ms": 8.0,
        "draft_order_len": 12,
        "my_team_id": "7",
        "ranked_n": 50,
        "positive_vona_n": 11,
        "picks_total": 6,
        "picks_masked": 6,
        "picks_unresolved": 0,
        "unresolved_ids": [],
        "roster_filled": 0,
        "top": {
            "player_id": "gsis:x",
            "name": "X",
            "vona": 3.0,
            "mlv": 40.0,
            "projected_points": 250.0,
        },
    }
    row.update(over)
    return row


def _failed(rows: list[dict]) -> set[str]:
    return {v.name for v in evaluate(rows) if not v.passed}


def test_a_clean_rehearsal_passes_every_check() -> None:
    verdicts = evaluate([_row(), _row(overall=19)])
    assert all(v.passed for v in verdicts), [v.name for v in verdicts if not v.passed]


def test_a_degraded_survival_basis_fails_loudly() -> None:
    rows = [_row(), _row(survival_basis="degraded_no_order", positive_vona_n=0)]
    assert "survival is live" in _failed(rows)


def test_a_recompute_over_the_budget_fails() -> None:
    """Asserted on the MAX, not the median: one 250 ms recompute on the clock is the thing the
    budget exists to catch, and a median would hide it behind the other 100 rows."""
    assert "recompute under 200ms" in _failed([_row(), _row(recompute_ms=250.0)])


def test_an_unmasked_drafted_player_fails_and_is_named() -> None:
    rows = [_row(picks_masked=5, picks_unresolved=1, unresolved_ids=["cbs:404"])]
    bad = next(v for v in evaluate(rows) if v.name == "every drafted player masked")
    assert not bad.passed
    assert "cbs:404" in bad.detail


def test_a_dead_scarcity_term_fails_even_when_survival_says_my_slot() -> None:
    """survival_basis is a label. If it says my_slot and VONA is still 0 for every candidate,
    something else is broken and the report must not call that a clean run."""
    assert "the scarcity term is live" in _failed([_row(), _row(positive_vona_n=0)])


def test_a_short_draft_order_fails() -> None:
    assert "the order was read from the room" in _failed([_row(draft_order_len=0)])


def test_an_empty_log_is_a_failure_not_a_pass() -> None:
    """A rehearsal that recorded nothing must never read as a clean run — the single outcome
    most likely to be misread as success."""
    verdicts = evaluate([])
    assert verdicts, "an empty log must still produce verdicts, not an empty report"
    assert not any(v.passed for v in verdicts)


def test_the_overlay_foot_names_the_missing_input() -> None:
    """The report's one claim ABOUT the overlay. Derived from survival_basis, which is the same
    single rule overlay.ts renders — pinned there by apps/extension/tests/overlay.test.ts."""
    assert "draft order not read yet" in report_script._overlay_foot(
        _row(survival_basis="degraded_no_order")
    )
    assert "no draft slot set" in report_script._overlay_foot(
        _row(survival_basis="degraded_no_slot")
    )
    assert "degraded" not in report_script._overlay_foot(_row(survival_basis="my_slot"))
