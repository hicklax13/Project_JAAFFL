"""nflverse expected-points (xEP) → a real league-points projection source (§3.1).

This is the translation layer that turns nflverse's ``ff_opportunity`` frame into the engine's
canonical vocabulary. It exists because the projection blend previously had exactly one live
source — an ECR→points curve of the form ``300 − rank`` — so every μ in the system was linear in
expert rank rather than a projection of anything.

**Verified ground truth (nflreadpy 0.1.5, pulled 2026-07-25):**

* ``load_ff_opportunity(seasons=[2026])`` **raises** ``ValueError: Season must be between 2006 and
  2025``. xEP is a retrospective measure of realized opportunity, so the draft season never has
  rows — callers must request the last COMPLETED season (see ``build_projections``' ``xep_season``).
* The frame is **weekly** (6,054 rows for 2025 across 159 columns), carries both the realized
  ``X`` and the model's ``X_exp`` for every stat, and runs to **week 22** (NFL playoffs), which
  fantasy does not score.
* ``player_id`` is the raw **GSIS** id (``00-0039139``), so the canonical join is a literal
  ``gsis:`` prefix — the same scheme ``data/crosswalk.py`` assigns. No crosswalk lookup needed.
* Coverage is **skill positions only** (WR/RB/TE/QB); there is no DST row and one stray K row, so
  K/DST honestly degrade to the ECR source rather than being fabricated here.

**Why the season SUM and not a per-game rate.** Backtested both candidates on two independent
year-pairs (2024 xEP → realized 2025, and 2023 → 2024), scored under the JAAFFL map. The season
sum is near-unbiased and no wider; ``rate × 17`` systematically overshoots:

2024 xEP → realized 2025, via ``scripts/measure_projection_sigma.py`` (run 2026-07-25):

| | RB bias / SD | WR bias / SD | QB bias / SD |
|---|---|---|---|
| season sum | −12.1 / 54.6 | −12.8 / 42.4 | −27.4 / 103.9 |
| rate × 17 | −31.2 / 58.2 | −29.9 / 41.2 | −79.3 / 99.6 |

Same ordering in the 2023→2024 pair. So μ uses the sum, and a player under :data:`MIN_GAMES` is
**omitted** (degrading him to ECR-only, honestly marked in ``PlayerProjection.sources``) rather
than extrapolated from a handful of snaps.

**σ is real and per-player.** Those same backtests measure the year-over-year projection error by
position (the ``drift_sigma`` this module is handed, wired in ``engine/precompute.py``). Each
player's own weekly actual-vs-expected residual then scales that positional anchor, so two RBs
with the same season total but different week-to-week volatility get different risk bands — which
a flat per-position constant cannot express.

**Known limitation — clamp saturation at the top of the board.** The volatility ratio measures
absolute point swings, and elite players handle the most volume, so they cluster at
:data:`VOL_RATIO_MAX`. Measured on the live 2026 board: of the top 200 by ECR, **47 sit at the
max clamp, 3 at the min, and 137 land in between** (27% saturated). Those 47 therefore share a
per-position σ again — arguably correct (they *are* uniformly high-variance in raw points) but it
does mean σ discriminates least exactly where the early rounds are decided. Cross-source
disagreement can still push an individual above the clamp. Left as-is deliberately rather than
widened by feel: E2 (``scripts/tune_engine_params.py``) is the instrument that should decide,
since σ only reaches Score through the tunable ``λ·σ`` risk term.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from jaaffl.domain import LeagueSettings, Position
from jaaffl.league.scoring import league_points

# Fantasy scores the NFL regular season only; the frame runs to week 22 (verified).
MAX_FANTASY_WEEK = 18
# Below this many games the season sum is not a projection, it is noise — omit the player.
MIN_GAMES = 6
# A healthy season under the 18-week schedule (one bye).
GAMES_HORIZON = 17
# Bounds on the per-player volatility multiplier, so one freak week cannot dominate σ.
VOL_RATIO_MIN = 0.6
VOL_RATIO_MAX = 1.6

# ``ff_opportunity.player_id`` is the raw GSIS id; canonical ids are ``gsis:<gsis_id>``
# (data/crosswalk.py ``player_from_playerid_row``). Keep the two in lockstep.
_CANONICAL_PREFIX = "gsis:"

# JAAFFL-canonical stat key → (expected column, realized column). Only stats the owner-verified
# ``jaaffl_scoring`` map actually scores appear here:
#   * ``receptions_exp`` is deliberately ABSENT — the league is non-PPR, a catch is worth 0.
#   * interceptions and fumbles are deliberately ABSENT — JAAFFL applies NO offensive turnover
#     penalty, so scoring them would invent a rule the league does not have.
_STAT_COLUMNS: dict[str, tuple[str, str]] = {
    "passing_yards": ("pass_yards_gained_exp", "pass_yards_gained"),
    "passing_td": ("pass_touchdown_exp", "pass_touchdown"),
    "rushing_yards": ("rush_yards_gained_exp", "rush_yards_gained"),
    "rushing_td": ("rush_touchdown_exp", "rush_touchdown"),
    "receiving_yards": ("rec_yards_gained_exp", "rec_yards_gained"),
    "receiving_td": ("rec_touchdown_exp", "rec_touchdown"),
}
# Two-point conversions arrive split across the three phases; JAAFFL scores them all at 2.
_TWO_POINT = "two_point"
_TWO_POINT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pass_two_point_conv_exp", "pass_two_point_conv"),
    ("rec_two_point_conv_exp", "rec_two_point_conv"),
    ("rush_two_point_conv_exp", "rush_two_point_conv"),
)

CANONICAL_STATS: tuple[str, ...] = (*_STAT_COLUMNS, _TWO_POINT)


@dataclass(frozen=True, slots=True)
class XepSource:
    """One projection source, keyed by canonical ``player_id`` — the crossing contract (§4.7)."""

    points: dict[str, float] = field(default_factory=dict)  # season league points under the map
    stat_lines: dict[str, dict[str, float]] = field(default_factory=dict)  # canonical stat keys
    sigma: dict[str, float] = field(default_factory=dict)  # per-player season-points σ
    games: dict[str, int] = field(default_factory=dict)  # weeks that survived the filters


def _value(row: Mapping[str, object], column: str) -> float:
    """A missing or null column is 0.0 — the real frame is sparsely populated per position."""
    raw = row.get(column)
    return 0.0 if raw is None else float(raw)  # type: ignore[arg-type]


def _named_rows(rows: object) -> Iterable[Mapping[str, object]]:
    """Accept a Polars frame straight from the provider (§4.3) or any iterable of row mappings,
    so the engine never has to know which one it is holding."""
    iter_rows = getattr(rows, "iter_rows", None)
    return iter_rows(named=True) if callable(iter_rows) else rows  # type: ignore[return-value]


def _stat_lines(row: Mapping[str, object]) -> tuple[dict[str, float], dict[str, float]]:
    """Split one weekly row into its (expected, realized) canonical stat lines."""
    expected = {stat: _value(row, cols[0]) for stat, cols in _STAT_COLUMNS.items()}
    realized = {stat: _value(row, cols[1]) for stat, cols in _STAT_COLUMNS.items()}
    expected[_TWO_POINT] = sum(_value(row, exp) for exp, _ in _TWO_POINT_COLUMNS)
    realized[_TWO_POINT] = sum(_value(row, act) for _, act in _TWO_POINT_COLUMNS)
    return expected, realized


def _volatility_ratio(vol: float, median: float) -> float:
    """Clamped ratio of a player's weekly residual σ to his position's median. A degenerate
    position (every measured player perfectly on-model) puts the outlier at the ceiling and
    everyone else at the floor, rather than dividing by zero."""
    if median <= 0.0:
        return VOL_RATIO_MAX if vol > 0.0 else VOL_RATIO_MIN
    return max(VOL_RATIO_MIN, min(VOL_RATIO_MAX, vol / median))


def expected_points_source(
    rows: object,
    *,
    settings: LeagueSettings,
    position: Mapping[str, Position],
    drift_sigma: Mapping[Position, float],
    max_week: int = MAX_FANTASY_WEEK,
    min_games: int = MIN_GAMES,
    games_horizon: int = GAMES_HORIZON,
) -> XepSource:
    """Fold weekly ``ff_opportunity`` rows into a canonical-keyed projection source.

    ``position`` is the canonical player universe — it is authoritative, so a row for a player the
    league cannot roster (or whose id never resolved) is skipped rather than passed through raw.
    ``drift_sigma`` is the measured per-position year-over-year projection error that anchors σ.
    """
    expected_totals: dict[str, dict[str, float]] = {}
    residuals: dict[str, list[float]] = {}
    games: dict[str, int] = {}

    for row in _named_rows(rows):
        raw_id = row.get("player_id")
        if raw_id is None:
            continue
        pid = f"{_CANONICAL_PREFIX}{raw_id}"
        pos = position.get(pid)
        if pos is None:
            continue
        week = row.get("week")
        if week is None or not 1 <= int(week) <= max_week:
            continue

        expected, realized = _stat_lines(row)
        totals = expected_totals.setdefault(pid, dict.fromkeys(CANONICAL_STATS, 0.0))
        for stat, value in expected.items():
            totals[stat] += value
        games[pid] = games.get(pid, 0) + 1
        residuals.setdefault(pid, []).append(
            _points(realized, settings, pos) - _points(expected, settings, pos)
        )

    kept = {pid: line for pid, line in expected_totals.items() if games[pid] >= min_games}
    points = {pid: _points(line, settings, position[pid]) for pid, line in kept.items()}

    # Per-player weekly residual σ, scaled to a season, then normalized within its position.
    volatility = {
        pid: statistics.pstdev(residuals[pid]) * math.sqrt(games_horizon)
        for pid in kept
        if len(residuals[pid]) >= 2
    }
    medians: dict[Position, float] = {}
    for pos in {position[pid] for pid in volatility}:
        medians[pos] = statistics.median(
            [v for pid, v in volatility.items() if position[pid] is pos]
        )
    sigma = {
        pid: drift_sigma[position[pid]] * _volatility_ratio(vol, medians[position[pid]])
        for pid, vol in volatility.items()
        if position[pid] in drift_sigma
    }

    return XepSource(
        points=points,
        stat_lines={pid: dict(line) for pid, line in kept.items()},
        sigma=sigma,
        games={pid: games[pid] for pid in kept},
    )


def _points(stat_line: Mapping[str, float], settings: LeagueSettings, position: Position) -> float:
    return league_points(
        stat_line,
        settings.scoring,
        position,
        tiers=settings.scoring_tiers,
        bonuses=settings.scoring_bonuses,
    )
