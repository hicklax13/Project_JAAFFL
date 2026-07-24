"""E1 — measure the RB/WR flex split from ADP (plan §12.3 item 1; the highest-value calibration).

Across a 12-team league there are ``12`` dedicated RB slots, ``36`` dedicated WR slots, and ``12``
flex slots — ``60`` startable RB/WR in all. Rank RB+WR by ADP and take the top 60: whatever the
market drafts *beyond* the 12 dedicated RB and 36 dedicated WR is what it treats as flex. The
overflow's composition IS the flex split.

Non-PPR is expected to skew this more RB-heavy than the 8 RB / 4 WR prior — measuring is the point.
"""

from __future__ import annotations

from collections.abc import Iterable


def flex_pool_counts(
    rows: Iterable[tuple[str, float | None]],
    *,
    dedicated_rb: int = 12,
    dedicated_wr: int = 36,
    flex_slots: int = 12,
) -> tuple[int, int]:
    """Return ``(rb, wr)`` counts within the top ``dedicated_rb + dedicated_wr + flex_slots``
    startable RB/WR by ADP. The auditable raw input behind :func:`measure_flex_split` — non-RB/WR
    positions and ``None`` ADPs are ignored."""
    top = sorted(
        (
            (str(pos).upper(), adp)
            for pos, adp in rows
            if adp is not None and str(pos).upper() in ("RB", "WR")
        ),
        key=lambda row: row[1],
    )[: dedicated_rb + dedicated_wr + flex_slots]
    rb = sum(1 for pos, _ in top if pos == "RB")
    return rb, len(top) - rb


def measure_flex_split(
    rows: Iterable[tuple[str, float | None]],
    *,
    dedicated_rb: int = 12,
    dedicated_wr: int = 36,
    flex_slots: int = 12,
) -> dict[str, int]:
    """Measure the RB/WR flex allocation from ``(position, adp)`` rows.

    ``rows`` is any iterable of ``(position, adp)`` — non-RB/WR positions and ``None`` ADPs are
    ignored. Returns ``{"RB": flex_rb, "WR": flex_wr}`` that ALWAYS sums to ``flex_slots``:
    ``flex_rb = clamp(#RB_in_top_N − dedicated_rb, 0, flex_slots)`` and ``flex_wr`` is the
    remainder. The clamp+complement keeps the split valid even on a lopsided board (the raw
    ``#WR − dedicated_wr`` breaks when the top N holds fewer than ``dedicated_wr`` WRs).

    Defaults encode this league (12 teams · RB1/WR3/flex1): 12 dedicated RB, 36 dedicated WR,
    12 flex. The CLI derives them from ``config/league.json`` and passes live FFC ADP.
    """
    rb_in_top, _ = flex_pool_counts(
        rows, dedicated_rb=dedicated_rb, dedicated_wr=dedicated_wr, flex_slots=flex_slots
    )
    flex_rb = max(0, min(flex_slots, rb_in_top - dedicated_rb))
    return {"RB": flex_rb, "WR": flex_slots - flex_rb}
