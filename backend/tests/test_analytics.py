"""Analytics series for the dashboard panels (GET /analytics) — pure math, no I/O."""

from __future__ import annotations

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.analytics import CURVE_DEPTH, SURVIVAL_CANDIDATES, survival_curves, value_curves
from tests.engine_fixtures import draft_state, jaaffl_settings, make_context


def _specs() -> list[dict]:
    """A board with all four charted positions plus a K and DST (neither must be charted)."""
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
    specs.append({"pid": "dst0", "pos": Position.DST, "mu": 90.0, "adp": 165.0, "sd": 6.0})
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


def test_value_curves_do_not_require_a_draft_order() -> None:
    """Unlike survival/VONA, value curves are pure VOR math — no snake order needed at all."""
    context = make_context(_specs(), settings=jaaffl_settings(draft_order=None))
    assert value_curves(context, draft_state(1))


def test_survival_is_monotonically_decreasing_and_bounded() -> None:
    """A player can only get less available as picks pass; probabilities stay in [0, 1]."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10))

    assert curves, "expected survival curves for the default candidate set"
    for curve in curves:
        values = [p.survival for p in curve.points]
        assert all(0.0 <= v <= 1.0 for v in values)
        assert values == sorted(values, reverse=True)


def test_survival_caps_candidate_count() -> None:
    """One line per candidate, capped so the chart stays readable."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10))
    assert len(curves) <= SURVIVAL_CANDIDATES


def test_explicit_candidates_are_honoured_in_order() -> None:
    """The dashboard passes the ids it already has, so the lines match the ranked picks shown."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10), candidates=["wr3", "rb7"])
    assert [c.player_id for c in curves] == ["wr3", "rb7"]


def test_unknown_and_drafted_candidate_ids_are_ignored_not_fatal() -> None:
    """A stale id from the client must degrade a line, never 500 the endpoint."""
    context = make_context(_specs())
    state = draft_state(
        3, picks=[DraftPick(overall=1, round=1, pick_in_round=1, team_id="t0", player_id="rb0")]
    )
    curves, _ = survival_curves(context, state, candidates=["rb0", "no-such-player", "wr1"])
    assert [c.player_id for c in curves] == ["wr1"]


def test_markers_come_from_the_real_entered_draft_order() -> None:
    """config/league.json forbids inferring snake order; markers must read settings.draft_order."""
    context = make_context(_specs())
    state = draft_state(5, my_team_id="t0")
    _, markers = survival_curves(context, state)

    assert len(markers) == 2
    assert all(m > state.current_overall_pick for m in markers)
    assert markers == sorted(markers)


def test_survival_domain_spans_current_pick_through_second_marker_plus_tail() -> None:
    """The curve must visibly continue past your second turn, not stop on the marker."""
    context = make_context(_specs())
    state = draft_state(5, my_team_id="t0")
    curves, markers = survival_curves(context, state)

    picks = [p.pick for p in curves[0].points]
    assert picks[0] == state.current_overall_pick
    assert picks == list(range(picks[0], picks[-1] + 1))  # every integer pick, no gaps
    assert picks[-1] > markers[-1]


def test_survival_degrades_when_draft_order_is_unknown() -> None:
    """Pre-draft (no order / no team) must return empty markers rather than raising."""
    context = make_context(_specs(), settings=jaaffl_settings(draft_order=None))
    state = draft_state(1, my_team_id="t0")
    curves, markers = survival_curves(context, state)
    assert markers == []
    assert curves  # curves still render over the fallback span


def test_markers_are_empty_once_my_picks_are_exhausted() -> None:
    """next_overall_pick returns a far-future sentinel when you have no picks left; charting it
    would draw markers and points past the literal end of the draft."""
    context = make_context(_specs())
    state = draft_state(200, my_team_id="t0")  # t0's last pick is overall 193
    curves, markers = survival_curves(context, state)

    assert markers == []
    assert all(point.pick <= 204 for curve in curves for point in curve.points)
