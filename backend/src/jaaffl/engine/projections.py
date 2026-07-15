"""Stage 1 of the engine: projection ensemble.

Blend free historical production (nflverse) with CBS on-page projections and any enabled
paid projections (FantasyPros), plus injury/context features, into a per-player stat line.
"""

from __future__ import annotations

from collections.abc import Sequence

from jaaffl.domain import LeagueSettings
from jaaffl.providers import FantasyDataProvider


def build_projections(
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    season: int,
    week: int | None = None,
) -> dict[str, dict[str, float]]:
    """Return canonical ``player_id -> stat_line`` blended across available providers.

    TODO(stage 5): pull each provider's projections, reconcile via the crosswalk, and
    ensemble (weighted by source reliability). In the $0 tier this leans on nflverse
    history + CBS on-page numbers; enabling FantasyPros adds a vendor projection source.
    """
    raise NotImplementedError("stage 5: projection ensemble")
