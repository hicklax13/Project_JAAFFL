"""nflverse provider (nflreadpy-backed) — the free historical base of the $0 prototype tier.

Polars-native: ``nfl_data_py`` is archived (read-only since 2025-09-25); ``nflreadpy`` is the
maintained successor and scans zero-copy into DuckDB. The class is ``NflreadpyProvider`` but the
stable ``name`` key stays ``"nflverse"`` so existing config/log references hold.

Injuries are deliberately NOT offered here. Ground truth (nflreadpy 0.1.5, 2026-07-16):
``load_injuries`` covers seasons 2009–2025 only and RAISES ``ValueError`` for 2026 — so it gives
zero draft-time injuries for the active 2026 draft. Fresh injuries come from CBS on-page (§4.5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from jaaffl.providers.base import Capability, FantasyDataProvider, ProviderError

if TYPE_CHECKING:
    import polars as pl

    from jaaffl.data import Crosswalk

log = structlog.get_logger(__name__)

# FantasyPros ECR board to serve. Ground truth (nflreadpy 0.1.5): load_ff_rankings() is ONE live
# scrape with no season/week axis and 9 ``ecr_type`` codes where d*=dynasty, r*=redraft,
# b*=best-ball. ``page_type == 'redraft-overall'`` is the non-IDP in-season draft board (491 rows:
# {QB,RB,WR,TE,K,DST}). It is PPR-sourced (ppr-cheatsheets.php) — the free feed has NO explicit
# non-PPR board — so ECR here is a board-ordering / deep-round-ADP-fallback signal; the
# authoritative non-PPR draft signal is FFC ADP (Standard) + CBS on-page.
_ECR_PAGE_TYPE = "redraft-overall"


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
        return frozenset(
            {Capability.HISTORICAL_STATS, Capability.RANKINGS, Capability.EXPECTED_POINTS}
        )

    def historical_stats(self, season: int) -> pl.DataFrame:
        """Weekly player stats for a season (thin delegate to nflreadpy)."""
        return _import_nflreadpy().load_player_stats(seasons=[season])

    def expected_points(self, season: int, week: int | None = None) -> pl.DataFrame:
        """Expected fantasy points (xEP) from nflverse ffopportunity."""
        return _import_nflreadpy().load_ff_opportunity(seasons=[season])

    def rankings(self, season: int, week: int | None = None) -> dict[str, float]:
        """Expert consensus rank (ECR) keyed by canonical ``player_id``.

        ``season``/``week`` are accepted for protocol compatibility but do NOT filter this
        source — ``load_ff_rankings()`` is a single live FantasyPros scrape (provenance =
        ``scrape_date``), not a season-partitioned table. Selects the ``redraft-overall`` board,
        joins each row to canonical via the FantasyPros ``id`` (``resolve('fantasypros', id)``)
        with a name+team+pos fuzzy fallback, and SKIPS (logs, never raises) anything unresolved.
        """
        import polars as pl

        frame = _import_nflreadpy().load_ff_rankings()
        board = frame.filter(pl.col("page_type") == _ECR_PAGE_TYPE)
        cx = self._resolve_crosswalk()
        out: dict[str, float] = {}
        skipped = 0
        for row in board.select(["player", "id", "pos", "team", "ecr"]).iter_rows(named=True):
            canonical = self._resolve_rank_row(cx, row)
            if canonical is None:
                skipped += 1
                continue
            out[canonical] = float(row["ecr"])
        if skipped:
            log.info("nflverse_rankings_unresolved_skipped", skipped=skipped, kept=len(out))
        return out

    def seed_crosswalk(self) -> int:
        """Stage-A seed: pull the nflverse ``ff_playerids`` crosswalk (the DynastyProcess table
        carrying ``cbs_id``/``fantasypros_id``/… alongside ``gsis_id``) and register deterministic
        source→canonical links. Returns the number of players seeded. Run once per draft-prep."""
        df = _import_nflreadpy().load_ff_playerids()
        return self._resolve_crosswalk().seed_from_playerids(df.iter_rows(named=True))

    @staticmethod
    def _resolve_rank_row(cx: Crosswalk, row: dict) -> str | None:
        fp_id = row.get("id")
        if fp_id is not None:
            hit = cx.resolve("fantasypros", str(fp_id))
            if hit is not None:
                return hit
        return cx.resolve_name(row["player"], row.get("team"), row["pos"])

    def _resolve_crosswalk(self) -> Crosswalk:
        if self._crosswalk is None:
            from jaaffl.data import Crosswalk

            self._crosswalk = Crosswalk()
        return self._crosswalk
