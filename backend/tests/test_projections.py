"""Stage-0 projections (§3.1 + §3.10 R1/R4): μ/σ/floor/ceiling under the exact CBS map.

``assemble_projections`` is the pure blend/shrinkage/situation core (canonical-keyed points in →
PlayerProjection out); ``build_projections`` is the thin provider-gathering wrapper. Non-PPR is
enforced upstream (sources are already league points). z ≈ 1.2816 gives the 10th/90th band.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import Player, Position
from jaaffl.engine.projections import (
    Z_SCORE,
    SituationSignal,
    assemble_projections,
    build_projections,
)
from jaaffl.league.defaults import jaaffl_scoring
from jaaffl.league.replacement import replacement_values
from jaaffl.providers.base import Capability, FantasyDataProvider
from tests.engine_fixtures import engine_params, jaaffl_settings


def _assemble(source_points, position, **kw):
    return assemble_projections(source_points, position, engine_params(), jaaffl_settings(), **kw)


def test_mu_is_simple_average_of_sources() -> None:
    proj = _assemble(
        {"cbs": {"wr1": 200.0}, "ecr": {"wr1": 180.0}},
        {"wr1": Position.WR},
        sigma_floor={Position.WR: 10.0},
    )
    assert proj["wr1"].mu == pytest.approx(190.0)  # simple average, WR reliability = 1.0
    assert proj["wr1"].sources == {"cbs": 200.0, "ecr": 180.0}


def test_sigma_floors_at_position_residual_and_sets_10_90_band() -> None:
    proj = _assemble(
        {"cbs": {"rb1": 200.0}},  # single source → cross-source SD 0 → σ = floor
        {"rb1": Position.RB},
        sigma_floor={Position.RB: 30.0},
    )
    p = proj["rb1"]
    assert p.sigma == pytest.approx(30.0)
    assert p.floor == pytest.approx(p.mu - Z_SCORE * 30.0)
    assert p.ceiling == pytest.approx(p.mu + Z_SCORE * 30.0)


def test_reliability_shrinkage_pulls_kicker_toward_baseline() -> None:
    """R1: a K's projection is shrunk toward its replacement baseline by r_pos = 0.4."""
    source = {f"k{i}": 150.0 - 3.0 * i for i in range(20)}
    position = {f"k{i}": Position.K for i in range(20)}
    proj = _assemble({"cbs": source}, position, sigma_floor={Position.K: 5.0})
    # Anchor: the replacement baseline the engine itself computes for K.
    players = {pid: Player(player_id=pid, name=pid, position=Position.K) for pid in source}
    baseline = replacement_values(jaaffl_settings(), source, players, flex_split=(8, 4))[Position.K]
    assert proj["k0"].reliability == pytest.approx(0.4)
    assert proj["k0"].mu == pytest.approx(
        baseline + 0.4 * (150.0 - baseline)
    )  # pulled 60% toward base
    assert baseline < proj["k0"].mu < 150.0  # strictly shrunk, not collapsed


def test_mu_raw_is_the_blend_before_the_reliability_shrink() -> None:
    """``mu_raw`` is the same blend ``mu`` is derived from, BEFORE R1 pulls it toward replacement.

    The calibration harness needs it because :class:`~jaaffl.engine.simulate.ScoreAgent` re-applies
    R1 itself with the params under test — handed the already-shrunk ``mu`` it shrinks twice, which
    is exactly the defect Tier 11 fixes. Carried rather than inverted: inverting divides by
    ``reliability``, which a config may legitimately set to 0.
    """
    source = {f"k{i}": 150.0 - 3.0 * i for i in range(20)}
    position = {f"k{i}": Position.K for i in range(20)}
    proj = _assemble({"cbs": source}, position, sigma_floor={Position.K: 5.0})
    players = {pid: Player(player_id=pid, name=pid, position=Position.K) for pid in source}
    baseline = replacement_values(jaaffl_settings(), source, players, flex_split=(8, 4))[Position.K]

    assert proj["k0"].mu_raw == pytest.approx(150.0)  # the blend itself, untouched by R1
    assert proj["k0"].mu == pytest.approx(baseline + 0.4 * (proj["k0"].mu_raw - baseline))
    assert proj["k0"].mu_raw > proj["k0"].mu  # an above-replacement kicker is pulled DOWN


