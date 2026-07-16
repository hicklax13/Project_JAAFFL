"""Shared factory helpers for the Stage-5 engine tests.

Plain callables (matching the repo's ``sample_settings()`` helper style, not pytest fixtures) so
they compose freely across the many engine test modules. ``tests`` is an importable package
(``tests/__init__.py`` exists), so ``from tests.engine_fixtures import ...`` resolves in pytest's
prepend import mode.

The league here is THE immutable JAAFFL constitution (config/league.json): Snake · 12 teams ·
Standard (non-PPR) · QB1/RB1/WR3/(WR-RB flex)1/TE1/K1/DST1/Bench8. The flex is WR-or-RB only.
"""

from __future__ import annotations

from jaaffl.domain import LeagueSettings, Player, Position, RosterSlot

# Canonical ids are ``gsis:<gsis_id>`` (data/crosswalk.py) — mirror that scheme in fixtures.
FLEX_ELIGIBLE = [Position.WR, Position.RB]  # WR/RB only — NO TE/QB/K/DST (league rule).


def jaaffl_settings(league_id: str = "cbs-test") -> LeagueSettings:
    """The immutable JAAFFL roster as a ``LeagueSettings`` (scoring left to callers/defaults)."""
    return LeagueSettings(
        league_id=league_id,
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=3),
            RosterSlot(slot="WR/RB", eligible_positions=FLEX_ELIGIBLE, count=1),
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


def player(pid: str, position: Position, name: str | None = None, nfl_team: str = "FA") -> Player:
    return Player(player_id=pid, name=name or pid, position=position, nfl_team=nfl_team)
