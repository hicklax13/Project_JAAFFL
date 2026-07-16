"""Stage 1 of the engine: flex-aware Marginal Lineup Value (§3.3) — the value currency.

A candidate's value is its **marginal gain to the optimal 9-starter lineup**: solve the best
position-legal assignment of your roster (empty slots filled by replacement phantoms) to the 9
starting slots, then measure how much adding the candidate raises it.

```
L*(R)  = max over legal assignments of Σ_slot μ(player_in_slot)   (empty slots → baseline phantom)
MLV_p  = L*(B(R ∪ {p})) − L*(B(R))
```

For THIS fixed roster (QB, RB, WR×3, WR/RB-flex, TE, K, DST) the assignment has a trivial greedy
optimum — best player to each single-eligible slot, then the flex takes the best leftover among
{RB, WR} vs the flex phantom `max(RB_base, WR_base)`. ``lineup_value`` is that greedy (pure Python,
the hot-path default); ``lineup_value_hungarian`` is the general ``linear_sum_assignment``
verification path (imported lazily so the hot path needs no SciPy). Tests assert they agree.

Reduction guarantees (design §6.C.3): empty roster ⇒ MLV_p = μ_p − baseline(pos(p)) (classic VOR);
a 2nd QB behind a starter ⇒ MLV ≈ 0 (need is automatic, no hand-tuned multiplier); a player who
cracks no starting slot ⇒ MLV = 0 (its value is carried by the ceiling tilt + VONA, not MLV).

The CP-SAT ``optimize_roster`` below is the STRETCH end-of-season/season-simulator ILP (§3.9) —
never on the per-pick hot path — and stays a stub.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jaaffl.domain import LeagueSettings, Position


@dataclass(frozen=True, slots=True)
class StartingSlot:
    """One startable slot and its position eligibility. FLEX → {RB, WR} (no TE/QB — league rule)."""

    label: str
    eligible: frozenset[Position]


def expand_starting_slots(settings: LeagueSettings) -> list[StartingSlot]:
    """Expand ``roster_slots`` (starting=True) by ``count`` → the flat 9 starting slots."""
    slots: list[StartingSlot] = []
    for slot in settings.roster_slots:
        if not slot.starting:
            continue
        eligible = frozenset(slot.eligible_positions)
        slots.extend(StartingSlot(label=slot.slot, eligible=eligible) for _ in range(slot.count))
    return slots


def _flex_phantom(eligible: frozenset[Position], baselines: Mapping[Position, float]) -> float:
    """Replacement value of an empty slot = the best baseline among its eligible positions."""
    return max((baselines.get(pos, 0.0) for pos in eligible), default=0.0)


def lineup_value(
    player_ids: Sequence[str],
    mu: Mapping[str, float],
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],
    slots: Sequence[StartingSlot],
) -> float:
    """L*(R): greedy optimal starting-lineup value with empty slots replacement-filled.

    Optimal for the "dedicated single-eligible slots + one WR/RB flex" structure of this roster:
    fill each dedicated slot with the best available player of its position (else the phantom),
    then each flex slot takes the best remaining eligible player vs the flex phantom.
    """
    pool: dict[Position, list[float]] = defaultdict(list)
    for pid in player_ids:
        pool[position[pid]].append(mu[pid])
    for values in pool.values():
        values.sort(reverse=True)
    cursor: dict[Position, int] = defaultdict(int)

    dedicated = [s for s in slots if len(s.eligible) == 1]
    flex = [s for s in slots if len(s.eligible) > 1]
    total = 0.0

    for slot in dedicated:
        pos = next(iter(slot.eligible))
        phantom = baselines.get(pos, 0.0)
        available = pool.get(pos, ())
        i = cursor[pos]
        # A real player starts here only if it beats replacement; a sub-replacement player
        # never displaces the phantom (and stays a "leftover" that also loses in the flex).
        if i < len(available) and available[i] >= phantom:
            total += available[i]
            cursor[pos] = i + 1
        else:
            total += phantom

    for slot in flex:
        best_value = _flex_phantom(slot.eligible, baselines)
        best_pos: Position | None = None
        for pos in slot.eligible:
            available = pool.get(pos, ())
            i = cursor[pos]
            if i < len(available) and available[i] > best_value:
                best_value = available[i]
                best_pos = pos
        if best_pos is not None:
            cursor[best_pos] += 1
        total += best_value

    return total


def lineup_value_hungarian(
    player_ids: Sequence[str],
    mu: Mapping[str, float],
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],
    slots: Sequence[StartingSlot],
) -> float:
    """L*(R) via the general Hungarian assignment — the verification path (and future multi-flex).

    Rows = slots; columns = players ∪ {one phantom per slot}. Cost ``C[i,j] = −μ_eff(j)`` when
    ``j`` is eligible for slot ``i`` else a large sentinel; the per-slot phantom guarantees a
    feasible perfect matching, so the optimum never selects a sentinel cell.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    n = len(slots)
    # Columns: real players, then one phantom bound to each slot index.
    player_cols = [(mu[pid], position[pid]) for pid in player_ids]
    phantom_cols = [(_flex_phantom(slot.eligible, baselines), i) for i, slot in enumerate(slots)]
    big = 1.0e9
    cost = np.full((n, len(player_cols) + len(phantom_cols)), big)

    for i, slot in enumerate(slots):
        for j, (value, pos) in enumerate(player_cols):
            if pos in slot.eligible:
                cost[i, j] = -value
        for k, (value, slot_idx) in enumerate(phantom_cols):
            if slot_idx == i:  # a phantom fills only its own slot
                cost[i, len(player_cols) + k] = -value

    rows, cols = linear_sum_assignment(cost)
    return float(-cost[rows, cols].sum())


def marginal_lineup_value(
    candidate_id: str,
    roster: Sequence[str],
    mu: Mapping[str, float],
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],
    slots: Sequence[StartingSlot],
    *,
    base_value: float | None = None,
) -> float:
    """MLV_p = L*(B(R ∪ {p})) − L*(B(R)). Pass ``base_value`` to reuse a cached L*(B(R))."""
    if base_value is None:
        base_value = lineup_value(roster, mu, position, baselines, slots)
    with_candidate = lineup_value([*roster, candidate_id], mu, position, baselines, slots)
    return with_candidate - base_value


def optimize_roster(
    player_values: dict[str, float],
    player_positions: dict[str, str],
    settings: LeagueSettings,
    *,
    already_rostered: list[str] | None = None,
) -> list[str]:
    """Return the value-maximizing set of ``player_id``s that fills the roster legally.

    STRETCH (§3.9): the end-state / season-simulator ILP (OR-Tools CP-SAT) — binary pick vars,
    slot-eligibility constraints (incl. flex/superflex), and roster-size caps. Reserved for the
    rest-of-season simulator; **never** the per-pick path (that is ``marginal_lineup_value``).
    """
    raise NotImplementedError("stretch (§3.9): CP-SAT roster optimization")
