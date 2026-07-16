"""Build the active provider set from configuration.

Registry order IS preference order. The three free adapters (nflverse + ffc + cbs_onpage) are
always present and, with no keys, ARE the $0 prototype tier. Paid providers append AFTER the free
tier only when their config flag AND key enable them, so enabling one adds a lower-preference
supplier for its capabilities (the precompute layer may still prefer/merge it for freshness —
e.g. FantasyPros injuries, §4.6). See ``docs/legal-and-compliance.md`` before enabling any.

FFC and CBS need a ``Crosswalk`` (source-id / name+team+pos -> canonical id) and CBS needs a
``Warehouse`` reader, so ``build_registry`` gains injected dependencies with lazy defaults.
"""

from __future__ import annotations

from jaaffl.config import Settings, get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.providers.base import Capability, FantasyDataProvider
from jaaffl.providers.cbs_onpage import CbsOnPageProvider
from jaaffl.providers.fantasypros import FantasyProsProvider
from jaaffl.providers.ffc import FantasyFootballCalculatorProvider
from jaaffl.providers.nflverse import NflreadpyProvider
from jaaffl.providers.sportradar import SportradarProvider
from jaaffl.providers.sportsdataio import SportsDataIOProvider


def build_registry(
    settings: Settings | None = None,
    *,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
) -> list[FantasyDataProvider]:
    settings = settings or get_settings()
    warehouse = warehouse or Warehouse()
    crosswalk = crosswalk or Crosswalk()

    providers: list[FantasyDataProvider] = [
        NflreadpyProvider(crosswalk=crosswalk),  # free $0 base (history, ECR, xEP)
    ]
    ffc = FantasyFootballCalculatorProvider(settings, crosswalk)  # free $0 ADP
    if ffc.enabled:  # jaaffl_enable_ffc kill-switch (default on)
        providers.append(ffc)
    providers.append(CbsOnPageProvider(warehouse, crosswalk))  # free $0 CBS snapshot
    for gated in (
        FantasyProsProvider(settings),
        SportsDataIOProvider(settings),
        SportradarProvider(settings),
    ):
        if gated.enabled:  # enabled == flag AND key
            providers.append(gated)
    return providers


def providers_supporting(
    capability: Capability,
    settings: Settings | None = None,
    *,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
) -> list[FantasyDataProvider]:
    """Active providers supporting ``capability``, in registry (preference) order."""
    reg = build_registry(settings, warehouse=warehouse, crosswalk=crosswalk)
    return [p for p in reg if p.supports(capability)]
