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
from jaaffl.engine.optimize import (
    StartingSlot,
    lineup_value,
    marginal_lineup_value,
    value_over_replacement,
)
from jaaffl.engine.risk import (
    has_open_non_puntable_slot,
    is_punted,
    lambda_weight,
    open_startable_by_position,
    puntable_positions,
    risk_penalty,
    seat_roster,
    slot_state_for,
)

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
    # position -> how many that ONE team may legally roster (``optimize.roster_capacity``). Empty
    # means "unlimited", which is bit-identical to the pre-Tier-8 behaviour, so a caller that has
    # not opted in is unchanged.
    roster_capacity: Mapping[Position, int] = field(default_factory=dict)
    # position -> median sigma of that position on this board. EXPERIMENT LEVER, empty by default
    # and therefore inert: supplied, it centres the risk term (see ``risk.risk_penalty``). It is
    # deliberately NOT ``sigma`` — the objective must keep sampling seasons from the true sigma.
    sigma_median: Mapping[Position, float] = field(default_factory=dict)
    # Two CALENDAR/ROSTER facts the week-axis objective needs and no agent reads: the week a
    # player's NFL team does not play, and which team that is (for the measured same-team weekly
    # correlation). Both empty by default, which makes ``engine.weekly`` degrade to "no byes, every
    # player independent" rather than guessing — the same posture ``bye_week`` already takes on
    # ``DraftContext``, where an unresolved team means no chip rather than a wrong one.
    bye_week: Mapping[str, int] = field(default_factory=dict)
    nfl_team: Mapping[str, str] = field(default_factory=dict)


def optimal_lineup_value(roster: Sequence[str], ctx: SimContext) -> float:
    """Flex-aware optimal 9-starter value of ``roster`` (§6.C.3) under the deterministic ``mu``.

    **Sigma-blind by construction** — it reads ``ctx.value`` and never ``ctx.sigma``. Fine as a
    *value* measure, but disqualifying as the sole E2/E6 objective: a risk term ``lambda*sigma``
    that moves the ranking away from ``mu`` can only ever cost points against a scorer that pays
    out on ``mu``, so lambda could be penalised and never rewarded. :func:`win_probability` over
    :func:`sample_season_outcomes` is the objective that can price risk; this stays available as the
    deterministic point-value view, and E2/E6 report both side by side.

    **Scored as a FINAL roster** (``picks_remaining=0``, Tier 7): the draft is over, so a starting
    slot this roster cannot fill yields nothing rather than its replacement baseline. Before Tier 7
    the phantom was credited unconditionally here, which made a roster with no quarterback worth
    exactly as much as one with a below-replacement quarterback. Measured on the real 510-player
    board, this objective reported **+15.34** points for a swap worth **+260.77** — 5.9% of it —
    so the engine's unfillable roster was invisible to every gate that might have fixed it.

    No waiver wire is modelled: ``config/league.json`` specifies none, and inventing one would
    breach its ``agent_usage_contract``. Zero is the honest floor for "the roster the draft
    produced", and real streaming makes this a conservative bound rather than a neutral one.
    """
    return lineup_value(
        roster, ctx.value, ctx.position, ctx.baselines, ctx.slots, picks_remaining=0
    )


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

    Scored as a FINAL roster (``picks_remaining=0``) for the reason spelled out on
    :func:`optimal_lineup_value`; both pass the same capacity, which is what keeps the σ=0
    equivalence pin between them exact.
    """
    import numpy as np

    ids = [pid for pid in roster if pid in outcomes.index]
    if not ids:
        empty = lineup_value(
            [], ctx.value, ctx.position, ctx.baselines, ctx.slots, picks_remaining=0
        )
        return np.full(outcomes.draws.shape[0], empty, dtype=float)
    realized = outcomes.draws[:, [outcomes.index[pid] for pid in ids]]
    return np.array(
        [
            lineup_value(
                ids,
                dict(zip(ids, row, strict=True)),
                ctx.position,
                ctx.baselines,
                ctx.slots,
                picks_remaining=0,
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
    """Value over replacement, from the shared rule — the behavioural agents' whole ranking."""
    return value_over_replacement(pid, ctx.value, ctx.position, ctx.baselines)


