"""nflverse xEP → league-points projection source (§3.1 `Capability.EXPECTED_POINTS`).

`league/xep.py` is the translation layer between nflverse's ``ff_opportunity`` weekly frame and
the engine's canonical vocabulary: expected stat columns → JAAFFL-canonical stat keys → league
points under the OWNER-VERIFIED ``jaaffl_scoring`` map, plus a real per-player σ derived from the
weekly actual-vs-expected residual (rather than a flat per-position constant).

Every row shape here mirrors the REAL frame verified against nflreadpy 0.1.5 (159 columns, weekly
grain, ``player_id`` = the raw GSIS id, weeks 1–22 incl. NFL playoffs).
"""

from __future__ import annotations

import math
import statistics

import pytest

from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.league.defaults import jaaffl_scoring
from jaaffl.league.xep import GAMES_HORIZON, MAX_FANTASY_WEEK, MIN_GAMES, expected_points_source

_RULES, _TIERS, _BONUSES = jaaffl_scoring()


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="cbs-test",
        team_count=12,
        roster_slots=[RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1)],
        scoring=_RULES,
        scoring_tiers=_TIERS,
        scoring_bonuses=_BONUSES,
    )


def _row(player_id: str, week: int, **stats: float) -> dict[str, object]:
    """One ff_opportunity weekly row. Unlisted stat columns are absent (the real frame carries
    nulls), so the mapper must tolerate missing/None columns."""
    return {"player_id": player_id, "week": float(week), "season": "2025", **stats}


def _weeks(player_id: str, n: int, **per_week: float) -> list[dict[str, object]]:
    return [_row(player_id, w, **per_week) for w in range(1, n + 1)]


def _source(rows, position, **kw):
    return expected_points_source(
        rows, settings=_settings(), position=position, drift_sigma={Position.RB: 60.0}, **kw
    )


# --- μ: expected columns → canonical stat keys → league points ----------------------------


def test_expected_columns_map_to_canonical_stats_and_score_under_the_jaaffl_map() -> None:
    """A full 17-game season of a fixed weekly xEP line scores the hand-computed JAAFFL total."""
    rows = _weeks(
        "00-0039139", 17, rush_yards_gained_exp=60.0, rec_yards_gained_exp=35.0,
        rush_touchdown_exp=0.45, rec_touchdown_exp=0.18,
    )  # fmt: skip
    src = _source(rows, {"gsis:00-0039139": Position.RB})
    # Season sums: 1020 rush yds, 595 rec yds, 7.65 rush TD, 3.06 rec TD.
    assert src.stat_lines["gsis:00-0039139"] == {
        "rushing_yards": pytest.approx(1020.0),
        "rushing_td": pytest.approx(7.65),
        "receiving_yards": pytest.approx(595.0),
        "receiving_td": pytest.approx(3.06),
        "passing_yards": pytest.approx(0.0),
        "passing_td": pytest.approx(0.0),
        "two_point": pytest.approx(0.0),
    }
    # JAAFFL: 0.1/yd rush + rec, 6/TD → 102.0 + 59.5 + 45.9 + 18.36
    assert src.points["gsis:00-0039139"] == pytest.approx(225.76)
    assert src.games["gsis:00-0039139"] == 17


def test_receptions_never_score_because_the_league_is_non_ppr() -> None:
    """The one place non-PPR is enforced: a huge ``receptions_exp`` contributes exactly zero."""
    rows = _weeks("00-0036322", 17, receptions_exp=9.0, rec_yards_gained_exp=100.0)
    src = _source(rows, {"gsis:00-0036322": Position.WR})
    assert "reception" not in src.stat_lines["gsis:00-0036322"]
    assert src.points["gsis:00-0036322"] == pytest.approx(170.0)  # 1700 yds × 0.1, catches = 0


def test_passing_yards_score_one_point_per_fifty() -> None:
    rows = _weeks("00-0034857", 17, pass_yards_gained_exp=250.0, pass_touchdown_exp=1.5)
    src = _source(rows, {"gsis:00-0034857": Position.QB})
    # 4250 pass yds × 0.02 = 85.0 ; 25.5 pass TD × 6 = 153.0
    assert src.points["gsis:00-0034857"] == pytest.approx(238.0)


def test_nfl_playoff_weeks_are_excluded_from_the_fantasy_season() -> None:
    """The real frame runs to week 22; fantasy scores weeks 1–18 only."""
    rows = _weeks("00-0039139", MAX_FANTASY_WEEK, rush_yards_gained_exp=100.0)
    rows += [_row("00-0039139", w, rush_yards_gained_exp=100.0) for w in (19, 20, 21, 22)]
    src = _source(rows, {"gsis:00-0039139": Position.RB})
    assert src.games["gsis:00-0039139"] == MAX_FANTASY_WEEK
    assert src.points["gsis:00-0039139"] == pytest.approx(MAX_FANTASY_WEEK * 10.0)


# --- honest degradation -------------------------------------------------------------------


