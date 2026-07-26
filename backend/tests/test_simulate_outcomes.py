"""Stochastic season outcomes + the win-probability objective (Tier 4, plan §3.9).

The E2/E6 harness scored a finished roster with the deterministic ``mu`` — so ``SimContext.sigma``
was read only when *making* picks, never when *scoring* them, and the ``lambda*sigma`` risk term was
structurally unmeasurable. These tests pin the replacement: sample each player's season from
``N(mu, sigma)`` and score the field by who actually wins.

Two of them are *justification* tests, not just behaviour tests — they encode WHY the objective is
win probability rather than mean lineup value or a floor percentile
(``..._rewards_sigma_monotonically`` / ``..._when_behind_and_punishes_it_when_ahead``).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots
from jaaffl.engine.simulate import (
    SimContext,
    optimal_lineup_value,
    roster_season_values,
    sample_season_outcomes,
    win_probability,
)


def _one_slot_ctx(sigma: dict[str, float], value: dict[str, float]) -> SimContext:
    """A single-QB-slot league: ``lineup_value`` is just that player's outcome, so the win
    probability is analytic and the tests read as probability statements, not lineup puzzles."""
    settings = LeagueSettings(
        league_id="L",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True)
        ],
    )
    return SimContext(
        value=value,
        position=dict.fromkeys(value, Position.QB),
        baselines=dict.fromkeys(Position, 0.0),
        slots=expand_starting_slots(settings),
        roster_size=1,
        sigma=sigma,
    )


def _pool_ctx(n: int = 40) -> SimContext:
    """A small multi-position pool with per-player sigma (deliberately NOT per-position flat)."""
    value, position, sigma = {}, {}, {}
    for i, pos in enumerate([Position.QB, Position.RB, Position.WR, Position.TE]):
        for k in range(n // 4):
            pid = f"{pos.value.lower()}{k}"
            value[pid] = 200.0 - 2.0 * (i * (n // 4) + k)
            position[pid] = pos
            sigma[pid] = 10.0 + 3.0 * k  # per-PLAYER spread, so sigma can re-rank
    settings = LeagueSettings(
        league_id="L",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(
                slot="WR/RB", eligible_positions=[Position.WR, Position.RB], count=1, starting=True
            ),
        ],
    )
    return SimContext(
        value=value,
        position=position,
        baselines=dict.fromkeys(Position, 20.0),
        slots=expand_starting_slots(settings),
        roster_size=3,
        sigma=sigma,
    )


def test_sample_season_outcomes_matches_each_players_mu_and_sigma() -> None:
    ctx = _pool_ctx()
    outcomes = sample_season_outcomes(ctx, n_draws=20_000, seed=7)
    for pid in ("qb0", "wr5", "te9"):
        column = outcomes.draws[:, outcomes.index[pid]]
        assert column.mean() == pytest.approx(ctx.value[pid], abs=0.6)
        assert column.std() == pytest.approx(ctx.sigma[pid], rel=0.05)


def test_sample_season_outcomes_is_reproducible_and_seed_dependent() -> None:
    ctx = _pool_ctx()
    a = sample_season_outcomes(ctx, n_draws=64, seed=3)
    b = sample_season_outcomes(ctx, n_draws=64, seed=3)
    c = sample_season_outcomes(ctx, n_draws=64, seed=4)
    assert np.array_equal(a.draws, b.draws)
    assert not np.array_equal(a.draws, c.draws)


def test_sample_season_outcomes_gives_a_player_the_same_season_in_every_roster() -> None:
    """Common random numbers, keyed by PLAYER id. Two param vectors that both drafted ``rb3`` must
    see the SAME realized ``rb3``, so the comparison is 'who built the better roster out of the same
    season' rather than 'who got luckier'. This is what gives the 12-slot gate any power at all."""
    ctx = _pool_ctx()
    outcomes = sample_season_outcomes(ctx, n_draws=32, seed=11)

    # The load-bearing pin: PERMUTING the roster must not change its value. Any keying by position
    # in the roster list (rather than by player id) fails this immediately, whereas a
    # marginal-contribution check does not — a positional mutant degrades both of its branches
    # identically and slips through. Verified by mutation.
    assert np.array_equal(
        roster_season_values(["rb3", "qb0", "wr2"], outcomes, ctx),
        roster_season_values(["wr2", "rb3", "qb0"], outcomes, ctx),
    )

    # And rb3 contributes the same realized season whoever else is on the roster.
    with_qb0 = roster_season_values(["rb3", "qb0"], outcomes, ctx) - roster_season_values(
        ["qb0"], outcomes, ctx
    )
    with_qb1 = roster_season_values(["rb3", "qb1"], outcomes, ctx) - roster_season_values(
        ["qb1"], outcomes, ctx
    )
    # Equal to float noise, not bit-equal: the two differences sum different QB magnitudes.
    assert with_qb0 == pytest.approx(with_qb1, abs=1e-9)
    assert with_qb0.std() > 0.0  # and it is a real sampled season, not a constant


