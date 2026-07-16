"""The single provider interface every data source implements.

A provider declares which :class:`Capability` values it supports; callers check
``supports(...)`` before calling, and unsupported calls raise
:class:`CapabilityNotSupported`. Return shapes are keyed by canonical JAAFFL
``player_id`` (resolve via ``jaaffl.data.Crosswalk``).
"""

from __future__ import annotations

import abc
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    from jaaffl.domain import Player


class Capability(StrEnum):
    HISTORICAL_STATS = "historical_stats"
    PROJECTIONS = "projections"
    ADP = "adp"
    RANKINGS = "rankings"  # ECR (nflreadpy load_ff_rankings)
    EXPECTED_POINTS = "expected_points"  # xEP (nflreadpy load_ff_opportunity)
    INJURIES = "injuries"
    NEWS = "news"


class ProviderError(RuntimeError):
    """Base error for provider failures."""


class CapabilityNotSupported(ProviderError):
    """Raised when a provider is asked for a capability it does not declare."""


class FantasyDataProvider(abc.ABC):
    """Interface for a fantasy/NFL data source."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable provider key, e.g. 'nflverse', 'fantasypros'."""

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset()

    @property
    def enabled(self) -> bool:
        """Whether this provider is active (config-gated for paid sources)."""
        return True

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def _require(self, capability: Capability) -> None:
        if not self.supports(capability):
            raise CapabilityNotSupported(f"{self.name} does not support {capability.value}")

    # --- Capability methods. Concrete providers override those they declare. ---

    def players(self, season: int) -> list[Player]:
        self._require(Capability.HISTORICAL_STATS)
        raise NotImplementedError

    def historical_stats(self, season: int) -> pl.DataFrame:
        self._require(Capability.HISTORICAL_STATS)
        raise NotImplementedError

    def expected_points(self, season: int, week: int | None = None) -> pl.DataFrame:
        """Expected fantasy points (xEP), e.g. nflverse ffopportunity."""
        self._require(Capability.EXPECTED_POINTS)
        raise NotImplementedError

    def projections(self, season: int, week: int | None = None) -> dict[str, dict[str, float]]:
        """canonical player_id -> stat_line (stat name -> value)."""
        self._require(Capability.PROJECTIONS)
        raise NotImplementedError

    def adp(self, season: int) -> dict[str, float]:
        """canonical player_id -> average draft position."""
        self._require(Capability.ADP)
        raise NotImplementedError

    def rankings(self, season: int, week: int | None = None) -> dict[str, float]:
        """canonical player_id -> expert consensus rank."""
        self._require(Capability.RANKINGS)
        raise NotImplementedError

    def injuries(self, season: int, week: int | None = None) -> dict[str, str]:
        """canonical player_id -> injury status."""
        self._require(Capability.INJURIES)
        raise NotImplementedError
