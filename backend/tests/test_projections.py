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
from jaaffl.league.defaults import cbs_standard_scoring
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


class _FakeProvider(FantasyDataProvider):
    def __init__(self, name, caps, *, projections=None, rankings=None):
        self._name, self._caps = name, frozenset(caps)
        self._projections, self._rankings = projections or {}, rankings or {}

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


def test_build_projections_blends_cbs_stat_lines_and_ecr() -> None:
    rules, tiers, bonuses = cbs_standard_scoring()
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
