"""FantasyPros provider — OPT-IN, PAID (personal, non-commercial Premium tier).

Off by default. Enabled only when ``JAAFFL_ENABLE_FANTASYPROS=true`` and an API key is set.
Adds consensus rankings, ADP, projections, news, and injuries on top of the free tier.
Commercial use requires FantasyPros' separate commercial plan — see the compliance doc.
"""

from __future__ import annotations

from jaaffl.config import Settings, get_settings
from jaaffl.providers.base import Capability, FantasyDataProvider


class FantasyProsProvider(FantasyDataProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def name(self) -> str:
        return "fantasypros"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset(
            {
                Capability.PROJECTIONS,
                Capability.ADP,
                Capability.RANKINGS,
                Capability.INJURIES,
                Capability.NEWS,
            }
        )

    @property
    def enabled(self) -> bool:
        return bool(self._settings.jaaffl_enable_fantasypros and self._settings.fantasypros_api_key)

    def projections(self, season: int, week: int | None = None) -> dict[str, dict[str, float]]:
        # TODO(stage 4): call the FantasyPros API and map ids through the crosswalk.
        raise NotImplementedError("stage 4: FantasyPros projections")

    def adp(self, season: int) -> dict[str, float]:
        raise NotImplementedError("stage 4: FantasyPros ADP")

    def rankings(self, season: int, week: int | None = None) -> dict[str, float]:
        raise NotImplementedError("stage 4: FantasyPros ECR")

    def injuries(self, season: int, week: int | None = None) -> dict[str, str]:
        raise NotImplementedError("stage 4: FantasyPros injuries")
