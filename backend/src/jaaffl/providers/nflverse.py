"""nflverse provider (nflreadpy-backed) — the free historical base of the $0 prototype tier.

Polars-native: ``nfl_data_py`` is archived (read-only since 2025-09-25); ``nflreadpy`` is the
maintained successor and scans zero-copy into DuckDB. The class is ``NflreadpyProvider`` but the
stable ``name`` key stays ``"nflverse"`` so existing config/log references hold.

Note: nflverse's injury source lapsed after the 2024 season, so injuries are NOT offered
here — use CBS on-page data or an opt-in paid provider for current injuries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jaaffl.providers.base import Capability, FantasyDataProvider, ProviderError

if TYPE_CHECKING:
    import polars as pl

    from jaaffl.data import Crosswalk


def _import_nflreadpy():
    try:
        import nflreadpy  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ProviderError(
            "nflverse provider needs the 'data' extra: pip install -e '.[data]'"
        ) from exc
    return nflreadpy


class NflreadpyProvider(FantasyDataProvider):
    def __init__(self, crosswalk: Crosswalk | None = None) -> None:
        self._crosswalk = crosswalk

    @property
    def name(self) -> str:
        return "nflverse"

    @property
    def capabilities(self) -> frozenset[Capability]:
        # RANKINGS (ECR via load_ff_rankings) keeps the inherited NotImplementedError body
        # until the stage-4 id-crosswalk wiring lands.
        return frozenset(
            {Capability.HISTORICAL_STATS, Capability.RANKINGS, Capability.EXPECTED_POINTS}
        )

    def historical_stats(self, season: int) -> pl.DataFrame:
        """Weekly player stats for a season (thin delegate to nflreadpy)."""
        return _import_nflreadpy().load_player_stats(seasons=[season])

    def expected_points(self, season: int, week: int | None = None) -> pl.DataFrame:
        """Expected fantasy points (xEP) from nflverse ffopportunity."""
        return _import_nflreadpy().load_ff_opportunity(seasons=[season])
