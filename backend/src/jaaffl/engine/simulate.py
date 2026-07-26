"""Draft simulator + Monte-Carlo rollouts (stretch, §3.9 / §9.2). NOT on the per-pick hot path.

Two roles:

* **E2/E6 substrate** — behavioral :class:`DraftAgent`s draft a full 17-round snake to completion
  (:func:`simulate_draft`), each final roster scored by :func:`optimal_lineup_value` (the flex-aware
  optimal 9). Our params-sensitive :class:`ScoreAgent` plays the behavioral opponents.
* **MC-VONA** — :func:`simulate_drafts` rolls the draft forward for ``E[best available]``.

Pure numpy (the base ``engine`` extra).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from jaaffl.config import EngineParams
from jaaffl.domain import Position
from jaaffl.engine.optimize import StartingSlot, lineup_value, marginal_lineup_value

if TYPE_CHECKING:
    import numpy as np

_FAR = 1.0e9


@dataclass(frozen=True)
class SimContext:
    """The immutable pool a simulated draft reads: per-player value / position / ADP, positional
    replacement baselines, the 9 starting slots, and roster size. ``sigma`` / ``cliff_bonus`` feed
    the :class:`ScoreAgent`'s risk / tier terms (empty for the behavioral opponents)."""

    value: Mapping[str, float]
    position: Mapping[str, Position]
    baselines: Mapping[Position, float]
    slots: Sequence[StartingSlot]
    roster_size: int
    adp: Mapping[str, float] = field(default_factory=dict)
    adp_stdev: Mapping[str, float] = field(default_factory=dict)
    sigma: Mapping[str, float] = field(default_factory=dict)
    cliff_bonus: Mapping[str, float] = field(default_factory=dict)


def optimal_lineup_value(roster: Sequence[str], ctx: SimContext) -> float:
    """Flex-aware optimal 9-starter value of ``roster`` (§6.C.3) under the deterministic ``mu``.

    **Sigma-blind by construction** — it reads ``ctx.value`` and never ``ctx.sigma``. Fine as a
    *value* measure, but disqualifying as the sole E2/E6 objective: a risk term ``lambda*sigma``
    that moves the ranking away from ``mu`` can only ever cost points against a scorer that pays
    out on ``mu``, so lambda could be penalised and never rewarded. :func:`win_probability` over
    :func:`sample_season_outcomes` is the objective that can price risk; this stays available as the
    deterministic point-value view, and E2/E6 report both side by side.
    """
    return lineup_value(roster, ctx.value, ctx.position, ctx.baselines, ctx.slots)


@dataclass(frozen=True)
class SeasonOutcomes:
    """``n_draws`` sampled seasons for a whole pool: ``draws[d, index[pid]]`` is ``pid``'s realized
    season total in draw ``d``. Sampled ONCE for the pool and keyed by player id, so a player who
    appears on two different rosters realizes the *same* season in both — common random numbers,
    which is what makes the 12-slot paired comparison sensitive enough to see a param change."""

    order: tuple[str, ...]
    index: Mapping[str, int]
    draws: np.ndarray


def sample_season_outcomes(ctx: SimContext, *, n_draws: int, seed: int) -> SeasonOutcomes:
    """Draw ``n_draws`` season totals per player from ``N(mu_p, sigma_p)``, reproducible from
    ``seed``.

    Outcomes are NOT clipped at zero: :func:`optimize.lineup_value` already refuses to start a
    sub-replacement player, so a bust is benched rather than scored negative — the option value of a
    deep bench falls out of the lineup rule instead of being imposed here. A player absent from
    ``ctx.sigma`` draws at ``sigma = 0`` (a fixed ``mu``), so a pool with partial sigma coverage
    stays well defined.
    """
    import numpy as np

    order = tuple(sorted(ctx.value))
    mu = np.array([ctx.value[pid] for pid in order], dtype=float)
    sigma = np.array([ctx.sigma.get(pid, 0.0) for pid in order], dtype=float)
    rng = np.random.default_rng(seed)
    draws = mu + rng.standard_normal((n_draws, len(order))) * sigma
    return SeasonOutcomes(order=order, index={pid: i for i, pid in enumerate(order)}, draws=draws)


def roster_season_values(
    roster: Sequence[str], outcomes: SeasonOutcomes, ctx: SimContext
) -> np.ndarray:
    """``(n_draws,)`` optimal starting-lineup value of ``roster`` under each sampled season.

    The lineup is re-optimised per draw (you start whoever actually produced), so this is the
    season-long analogue of :func:`optimal_lineup_value` — and at ``sigma = 0`` it reproduces that
    function exactly, making the stochastic scorer a strict generalisation of the deterministic one.
    """
    import numpy as np

    ids = [pid for pid in roster if pid in outcomes.index]
    if not ids:
        empty = lineup_value([], ctx.value, ctx.position, ctx.baselines, ctx.slots)
        return np.full(outcomes.draws.shape[0], empty, dtype=float)
    realized = outcomes.draws[:, [outcomes.index[pid] for pid in ids]]
    return np.array(
        [
            lineup_value(
                ids, dict(zip(ids, row, strict=True)), ctx.position, ctx.baselines, ctx.slots
            )
            for row in realized
        ],
        dtype=float,
    )


