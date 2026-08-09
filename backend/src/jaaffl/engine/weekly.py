"""A WEEKLY, correlated, absence-aware season model — the objective's missing axis (Tier 11).

``simulate.sample_season_outcomes`` draws **one independent season total per player**. Three things
follow, and the engine has been unable to see any of them for six tiers:

* ``mean_lineup_value_objective`` prices a bench player at exactly **0** — 8 of this league's 17
  picks — while ``roster_season_values`` re-optimises the lineup with **perfect hindsight** of the
  realized season. They BRACKET bench value and neither is right.
* ``bye_stack`` and ``sos`` have no week to attach to.
* ``handcuff_synergy`` has no cross-player dependence to attach to.

This module supplies the axis. **Every parameter is MEASURED** from the same free nflverse
``ff_opportunity`` frame ``league/xep.py`` already reads — weekly rows, seasons 2023-2025, scored
under the owner-verified JAAFFL map — never chosen by feel.

**The season marginal is preserved exactly.** Given per-week zero-production probability ``q`` and
``n`` playable weeks (the schedule minus his bye)::

    m   = mu / (n * (1 - q))                              # per-week mean WHEN PRESENT
    s^2 = (sigma^2 / n - q * (1 - q) * m^2) / (1 - q)     # per-week SD when present

yields ``E[sum_w] = mu`` and ``Var[sum_w] = sigma^2``; correlation changes only the JOINT. That is
what makes a difference between this objective and the season objective attributable to STRUCTURE
(weeks, byes, absence, correlation, ex-ante lineups) rather than to a changed scale — the trap
Tier 9 fell into when the fixture and the real board turned out to be measuring different things.
Verified on the real board 2026-08-09: **0 of 305** players hit ``s^2 < 0``, and the production SD
lands at 0.68-1.17x (median 1.07) of ``sigma / sqrt(n)``.

**``sigma_week = sigma_season / sqrt(n)`` is not an invention.** ``league/xep.py`` builds season
sigma as ``pstdev(weekly residuals) * sqrt(GAMES_HORIZON)``, so this is that transform inverted.

⚠️ **The absence process REALLOCATES the board's sigma; it does not add to it.** ``league/xep.py``
measures weekly residuals only over weeks a player actually appeared, so the shipped sigma EXCLUDES
missed-game variance and is therefore too small. Correcting THAT would supersede every number in the
project again and is recorded in ``ROADMAP.md`` as open; this module only gets the STRUCTURE of the
existing sigma right.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jaaffl.domain import Position
from jaaffl.engine.optimize import StartingSlot
from jaaffl.league.xep import MAX_FANTASY_WEEK

if TYPE_CHECKING:
    import numpy as np

    from jaaffl.engine.simulate import SimContext

# The fantasy calendar, taken from the one place that already states it rather than restated here.
REGULAR_SEASON_WEEKS = MAX_FANTASY_WEEK

# Measured 2026-08-09 from nflverse ff_opportunity, seasons 2023 + 2024 + 2025 pooled, standardised
# weekly residuals of same-team pairs, scored under the owner-verified JAAFFL map.
#
# ⚠️ THIS IS THE **CONDITIONAL** TABLE — the correlation of production in weeks BOTH players
# actually played — because that is the quantity this model applies. The shock below is drawn only
# for present weeks; absence zeroes a player independently. Calibrating the shock with the
# absence-AWARE correlation instead would double-count the zeros and under-produce the real thing.
#
#   pair     rho      se       n       2023 / 2024 / 2025      significant?
#   QBxWR   +0.2681  0.0148   5374    +0.228 / +0.274 / +0.309    yes
#   QBxTE   +0.2323  0.0208   2603    +0.252 / +0.204 / +0.241    yes
#   QBxQB   +0.1198  0.0945    139    +0.103 / +0.152 / +0.114    no
#   QBxRB   +0.0523  0.0162   3815    +0.080 / +0.046 / +0.030    yes
#   RBxRB   +0.0327  0.0194   2845    +0.056 / +0.006 / +0.036    no
#   RBxWR   -0.0177  0.0089  12279    -0.041 / -0.004 / -0.005    yes
#   RBxTE   +0.0149  0.0127   6017    +0.038 / +0.004 / +0.004    no
#   WRxWR   +0.0101  0.0119   6699    -0.015 / +0.021 / +0.030    no
#   TExWR   -0.0013  0.0107   8421    -0.017 / +0.000 / +0.014    no
#   TExTE   -0.0030  0.0292   1209    -0.015 / +0.047 / -0.034    no
#   control (DIFFERENT team, same week): -0.0128 (se 0.0088) — what says this is a team effect
#   and not a league-wide week effect.
#
# ⚠️ THE ENTIRE SAME-TEAM STRUCTURE IS THE QUARTERBACK. QB x pass-catcher is ~+0.25 and every pair
# without a QB is inside +/-0.035 and not significant. The obvious model — one shared "team factor"
# per team — is therefore WRONG: it would give WR x WR the same +0.25 it gives QB x WR, where the
# data says +0.010. Applying the measured pair table directly, via a per-team Cholesky, assumes no
# factor structure the data does not support.
#
# The ABSENCE-AWARE table (a week with no row scoring 0.0, i.e. what a lineup records) was measured
# separately and is NOT used as an input — it is the out-of-sample CHECK on the assembled model,
# pinned by ``test_weekly.py``: QBxWR +0.1793, QBxTE +0.1496, QBxRB +0.0277, everything else inside
# +/-0.03, different-team control +0.0008.
#
# One thing this model does NOT reproduce: absence-aware QB x QB is **-0.2825**, because only one
# quarterback starts. That is an ABSENCE mechanism, and absences here are independent across
# players, so the model carries the conditional +0.12 instead. Same limitation, measured, as the
# handcuff — see ``test_harness_fidelity.py``.
#
# K and DST are absent on purpose: ff_opportunity covers skill positions only, so there is nothing
# measured to use, and fabricating a number is the defect this project keeps finding.
SAME_TEAM_RHO: dict[frozenset[Position], float] = {
    frozenset({Position.QB, Position.WR}): 0.2681,
    frozenset({Position.QB, Position.TE}): 0.2323,
    frozenset({Position.QB}): 0.1198,
    frozenset({Position.QB, Position.RB}): 0.0523,
    frozenset({Position.RB}): 0.0327,
    frozenset({Position.RB, Position.WR}): -0.0177,
    frozenset({Position.RB, Position.TE}): 0.0149,
    frozenset({Position.WR}): 0.0101,
    frozenset({Position.TE, Position.WR}): -0.0013,
    frozenset({Position.TE}): -0.0030,
}

# Measured the same way: the share of weeks INSIDE a player's own [first seen, last seen] window
# with no ff_opportunity row, over players with >= 6 scored weeks.
#
#   QB 0.1727 (n=2044)   RB 0.1731 (n=4599)   WR 0.2336 (n=7115)   TE 0.2885 (n=3785)
#
# Called ZERO PRODUCTION rather than injury on purpose — the frame carries a row only where there
# was opportunity, so a healthy receiver who saw no targets counts here. For a starting lineup the
# two are the same event. K and DST are 0.0 for the same reason they carry no correlation.
ZERO_PRODUCTION_RATE: dict[Position, float] = {
    Position.QB: 0.1727,
    Position.RB: 0.1731,
    Position.WR: 0.2336,
    Position.TE: 0.2885,
    Position.K: 0.0,
    Position.DST: 0.0,
}

_PD_TOLERANCE = 1e-9


@dataclass(frozen=True)
class WeeklyOutcomes:
    """``n_draws`` sampled seasons on a week axis.

    ``weekly[d, w, index[pid]]`` is ``pid``'s realized points in week ``w`` of draw ``d``, and
    ``available[d, w, index[pid]]`` is whether he played at all (False on a bye or a
    zero-production week). Availability is carried EXPLICITLY rather than inferred from a 0.0
    score: a present player can legitimately score 0.0, and a lineup rule that confused the two
    would quietly start absent players.

    Sampled ONCE for the whole pool and keyed by player id, so a player realizes the SAME season on
    every roster he appears on — the common random numbers that make the 12-slot paired comparison
    sensitive enough to see a parameter change rather than sampling noise.
    """

    order: tuple[str, ...]
    index: Mapping[str, int]
    weekly: np.ndarray  # (n_draws, weeks, n_players)
    available: np.ndarray  # (n_draws, weeks, n_players), bool

    def season_totals(self) -> np.ndarray:
        """``(n_draws, n_players)`` — the quantity ``sample_season_outcomes`` draws directly."""
        return self.weekly.sum(axis=1)


@dataclass(frozen=True)
class WeeklyModel:
    """Per-player weekly parameters plus the per-team correlation factors, ready to sample."""

    order: tuple[str, ...]
    index: Mapping[str, int]
    position: Mapping[str, Position]
    weeks: int
    production_mean: Mapping[str, float]  # m: per-week mean WHEN PRESENT
    production_sd: Mapping[str, float]  # s: per-week SD when present
    absent_rate: Mapping[str, float]  # q: per-week zero-production probability
    plays_week: np.ndarray  # (weeks, n_players) bool — the bye calendar
    groups: Sequence[tuple[tuple[int, ...], np.ndarray]]  # (member column indices, Cholesky factor)
    # Players whose board sigma cannot absorb the absence process — ``s**2`` solved negative and was
    # clamped to 0, leaving them with a deterministic weekly score and no correlation. SURFACED
    # rather than silent, because a silently variance-free player is exactly the kind of degradation
    # this project keeps discovering six tiers late. Measured 2026-08-09: **0 of 305** on the real
    # board (production sd 0.68-1.17x of ``sigma/sqrt(n)``), **8 of 178** on the demo fixture, whose
    # synthetic value curve is steeper against the same real sigma anchors (median mu/sigma at WR
    # 3.9 on the fixture vs 2.4 on the real board).
    degenerate: tuple[str, ...] = ()

    @classmethod
    def from_context(
        cls,
        ctx: SimContext,
        *,
        bye_week: Mapping[str, int] | None = None,
        team: Mapping[str, str] | None = None,
        same_team_rho: Mapping[frozenset[Position], float] | None = None,
        zero_production_rate: Mapping[Position, float] | None = None,
        weeks: int = REGULAR_SEASON_WEEKS,
    ) -> WeeklyModel:
        """Solve each player's weekly parameters and factor each team's correlation matrix.

        ``bye_week`` and ``team`` default to the ones the context carries (empty on the fixture
        pool, real on a precompute-backed one). A player with no resolvable team is his own group,
        so he is simply independent rather than silently pooled with other unknowns.
        """
        import numpy as np

        bye_week = ctx.bye_week if bye_week is None else bye_week
        team = ctx.nfl_team if team is None else team
        rho = SAME_TEAM_RHO if same_team_rho is None else same_team_rho
        rates = ZERO_PRODUCTION_RATE if zero_production_rate is None else zero_production_rate

        order = tuple(sorted(ctx.value))
        index = {pid: i for i, pid in enumerate(order)}
        plays = np.ones((weeks, len(order)), dtype=bool)
        production_mean: dict[str, float] = {}
        production_sd: dict[str, float] = {}
        absent: dict[str, float] = {}
        degenerate: list[str] = []

        for pid in order:
            pos = ctx.position[pid]
            bye = bye_week.get(pid)
            if bye is not None and 1 <= int(bye) <= weeks:
                plays[int(bye) - 1, index[pid]] = False
            n = int(plays[:, index[pid]].sum())
            q = float(rates.get(pos, 0.0))
            mu, sigma = float(ctx.value[pid]), float(ctx.sigma.get(pid, 0.0))
            m = mu / (n * (1.0 - q)) if n and q < 1.0 else 0.0
            # Solve s so that Var[sum_w] == sigma**2 EXACTLY under the absence process. A negative
            # solution means the absence process alone already exceeds the board's season sigma;
            # measured on the real board that happens for 0 of 300 players, so the clamp is a
            # guard, not a regime — but it must never silently produce a NaN.
            variance = (sigma**2 / n - q * (1.0 - q) * m**2) / (1.0 - q) if n and q < 1.0 else 0.0
            if variance < 0.0 and sigma > 0.0:
                degenerate.append(pid)
            production_mean[pid] = m
            production_sd[pid] = float(np.sqrt(max(0.0, variance)))
            absent[pid] = q

        groups: list[tuple[tuple[int, ...], np.ndarray]] = []
        by_team: dict[str, list[str]] = defaultdict(list)
        for pid in order:
            code = team.get(pid) or ""
            by_team[code or f"__solo__{pid}"].append(pid)
        for code, members in sorted(by_team.items()):
            cols = tuple(index[pid] for pid in members)
            size = len(cols)
            if size == 1:
                groups.append((cols, np.ones((1, 1))))
                continue
            matrix = np.eye(size)
            for a in range(size):
                for b in range(a + 1, size):
                    pair = frozenset({ctx.position[members[a]], ctx.position[members[b]]})
                    matrix[a, b] = matrix[b, a] = float(rho.get(pair, 0.0))
            smallest = float(np.linalg.eigvalsh(matrix).min())
            if smallest <= _PD_TOLERANCE:
                # Deliberately NOT repaired to the nearest PSD matrix. A silent projection is an
                # unmeasured change to the model wearing a numerical-hygiene costume, and this
                # project's recurring defect is measuring something other than what it claims.
                # Measured on the real board the worst minimum eigenvalue over 32 teams is 0.1698.
                raise ValueError(
                    f"same-team correlation for {code!r} ({size} players) is not positive "
                    f"definite (min eigenvalue {smallest:.6f}); fix the measured table rather "
                    f"than repairing the matrix"
                )
            groups.append((cols, np.linalg.cholesky(matrix)))

        return cls(
            order=order,
            index=index,
            position=dict(ctx.position),
            weeks=weeks,
            production_mean=production_mean,
            production_sd=production_sd,
            absent_rate=absent,
            plays_week=plays,
            groups=groups,
            degenerate=tuple(degenerate),
        )

    def sample(self, *, n_draws: int, seed: int) -> WeeklyOutcomes:
        """Draw ``n_draws`` correlated, absence-aware seasons on the week axis. Reproducible."""
        import numpy as np

        rng = np.random.default_rng(seed)
        n = len(self.order)
        shocks = rng.standard_normal((n_draws, self.weeks, n))
        correlated = np.empty_like(shocks)
        for cols, factor in self.groups:
            idx = np.asarray(cols, dtype=int)
            correlated[:, :, idx] = shocks[:, :, idx] @ factor.T

        m = np.array([self.production_mean[pid] for pid in self.order])
        s = np.array([self.production_sd[pid] for pid in self.order])
        q = np.array([self.absent_rate[pid] for pid in self.order])

        # A bye is a hard zero; a zero-production week is drawn independently per player-week. The
        # two are folded into ONE availability mask so the lineup rule has a single question to ask.
        present = rng.random((n_draws, self.weeks, n)) >= q
        available = present & self.plays_week[None, :, :]
        weekly = np.where(available, m + s * correlated, 0.0)
        return WeeklyOutcomes(
            order=self.order, index=self.index, weekly=weekly, available=available
        )


def _slot_plan(slots: Sequence[StartingSlot]) -> tuple[list[Position], list[frozenset[Position]]]:
    dedicated = [next(iter(s.eligible)) for s in slots if len(s.eligible) == 1]
    flex = [s.eligible for s in slots if len(s.eligible) > 1]
    return dedicated, flex


def weekly_lineup_totals(
    roster: Sequence[str],
    outcomes: WeeklyOutcomes,
    ctx: SimContext,
    *,
    hindsight: bool = False,
) -> np.ndarray:
    """``(n_draws,)`` season total of ``roster``, summed over per-week starting lineups.

    ``hindsight=False`` (the default and the honest rule) sets each week's lineup **ex ante**: the
    best legal nine by ``mu`` among the players available that week, scored on what they then
    realized. No hindsight anywhere. It is therefore a **lower** bound on bench value — a real
    manager also reacts to in-season information — and that is stated rather than glossed.

    ``hindsight=True`` ranks by the realized week instead, reproducing the per-week analogue of
    ``roster_season_values``' whole-season re-optimisation. Kept so the bracket can be REPORTED
    rather than assumed: ``mean_lineup_value_objective`` (bench = 0) · ex-ante weekly · weekly
    hindsight, in increasing order of what a bench is allowed to be worth.

    The greedy — fill each dedicated slot with the best available player of its position, then let
    each flex slot take the best remaining eligible — is the same rule ``optimize.lineup_value``
    uses, and optimal for this roster's "dedicated + one WR/RB flex" structure for the reason that
    function's docstring gives. Scored as a FINAL roster: no replacement phantoms, because the
    draft is over and there is no pick left to draft one.

    Vectorised over ``(draw, week)``. Selection is a ``cumsum`` over the player axis, which turns
    "the r-th player still available at this position" into one ``argsort`` plus two gathers.
    Measured 2026-08-09: 2.53 ms per roster-scoring at 400 draws x 18 weeks, so a 4-arm 5-block
    tournament costs about a minute — comparable to the season objective it sits beside, which it
    has to be or replicates stop being affordable.
    """
    import numpy as np

    ids = [pid for pid in roster if pid in outcomes.index]
    draws, weeks = outcomes.weekly.shape[0], outcomes.weekly.shape[1]
    if not ids:
        return np.zeros(draws)

    by_position: dict[Position, list[int]] = defaultdict(list)
    for pid in ids:
        by_position[ctx.position[pid]].append(outcomes.index[pid])

    realized: dict[Position, np.ndarray] = {}
    ranked: dict[Position, np.ndarray] = {}
    ranked_mu: dict[Position, np.ndarray] = {}
    depth: dict[Position, np.ndarray] = {}
    for pos, cols in by_position.items():
        idx = np.asarray(cols, dtype=int)
        values = outcomes.weekly[:, :, idx]
        alive = outcomes.available[:, :, idx]
        mu = np.array([ctx.value[outcomes.order[c]] for c in cols])
        # Rank available players best-first; unavailable ones sink below every real key so they can
        # never be selected, and `depth` records how many real ones there are that week.
        key = values if hindsight else np.broadcast_to(mu, values.shape)
        order = np.argsort(np.where(alive, key, -np.inf), axis=2)[:, :, ::-1]
        realized[pos] = values
        ranked[pos] = order
        ranked_mu[pos] = np.take_along_axis(np.broadcast_to(mu, values.shape), order, axis=2)
        depth[pos] = alive.sum(axis=2)

    used: dict[Position, np.ndarray] = {
        pos: np.zeros((draws, weeks), dtype=int) for pos in by_position
    }
    total = np.zeros((draws, weeks))

    def peek(pos: Position) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(realized value, mu, is-there-one) of the next unused available player at ``pos``."""
        if pos not in by_position:
            zeros = np.zeros((draws, weeks))
            return zeros, zeros, np.zeros((draws, weeks), dtype=bool)
        rank = used[pos]
        ok = rank < depth[pos]
        safe = np.minimum(rank, ranked[pos].shape[2] - 1)[..., None]
        chosen = np.take_along_axis(ranked[pos], safe, axis=2)[..., 0]
        value = np.take_along_axis(realized[pos], chosen[..., None], axis=2)[..., 0]
        mu = np.take_along_axis(ranked_mu[pos], safe, axis=2)[..., 0]
        return np.where(ok, value, 0.0), np.where(ok, mu, -np.inf), ok

    dedicated, flex = _slot_plan(ctx.slots)
    for pos in dedicated:
        value, _mu, ok = peek(pos)
        total += value
        if pos in used:
            used[pos] = used[pos] + ok
    for eligible in flex:
        best_value = np.zeros((draws, weeks))
        best_key = np.full((draws, weeks), -np.inf)
        winner: dict[Position, np.ndarray] = {}
        for pos in sorted(eligible, key=lambda p: p.value):
            value, mu, ok = peek(pos)
            key = np.where(ok, value if hindsight else mu, -np.inf)
            take = ok & (key > best_key)
            best_value = np.where(take, value, best_value)
            best_key = np.where(take, key, best_key)
            for other in winner:
                winner[other] = winner[other] & ~take
            winner[pos] = take
        total += best_value
        for pos, take in winner.items():
            if pos in used:
                used[pos] = used[pos] + take

    return total.sum(axis=1)
