"""Bye weeks derived from the free nflverse schedule (`league/schedule.py`)."""

from __future__ import annotations

from jaaffl.domain import Position
from jaaffl.engine.recommend import recommend
from jaaffl.league.schedule import bye_weeks, player_bye_weeks
from tests.engine_fixtures import draft_state, engine_params, make_context, player


def test_bye_weeks_names_the_single_week_a_team_does_not_play() -> None:
    """Four teams over three weeks; AAA is the only one absent from a week."""
    games = [
        (1, "AAA", "BBB"),
        (1, "CCC", "DDD"),
        (2, "BBB", "CCC"),  # AAA and DDD both absent in week 2
        (3, "AAA", "CCC"),
        (3, "BBB", "DDD"),
    ]

    # AAA and DDD each miss exactly week 2; BBB and CCC play all three.
    assert bye_weeks(games) == {"AAA": 2, "DDD": 2}


def test_a_team_missing_several_weeks_gets_no_bye_rather_than_a_guess() -> None:
    """The absence rule fails SAFE. Playoff rows extend the span, so most teams go missing for
    many weeks — that must yield no bye at all, never a plausible wrong one on every chip."""
    games = [
        (1, "AAA", "BBB"),
        (2, "AAA", "BBB"),
        (3, "AAA", "BBB"),
        (4, "CCC", "DDD"),  # AAA/BBB absent for week 4; CCC/DDD absent for weeks 1-3
    ]

    byes = bye_weeks(games)

    assert byes == {"AAA": 4, "BBB": 4}  # CCC and DDD miss three weeks each -> omitted
    assert "CCC" not in byes
    assert "DDD" not in byes


def test_player_bye_weeks_joins_players_to_their_team_bye() -> None:
    """A player with no team, or on a team with no derived bye, is simply absent."""
    players = {
        "rb0": player("rb0", Position.RB, nfl_team="AAA"),
        "wr0": player("wr0", Position.WR, nfl_team="ZZZ"),  # team absent from the bye map
        "te0": player("te0", Position.TE, nfl_team=None),  # free agent / unknown team
    }

    assert player_bye_weeks(players, {"AAA": 7}) == {"rb0": 7}


def test_player_bye_weeks_reconciles_the_two_nflverse_team_vocabularies() -> None:
    """The player universe and the schedule are coded DIFFERENTLY, and the board mixes both.

    `load_ff_playerids` (DynastyProcess) spells teams `NOS`/`SFO`/`LAR`; `load_schedules` spells
    them `NO`/`SF`/`LA`. Measured on the live 2026 board, joining raw left **152 of 510** projected
    players with no bye — 9 of 32 teams, ~30%. Team defenses were unaffected because they come from
    `load_teams`, which already uses the schedule's vocabulary, so the two coexist in one dict.
    """
    players = {
        "saints": player("saints", Position.RB, nfl_team="NOS"),
        "niners": player("niners", Position.WR, nfl_team="SFO"),
        "rams": player("rams", Position.TE, nfl_team="LAR"),  # schedule says "LA", not "LAR"
        "hawks": player("hawks", Position.QB, nfl_team="SEA"),  # already identical in both
    }
    team_byes = {"NO": 11, "SF": 6, "LA": 8, "SEA": 13}  # as the SCHEDULE spells them

    assert player_bye_weeks(players, team_byes) == {
        "saints": 11,
        "niners": 6,
        "rams": 8,
        "hawks": 13,
    }


def test_recommend_renders_the_bye_week_the_overlay_asks_for() -> None:
    """The end of the chain: `RecommendedPick.bye_week` is what `overlay.ts` renders as `bye N`.

    It was declared on the contract, mirrored in Zod and rendered by the overlay, while NOTHING in
    the backend ever populated it — so the chip could never appear. Assert on the rendered value.
    """
    specs = [
        {"pid": f"rb{i}", "pos": Position.RB, "mu": 200.0 - i, "adp": i + 1.0} for i in range(6)
    ]
    specs += [
        {"pid": f"wr{i}", "pos": Position.WR, "mu": 190.0 - i, "adp": i + 7.0} for i in range(6)
    ]
    context = make_context(specs, params=engine_params(), bye_week={"rb0": 11})

    ranked = recommend(draft_state(1), context, engine_params()).ranked
    by_id = {pick.player_id: pick for pick in ranked}

    assert by_id["rb0"].bye_week == 11
    assert by_id["rb1"].bye_week is None  # no bye known -> stays absent, never fabricated
