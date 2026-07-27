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
    from jaaffl.domain import Player

log = structlog.get_logger(__name__)

# FantasyPros ECR board to serve. Ground truth (nflreadpy 0.1.5): load_ff_rankings() is ONE live
# scrape with no season/week axis and 9 ``ecr_type`` codes where d*=dynasty, r*=redraft,
# b*=best-ball. ``page_type == 'redraft-overall'`` is the non-IDP in-season draft board (491 rows:
# {QB,RB,WR,TE,K,DST}). It is PPR-sourced (ppr-cheatsheets.php) — the free feed has NO explicit
# non-PPR board — so ECR here is a board-ordering / deep-round-ADP-fallback signal; the
# authoritative non-PPR draft signal is FFC ADP (Standard) + CBS on-page.
_ECR_PAGE_TYPE = "redraft-overall"

# --- team defenses ------------------------------------------------------------------------------
# ff_playerids is a table of PEOPLE and carries no team-defense rows at all (verified 2026-07-25
# against nflreadpy 0.1.5: 0 rows for each of DST/DEF/D/ST, and no name contains 'Defense'), so a
# universe built from it alone could never roster the DST this league starts. Defenses therefore
# come from the separate free ``load_teams()`` dimension.
#
# load_teams() returns 36 rows: the 32 current franchises plus 4 legacy/relocation duplicates.
# They MUST be dropped or one defense becomes draftable twice under two ids (e.g. dst:LV and
# dst:OAK are the same team). Verified 2026-07-25 — 36 abbrs minus these 4 leaves exactly 32.
_LEGACY_TEAM_ABBRS = frozenset({"OAK", "SD", "STL", "LA"})

# Canonical id namespace for a team defense. Deliberately NOT ``gsis:`` — a team has no gsis id
# and reusing that prefix would falsely imply one. ``team_abbr`` is stable across seasons, so a
# persisted crosswalk link or manual override survives a re-seed.
_DST_ID_PREFIX = "dst:"


def _team_defenses(frame: pl.DataFrame) -> list[Player]:
    """The 32 current team defenses as canonical ``dst:<team_abbr>`` :class:`Player`s.

    Named with the full ``team_name`` ("San Francisco 49ers"): ``crosswalk.name_norm`` collapses a
    DST to its nickname token, so the full name and the bare nickname both resolve identically
    (verified: every DST on the FantasyPros redraft board scores 1.00 against both forms), and the
    full name is what reads correctly on a draft board.
    """
    from jaaffl.domain import Player

    defenses: list[Player] = []
    for row in frame.iter_rows(named=True):
        abbr = str(row.get("team_abbr") or "").strip().upper()
        if not abbr or abbr in _LEGACY_TEAM_ABBRS:
            continue
        defenses.append(
            Player(
                player_id=f"{_DST_ID_PREFIX}{abbr}",
                name=str(row.get("team_name") or abbr),
                position="DST",
                nfl_team=abbr,
            )
        )
    return defenses


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
            {
                Capability.HISTORICAL_STATS,
                Capability.RANKINGS,
                Capability.EXPECTED_POINTS,
                Capability.SCHEDULE,
            }
        )

    def historical_stats(self, season: int) -> pl.DataFrame:
        """Weekly player stats for a season (thin delegate to nflreadpy)."""
        return _import_nflreadpy().load_player_stats(seasons=[season])

    def expected_points(self, season: int, week: int | None = None) -> pl.DataFrame:
        """Expected fantasy points (xEP) from nflverse ffopportunity."""
        return _import_nflreadpy().load_ff_opportunity(seasons=[season])

    def schedule(self, season: int) -> list[tuple[int, str, str]]:
        """REGULAR-SEASON fixtures as ``(week, home_team, away_team)`` — the input for bye weeks.

        Unlike xEP (which nflreadpy *raises* for the current season, forcing ``season − 1``), the
        schedule is published months ahead, so this reads the DRAFT season directly: measured
        2026-07-27, ``load_schedules(2026)`` returns 272 regular-season games covering all 32
        teams, and every team has exactly one derivable bye.
        """
        import polars as pl

        frame = _import_nflreadpy().load_schedules(seasons=[season])
        regular = frame.filter(pl.col("game_type") == "REG")
        return [
            (int(row["week"]), str(row["home_team"]), str(row["away_team"]))
            for row in regular.select(["week", "home_team", "away_team"]).iter_rows(named=True)
        ]

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

    def players(self, season: int) -> list[Player]:
        """The FREE nflverse player universe as domain ``Player``s (canonical ``gsis:<gsis_id>``).

        Loads the DynastyProcess ``ff_playerids`` dimension — the SAME source as
        :meth:`seed_crosswalk`, so the universe ids are exactly the ids the seed + :meth:`rankings`
        resolve to; the precompute join cannot silently empty out. Rows without a gsis id or with a
        non-league position are SKIPPED and logged, mirroring :meth:`rankings`. Position codes are
        aliased before that gate (``crosswalk._PLAYERID_POSITION_ALIASES``), which is what keeps
        this table's ``PK`` kickers in the universe. The 32 team defenses are APPENDED from the
        separate ``load_teams`` dimension (:func:`_team_defenses`) because ff_playerids has no
        team-defense rows at all — so this method reads TWO tables, and the result covers every
        position the league starts. ``season`` is accepted for protocol compatibility but does not
        filter either dimension. Raises :class:`ProviderError` when the ``data`` extra is missing.
        """
        from jaaffl.data.crosswalk import player_from_playerid_row

        nflreadpy = _import_nflreadpy()
        frame = nflreadpy.load_ff_playerids()
        universe: list[Player] = []
        skipped = 0
        for row in frame.iter_rows(named=True):
            player = player_from_playerid_row(row)
            if player is None:
                skipped += 1
                continue
            universe.append(player)
        defenses = _team_defenses(nflreadpy.load_teams())
        universe.extend(defenses)
        if skipped:
            log.info(
                "nflverse_players_unresolved_skipped",
                skipped=skipped,
                kept=len(universe),
                defenses=len(defenses),
            )
        return universe

    def seed_crosswalk(self) -> int:
        """Stage-A seed: pull the nflverse ``ff_playerids`` crosswalk (the DynastyProcess table
        carrying ``cbs_id``/``fantasypros_id``/… alongside ``gsis_id``) and register deterministic
        source→canonical links. Returns the number of players seeded. Run once per draft-prep.

        Team defenses are registered too, from ``load_teams`` (ff_playerids has no team rows).
        They carry no source ids to link, but they MUST exist as ``players`` rows: a live CBS
        defense pick resolves by name+team+pos (:meth:`Crosswalk.resolve_name`), and that fuzzy
        path can only match a candidate that is already in the table — otherwise a drafted DST
        stays unresolved and is never masked out of the candidate pool.
        """
        nflreadpy = _import_nflreadpy()
        crosswalk = self._resolve_crosswalk()
        seeded = crosswalk.seed_from_playerids(nflreadpy.load_ff_playerids().iter_rows(named=True))
        defenses = _team_defenses(nflreadpy.load_teams())
        for defense in defenses:
            crosswalk.upsert(defense)
        return seeded + len(defenses)

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
