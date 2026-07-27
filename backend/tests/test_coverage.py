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

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Player, Position, RosterSlot
from jaaffl.league.coverage import (
    board_coverage_gaps,
    inert_cliff_positions,
    startable_positions,
    teams_missing_bye_weeks,
    unfillable_starting_slots,
)

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


# --- the tier-cliff liveness guard -------------------------------------------------------------
# Same inversion, one layer up. `cliff_bonus` was POPULATED and useless: 447 entries on the live
# 2026 board, every one exactly 0.0, so `recommend`'s `alpha * CliffBonus` was 0.00 on every pick
# for four tiers of work. A count is not a diagnostic; ask instead "can this term move a pick?"


def _tiered(**per_position: list[float]):
    """Build (tiers, cliff_bonus, position) from per-position cliff values, one player each."""
    tiers, cliff_bonus, position = {}, {}, {}
    for name, bonuses in per_position.items():
        pos = Position(name)
        for i, bonus in enumerate(bonuses):
            pid = f"{name}{i}"
            tiers[pid], cliff_bonus[pid], position[pid] = i + 1, bonus, pos
    return tiers, cliff_bonus, position


_LIVE_BOARD = dict(
    QB=[9.0, 0.0], RB=[40.0, 0.0], WR=[7.0, 0.0], TE=[43.0, 0.0], K=[3.0, 0.0], DST=[4.0, 0.0]
)  # noqa: E501


def test_inert_cliff_positions_is_empty_when_every_position_can_price_a_drop() -> None:
    assert inert_cliff_positions(_settings(), *_tiered(**_LIVE_BOARD)) == []


def test_inert_cliff_positions_names_everything_when_the_whole_map_is_zero() -> None:
    """The exact live regression — a fully populated cliff map that is uniformly 0.0."""
    dead = {name: [0.0] * len(values) for name, values in _LIVE_BOARD.items()}
    assert inert_cliff_positions(_settings(), *_tiered(**dead)) == [
        Position.DST,
        Position.K,
        Position.QB,
        Position.RB,
        Position.TE,
        Position.WR,
    ]


def test_inert_cliff_positions_names_only_the_dead_positions() -> None:
    """Partial death is the harder case: a board-wide "some cliff exists" check would pass here
    while the term stayed inert at two of the six positions."""
    board = {**_LIVE_BOARD, "QB": [0.0, 0.0], "TE": [0.0, 0.0]}
    assert inert_cliff_positions(_settings(), *_tiered(**board)) == [Position.QB, Position.TE]


def test_inert_cliff_positions_flags_a_position_with_no_boundary_at_all() -> None:
    """DST's live shape: all 31 defenses in a SINGLE tier, so there is no boundary to price and
    every entry is 0.0 for a different reason than the others. Same verdict — alpha is dead here."""
    board = {**_LIVE_BOARD, "DST": [0.0]}  # one tier, one entry, no boundary below it
    assert inert_cliff_positions(_settings(), *_tiered(**board)) == [Position.DST]


def test_inert_cliff_positions_ignores_positions_this_league_cannot_start() -> None:
    """A dead cliff among linebackers is not a draft-night problem in a non-IDP league."""
    board = {**_LIVE_BOARD, "LB": [0.0, 0.0]}
    assert inert_cliff_positions(_settings(), *_tiered(**board)) == []


# --- scripts/preflight.py exit-code contract -------------------------------------------------
# The script stays thin (the logic above is what's really tested), but an alarm that cannot
# actually fire is worse than none — these pin that it fails loudly and passes quietly.


