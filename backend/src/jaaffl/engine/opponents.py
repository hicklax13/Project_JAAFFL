"""Stage 2 of the engine: opponent pick-probability / survival model (§3.4, §3.10 R2/R3).

Opportunity cost is what makes the engine *live*. Closed-form Gaussian survival from FFC ADP mean
+ stdev, evaluated at your next pick N* read from the **actual** entered snake order (never
inferred from team count). Analytic is the v1 default; Monte-Carlo is the stretch refinement (§3.9).

```
S_j(N) = P(slot_j > N) = 1 − Φ((N − m_j^eff)/s_j)          # availability at pick N
N*     = next_overall_pick(settings, state, horizon=H)      # H-th upcoming pick (R2 turn-aware)
m_j^eff = m_j − β · run_pressure(pos(j))                     # board-conditioned ADP (R3)
```
``pick_probabilities`` returns P(taken before N*) = 1 − S. ``expected_best_available`` gives the
VONA baseline E[best surviving MLV at a position], from which recommend forms
``VONA_p = MLV_p − expected_best_available(pos(p), …)``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from jaaffl.domain import DraftState, LeagueSettings, Position

_DEFAULT_ROUNDS = 17  # JAAFFL constitution; used only if roster_slots are absent.


def _draft_rounds(settings: LeagueSettings) -> int:
    return sum(slot.count for slot in settings.roster_slots) or _DEFAULT_ROUNDS


def _my_overall_picks(settings: LeagueSettings, my_team_id: str | None) -> list[int]:
    """Every overall pick I own across the snake, from the ACTUAL entered round-1 order.

    Never inferred from team count — a missing order or unknown team is surfaced as a ValueError.
    """
    order = settings.draft_order
    if not order or my_team_id is None or my_team_id not in order:
        raise ValueError(
            "draft_order missing or my_team_id not in it — the live snake order must be read from "
            "the CBS room; the engine never infers it from team_count (league rule)."
        )
    n = len(order)
    slot = order.index(my_team_id)
    picks: list[int] = []
    for rnd in range(1, _draft_rounds(settings) + 1):
        pos_in_round = slot if rnd % 2 == 1 else n - 1 - slot  # snake reflection on even rounds
        picks.append((rnd - 1) * n + pos_in_round + 1)
    return picks


def next_overall_pick(settings: LeagueSettings, state: DraftState, *, horizon: int = 1) -> int:
    """Your H-th upcoming overall pick N_H* (H=1 = the very next). Clamps to your last pick; if you
    have none left, returns a far-future sentinel so everything trivially survives."""
    upcoming = [
        p for p in _my_overall_picks(settings, state.my_team_id) if p > state.current_overall_pick
    ]
    if not upcoming:
        return _draft_rounds(settings) * len(settings.draft_order or []) + 1
    return upcoming[min(max(horizon, 1), len(upcoming)) - 1]


def pick_probabilities(
    state: DraftState,
    settings: LeagueSettings,
    adp: Mapping[str, float],
    adp_sd: Mapping[str, float],
    *,
    horizon: int | None = None,
    my_next_overall: int | None = None,
    adp_shift: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """player_id → P(taken before your next pick) = Φ((N* − m_j^eff)/s_j), vectorized in NumPy.

    ``adp_shift`` adds a per-player offset to the ADP mean (R3 board conditioning: m_j^eff =
    m_j − β·run_pressure). A non-positive ``s_j`` degenerates to a deterministic step (taken iff
    m_j ≤ N*).
    """
    if not adp:
        return {}
    import numpy as np
    from scipy.special import ndtr  # Φ, the standard-normal CDF

    if my_next_overall is None:
        my_next_overall = next_overall_pick(settings, state, horizon=horizon or 1)
    shift = adp_shift or {}
    ids = list(adp)
    means = np.array([adp[j] + shift.get(j, 0.0) for j in ids], dtype=float)
    sds = np.array([float(adp_sd.get(j) or 0.0) for j in ids], dtype=float)
    n_star = float(my_next_overall)

    probs = np.empty(len(ids), dtype=float)
    positive = sds > 0.0
    probs[positive] = ndtr((n_star - means[positive]) / sds[positive])
    probs[~positive] = (means[~positive] <= n_star).astype(float)  # deterministic when s≤0
    return {j: float(p) for j, p in zip(ids, probs, strict=True)}


def expected_best_available(
    candidates: Sequence[str],
    mlv: Mapping[str, float],
    survival: Mapping[str, float],
    replacement: float,
    *,
    shortcut: bool = False,
) -> float:
    """E[best surviving MLV at a position by N*] over ``candidates`` sorted by MLV descending.

    Exact expected-max over independent survivals: ``Σ_k MLV_k·S_k·Π_{i<k}(1−S_i) +
    replacement·Π_all(1−S_i)``. ``shortcut=True`` returns the MLV of the first candidate whose
    cumulative "something survives" probability crosses 0.5 (design §6.C.4). Both fall back to
    ``replacement`` when the pool is exhausted / nobody survives.
    """
    if shortcut:
        all_gone = 1.0
        for pid in candidates:
            all_gone *= 1.0 - survival[pid]
            if 1.0 - all_gone >= 0.5:  # >50% chance one of the top-k survived
                return mlv[pid]
        return replacement

    result = 0.0
    all_gone = 1.0  # Π_{i<k}(1 − S_i): probability every higher-MLV candidate is already taken
    for pid in candidates:
        s = survival[pid]
        result += mlv[pid] * s * all_gone
        all_gone *= 1.0 - s
    return result + replacement * all_gone


def run_pressure_by_position(
    state: DraftState,
    settings: LeagueSettings,
    adp: Mapping[str, float],
    position: Mapping[str, Position],
) -> dict[Position, float]:
    """R3 run detector: (picks at a position since my last turn) − (ADP-expected picks over that
    span). Positive ⇒ that position is going faster than the board expected."""
    my_picks = _my_overall_picks(settings, state.my_team_id)
    prior = [p for p in my_picks if p < state.current_overall_pick]
    low = (max(prior) + 1) if prior else 1
    high = state.current_overall_pick - 1
    if high < low:
        return {}

    actual: Counter[Position] = Counter()
    for pick in state.picks:
        if pick.player_id and low <= pick.overall <= high and pick.player_id in position:
            actual[position[pick.player_id]] += 1
    expected: Counter[Position] = Counter()
    for pid, mean in adp.items():
        if pid in position and low <= mean <= high:  # ADP said this player would go in the window
            expected[position[pid]] += 1
    return {
        pos: actual.get(pos, 0) - float(expected.get(pos, 0)) for pos in set(actual) | set(expected)
    }


def board_adp_shift(
    run_pressure: Mapping[Position, float],
    position: Mapping[str, Position],
    beta: float,
) -> dict[str, float]:
    """Per-player ADP-mean shift for R3: ``−β · run_pressure(pos(j))`` (β=0 ⇒ pure static ADP)."""
    return {pid: -beta * run_pressure.get(pos, 0.0) for pid, pos in position.items()}
