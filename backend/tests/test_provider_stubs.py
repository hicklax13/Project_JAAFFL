"""Paid/commercial provider stubs (plan §4.6) — OFF by default, gated by flag AND key; every
declared capability method raises NotImplementedError until a plan is subscribed. Also pins the
widened FantasyPros ``adp()`` return type (dict[str, AdpRecord])."""

from __future__ import annotations

import pytest

from jaaffl.config import Settings
from jaaffl.providers.base import Capability, CapabilityNotSupported
from jaaffl.providers.fantasypros import FantasyProsProvider
from jaaffl.providers.sportradar import SportradarProvider
from jaaffl.providers.sportsdataio import SportsDataIOProvider


@pytest.mark.parametrize(
    ("cls", "flag", "key"),
    [
        (SportsDataIOProvider, "jaaffl_enable_sportsdataio", "sportsdataio_api_key"),
        (SportradarProvider, "jaaffl_enable_sportradar", "sportradar_api_key"),
    ],
)
def test_stub_enabled_requires_flag_and_key(cls: type, flag: str, key: str) -> None:
    assert cls(Settings()).enabled is False
    assert cls(Settings(**{flag: True})).enabled is False  # flag on, no key -> still off
    assert cls(Settings(**{flag: True, key: "k"})).enabled is True


def test_sportsdataio_identity_and_capabilities() -> None:
    p = SportsDataIOProvider(Settings(jaaffl_enable_sportsdataio=True, sportsdataio_api_key="k"))
    assert p.name == "sportsdataio"
    assert p.supports(Capability.PROJECTIONS)
    assert p.supports(Capability.INJURIES)
    assert not p.supports(Capability.ADP)


def test_sportradar_identity_and_capabilities() -> None:
    p = SportradarProvider(Settings(jaaffl_enable_sportradar=True, sportradar_api_key="k"))
    assert p.name == "sportradar"
    assert p.supports(Capability.PROJECTIONS)
    assert p.supports(Capability.INJURIES)
    assert not p.supports(Capability.ADP)


def test_stub_declared_methods_raise_notimplemented() -> None:
    sdio = SportsDataIOProvider(Settings(jaaffl_enable_sportsdataio=True, sportsdataio_api_key="k"))
    sr = SportradarProvider(Settings(jaaffl_enable_sportradar=True, sportradar_api_key="k"))
    with pytest.raises(NotImplementedError):
        sdio.projections(2026)
    with pytest.raises(NotImplementedError):
        sdio.injuries(2026)
    with pytest.raises(NotImplementedError):
        sr.projections(2026)
    with pytest.raises(NotImplementedError):
        sr.injuries(2026)


def test_stub_undeclared_capability_raises_capabilitynotsupported() -> None:
    sdio = SportsDataIOProvider(Settings(jaaffl_enable_sportsdataio=True, sportsdataio_api_key="k"))
    with pytest.raises(CapabilityNotSupported):
        sdio.adp(2026)


def test_fantasypros_adp_is_adprecord_typed() -> None:
    assert FantasyProsProvider.adp.__annotations__["return"] == "dict[str, AdpRecord]"
