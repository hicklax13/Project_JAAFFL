"""CBS on-page provider (plan §4.5) — the only $0 source of the league's ACTUAL settings plus
CBS first-party projections / injuries / rankings.

Performs ZERO network I/O: it READS the latest CBS snapshot from the warehouse (fed by the
extension->ingest path), never fetches. Methods degrade gracefully to empty ({} / None) until a
snapshot exists. CBS ids resolve to canonical via ``Crosswalk.resolve("cbs", cbs_id)``.

TODO(capture): the real CBS field shapes (CbsPageSnapshot projections/injuries/rankings maps and
the authoritative league_settings) are UNVERIFIED — record-mode capture is an owner-manual
session (docs/owner-manual-todo.md). This reader is built against SYNTHETIC fixtures; a fuzzy
``resolve_name`` fallback is deferred until the snapshot also carries a cbs_id -> name/team/pos
directory. Do NOT claim real CBS-frame support until capture lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import structlog

from jaaffl.providers.base import Capability, FantasyDataProvider

if TYPE_CHECKING:
    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.domain import CbsPageSnapshot, LeagueSettings

log = structlog.get_logger(__name__)

_V = TypeVar("_V")


class CbsOnPageProvider(FantasyDataProvider):
    def __init__(
        self, warehouse: Warehouse, crosswalk: Crosswalk, league_id: str | None = None
    ) -> None:
        self._warehouse = warehouse
        self._crosswalk = crosswalk
        self._league_id = league_id  # None -> warehouse resolves the sole active league

    @property
    def name(self) -> str:
        return "cbs_onpage"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.PROJECTIONS, Capability.INJURIES, Capability.RANKINGS})

    def projections(self, season: int, week: int | None = None) -> dict[str, dict[str, float]]:
        snap = self._latest()
        return self._resolve_cbs_map(snap.projections) if snap else {}

    def injuries(self, season: int, week: int | None = None) -> dict[str, str]:
        snap = self._latest()
        return self._resolve_cbs_map(snap.injuries) if snap else {}

    def rankings(self, season: int, week: int | None = None) -> dict[str, float]:
        snap = self._latest()
        return self._resolve_cbs_map(snap.rankings) if snap else {}

    def league_settings(self, league_id: str | None = None) -> LeagueSettings | None:
        """Authoritative CBS scoring + roster (non-capability method; consumed by
        jaaffl.league/jaaffl.ingest, not capability dispatch). ``None`` until a snapshot exists —
        config/league.json is the validation default / offline fallback, parsed elsewhere."""
        snap = self._warehouse.latest_cbs_snapshot(league_id or self._league_id)
        return snap.league_settings if snap else None

    # --- internals -------------------------------------------------------------------
    def _latest(self) -> CbsPageSnapshot | None:
        return self._warehouse.latest_cbs_snapshot(self._league_id)

    def _resolve_cbs_map(self, mapping: dict[str, _V]) -> dict[str, _V]:
        """Re-key a cbs_id-keyed map to canonical player_id, skipping (logging) unresolved ids.

        TODO(capture): add the fuzzy ``resolve_name`` fallback once the snapshot carries a
        cbs_id -> name/team/pos directory — today only the deterministic cbs-id join exists.
        """
        out: dict[str, _V] = {}
        skipped = 0
        for cbs_id, value in mapping.items():
            canonical = self._crosswalk.resolve("cbs", cbs_id)
            if canonical is None:
                skipped += 1
                continue
            out[canonical] = value
        if skipped:
            log.info("cbs_onpage_unresolved_skipped", skipped=skipped, kept=len(out))
        return out
