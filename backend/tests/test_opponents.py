"""Stage-2 VONA / survival (§3.4 + §3.10 R2/R3): closed-form Gaussian availability.

Survival S_j(N) = 1 − Φ((N − m_j)/s_j) from FFC ADP mean m_j + stdev s_j at your next pick N*,
read from the ACTUAL entered snake order (never inferred from team count). Turn-aware horizon (R2)
and board-conditioned survival (R3) refine it.
"""

from __future__ import annotations

import math

import pytest

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.opponents import (
    board_adp_shift,
    expected_best_available,
    next_overall_pick,
    pick_probabilities,
    run_pressure_by_position,
)
from tests.engine_fixtures import draft_state, jaaffl_settings, teams


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def test_next_overall_pick_reads_actual_snake_order() -> None:
    """Worked example (§3.4): at overall 25 (3.01) my next pick is 4.12 = overall 48."""
    settings = jaaffl_settings(draft_order=teams(12))  # I am t0 → round-1 slot 0
    state = draft_state(25, my_team_id="t0")
    assert next_overall_pick(settings, state) == 48  # H=1
    assert next_overall_pick(settings, state, horizon=2) == 49  # H=2 (the other side of the turn)


def test_next_overall_pick_refuses_to_infer_order_from_team_count() -> None:
    """League rule: never infer a plain snake from team count — a missing order is surfaced."""
    settings = jaaffl_settings(draft_order=None)
    with pytest.raises(ValueError, match="draft_order"):
        next_overall_pick(settings, draft_state(25))


def test_pick_probabilities_reproduce_the_worked_example() -> None:
    """§3.4 golden: at N*=48, a WR (m=30,s=8) is ~98.8% gone; an RB (m=55,s=10) ~24.2% gone."""
    settings = jaaffl_settings(draft_order=teams(12))
    state = draft_state(25, my_team_id="t0")
    p = pick_probabilities(state, settings, {"wr": 30.0, "rb": 55.0}, {"wr": 8.0, "rb": 10.0})
    assert p["wr"] == pytest.approx(0.988, abs=5e-4)  # P(taken) → survival 0.012
    assert p["rb"] == pytest.approx(0.242, abs=5e-4)  # P(taken) → survival 0.758


def test_pick_probabilities_vectorized_matches_scalar_loop() -> None:
    settings = jaaffl_settings(draft_order=teams(12))
    state = draft_state(25, my_team_id="t0")
    adp = {f"p{i}": 20.0 + i for i in range(300)}
    sd = {f"p{i}": 6.0 + (i % 5) for i in range(300)}
    got = pick_probabilities(state, settings, adp, sd)
    n_star = 48
    for pid in adp:
        expected = _phi((n_star - adp[pid]) / sd[pid])
        assert got[pid] == pytest.approx(expected, abs=1e-9)


def test_pick_probabilities_handle_zero_stdev_deterministically() -> None:
    settings = jaaffl_settings(draft_order=teams(12))
    state = draft_state(25, my_team_id="t0")  # N* = 48
    p = pick_probabilities(
        state, settings, {"gone": 40.0, "safe": 60.0}, {"gone": 0.0, "safe": 0.0}
    )
    assert p["gone"] == pytest.approx(1.0)  # ADP 40 < 48 ⇒ certainly taken
    assert p["safe"] == pytest.approx(0.0)  # ADP 60 > 48 ⇒ certainly available


def test_expected_best_available_exact_and_shortcut_agree_and_fall_back() -> None:
    # A smooth pool where the expected-max and the 0.5-crossing median are close.
    candidates = [f"c{i}" for i in range(12)]
    mlv = {c: 100.0 - 6.0 * i for i, c in enumerate(candidates)}
    survival = {c: 0.55 for c in candidates}  # each ~55% likely to survive
    exact = expected_best_available(candidates, mlv, survival, replacement=20.0)
    shortcut = expected_best_available(candidates, mlv, survival, replacement=20.0, shortcut=True)
    assert exact == pytest.approx(shortcut, abs=6.0)
    # Exhausted pool ⇒ both return the replacement tail value.
    assert expected_best_available([], mlv, survival, replacement=20.0) == pytest.approx(20.0)
    gone = {c: 0.0 for c in candidates}  # nobody survives
    assert expected_best_available(candidates, mlv, gone, replacement=20.0) == pytest.approx(20.0)


def test_expected_best_available_is_bounded_by_top_mlv() -> None:
    candidates = ["a", "b"]
    mlv = {"a": 90.0, "b": 50.0}
    survival = {"a": 1.0, "b": 1.0}  # top always survives → expected best = top MLV
    assert expected_best_available(candidates, mlv, survival, replacement=10.0) == pytest.approx(
        90.0
    )


def test_run_pressure_is_zero_without_a_run_and_positive_during_one() -> None:
    """R3: picks at a position beyond ADP expectation since my last turn → positive run pressure."""
    settings = jaaffl_settings(draft_order=teams(12))
    position = {f"rb{i}": Position.RB for i in range(8)}
    # My last turn was overall 24; picks 25..35 are the window before my next (current=36).
    # 5 RBs taken in the window whose ADP said they'd go LATER (m≈50) → a real run.
    adp = {f"rb{i}": 50.0 for i in range(8)}
    picks = [
        DraftPick(
            overall=o, round=3, pick_in_round=o - 24, team_id=f"t{o % 12}", player_id=f"rb{i}"
        )
        for i, o in enumerate(range(25, 30))
    ]
    state = draft_state(36, my_team_id="t0", picks=picks)
    pressure = run_pressure_by_position(state, settings, adp, position)
    assert pressure[Position.RB] > 0  # 5 RBs taken, ~0 expected by ADP → strong run


def test_board_adp_shift_pulls_effective_adp_earlier_under_a_run() -> None:
    """R3: m_j^eff = m_j − β·run_pressure(pos); β=0 is a no-op, β>0 lowers survival."""
    settings = jaaffl_settings(draft_order=teams(12))
    state = draft_state(48, my_team_id="t0")
    adp = {"rb_scarce": 60.0}
    sd = {"rb_scarce": 10.0}
    position = {"rb_scarce": Position.RB}
    run_pressure = {Position.RB: 6.0}

    no_shift = board_adp_shift(run_pressure, position, beta=0.0)
    assert no_shift.get("rb_scarce", 0.0) == pytest.approx(0.0)  # β=0 → static ADP

    shift = board_adp_shift(run_pressure, position, beta=0.5)  # −0.5·6 = −3.0 to the mean
    assert shift["rb_scarce"] == pytest.approx(-3.0)
    p_static = pick_probabilities(state, settings, adp, sd)["rb_scarce"]
    p_run = pick_probabilities(state, settings, adp, sd, adp_shift=shift)["rb_scarce"]
    assert p_run > p_static  # a run makes the scarce RB MORE likely gone (lower survival)