def win_probability(
    rosters: Sequence[Sequence[str]],
    outcomes: SeasonOutcomes,
    ctx: SimContext,
    *,
    our_slot: int,
) -> float:
    """``P(our roster posts the highest realized starting-lineup total of the field)``.

    The E2/E6 objective. Plan §3.9 names playoff/championship odds as "the true objective that
    lambda only proxies"; being **ordinal**, this escapes the two traps that disqualify the
    alternatives. A *mean* outcome objective rewards spread monotonically (Jensen — the lineup is
    re-optimised after the fact); a *floor percentile* punishes it monotonically. Either fixes the
    sign of the optimal lambda for every round, which would leave the shipped lambda SCHEDULE —
    whose entire content is that lambda flips sign between round 1 and round 17 — exactly as
    unmeasurable as the deterministic scorer leaves it. Only a rank objective rewards variance when
    you trail the field and punishes it when you lead.

    **Scope, honestly:** a *total-points* championship proxy. ``config/league.json`` fixes the
    roster and scoring but specifies **no** playoff bracket or head-to-head schedule, and inventing
    would breach its ``agent_usage_contract``; "highest season total of the 12" needs no config that
    does not exist. Ties split evenly, so a field of clones scores exactly ``1/teams``.
    """
    import numpy as np

    totals = np.stack([roster_season_values(roster, outcomes, ctx) for roster in rosters])
    winners = totals == totals.max(axis=0)
    return float(np.mean(winners[our_slot] / winners.sum(axis=0)))


def _dedicated_demand(ctx: SimContext) -> dict[Position, int]:
    demand: dict[Position, int] = defaultdict(int)
    for slot in ctx.slots:
        if len(slot.eligible) == 1:
            demand[next(iter(slot.eligible))] += 1
    return demand


def _unfilled_positions(roster: Sequence[str], ctx: SimContext) -> set[Position]:
    have: dict[Position, int] = defaultdict(int)
    for pid in roster:
        have[ctx.position[pid]] += 1
    return {pos for pos, need in _dedicated_demand(ctx).items() if have[pos] < need}


def _vbd(pid: str, ctx: SimContext) -> float:
    return ctx.value[pid] - ctx.baselines.get(ctx.position[pid], 0.0)


class DraftAgent(Protocol):
    """A drafting policy: choose one ``player_id`` from ``available`` given the current roster."""

    def pick(
        self,
        available: Sequence[str],
        my_roster: Sequence[str],
        ctx: SimContext,
        rng: np.random.Generator | None = None,
    ) -> str: ...


class VbdOnlyAgent:
    """Pure static VOR — argmax value − replacement baseline; no VONA/risk/cliff (design §6.C.2)."""

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        return max(available, key=lambda p: _vbd(p, ctx))


class NeedBasedAgent:
    """Fills an empty dedicated starting slot first (best-value eligible), else best VBD."""

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        need = _unfilled_positions(my_roster, ctx)
        if need:
            fillers = [p for p in available if ctx.position[p] in need]
            if fillers:
                return max(fillers, key=lambda p: ctx.value[p])
        return max(available, key=lambda p: _vbd(p, ctx))


class AdpNoiseAgent:
    """The market's central tendency — argmin adp + N(0, adp_stdev). Stateless; rng from the sim."""

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        if rng is None:  # no rng → deterministic argmin (no noise)
            return min(available, key=lambda p: ctx.adp.get(p, _FAR))
        return min(
            available,
            key=lambda p: ctx.adp.get(p, _FAR) + float(rng.normal(0.0, ctx.adp_stdev.get(p, 0.0))),
        )


def _phase_lambda(params: EngineParams, round_no: int) -> float:
    """The phase-default risk λ for ``round_no`` from ``params.lambda_schedule`` (the sim uses the
    phase default; the last-startable/surplus override is a hot-path refinement)."""
    for entry in params.lambda_schedule:
        low, high = entry["rounds"]
        if low <= round_no <= high:
            return float(entry["lambda"])
    return 0.0


