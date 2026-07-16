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
from jaaffl.providers.registry import build_registry


def fake_nflreadpy(monkeypatch: pytest.MonkeyPatch, **funcs) -> None:
    """Install a stub nflreadpy module so no network I/O happens in tests."""
    monkeypatch.setitem(sys.modules, "nflreadpy", types.SimpleNamespace(**funcs))


def test_default_registry_is_free_tier_only() -> None:
    settings = Settings(jaaffl_enable_fantasypros=False)
    assert [p.name for p in build_registry(settings)] == ["nflverse"]


def test_fantasypros_requires_flag_and_key() -> None:
    # Flag on but no key -> still disabled -> not in registry.
    settings = Settings(jaaffl_enable_fantasypros=True, fantasypros_api_key=None)
    assert [p.name for p in build_registry(settings)] == ["nflverse"]


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


def test_rankings_scaffolded_until_stage_4() -> None:
    # Capability declared (id-crosswalk wiring lands in roadmap stage 4).
    with pytest.raises(NotImplementedError):
        NflreadpyProvider().rankings(2026)


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
