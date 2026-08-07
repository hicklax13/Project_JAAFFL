"""The harness must be able to MEASURE the vector it is tuning.

The fourth instance of this project's recurring defect, and every one of them was invisible for
the same reason: the thing that looked healthy (a map SIZE, a roster COUNT, a green suite) is not
the thing that matters.

* **Tier 4** — both fixture pools were params-blind: kappa, alpha AND lambda switched off together
  left a bit-identical roster in 96/96 cells, so the Optuna study maximised a constant.
* **Tier 5** — alpha multiplied a ``cliff_bonus`` map with 293 entries, every one of them 0.0.
* **Tier 6** — the three positional modifiers were advertised in the config and priced by nothing.
* **Tier 8** — ``ScoreAgent``, the agent every E2/E6 number is produced by, read neither
  ``lambda_slot_override`` nor ``punt_guard``. Measured 2026-08-07 over 12 slots x 5 seeds:
  sign-flipping the override changed **0 of 60** rosters and disabling the punt guard changed
  **0 of 60**, while doubling ``lambda_schedule`` and zeroing ``alpha`` each changed **60 of 60**.
  So Tier 7's closing instruction — get E2/E6 evidence with ``--replicates >= 3`` before touching
  ``lambda_slot_override`` — was impossible to satisfy.

This test asks the only question that catches all four: change the knob, does any pick move?
"""

from __future__ import annotations

import pytest

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.config import EngineParams
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    simulate_draft,
)

SEEDS = (1001, 1002, 1003, 1004, 1005)
TEAMS = 12


def _rosters(params: EngineParams) -> list[tuple[str, ...]]:
    """Every (slot, seed) roster our agent drafts under ``params``, as comparable tuples."""
    ctx = demo_sim_context()
    return [
        tuple(
            simulate_draft(
                ctx,
                our_slot=slot,
                our_agent=ScoreAgent(params),
                opponents=[NeedBasedAgent(), AdpNoiseAgent()],
                seed=seed,
                teams=TEAMS,
            )[slot]
        )
        for slot in range(TEAMS)
        for seed in SEEDS
    ]


def _mutate(base: EngineParams, **changes: object) -> EngineParams:
    return EngineParams.model_validate({**base.model_dump(), **changes})


@pytest.mark.parametrize(
    ("knob", "changes"),
    [
        (
            "lambda_slot_override",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": -2.0,
                    "surplus_stash_ceiling": 2.0,
                }
            },
        ),
        ("punt_guard", {"punt_guard": {"enabled": False, "stream_round": {}}}),
        # Controls: knobs the harness was already measured to price, so a null result above
        # cannot be blamed on the experiment.
        ("alpha", {"alpha": 0.0}),
        (
            "lambda_schedule",
            {
                "lambda_schedule": [
                    {"rounds": [1, 2], "lambda": 0.6},
                    {"rounds": [3, 6], "lambda": 0.4},
                    {"rounds": [7, 9], "lambda": 0.0},
                    {"rounds": [10, 13], "lambda": -0.6},
                    {"rounds": [14, 17], "lambda": -0.8},
                ]
            },
        ),
    ],
)
def test_the_harness_can_see_every_knob_it_tunes(knob: str, changes: dict) -> None:
    """Drive each knob to an extreme and require at least one simulated pick to move."""
    base = committed_engine_params()
    before, after = _rosters(base), _rosters(_mutate(base, **changes))
    moved = sum(1 for a, b in zip(before, after, strict=True) if a != b)
    assert moved > 0, (
        f"{knob} cannot change a single pick across {len(before)} simulated drafts — "
        "the harness is blind to it, so no measurement of it means anything"
    )
