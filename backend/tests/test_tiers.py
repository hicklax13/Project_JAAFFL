"""Stage-4 tier cliffs (§3.6): positional tiers on projected value + last-in-tier cliff bonuses.

Tiers are interpretation + a guard rail (not an optimizer): a cliff bonus flags the last player
before a talent gap so the engine reaches across a tier boundary only when it should.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import Position
from jaaffl.engine.tiers import assign_tiers, cliff_bonuses


def _three_cluster_rb() -> tuple[dict[str, float], dict[str, Position]]:
    value, position = {}, {}
    for i, points in enumerate([260, 259, 258, 190, 189, 188, 90, 89, 88]):  # 3 separated clusters
        pid = f"rb{i}"
        value[pid] = float(points)
        position[pid] = Position.RB
    return value, position


def test_assign_tiers_is_deterministic() -> None:
    value, position = _three_cluster_rb()
    assert assign_tiers(value, position) == assign_tiers(value, position)


def test_assign_tiers_orders_by_value_and_finds_the_three_clusters() -> None:
    value, position = _three_cluster_rb()
    tiers = assign_tiers(value, position)
    # Tier 1 = the best (highest-value) cluster; numbers increase as value falls.
    assert tiers["rb0"] == tiers["rb1"] == tiers["rb2"] == 1
    assert tiers["rb3"] == tiers["rb4"] == tiers["rb5"] == 2
    assert tiers["rb6"] == tiers["rb7"] == tiers["rb8"] == 3
    assert max(tiers.values()) <= 8  # default cap


def test_assign_tiers_respects_max_tiers_per_pos() -> None:
    # Ten well-separated singletons — enough real drops to want ten tiers, capped at two.
    value = {f"wr{i}": 300.0 - i * 30.0 for i in range(10)}
    value["wr0"] = 400.0  # one dominant drop, so the cap picks it first
    position = {f"wr{i}": Position.WR for i in range(10)}
    tiers = assign_tiers(value, position, max_tiers_per_pos=2)
    assert min(tiers.values()) == 1
    assert max(tiers.values()) == 2  # tiers are contiguous 1..K
    assert tiers["wr0"] == 1 and tiers["wr1"] == 2  # the cap keeps the LARGEST drop


def test_assign_tiers_handles_single_player() -> None:
    assert assign_tiers({"qb0": 5.0}, {"qb0": Position.QB}) == {"qb0": 1}


def test_assign_tiers_is_per_position() -> None:
    value = {"rb0": 200.0, "rb1": 100.0, "wr0": 200.0, "wr1": 100.0}
    position = {"rb0": Position.RB, "rb1": Position.RB, "wr0": Position.WR, "wr1": Position.WR}
    tiers = assign_tiers(value, position)
    # Each position tiered independently — every id present, tiers start at 1 per position.
    assert set(tiers) == set(value)
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


# --- The live regression (Tier 5) -------------------------------------------------------------
#
# Shape of the real board, which every test above misses: a position holds ~120 players and only
# the top ~20 clear replacement, because replacement IS the last startable player. So a tier
# boundary anywhere below that rank prices `max(0.0, 0.00 − 0.00)` — a populated cliff map whose
# every entry is 0.0. Measured on the live 2026 board on 2026-07-26: 8 boundaries across 510
# players, cliff 0.00 at all 8, `applied_cliff = α · 0.0` on every pick.


def _realistic_position_pool(
    *,
    count: int = 120,
    top: float = 300.0,
    gap: float = 40.0,
    decay: float = 2.0,
    replaced: int = 20,
) -> tuple[dict[str, float], dict[str, float], dict[str, Position]]:
    """One position's board: an elite outlier ``gap`` clear of a smooth tail, replacement at the
    last startable rank. Returns ``(value, mlv, position)`` with ``mlv = max(0, value − baseline)``
    — the empty-roster identity ``marginal_lineup_value`` actually computes."""
    value = {"rb0": top}
    for i in range(1, count):
        value[f"rb{i}"] = top - gap - (i - 1) * decay
    baseline = value[f"rb{replaced - 1}"]
    mlv = {pid: max(0.0, v - baseline) for pid, v in value.items()}
    return value, mlv, {pid: Position.RB for pid in value}


def test_tiers_price_the_top_of_board_gap_when_most_players_are_below_replacement() -> None:
    """The elite outlier is 40 points clear of the field — the single biggest fact about the
    position — so he must carry a cliff. Before Tier 5 the boundary landed at rank ~54, deep in
    sub-replacement territory, and priced to exactly 0.0."""
    value, mlv, position = _realistic_position_pool()

    bonuses = cliff_bonuses(assign_tiers(value, position), mlv, position)

    assert bonuses["rb0"] == pytest.approx(40.0), (
        "the last player before a 40-point drop must carry that drop as his cliff"
    )


def test_a_realistic_board_is_never_uniformly_zero() -> None:
    """The exact regression that hid for four tiers: a POPULATED cliff map is not a LIVE one."""
    value, mlv, position = _realistic_position_pool()

    bonuses = cliff_bonuses(assign_tiers(value, position), mlv, position)

    assert any(b > 0.0 for b in bonuses.values()), (
        "every boundary priced to 0.0 — the tier-cliff term is structurally inert"
    )


def test_tiers_follow_where_the_talent_drops_not_a_fixed_rank() -> None:
    """Two pools with the SAME rank order and the same 60-point drop, moved from rank 0 to rank
    10. The boundary has to move with the drop — which is only possible if the cut reads value."""
    early, mlv_early, position = _realistic_position_pool(count=40, gap=60.0, decay=1.0)
    late = {f"rb{i}": 300.0 - i for i in range(11)}  # smooth to rank 10 ...
    for i in range(11, 40):  # ... then the same 60-point drop
        late[f"rb{i}"] = 290.0 - 60.0 - (i - 11)
    mlv_late = {pid: max(0.0, v - late["rb19"]) for pid, v in late.items()}

    early_tiers, late_tiers = assign_tiers(early, position), assign_tiers(late, position)

    assert early_tiers["rb0"] == 1 and early_tiers["rb1"] == 2, "break belongs after rank 0"
    assert late_tiers["rb10"] == 1 and late_tiers["rb11"] == 2, "break belongs after rank 10"
    assert cliff_bonuses(early_tiers, mlv_early, position)["rb0"] == pytest.approx(60.0)
    assert cliff_bonuses(late_tiers, mlv_late, position)["rb10"] == pytest.approx(60.0)


def test_a_flat_position_is_one_tier_rather_than_a_manufactured_ladder() -> None:
    """K and DST are punt/stream positions (``punt_guard`` blocks them before R16/R17). The policy
    must not manufacture urgency where the board has none: with every step identical there is no
    drop that stands out, so the honest answer is a single tier and no cliff at all."""
    value = {f"k{i}": 90.0 - i for i in range(32)}
    position = {pid: Position.K for pid in value}
    mlv = {pid: max(0.0, v - value["k11"]) for pid, v in value.items()}

    tiers = assign_tiers(value, position)

    assert set(tiers.values()) == {1}, "a uniform board has no tier structure to find"
    assert max(cliff_bonuses(tiers, mlv, position).values()) == pytest.approx(0.0)
