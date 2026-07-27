"""The shared E2/E6 fixture pool — and the guard that it can measure anything at all.

`scripts/tune_engine_params.py` and `scripts/run_tournament.py` each carried their own
near-identical `_demo_context()`. Measured on those pools before Tier 4: turning kappa, alpha
AND lambda completely off produced a **bit-identical roster in 96 / 96** (slot x seed x
opponent-field) cells. Three independent reasons, none visible from a passing test:

* `cliff_bonus` was `{}`, so `alpha * cliff` was exactly 0 for every candidate;
* `sigma` took exactly TWO values (35.0 for RB/WR, 25.0 for QB/TE), so `-lambda * sigma` was a
  per-position constant that can never re-rank *within* a position;
* the pools held no K and no DST at all, so `reliability_shrinkage` — which `run_study` tunes via
  `reliability_k` / `reliability_dst` — had nothing to shrink;
* and the value curve was steep enough (a 240-point range over ~148 players) that the MLV gradient
  swamped what little the strategic terms could contribute.

So E2 `--smoke` was running an Optuna study over a **constant function**, and E6 — which only ever
runs `--smoke` (`run_tournament.py` errors without it) — was comparing an agent whose strategic
terms provably contributed nothing, i.e. measuring MLV vs VBD.
"""

from __future__ import annotations

from collections import Counter

import pytest

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.config import EngineParams
from jaaffl.domain import Position
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    simulate_draft,
)

# Two (slot, seed) cells is enough to catch a params-blind pool and keeps this under a few seconds;
# the pre-Tier-4 pool was identical in ALL 96 cells, so a blind pool cannot squeak through on two.
_CELLS = ((0, 1), (7, 1001))


def _roster(params: EngineParams, slot: int, seed: int) -> list[str]:
    return simulate_draft(
        demo_sim_context(),
        our_slot=slot,
        our_agent=ScoreAgent(params),
        opponents=[NeedBasedAgent(), AdpNoiseAgent()],
        seed=seed,
    )[slot]


def _with(**overrides: object) -> EngineParams:
    """A variant of the COMMITTED vector — not of bare ``EngineParams()``, whose empty
    ``lambda_schedule`` would make a "lambda off" variant a silent no-op."""
    return EngineParams.model_validate({**committed_engine_params().model_dump(), **overrides})


def _lambda_off() -> EngineParams:
    return _with(
        lambda_schedule=[
            {"rounds": e["rounds"], "lambda": 0.0}
            for e in committed_engine_params().lambda_schedule
        ]
    )


def test_committed_baseline_carries_the_shipped_lambda_schedule() -> None:
    """E2's baseline arm and E6's "ours" contender were both bare `EngineParams()`, whose
    `lambda_schedule` default is `[]` — so `_phase_lambda` returned 0.0 in every round and BOTH
    experiments silently compared against a risk-free agent. `config/engine.json` meanwhile ships a
    five-band schedule (+0.3 early through -0.4 late) that the live engine loads via
    `get_engine_params()`. Every published E2 "baseline" number therefore described a vector the
    engine does not run, and the pure-MLV control was not testing lambda at all: the arm it was
    compared against already had none.
    """
    assert EngineParams().lambda_schedule == []  # the default that caused it
    committed = committed_engine_params()
    assert len(committed.lambda_schedule) == 5
    lambdas = [entry["lambda"] for entry in committed.lambda_schedule]
    assert max(lambdas) > 0 > min(lambdas)  # it genuinely changes sign across the draft


def test_demo_pool_carries_per_player_sigma_not_a_per_position_constant() -> None:
    ctx = demo_sim_context()
    per_position: dict[Position, set[float]] = {}
    for pid, sigma in ctx.sigma.items():
        per_position.setdefault(ctx.position[pid], set()).add(sigma)
    # A per-position constant cannot re-rank within a position, which is where lambda has to bite.
    assert all(len(values) > 1 for values in per_position.values())
    assert len(set(ctx.sigma.values())) >= 20


def test_demo_pool_carries_real_cliff_bonuses() -> None:
    """Scope note (Tier 5). This guards the FIXTURE, and the fixture was never the problem.

    `demo_sim_context` computes its cliffs inline from `_PLAN`, so it never calls `assign_tiers`
    and cannot see a tiering regression. It passed the entire time the LIVE board's cliff map was
    447 entries of exactly 0.0. That blind spot is covered at the other end of the pipeline by
    `league.coverage.inert_cliff_positions`, which reads the real precomputed context — a fixture
    can only prove the harness can measure a term, never that the board actually carries one.
    """
    ctx = demo_sim_context()
    positive = [pid for pid, bonus in ctx.cliff_bonus.items() if bonus > 0.0]
    assert positive, "alpha multiplies cliff_bonus; an empty map makes alpha exactly inert"
    # A cliff marks the LAST player of a tier, so it must be a minority of the pool, not everyone.
    assert len(positive) < len(ctx.value) // 3


def test_demo_pool_contains_the_positions_reliability_shrinkage_targets() -> None:
    """`run_study` tunes `reliability_k` and `reliability_dst`. A pool with no K and no DST tunes
    two parameters that cannot affect a single pick."""
    present = Counter(ctx_pos for ctx_pos in demo_sim_context().position.values())
    assert present[Position.K] > 12  # more than one per team, so the draft has a real choice
    assert present[Position.DST] > 12


@pytest.mark.parametrize(
    ("term", "mutated"),
    [
        ("kappa", _with(kappa=0.0)),
        ("alpha", _with(alpha=0.0)),
        ("lambda", _lambda_off()),
        ("reliability_shrinkage", _with(reliability_shrinkage={"K": 1.0, "DST": 1.0})),
    ],
)
def test_demo_pool_is_sensitive_to_every_strategic_term(term: str, mutated: EngineParams) -> None:
    """THE guard. Each tuned term, switched off on its own, must change at least one drafted roster.

    If this fails, E2 `--smoke` is optimising a constant in that dimension and E6's efficacy claim
    silently narrows to 'MLV beats the baseline' — which is exactly what was true before Tier 4.

    Scoped honestly, verified by mutation: the `lambda` case here covers the CROSS-position channel
    (`lambda * sigma` tilts a 106-sigma QB against a 29-sigma TE) and survives a per-position-flat
    sigma. Within-position re-ranking — the other half of what lambda does — is pinned separately by
    `test_demo_pool_carries_per_player_sigma_not_a_per_position_constant`, which does fail on a flat
    pool. The other three cases die on the pre-Tier-4 pool.
    """
    shipped = committed_engine_params()
    assert any(
        _roster(shipped, slot, seed) != _roster(mutated, slot, seed) for slot, seed in _CELLS
    ), f"the fixture pool cannot measure {term}"
