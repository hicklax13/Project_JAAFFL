"""Stage 0 of the engine: projection blend (§3.1) + round-aware refinements R1/R4 (§3.10).

Produce, per player, μ/σ/floor/ceiling in **league points under the exact CBS map** — the one place
non-PPR (Rec = 0) is enforced (sources are converted to points via ``league.scoring`` upstream). The
blend is a simple average of the $0 sources (empirically ≥ any hand-weighting — wisdom of crowds).

- **R1 reliability shrinkage** (§3.10.2): μ is shrunk toward its positional replacement baseline by
  ``r_pos`` — ~1.0 for RB/WR/QB/TE, ~0.4 for the low-reliability K/DST — so projection noise cannot
  hand a kicker a mid-round value.
- **R4 opportunity/situation** (§3.10.6): a capped μ nudge (± ``caps.mu_refinement_pct``) plus a σ
  widen and a surfaced flag for team-change / rookie-competition / etc. — usage moves μ/σ, never a
  separate additive score term.

``assemble_projections`` is the pure core (canonical-keyed points → PlayerProjection);
``build_projections`` gathers those points from providers (PROJECTIONS via the exact scoring map,
EXPECTED_POINTS via ``league.xep``, RANKINGS via an ECR→points curve). All provider I/O is
precompute — never the hot path.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import structlog

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Player, Position
from jaaffl.league.replacement import replacement_values
from jaaffl.league.scoring import league_points
from jaaffl.league.xep import XepSource, expected_points_source
from jaaffl.providers.base import Capability, FantasyDataProvider, ProviderError

log = structlog.get_logger(__name__)

Z_SCORE = 1.2816  # 10th/90th-pct band multiplier (design §3.1; z for an 80% central interval)


@dataclass(frozen=True, slots=True)
class SituationSignal:
    """A capped opportunity/situation adjustment (R4): fractional μ nudge + σ widen + a flag."""

    mu_delta_pct: float = 0.0  # requested fractional μ change (clamped to caps.mu_refinement_pct)
    sigma_multiplier: float = 1.0  # σ widen for scheme/role uncertainty
    flag: str | None = None  # surfaced reason, e.g. "new team — role unconfirmed"


@dataclass(frozen=True, slots=True)
class PlayerProjection:
    """Per-candidate projection under the exact CBS map — the DraftContext's Stage-0 output."""

    player_id: str
    position: Position
    mu: float  # E[season league points], post-shrinkage/situation
    sigma: float  # season-points SD (σ̂ scale)
    floor: float  # μ − z·σ
    ceiling: float  # μ + z·σ
    sources: dict[str, float] = field(
        default_factory=dict
    )  # per-source league points (transparency)
    stat_line: dict[str, float] = field(default_factory=dict)  # blended stats (when available)
    reliability: float = 1.0  # r_pos applied (§3.10 R1)
    situation_flag: str | None = None  # R4 flag, surfaced in the overlay


def assemble_projections(
    source_points: Mapping[str, Mapping[str, float]],
    position: Mapping[str, Position],
    params: EngineParams,
    settings: LeagueSettings,
    *,
    sigma_floor: Mapping[Position, float],
    situation: Mapping[str, SituationSignal] | None = None,
    games_missed: Mapping[Position, float] | None = None,
    stat_lines: Mapping[str, Mapping[str, float]] | None = None,
    sigma_prior: Mapping[str, float] | None = None,
) -> dict[str, PlayerProjection]:
    """Blend canonical-keyed source points into PlayerProjections (pure; no provider/network).

    ``sigma_prior`` is the per-player σ measured from history (``league.xep``); ``sigma_floor`` is
    the per-position fallback for everyone it could not measure (rookies, K/DST, anyone under the
    games floor). σ is a floor stack — cross-source disagreement still wins when it is wider.
    """
    situation = situation or {}
    stat_lines = stat_lines or {}
    sigma_prior = sigma_prior or {}

    # 1) Gather each player's per-source points (drop rows with no resolved position).
    per_player: dict[str, dict[str, float]] = {}
    for src, points in source_points.items():
        for pid, value in points.items():
            if pid in position:
                per_player.setdefault(pid, {})[src] = value

    # 2) μ = simple-average blend, then the capped R4 situation nudge → μ_adj; cross-source SD.
    mu_cap = float(params.caps["mu_refinement_pct"])
    mu_adj: dict[str, float] = {}
    cross_sd: dict[str, float] = {}
    for pid, srcs in per_player.items():
        values = list(srcs.values())
        blended = sum(values) / len(values)
        signal = situation.get(pid)
        if signal is not None:
            delta = max(-mu_cap, min(mu_cap, signal.mu_delta_pct))  # clamp to ±cap
            blended *= 1.0 + delta
        mu_adj[pid] = blended
        cross_sd[pid] = statistics.pstdev(values) if len(values) >= 2 else 0.0

    # 3) Replacement baselines from μ_adj (the R1 shrink anchor).
    players_min = {pid: Player(player_id=pid, name=pid, position=position[pid]) for pid in mu_adj}
    flex = (int(params.flex_split["RB"]), int(params.flex_split["WR"]))
    baselines = replacement_values(
        settings, mu_adj, players_min, flex_split=flex, games_missed=games_missed
    )

    # 4) Per player: R1 shrinkage toward baseline, σ (floored + situation-widened), 10/90 band.
    out: dict[str, PlayerProjection] = {}
    for pid, adj in mu_adj.items():
        pos = position[pid]
        reliability = float(params.reliability_shrinkage.get(pos.value, 1.0))
        baseline = baselines.get(pos, adj)
        mu = baseline + reliability * (adj - baseline)
        signal = situation.get(pid)
        floor = float(sigma_prior.get(pid, sigma_floor.get(pos, 0.0)))
        sigma = max(cross_sd[pid], floor)
        if signal is not None:
            sigma *= signal.sigma_multiplier
        out[pid] = PlayerProjection(
            player_id=pid,
            position=pos,
            mu=mu,
            sigma=sigma,
            floor=mu - Z_SCORE * sigma,
            ceiling=mu + Z_SCORE * sigma,
            sources=dict(per_player[pid]),
            stat_line=dict(stat_lines.get(pid, {})),
            reliability=reliability,
            situation_flag=signal.flag if signal is not None else None,
        )
    return out


