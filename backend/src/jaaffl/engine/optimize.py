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
never on the per-pick hot path — and needs the ``engine-stretch`` extra (ortools).
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


def roster_capacity(settings: LeagueSettings) -> dict[Position, int]:
    """How many players at each position ONE team can legally roster: every slot it is eligible for.

    A permissive upper bound at the skill positions — the bench is shared, so counting it once per
    eligible position over-counts — and an EXACT bound at K and DST, which fit only their own
    starting slot because ``league/constitution.py`` gives the bench ``(QB, RB, WR, TE)``. Exactness
    where it matters is the whole point.

    ``expand_starting_slots``, ``lineup_value`` and ``optimize_roster`` all already honour this
    eligibility. This exists so the simulated draft AGENTS can honour it too, rather than being the
    one part of the engine that ignores it: measured 2026-08-07, the behavioural field drafted
    **33 of 33** draftable kickers for 12 teams and held up to five each, none of which it could
    have started or benched. That manufactured a late-round famine no engine could survive, and it
    is what Tiers 6, 7 and 8 all first mistook for the engine being unable to draft a kicker.

    NOTE the bench eligibility is a JAAFFL modeling choice, not the constitution:
    ``config/league.json`` specifies a bench COUNT with no eligibility. If CBS turns out to permit
    benching a kicker, ``constitution._BENCH_ELIGIBLE`` changes and this follows automatically.
    """
    capacity: dict[Position, int] = defaultdict(int)
    for slot in settings.roster_slots:
        for position in slot.eligible_positions:
            capacity[position] += slot.count
    return dict(capacity)


def _flex_phantom(eligible: frozenset[Position], baselines: Mapping[Position, float]) -> float:
    """Replacement value of an empty slot = the best baseline among its eligible positions."""
    return max((baselines.get(pos, 0.0) for pos in eligible), default=0.0)


