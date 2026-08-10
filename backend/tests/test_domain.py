"""Exercise the implemented league logic against a representative 12-team PPR league."""

from jaaffl.domain import DraftState, LeagueSettings, Position, RosterSlot, ScoringRule
from jaaffl.league import league_points, starter_demand

FLEX = [Position.RB, Position.WR, Position.TE]


def sample_settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="L1",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=2),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=2),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1),
            RosterSlot(slot="FLEX", eligible_positions=FLEX, count=1),
            RosterSlot(slot="BENCH", eligible_positions=FLEX, count=6, starting=False),
        ],
        scoring=[
            ScoringRule(stat="passing_yards", points_per_unit=0.04),
            ScoringRule(stat="passing_td", points_per_unit=4.0),
            ScoringRule(stat="reception", points_per_unit=1.0),
            ScoringRule(stat="receiving_yards", points_per_unit=0.1),
            ScoringRule(stat="receiving_td", points_per_unit=6.0),
        ],
    )


def test_starter_demand_counts_dedicated_slots_only() -> None:
    demand = starter_demand(sample_settings())
    assert demand[Position.QB] == 12  # 1 * 12 teams
    assert demand[Position.RB] == 24  # 2 * 12
    assert demand[Position.WR] == 24
    assert demand[Position.TE] == 12
    # FLEX (multi-eligible) and BENCH (non-starting) are excluded from dedicated demand.
    assert sum(demand.values()) == 72


def test_league_points_ppr_receiving() -> None:
    stat_line = {"reception": 5, "receiving_yards": 80, "receiving_td": 1}
    pts = league_points(stat_line, sample_settings().scoring, Position.WR)
    assert pts == 5 * 1.0 + 80 * 0.1 + 1 * 6.0  # 19.0


def test_scoring_applies_to_filter() -> None:
    scoring = [ScoringRule(stat="reception", points_per_unit=1.0, applies_to=[Position.RB])]
    # A WR reception should not score when the rule is RB-only.
    assert league_points({"reception": 4}, scoring, Position.WR) == 0.0
    assert league_points({"reception": 4}, scoring, Position.RB) == 4.0


def test_draft_state_carries_the_rooms_entered_order() -> None:
    """config/league.json forbids inferring a snake order from team count, so the ONLY place the
    real order can come from is the room. It has to survive the fold, and the fold's output is a
    DraftState — so DraftState is where it lives."""
    state = DraftState(
        league_id="L1",
        current_overall_pick=1,
        draft_order=[str(i) for i in range(1, 13)],
    )
    assert state.draft_order == [str(i) for i in range(1, 13)]


def test_draft_state_order_defaults_to_none_and_is_never_synthesized() -> None:
    assert DraftState(league_id="L1", current_overall_pick=1).draft_order is None
