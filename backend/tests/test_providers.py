"""The default registry is the free ($0) tier; capability gating works."""

import pytest

from jaaffl.config import Settings
from jaaffl.providers.base import Capability, CapabilityNotSupported
from jaaffl.providers.nflverse import NflverseProvider
from jaaffl.providers.registry import build_registry


def test_default_registry_is_free_tier_only() -> None:
    settings = Settings(jaaffl_enable_fantasypros=False)
    assert [p.name for p in build_registry(settings)] == ["nflverse"]


def test_fantasypros_requires_flag_and_key() -> None:
    # Flag on but no key -> still disabled -> not in registry.
    settings = Settings(jaaffl_enable_fantasypros=True, fantasypros_api_key=None)
    assert [p.name for p in build_registry(settings)] == ["nflverse"]


def test_nflverse_capabilities() -> None:
    provider = NflverseProvider()
    assert provider.supports(Capability.HISTORICAL_STATS)
    assert not provider.supports(Capability.PROJECTIONS)


def test_unsupported_capability_raises() -> None:
    with pytest.raises(CapabilityNotSupported):
        NflverseProvider().projections(2024)
