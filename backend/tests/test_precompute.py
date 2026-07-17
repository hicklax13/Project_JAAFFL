"""Pre-draft precompute bridge (§3.7 / §4.7): the $0 registry → a RecommendationEngine context.

All provider I/O + network live in the injectable factory; the engine hot path then reads the
cached context. This whole module is exercised with FAKE providers + a fake player universe — no
network — so it proves the 503→200 bridge end-to-end offline.
"""

from __future__ import annotations

import pytest

from jaaffl.config import Settings
from jaaffl.data.warehouse import Warehouse
from jaaffl.domain import Player, Position
from jaaffl.engine.precompute import build_registry_context_source
from jaaffl.engine.service import RecommendationEngine
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider
from tests.engine_fixtures import draft_state


class _CountingFake(FantasyDataProvider):
    """A fake provider that counts capability calls so a test can prove the hot path is
    provider-free (the count must not move once the context is cached)."""

    def __init__(self, name, caps, *, adp=None, rankings=None, projections=None, players=None):
        self._name, self._caps = name, frozenset(caps)
        self._adp, self._rankings = adp or {}, rankings or {}
        self._projections, self._players = projections or {}, players or []
        self.calls = 0

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def players(self, season):
        self.calls += 1
        return list(self._players)

    def adp(self, season):
        self.calls += 1
        return self._adp

    def rankings(self, season, week=None):
        self.calls += 1
        return self._rankings

    def projections(self, season, week=None):
        self.calls += 1
        return self._projections


def _universe():
    return [
        Player(player_id="rb0", name="rb0", position=Position.RB),
        Player(player_id="rb1", name="rb1", position=Position.RB),
        Player(player_id="wr0", name="wr0", position=Position.WR),
        Player(player_id="wr1", name="wr1", position=Position.WR),
        Player(player_id="te0", name="te0", position=Position.TE),
    ]


def _providers():
    """The $0 free-tier shape (nflverse HISTORICAL_STATS+RANKINGS, ffc ADP, cbs_onpage
    PROJECTIONS) — all fakes, no network."""
    return [
        _CountingFake(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS},
            rankings={"rb0": 1.0, "rb1": 5.0, "wr0": 2.0, "wr1": 6.0, "te0": 20.0},
            players=_universe(),
        ),
        _CountingFake(
            "ffc",
            {Capability.ADP},
            adp={"rb0": AdpRecord(adp=1.0, stdev=3.0), "wr0": AdpRecord(adp=2.0, stdev=None)},
        ),
        _CountingFake(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={
                "rb0": {"rushing_yards": 1500, "rushing_td": 12},
                "rb1": {"rushing_yards": 900, "rushing_td": 6},
                "wr0": {"receiving_yards": 1200, "receiving_td": 9},
                "wr1": {"receiving_yards": 800, "receiving_td": 5},
                "te0": {"receiving_yards": 700, "receiving_td": 5},
            },
        ),
    ]


def _source(providers, tmp_path):
    return build_registry_context_source(
        Settings(jaaffl_data_dir=tmp_path / "data"),
        warehouse=Warehouse(tmp_path / "data"),
        providers=providers,
    )


def test_factory_builds_a_valid_context_from_fake_providers(tmp_path) -> None:
    ctx = _source(_providers(), tmp_path)("cbs-local")
    assert ctx is not None
    # The immutable constitution roster, reproduced verbatim (draft_order NEVER inferred → None).
    assert ctx.settings.league_id == "cbs-local"
    assert ctx.settings.team_count == 12
    assert ctx.settings.draft_type == "snake"
    assert ctx.settings.draft_order is None
    assert len(ctx.starting_slots) == 9
    # Joined by canonical id: CBS points (1500·0.1 + 12·6 = 222) blended with ECR (300 − 1 = 299).
    assert ctx.projections["rb0"].sources["cbs"] == pytest.approx(222.0)
    assert ctx.mu["rb0"] == pytest.approx((222.0 + 299.0) / 2)
    assert ctx.adp_mean["rb0"] == pytest.approx(1.0)
    assert ctx.adp_sd["rb0"] == pytest.approx(3.0)  # FFC stdev
    assert ctx.adp_sd["wr0"] == pytest.approx(12.0)  # None stdev → wide default


def test_factory_returns_none_when_universe_is_empty(tmp_path) -> None:
    """No player universe → None so /recommendation still 503s gracefully (never a 500)."""
    providers = [_CountingFake("nflverse", {Capability.HISTORICAL_STATS}, players=[])]
    assert _source(providers, tmp_path)("cbs-local") is None


def test_engine_using_source_turns_state_into_a_real_recommendation(tmp_path) -> None:
    engine = RecommendationEngine(context_source=_source(_providers(), tmp_path))
    state = draft_state(1, league_id="cbs-local", my_team_id="t0")
    rec = engine.recommend(state, limit=3)
    assert rec is not None
    assert 1 <= len(rec.ranked) <= 3
    top = rec.ranked[0]
    assert top.components is not None
    c = top.components
    kappa = engine.context_for("cbs-local").params.kappa
    reconstructed = (
        c.mlv
        + kappa * max(0.0, c.vona)
        - c.risk_penalty
        + c.cliff_bonus
        + sum(c.modifiers.values())
    )
    assert top.score == pytest.approx(reconstructed)


def test_hot_path_touches_no_provider_once_the_context_is_cached(tmp_path) -> None:
    """§4.7: precompute is the only provider I/O — a second recompute reads the cache with no
    provider calls."""
    providers = _providers()
    engine = RecommendationEngine(context_source=_source(providers, tmp_path))
    state = draft_state(1, league_id="cbs-local", my_team_id="t0")
    engine.recommend(state)  # builds + caches the context (providers hit here)
    calls_after_build = sum(p.calls for p in providers)
    assert calls_after_build > 0
    engine.recommend(state)  # cached → no provider touched
    assert sum(p.calls for p in providers) == calls_after_build


def test_registry_player_loader_uses_real_players_method(monkeypatch, tmp_path) -> None:
    """The 503→universe flip at the loader seam: the real NflreadpyProvider.players() (fake
    nflreadpy) yields a real universe dict through _registry_player_loader — where it used to
    swallow NotImplementedError to {} (the keystone before players() existed)."""
    import polars as pl

    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import _registry_player_loader
    from jaaffl.providers.nflverse import NflreadpyProvider
    from tests.test_providers import fake_nflreadpy

    Warehouse(tmp_path).init()
    row = {
        "gsis_id": "00-0034796", "cbs_id": "2181292", "pfr_id": "LambCe00", "sleeper_id": "6786",
        "espn_id": "4241389", "yahoo_id": "32692", "fantasypros_id": "17246",
        "name": "CeeDee Lamb", "position": "WR", "team": "DAL",
    }
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: pl.DataFrame([row]))
    provider = NflreadpyProvider(crosswalk=Crosswalk(tmp_path / "app.sqlite"))
    universe = _registry_player_loader([provider])(2026)
    assert set(universe) == {"gsis:00-0034796"}
    assert universe["gsis:00-0034796"].name == "CeeDee Lamb"
