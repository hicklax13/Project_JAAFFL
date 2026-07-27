"""Engine precompute assembler (§3.7): providers → an immutable in-memory ``DraftContext``.

ALL provider I/O and network live here (design §4.7). Pre-draft, ``build_draft_context`` calls the
providers once, joins all by canonical ``player_id``, and freezes projections μ/σ/floor/ceiling,
ADP mean/SD (with ECR deep-round fill past the FFC thinning cliff), GMM tiers + cliff bonuses,
replacement baselines + flex allocation, and the 9 starting slots. The per-pick hot path
(``engine.recommend``) then reads this context and touches **no** provider and **no** network.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Player, Position
from jaaffl.engine.optimize import StartingSlot, expand_starting_slots, marginal_lineup_value
from jaaffl.engine.projections import PlayerProjection, SituationSignal, build_projections
from jaaffl.engine.tiers import assign_tiers, cliff_bonuses
from jaaffl.league.replacement import replacement_values
from jaaffl.providers.base import Capability, FantasyDataProvider

# When FFC gives no stdev (or a player only has ECR), fall back to a wide spread so survival stays
# uncertain rather than a false step function (design §3.4 FFC caveat).
_DEFAULT_ADP_SD = 12.0


@dataclass(frozen=True, slots=True)
class DraftContext:
    """Immutable precompute artifact — everything the stateless per-pick ``recompute()`` needs."""

    settings: LeagueSettings
    params: EngineParams
    projections: dict[str, PlayerProjection]
    mu: dict[str, float]  # league points μ_p view of ``projections``
    position: dict[str, Position]
    baselines: dict[
        Position, float
    ]  # static replacement baselines (recompute() re-derives dynamic)
    flex_split: tuple[int, int]
    tiers: dict[str, int]
    cliff_bonus: dict[str, float]  # raw CliffBonus_p (α applied in recommend)
    adp_mean: dict[str, float]  # FFC m_j (+ ECR fill)
    adp_sd: dict[str, float]  # FFC s_j (+ default)
    ecr: dict[str, float]
    starting_slots: list[StartingSlot]
    players: dict[str, Player]


def build_draft_context(
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    params: EngineParams,
    season: int,
    *,
    players: Mapping[str, Player],
    sigma_floor: Mapping[Position, float],
    week: int | None = None,
    ecr_to_points: Callable[[Position, float], float] | None = None,
    situation: Mapping[str, SituationSignal] | None = None,
    games_missed: Mapping[Position, float] | None = None,
) -> DraftContext:
    """Assemble the DraftContext from the first provider supporting each capability (precompute)."""
    players = dict(players)
    position = {pid: player.position for pid, player in players.items()}

    # --- ADP (mean + stdev), keyed canonical; unresolved rows already skipped by the provider. ---
    adp_mean: dict[str, float] = {}
    adp_sd: dict[str, float] = {}
    adp_provider = next((p for p in providers if p.supports(Capability.ADP)), None)
    if adp_provider is not None:
        for pid, record in adp_provider.adp(season).items():
            if pid in players:
                adp_mean[pid] = record.adp
                adp_sd[pid] = record.stdev if record.stdev else _DEFAULT_ADP_SD

    # --- ECR (for tiers + deep-round survival fill). ---
    ecr: dict[str, float] = {}
    rankings_provider = next((p for p in providers if p.supports(Capability.RANKINGS)), None)
    if rankings_provider is not None:
        ecr = {
            pid: e for pid, e in rankings_provider.rankings(season, week).items() if pid in players
        }

    # Deep-round fill: past the ~15-round FFC thinning cliff, back ADP with ECR so those players
    # still have a survival estimate (a wider default SD reflects the extra uncertainty).
    for pid, rank in ecr.items():
        adp_mean.setdefault(pid, rank)
        adp_sd.setdefault(pid, _DEFAULT_ADP_SD)

    # --- Projections μ/σ/floor/ceiling under the exact CBS map. ---
    projections = build_projections(
        settings,
        providers,
        params,
        season,
        players=players,
        sigma_floor=sigma_floor,
        week=week,
        situation=situation,
        ecr_to_points=ecr_to_points,
        games_missed=games_missed,
    )
    mu = {pid: proj.mu for pid, proj in projections.items()}

    # --- Static replacement baselines + tiers + cliff bonuses (over static/empty-roster MLV). ---
    flex = (int(params.flex_split["RB"]), int(params.flex_split["WR"]))
    baselines = replacement_values(
        settings, mu, players, flex_split=flex, games_missed=games_missed
    )
    starting_slots = expand_starting_slots(settings)
    static_mlv = {
        pid: marginal_lineup_value(pid, [], mu, position, baselines, starting_slots) for pid in mu
    }
    # Tiers are cut on μ, NOT on ECR (§3.6's letter) — the conflict is surfaced, with its
    # measurements, in ``engine/tiers.py``'s module docstring. In short: the cliff is priced in
    # MLV, a μ quantity, and since Tier 1 replaced the ``300 − ecr`` placeholder with real xEP the
    # two orderings genuinely differ (Spearman −0.943). Tiering μ also covers every projected
    # player, not just the ones the rankings feed reached (live 2026: 510 vs 447).
    tiers = assign_tiers(mu, position)
    cliff = cliff_bonuses(tiers, static_mlv, position)

    return DraftContext(
        settings=settings,
        params=params,
        projections=projections,
        mu=mu,
        position=position,
        baselines=baselines,
        flex_split=flex,
        tiers=tiers,
        cliff_bonus=cliff,
        adp_mean=adp_mean,
        adp_sd=adp_sd,
        ecr=ecr,
        starting_slots=starting_slots,
        players=players,
    )
