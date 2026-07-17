"""Pre-draft precompute bridge (§3.7 / §4.7): the $0 provider registry → a RecommendationEngine
``context_source``.

ALL provider I/O and network live here (design §4.7). This module builds the immutable
``DraftContext`` the engine caches per league; the per-pick hot path (``engine.recommend``) then
reads that cached context and touches **no** provider and **no** network. The factory is fully
injectable (providers / player universe / season / sigma_floor / ecr_to_points) so tests exercise
the whole bridge with fakes and zero network.

This file lives under ``engine/`` but is deliberately NOT the hot path — it is the one engine module
allowed to reach providers, via ``jaaffl.providers.registry`` (base + registry only, §4.7); the
frozen ``recommend``/``optimize``/``opponents``/``tiers``/``projections``/``context`` modules import
no concrete provider. Real CBS scoring VALUES stay behind TODO(capture): the offline
``cbs_standard_scoring()`` map is the validation fallback until a live CBS scoring-page capture
lands (owner-manual, docs/owner-manual-todo.md).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from jaaffl.config import EngineParams, Settings
from jaaffl.domain import Player, Position
from jaaffl.engine.context import DraftContext, build_draft_context
from jaaffl.league.constitution import resolve_league_settings
from jaaffl.providers.base import Capability, FantasyDataProvider, ProviderError
from jaaffl.providers.registry import build_registry

if TYPE_CHECKING:
    from jaaffl.data import Crosswalk, Warehouse

log = structlog.get_logger(__name__)

# backend/src/jaaffl/engine/precompute.py → repo root is parents[4].
_REPO_ROOT = Path(__file__).resolve().parents[4]

# --- v1 defaults (documented; superseded by injection or the E-track calibration) ---------------

# Per-position σ floor (season league points) for the projection band — a v1 PLACEHOLDER pending E3
# calibration (design §3.1). Every domain Position is covered so a stray IDP row can never KeyError
# inside ``assemble_projections``.
_DEFAULT_SIGMA_FLOOR: dict[Position, float] = {
    Position.QB: 55.0,
    Position.RB: 50.0,
    Position.WR: 50.0,
    Position.TE: 40.0,
    Position.K: 20.0,
    Position.DST: 25.0,
    Position.DL: 25.0,
    Position.LB: 25.0,
    Position.DB: 25.0,
}

# ECR (expert-consensus rank) → league points: a monotonically decreasing v1 PLACEHOLDER (design
# §3.1). The free ECR board is PPR-sourced, so it is only a board-ordering signal — the
# authoritative value comes from CBS projections under the exact scoring map. ``position`` is
# accepted for a future position-aware curve but unused in v1.
_ECR_POINTS_INTERCEPT = 300.0


def _default_ecr_to_points(position: Position, ecr: float) -> float:
    return max(0.0, _ECR_POINTS_INTERCEPT - float(ecr))


def _load_engine_params(settings: Settings) -> EngineParams:
    """EngineParams from config/engine.json (§10.3), resolved robustly regardless of CWD: the
    configured path if it exists, else the repo-root config, else the model defaults."""
    path = Path(settings.jaaffl_engine_params_path)
    if not path.is_file():
        path = _REPO_ROOT / "config" / "engine.json"
    if path.is_file():
        return EngineParams.model_validate_json(path.read_text(encoding="utf-8"))
    log.warning("engine_params_file_missing_using_defaults")
    return EngineParams()


def _registry_player_loader(
    providers: Sequence[FantasyDataProvider],
) -> Callable[[int], dict[str, Player]]:
    """Default player universe: the first HISTORICAL_STATS provider's ``players(season)``, keyed by
    canonical player_id (design §4.7 / providers.base).

    Degrades to ``{}`` — so the source returns None and ``/recommendation`` 503s, never 500s — when
    no HISTORICAL_STATS provider exists, or its ``players`` is unavailable: a provider that doesn't
    override the base stub (``NotImplementedError``) or the ``data`` extra is missing
    (``ProviderError``). Enabling precompute without a live universe therefore fails soft.
    """

    def _load(season: int) -> dict[str, Player]:
        provider = next((p for p in providers if p.supports(Capability.HISTORICAL_STATS)), None)
        if provider is None:
            return {}
        try:
            universe = provider.players(season)
        except (NotImplementedError, ProviderError):
            log.warning("precompute_player_universe_unavailable", provider=provider.name)
            return {}
        return {player.player_id: player for player in universe}

    return _load


def build_registry_context_source(
    settings: Settings,
    *,
    warehouse: Warehouse,
    crosswalk: Crosswalk | None = None,
    providers: Sequence[FantasyDataProvider] | None = None,
    player_loader: Callable[[int], Mapping[str, Player]] | None = None,
    season: int | None = None,
    sigma_floor: Mapping[Position, float] | None = None,
    ecr_to_points: Callable[[Position, float], float] | None = None,
) -> Callable[[str], DraftContext | None]:
    """Return a ``(league_id) -> DraftContext | None`` the RecommendationEngine caches per league.

    Everything is resolved once here (providers, params, universe loader, season, band defaults);
    the returned closure does the per-league provider read + assembly via the frozen
    ``build_draft_context``. Returns ``None`` when the data is insufficient (empty universe or no
    projections) so ``/recommendation`` still 503s gracefully rather than serving a hollow board.

    Injection points keep tests network-free: pass ``providers`` and/or ``player_loader`` to bypass
    ``build_registry`` and the nflverse universe loader entirely. All provider I/O + network happen
    inside the returned closure (through the providers) — never in the engine hot path.
    """
    resolved_season = settings.jaaffl_season if season is None else season
    resolved_sigma_floor = _DEFAULT_SIGMA_FLOOR if sigma_floor is None else sigma_floor
    resolved_ecr_to_points = _default_ecr_to_points if ecr_to_points is None else ecr_to_points
    params = _load_engine_params(settings)

    if providers is None:
        from jaaffl.data import Crosswalk as _Crosswalk

        resolved_crosswalk = crosswalk or _Crosswalk(warehouse.app_sqlite)
        resolved_providers: Sequence[FantasyDataProvider] = build_registry(
            settings, warehouse=warehouse, crosswalk=resolved_crosswalk
        )
    else:
        resolved_providers = list(providers)

    load_players = player_loader or _registry_player_loader(resolved_providers)

    def _context_for(league_id: str) -> DraftContext | None:
        players = dict(load_players(resolved_season))
        if not players:
            log.info("precompute_no_player_universe", league_id=league_id)
            return None
        # The one provider read of the CBS snapshot (offline: warehouse-backed, never network); it
        # supplies the real scoring map when a capture exists, else the offline default is used.
        snapshot = warehouse.latest_cbs_snapshot(league_id)
        league_settings = resolve_league_settings(league_id, snapshot=snapshot)
        context = build_draft_context(
            league_settings,
            resolved_providers,
            params,
            resolved_season,
            players=players,
            sigma_floor=resolved_sigma_floor,
            ecr_to_points=resolved_ecr_to_points,
        )
        if not context.mu:  # no projections resolved → 503 rather than an empty board
            log.info("precompute_empty_projections", league_id=league_id)
            return None
        log.info("precompute_context_built", league_id=league_id, players=len(context.mu))
        return context

    return _context_for
