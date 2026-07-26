"""Board position-coverage guard (the drift alarm behind the PK/K + DST gaps).

Both live gaps this guard exists to catch were SILENT: the universe loader logged a large,
normal-looking skip count while two of the nine starting slots were unfillable. The guard
inverts the question — instead of "were there unmapped source codes?" (noisy, ignorable) it
asks "can every STARTABLE slot actually be filled from the board?" (a short, unambiguous list).

Startability is derived from the league's own roster slots, so a league change moves the guard
with it and bench-only IDP positions never raise a false alarm.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.league.coverage import board_coverage_gaps, startable_positions

# backend/tests/test_coverage.py -> repo root is parents[2].
_PREFLIGHT = Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"


def _settings(**over) -> LeagueSettings:
    """JAAFFL's real shape: 9 starters (QB/RB/WR×3/flex/TE/K/DST) + 8 bench."""
    base = dict(
        league_id="jaaffl-2026",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=3),
            RosterSlot(slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1),
            RosterSlot(slot="K", eligible_positions=[Position.K], count=1),
            RosterSlot(slot="DST", eligible_positions=[Position.DST], count=1),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=8,
                starting=False,
            ),
        ],
    )
    base.update(over)
    return LeagueSettings(**base)


def test_startable_positions_comes_from_the_leagues_own_starting_slots() -> None:
    assert startable_positions(_settings()) == {
        Position.QB,
        Position.RB,
        Position.WR,
        Position.TE,
        Position.K,
        Position.DST,
    }


def test_startable_positions_excludes_bench_only_slots() -> None:
    """A bench-eligible IDP position is NOT startable — the guard must never demand one, or it
    would fire forever in this non-IDP league and be trained away as noise."""
    settings = _settings(
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="BENCH", eligible_positions=[Position.LB], count=8, starting=False),
        ]
    )
    assert startable_positions(settings) == {Position.QB}


def test_startable_positions_ignores_zero_count_slots() -> None:
    settings = _settings(
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="DST", eligible_positions=[Position.DST], count=0),
        ]
    )
    assert startable_positions(settings) == {Position.QB}


def test_board_coverage_gaps_is_empty_when_every_startable_slot_is_fillable() -> None:
    board = {
        "a": Position.QB,
        "b": Position.RB,
        "c": Position.WR,
        "d": Position.TE,
        "e": Position.K,
        "f": Position.DST,
    }
    assert board_coverage_gaps(_settings(), board) == []


def test_board_coverage_gaps_reports_the_missing_positions_sorted() -> None:
    """The exact live regression: kickers and defenses absent from the board."""
    board = {"a": Position.QB, "b": Position.RB, "c": Position.WR, "d": Position.TE}
    assert board_coverage_gaps(_settings(), board) == [Position.DST, Position.K]


def test_board_coverage_gaps_ignores_extra_unstartable_positions() -> None:
    """1,183 linebackers on the board do not make up for a missing kicker."""
    board = {
        "a": Position.QB,
        "b": Position.RB,
        "c": Position.WR,
        "d": Position.TE,
        "e": Position.DST,
        "f": Position.LB,
        "g": Position.DL,
    }
    assert board_coverage_gaps(_settings(), board) == [Position.K]


def test_board_coverage_gaps_flags_everything_on_an_empty_board() -> None:
    assert board_coverage_gaps(_settings(), {}) == [
        Position.DST,
        Position.K,
        Position.QB,
        Position.RB,
        Position.TE,
        Position.WR,
    ]


# --- scripts/preflight.py exit-code contract -------------------------------------------------
# The script stays thin (the logic above is what's really tested), but an alarm that cannot
# actually fire is worse than none — these pin that it fails loudly and passes quietly.


def _load_preflight():
    spec = importlib.util.spec_from_file_location("preflight", _PREFLIGHT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_context(board: dict[str, Position]):
    """Enough of a DraftContext for preflight: settings + mu + position."""
    return SimpleNamespace(
        settings=_settings(),
        mu=dict.fromkeys(board, 1.0),
        position=dict(board),
    )


@pytest.fixture
def preflight(monkeypatch, tmp_path):
    """The script with its network context-build stubbed; returns (module, set_board)."""
    module = _load_preflight()
    holder: dict = {}
    monkeypatch.setattr(
        module,
        "build_registry_context_source",
        lambda *a, **k: lambda league_id: holder.get("context"),
    )
    return module, holder, tmp_path


def test_preflight_exits_nonzero_when_a_startable_position_is_missing(preflight) -> None:
    """The live regression: a board with no kickers and no defenses must FAIL the morning check."""
    module, holder, tmp_path = preflight
    holder["context"] = _fake_context(
        {"a": Position.QB, "b": Position.RB, "c": Position.WR, "d": Position.TE}
    )
    assert module.main(["--data-dir", str(tmp_path)]) == 1


def test_preflight_exits_zero_when_every_startable_position_is_fillable(preflight) -> None:
    module, holder, tmp_path = preflight
    holder["context"] = _fake_context(
        {
            "a": Position.QB,
            "b": Position.RB,
            "c": Position.WR,
            "d": Position.TE,
            "e": Position.K,
            "f": Position.DST,
            "g": Position.LB,  # bench-only extras never affect the verdict
        }
    )
    assert module.main(["--data-dir", str(tmp_path)]) == 0


def test_preflight_exits_nonzero_when_no_context_can_be_built(preflight) -> None:
    """An empty universe already 503s the live service; preflight must not report OK for it."""
    module, holder, tmp_path = preflight
    holder["context"] = None
    assert module.main(["--data-dir", str(tmp_path)]) == 1
