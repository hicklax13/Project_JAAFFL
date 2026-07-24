"""Analytics series for the dashboard panels (GET /analytics) — pure math, no I/O."""

from __future__ import annotations

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.analytics import CURVE_DEPTH, value_curves
from tests.engine_fixtures import draft_state, make_context, teams


def _specs() -> list[dict]:
    """A board with all four charted positions plus a K (which must NOT be charted)."""
    specs: list[dict] = []
    for i in range(40):
        specs.append(
            {
                "pid": f"rb{i}",
                "pos": Position.RB,
                "mu": 300.0 - 5 * i,
                "adp": float(i + 1),
                "sd": 6.0,
            }
        )
    for i in range(40):
        specs.append(
            {
                "pid": f"wr{i}",
                "pos": Position.WR,
                "mu": 280.0 - 2 * i,
                "adp": float(41 + i),
                "sd": 6.0,
            }
        )
    for i in range(6):
        specs.append(
            {
                "pid": f"qb{i}",
                "pos": Position.QB,
                "mu": 320.0 - 8 * i,
                "adp": float(20 + i),
                "sd": 6.0,
            }
        )
    for i in range(6):
        specs.append(
            {
                "pid": f"te{i}",
                "pos": Position.TE,
                "mu": 200.0 - 15 * i,
                "adp": float(30 + i),
                "sd": 6.0,
            }
        )
    specs.append({"pid": "k0", "pos": Position.K, "mu": 130.0, "adp": 160.0, "sd": 6.0})
    return specs


def test_value_curves_rank_by_descending_vor() -> None:
    """Each curve is VOR-ranked best-first, and rank is 1-based and contiguous."""
    context = make_context(_specs())
    curves = {c.position: c for c in value_curves(context, draft_state(1))}

    rb = curves["RB"]
    assert [p.rank for p in rb.full] == list(range(1, len(rb.full) + 1))
    assert rb.full == sorted(rb.full, key=lambda p: p.vor, reverse=True)
    assert rb.full[0].player_id == "rb0"


def test_value_curves_exclude_k_and_dst() -> None:
    """K/DST go in the final rounds and their curves are flat — charting them is noise."""
    context = make_context(_specs())
    assert {c.position for c in value_curves(context, draft_state(1))} == {"QB", "RB", "WR", "TE"}


def test_value_curves_cap_depth_per_position() -> None:
    """Payload is bounded at CURVE_DEPTH players per position."""
    context = make_context(_specs())
    curves = {c.position: c for c in value_curves(context, draft_state(1))}
    assert len(curves["RB"].full) == CURVE_DEPTH


def test_remaining_drops_drafted_players_while_full_keeps_them() -> None:
    """The gap between `full` and `remaining` IS the positional run the panel visualises."""
    context = make_context(_specs())
    state = draft_state(
        3,
        picks=[
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t0", player_id="rb0"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t1", player_id="rb1"),
        ],
    )
    rb = {c.position: c for c in value_curves(context, state)}["RB"]

    assert [p.player_id for p in rb.full][:2] == ["rb0", "rb1"]
    assert "rb0" not in {p.player_id for p in rb.remaining}
    assert "rb1" not in {p.player_id for p in rb.remaining}
    assert rb.remaining[0].player_id == "rb2"
    assert rb.remaining[0].rank == 1  # remaining is re-ranked from 1, not a gapped slice


def test_vor_is_mu_minus_positional_baseline() -> None:
    """VOR is value over replacement, using the context's own baselines."""
    context = make_context(_specs())
    rb = {c.position: c for c in value_curves(context, draft_state(1))}["RB"]
    expected = context.mu["rb0"] - context.baselines[Position.RB]
    assert rb.full[0].vor == round(expected, 2)


def test_draft_order_is_never_inferred_from_team_count() -> None:
    """Guard: fixtures pass the REAL entered order; curves must not need one at all."""
    context = make_context(_specs())
    assert context.settings.draft_order == teams(12)
    assert value_curves(context, draft_state(1))  # value curves are order-independent
