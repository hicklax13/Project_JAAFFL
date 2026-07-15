"""Cross-source player/team identity.

Every provider names players differently (CBS ids, nflverse GSIS ids, FantasyPros ids).
The crosswalk maps them to a single JAAFFL canonical ``player_id`` so projections and draft
events line up. Without this, the engine cannot join a CBS pick to nflverse history.
"""

from __future__ import annotations

from jaaffl.domain import Player


class Crosswalk:
    """Resolve source-specific ids to canonical JAAFFL player ids."""

    def resolve(self, source: str, source_id: str) -> str | None:
        """Return the canonical ``player_id`` for a ``(source, source_id)`` pair, if known."""
        raise NotImplementedError("stage 3: id resolution")

    def upsert(self, player: Player) -> None:
        """Register/merge a player and its ``external_ids`` into the crosswalk."""
        raise NotImplementedError("stage 3: id upsert + fuzzy match")
