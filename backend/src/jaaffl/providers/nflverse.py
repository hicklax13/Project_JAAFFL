"""nflverse / nfl_data_py provider — the free historical base of the $0 prototype tier.

Provides play-by-play-derived weekly/seasonal stats, rosters, schedules, and draft picks.
Note: nflverse's injury source lapsed after the 2024 season, so injuries are NOT offered
here — use CBS on-page data or an opt-in paid provider for current injuries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jaaffl.providers.base import Capability, FantasyDataProvider, ProviderError

if TYPE_CHECKING:
    import pandas as pd


def _import_nfl_data_py():
    try:
        import nfl_data_py  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ProviderError(
            "nflverse provider needs the 'data' extra: pip install -e '.[data]'"
        ) from exc
    return nfl_data_py


class NflverseProvider(FantasyDataProvider):
    @property
    def name(self) -> str:
        return "nflverse"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.HISTORICAL_STATS})

    def historical_stats(self, season: int) -> pd.DataFrame:
        """Weekly player stats for a season (thin delegate to nfl_data_py)."""
        nfl = _import_nfl_data_py()
        return nfl.import_weekly_data([season])

    # TODO(stage 3–4): map nfl_data_py rosters/ids into Player + external_ids for the
    # crosswalk, and expose seasonal/draft-pick pulls used by the projection ensemble.