def _rosterable(available: Sequence[str], my_roster: Sequence[str], ctx: SimContext) -> list[str]:
    """``available`` minus players this roster has no legal slot left for (``roster_capacity``).

    Every agent narrows to this first. Without it, once an agent's dedicated need was met it fell
    through to greedy VBD — which late in a draft favours STREAMING positions, because a remaining
    kicker sits within a few points of his baseline while a 200th-ranked receiver is 60 below his.
    Measured 2026-08-07: the field drafted 33 of 33 draftable kickers for 12 teams, holding up to
    five each, and that famine (not the scoring rule) is what three tiers running mistook for the
    engine being unable to draft a kicker.

    Falls back to the unfiltered pool if nothing is legal, so an agent can never fail to pick — a
    simulated draft that cannot complete would be worse than one final illegal pick, and
    ``test_simulate`` guards the outcome either way. An empty ``roster_capacity`` means unlimited.
    """
    if not ctx.roster_capacity:
        return list(available)
    held: defaultdict[Position, int] = defaultdict(int)
    for pid in my_roster:
        held[ctx.position[pid]] += 1
    legal = [
        pid
        for pid in available
        if held[ctx.position[pid]] < ctx.roster_capacity.get(ctx.position[pid], len(available))
    ]
    return legal or list(available)


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
        return max(_rosterable(available, my_roster, ctx), key=lambda p: _vbd(p, ctx))


class NeedBasedAgent:
    """Fills an empty dedicated starting slot first (best-value eligible), else best VBD."""

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        pool = _rosterable(available, my_roster, ctx)
        need = _unfilled_positions(my_roster, ctx)
        if need:
            fillers = [p for p in pool if ctx.position[p] in need]
            if fillers:
                return max(fillers, key=lambda p: ctx.value[p])
        return max(pool, key=lambda p: _vbd(p, ctx))


class AdpNoiseAgent:
    """The market's central tendency — argmin adp + N(0, adp_stdev). Stateless; rng from the sim."""

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        pool = _rosterable(available, my_roster, ctx)
        if rng is None:  # no rng → deterministic argmin (no noise)
            return min(pool, key=lambda p: ctx.adp.get(p, _FAR))
        return min(
            pool,
            key=lambda p: ctx.adp.get(p, _FAR) + float(rng.normal(0.0, ctx.adp_stdev.get(p, 0.0))),
        )


class SoftmaxVbdAgent:
    """Boltzmann-rational VBD: picks player ``p`` with probability proportional to
    ``exp(VBD_p / temperature)`` over the top ``candidate_cap`` by VBD.

    A *training* opponent, and a stochastic one. It exists because two requirements collide: the
    held-out set must contain :class:`AdpNoiseAgent` (so ``--eval-seeds`` varies the DRAFT and the
    ADP-based survival model is tested against opponents that follow ADP), while train and held-out
    opponent sets must stay disjoint. Both hold only if ``AdpNoiseAgent`` LEAVES the training mix —
    and the training mix must not then collapse to the fully deterministic :class:`VbdOnlyAgent`.

    Behaviourally distinct from all three existing agents: the market (ADP), the slot-filler (need),
    and greedy VBD. This is a human who mostly takes the best player available and sometimes
    reaches — the standard quantal-response model of a real drafter.
    """

    def __init__(self, *, temperature: float = 4.0, candidate_cap: int = 25) -> None:
        self._temperature = temperature
        self._cap = candidate_cap

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        pool = _rosterable(available, my_roster, ctx)
        candidates = sorted(pool, key=lambda p: _vbd(p, ctx), reverse=True)[: self._cap]
        if rng is None:  # no rng -> deterministic argmax, matching the other agents' convention
            return candidates[0]
        import numpy as np

        scores = np.array([_vbd(p, ctx) for p in candidates], dtype=float)
        # Shift by the max before exponentiating: raw VBD reaches the hundreds and exp() overflows.
        weights = np.exp((scores - scores.max()) / self._temperature)
        return str(rng.choice(candidates, p=weights / weights.sum()))