class ScoreAgent:
    """Our agent: drafts by ``Score(p) = MLV + κ·max(0, VONA) − λ(round)·σ + α·cliff`` under trial
    params (design §10.3). VONA is a tractable within-position cliff — ``MLV(p)`` minus the best
    OTHER same-position candidate's MLV — the "take the scarce one now" proxy. Candidates are capped
    to the top ``candidate_cap`` available by value so a full-draft rollout stays tractable.
    ``σ`` / ``cliff`` come from the context (0 for the behavioral-opponent pools that omit them).

    **Reliability shrinkage (§3.10 R1):** MLV is computed on ``μ`` pulled toward each position's
    replacement by ``params.reliability_shrinkage`` (K/DST are noisy → deferred), so our DECISIONS
    defer high-variance positions while the OBJECTIVE scores raw μ — a real E2 tuning lever."""

    def __init__(self, params: EngineParams, *, candidate_cap: int = 50) -> None:
        self._params = params
        self._cap = candidate_cap
        self._eff_cache_id: int | None = None
        self._eff_cache: Mapping[str, float] = {}

    def _effective_value(self, ctx: SimContext) -> Mapping[str, float]:
        """``μ`` with reliability shrinkage applied (``base + factor·(μ − base)``; factor 1.0 = no
        shrink). Cached per context — one context is reused across a whole evaluation."""
        if self._eff_cache_id == id(ctx):
            return self._eff_cache
        shrink = self._params.reliability_shrinkage or {}
        if not shrink or all(factor >= 1.0 for factor in shrink.values()):
            eff: Mapping[str, float] = ctx.value
        else:
            eff = {}
            for pid, mu in ctx.value.items():
                factor = shrink.get(ctx.position[pid].value, 1.0)
                base = ctx.baselines.get(ctx.position[pid], 0.0)
                eff[pid] = mu if factor >= 1.0 else base + factor * (mu - base)
        self._eff_cache_id, self._eff_cache = id(ctx), eff
        return eff

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        params = self._params
        value = self._effective_value(ctx)
        base = lineup_value(list(my_roster), value, ctx.position, ctx.baselines, ctx.slots)
        candidates = sorted(available, key=lambda p: value[p], reverse=True)[: self._cap]
        mlv = {
            p: marginal_lineup_value(
                p, my_roster, value, ctx.position, ctx.baselines, ctx.slots, base_value=base
            )
            for p in candidates
        }
        lam = _phase_lambda(params, len(my_roster) + 1)

        def vona(pid: str) -> float:
            pos = ctx.position[pid]
            others = [mlv[q] for q in candidates if ctx.position[q] == pos and q != pid]
            return mlv[pid] - (max(others) if others else 0.0)

        def score(pid: str) -> float:
            return (
                mlv[pid]
                + params.kappa * max(0.0, vona(pid))
                - lam * ctx.sigma.get(pid, 0.0)
                + params.alpha * ctx.cliff_bonus.get(pid, 0.0)
            )

        return max(candidates, key=score)


