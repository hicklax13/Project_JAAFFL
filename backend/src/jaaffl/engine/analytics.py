"""Analytics series for the dashboard panels (``GET /analytics``).

Derives the value curves and survival curves the war-room panels render, from the already-cached
:class:`DraftContext` plus the folded :class:`DraftState`. Pure functions, no I/O and no providers —
and NOT on the per-pick hot path: ``recommend`` never calls this module.

Survival reuses ``opponents.pick_probabilities`` (and the R3 board-conditioning helpers) rather than
re-deriving the Gaussian, so the panel and the engine can never disagree about who is scarce.

Backend-internal view models: no place in the E5 Pydantic⇄Zod parity surface, exactly like
:class:`DraftBoardState` (``ingest/board.py``). The dashboard parses these with a local Zod schema
(``packages/shared/src/analytics.ts``); the strict parity set stays the fixed nine.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from jaaffl.domain import DraftState, LeagueSettings, Position
from jaaffl.engine.context import DraftContext
from jaaffl.engine.opponents import (
    board_adp_shift,
    next_overall_pick,
    pick_probabilities,
    run_pressure_by_position,
)

# Positions worth charting. K and DST are drafted in the final rounds and their curves are flat,
# so plotting them adds noise without informing a decision (config/league.json strategic_notes).
CURVE_POSITIONS: tuple[Position, ...] = (Position.QB, Position.RB, Position.WR, Position.TE)

# Bound the payload: 36 players per position is ~three rounds deep at 12 teams.
CURVE_DEPTH = 36

# One survival line per candidate — matches the scalar SurvivalPanel's slice(0, 6) so the two
# survival surfaces always show the same players.
SURVIVAL_CANDIDATES = 6

# Picks charted beyond your second upcoming pick, so the curve continues past the marker.
SURVIVAL_TAIL = 6

# Backstop on the charted width (e.g. when the draft order/team slot is unknown and end-of-draft
# clamping in survival_curves has nothing to clamp against). The real no-picks-left guard is
# _total_picks below — see _marker_picks and survival_curves.
SURVIVAL_MAX_SPAN = 60

# Mirrors opponents._draft_rounds: rounds = total roster slots, falling back to the JAAFFL
# constitution's 17. Duplicated (not imported) because opponents.py is frozen and exposes no
# public accessor.
_DEFAULT_ROUNDS = 17


def _total_picks(settings: LeagueSettings) -> int:
    """The last valid overall pick. ``next_overall_pick`` returns this + 1 as its no-picks-left
    sentinel, so any marker beyond it is not a real pick."""
    rounds = sum(slot.count for slot in settings.roster_slots) or _DEFAULT_ROUNDS
    return rounds * len(settings.draft_order or [])


class CurvePoint(BaseModel):
    """One (rank, VOR) sample on a positional value curve."""

    rank: int = Field(ge=1)
    vor: float
    player_id: str
    name: str | None = None


class PositionCurve(BaseModel):
    """A position's value curve: the original board and what is still undrafted."""

    position: str
    full: list[CurvePoint] = Field(default_factory=list)
    remaining: list[CurvePoint] = Field(default_factory=list)


def _drafted_ids(state: DraftState) -> set[str]:
    return {pick.player_id for pick in state.picks if pick.player_id}


def _vor(pid: str, context: DraftContext) -> float:
    """Value over replacement: μ minus the replacement baseline for that player's position."""
    return context.mu[pid] - context.baselines.get(context.position[pid], 0.0)


def _curve(pids: Iterable[str], context: DraftContext) -> list[CurvePoint]:
    """VOR-ranked points for one position, best-first, re-ranked from 1 and capped.

    Ranks by VOR (not raw ``mu``) so the ordering is correct even if a caller ever passes
    mixed-position ``pids`` — a single-position input would rank identically either way, since
    the baseline is then constant, but nothing about this function's signature enforces that.
    """
    ranked = sorted(pids, key=lambda pid: _vor(pid, context), reverse=True)
    points: list[CurvePoint] = []
    for rank, pid in enumerate(ranked[:CURVE_DEPTH], start=1):
        player = context.players.get(pid)
        points.append(
            CurvePoint(
                rank=rank,
                vor=round(_vor(pid, context), 2),
                player_id=pid,
                name=player.name if player is not None else None,
            )
        )
    return points


