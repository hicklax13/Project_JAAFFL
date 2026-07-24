"""CP-SAT optimize_roster (stretch, §3.9): the value-maximizing legal roster.

Reserved for the rest-of-season simulator's end-state (NEVER the per-pick hot path — that is
marginal_lineup_value). Needs the `engine-stretch` extra (ortools); the whole module skips when it
is absent, so CI's base `[dev,data,engine]` install stays green.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ortools")

from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import optimize_roster


def _settings() -> LeagueSettings:
    """A small roster that still exercises the interesting constraints: a dedicated RB + WR, a
    WR/RB flex, and a QB/RB/WR/TE bench."""
    return LeagueSettings(
        league_id="L",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=1, starting=True),
            RosterSlot(
                slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1, starting=True
            ),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=1,
                starting=False,
            ),
        ],
    )


_VALUES = {"rb1": 100.0, "rb2": 90.0, "wr1": 95.0, "wr2": 80.0, "qb1": 70.0, "k1": 50.0}
_POS = {"rb1": "RB", "rb2": "RB", "wr1": "WR", "wr2": "WR", "qb1": "QB", "k1": "K"}


def test_picks_the_value_maximizing_legal_roster() -> None:
    # RB→rb1, WR→wr1, flex→rb2 (90 > wr2 80), bench→wr2 (80 > qb1 70). K has no eligible slot.
    roster = set(optimize_roster(_VALUES, _POS, _settings()))
    assert roster == {"rb1", "wr1", "rb2", "wr2"}


def test_forces_already_rostered_players_in() -> None:
    # qb1 is forced into the bench, displacing the lower-value wr2.
    roster = set(optimize_roster(_VALUES, _POS, _settings(), already_rostered=["qb1"]))
    assert "qb1" in roster
    assert roster == {"rb1", "wr1", "rb2", "qb1"}


def test_leaves_a_slot_empty_rather_than_rostering_an_ineligible_player() -> None:
    # No WR in the pool: the WR slot goes empty; K is never rosterable (no eligible slot).
    values = {"rb1": 100.0, "rb2": 90.0, "rb3": 85.0, "k1": 50.0}
    pos = {"rb1": "RB", "rb2": "RB", "rb3": "RB", "k1": "K"}
    roster = set(optimize_roster(values, pos, _settings()))
    assert roster == {"rb1", "rb2", "rb3"}  # RB + flex + bench; WR slot empty, K excluded
    assert "k1" not in roster
