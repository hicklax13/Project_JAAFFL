"""Replacement baselines vs THIS roster (§3.2): VOLS + man-games blend, flex allocation, dynamic.

Targets (design §10.3): RB ≈ 22–24, WR ≈ 40–42, QB/TE/K/DST ≈ 13. The flex split (default 8 RB /
4 WR) is the single most sensitive knob and is MEASURED live (E1, top-60); here we pin the
computation given inputs. ``games_missed`` is the man-games (BEER+) calibration input (E1/E2).
"""

from __future__ import annotations

import pytest

from jaaffl.domain import Player, Position
from jaaffl.league.replacement import (
    dynamic_replacement_values,
    replacement_values,
    starter_demand,
)
from tests.engine_fixtures import jaaffl_settings


def _board() -> tuple[dict[str, float], dict[str, Player]]:
    """A calibration-style board: descending μ per position, deep enough to rank past demand."""
    counts = {
        Position.RB: 30,
        Position.WR: 50,
        Position.QB: 16,
        Position.TE: 16,
        Position.K: 16,
        Position.DST: 16,
    }
    starts = {
        Position.RB: 300.0,
        Position.WR: 280.0,
        Position.QB: 340.0,
        Position.TE: 190.0,
        Position.K: 150.0,
        Position.DST: 160.0,
    }
    mu: dict[str, float] = {}
    players: dict[str, Player] = {}
    for pos, n in counts.items():
        for i in range(n):
            pid = f"{pos.value.lower()}{i}"
            mu[pid] = starts[pos] - i * 5.0  # strictly descending, unique per rank
            players[pid] = Player(player_id=pid, name=pid, position=pos)
    return mu, players


# games_missed tuned so the documented ranges fall out (RB→22, WR→41, others→13).
_GAMES_MISSED = {
    Position.RB: 4.0,
    Position.WR: 1.0,
    Position.QB: 3.0,
    Position.TE: 3.0,
    Position.K: 3.0,
    Position.DST: 3.0,
}


def test_starter_demand_is_dedicated_only_for_this_roster() -> None:
    demand = starter_demand(jaaffl_settings())
    assert demand[Position.QB] == 12  # 1×12
    assert demand[Position.RB] == 12  # 1×12 (flex excluded here)
    assert demand[Position.WR] == 36  # 3×12
    assert demand[Position.TE] == demand[Position.K] == demand[Position.DST] == 12


def test_flex_allocation_deepens_rb_and_wr_pools() -> None:
    """The 12 WR/RB flex slots split (8 RB / 4 WR default) → VOLS RB20 / WR40 before man-games."""
    mu, players = _board()
    baselines = replacement_values(
        jaaffl_settings(), mu, players, flex_split=(8, 4), games_missed={}
    )
    # With no man-games, rank == VOLS index: RB 12+8=20, WR 36+4=40.
    assert baselines[Position.RB] == pytest.approx(mu["rb19"])  # 20th RB (0-indexed 19)
    assert baselines[Position.WR] == pytest.approx(mu["wr39"])  # 40th WR


def test_replacement_values_hit_design_ranges() -> None:
    """RB≈22–24, WR≈40–42, QB/TE/K/DST≈13 with the §10.3 flex split + man-games blend."""
    mu, players = _board()
    baselines = replacement_values(
        jaaffl_settings(), mu, players, flex_split=(8, 4), games_missed=_GAMES_MISSED
    )
    # rank(RB) = round(0.5·20 + 0.5·25) = 22 → 22nd-best RB (index 21).
    assert baselines[Position.RB] == pytest.approx(mu["rb21"])
    # rank(WR) = round(0.5·40 + 0.5·42) = 41 → 41st WR (index 40).
    assert baselines[Position.WR] == pytest.approx(mu["wr40"])
    # rank(others) = round(0.5·12 + 0.5·14) = 13 → 13th (index 12).
    for pos in (Position.QB, Position.TE, Position.K, Position.DST):
        assert baselines[pos] == pytest.approx(mu[f"{pos.value.lower()}12"])


def test_replacement_clamps_to_last_when_pool_shallower_than_demand() -> None:
    """Fewer players than the replacement rank ⇒ fall back to the worst available (never crash)."""
    players = {"rb0": Player(player_id="rb0", name="rb0", position=Position.RB)}
    mu = {"rb0": 111.0}
    baselines = replacement_values(
        jaaffl_settings(), mu, players, flex_split=(8, 4), games_missed={}
    )
    assert baselines[Position.RB] == pytest.approx(111.0)  # only one RB → it is the baseline
    assert baselines[Position.WR] == pytest.approx(0.0)  # no WRs → 0.0 floor