def simulate_draft(
    ctx: SimContext,
    *,
    our_slot: int,
    our_agent: DraftAgent,
    opponents: Sequence[DraftAgent],
    seed: int,
    teams: int = 12,
) -> list[list[str]]:
    """Simulate a full snake draft to completion; return each team's final roster (``teams`` lists).

    Our agent sits at ``our_slot`` (0-indexed); the ``opponents`` cycle through the other seats.
    Snake order over ``ctx.roster_size`` rounds. Candidates are passed to each agent in a
    deterministic (sorted) order, and all randomness flows from ``seed``, so runs are reproducible.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    seats: list[DraftAgent] = []
    opp_cursor = 0
    for seat in range(teams):
        if seat == our_slot:
            seats.append(our_agent)
        else:
            seats.append(opponents[opp_cursor % len(opponents)])
            opp_cursor += 1

    rosters: list[list[str]] = [[] for _ in range(teams)]
    available: set[str] = set(ctx.value)
    order = list(range(teams))
    for rnd in range(ctx.roster_size):
        seat_order = order if rnd % 2 == 0 else order[::-1]  # snake
        for seat in seat_order:
            if not available:
                return rosters
            choice = seats[seat].pick(sorted(available), rosters[seat], ctx, rng)
            rosters[seat].append(choice)
            available.discard(choice)
    return rosters


def mc_expected_best_available(
    ctx: SimContext,
    *,
    available: Sequence[str],
    candidates_by_position: Mapping[Position, Sequence[str]],
    mlv: Mapping[str, float],
    picks_between: int,
    n_sims: int = 200,
    seed: int = 0,
) -> dict[Position, float]:
    """MC-VONA (§3.9): ``E[best surviving MLV]`` per position, the ``use_mc_vona`` refinement.

    Estimates exactly the quantity :func:`opponents.expected_best_available` estimates, so the
    resulting ``VONA = MLV(p) − E_π[pos]`` stays on the same scale and the two are directly
    comparable. What changes is the *opponent model*: the analytic form multiplies INDEPENDENT
    per-player survivals (``Σ_k MLV_k·S_k·Π_{i<k}(1−S_i)``), which can price a board on which
    nobody is taken at all. Rolling the draft forward is coupled by construction — ``picks_between``
    picks remove exactly ``picks_between`` players, concentrated at the top by ADP.

    Measured on the pick-1 worst case (239 players, horizon 2, 2000 rollouts): MC returns a LOWER
    ``E_π`` at RB than the analytic form, i.e. a HIGHER VONA (+6.45), and the two disagree on the
    #1 pick. Direction is a property of the board, not a theorem — do not assume its sign.

    One shared rollout answers EVERY position per sim (not one rollout per candidate), so the
    positional estimates are mutually consistent and the cost is ``O(n_sims × picks_between)``
    rather than ``O(n_sims × candidates)``.

    Vectorized restatement of :class:`AdpNoiseAgent`'s model — ``argmin(adp + N(0, adp_stdev))``,
    redrawn each pick — evaluated for the whole pool at once instead of per candidate. The
    equivalence is pinned by a test (σ=0 must reproduce the agent's deterministic order).
    Reproducible from ``seed``.
    """
    import numpy as np

    pool = list(available)
    if not pool or n_sims <= 0:
        return {pos: float(ctx.baselines.get(pos, 0.0)) for pos in candidates_by_position}

    index = {pid: i for i, pid in enumerate(pool)}
    adp = np.array([ctx.adp.get(pid, _FAR) for pid in pool], dtype=float)
    stdev = np.array([ctx.adp_stdev.get(pid, 0.0) for pid in pool], dtype=float)

    # Per position: the candidate row-indices and their MLVs, ordered best-MLV first, so the
    # survivor scan is a first-hit lookup instead of a max over the whole position.
    ranked: dict[Position, tuple[np.ndarray, np.ndarray]] = {}
    for pos, pids in candidates_by_position.items():
        rows = [(index[pid], mlv[pid]) for pid in pids if pid in index]
        rows.sort(key=lambda r: r[1], reverse=True)
        ranked[pos] = (
            np.array([r[0] for r in rows], dtype=int),
            np.array([r[1] for r in rows], dtype=float),
        )

    steps = max(0, min(picks_between, len(pool)))
    totals = dict.fromkeys(candidates_by_position, 0.0)
    for sim in range(n_sims):
        rng = np.random.default_rng((seed, sim))
        alive = np.ones(len(pool), dtype=bool)
        for _ in range(steps):
            keys = np.where(alive, adp + rng.normal(0.0, 1.0, size=len(pool)) * stdev, np.inf)
            alive[int(np.argmin(keys))] = False
        for pos, (rows, values) in ranked.items():
            survivors = alive[rows] if rows.size else np.zeros(0, dtype=bool)
            # Best surviving MLV, else this position's replacement — the analytic fallback.
            totals[pos] += (
                float(values[int(np.argmax(survivors))])
                if survivors.any()
                else float(ctx.baselines.get(pos, 0.0))
            )
    return {pos: total / n_sims for pos, total in totals.items()}


def simulate_drafts(
    ctx: SimContext,
    *,
    my_roster: Sequence[str],
    candidates: Sequence[str],
    picks_between: int = 11,
    n_sims: int = 100,
    seed: int = 0,
    our_agent: DraftAgent | None = None,
) -> dict[str, float]:
    """MC-VONA (design §3.9): ``candidate first pick -> expected end-of-draft roster value``.

    For each candidate ``c``, roll the draft forward ``n_sims`` times — ``picks_between`` opponent
    picks (sampled from ADP via :class:`AdpNoiseAgent`) deplete the pool between each of our
    ``our_agent`` picks — until our roster is full, and average :func:`optimal_lineup_value`. The
    ``E[best available]`` refinement to analytic VONA; NOT on the per-pick hot path (budget-gated,
    ``use_mc_vona``). Reproducible from ``seed``.
    """
    import numpy as np

    our_agent = our_agent or VbdOnlyAgent()
    opponent = AdpNoiseAgent()
    base = list(my_roster)
    results: dict[str, float] = {}
    for candidate_index, candidate in enumerate(candidates):
        total = 0.0
        for sim in range(n_sims):
            rng = np.random.default_rng((seed, candidate_index, sim))
            available = set(ctx.value) - set(base) - {candidate}
            roster = [*base, candidate]
            while len(roster) < ctx.roster_size and available:
                for _ in range(picks_between):
                    if not available:
                        break
                    available.discard(opponent.pick(sorted(available), (), ctx, rng))
                if not available:
                    break
                mine = our_agent.pick(sorted(available), roster, ctx, rng)
                roster.append(mine)
                available.discard(mine)
            total += optimal_lineup_value(roster, ctx)
        results[candidate] = total / n_sims
    return results