def test_a_player_below_the_games_floor_is_omitted_rather_than_projected_from_noise() -> None:
    """Two games is not a season. Omitting the player degrades him to ECR-only (honestly
    marked) instead of blending a fabricated 2-game total into μ."""
    rows = _weeks("00-0039139", MIN_GAMES - 1, rush_yards_gained_exp=100.0)
    src = _source(rows, {"gsis:00-0039139": Position.RB})
    assert "gsis:00-0039139" not in src.points
    assert "gsis:00-0039139" not in src.stat_lines


def test_rows_outside_the_player_universe_are_skipped() -> None:
    """Null player ids and ids absent from the canonical universe never reach the engine."""
    rows = _weeks("00-0039139", 17, rush_yards_gained_exp=100.0)
    rows += _weeks("00-0000000", 17, rush_yards_gained_exp=100.0)  # not in the universe
    rows += [{"player_id": None, "week": 1.0, "rush_yards_gained_exp": 999.0}]
    src = _source(rows, {"gsis:00-0039139": Position.RB})
    assert set(src.points) == {"gsis:00-0039139"}


# --- σ: real per-player dispersion from the weekly residual -------------------------------


def test_sigma_anchors_on_the_measured_positional_drift_for_a_median_volatility_player() -> None:
    """A lone player is by definition the positional median, so his ratio is 1.0 and σ is
    exactly the measured year-over-year drift for his position."""
    rows = [
        _row("00-0039139", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0 + 50.0 * (w % 2))
        for w in range(1, 18)
    ]
    src = _source(rows, {"gsis:00-0039139": Position.RB})
    assert src.sigma["gsis:00-0039139"] == pytest.approx(60.0)


def test_a_volatile_player_gets_a_wider_sigma_than_a_steady_one_at_the_same_total() -> None:
    """The whole point of a per-player σ: identical season totals, different week-to-week
    residuals ⇒ different risk bands. The flat per-position floor cannot express this."""
    steady = [
        _row("00-0000001", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0)
        for w in range(1, 18)
    ]
    volatile = [
        _row(
            "00-0000002", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0 + 200.0 * (w % 2)
        )
        for w in range(1, 18)
    ]
    position = {"gsis:00-0000001": Position.RB, "gsis:00-0000002": Position.RB}
    src = _source(steady + volatile, position)
    assert src.sigma["gsis:00-0000002"] > src.sigma["gsis:00-0000001"]
    assert src.points["gsis:00-0000001"] == pytest.approx(src.points["gsis:00-0000002"])


def test_sigma_scales_the_positional_drift_by_measured_weekly_residual_volatility() -> None:
    """σ_p = drift[pos] × clamp(vol_p / median(vol_pos)). Hand-compute the ratio for a
    two-player pool so the formula is pinned, not merely 'bigger than'."""
    # Deltas chosen so both ratios (0.8 and 1.2) sit INSIDE the clamp — the clamp itself is
    # pinned by the next test, so this one measures the formula, not the guard rail.
    calm = [
        _row("00-0000001", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0 + 20.0 * (w % 2))
        for w in range(1, 18)
    ]
    rough = [
        _row("00-0000002", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0 + 30.0 * (w % 2))
        for w in range(1, 18)
    ]
    position = {"gsis:00-0000001": Position.RB, "gsis:00-0000002": Position.RB}
    src = _source(calm + rough, position)

    def vol(delta: float) -> float:
        residuals = [delta * (w % 2) * 0.1 for w in range(1, 18)]  # 0.1 pts per rushing yard
        return statistics.pstdev(residuals) * math.sqrt(GAMES_HORIZON)

    median_vol = statistics.median([vol(20.0), vol(30.0)])
    assert src.sigma["gsis:00-0000001"] == pytest.approx(60.0 * 0.8)
    assert src.sigma["gsis:00-0000001"] == pytest.approx(60.0 * vol(20.0) / median_vol)
    assert src.sigma["gsis:00-0000002"] == pytest.approx(60.0 * vol(30.0) / median_vol)


def test_the_volatility_ratio_is_clamped_so_one_freak_week_cannot_explode_sigma() -> None:
    calm = [
        _row(f"00-000000{i}", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0)
        for i in range(1, 4)
        for w in range(1, 18)
    ]
    freak = [
        _row(
            "00-0000009", w, rush_yards_gained_exp=100.0, rush_yards_gained=100.0 + 900.0 * (w % 2)
        )
        for w in range(1, 18)
    ]
    position = {f"gsis:00-000000{i}": Position.RB for i in (1, 2, 3, 9)}
    src = _source(calm + freak, position)
    assert src.sigma["gsis:00-0000009"] == pytest.approx(60.0 * 1.6)  # clamped, not unbounded
    assert src.sigma["gsis:00-0000001"] == pytest.approx(60.0 * 0.6)


def test_a_polars_frame_is_accepted_directly_from_the_provider() -> None:
    """The provider boundary returns a Polars frame (§4.3); the mapper takes it as-is so the
    engine never has to know that."""
    pl = pytest.importorskip("polars")
    rows = _weeks("00-0039139", 17, rush_yards_gained_exp=100.0)
    frame = pl.DataFrame(rows)
    src = _source(frame, {"gsis:00-0039139": Position.RB})
    assert src.points["gsis:00-0039139"] == pytest.approx(170.0)