def build_projections(
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    params: EngineParams,
    season: int,
    *,
    players: Mapping[str, Player],
    sigma_floor: Mapping[Position, float],
    week: int | None = None,
    situation: Mapping[str, SituationSignal] | None = None,
    ecr_to_points: Callable[[Position, float], float] | None = None,
    games_missed: Mapping[Position, float] | None = None,
    xep_season: int | None = None,
) -> dict[str, PlayerProjection]:
    """Gather canonical-keyed source points from the first provider supporting each capability, then
    blend (§3.1). PROJECTIONS stat lines → points via the exact CBS map; EXPECTED_POINTS (nflverse
    xEP) → points via the same map through ``league.xep``; RANKINGS ECR → points via
    ``ecr_to_points`` (skipped if not supplied). Provider I/O only — this runs in precompute.

    ``xep_season`` defaults to ``season - 1``: xEP measures REALIZED opportunity, so the draft
    season has no rows at all (verified — nflreadpy raises ``ValueError`` for 2026). A pull that
    fails or covers nobody is logged and dropped, leaving those players honestly marked as
    ECR-only in ``PlayerProjection.sources`` rather than carrying a fabricated projection.
    """
    position = {pid: player.position for pid, player in players.items()}
    source_points: dict[str, dict[str, float]] = {}
    stat_lines: dict[str, dict[str, float]] = {}
    sigma_prior: dict[str, float] = {}

    xep_provider = next((p for p in providers if p.supports(Capability.EXPECTED_POINTS)), None)
    if xep_provider is not None:
        resolved_xep_season = season - 1 if xep_season is None else xep_season
        xep = _expected_points(
            xep_provider, resolved_xep_season, settings, position, sigma_floor, week
        )
        if xep is not None and xep.points:
            source_points["xep"] = dict(xep.points)
            stat_lines.update({pid: dict(line) for pid, line in xep.stat_lines.items()})
            sigma_prior.update(xep.sigma)
            log.info(
                "projections_xep_source",
                season=resolved_xep_season,
                players=len(xep.points),
                measured_sigma=len(xep.sigma),
            )

    projections_provider = next((p for p in providers if p.supports(Capability.PROJECTIONS)), None)
    if projections_provider is not None:
        cbs_points: dict[str, float] = {}
        for pid, stat_line in projections_provider.projections(season, week).items():
            if pid in players:
                cbs_points[pid] = league_points(
                    stat_line,
                    settings.scoring,
                    players[pid].position,
                    tiers=settings.scoring_tiers,
                    bonuses=settings.scoring_bonuses,
                )
                stat_lines[pid] = dict(stat_line)
        if cbs_points:
            source_points["cbs"] = cbs_points

    if ecr_to_points is not None:
        rankings_provider = next((p for p in providers if p.supports(Capability.RANKINGS)), None)
        if rankings_provider is not None:
            ecr_points = {
                pid: ecr_to_points(players[pid].position, ecr)
                for pid, ecr in rankings_provider.rankings(season, week).items()
                if pid in players
            }
            if ecr_points:
                source_points["ecr"] = ecr_points

    return assemble_projections(
        source_points,
        position,
        params,
        settings,
        sigma_floor=sigma_floor,
        situation=situation,
        games_missed=games_missed,
        stat_lines=stat_lines,
        sigma_prior=sigma_prior,
    )


def _expected_points(
    provider: FantasyDataProvider,
    season: int,
    settings: LeagueSettings,
    position: Mapping[str, Position],
    sigma_floor: Mapping[Position, float],
    week: int | None,
) -> XepSource | None:
    """Pull + translate the xEP frame, or ``None`` when the source cannot be had.

    Failures are LOUD in the log and invisible in the output: the affected players simply have no
    ``xep`` entry in ``sources``, which is the project's live-data-honesty posture (never a
    silently substituted stand-in). ``ValueError`` is the real, observed failure — nflreadpy
    raises it for a season outside 2006–2025.
    """
    try:
        frame = provider.expected_points(season, week)
    except (ProviderError, NotImplementedError, ValueError) as exc:
        log.warning(
            "projections_xep_unavailable",
            provider=provider.name,
            season=season,
            error=str(exc),
        )
        return None
    return expected_points_source(
        frame, settings=settings, position=position, drift_sigma=sigma_floor
    )
