"""dispatch: execute the deterministic (key-free) assistant tools over an injected context.

explain_recommendation + league_summary run with no OpenAI and no network — the data comes from
an injected AssistantContext (the API layer wires it to app.state; tests pass fakes). The two
LLM/external tools (query_warehouse, player_news) stay unwired until the Responses API loop.
"""

from __future__ import annotations

import pytest

from jaaffl.assistant.tools import AssistantContext, dispatch
from jaaffl.domain import (
    DraftPick,
    DraftState,
    LeagueSettings,
    Position,
    Recommendation,
    RecommendedPick,
    RosterSlot,
    ScoreComponents,
)


def _rec() -> Recommendation:
    return Recommendation(
        league_id="L1",
        as_of_overall_pick=5,
        ranked=[
            RecommendedPick(
                player_id="p1",
                score=41.2,
                name="James Cook",
                position=Position.RB,
                components=ScoreComponents(
                    mlv=32.4,
                    vona=15.0,
                    risk_penalty=2.1,
                    cliff_bonus=2.0,
                    sigma=40.0,
                    floor=200.0,
                    ceiling=300.0,
                    replacement_baseline=118.0,
                ),
            )
        ],
    )


def _ctx(*, rec=None, league=None, state=None) -> AssistantContext:
    return AssistantContext(
        recommendation=lambda _lid: rec,
        league_settings=(lambda _lid: league) if league is not None else None,
        draft_state=(lambda _lid: state) if state is not None else None,
    )


def test_explain_recommendation_returns_prose_for_the_named_player() -> None:
    result = dispatch(
        "explain_recommendation", {"league_id": "L1", "player_id": "p1"}, context=_ctx(rec=_rec())
    )
    assert result["player_id"] == "p1"
    assert "James Cook" in result["explanation"]


def test_explain_recommendation_reports_an_unknown_player() -> None:
    result = dispatch(
        "explain_recommendation",
        {"league_id": "L1", "player_id": "ghost"},
        context=_ctx(rec=_rec()),
    )
    assert "error" in result


def test_explain_recommendation_reports_no_recommendation_yet() -> None:
    result = dispatch(
        "explain_recommendation", {"league_id": "L1", "player_id": "p1"}, context=_ctx(rec=None)
    )
    assert "error" in result


def test_league_summary_folds_settings_and_live_state() -> None:
    league = LeagueSettings(
        league_id="L1",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True)
        ],
    )
    state = DraftState(
        league_id="L1",
        current_overall_pick=6,
        picks=[DraftPick(overall=1, round=1, pick_in_round=1, team_id="T1")],
    )
    result = dispatch(
        "league_summary", {"league_id": "L1"}, context=_ctx(league=league, state=state)
    )
    assert result["settings"]["team_count"] == 12
    assert result["draft"]["current_overall_pick"] == 6
    assert result["draft"]["picks_made"] == 1


def test_unwired_tools_raise_not_implemented() -> None:
    for name in ("query_warehouse", "player_news"):
        with pytest.raises(NotImplementedError):
            dispatch(name, {}, context=_ctx(rec=_rec()))


def test_unknown_tool_raises_value_error() -> None:
    with pytest.raises(ValueError):
        dispatch("not_a_tool", {}, context=_ctx(rec=_rec()))
