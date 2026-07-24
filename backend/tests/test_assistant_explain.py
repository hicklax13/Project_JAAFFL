"""explain_pick: turn a RecommendedPick's ScoreComponents into prose (Stage 7 [v1-lite]).

Deterministic — no OpenAI. This is the key-free core of the `explain_recommendation` tool: it
narrates the additive Score(p) decomposition (MLV, VONA urgency, risk, tier cliff) a human can read.
"""

from __future__ import annotations

from jaaffl.assistant.explain import explain_pick
from jaaffl.config import EngineParams
from jaaffl.domain import Position, RecommendedPick, ScoreComponents


def _components(**overrides) -> ScoreComponents:
    base = dict(
        mlv=32.4,
        vona=15.0,
        risk_penalty=2.1,
        cliff_bonus=2.0,
        sigma=40.0,
        floor=200.0,
        ceiling=300.0,
        replacement_baseline=118.0,
        modifiers={"bye_stack": -0.1},
    )
    base.update(overrides)
    return ScoreComponents(**base)


def _pick(components: ScoreComponents | None = None, **overrides) -> RecommendedPick:
    base = dict(
        player_id="p1",
        score=41.2,
        name="James Cook",
        position=Position.RB,
        nfl_team="BUF",
        tier=3,
        next_turn_availability=0.18,
        components=components if components is not None else _components(),
    )
    base.update(overrides)
    return RecommendedPick(**base)


def test_narrates_name_position_and_lineup_value() -> None:
    text = explain_pick(_pick(), EngineParams())
    assert "James Cook" in text
    assert "RB" in text
    assert "marginal" in text.lower() or "lineup value" in text.lower()
    assert "118" in text  # the replacement baseline it clears


def test_high_vona_reads_as_urgency_zero_vona_reads_as_can_wait() -> None:
    urgent = explain_pick(_pick(components=_components(vona=15.0)), EngineParams())
    patient = explain_pick(_pick(components=_components(vona=0.0)), EngineParams())
    assert "high urgency" in urgent.lower()
    assert "high urgency" not in patient.lower()
    assert "survive" in patient.lower() or "wait" in patient.lower()


def test_positive_cliff_bonus_calls_out_the_tier_cliff() -> None:
    text = explain_pick(_pick(components=_components(cliff_bonus=2.0)), EngineParams())
    assert "cliff" in text.lower() or "tier" in text.lower()
    flat = explain_pick(_pick(components=_components(cliff_bonus=0.0)), EngineParams())
    assert "cliff" not in flat.lower()


def test_mentions_the_risk_band_and_survival_probability() -> None:
    text = explain_pick(_pick(), EngineParams())
    assert "floor" in text.lower() and "ceiling" in text.lower()
    assert "18%" in text  # next_turn_availability 0.18
    assert "next pick" in text.lower()


def test_degrades_without_components() -> None:
    text = explain_pick(_pick(components=None), EngineParams())
    assert "James Cook" in text
    assert "41.2" in text  # still reports the score, no crash