def test_mu_raw_equals_mu_wherever_reliability_is_one() -> None:
    """No shrink → the two views coincide, so nothing outside K/DST can observe a difference."""
    source = {f"wr{i}": 200.0 - 4.0 * i for i in range(50)}
    proj = _assemble(
        {"cbs": source}, {f"wr{i}": Position.WR for i in range(50)}, sigma_floor={Position.WR: 20.0}
    )
    for player in proj.values():
        assert player.reliability == pytest.approx(1.0)
        assert player.mu == pytest.approx(player.mu_raw)


def test_mu_raw_carries_the_situation_nudge_but_not_the_shrink() -> None:
    """R4 happens BEFORE R1, so the nudge belongs in ``mu_raw`` and the shrink does not.

    Pinned separately because the two refinements are applied in the same loop: a fix that captured
    the pre-NUDGE blend instead of the pre-SHRINK one would satisfy the kicker test above (K here
    has no situation signal) and still hand the harness the wrong number for every flagged player.
    """
    source = {f"k{i}": 150.0 - 3.0 * i for i in range(20)}
    position = {f"k{i}": Position.K for i in range(20)}
    sit = {"k0": SituationSignal(mu_delta_pct=0.10, flag="new team")}
    proj = _assemble({"cbs": source}, position, sigma_floor={Position.K: 5.0}, situation=sit)
    assert proj["k0"].mu_raw == pytest.approx(150.0 * 1.10)


def test_skill_position_projection_is_not_shrunk() -> None:
    source = {f"wr{i}": 200.0 - 4.0 * i for i in range(50)}
    proj = _assemble(
        {"cbs": source}, {f"wr{i}": Position.WR for i in range(50)}, sigma_floor={Position.WR: 20.0}
    )
    assert proj["wr0"].reliability == pytest.approx(1.0)
    assert proj["wr0"].mu == pytest.approx(200.0)  # unchanged (r = 1.0)


def test_situation_mu_nudge_is_capped_and_widens_sigma() -> None:
    """R4: a requested +50% team-change nudge clamps to caps.mu_refinement_pct (15%); σ widens."""
    sit = {"wr_moved": SituationSignal(mu_delta_pct=0.5, sigma_multiplier=1.25, flag="new team")}
    proj = _assemble(
        {"cbs": {"wr_moved": 180.0}},
        {"wr_moved": Position.WR},
        sigma_floor={Position.WR: 20.0},
        situation=sit,
    )
    assert proj["wr_moved"].mu == pytest.approx(180.0 * 1.15)  # +15% cap, not +50%
    assert proj["wr_moved"].sigma == pytest.approx(20.0 * 1.25)  # widened
    assert proj["wr_moved"].situation_flag == "new team"


def test_sigma_prior_overrides_the_flat_position_floor() -> None:
    """A measured per-player σ beats the per-position placeholder — that is the whole point of
    deriving σ from history rather than a constant."""
    proj = _assemble(
        {"cbs": {"rb1": 200.0, "rb2": 200.0}},
        {"rb1": Position.RB, "rb2": Position.RB},
        sigma_floor={Position.RB: 50.0},
        sigma_prior={"rb1": 31.0},  # rb2 has no measurement → keeps the floor
    )
    assert proj["rb1"].sigma == pytest.approx(31.0)
    assert proj["rb2"].sigma == pytest.approx(50.0)


def test_cross_source_disagreement_still_beats_a_lower_sigma_prior() -> None:
    """σ is a floor stack: two sources that disagree by more than the prior widen the band."""
    proj = _assemble(
        {"xep": {"rb1": 100.0}, "ecr": {"rb1": 300.0}},
        {"rb1": Position.RB},
        sigma_floor={Position.RB: 50.0},
        sigma_prior={"rb1": 31.0},
    )
    assert proj["rb1"].sigma == pytest.approx(100.0)  # pstdev([100, 300]) = 100


