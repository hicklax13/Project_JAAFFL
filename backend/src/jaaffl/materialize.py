"""Pre-draft materialization (plan §2.4/§2.8/§4.7) — the precompute layer that turns provider
pulls into local stores. This is the ONE place allowed to import both the provider registry AND
the warehouse; the engine never touches providers directly.

Two clean halves keep the store roles honest:

* ``refresh_*`` — the NETWORK step (pre-draft only): call ``providers_supporting(...)``, resolve to
  canonical ids, and persist raw pulls to Parquet via the Warehouse.
* ``Warehouse.materialize()`` — the NETWORK-FREE rebuild step (what ``make warehouse`` runs): load
  Parquet into the DISPOSABLE DuckDB analytics tables. Reproducible for fixed Parquet inputs.

Stage 4 fills ``adp`` (from FFC); Stage 5's ``refresh_projections`` fills ``projections``
(μ/σ/floor/ceiling under the exact CBS scoring map) via the engine, both written to Parquet so
``Warehouse.materialize()`` reloads them reproducibly. app.sqlite is never touched by a rebuild.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from jaaffl.config import EngineParams, Settings, get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import LeagueSettings, Player, Position
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider
from jaaffl.providers.registry import build_registry, providers_supporting

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import polars as pl

    from jaaffl.engine.projections import SituationSignal

log = structlog.get_logger(__name__)


def refresh_adp(
    season: int | None = None,
    *,
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
    providers: list[FantasyDataProvider] | None = None,
    captured_at: date | None = None,
) -> Path | None:
    """Pull ADP from the first ADP supporter (FFC in the $0 tier), keyed by canonical id, and
    persist it to ``parquet/ffc/adp_{scoring}_{teams}_{season}_{yyyymmdd}.parquet``. Returns the
    Parquet path, or ``None`` when no ADP supporter is active or the pull is empty. NETWORK step —
    precompute only. ``providers`` may be injected (tests / custom precompute); otherwise the
    registry's ADP supporters are used.
    """
    settings = settings or get_settings()
    warehouse = warehouse or Warehouse()
    crosswalk = crosswalk or Crosswalk()
    season = int(season or settings.jaaffl_season)

    supporters = (
        providers
        if providers is not None
        else providers_supporting(
            Capability.ADP, settings, warehouse=warehouse, crosswalk=crosswalk
        )
    )
    if not supporters:
        log.info("refresh_adp_no_supporters", season=season)
        return None
    records = supporters[0].adp(season)
    if not records:
        log.info("refresh_adp_empty", season=season, provider=supporters[0].name)
        return None

    scoring = settings.jaaffl_ffc_scoring
    teams = settings.jaaffl_ffc_teams
    stamped = captured_at or date.today()
    frame = _adp_dataframe(records, season, scoring, teams, stamped)
    # Date-stamp the file: ADP drifts through preseason, so each day is its own snapshot and a
    # re-run must not overwrite the series (materialize globs adp_*.parquet; the DuckDB adp PK
    # carries captured_at to hold every day's row).
    return warehouse.write_parquet(f"ffc/adp_{scoring}_{teams}_{season}_{stamped:%Y%m%d}", frame)


def refresh_nflverse_history(
    season: int,
    *,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
    provider: FantasyDataProvider | None = None,
) -> dict[str, Path]:
    """Seed the id crosswalk and persist raw nflverse pulls (player stats + xEP) to
    ``parquet/nflverse/*.parquet`` for Stage-5 projections. NETWORK step — precompute only. These
    Parquet snapshots are NOT loaded into DuckDB here (``projections`` is Stage 5)."""
    from jaaffl.providers.nflverse import NflreadpyProvider

    warehouse = warehouse or Warehouse()
    crosswalk = crosswalk or Crosswalk()
    provider = provider or NflreadpyProvider(crosswalk=crosswalk)
    if hasattr(provider, "seed_crosswalk"):
        provider.seed_crosswalk()
    return {
        "player_stats": warehouse.write_parquet(
            f"nflverse/player_stats_{season}", provider.historical_stats(season)
        ),
        "ff_opportunity": warehouse.write_parquet(
            f"nflverse/ff_opportunity_{season}", provider.expected_points(season)
        ),
    }


def refresh_projections(
    season: int,
    league_settings: LeagueSettings,
    engine_params: EngineParams,
    *,
    players: Mapping[str, Player],
    sigma_floor: Mapping[Position, float],
    warehouse: Warehouse | None = None,
    settings: Settings | None = None,
    crosswalk: Crosswalk | None = None,
    providers: list[FantasyDataProvider] | None = None,
    scoring_version: str = "cbs_standard",
    ecr_to_points: Callable[[Position, float], float] | None = None,
    situation: Mapping[str, SituationSignal] | None = None,
    games_missed: Mapping[Position, float] | None = None,
) -> Path | None:
    """Build engine projections (μ/σ/floor/ceiling under the CBS map) and persist them to
    ``parquet/projections/proj_{scoring_version}_{season}.parquet`` for ``materialize()`` to load
    into the DuckDB ``projections`` table. NETWORK step (via the providers) — precompute only;
    reproducible for fixed provider inputs. Returns the Parquet path, or ``None`` when empty."""
    from jaaffl.engine.projections import build_projections

    settings = settings or get_settings()
    warehouse = warehouse or Warehouse()
    crosswalk = crosswalk or Crosswalk()
    if providers is None:
        providers = build_registry(settings, warehouse=warehouse, crosswalk=crosswalk)

    projections = build_projections(
        league_settings,
        providers,
        engine_params,
        season,
        players=players,
        sigma_floor=sigma_floor,
        ecr_to_points=ecr_to_points,
        situation=situation,
        games_missed=games_missed,
    )
    if not projections:
        log.info("refresh_projections_empty", season=season)
        return None
    frame = _projections_dataframe(projections, season, scoring_version)
    return warehouse.write_parquet(f"projections/proj_{scoring_version}_{season}", frame)


def _projections_dataframe(projections: dict, season: int, scoring_version: str) -> pl.DataFrame:
    import json

    import polars as pl

    rows = [
        {
            "player_id": proj.player_id,
            "season": season,
            "source": "engine",
            "scoring_version": scoring_version,
            "stat_line": json.dumps(proj.stat_line, sort_keys=True),
            "mu": proj.mu,
            "sigma": proj.sigma,
            "floor": proj.floor,
            "ceiling": proj.ceiling,
        }
        for proj in projections.values()
    ]
    schema = {
        "player_id": pl.Utf8,
        "season": pl.Int64,
        "source": pl.Utf8,
        "scoring_version": pl.Utf8,
        "stat_line": pl.Utf8,
        "mu": pl.Float64,
        "sigma": pl.Float64,
        "floor": pl.Float64,
        "ceiling": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def _adp_dataframe(
    records: dict[str, AdpRecord], season: int, scoring: str, teams: int, captured_at: date
) -> pl.DataFrame:
    import polars as pl

    rows = [
        {
            "player_id": cid,
            "season": season,
            "scoring": scoring,
            "teams": teams,
            "adp": rec.adp,
            "stdev": rec.stdev,
            "high": None if rec.high is None else int(rec.high),
            "low": None if rec.low is None else int(rec.low),
            "times_drafted": rec.times_drafted,
            "bye": rec.bye,
            "captured_at": captured_at,
        }
        for cid, rec in records.items()
    ]
    schema = {
        "player_id": pl.Utf8,
        "season": pl.Int64,
        "scoring": pl.Utf8,
        "teams": pl.Int64,
        "adp": pl.Float64,
        "stdev": pl.Float64,
        "high": pl.Int64,
        "low": pl.Int64,
        "times_drafted": pl.Int64,
        "bye": pl.Int64,
        "captured_at": pl.Date,
    }
    return pl.DataFrame(rows, schema=schema)