def lineup_value(
    player_ids: Sequence[str],
    mu: Mapping[str, float],
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],
    slots: Sequence[StartingSlot],
    *,
    picks_remaining: int | None = None,
) -> float:
    """L*(R): greedy optimal starting-lineup value with empty slots replacement-filled.

    Optimal for the "dedicated single-eligible slots + one WR/RB flex" structure of this roster:
    fill each dedicated slot with the best available player of its position (else the phantom),
    then each flex slot takes the best remaining eligible player vs the flex phantom.

    ``picks_remaining`` caps how many empty slots may be credited a phantom at all — **a
    replacement phantom you have no pick left to draft is not a player, it is a promise nobody
    keeps.** ``None`` (the default) means "unlimited", which is bit-identical to the pre-Tier-7
    behaviour, so every caller that has not opted in is unchanged.

    Before Tier 7 the phantom was credited unconditionally, including for a FINAL roster. That
    made an empty QB slot worth ``baselines[QB]`` forever, so (measured on the real 510-player
    board) a roster with no quarterback scored exactly as much as one with a replacement
    quarterback, and the engine drafted a thirteenth tight end while three of its nine starting
    slots stayed unfillable. The surviving phantoms are the HIGHEST-valued ones: given fewer picks
    than empty slots you would fill the slots that pay the most, so those are the ones still worth
    counting.
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
    # Slots nobody on the roster can start above replacement, as (phantom, fallback): what the
    # slot is worth if a pick is still free to draft its replacement, and what it is worth if not.
    # The fallback is the best sub-replacement leftover at that position -- a player you would
    # obviously start over nobody, and 0.0 when the roster has none at all.
    open_slots: list[tuple[float, float]] = []

    for slot in dedicated:
        pos = next(iter(slot.eligible))
        phantom = baselines.get(pos, 0.0)
        available = pool.get(pos, ())
        i = cursor[pos]
        # A real player starts here only if it beats replacement; a sub-replacement player never
        # displaces the phantom (and stays a "leftover" that also loses in the flex) -- unless no
        # pick remains to draft that phantom, in which case starting him beats starting nobody.
        if i < len(available) and available[i] >= phantom:
            total += available[i]
            cursor[pos] = i + 1
        else:
            fallback = available[i] if i < len(available) else 0.0
            if i < len(available):
                cursor[pos] = i + 1  # provisionally consumed; he can never win a slot elsewhere
            open_slots.append((phantom, fallback))

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
        else:
            fallback = 0.0
            fallback_pos: Position | None = None
            for pos in slot.eligible:
                available = pool.get(pos, ())
                i = cursor[pos]
                if i < len(available) and available[i] > fallback:
                    fallback, fallback_pos = available[i], pos
            if fallback_pos is not None:
                cursor[fallback_pos] += 1
            open_slots.append((best_value, fallback))

    if picks_remaining is None:
        return total + sum(phantom for phantom, _ in open_slots)
    # Spend the remaining picks where they buy the most: a slot is worth `phantom` if a pick
    # drafts its replacement and `fallback` otherwise, so the gain from spending one here is
    # `phantom - fallback`. Take the largest gains first; every slot still pays its fallback.
    open_slots.sort(key=lambda pair: pair[0] - pair[1], reverse=True)
    total += sum(fallback for _, fallback in open_slots)
    for phantom, fallback in open_slots[: max(0, picks_remaining)]:
        total += phantom - fallback
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

    **Unlimited-capacity only.** This deliberately has no ``picks_remaining``: it is the
    reference that pins the greedy's *assignment* choice, and every phantom is always available to
    it. The capacity rule is a separate question (which phantoms you can still afford to draft)
    layered on top of that assignment, so mixing the two here would test two things at once. The
    agreement tests therefore compare it against ``lineup_value``'s default.
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
    picks_remaining: int | None = None,
) -> float:
    """MLV_p = L*(B(R ∪ {p}), k−1) − L*(B(R), k). Pass ``base_value`` to reuse a cached L*(B(R)).

    Taking ``p`` **spends a pick**, so the candidate roster is valued with one fewer. That
    decrement is the entire mechanism: it is what turns "a slot I can no longer fill" from a
    silent zero into a measured loss. A body you cannot start now costs you the best phantom you
    can no longer afford, instead of scoring the same 0.00 as the starter you desperately need.

    Inert while ``k − 1 >= u`` (``u`` = slots taking a phantom), because both terms then credit
    every phantom. On this league's 9 starting slots that means rounds 1-14 are bit-identical, so
    the measured early-draft behaviour is preserved exactly and only the endgame changes.
    """
    if base_value is None:
        base_value = lineup_value(
            roster, mu, position, baselines, slots, picks_remaining=picks_remaining
        )
    after = None if picks_remaining is None else max(0, picks_remaining - 1)
    with_candidate = lineup_value(
        [*roster, candidate_id], mu, position, baselines, slots, picks_remaining=after
    )
    return with_candidate - base_value


def optimize_roster(
    player_values: dict[str, float],
    player_positions: dict[str, str],
    settings: LeagueSettings,
    *,
    already_rostered: list[str] | None = None,
) -> list[str]:
    """Return the value-maximizing set of ``player_id``s that fills the roster legally.

    STRETCH (§3.9): the end-state / season-simulator ILP (OR-Tools CP-SAT) — binary assignment
    vars, slot-eligibility constraints (incl. the WR/RB flex), and roster-size caps. Reserved for
    the rest-of-season simulator; **never** the per-pick path (that is ``marginal_lineup_value``).

    Formulation: assign players to the flat roster slots (starting + bench, expanded by ``count``),
    each slot holding ≤ 1 eligible player and each player ≤ 1 slot, maximizing assigned value.
    ``already_rostered`` players are forced into an eligible slot. A slot with no eligible player is
    left empty (degrades gracefully rather than turning infeasible). Values are scaled to integers
    (CP-SAT is integer-objective). Returns the assigned ``player_id``s (order not significant).
    """
    from ortools.sat.python import cp_model

    slots: list[frozenset[str]] = []
    for roster_slot in settings.roster_slots:
        eligible = frozenset(str(pos) for pos in roster_slot.eligible_positions)
        slots.extend(eligible for _ in range(roster_slot.count))

    players = list(player_values)
    model = cp_model.CpModel()
    assign = {
        (pid, s): model.new_bool_var(f"x_{pid}_{s}") for pid in players for s in range(len(slots))
    }
    for pid in players:
        pos = str(player_positions.get(pid, ""))
        for s, eligible in enumerate(slots):
            if pos not in eligible:
                model.add(assign[(pid, s)] == 0)
    for s in range(len(slots)):  # each slot holds at most one player
        model.add(sum(assign[(pid, s)] for pid in players) <= 1)
    for pid in players:  # each player fills at most one slot
        model.add(sum(assign[(pid, s)] for s in range(len(slots))) <= 1)
    forced = set(already_rostered or []) & set(players)
    for pid in forced:  # a player already on the roster must be placed (if eligible anywhere)
        if any(str(player_positions.get(pid, "")) in eligible for eligible in slots):
            model.add(sum(assign[(pid, s)] for s in range(len(slots))) == 1)

    scale = 1000
    model.maximize(
        sum(
            round(player_values[pid] * scale) * assign[(pid, s)]
            for pid in players
            for s in range(len(slots))
        )
    )
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return sorted(forced)  # infeasible — best effort (should not happen with the ≤1 relaxation)
    return [
        pid for pid in players if any(solver.value(assign[(pid, s)]) for s in range(len(slots)))
    ]