class _FakeProvider(FantasyDataProvider):
    def __init__(self, name, caps, *, projections=None, rankings=None, expected_points=None):
        self._name, self._caps = name, frozenset(caps)
        self._projections, self._rankings = projections or {}, rankings or {}
        self._expected_points = expected_points
        self.expected_points_seasons: list[int] = []

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def projections(self, season, week=None):
        return self._projections

    def rankings(self, season, week=None):
        return self._rankings

    def expected_points(self, season, week=None):
        self.expected_points_seasons.append(season)
        if isinstance(self._expected_points, Exception):
            raise self._expected_points
        return self._expected_points


def test_build_projections_blends_cbs_stat_lines_and_ecr() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    settings = jaaffl_settings()
    settings = settings.model_copy(
        update={"scoring": rules, "scoring_tiers": tiers, "scoring_bonuses": bonuses}
    )
    providers = [
        _FakeProvider(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={"wr1": {"receiving_yards": 1000, "receiving_td": 8}},
        ),
        _FakeProvider("nflverse", {Capability.RANKINGS}, rankings={"wr1": 5.0}),
    ]
    players = {"wr1": Player(player_id="wr1", name="wr1", position=Position.WR)}
    proj = build_projections(
        settings,
        providers,
        engine_params(),
        2026,
        players=players,
        sigma_floor={Position.WR: 20.0},
        ecr_to_points=lambda pos, e: 200.0 - e,
    )
    # CBS: 1000·0.1 + 8·6 = 148 (Rec = 0); ECR: 200 − 5 = 195 → μ = 171.5.
    assert proj["wr1"].sources == {"cbs": pytest.approx(148.0), "ecr": pytest.approx(195.0)}
    assert proj["wr1"].mu == pytest.approx(171.5)
    assert proj["wr1"].stat_line == {"receiving_yards": 1000, "receiving_td": 8}


# --- xEP as a live blend source (§3.1 Capability.EXPECTED_POINTS) --------------------------


def _jaaffl_scored_settings():
    rules, tiers, bonuses = jaaffl_scoring()
    return jaaffl_settings().model_copy(
        update={"scoring": rules, "scoring_tiers": tiers, "scoring_bonuses": bonuses}
    )


def _xep_rows(gsis: str, weeks: int = 17, **stats: float) -> list[dict]:
    return [{"player_id": gsis, "week": float(w), **stats} for w in range(1, weeks + 1)]


def test_build_projections_blends_real_xep_points_with_ecr() -> None:
    """The core fix: μ stops being a linear function of expert rank because a REAL projection
    source now sits in the blend."""
    rows = _xep_rows("00-0039139", rush_yards_gained_exp=60.0, rush_touchdown_exp=0.5)
    providers = [
        _FakeProvider("nflverse", {Capability.RANKINGS, Capability.EXPECTED_POINTS},
                      rankings={"gsis:00-0039139": 5.0}, expected_points=rows),
    ]  # fmt: skip
    players = {
        "gsis:00-0039139": Player(
            player_id="gsis:00-0039139", name="Jahmyr Gibbs", position=Position.RB
        )
    }
    proj = build_projections(
        _jaaffl_scored_settings(),
        providers,
        engine_params(),
        2026,
        players=players,
        sigma_floor={Position.RB: 61.0},
        ecr_to_points=lambda pos, e: 300.0 - e,
    )
    # xEP: 1020 rush yds × 0.1 + 8.5 rush TD × 6 = 153.0 ; ECR: 300 − 5 = 295.
    p = proj["gsis:00-0039139"]
    assert p.sources == {"xep": pytest.approx(153.0), "ecr": pytest.approx(295.0)}
    assert p.mu == pytest.approx(224.0)
    assert p.stat_line["rushing_yards"] == pytest.approx(1020.0)


def test_expected_points_is_pulled_for_the_last_completed_season_not_the_draft_season() -> None:
    """VERIFIED: nflreadpy raises ``ValueError: Season must be between 2006 and 2025`` for the
    2026 draft season. xEP is retrospective, so the blend must ask for season − 1."""
    provider = _FakeProvider(
        "nflverse", {Capability.EXPECTED_POINTS},
        expected_points=_xep_rows("00-0039139", rush_yards_gained_exp=60.0),
    )  # fmt: skip
    players = {
        "gsis:00-0039139": Player(player_id="gsis:00-0039139", name="g", position=Position.RB)
    }
    build_projections(
        _jaaffl_scored_settings(), [provider], engine_params(), 2026,
        players=players, sigma_floor={Position.RB: 61.0},
    )  # fmt: skip
    assert provider.expected_points_seasons == [2025]


