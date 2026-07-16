"""FantasyFootballCalculator ADP provider (plan §4.4) — the free source of Standard (non-PPR),
12-team ADP *with stdev*, the survival input the analytic VONA needs (``S_j(N)`` uses s_j).

Network happens ONLY here, ONLY in precompute, ONLY daily: a 24 h file+memo cache fronts one
httpx GET of ``/adp/{scoring}?teams={teams}&year={season}`` (FFC etiquette — never poll faster).
The current draft season is the only queryable year; a past/off year returns ``status='Error'``
with no players, which raises ``ProviderError`` and is NEVER cached as authoritative.

Ground truth (2026-07-16): FFC positions are ``DEF``/``PK`` (mapped to ``DST``/``K`` before
resolution, else every kicker/defense would silently drop), and rows carry no crosswalk-seedable
id, so each resolves by name+team+pos via :meth:`Crosswalk.resolve_name`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

from jaaffl.config import Settings, get_settings
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider, ProviderError

if TYPE_CHECKING:
    from jaaffl.data import Crosswalk

log = structlog.get_logger(__name__)

# The immutable constitution these mirror (config/league.json). Divergence is surfaced, never
# silently rewritten (matches ingest/cbs.py's _IMMUTABLE_* idiom).
_IMMUTABLE_SCORING = "standard"
_IMMUTABLE_TEAMS = 12

# FFC position codes -> canonical positions. DEF/PK differ from the domain's DST/K; anything
# absent here (should not occur for this league) is skipped.
_FFC_POSITION_MAP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "DEF": "DST", "PK": "K"}

_HEADERS = {"User-Agent": "JAAFFL/0.1 (personal, non-commercial draft assistant)"}
_TIMEOUT = 30.0


class FantasyFootballCalculatorProvider(FantasyDataProvider):
    def __init__(
        self,
        settings: Settings | None = None,
        crosswalk: Crosswalk | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._crosswalk = crosswalk
        self._client = client
        self._scoring = self._settings.jaaffl_ffc_scoring
        self._teams = self._settings.jaaffl_ffc_teams
        self._base_url = self._settings.jaaffl_ffc_base_url.rstrip("/")
        self._ttl_seconds = max(self._settings.jaaffl_ffc_cache_ttl_hours, 24) * 3600
        self._memo: dict[int, dict] = {}

    @property
    def name(self) -> str:
        return "ffc"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.ADP})

    @property
    def enabled(self) -> bool:
        return bool(self._settings.jaaffl_enable_ffc)

    def adp(self, season: int | None = None) -> dict[str, AdpRecord]:
        season = season or self._settings.jaaffl_season
        if not season:
            raise ProviderError("FFC needs a draft season (set jaaffl_season)")
        self._surface_league_divergence()
        payload = self._get_payload(int(season))
        if not _is_success(payload):
            raise ProviderError(
                f"FFC returned no ADP for season={season} (query the CURRENT draft season only)"
            )
        cx = self._resolve_crosswalk()
        out: dict[str, AdpRecord] = {}
        skipped = 0
        for row in payload["players"]:
            pos = _FFC_POSITION_MAP.get(str(row.get("position", "")).upper())
            cid = cx.resolve_name(row["name"], row.get("team"), pos) if pos else None
            if cid is None:
                skipped += 1
                continue
            out[cid] = AdpRecord(
                adp=row["adp"],
                stdev=row.get("stdev"),
                high=row.get("high"),
                low=row.get("low"),
                times_drafted=row.get("times_drafted"),
                bye=row.get("bye"),
            )
        if skipped:
            log.info("ffc_adp_unresolved_skipped", season=season, skipped=skipped, kept=len(out))
        return out

    # --- cache + fetch ---------------------------------------------------------------
    def _get_payload(self, season: int) -> dict:
        """Return the FFC payload for ``season`` via memo -> fresh file cache -> one GET. Only a
        SUCCESS payload is cached (memo + file); an error/empty payload is returned uncached so
        the caller raises and no empty result is ever persisted as authoritative."""
        if season in self._memo:
            return self._memo[season]
        path = self._cache_path(season)
        cached = self._read_fresh_cache(path)
        if cached is not None:
            self._memo[season] = cached
            return cached
        payload = self._fetch(season)
        if _is_success(payload):
            self._write_cache(path, payload)
            self._memo[season] = payload
        return payload

    def _fetch(self, season: int) -> dict:
        url = f"{self._base_url}/adp/{self._scoring}"
        params = {"teams": self._teams, "year": season}
        if self._client is not None:
            resp = self._client.get(url, params=params, headers=_HEADERS)
        else:  # pragma: no cover - real network path, exercised only in precompute
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(url, params=params, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()

    def _read_fresh_cache(self, path: Path) -> dict | None:
        if not path.exists() or (time.time() - path.stat().st_mtime) > self._ttl_seconds:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
            return None

    def _write_cache(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _cache_path(self, season: int) -> Path:
        # Components are trusted config/ints, but sanitize defensively (no path traversal).
        scoring = re.sub(r"[^a-z0-9]", "", self._scoring.lower()) or "standard"
        name = f"adp_{scoring}_{int(self._teams)}_{int(season)}.json"
        return self._settings.jaaffl_data_dir / "cache" / "ffc" / name

    # --- helpers ---------------------------------------------------------------------
    def _surface_league_divergence(self) -> None:
        if self._teams != _IMMUTABLE_TEAMS or self._scoring.lower() != _IMMUTABLE_SCORING:
            log.warning(
                "ffc_settings_conflict",
                scoring=self._scoring,
                teams=self._teams,
                immutable_scoring=_IMMUTABLE_SCORING,
                immutable_teams=_IMMUTABLE_TEAMS,
            )

    def _resolve_crosswalk(self) -> Crosswalk:
        if self._crosswalk is None:
            from jaaffl.data import Crosswalk

            self._crosswalk = Crosswalk()
        return self._crosswalk


def _is_success(payload: dict) -> bool:
    return payload.get("status") == "Success" and bool(payload.get("players"))
