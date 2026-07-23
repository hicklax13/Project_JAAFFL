"""E1 — measure the RB/WR flex split from live ADP (plan §12.3 item 1, Track J).

The engine allocates the league's flex demand between RB and WR (EngineParams.flex_split). The
prior is 8 RB / 4 WR, but non-PPR is likely more RB-heavy — so we MEASURE it: rank RB+WR by ADP,
take the top 60 startable (12 dedicated RB + 36 dedicated WR + 12 flex across 12 teams), and read
the flex composition off the overflow. The measurement is a pure function; the CLI wires it to FFC.
"""

from __future__ import annotations

from jaaffl.calibrate.flex_split import flex_pool_counts, measure_flex_split


def _rows(rb_adps: list[float], wr_adps: list[float], other=()):
    rows = [("RB", a) for a in rb_adps] + [("WR", a) for a in wr_adps] + list(other)
    return rows


def test_top60_overflow_beyond_dedicated_is_the_flex_split() -> None:
    # 20 RB (ADP 1..20) + 40 WR (ADP 21..60): the top 60 hold 20 RB, 40 WR.
    # flex_RB = 20 - 12 = 8; flex_WR = 12 - 8 = 4  (the 8RB/4WR prior, recovered).
    rows = _rows(list(range(1, 21)), list(range(21, 61)))
    assert measure_flex_split(rows) == {"RB": 8, "WR": 4}


def test_rb_heavy_board_sends_all_flex_to_rb() -> None:
    # 30 RB ahead of 30 WR in the top 60 → #RB-12 = 18, clamped to the 12 real flex slots.
    rows = _rows(list(range(1, 31)), list(range(31, 61)))
    assert measure_flex_split(rows) == {"RB": 12, "WR": 0}


def test_wr_heavy_board_sends_all_flex_to_wr() -> None:
    # Only 12 RB in the top 60 → no RB overflow → all 12 flex slots are WR.
    rows = _rows(list(range(1, 13)), list(range(13, 61)))
    assert measure_flex_split(rows) == {"RB": 0, "WR": 12}


def test_only_the_top60_by_adp_count() -> None:
    # Extra RBs buried past ADP 60 must NOT inflate the RB flex count.
    rows = _rows(list(range(1, 21)) + [200.0, 201.0, 202.0], list(range(21, 61)))
    assert measure_flex_split(rows) == {"RB": 8, "WR": 4}


def test_ignores_non_flex_positions_and_missing_adp() -> None:
    rows = _rows(
        list(range(1, 21)),
        list(range(21, 61)),
        other=[("QB", 5.0), ("TE", 6.0), ("K", 7.0), ("DST", 8.0), ("RB", None)],
    )
    assert measure_flex_split(rows) == {"RB": 8, "WR": 4}


def test_split_always_sums_to_the_flex_slot_count() -> None:
    for rb in range(0, 40):
        rows = _rows(list(range(1, rb + 1)), list(range(rb + 1, rb + 60)))
        split = measure_flex_split(rows)
        assert split["RB"] + split["WR"] == 12
        assert split["RB"] >= 0 and split["WR"] >= 0


def test_pool_counts_expose_the_raw_composition_behind_the_clamp() -> None:
    # 30 RB ahead of 30 WR: the raw top-60 pool is 30/30, but the flex split clamps to 12/0.
    # Surfacing the raw counts makes an aggressive calibration auditable.
    rows = _rows(list(range(1, 31)), list(range(31, 61)))
    assert flex_pool_counts(rows) == (30, 30)
    assert measure_flex_split(rows) == {"RB": 12, "WR": 0}