class ScoreAgent:
    """Our agent: drafts by ``Score(p) = MLV + κ·max(0, VONA) − λ·σ + α·cliff`` under trial params
    (design §10.3), punt-sorted. VONA is a tractable within-position cliff — ``MLV(p)`` minus the
    best OTHER same-position candidate's MLV — the "take the scarce one now" proxy, and the one
    deliberate, declared departure from ``recommend.py`` (which uses the survival-weighted
    ``expected_best_available``). ``σ`` / ``cliff`` come from the context (0 for the
    behavioral-opponent pools that omit them).

    **λ and the punt guard are the SHIPPED ones (Tier 8).** ``λ`` comes from
    ``engine.risk.lambda_weight``, so ``lambda_slot_override`` applies, and the ranking is
    punt-sorted through ``engine.risk.is_punted``. Before Tier 8 this agent read only
    ``lambda_schedule`` and had no punt guard, so **E2/E6 could not measure either key**: driven to
    an extreme, each changed 0 of 60 simulated rosters while ``alpha`` and ``lambda_schedule``
    changed 60 of 60. Tier 7 closed by requiring E2/E6 evidence before touching
    ``lambda_slot_override``; that evidence was not obtainable.

    **Candidates match the shipped agent.** ``recommend.py`` keeps the top ``params.candidate_cap``
    available **by MLV**; this used to keep the top 50 **by raw value**, and ``evaluate_params``
    never passed a cap — so E2 tuned a config key (``candidate_cap: 180``) that its own agent
    ignored, over a candidate set the live engine does not use. Ranking by raw value also hid K and
    DST completely: their μ is low but their MLV jumps the moment their dedicated slot is empty. An
    agent that can never draft a DST silently makes ``reliability_shrinkage`` — which ``run_study``
    tunes — unable to change a single pick.

    **Reliability shrinkage (§3.10 R1):** MLV is computed on ``μ`` pulled toward each position's
    replacement by ``params.reliability_shrinkage`` (K/DST are noisy → deferred), so our DECISIONS
    defer high-variance positions while the OBJECTIVE scores raw μ — a real E2 tuning lever."""

    def __init__(
        self,
        params: EngineParams,
        *,
        candidate_cap: int | None = None,
        centre_sigma: bool = False,
        gate_surplus_stash: bool = False,
    ) -> None:
        self._params = params
        self._cap = params.candidate_cap if candidate_cap is None else candidate_cap
        # Two Tier 8 EXPERIMENT LEVERS, both off by default so the agent stays the shipped agent.
        # `centre_sigma` prices σ against `ctx.sigma_median` instead of raw; `gate_surplus_stash`
        # withholds the surplus ceiling once every remaining pick is spoken for by an unfilled
        # starting slot. Constructor flags rather than config keys on purpose: neither is
        # owner-adopted, and nothing may reach `config/engine.json` on simulator evidence alone.
        # They are flags on the SHIPPED agent (not a subclass) so the arms are measured through the
        # real code path — a duplicate scorer is the exact defect this tier just removed.
        self._centre_sigma = centre_sigma
        self._gate_surplus_stash = gate_surplus_stash
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
        # A league rule, not a strategy: never spend a pick on a player no roster slot can hold.
        available = _rosterable(available, my_roster, ctx)
        # Picks left, including this one. A replacement phantom you have no pick left to draft is
        # not a player, so MLV stops pricing an unfillable slot as though it were free (Tier 7).
        picks_remaining = max(0, ctx.roster_size - len(my_roster))
        base = lineup_value(
            list(my_roster),
            value,
            ctx.position,
            ctx.baselines,
            ctx.slots,
            picks_remaining=picks_remaining,
        )
        all_mlv = {
            p: marginal_lineup_value(
                p,
                my_roster,
                value,
                ctx.position,
                ctx.baselines,
                ctx.slots,
                base_value=base,
                picks_remaining=picks_remaining,
            )
            for p in available
        }
        # VOR on the SAME `value` mapping MLV was computed from (reliability-shrunk), so the
        # tiebreak and the term it breaks ties for agree about what a player is worth.
        vor = {p: value_over_replacement(p, value, ctx.position, ctx.baselines) for p in available}
        # Cap by MLV, as recommend.py does — not by raw value, which hides K/DST behind deep bench
        # skill players whose marginal contribution to the starting nine is zero. Ties broken by
        # VOR then id, because once every starting slot is filled EVERY below-replacement candidate
        # has MLV exactly 0.0: on the real board this cap was selecting 180 of 425 players by dict
        # order, and a player never scored can never be picked (Tier 10).
        #
        # ⚠️ Unlike recommend.py, changing WHO is in this cap changes the SCORES of those who
        # remain: `vona` below is a within-position best-OTHER-candidate proxy computed over
        # `candidates`, so it moves when membership moves. recommend.py's VONA comes from
        # `expected_best_available` over the whole of `available`, computed before its cut, so
        # there the change is a pure re-rank plus membership. Here it is not confined to ties.
        candidates = sorted(available, key=lambda p: (-all_mlv[p], -vor[p], p))[: self._cap]
        mlv = {p: all_mlv[p] for p in candidates}

        # The SHIPPED slot/punt rule, from the one module recommend.py also reads. Until Tier 8
        # this used a private phase-only lambda and no punt guard, so E2/E6 could not see
        # `lambda_slot_override` or `punt_guard` at all: 0 of 60 simulated rosters moved when
        # either was driven to an extreme, while `alpha` and `lambda_schedule` moved 60 of 60.
        round_no = len(my_roster) + 1
        filled = seat_roster(list(my_roster), ctx.position, ctx.slots)
        open_startable = open_startable_by_position(filled, ctx.slots)
        open_non_puntable = has_open_non_puntable_slot(
            filled, ctx.slots, puntable_positions(params)
        )
        # Tier 8 experiment lever, off unless the caller asks: after spending this pick, are there
        # still more picks than unfilled starting slots? If not, a "stash" is not a stash.
        can_stash = (
            (picks_remaining - 1) >= sum(1 for seated in filled if not seated)
            if self._gate_surplus_stash
            else True
        )

        def vona(pid: str) -> float:
            pos = ctx.position[pid]
            others = [mlv[q] for q in candidates if ctx.position[q] == pos and q != pid]
            return mlv[pid] - (max(others) if others else 0.0)

        def score(pid: str) -> float:
            pos = ctx.position[pid]
            lam = lambda_weight(
                round_no, slot_state_for(pos, open_startable), params, can_stash=can_stash
            )
            return (
                mlv[pid]
                + params.kappa * max(0.0, vona(pid))
                - risk_penalty(
                    lam,
                    ctx.sigma.get(pid, 0.0),
                    sigma_median=ctx.sigma_median.get(pos) if self._centre_sigma else None,
                )
                + params.alpha * ctx.cliff_bonus.get(pid, 0.0)
            )

        # Ranked exactly as recommend.py ranks: non-punted first, then score descending. `min`
        # returns the FIRST minimal element, so among candidates the score cannot separate this
        # inherits the `candidates` order above — which Tier 10 made a total order by VOR then id.
        # A tiebreak repeated here would be blind: measured by mutation, removing it moves zero
        # picks, and this project deletes code its own tests cannot see.
        return min(
            candidates,
            key=lambda pid: (
                is_punted(
                    ctx.position[pid],
                    round_no,
                    params,
                    has_open_non_puntable=open_non_puntable,
                ),
                -score(pid),
            ),
        )


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
