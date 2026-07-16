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

from pydantic import BaseModel, ConfigDict

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


class AdpRecord(BaseModel):
    """One provider's ADP row for a canonical player (plan §4.1). Frozen; ``stdev`` is what
    the survival model ``S_j(N)=1-Phi((N-m_j)/s_j)`` needs — an ADP *mean* alone is
    insufficient, so the protocol carries the spread and range too.

    Backend-internal: never serialized to the TS contracts (there is no Zod mirror).
    """

    model_config = ConfigDict(frozen=True)

    adp: float  # mean draft position m_j
    stdev: float | None = None  # s_j (None -> engine falls back to ECR spread)
    high: float | None = None  # earliest observed pick
    low: float | None = None  # latest observed pick
    times_drafted: int | None = None
    bye: int | None = None


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

    def adp(self, season: int) -> dict[str, AdpRecord]:
        """canonical player_id -> ADP record (mean + stdev + range)."""
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
