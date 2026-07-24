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

from collections.abc import Iterable

from pydantic import BaseModel, Field

from jaaffl.domain import DraftState, Position
from jaaffl.engine.context import DraftContext

# Positions worth charting. K and DST are drafted in the final rounds and their curves are flat,
# so plotting them adds noise without informing a decision (config/league.json strategic_notes).
CURVE_POSITIONS: tuple[Position, ...] = (Position.QB, Position.RB, Position.WR, Position.TE)

# Bound the payload: 36 players per position is ~three rounds deep at 12 teams.
CURVE_DEPTH = 36


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
