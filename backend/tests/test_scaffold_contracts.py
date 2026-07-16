"""Phase 0 scaffold-change contracts (plan §1.4): tiered scoring (SC1) + ScoreComponents (SC3).

Bracket values below are illustrative CBS shapes — the real map is read live in Stage 2
(config/league.json ``scoring_note``); these tests pin the *structure*, not the values.
"""

import pytest
from pydantic import ValidationError

from jaaffl.domain import (
    LeagueSettings,
    Position,
    RecommendedPick,
    ScoreComponents,
    ScoringBonus,
    ScoringBracket,
    ScoringTier,
)


def dst_dual_tiers() -> list[ScoringTier]:
    """CBS 'Standard' DST scores on BOTH points-allowed AND yards-allowed brackets."""
    return [
        ScoringTier(
            stat="dst_points_allowed",
            applies_to=[Position.DST],
            brackets=[
                ScoringBracket(lower=0, upper=1, points=10),
                ScoringBracket(lower=1, upper=7, points=7),
                ScoringBracket(lower=35, upper=None, points=-4),
            ],
        ),
        ScoringTier(
            stat="dst_yards_allowed",
            applies_to=[Position.DST],
            brackets=[
                ScoringBracket(lower=0, upper=100, points=5),
                ScoringBracket(lower=400, upper=None, points=-3),
            ],
        ),
    ]


def k_50_plus_bonus() -> ScoringBonus:
    return ScoringBonus(stat="field_goal_distance", threshold=50, points=2, applies_to=[Position.K])


def full_components() -> ScoreComponents:
    return ScoreComponents(
        mlv=42.5,
        vona=-3.1,  # raw VONA may be negative (pre-kappa, pre-max-gate)
        risk_penalty=1.8,
        cliff_bonus=0.9,
        sigma=12.0,
        floor=110.0,
        ceiling=180.0,
        replacement_baseline=95.0,
        modifiers={"bye_stack": -1.5, "handcuff_synergy": 2.0, "sos": 0.5},
    )


def test_league_settings_new_scoring_fields_default_empty() -> None:
    settings = LeagueSettings(league_id="L1", team_count=12)
    assert settings.scoring_tiers == []
    assert settings.scoring_bonuses == []


def test_league_settings_round_trips_dst_dual_tiers_and_k_bonus() -> None:
    settings = LeagueSettings(
        league_id="L1",
        team_count=12,
        scoring_tiers=dst_dual_tiers(),
        scoring_bonuses=[k_50_plus_bonus()],
    )
    rebuilt = LeagueSettings.model_validate(settings.model_dump())
    assert rebuilt == settings
    assert {t.stat for t in rebuilt.scoring_tiers} == {
        "dst_points_allowed",
        "dst_yards_allowed",
    }
    assert rebuilt.scoring_bonuses[0].threshold == 50


def test_scoring_bracket_upper_none_is_open_ended() -> None:
    bracket = ScoringBracket(lower=35, points=-4)
    assert bracket.upper is None


def test_score_components_embed_on_recommended_pick() -> None:
    pick = RecommendedPick(player_id="p1", score=51.2, components=full_components())
    rebuilt = RecommendedPick.model_validate(pick.model_dump())
    assert rebuilt.components == full_components()
    assert rebuilt.components.modifiers["handcuff_synergy"] == 2.0


def test_recommended_pick_components_optional_default_none() -> None:
    pick = RecommendedPick(player_id="p1", score=1.0)
    assert pick.components is None


def test_score_components_sigma_must_be_nonnegative() -> None:
    with pytest.raises(ValidationError):
        ScoreComponents(
            mlv=0.0,
            vona=0.0,
            risk_penalty=0.0,
            cliff_bonus=0.0,
            sigma=-0.1,
            floor=0.0,
            ceiling=0.0,
            replacement_baseline=0.0,
        )