def test_roster_season_values_reduces_to_the_deterministic_scorer_when_sigma_is_zero() -> None:
    """The pin: at sigma=0 the stochastic scorer must reproduce ``optimal_lineup_value`` exactly,
    so the new objective is a strict generalisation of the old one (cf. the sigma=0 pin that ties
    ``mc_expected_best_available`` to ``AdpNoiseAgent``)."""
    ctx = _pool_ctx()
    zero = dataclasses.replace(ctx, sigma=dict.fromkeys(ctx.value, 0.0))
    outcomes = sample_season_outcomes(zero, n_draws=8, seed=2)
    roster = ["rb0", "rb1", "wr0", "qb0"]
    values = roster_season_values(roster, outcomes, zero)
    assert values == pytest.approx([optimal_lineup_value(roster, zero)] * 8)


def test_win_probability_of_an_identical_field_is_exactly_one_over_twelve() -> None:
    """Ties split evenly, so a field of clones is exactly 1/12 — not merely close to it."""
    ctx = _one_slot_ctx(sigma={"qb0": 15.0}, value={"qb0": 100.0})
    outcomes = sample_season_outcomes(ctx, n_draws=200, seed=5)
    rosters = [["qb0"] for _ in range(12)]
    assert win_probability(rosters, outcomes, ctx, our_slot=4) == pytest.approx(1.0 / 12.0)


def test_win_probability_is_one_for_a_strictly_dominant_roster() -> None:
    ctx = _one_slot_ctx(sigma={"qb0": 1.0, "qb1": 1.0}, value={"qb0": 1000.0, "qb1": 100.0})
    outcomes = sample_season_outcomes(ctx, n_draws=500, seed=5)
    rosters = [["qb0"]] + [["qb1"] for _ in range(11)]
    assert win_probability(rosters, outcomes, ctx, our_slot=0) == pytest.approx(1.0)


def _duel_ctx(*, our_mu: float, our_sigma: float) -> SimContext:
    """Us vs ELEVEN DISTINCT opponents. The field must not be clones: identical rosters realize
    perfectly correlated seasons, which collapses a 12-team race into a coin flip and hides exactly
    the effect these tests exist to measure."""
    value = {"a": our_mu} | {f"b{i}": 100.0 for i in range(11)}
    sigma = {"a": our_sigma} | {f"b{i}": 5.0 for i in range(11)}
    return _one_slot_ctx(sigma=sigma, value=value)


def _p_win(ctx: SimContext, *, n_draws: int = 20_000, seed: int = 13) -> float:
    rosters = [["a"], *[[f"b{i}"] for i in range(11)]]
    return win_probability(
        rosters, sample_season_outcomes(ctx, n_draws=n_draws, seed=seed), ctx, our_slot=0
    )


def test_win_probability_responds_to_sigma_where_the_deterministic_scorer_cannot() -> None:
    """THE Tier-4 defect, as a test. Same mu, different sigma: ``optimal_lineup_value`` returns the
    identical number (so lambda could only ever distort), while the win probability moves a lot."""
    lo, hi = _duel_ctx(our_mu=100.0, our_sigma=2.0), _duel_ctx(our_mu=100.0, our_sigma=40.0)
    assert optimal_lineup_value(["a"], lo) == optimal_lineup_value(["a"], hi)  # sigma-blind, today
    assert _p_win(hi) > _p_win(lo) + 0.10


def test_mean_lineup_value_under_sampling_rewards_sigma_monotonically() -> None:
    """WHY the objective is NOT 'mean lineup value under sampling'. Because the lineup is
    re-optimised after outcomes are revealed, ``E[L*]`` is a max over assignments and Jensen makes
    it increase with spread. Adopting it would make ceiling-tilt (lambda<0) right in EVERY round —
    swapping one structural verdict for the opposite one, and leaving the lambda SCHEDULE (whose
    whole content is that lambda changes sign by round) just as unmeasurable as it is today."""
    means = []
    for sigma in (1.0, 20.0, 60.0):
        ctx = _one_slot_ctx(sigma={"a": sigma, "b": sigma}, value={"a": 100.0, "b": 100.0})
        outcomes = sample_season_outcomes(ctx, n_draws=8000, seed=9)
        means.append(float(roster_season_values(["a", "b"], outcomes, ctx).mean()))
    assert means[0] < means[1] < means[2]


def test_win_probability_rewards_variance_when_behind_and_punishes_it_when_ahead() -> None:
    """WHY the objective IS win probability. It is ordinal, so it escapes both Jensen traps — and it
    is the only one of the three candidates under which the OPTIMAL SIGN OF LAMBDA can differ by
    round. That sign-flip is the entire content of the shipped lambda schedule (floor-tilt early,
    ceiling-tilt late), so no other objective can calibrate it."""
    # Behind the field on mu -> variance is your only route to the top.
    assert _p_win(_duel_ctx(our_mu=85.0, our_sigma=30.0)) > _p_win(
        _duel_ctx(our_mu=85.0, our_sigma=2.0)
    )
    # Ahead of the field on mu -> variance can only give the lead away.
    assert _p_win(_duel_ctx(our_mu=115.0, our_sigma=30.0)) < _p_win(
        _duel_ctx(our_mu=115.0, our_sigma=2.0)
    )
