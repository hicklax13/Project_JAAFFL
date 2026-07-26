"""The default registry is the free ($0) tier; capability gating works.

SC2 (plan §1.4.2/§4.3): the nflverse provider is nflreadpy-backed (Polars) — the class is
``NflreadpyProvider`` but its stable ``name`` key stays ``"nflverse"``.
"""

import sys
import types

import pytest

from jaaffl.config import Settings
from jaaffl.providers.base import Capability, CapabilityNotSupported
from jaaffl.providers.nflverse import NflreadpyProvider
from jaaffl.providers.registry import build_registry, providers_supporting

# The $0 default tier, in preference order (registry order IS preference order).
FREE_TIER = ["nflverse", "ffc", "cbs_onpage"]


def fake_nflreadpy(monkeypatch: pytest.MonkeyPatch, **funcs) -> None:
    """Install a stub nflreadpy module so no network I/O happens in tests.

    ``load_teams`` defaults to an EMPTY frame (with the real column names) because
    ``NflreadpyProvider.players`` reads two tables — ff_playerids for people and load_teams for
    team defenses. Tests about playerid mapping therefore need no teams fixture and see zero
    DSTs; tests that exercise defenses pass their own ``load_teams``. The default is a test-only
    convenience: production never tolerates a missing table, it raises.
    """
    import polars as pl

    funcs.setdefault(
        "load_teams",
        lambda: pl.DataFrame(schema={"team_abbr": pl.String, "team_name": pl.String}),
    )
    monkeypatch.setitem(sys.modules, "nflreadpy", types.SimpleNamespace(**funcs))


def test_default_registry_is_the_free_tier() -> None:
    settings = Settings(jaaffl_enable_fantasypros=False)
    assert [p.name for p in build_registry(settings)] == FREE_TIER


def test_gated_provider_requires_flag_and_key() -> None:
    # Flag on but no key -> still disabled -> only the free tier.
    assert [p.name for p in build_registry(Settings(jaaffl_enable_fantasypros=True))] == FREE_TIER
    assert [p.name for p in build_registry(Settings(jaaffl_enable_sportsdataio=True))] == FREE_TIER


def test_ffc_kill_switch_removes_it_from_the_free_tier() -> None:
    # jaaffl_enable_ffc=false must actually disable FFC (drop it from the registry + ADP support).
    off = Settings(jaaffl_enable_ffc=False)
    assert [p.name for p in build_registry(off)] == ["nflverse", "cbs_onpage"]
    assert providers_supporting(Capability.ADP, off) == []


def test_enabled_gated_provider_appends_after_free_tier() -> None:
    settings = Settings(jaaffl_enable_fantasypros=True, fantasypros_api_key="k")
    assert [p.name for p in build_registry(settings)] == [*FREE_TIER, "fantasypros"]


def test_multiple_gated_providers_append_in_declared_order() -> None:
    settings = Settings(
        jaaffl_enable_sportsdataio=True,
        sportsdataio_api_key="k",
        jaaffl_enable_sportradar=True,
        sportradar_api_key="k",
    )
    assert [p.name for p in build_registry(settings)] == [*FREE_TIER, "sportsdataio", "sportradar"]


def test_providers_supporting_free_tier_preference_order() -> None:
    free = Settings(jaaffl_enable_fantasypros=False)
    assert [p.name for p in providers_supporting(Capability.ADP, free)] == ["ffc"]
    assert [p.name for p in providers_supporting(Capability.RANKINGS, free)] == [
        "nflverse",
        "cbs_onpage",
    ]
    assert [p.name for p in providers_supporting(Capability.PROJECTIONS, free)] == ["cbs_onpage"]
    assert [p.name for p in providers_supporting(Capability.INJURIES, free)] == ["cbs_onpage"]
    assert [p.name for p in providers_supporting(Capability.HISTORICAL_STATS, free)] == ["nflverse"]
    assert [p.name for p in providers_supporting(Capability.EXPECTED_POINTS, free)] == ["nflverse"]


def test_enabled_fantasypros_appends_as_lower_preference_supplier() -> None:
    settings = Settings(jaaffl_enable_fantasypros=True, fantasypros_api_key="k")
    assert [p.name for p in providers_supporting(Capability.ADP, settings)] == [
        "ffc",
        "fantasypros",
    ]
    assert [p.name for p in providers_supporting(Capability.INJURIES, settings)] == [
        "cbs_onpage",
        "fantasypros",
    ]


def test_build_registry_accepts_injected_warehouse_and_crosswalk(tmp_path) -> None:
    from jaaffl.data import Crosswalk, Warehouse

    Warehouse(tmp_path).init()
    reg = build_registry(
        Settings(jaaffl_data_dir=tmp_path),
        warehouse=Warehouse(tmp_path),
        crosswalk=Crosswalk(tmp_path / "app.sqlite"),
    )
    assert [p.name for p in reg] == FREE_TIER


def test_nflreadpy_provider_keeps_stable_name_key() -> None:
    assert NflreadpyProvider().name == "nflverse"


def test_nflreadpy_capabilities() -> None:
    provider = NflreadpyProvider()
    assert provider.supports(Capability.HISTORICAL_STATS)
    assert provider.supports(Capability.RANKINGS)
    assert provider.supports(Capability.EXPECTED_POINTS)
    assert not provider.supports(Capability.PROJECTIONS)
    # nflverse's injury source lapsed after 2024 — injuries come from CBS on-page (§4.5).
    assert not provider.supports(Capability.INJURIES)


def test_unsupported_capability_raises() -> None:
    with pytest.raises(CapabilityNotSupported):
        NflreadpyProvider().projections(2026)


@pytest.mark.parametrize(
    ("method", "loader"),
    [("historical_stats", "load_player_stats"), ("expected_points", "load_ff_opportunity")],
)
def test_polars_methods_delegate_to_nflreadpy(
    monkeypatch: pytest.MonkeyPatch, method: str, loader: str
) -> None:
    calls: dict = {}

    def fake_loader(seasons):
        calls["seasons"] = seasons
        return "FRAME"

    fake_nflreadpy(monkeypatch, **{loader: fake_loader})
    assert getattr(NflreadpyProvider(), method)(2025) == "FRAME"
    assert calls["seasons"] == [2025]


def test_installed_nflreadpy_exposes_the_planned_api() -> None:
    """Pins the plan's [VERIFY] items against the real package when the data extra is
    installed (always in CI): the loader fns SC2 delegates to, plus the stage-3/4
    id-crosswalk functions (plan §4.3)."""
    nflreadpy = pytest.importorskip("nflreadpy")
    pytest.importorskip("polars")
    for fn in (
        "load_player_stats",
        "load_ff_opportunity",
        "load_ff_rankings",
        "load_ff_playerids",
        "load_players",
    ):
        assert callable(getattr(nflreadpy, fn, None)), f"nflreadpy.{fn} missing"


def test_provider_boundary_is_polars_typed() -> None:
    # SC2: the provider boundary returns polars frames (annotation pins the contract).
    from jaaffl.providers.base import FantasyDataProvider

    assert FantasyDataProvider.historical_stats.__annotations__["return"] == "pl.DataFrame"
    assert FantasyDataProvider.expected_points.__annotations__["return"] == "pl.DataFrame"
