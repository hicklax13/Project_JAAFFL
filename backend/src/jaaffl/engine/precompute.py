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
no concrete provider. The owner-provided ``jaaffl_scoring()`` map is the authoritative scoring; a
captured CBS scoring page may still override it (owner-manual, docs/owner-manual-todo.md).
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

# Per-position σ (season league points) for the projection band, in two roles: the ANCHOR that
# ``league.xep`` scales by each player's own measured volatility, and the FALLBACK floor for
# everyone it could not measure. Every domain Position is covered so a stray IDP row can never
# KeyError inside ``assemble_projections``.
#
# QB/RB/WR/TE are MEASURED, not chosen: the SD of (realized season points − prior-season xEP),
# scored under the owner-verified JAAFFL map, averaged over two independent year-pairs.
# Reproduce verbatim with ``scripts/measure_projection_sigma.py`` (read-only; run 2026-07-25):
#
#   pos   2024→2025   2023→2024   used     n
#   QB      103.9       108.8     106.3   42/45
#   RB       54.6        63.5      59.0   81/91
#   WR       42.4        44.1      43.3  130/141
#   TE       26.2        32.3      29.2   75/73
#
# This replaces a flat ~50-for-everyone v1 placeholder that made a QB season look as predictable
# as a WR season. K/DST/IDP stay UNMEASURED priors — ffopportunity covers skill positions only
# (verified: zero DST rows, one stray K row), so there is nothing to measure them against yet.
_DEFAULT_SIGMA_FLOOR: dict[Position, float] = {
    Position.QB: 106.3,
    Position.RB: 59.0,
    Position.WR: 43.3,
    Position.TE: 29.2,
    Position.K: 20.0,  # unmeasured prior
    Position.DST: 25.0,  # unmeasured prior
    Position.DL: 25.0,  # unmeasured prior
    Position.LB: 25.0,  # unmeasured prior
    Position.DB: 25.0,  # unmeasured prior
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


def _seed_crosswalk_once(providers: Sequence[FantasyDataProvider]) -> Callable[[], None]:
    """Return a call-once closure that seeds the id crosswalk from the provider registry.

    **Why this has to be automatic.** CBS picks are ID-only (protocol doc §3), and FFC ADP is
    name-keyed, and nflverse ECR joins on the FantasyPros id — all three resolve through
    ``data/crosswalk.py``. On a fresh clone that table is EMPTY, and the failure is silent: a real
    server against a pristine data dir logged ``ffc_adp kept=0 skipped=179`` and
    ``rankings kept=0 skipped=508`` while still answering ``/recommendation`` with HTTP 200 and
    plausible-looking scores — every one of them carrying ``vona = 0.0``, because the entire
    opponent/survival model had no ADP. Tiers and cliff bonuses were empty for the same reason,
    and drafted CBS picks could never be masked. Leaving that to a manual, dry-run-by-default
    script (``scripts/seed_cbs_crosswalk.py``) means one forgotten step silently guts the engine
    on draft night.

    **Why here.** ``precompute`` is the one module allowed provider I/O (§4.7), and this must run
    BEFORE the providers are read, so the seam is the context closure — not app startup (which
    would pay a multi-second network pull on every boot, including offline ones) and not the hot
    path. It is lazy, so the cost lands on the first ``/recommendation``, which already does the
    provider pulls.

    Seeded once per process: the links persist in SQLite, and re-seeding per league would rewrite
    ~4.5k rows for nothing. Idempotent and precedence-safe either way — ``Crosswalk.link`` upserts
    and never downgrades a manual mapping. A failure is logged and swallowed so an offline draft
    still gets a board rather than losing the engine to a seeding error.
    """
    done = False

    def _seed() -> None:
        nonlocal done
        if done:
            return
        done = True  # set first: one failed attempt must not retry on every league
        provider = next((p for p in providers if hasattr(p, "seed_crosswalk")), None)
        if provider is None:
            return
        try:
            seeded = provider.seed_crosswalk()
        except (ProviderError, NotImplementedError, OSError) as exc:
            log.warning("precompute_crosswalk_seed_failed", provider=provider.name, error=str(exc))
            return
        log.info("precompute_crosswalk_seeded", provider=provider.name, players=seeded)

    return _seed


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
    seed_crosswalk = _seed_crosswalk_once(resolved_providers)

    def _context_for(league_id: str) -> DraftContext | None:
        # BEFORE any provider read: FFC ADP resolves by name and nflverse ECR by FantasyPros id,
        # so an unseeded crosswalk silently yields a board with no ADP, no ECR and vona = 0.
        seed_crosswalk()
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