def value_curves(context: DraftContext, state: DraftState) -> list[PositionCurve]:
    """Per-position VOR-vs-rank curves: the full preseason board plus what remains.

    The gap between ``full`` and ``remaining`` is what the panel draws as the positional run.
    """
    drafted = _drafted_ids(state)
    curves: list[PositionCurve] = []
    for position in CURVE_POSITIONS:
        at_pos = [
            pid for pid, pos in context.position.items() if pos == position and pid in context.mu
        ]
        if not at_pos:
            continue
        curves.append(
            PositionCurve(
                position=position.value,
                full=_curve(at_pos, context),
                remaining=_curve([pid for pid in at_pos if pid not in drafted], context),
            )
        )
    return curves


class SurvivalPoint(BaseModel):
    """P(player still on the board) at one overall pick number."""

    pick: int = Field(ge=1)
    survival: float = Field(ge=0.0, le=1.0)


class SurvivalCurve(BaseModel):
    """One candidate's availability decay across the charted pick span."""

    player_id: str
    name: str | None = None
    position: str | None = None
    points: list[SurvivalPoint] = Field(default_factory=list)


def _marker_picks(context: DraftContext, state: DraftState) -> list[int]:
    """Your next two upcoming picks, read from the REAL entered draft order.

    ``config/league.json`` sets ``infer_from_team_count: false`` — the order is decided in person
    and entered into CBS — so these MUST come from ``next_overall_pick``. Degrades to ``[]`` when
    the order or our team slot is not known yet (pre-draft), rather than raising.
    """
    total = _total_picks(context.settings)
    markers: list[int] = []
    for horizon in (1, 2):
        try:
            pick = next_overall_pick(context.settings, state, horizon=horizon)
        except ValueError:
            return []
        # Beyond the last pick of the draft = the no-picks-left sentinel, not a real upcoming pick.
        if pick <= state.current_overall_pick or (total and pick > total):
            break
        markers.append(pick)
    return markers


def survival_curves(
    context: DraftContext,
    state: DraftState,
    *,
    candidates: Sequence[str] | None = None,
) -> tuple[list[SurvivalCurve], list[int]]:
    """``(curves, marker_picks)`` — availability decay for the candidate set.

    ``candidates`` are the ids the dashboard already holds from the WS push, so the lines match the
    ranked picks rendered above them; unknown or already-drafted ids are skipped rather than
    raising. Omitted, it falls back to the best available by projected points so the endpoint is
    useful (and testable) on its own.
    """
    drafted = _drafted_ids(state)
    available = [pid for pid in context.mu if pid not in drafted]
    if candidates is None:
        chosen = sorted(available, key=lambda pid: context.mu[pid], reverse=True)
    else:
        available_set = set(available)
        chosen = [pid for pid in candidates if pid in available_set]
    chosen = [pid for pid in chosen[:SURVIVAL_CANDIDATES] if pid in context.adp_mean]

    markers = _marker_picks(context, state)
    start = state.current_overall_pick
    end = min((markers[-1] if markers else start) + SURVIVAL_TAIL, start + SURVIVAL_MAX_SPAN)
    total = _total_picks(context.settings)
    if total:
        end = min(end, total)
    picks = list(range(start, end + 1))

    if not chosen or not picks:
        return [], markers

    # Board-conditioned effective ADP (R3), mirroring recommend(): a position going faster than ADP
    # pulls its survival down, so the chart agrees with the advice the engine is giving.
    available_adp = {pid: context.adp_mean[pid] for pid in available if pid in context.adp_mean}
    try:
        pressure = run_pressure_by_position(
            state, context.settings, available_adp, context.position
        )
    except ValueError:
        pressure = {}
    shift = board_adp_shift(pressure, context.position, beta=context.params.board_survival_weight)

    subset_adp = {pid: context.adp_mean[pid] for pid in chosen}
    subset_sd = {pid: context.adp_sd[pid] for pid in chosen if pid in context.adp_sd}

    # One vectorized call per charted pick, then fan out — not one call per (player, pick).
    series: dict[str, list[SurvivalPoint]] = {pid: [] for pid in chosen}
    for pick in picks:
        taken = pick_probabilities(
            state,
            context.settings,
            subset_adp,
            subset_sd,
            my_next_overall=pick,
            adp_shift=shift,
        )
        for pid in chosen:
            survival = 1.0 - float(taken.get(pid, 0.0))
            series[pid].append(
                SurvivalPoint(pick=pick, survival=round(min(1.0, max(0.0, survival)), 4))
            )

    curves = [
        SurvivalCurve(
            player_id=pid,
            name=context.players[pid].name if pid in context.players else None,
            position=context.position[pid].value if pid in context.position else None,
            points=series[pid],
        )
        for pid in chosen
    ]
    return curves, markers