def test_dynamic_baseline_rises_as_startable_slots_fill() -> None:
    """Depletion-aware (§3.2 Dynamic VBD): as a position's remaining startable demand shrinks, the
    remaining-demand-th best AVAILABLE player is higher up the board → baseline rises."""
    mu, players = _board()
    settings = jaaffl_settings()
    available = list(mu)  # full board available
    base0 = dynamic_replacement_values(
        settings, mu, players, available, drafted_at_pos={}, flex_split=(8, 4)
    )
    base_run = dynamic_replacement_values(
        settings, mu, players, available, drafted_at_pos={Position.RB: 10}, flex_split=(8, 4)
    )
    # remaining RB demand 20 → 10; the 10th-best available RB beats the 20th → baseline rose.
    assert base_run[Position.RB] > base0[Position.RB]
    # An untouched position is unchanged.
    assert base_run[Position.WR] == pytest.approx(base0[Position.WR])


def test_dynamic_baseline_does_not_collapse_when_demand_saturated() -> None:
    """The player filling your LAST open slot at a near-exhausted position keeps positive VOR — the
    baseline must be the first FREE player, not the best remaining candidate's own μ."""
    mu = {"d0": 100.0, "d1": 60.0, "d2": 40.0}  # 3 DSTs left on the board
    players = {p: Player(player_id=p, name=p, position=Position.DST) for p in mu}
    # DST demand is 12 (1 per team); 11 already drafted → exactly your slot remains startable.
    base = dynamic_replacement_values(
        jaaffl_settings(),
        mu,
        players,
        list(mu),
        drafted_at_pos={Position.DST: 11},
        flex_split=(8, 4),
    )
    assert base[Position.DST] == pytest.approx(60.0)  # first non-starter (d1), NOT the top d0
    assert base[Position.DST] < mu["d0"]  # so the DST you draft has strictly positive VOR


def test_dynamic_baseline_is_monotonic_nondecreasing_in_draft_count() -> None:
    mu, players = _board()
    settings = jaaffl_settings()
    available = list(mu)
    prev = -1.0
    for drafted in range(0, 20, 2):
        base = dynamic_replacement_values(
            settings,
            mu,
            players,
            available,
            drafted_at_pos={Position.RB: drafted},
            flex_split=(8, 4),
        )
        assert base[Position.RB] >= prev
        prev = base[Position.RB]


# --- Tier 7: the baseline must never BE the best available player ------------------------------


def test_a_saturated_position_does_not_price_replacement_at_the_best_available() -> None:
    """The collapse that zeroed every needed position's MLV for six tiers.

    ``remaining = max(0, demand - drafted)`` bottoms out at 0, so ``_value_at_rank(ranked, 1)``
    returned **the best available player himself** — making his own MLV exactly ``0.0000`` by
    construction, because ``lineup_value`` credits ``max(mu, baseline)`` either way. Measured on
    the real board, QB ``mu_best - baseline`` went ``+51.15, +9.40, +0.32, 0.0000, 0.0000, ...``
    from round 4 onward and never recovered, so the engine could not distinguish a quarterback it
    had to have from a thirteenth tight end. This function's own docstring already says it points
    one past remaining demand precisely to avoid "collapsing onto the best remaining candidate's
    own μ" — the zero floor defeated that intent exactly when it mattered.
    """
    mu, players = _board()
    available = list(mu)
    settings = jaaffl_settings()
    # Every league-wide startable QB slot is gone: demand is fully saturated.
    baselines = dynamic_replacement_values(
        settings,
        mu,
        players,
        available,
        drafted_at_pos={Position.QB: 99},
        flex_split=(8, 4),
    )
    best_qb = max(
        (mu[pid] for pid in available if players[pid].position is Position.QB),
    )
    assert baselines[Position.QB] < best_qb


def test_the_saturated_baseline_is_the_next_man_up() -> None:
    """Skipping the best available means you get the SECOND best — that gap is the real MLV."""
    mu, players = _board()
    available = list(mu)
    ranked = sorted(
        (mu[pid] for pid in available if players[pid].position is Position.QB), reverse=True
    )
    baselines = dynamic_replacement_values(
        jaaffl_settings(),
        mu,
        players,
        available,
        drafted_at_pos={Position.QB: 99},
        flex_split=(8, 4),
    )
    assert baselines[Position.QB] == pytest.approx(ranked[1])
