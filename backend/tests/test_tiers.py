"""Stage-4 tier cliffs (§3.6): Boris-Chen GMM tiers on ECR + last-in-tier cliff bonuses.

Tiers are interpretation + a guard rail (not an optimizer): a cliff bonus flags the last player
before a talent gap so the engine reaches across a tier boundary only when it should.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import Position
from jaaffl.engine.tiers import assign_tiers, cliff_bonuses


def _three_cluster_rb() -> tuple[dict[str, float], dict[str, Position]]:
    ecr, position = {}, {}
    for i, e in enumerate([1, 2, 3, 15, 16, 17, 40, 41, 42]):  # 3 well-separated ECR clusters
        pid = f"rb{i}"
        ecr[pid] = float(e)
        position[pid] = Position.RB
    return ecr, position


def test_assign_tiers_is_deterministic_for_fixed_random_state() -> None:
    ecr, position = _three_cluster_rb()
    assert assign_tiers(ecr, position, random_state=0) == assign_tiers(
        ecr, position, random_state=0
    )


def test_assign_tiers_orders_by_ecr_and_finds_the_three_clusters() -> None:
    ecr, position = _three_cluster_rb()
    tiers = assign_tiers(ecr, position, random_state=0)
    # Tier 1 = the best (lowest-ECR) cluster; numbers increase as ECR worsens.
    assert tiers["rb0"] == tiers["rb1"] == tiers["rb2"] == 1
    assert tiers["rb3"] == tiers["rb4"] == tiers["rb5"] == 2
    assert tiers["rb6"] == tiers["rb7"] == tiers["rb8"] == 3
    assert max(tiers.values()) <= 8  # default cap


def test_assign_tiers_respects_max_tiers_per_pos() -> None:
    ecr = {f"wr{i}": float(i) for i in range(20)}
    position = {f"wr{i}": Position.WR for i in range(20)}
    tiers = assign_tiers(ecr, position, max_tiers_per_pos=2, random_state=0)
    assert min(tiers.values()) == 1
    assert max(tiers.values()) <= 2  # tiers are contiguous 1..K


def test_assign_tiers_handles_single_player() -> None:
    assert assign_tiers({"qb0": 5.0}, {"qb0": Position.QB}) == {"qb0": 1}


def test_assign_tiers_is_per_position() -> None:
    ecr = {"rb0": 1.0, "rb1": 2.0, "wr0": 1.0, "wr1": 2.0}
    position = {"rb0": Position.RB, "rb1": Position.RB, "wr0": Position.WR, "wr1": Position.WR}
    tiers = assign_tiers(ecr, position, random_state=0)
    # Each position tiered independently — every id present, tiers start at 1 per position.
    assert set(tiers) == set(ecr)
    assert min(tiers[p] for p in ("rb0", "rb1")) == 1
    assert min(tiers[p] for p in ("wr0", "wr1")) == 1


def test_cliff_bonus_flags_last_in_tier_gap_to_next_tier_best() -> None:
    position = {p: Position.RB for p in "abcd"}
    tiers = {"a": 1, "b": 1, "c": 2, "d": 2}
    mlv = {"a": 100.0, "b": 80.0, "c": 50.0, "d": 40.0}
    cb = cliff_bonuses(tiers, mlv, position)
    assert cb["b"] == pytest.approx(30.0)  # last of tier 1 (mlv 80) − best of tier 2 (mlv 50)
    assert cb["a"] == pytest.approx(0.0)  # not last in its tier
    assert cb["c"] == pytest.approx(0.0)  # tier 2 is the bottom tier
    assert cb["d"] == pytest.approx(0.0)  # bottom tier's last has no cliff below


def test_cliff_bonus_is_never_negative() -> None:
    """A cliff bonus is urgency, never a penalty — an inverted MLV/tier ordering clamps to 0."""
    position = {"x": Position.WR, "y": Position.WR}
    tiers = {"x": 1, "y": 2}
    mlv = {"x": 10.0, "y": 40.0}  # last of tier 1 below best of tier 2 → clamp
    assert cliff_bonuses(tiers, mlv, position)["x"] == pytest.approx(0.0)


def test_cliff_bonus_compares_within_position_only() -> None:
    position = {"rb_last": Position.RB, "wr_top": Position.WR}
    tiers = {"rb_last": 1, "wr_top": 2}  # different positions — not a cliff pair
    mlv = {"rb_last": 90.0, "wr_top": 20.0}
    assert cliff_bonuses(tiers, mlv, position)["rb_last"] == pytest.approx(0.0)