def test_an_unavailable_xep_pull_degrades_to_ecr_only_rather_than_failing() -> None:
    """Honest degradation: the player keeps a projection, and ``sources`` shows it is ECR-only —
    it never silently pretends a real projection exists."""
    provider = _FakeProvider(
        "nflverse", {Capability.RANKINGS, Capability.EXPECTED_POINTS},
        rankings={"gsis:00-0039139": 5.0},
        expected_points=ValueError("Season must be between 2006 and 2025"),
    )  # fmt: skip
    players = {
        "gsis:00-0039139": Player(player_id="gsis:00-0039139", name="g", position=Position.RB)
    }
    proj = build_projections(
        _jaaffl_scored_settings(), [provider], engine_params(), 2026,
        players=players, sigma_floor={Position.RB: 61.0},
        ecr_to_points=lambda pos, e: 300.0 - e,
    )  # fmt: skip
    assert provider.expected_points_seasons == [2025]  # it really was attempted, then degraded
    assert proj["gsis:00-0039139"].sources == {"ecr": pytest.approx(295.0)}
    assert proj["gsis:00-0039139"].sigma == pytest.approx(61.0)  # falls back to the position floor


def test_a_player_without_xep_coverage_is_marked_ecr_only() -> None:
    """K/DST have no ffopportunity rows (verified: 1 stray K row, zero DST). They must degrade
    visibly, not be handed a fabricated projection."""
    providers = [
        _FakeProvider("nflverse", {Capability.RANKINGS, Capability.EXPECTED_POINTS},
                      rankings={"gsis:rb": 5.0, "gsis:k": 90.0},
                      expected_points=_xep_rows("rb", rush_yards_gained_exp=60.0)),
    ]  # fmt: skip
    players = {
        "gsis:rb": Player(player_id="gsis:rb", name="rb", position=Position.RB),
        "gsis:k": Player(player_id="gsis:k", name="k", position=Position.K),
    }
    proj = build_projections(
        _jaaffl_scored_settings(), providers, engine_params(), 2026,
        players=players, sigma_floor={Position.RB: 61.0, Position.K: 20.0},
        ecr_to_points=lambda pos, e: 300.0 - e,
    )  # fmt: skip
    assert set(proj["gsis:rb"].sources) == {"xep", "ecr"}
    assert set(proj["gsis:k"].sources) == {"ecr"}


def test_xep_sigma_reaches_the_projection_as_a_real_per_player_band() -> None:
    """End-to-end: the measured weekly residual, not the flat floor, sets the 10/90 band."""
    steady = _xep_rows("steady", rush_yards_gained_exp=100.0, rush_yards_gained=100.0)
    volatile = [
        {"player_id": "volatile", "week": float(w), "rush_yards_gained_exp": 100.0,
         "rush_yards_gained": 100.0 + 400.0 * (w % 2)}
        for w in range(1, 18)
    ]  # fmt: skip
    providers = [
        _FakeProvider("nflverse", {Capability.EXPECTED_POINTS}, expected_points=steady + volatile)
    ]
    players = {
        "gsis:steady": Player(player_id="gsis:steady", name="s", position=Position.RB),
        "gsis:volatile": Player(player_id="gsis:volatile", name="v", position=Position.RB),
    }
    proj = build_projections(
        _jaaffl_scored_settings(), providers, engine_params(), 2026,
        players=players, sigma_floor={Position.RB: 61.0},
    )  # fmt: skip
    assert proj["gsis:steady"].mu == pytest.approx(proj["gsis:volatile"].mu)
    assert proj["gsis:volatile"].sigma > proj["gsis:steady"].sigma
    assert proj["gsis:steady"].sigma != pytest.approx(61.0)  # no longer the flat constant
