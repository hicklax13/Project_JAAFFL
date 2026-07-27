"""Replacement-level baselines (VBD/VORP) derived from league roster construction.

Replacement level for a position is roughly the quality of the best still-available player
once every team has filled its dedicated starting slots at that position. Value over
replacement (VORP) then measures how much a player beats that baseline in *league* points.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from jaaffl.domain import LeagueSettings, Player, Position


def starter_demand(settings: LeagueSettings) -> dict[Position, int]:
    """League-wide count of *dedicated* starting slots per position.

    Dedicated (single-eligible-position) starting slots are summed across all teams. Flex
    slots (multiple eligible positions) are intentionally excluded here — allocating flex
    demand to the right positions depends on projected values and is handled in the engine
    (Stage 5). This function gives the exact dedicated baseline that flex allocation builds on.
    """
    demand: dict[Position, int] = defaultdict(int)
    for slot in settings.roster_slots:
        if not slot.starting:
            continue
        if len(slot.eligible_positions) == 1:
            demand[slot.eligible_positions[0]] += slot.count * settings.team_count
    return dict(demand)


def _demand_with_flex(settings: LeagueSettings, flex_split: tuple[int, int]) -> dict[Position, int]:
    """Dedicated demand + the WR/RB flex allocation (rb, wr) → league-wide startable demand."""
    demand = starter_demand(settings)
    demand[Position.RB] = demand.get(Position.RB, 0) + flex_split[0]
    demand[Position.WR] = demand.get(Position.WR, 0) + flex_split[1]
    return demand


def _ranked_mu(
    projected_points: Mapping[str, float],
    players: Mapping[str, Player],
    pos: Position,
    *,
    only: set[str] | None = None,
) -> list[float]:
    """League points of every player at ``pos`` (optionally restricted to ``only``), descending."""
    return sorted(
        (
            projected_points[pid]
            for pid in projected_points
            if players[pid].position == pos and (only is None or pid in only)
        ),
        reverse=True,
    )


def _value_at_rank(ranked: list[float], rank: int) -> float:
    """The μ at 1-indexed ``rank``; clamp to the worst available (0.0 if the pool is empty)."""
    if not ranked:
        return 0.0
    return ranked[rank - 1] if rank <= len(ranked) else ranked[-1]


def replacement_values(
    settings: LeagueSettings,
    projected_points: dict[str, float],
    players: dict[str, Player],
    *,
    flex_split: tuple[int, int],
    vols_weight: float = 0.5,
    games_missed: Mapping[Position, float] | None = None,
) -> dict[Position, float]:
    """Static replacement baselines for THIS roster (design §6.C.2 / §10.3).

    For each position the baseline is the μ at a blended replacement rank:
    ``rank = round(vols_weight·VOLS + (1−vols_weight)·man_games)`` where ``VOLS`` is the
    dedicated-plus-flex startable count and man-games deepens it by expected games missed over a
    17-round season. Yields the §10.3 targets (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13). The flex split
    is the most sensitive knob — MEASURE it live (E1, top-60); the default 8/4 is a placeholder.
    """
    demand = _demand_with_flex(settings, flex_split)
    out: dict[Position, float] = {}
    for pos, vols_idx in demand.items():
        gm = (games_missed or {}).get(pos, 0.0)
        mg_idx = vols_idx + round(vols_idx * gm / 17)  # man-games deepening (17-round season)
        rank = max(1, round(vols_weight * vols_idx + (1 - vols_weight) * mg_idx))
        out[pos] = _value_at_rank(_ranked_mu(projected_points, players, pos), rank)
    return out


def dynamic_replacement_values(
    settings: LeagueSettings,
    projected_points: Mapping[str, float],
    players: Mapping[str, Player],
    available_ids: Sequence[str],
    *,
    drafted_at_pos: Mapping[Position, int],
    flex_split: tuple[int, int],
) -> dict[Position, float]:
    """Depletion-aware baselines (design §6.C.2 "Dynamic VBD"): the replacement level recomputed
    from the **remaining league-wide startable demand** over the **still-available** players.

    ``baseline[pos] = μ of the FIRST non-startable available player`` = the ``(R+1)``-th best
    available, ``R = max(0, startable_demand[pos] − drafted_at_pos[pos])``. Pointing one past the
    remaining startable pool (not AT its last member) keeps this a true replacement level: when a
    position's demand saturates (R → 0/1), the baseline lands on a genuinely free player rather than
    collapsing onto the best remaining candidate's own μ — which would zero the MLV of the very
    player filling your last open slot at that position (e.g. a K/DST at its stream round). As
    startable slots fill leaguewide, R shrinks, the baseline rises, and every survivor is re-priced.
    (Live positional-run *urgency* is carried by board-conditioned VONA, §3.4/R3, not here.)

    **The rank is floored at 2 (Tier 7), which is what makes the paragraph above true.** ``R`` was
    floored at 0, so a fully saturated position took ``_value_at_rank(ranked, 1)`` — *the best
    available player himself* — and since ``lineup_value`` credits ``max(μ, baseline)`` either way,
    his own MLV came out at exactly ``0.0000``. The stated intent was already the right one; the
    zero floor defeated it precisely when the position mattered most. Measured on the real board,
    QB ``μ_best − baseline`` ran ``+51.15, +9.40, +0.32, 0.0000, 0.0000 …`` from round 4 on, so the
    engine scored a quarterback it had to have and a thirteenth tight end identically at zero.
    Rank 2 is "if I skip him I get the next man up" — the honest one-pick horizon; the
    survival-weighted version of the same question is κ·VONA's job, not this function's.
    """
    demand = _demand_with_flex(settings, flex_split)
    available = set(available_ids)
    out: dict[Position, float] = {}
    for pos, static_demand in demand.items():
        remaining = max(0, static_demand - drafted_at_pos.get(pos, 0))
        ranked = _ranked_mu(projected_points, players, pos, only=available)
        # First player BEYOND remaining demand, and never the best available (see above).
        out[pos] = _value_at_rank(ranked, max(2, remaining + 1))
    return out
