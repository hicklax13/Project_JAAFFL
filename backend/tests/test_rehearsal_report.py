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


# --- The prelude: the opening rows, recomputed before the order could exist ----------------
#
# CBS attaches the entered round-1 order to `fullstatedelta`, which rides on `picks/completed`
# frames (apps/extension/src/lib/parse.ts:123). parse.ts pushes the PICK events (line 332) before
# the ORDER event (line 347) from that same frame, and `LEAGUE_SETTINGS` is not in
# `_STATE_ADVANCING` (backend/src/jaaffl/api/app.py:43), so folding the order does not itself
# recompute. The opening recompute of every draft therefore runs before the order exists.
#
# Measured on a live server at 2a69c40: 7 rows, the early ones `degraded_no_order` and the later
# one `my_slot`. The old verdicts (`bases == {"my_slot"}`, `orders == {12}`) failed BOTH on that
# run — a healthy pipeline reported as broken, which is the exact failure mode this file exists
# to prevent, pointed the other way.


def _degraded(**over) -> dict:
    """A prelude row: the order has not been folded yet, so survival cannot be live."""
    return _row(survival_basis="degraded_no_order", draft_order_len=0, positive_vona_n=0, **over)


def test_a_prelude_before_the_order_arrives_is_not_a_failure() -> None:
    """The structural opening row must not fail a run that is otherwise clean."""
    verdicts = evaluate([_degraded(overall=1), _row(overall=2), _row(overall=3)])
    assert all(v.passed for v in verdicts), [v.name for v in verdicts if not v.passed]


def test_a_degraded_row_after_the_order_arrived_is_still_a_failure() -> None:
    """The property that actually matters, and that nothing tested before: once the order has
    been read, it must never go away again."""
    rows = [_degraded(overall=1), _row(overall=2), _degraded(overall=3)]
    failed = _failed(rows)
    assert "survival is live" in failed
    assert "the order was read from the room" in failed


def test_an_order_that_never_arrives_fails() -> None:
    """A whole draft run blind is the headline defect of Tier 12. It must never read as clean."""
    failed = _failed([_degraded(overall=1), _degraded(overall=2)])
    assert "survival is live" in failed
    assert "the order was read from the room" in failed


def test_a_wrong_length_order_fails_even_though_one_arrived() -> None:
    """`opponents._my_overall_picks` uses len(draft_order) AS the team count, so an 11-entry
    order silently corrupts every 'my next pick'. Neither 0 nor 12 is acceptable."""
    rows = [_row(overall=1), _row(overall=2, draft_order_len=11)]
    assert "the order was read from the room" in _failed(rows)


def test_the_prelude_length_is_named_in_the_detail() -> None:
    """A tolerated prelude that nobody can see is how a 40-row blind opening would slip past.
    The count is stated so a human reads it even when the verdict passes."""
    verdicts = evaluate([_degraded(overall=1), _row(overall=2)])
    order = next(v for v in verdicts if v.name == "the order was read from the room")
    assert order.passed
    assert "1" in order.detail and "prelude" in order.detail.lower()


def test_a_wrong_length_order_in_the_PRELUDE_fails() -> None:
    """The case the prelude allowance could otherwise hide, and the one mutation testing caught:
    a prelude row is meant to carry NO order (len 0). An 11-entry order there is corruption, not
    a not-yet-arrived order, and `_my_overall_picks` would read 11 AS the team count. Without the
    explicit length check this passes, because the later len-12 row makes `order_lost` zero."""
    rows = [_row(overall=1, draft_order_len=11), _row(overall=2)]
    bad = next(v for v in evaluate(rows) if v.name == "the order was read from the room")
    assert not bad.passed
    assert "11" in bad.detail


# --- A run whose ENGINE DIED must FAIL, not pass six of seven ---------------------------------
#
# On 2026-08-15 this report printed six PASS verdicts on a draft that ended in an unhandled
# KeyError. It had no choice: a crash writes no row, the report grades only rows that exist, and
# no criterion asked whether the engine threw. The most important event of the evening was
# invisible to the instrument built to observe it — the same failure shape as "an empty log reads
# as clean", which this file already guards against by name.


def _failure_row(**over) -> dict:
    row = {
        "ts": "2026-08-15T19:21:07.000+00:00",
        "path": "push",
        "league_id": "cbs-live",
        "overall": 168,
        "error": "KeyError: 'cbs:1910'",
    }
    row.update(over)
    return row


def test_a_recompute_failure_fails_the_run() -> None:
    rows = [_degraded(overall=1), _row(overall=2), _failure_row()]
    failed = _failed(rows)
    assert "no recompute failed" in failed, f"a dead engine still read as clean: {failed}"


def test_the_failing_error_is_named_so_it_can_be_chased() -> None:
    verdict = next(v for v in evaluate([_row(), _failure_row()]) if v.name == "no recompute failed")
    assert not verdict.passed
    assert "cbs:1910" in verdict.detail


def test_a_clean_run_passes_the_new_criterion_too() -> None:
    verdicts = evaluate([_degraded(overall=1), _row(overall=2)])
    assert all(v.passed for v in verdicts), [v.name for v in verdicts if not v.passed]


def test_failure_rows_do_not_corrupt_the_other_verdicts() -> None:
    """A failure row has no survival_basis, no recompute_ms and no top — it must be graded on its
    own criterion and excluded from the others, or one crash would fail every check for the wrong
    reason and bury the real signal."""
    healthy = [_degraded(overall=1)] + [_row(overall=i) for i in range(2, 6)]
    verdicts = {v.name: v for v in evaluate([*healthy, _failure_row()])}
    assert verdicts["survival is live"].passed
    assert verdicts["the order was read from the room"].passed
    assert verdicts["recompute under 200ms"].passed
    assert not verdicts["no recompute failed"].passed


def test_an_empty_log_still_fails_the_new_criterion_by_name() -> None:
    assert "no recompute failed" in {v.name for v in evaluate([]) if not v.passed}


def test_the_overlay_foot_ignores_a_failure_row() -> None:
    """The foot describes what the OVERLAY last showed. A failure row has no recompute_ms and no
    basis, so deriving from it printed a meaningless "recompute 0ms" over a crashed run."""
    served = _row(overall=9, recompute_ms=12.0)
    assert "12ms" in report_script._overlay_foot(served)
    assert report_script._overlay_foot(_failure_row()) != report_script._overlay_foot(served)
