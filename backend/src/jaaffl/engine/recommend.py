"""Engine orchestrator (§3.7) + the risk term (§3.5): live DraftState → ranked Recommendation.

This *is* the stateless per-pick ``recompute()``: given ``(state, context, params)`` it masks picked
players, re-derives depletion-aware baselines, computes survival + VONA, scores the top candidates
into a fully-decomposed ``ScoreComponents``, and ranks them. It imports **no** concrete provider,
httpx, or nflreadpy and touches **no** network — all provider I/O happened in precompute (§4.7).

The canonical score (design §6.C.7), reconstructed exactly by ``ScoreComponents``:

    score = MLV + κ·max(0, VONA) − risk_penalty + cliff_bonus + Σ modifiers

where ``vona`` is stored RAW (pre-κ, may be < 0), and ``risk_penalty`` (λ·σ̂) and ``cliff_bonus``
(α·CliffBonus) are the APPLIED signed contributions.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from jaaffl.config import EngineParams
from jaaffl.domain import (
    DraftState,
    Position,
    Recommendation,
    RecommendedPick,
    ScoreComponents,
)
from jaaffl.engine.context import DraftContext
from jaaffl.engine.opponents import (
    board_adp_shift,
    expected_best_available,
    pick_probabilities,
    run_pressure_by_position,
)
from jaaffl.engine.optimize import StartingSlot, lineup_value, marginal_lineup_value
from jaaffl.league.replacement import dynamic_replacement_values


class SlotState(StrEnum):
    """Where a candidate sits relative to your startable need at its position (§3.5)."""

    LAST_OPEN_STARTABLE = "last_open_startable"  # p fills your final open startable slot at its pos
    SURPLUS = "surplus"  # depth/stash beyond startable need
    NORMAL = "normal"


def lambda_weight(round_no: int, slot_state: SlotState, params: EngineParams) -> float:
    """Risk λ for the risk term ``−λ·σ̂`` (design §6.C.5).

    The phase default comes from ``params.lambda_schedule`` (floor-tilt λ>0 early, ceiling-tilt
    λ<0 late); the **slot override dominates** — filling your last open startable slot forces the
    floor tilt, a surplus/stash forces the ceiling tilt (``params.lambda_slot_override``).
    """
    if slot_state is SlotState.LAST_OPEN_STARTABLE:
        return float(params.lambda_slot_override["last_startable_slot_floor"])
    if slot_state is SlotState.SURPLUS:
        return float(params.lambda_slot_override["surplus_stash_ceiling"])
    for entry in params.lambda_schedule:
        low, high = entry["rounds"]
        if low <= round_no <= high:
            return float(entry["lambda"])
    return 0.0  # out-of-schedule round → neutral (never a crash)


def _seat_roster(
    my_roster: list[str],
    position: dict[str, Position],
    slots: list[StartingSlot],
) -> list[bool]:
    """Greedily seat rostered players into starting slots (maximize seated) → filled-per-slot."""
    remaining: Counter[Position] = Counter(position[p] for p in my_roster if p in position)
    filled = [False] * len(slots)
    for i, slot in enumerate(slots):  # dedicated (single-eligible) slots first
        if len(slot.eligible) == 1:
            pos = next(iter(slot.eligible))
            if remaining.get(pos, 0) > 0:
                filled[i] = True
                remaining[pos] -= 1
    for i, slot in enumerate(slots):  # then flex slots from whatever is left
        if len(slot.eligible) > 1 and not filled[i]:
            for pos in slot.eligible:
                if remaining.get(pos, 0) > 0:
                    filled[i] = True
                    remaining[pos] -= 1
                    break
    return filled


def _open_startable_by_position(
    filled: list[bool], slots: list[StartingSlot]
) -> dict[Position, int]:
    """How many open (unfilled) starting slots each position is still eligible to fill."""
    counts: dict[Position, int] = {}
    for i, slot in enumerate(slots):
        if not filled[i]:
            for pos in slot.eligible:
                counts[pos] = counts.get(pos, 0) + 1
    return counts


def _slot_state(pos: Position, open_startable: dict[Position, int]) -> SlotState:
    open_count = open_startable.get(pos, 0)
    if open_count == 0:
        return SlotState.SURPLUS
    if open_count == 1:
        return SlotState.LAST_OPEN_STARTABLE
    return SlotState.NORMAL


def _positional_modifiers(
    candidate_id: str,
    my_roster: list[str],
    context: DraftContext,
    params: EngineParams,
) -> dict[str, float]:
    """Bounded tie-breakers (bye-stack −, handcuff-synergy +, SOS ±), each capped (design §6.C.7).

    v1 ships the capped mechanism with no active modifier — bye/handcuff/SOS data is not on the $0
    tier yet, so fabricating one would violate live-data honesty. Each modifier, when added, is
    clamped to ``±caps.modifiers[name]`` and the sum re-clamped to ``±caps.modifier_abs_max``.
    """
    return {}


def _dominant_rationale(
    pick_pos: Position,
    components: ScoreComponents,
    params: EngineParams,
    situation_flag: str | None,
) -> str:
    """One line naming the dominant term behind the score (the anti-black-box guarantee, §6.5)."""
    kappa_vona = params.kappa * max(0.0, components.vona)
    terms = {
        "value (MLV)": components.mlv,
        "scarcity (VONA)": kappa_vona,
        "tier cliff": components.cliff_bonus,
        "risk tilt": -components.risk_penalty,
    }
    lead = max(terms, key=lambda k: abs(terms[k]))
    flag = f" · {situation_flag}" if situation_flag else ""
    return f"{pick_pos.value}: {lead} (MLV {components.mlv:.1f}, VONA {components.vona:.1f}){flag}"


def recommend(
    state: DraftState,
    context: DraftContext,
    params: EngineParams,
    *,
    use_mc_vona: bool = False,  # analytic VONA is the v1 default; MC is stretch (§3.9)
    limit: int | None = None,
) -> Recommendation:
    """Score every candidate into a decomposed, ranked Recommendation (stateless hot path)."""
    settings = context.settings
    picked = {pick.player_id for pick in state.picks if pick.player_id}
    available = [pid for pid in context.mu if pid not in picked]
    my_roster = [
        pick.player_id
        for pick in state.picks
        if pick.player_id and pick.team_id == state.my_team_id
    ]
    team_count = settings.team_count or 12
    round_no = (state.current_overall_pick - 1) // team_count + 1
    pick_in_round = (state.current_overall_pick - 1) % team_count + 1

    # 1) Depletion-aware baselines over what's still available (design §3.2 Dynamic VBD).
    drafted_at_pos: Counter[Position] = Counter(
        context.position[pid] for pid in picked if pid in context.position
    )
    baselines = dynamic_replacement_values(
        settings,
        context.mu,
        context.players,
        available,
        drafted_at_pos=drafted_at_pos,
        flex_split=context.flex_split,
    )

    # 2) Survival at N₁* (display) and N_H* (VONA horizon, R2), board-conditioned (R3). When the
    # snake order / my_team_id is unknown (e.g. before we know our slot), survival degrades to
    # "everyone available" so the engine still ranks on MLV rather than crashing.
    available_adp = {pid: context.adp_mean[pid] for pid in available if pid in context.adp_mean}
    try:
        run_pressure = run_pressure_by_position(state, settings, available_adp, context.position)
    except ValueError:
        run_pressure = {}
    shift = board_adp_shift(run_pressure, context.position, beta=params.board_survival_weight)
    horizon = max(1, int(params.vona_horizon_picks))

    def _survival(h: int) -> dict[str, float]:
        try:
            taken = pick_probabilities(
                state, settings, available_adp, context.adp_sd, horizon=h, adp_shift=shift
            )
        except ValueError:
            taken = {}  # no draft_order / my_team_id (e.g. pre-draft) → treat everyone as available
        return {pid: 1.0 - taken.get(pid, 0.0) for pid in available}

    survival_display = _survival(1)
    survival_vona = survival_display if horizon == 1 else _survival(horizon)

    # 3) Static-ish MLV for every available player (dynamic baselines); cache the base lineup once.
    base_value = lineup_value(
        my_roster, context.mu, context.position, baselines, context.starting_slots
    )
    mlv = {
        pid: marginal_lineup_value(
            pid,
            my_roster,
            context.mu,
            context.position,
            baselines,
            context.starting_slots,
            base_value=base_value,
        )
        for pid in available
    }

    # 4) VONA baseline E_π per position (expected best surviving MLV at that position by N_H*).
    by_position: dict[Position, list[str]] = {}
    for pid in available:
        by_position.setdefault(context.position[pid], []).append(pid)
    expected_best: dict[Position, float] = {}
    for pos, pids in by_position.items():
        ranked = sorted(pids, key=lambda p: mlv[p], reverse=True)
        expected_best[pos] = expected_best_available(
            ranked, mlv, survival_vona, replacement=baselines.get(pos, 0.0)
        )

    # 5) Candidate pool: top-K available by MLV (bounded hot path).
    candidates = sorted(available, key=lambda p: mlv[p], reverse=True)[: params.candidate_cap]

    # Slot-state accounting for my current roster (drives the λ override + punt guard). The
    # puntable positions come from the config (punt_guard.stream_round keys) — one source of truth,
    # so making, say, TE streamable is a config change, not a code change.
    puntable = frozenset(Position(key) for key in params.punt_guard.get("stream_round", {}))
    filled = _seat_roster(my_roster, context.position, context.starting_slots)
    open_startable = _open_startable_by_position(filled, context.starting_slots)
    has_open_non_puntable = any(
        not filled[i] and not (slot.eligible <= puntable)
        for i, slot in enumerate(context.starting_slots)
    )

    picks: list[tuple[bool, RecommendedPick]] = []
    for pid in candidates:
        pos = context.position[pid]
        proj = context.projections[pid]
        mlv_p = mlv[pid]
        vona = mlv_p - expected_best.get(pos, 0.0)  # RAW (may be < 0)
        slot_state = _slot_state(pos, open_startable)
        risk_penalty = lambda_weight(round_no, slot_state, params) * proj.sigma
        applied_cliff = params.alpha * context.cliff_bonus.get(pid, 0.0)
        mods = _positional_modifiers(pid, my_roster, context, params)
        score = (
            mlv_p
            + params.kappa * max(0.0, vona)
            - risk_penalty
            + applied_cliff
            + sum(mods.values())
        )
        components = ScoreComponents(
            mlv=mlv_p,
            vona=vona,
            risk_penalty=risk_penalty,
            cliff_bonus=applied_cliff,
            sigma=proj.sigma,
            floor=proj.floor,
            ceiling=proj.ceiling,
            replacement_baseline=baselines.get(pos, 0.0),
            modifiers=mods,
            reliability=proj.reliability,
            vona_horizon=horizon,
            best_available_next=expected_best.get(pos, 0.0),
        )
        # Punt guard (R1): demote K/DST out of #1 before their stream round unless the rest of the
        # startable roster is full — it re-ranks, never changes the score.
        stream_round = int(params.punt_guard.get("stream_round", {}).get(pos.value, 0))
        punted = bool(
            params.punt_guard.get("enabled")
            and pos in puntable
            and round_no < stream_round
            and has_open_non_puntable
        )
        picks.append(
            (
                punted,
                RecommendedPick(
                    player_id=pid,
                    score=score,
                    projected_points=proj.mu,
                    vorp=mlv_p,
                    adp=context.adp_mean.get(pid),
                    next_turn_availability=survival_display.get(pid),
                    tier=context.tiers.get(pid),
                    rationale=_dominant_rationale(pos, components, params, proj.situation_flag),
                    components=components,
                ),
            )
        )

    picks.sort(key=lambda item: (item[0], -item[1].score))  # non-punted first, then score desc
    ranked = [pick for _, pick in picks]
    if limit is not None:
        ranked = ranked[:limit]

    normal_lambda = lambda_weight(round_no, SlotState.NORMAL, params)
    reasoning = (
        f"R{round_no}P{pick_in_round} · λ={normal_lambda:+.2f} · κ={params.kappa} · "
        f"α={params.alpha} · flex_split={context.flex_split[0]}RB/{context.flex_split[1]}WR "
        f"(EngineParams v{params.version}; analytic VONA, horizon {horizon})"
    )
    return Recommendation(
        league_id=state.league_id,
        as_of_overall_pick=state.current_overall_pick,
        ranked=ranked,
        reasoning=reasoning,
    )
