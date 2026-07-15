"""Pluggable data providers (Stage 4).

The engine depends only on the :class:`FantasyDataProvider` protocol and the registry —
never on a concrete adapter — so free/personal and licensed/commercial sources are
interchangeable and paid feeds stay off by default. See ``docs/legal-and-compliance.md``.
"""

from jaaffl.providers.base import (
    Capability,
    CapabilityNotSupported,
    FantasyDataProvider,
    ProviderError,
)
from jaaffl.providers.registry import build_registry, providers_supporting

__all__ = [
    "Capability",
    "CapabilityNotSupported",
    "FantasyDataProvider",
    "ProviderError",
    "build_registry",
    "providers_supporting",
]
