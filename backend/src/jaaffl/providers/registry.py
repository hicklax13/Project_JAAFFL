"""Build the active provider set from configuration.

The free ``nflverse`` provider is always present. Paid providers are appended only when
their config flag (and key) enables them, so the default registry is the $0 prototype tier.
Commercial providers (SportsDataIO, Sportradar) implement the same interface and slot in
here when added — see ``docs/legal-and-compliance.md`` before enabling any of them.
"""

from __future__ import annotations

from jaaffl.config import Settings, get_settings
from jaaffl.providers.base import Capability, FantasyDataProvider
from jaaffl.providers.fantasypros import FantasyProsProvider
from jaaffl.providers.nflverse import NflverseProvider


def build_registry(settings: Settings | None = None) -> list[FantasyDataProvider]:
    settings = settings or get_settings()
    providers: list[FantasyDataProvider] = [NflverseProvider()]

    fantasypros = FantasyProsProvider(settings)
    if fantasypros.enabled:
        providers.append(fantasypros)

    # TODO(commercial): SportsDataIO / Sportradar providers, gated by their own flags.
    return providers


def providers_supporting(
    capability: Capability,
    settings: Settings | None = None,
) -> list[FantasyDataProvider]:
    """Active providers that support ``capability``, in registry (preference) order."""
    return [p for p in build_registry(settings) if p.supports(capability)]
