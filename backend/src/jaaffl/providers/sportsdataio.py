"""SportsDataIO provider — OPT-IN, PAID commercial feed (plan §4.6). Disabled stub.

Off by default. Enabled only when ``JAAFFL_ENABLE_SPORTSDATAIO=true`` and an API key is set.
Would add projections + injuries on top of the free tier. Commercial licensing applies — see
``docs/legal-and-compliance.md`` before enabling. Capability methods raise until subscribed.
"""

from __future__ import annotations

from jaaffl.config import Settings, get_settings
from jaaffl.providers.base import Capability, FantasyDataProvider


class SportsDataIOProvider(FantasyDataProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def name(self) -> str:
        return "sportsdataio"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.PROJECTIONS, Capability.INJURIES})

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.jaaffl_enable_sportsdataio and self._settings.sportsdataio_api_key
        )

    def projections(self, season: int, week: int | None = None) -> dict[str, dict[str, float]]:
        raise NotImplementedError("stage 4: SportsDataIO projections (subscribe to enable)")

    def injuries(self, season: int, week: int | None = None) -> dict[str, str]:
        raise NotImplementedError("stage 4: SportsDataIO injuries (subscribe to enable)")
