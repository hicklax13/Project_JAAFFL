"""Analytics series for the dashboard panels (GET /analytics) — pure math, no I/O."""

from __future__ import annotations

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.analytics import (
    CURVE_DEPTH,
    SURVIVAL_CANDIDATES,
    _total_picks,
    survival_curves,
    value_curves,
)
from jaaffl.engine.opponents import next_overall_pick
from tests.engine_fixtures import draft_state, jaaffl_settings, make_context, teams


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
        assert values[0] > values[-1]  # real decay, not a flat/degenerate curve


def test_survival_caps_candidate_count() -> None:
    """One line per candidate, capped so the chart stays readable — and the cap is actually
    reached when enough valid candidates exist, not just an upper bound nothing hits."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10))
    assert len(curves) == SURVIVAL_CANDIDATES


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


def test_total_picks_mirrors_the_sentinel_opponents_returns() -> None:
    """_total_picks duplicates opponents' private rounds formula (frozen, no public accessor).
    Pin it against the real sentinel so drift fails loudly instead of silently."""
    settings = jaaffl_settings(draft_order=teams(12))
    state = draft_state(204, my_team_id="t0")  # t0 has no picks left by the end of the draft
    sentinel = next_overall_pick(settings, state, horizon=1)
    assert _total_picks(settings) == sentinel - 1


def test_candidates_without_adp_are_backfilled_not_dropped() -> None:
    """Filtering must happen BEFORE the cap, or one unranked player shrinks the whole chart."""
    specs = _specs()
    # Highest-mu RB has no ADP/ECR at all (an unranked rookie the projections priced).
    specs.append({"pid": "rb_noadp", "pos": Position.RB, "mu": 999.0})
    context = make_context(specs)

    curves, _ = survival_curves(context, draft_state(10))

    assert "rb_noadp" not in {c.player_id for c in curves}
    assert len(curves) == SURVIVAL_CANDIDATES


def test_markers_deduplicate_when_exactly_one_pick_remains() -> None:
    """next_overall_pick clamps horizon=2 to your last pick when only one remains; without a
    dedupe that draws two overlapping marker lines instead of the single real one."""
    context = make_context(_specs())
    state = draft_state(192, my_team_id="t0")  # t0's last pick (193) is the only one left
    _, markers = survival_curves(context, state)
    assert markers == [193]


def test_board_conditioning_lowers_survival_through_the_public_surface() -> None:
    """R3 is unit-tested against the primitives in test_opponents.py
    (test_board_adp_shift_pulls_effective_adp_earlier_under_a_run), but this module's own promise
    is that the CHART agrees with the advice the engine gives — so the shift must also move
    survival the right way through THIS surface, not just the primitives underneath it.

    Worked example, mirroring that test's style: t0's picks are 1, 24, 25, 48, 49, ...; at
    current_overall_pick=55 the since-my-last-pick window is [50, 54] (all WR by ADP here, no RB
    expected). ``rb_target`` sits just past that window (ADP 56) so its own ADP never counts
    toward the window's "expected" tally in either scenario.
    """
    specs = _specs()
    specs.append({"pid": "rb_target", "pos": Position.RB, "mu": 130.0, "adp": 56.0, "sd": 6.0})
    context = make_context(specs)

    no_run = draft_state(55, my_team_id="t0", picks=[])
    # An opponent takes an RB inside the window — that position going faster than ADP expected.
    run = draft_state(
        55,
        my_team_id="t0",
        picks=[DraftPick(overall=52, round=5, pick_in_round=4, team_id="t5", player_id="rb0")],
    )

    curves_no_run, _ = survival_curves(context, no_run, candidates=["rb_target"])
    curves_run, _ = survival_curves(context, run, candidates=["rb_target"])

    point_no_run = curves_no_run[0].points[0]
    point_run = curves_run[0].points[0]
    assert point_no_run.pick == point_run.pick == 55  # same pick, isolating the shift's effect
    assert point_run.survival < point_no_run.survival
