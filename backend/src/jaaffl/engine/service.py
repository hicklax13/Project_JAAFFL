"""Recommendation service: hold the precomputed DraftContext per league, turn a folded DraftState
into a Recommendation (§8.3.3 / §8.5).

The context is built ONCE per league (precompute, network) and cached; the per-pick ``recommend``
is the provider-free hot path. ``context_source`` is injectable so the API can be exercised
headless (tests prime a context directly) and so a live server can lazily build from the registry.
"""

from __future__ import annotations

from collections.abc import Callable

from jaaffl.domain import DraftState, Recommendation
from jaaffl.engine.context import DraftContext
from jaaffl.engine.recommend import recommend


class RecommendationEngine:
    """Per-league DraftContext cache + the recompute entrypoint the API calls."""

    def __init__(
        self,
        *,
        context_source: Callable[[str], DraftContext | None] | None = None,
    ) -> None:
        self._context_source = context_source
        self._cache: dict[str, DraftContext] = {}

    def prime(self, league_id: str, context: DraftContext) -> None:
        """Install a pre-built context (the pre-draft precompute result, or a test fixture)."""
        self._cache[league_id] = context

    def context_for(self, league_id: str) -> DraftContext | None:
        """Return the cached context, building it once via ``context_source`` if provided."""
        context = self._cache.get(league_id)
        if context is None and self._context_source is not None:
            context = self._context_source(league_id)
            if context is not None:
                self._cache[league_id] = context
        return context

    def recommend(
        self,
        state: DraftState,
        *,
        limit: int | None = None,
        use_mc: bool = False,
    ) -> Recommendation | None:
        """Recompute for ``state``; ``None`` when no context is ready yet (→ API 503 warming up)."""
        context = self.context_for(state.league_id)
        if context is None:
            return None
        return recommend(state, context, context.params, limit=limit, use_mc_vona=use_mc)