def _load_preflight():
    spec = importlib.util.spec_from_file_location("preflight", _PREFLIGHT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_context(board: dict[str, Position], *, cliffs: dict | None = None):
    """Enough of a DraftContext for preflight: settings + mu + position + tier-cliff + byes.

    ``players``/``bye_week`` are populated (rather than omitted) because the real ``DraftContext``
    always carries them, and a fixture thinner than the object under test only proves the fixture.
    """
    tiers, cliff_bonus, cliff_position = _tiered(**(cliffs if cliffs is not None else _LIVE_BOARD))
    return SimpleNamespace(
        settings=_settings(),
        params=EngineParams(),
        mu=dict.fromkeys(board, 1.0),
        position={**cliff_position, **board},
        tiers=tiers,
        cliff_bonus=cliff_bonus,
        players={
            pid: Player(player_id=pid, name=pid, position=pos, nfl_team="SEA")
            for pid, pos in board.items()
        },
        bye_week=dict.fromkeys(board, 5),
    )


def _full_board() -> dict[str, Position]:
    return {
        "a": Position.QB,
        "b": Position.RB,
        "c": Position.WR,
        "d": Position.TE,
        "e": Position.K,
        "f": Position.DST,
    }


def test_preflight_exits_nonzero_when_a_core_position_cannot_price_a_tier_cliff(
    preflight,
) -> None:
    """A dead alpha at RB is a real draft-night defect: 127 running backs with a 40-point gap at
    the top, and the engine cannot see it. Hours before the draft there is still time to fix it."""
    module, holder, tmp_path = preflight
    holder["context"] = _fake_context(_full_board(), cliffs={**_LIVE_BOARD, "RB": [0.0, 0.0]})
    assert module.main(["--data-dir", str(tmp_path)]) == 1


def test_preflight_tolerates_a_flat_cliff_at_a_punt_position(preflight) -> None:
    """K and DST are stream positions — `punt_guard` blocks them until R16/R17 precisely because
    which one you get barely matters. A flat kicker board is the truth, not a defect, so this
    reports and does NOT fail. The puntable set is read from `punt_guard.stream_round`, the same
    single source `recommend.py` uses, so making TE streamable stays a config change."""
    module, holder, tmp_path = preflight
    holder["context"] = _fake_context(
        _full_board(), cliffs={**_LIVE_BOARD, "K": [0.0, 0.0], "DST": [0.0, 0.0]}
    )
    assert module.main(["--data-dir", str(tmp_path)]) == 0


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


# --- Bye-week coverage (the guard that would have caught the two-vocabulary join) --------------


def _byeplayer(pid: str, team: str | None) -> Player:
    return Player(player_id=pid, name=pid, position=Position.RB, nfl_team=team)


def test_teams_missing_bye_weeks_is_empty_when_every_team_resolves() -> None:
    players = {"a": _byeplayer("a", "SEA"), "b": _byeplayer("b", "NOS")}
    assert teams_missing_bye_weeks(players, {"a": 5, "b": 11}) == []


def test_teams_missing_bye_weeks_names_the_unjoined_teams_once_each() -> None:
    """The live failure: `load_ff_playerids` says NOS/SFO, `load_schedules` says NO/SF, so 9 of
    32 teams joined to nothing — 152 of 510 board players — while 23 teams looked perfectly fine.
    Reported per TEAM, because that is the unit the bug actually has."""
    players = {
        "a": _byeplayer("a", "NOS"),
        "b": _byeplayer("b", "NOS"),  # same team, reported once
        "c": _byeplayer("c", "SFO"),
        "d": _byeplayer("d", "SEA"),  # this one resolved
    }

    assert teams_missing_bye_weeks(players, {"d": 13}) == ["NO", "SF"]


def test_teams_missing_bye_weeks_ignores_free_agents() -> None:
    """A free agent has no team, so he cannot have a bye. That is a fact, not a coverage gap —
    reporting it would make the guard fire forever and be trained away as noise."""
    players = {"a": _byeplayer("a", "FA"), "b": _byeplayer("b", None), "c": _byeplayer("c", "SEA")}

    assert teams_missing_bye_weeks(players, {"c": 13}) == []


# --- Tier 7: the fourth instance of this module's one question --------------------------------
#
# A roster SIZE read healthy for six tiers: 17 of 17 picks made, and three of the nine starting
# slots unfillable. Tier 6 walked a full 12x17 draft on the real board using the engine's own
# recommendations and got {RB:1, TE:13, WR:3} -- zero QB, zero K, zero DST -- identically under
# both best-available and need-based opponents. Same shape as cliff_bonus's 447 entries and the
# bye join's 1188: a count is not a diagnostic.


def _jaaffl_slots():
    from jaaffl.engine.optimize import expand_starting_slots
    from tests.engine_fixtures import jaaffl_settings

    return expand_starting_slots(jaaffl_settings())


def _positions_for(roster: list[str]) -> dict[str, Position]:
    return {pid: Position(pid.split("-")[0]) for pid in roster}


def test_unfillable_starting_slots_names_every_empty_required_slot() -> None:
    """The exact roster Tier 6 measured — and it is worse than Tier 6 recorded.

    Tier 6 reported "three of your nine starting slots would be empty" (QB, K, DST) and
    ``docs/owner-manual-todo.md`` §1b still said so. That counted missing POSITIONS and forgot
    the WR/RB flex, which draws from the same pool the three dedicated WR slots and the RB slot
    have already drained: 1 RB + 3 WR fill RB + WR×3 exactly, leaving the flex with nothing.
    **Four** of the nine starting slots are unfillable, not three.
    """
    roster = [f"TE-{i}" for i in range(13)] + ["WR-0", "WR-1", "WR-2", "RB-0"]
    assert unfillable_starting_slots(roster, _positions_for(roster), _jaaffl_slots()) == [
        "DST",
        "K",
        "QB",
        "WR/RB",
    ]


def test_a_legal_roster_reports_nothing() -> None:
    """9 starters covered, including the WR/RB flex, so the list is empty."""
    roster = ["QB-0", "RB-0", "WR-0", "WR-1", "WR-2", "RB-1", "TE-0", "K-0", "DST-0"]
    assert unfillable_starting_slots(roster, _positions_for(roster), _jaaffl_slots()) == []


def test_the_flex_is_honoured_rather_than_assumed() -> None:
    """A 4th WR fills the WR/RB flex; the same roster one WR short does not."""
    slots = _jaaffl_slots()
    full = ["QB-0", "RB-0", "WR-0", "WR-1", "WR-2", "WR-3", "TE-0", "K-0", "DST-0"]
    assert unfillable_starting_slots(full, _positions_for(full), slots) == []
    short = [pid for pid in full if pid != "WR-3"]
    assert unfillable_starting_slots(short, _positions_for(short), slots) == ["WR/RB"]
