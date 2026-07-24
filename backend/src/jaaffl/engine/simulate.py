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
    """Flex-aware optimal 9-starter value of ``roster`` (§6.C.3) — the E2/E6 objective."""
    return lineup_value(roster, ctx.value, ctx.position, ctx.baselines, ctx.slots)


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
    ``σ`` / ``cliff`` come from the context (0 for the behavioral-opponent pools that omit them)."""

    def __init__(self, params: EngineParams, *, candidate_cap: int = 50) -> None:
        self._params = params
        self._cap = candidate_cap

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        params = self._params
        base = lineup_value(list(my_roster), ctx.value, ctx.position, ctx.baselines, ctx.slots)
        candidates = sorted(available, key=lambda p: ctx.value[p], reverse=True)[: self._cap]
        mlv = {
            p: marginal_lineup_value(
                p, my_roster, ctx.value, ctx.position, ctx.baselines, ctx.slots, base_value=base
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
