# Tier 8: the endgame defect was never in the engine — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the calibration harness manufacturing a kicker famine that no engine could survive,
make it able to see the two shipped coefficients it has never read, and re-establish the baseline —
then, and only then, measure whether `lambda_slot_override` should change.

**Architecture:** Two harness-fidelity fixes and no change to the shipped scoring rule. (1) A
simulated opponent may not draft a player it cannot legally roster — capacity comes from
`LeagueSettings` slot eligibility, the same source `lineup_value` and `optimize_roster` already
honour. (2) The shipped score rule moves into one module that both `recommend.py` and
`ScoreAgent` call, so the simulated agent stops being a different agent. Goal 1's re-measurement
runs **after** both, because either would invalidate it.

**Tech Stack:** Python 3.12, pytest, numpy, scipy, optuna. Backend only; no contract or schema
change, no new config key, no new coefficient.

---

## Why this shape (measured 2026-08-07, real 581-player board + the offline fixture pool)

### The finding, and the two accounts it replaces

Tier 6 and Tier 7 both concluded the engine cannot draft a kicker. Tier 7 named a mechanism: at R16
the engine takes a second quarterback (MLV −72.06, σ 170.08) over the best kicker (MLV +2.58,
σ 20.0), because `surplus_stash_ceiling = −0.4` pays +68.03 for variance while
`last_startable_slot_floor = +0.4` charges the kicker −8.00.

**That instance does not reproduce, and the conclusion is wrong.** Walking the same seat on today's
board, at R16 there is **no kicker on the board at all**; the engine takes a DST and then its
**first** QB at R17. The final roster holds `QB:1`, not `QB:2`.

The decisive experiment is the opponent field. Sweeping all 12 seats × 2 opponent fields = 24 real
drafts per arm:

| arm                                   | opponents as shipped today            | opponents that draft **legal** rosters |
| ------------------------------------- | ------------------------------------- | -------------------------------------- |
| **committed (shipped config)**        | **24/24 illegal** — `{K: 24, DST: 5}` | **0/24 — legal, K at median R16**      |
| `lambda_slot_override` zeroed         | 0/24, K at median R10                 | 0/24                                   |
| centred σ (candidate code fix)        | 24/24 illegal                         | 0/24                                   |
| feasibility gate (candidate code fix) | 24/24 illegal                         | 0/24                                   |
| centred + gated                       | 24/24 illegal                         | 0/24                                   |

**Against a field that drafts legally the shipped engine is fine at every seat.** Against today's
field it fails at every seat, and so does every candidate engine fix. Zeroing the override "works"
only because it makes the engine panic-draft a kicker in **round 10** to beat a field that is
illegally consuming the entire kicker supply — which would be bad advice in a real room, not a fix.

### Defect 1 — the simulated opponents draft rosters the league cannot hold

`NeedBasedAgent`, `VbdOnlyAgent`, `AdpNoiseAgent` and `SoftmaxVbdAgent` have no concept of roster
capacity. Once an agent's dedicated need is met it falls through to `max(available, key=_vbd)`, and
late in the draft greedy VBD **favours streaming positions**: a remaining kicker sits within a few
points of his baseline while a 200th-ranked receiver is 60 below his. So the field eats kickers.

Measured, real board (33 draftable K, 31 DST, 12 teams):

```
field drafted K=33 of 33 · DST=31 · teams hold K=0..5 each
kickers still available at my pick:  R12 15 · R13 11 · R14 7 · R15 4 · R16 0 · R17 0
```

Fixture pool (15 K, 15 DST, 12 teams): the `vbd-only` field drafts **15 of 15** kickers and **15 of
15** defenses, and rosters **13 players illegally** in a single draft.

The league cannot hold them. `league/constitution.py:31` gives `BENCH` the eligible set
`(QB, RB, WR, TE)`, so a kicker fits only the K slot and a defense only the DST slot — capacity 1
each. `expand_starting_slots`, `lineup_value` and `optimize_roster` all already honour that;
**only the draft agents ignore it.** This is not a new rule, it is an existing rule the agents skip.

Two consequences, both of which contaminate every number this project has published:

1. It manufactures a famine no engine can survive. That famine — not the scoring rule — is the
   "the engine cannot draft a kicker" finding of Tier 6, Tier 7, **and the first half of Tier 8**.
2. Opponents spend picks on players they cannot roster, so the simulated field is weaker than a
   real one and **every win-probability number is biased upward**.

Repairing it collapses the fixture failure rate to zero for every arm:

```
fixture, 12 slots x 8 seeds x 2 fields = 192 drafts per variant
                              opponents today        opponents capacity-capped
blind ScoreAgent (shipped)    24/192 (12.5%)         0/192
faithful, raw sigma           96/192 (50.0%)         0/192
faithful, centred sigma       96/192 (50.0%)         0/192
faithful, feasibility gate    96/192 (50.0%)         0/192
faithful, override zeroed     96/192 (50.0%)         0/192
```

The identical 96/192 across five different fixes is the tell: **the fixture pool was never measuring
the agent.** It was measuring whether the opponents left a kicker behind. All 96 failures are the
`vbd-only` field at 100%; `need+adp` is 0/96 throughout.

### Defect 2 — `ScoreAgent` is not the shipped agent, so E2/E6 cannot see two config keys

`recommend.py` computes `risk_penalty = lambda_weight(round_no, slot_state, params) · σ`, where
`lambda_weight` applies `lambda_slot_override`, and then re-ranks with the `punt_guard`.
`simulate.py::ScoreAgent.pick` uses `_phase_lambda`, which reads **only** `lambda_schedule`, and has
no punt guard at all. Grep confirms `lambda_slot_override` is read in exactly one place in the
codebase, and `punt_guard` likewise.

Measured — 12 slots × 5 seeds = 60 simulated drafts per arm, rosters compared bit-for-bit:

```
lambda_slot_override sign-flipped              rosters changed:   0/60   *** BLIND ***
lambda_slot_override zeroed                    rosters changed:   0/60   *** BLIND ***
punt_guard disabled                            rosters changed:   0/60   *** BLIND ***
lambda_schedule doubled  [POSITIVE CONTROL]    rosters changed:  60/60   MEASURABLE
alpha = 0                [POSITIVE CONTROL]    rosters changed:  60/60   MEASURABLE
```

Both positive controls move every roster, so the null result is real rather than a broken
experiment. **Tier 7 closed by requiring E2/E6 evidence with `--replicates >= 3` before touching
`lambda_slot_override`. That evidence could not exist.**

This is Tier 4's finding — "the simulated agent was not the shipped agent" — **half-fixed**. Tier 4
repaired candidate _selection_ (`candidate_cap` 50→180, ranking by MLV not raw value) and left the
_score function_ diverging. One rule implemented twice diverges; the fix is to implement it once.

### Defect 3 — `λ_slot · σ` is a positional bias term (real, and NOT the cause of the above)

Both factors are position-determined. `slot_state` is a property of position, and σ is
overwhelmingly positional on the real board:

| pos | n   | min σ | median σ   | max σ  | full override swing (0.8·median) |
| --- | --- | ----- | ---------- | ------ | -------------------------------- |
| K   | 33  | 20.00 | **20.00**  | 20.00  | 16.00                            |
| DST | 31  | 25.00 | **25.00**  | 25.00  | 20.00                            |
| TE  | 104 | 17.52 | 29.20      | 93.30  | 23.36                            |
| WR  | 207 | 25.98 | 43.30      | 108.47 | 34.64                            |
| RB  | 150 | 35.40 | 59.00      | 94.40  | 47.20                            |
| QB  | 56  | 63.78 | **106.30** | 170.08 | **85.04**                        |

Because the override assigns **opposite signs** to the two candidates being compared, the swing
reaches `0.8·σ ≈ 85` points at QB — larger than the entire MLV signal in the endgame. Observed at
R15 (committed config, hoarding opponents, seat 6):

```
K   Zane Gonzalez     MLV   0.00  λ=+0.40  σ=20.00  risk  −8.00   score −8.00
RB  Croskey-Merritt   MLV −44.80  λ=−0.40  σ=94.40  risk +37.76   score −7.04   <- TAKEN
```

A 45.76-point risk swing overturns a 44.80-point value verdict, to take a player whose own MLV says
he _costs_ 44.80. Note also that K and DST have **zero within-position σ variance** — every kicker
is 20.00, every defense 25.00, both pinned at `_DEFAULT_SIGMA_FLOOR` — so for those two positions
`λ·σ` carries no risk information whatsoever, only a positional shift.

The λ _schedule_ does not have this problem nearly as badly: it applies the same sign to every
candidate in a round, so it is common-mode and only re-ranks by σ, which is the intended "prefer
upside late" behaviour. **The slot override is what breaks common-mode.**

This is a genuine pick-quality defect. It is **not** a legality defect, and Tasks 1–2 do not fix it.
Task 5 measures it, on both objectives, and recommends only if both support a change.

### Honest caveats to carry into the docs

- **A conflict surfaced, not resolved (per `config/league.json`'s `agent_usage_contract`).**
  The league file says only `"Bench": 8` with **no** eligibility. `league/constitution.py:31`
  supplies `_BENCH_ELIGIBLE = (QB, RB, WR, TE)` and its own comment calls it _"a JAAFFL modeling
  choice"_. So "a kicker occupies only the K slot" is the repo's assumption, not the owner's league
  file. Tier 8 does not change either. The fix inherits the assumption the rest of the engine
  already runs on; if CBS actually permits benching a kicker, one constant changes and every
  consumer follows.
- **Every Tier 4–7 calibration number is superseded again.** Tier 7 invalidated them by changing
  what a roster is worth. Tasks 1 and 2 change what the opponents do and what our own agent scores,
  so the numbers move a third time. Task 4 re-establishes the baseline; nothing is compared against
  a stale one.
- **The capacity rule is applied to the SIMULATOR only, never to the live `recommend()` path.**
  The live path could also, in principle, surface a second kicker (his MLV is 0 but a SURPLUS
  `λ = −0.4` pays +8.00). Gating the hot path on `_BENCH_ELIGIBLE` would bet draft night on the
  ambiguous modeling choice above. Recorded as an owner question instead.
- **A simulator is not a fact about drafting.** The opponents are behavioural agents, not the eleven
  people in the room. What these measurements show is that the _harness_ was broken; they do not
  show that the engine will draft well on the night.

---

## File structure

| File                                      | Responsibility                                                              | Change                |
| ----------------------------------------- | --------------------------------------------------------------------------- | --------------------- |
| `backend/src/jaaffl/engine/optimize.py`   | roster structure derived from `LeagueSettings`                              | add `roster_capacity` |
| `backend/src/jaaffl/engine/risk.py`       | **new** — the one shipped risk/slot/punt rule                               | create                |
| `backend/src/jaaffl/engine/recommend.py`  | hot path; now imports the rule instead of owning it                         | modify                |
| `backend/src/jaaffl/engine/simulate.py`   | `SimContext.roster_capacity`; agents honour it; `ScoreAgent` uses `risk.py` | modify                |
| `backend/src/jaaffl/calibrate/tune.py`    | carry capacity from `DraftContext` into `SimContext`                        | modify                |
| `backend/src/jaaffl/calibrate/pools.py`   | fixture pool carries capacity too                                           | modify                |
| `backend/tests/test_optimize.py`          | `roster_capacity` unit tests                                                | add                   |
| `backend/tests/test_simulate.py`          | opponents never roster an illegal player                                    | add                   |
| `backend/tests/test_risk.py`              | imports move to the new home                                                | modify                |
| `backend/tests/test_harness_fidelity.py`  | **new** — the harness can SEE the shipped knobs                             | create                |
| `ROADMAP.md`, `docs/owner-manual-todo.md` | the corrected record                                                        | modify                |

---

### Task 1: `roster_capacity` — how many of a position a team can legally hold

**Files:**

- Modify: `backend/src/jaaffl/engine/optimize.py` (append after `expand_starting_slots`, ~line 52)
- Test: `backend/tests/test_optimize.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_optimize.py`:

```python
def test_roster_capacity_counts_every_slot_a_position_is_eligible_for() -> None:
    """K and DST fit only their own starting slot -- the JAAFFL bench is (QB, RB, WR, TE)."""
    from jaaffl.engine.optimize import roster_capacity
    from tests.engine_fixtures import jaaffl_settings

    capacity = roster_capacity(jaaffl_settings())
    assert capacity[Position.K] == 1
    assert capacity[Position.DST] == 1
    # QB: 1 dedicated starter + the 8 shared bench slots.
    assert capacity[Position.QB] == 9
    # WR: 3 dedicated + the WR/RB flex + 8 bench.
    assert capacity[Position.WR] == 12


def test_roster_capacity_never_reports_a_position_the_roster_cannot_hold() -> None:
    from jaaffl.engine.optimize import roster_capacity
    from tests.engine_fixtures import jaaffl_settings

    assert Position.LB not in roster_capacity(jaaffl_settings())
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q -k roster_capacity`
Expected: FAIL — `ImportError: cannot import name 'roster_capacity'`

- [ ] **Step 3: Implement** in `backend/src/jaaffl/engine/optimize.py`, directly after
      `expand_starting_slots`:

```python
def roster_capacity(settings: LeagueSettings) -> dict[Position, int]:
    """How many players at each position one team can LEGALLY roster: every slot it is eligible for.

    A permissive upper bound at the skill positions (the bench is shared, so counting it once per
    eligible position over-counts) and an EXACT bound at K and DST, which fit only their own
    starting slot because ``league/constitution.py`` gives the bench ``(QB, RB, WR, TE)``. Exactness
    where it matters is the point: the simulated field was drafting 33 of 33 draftable kickers for
    12 teams and holding up to five each, none of which it could have started or benched.

    ``expand_starting_slots``, ``lineup_value`` and ``optimize_roster`` already honour this
    eligibility. This function exists so the draft AGENTS can honour the same rule rather than
    being the one part of the engine that ignores it.
    """
    capacity: dict[Position, int] = defaultdict(int)
    for slot in settings.roster_slots:
        for position in slot.eligible_positions:
            capacity[position] += slot.count
    return dict(capacity)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q`
Expected: PASS, all pre-existing tests in the file included.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/optimize.py backend/tests/test_optimize.py
git commit -m "feat(engine): how many of a position a team can legally roster (#tier8.1)"
```

---

### Task 2: simulated opponents stop drafting players they cannot roster

**Files:**

- Modify: `backend/src/jaaffl/engine/simulate.py` (`SimContext`, and every agent's `pick`)
- Modify: `backend/src/jaaffl/calibrate/tune.py::sim_context_from_draft_context`
- Modify: `backend/src/jaaffl/calibrate/pools.py::demo_sim_context`
- Test: `backend/tests/test_simulate.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_simulate.py`:

```python
def test_no_simulated_team_drafts_a_player_it_cannot_roster() -> None:
    """Measured before this fix: the vbd-only field took 15 of 15 fixture kickers for 12 teams and
    rostered 13 players illegally, manufacturing a famine no engine could survive. That artifact --
    not the scoring rule -- is what Tiers 6 and 7 diagnosed as "the engine cannot draft a kicker".
    """
    from collections import Counter

    from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
    from jaaffl.engine.simulate import ScoreAgent, VbdOnlyAgent, simulate_draft

    ctx = demo_sim_context()
    rosters = simulate_draft(
        ctx,
        our_slot=5,
        our_agent=ScoreAgent(committed_engine_params()),
        opponents=[VbdOnlyAgent()],
        seed=2002,
    )
    illegal = [
        (team, position.value, held)
        for team, roster in enumerate(rosters)
        for position, held in Counter(ctx.position[pid] for pid in roster).items()
        if held > ctx.roster_capacity[position]
    ]
    assert illegal == [], f"teams rostered players they cannot hold: {illegal}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate.py -q -k cannot_roster`
Expected: FAIL — `AttributeError: 'SimContext' object has no attribute 'roster_capacity'`, and once
the field exists, a non-empty list naming K and DST overages.

- [ ] **Step 3: Implement.** In `backend/src/jaaffl/engine/simulate.py`, add the field to
      `SimContext` (after `cliff_bonus`):

```python
    # position -> how many that ONE team may legally roster (engine.optimize.roster_capacity).
    # Empty means "unlimited", which is bit-identical to the pre-Tier-8 behaviour, so a caller
    # that has not opted in is unchanged.
    roster_capacity: Mapping[Position, int] = field(default_factory=dict)
```

Add the shared filter next to `_vbd`:

```python
def _rosterable(
    available: Sequence[str], my_roster: Sequence[str], ctx: SimContext
) -> list[str]:
    """``available`` minus players this roster has no legal slot left for.

    Falls back to the unfiltered pool when nothing is legal, so an agent can never fail to pick --
    a simulated draft that cannot complete is worse than one final illegal pick, and the guard in
    ``test_simulate`` would catch it either way.
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
```

Then make every agent open its `pick` by narrowing the pool. `VbdOnlyAgent`:

```python
    def pick(self, available, my_roster, ctx, rng=None) -> str:
        return max(_rosterable(available, my_roster, ctx), key=lambda p: _vbd(p, ctx))
```

`NeedBasedAgent`:

```python
    def pick(self, available, my_roster, ctx, rng=None) -> str:
        pool = _rosterable(available, my_roster, ctx)
        need = _unfilled_positions(my_roster, ctx)
        if need:
            fillers = [p for p in pool if ctx.position[p] in need]
            if fillers:
                return max(fillers, key=lambda p: ctx.value[p])
        return max(pool, key=lambda p: _vbd(p, ctx))
```

`AdpNoiseAgent`:

```python
    def pick(self, available, my_roster, ctx, rng=None) -> str:
        pool = _rosterable(available, my_roster, ctx)
        if rng is None:  # no rng → deterministic argmin (no noise)
            return min(pool, key=lambda p: ctx.adp.get(p, _FAR))
        return min(
            pool,
            key=lambda p: ctx.adp.get(p, _FAR) + float(rng.normal(0.0, ctx.adp_stdev.get(p, 0.0))),
        )
```

`SoftmaxVbdAgent`, first line of `pick`:

```python
        pool = _rosterable(available, my_roster, ctx)
        candidates = sorted(pool, key=lambda p: _vbd(p, ctx), reverse=True)[: self._cap]
```

`ScoreAgent.pick`, replacing the first use of `available` (the rule binds our agent too — it is a
league rule, not a strategy):

```python
        available = _rosterable(available, my_roster, ctx)
```

- [ ] **Step 4: Populate the field at both construction sites.**
      In `backend/src/jaaffl/calibrate/tune.py::sim_context_from_draft_context`, add to the
      `SimContext(...)` call:

```python
        roster_capacity=roster_capacity(dc.settings),
```

and extend its import: `from jaaffl.engine.optimize import roster_capacity`.

In `backend/src/jaaffl/calibrate/pools.py::demo_sim_context`, add to the `SimContext(...)` call:

```python
        roster_capacity=roster_capacity(settings),
```

and extend its import to `from jaaffl.engine.optimize import expand_starting_slots, roster_capacity`.

- [ ] **Step 5: Run the test, then the whole simulate + calibrate surface**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate.py tests/test_simulate_outcomes.py tests/test_calibrate_pools.py tests/test_tune.py tests/test_late_round_legality.py -q`
Expected: PASS. `test_calibrate_pools` guards each strategic term individually — if any of its
term-sensitivity assertions now fail, STOP: narrowing the pool has made a term unmeasurable and that
must be understood before proceeding, not worked around.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/simulate.py backend/src/jaaffl/calibrate/tune.py \
        backend/src/jaaffl/calibrate/pools.py backend/tests/test_simulate.py
git commit -m "fix(simulate): opponents drafted 33 of 33 kickers into slots that do not exist (#tier8.2)"
```

---

### Task 3: one shipped scoring rule, in one place

**Files:**

- Create: `backend/src/jaaffl/engine/risk.py`
- Modify: `backend/src/jaaffl/engine/recommend.py:42-110` (delete the moved definitions, import them)
- Modify: `backend/tests/test_risk.py:12` (import from the new home)
- Test: `backend/tests/test_harness_fidelity.py` (created in Task 4)

- [ ] **Step 1: Create `backend/src/jaaffl/engine/risk.py`**

Move `SlotState`, `lambda_weight`, `_seat_roster`, `_open_startable_by_position` and `_slot_state`
out of `recommend.py` verbatim (keeping their docstrings), renaming the three private helpers to
`seat_roster`, `open_startable_by_position` and `slot_state_for`, and add the two rules that
`ScoreAgent` has never had:

```python
"""The shipped risk/slot rule (§3.5 + §6.C.5), in ONE place.

This module exists because the rule was implemented twice and the copies diverged. ``recommend.py``
applied ``lambda_slot_override`` and the ``punt_guard``; ``simulate.py::ScoreAgent`` -- the agent
every E2/E6 number is produced by -- applied neither, reading only ``lambda_schedule``. Measured
2026-08-07 over 12 slots x 5 seeds: sign-flipping ``lambda_slot_override`` changed **0 of 60**
simulated rosters, and disabling ``punt_guard`` changed 0 of 60, while doubling ``lambda_schedule``
and zeroing ``alpha`` each changed 60 of 60. So two shipped config keys were unmeasurable, and
Tier 7's closing instruction -- get E2/E6 evidence before touching ``lambda_slot_override`` -- was
impossible to satisfy.

Tier 4 found this same class of defect in this same agent (``candidate_cap`` 50 vs the shipped 180,
ranking by raw value where the engine ranks by MLV) and fixed candidate SELECTION while leaving the
SCORE FUNCTION diverging. One rule implemented twice diverges; the fix is to implement it once.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from enum import StrEnum

from jaaffl.config import EngineParams
from jaaffl.domain import Position
from jaaffl.engine.optimize import StartingSlot


class SlotState(StrEnum):
    """Where a candidate sits relative to your startable need at its position (§3.5)."""

    LAST_OPEN_STARTABLE = "last_open_startable"  # p fills your final open startable slot at its pos
    SURPLUS = "surplus"  # depth/stash beyond startable need
    NORMAL = "normal"


def lambda_weight(round_no: int, slot_state: SlotState, params: EngineParams) -> float:
    """Risk λ for the risk term ``−λ·σ̂`` (design §6.C.5).

    The phase default comes from ``params.lambda_schedule`` (floor-tilt λ>0 early, ceiling-tilt
    λ<0 late); the **slot override dominates** — filling your last open startable slot forces the
    floor tilt, a surplus/stash forces the ceiling tilt (``params.lambda_slot_override``).
    """
    if slot_state is SlotState.LAST_OPEN_STARTABLE:
        return float(params.lambda_slot_override["last_startable_slot_floor"])
    if slot_state is SlotState.SURPLUS:
        return float(params.lambda_slot_override["surplus_stash_ceiling"])
    for entry in params.lambda_schedule:
        low, high = entry["rounds"]
        if low <= round_no <= high:
            return float(entry["lambda"])
    return 0.0  # out-of-schedule round → neutral (never a crash)


def seat_roster(
    my_roster: Sequence[str],
    position: Mapping[str, Position],
    slots: Sequence[StartingSlot],
) -> list[bool]:
    """Greedily seat rostered players into starting slots (maximize seated) → filled-per-slot."""
    remaining: Counter[Position] = Counter(position[p] for p in my_roster if p in position)
    filled = [False] * len(slots)
    for i, slot in enumerate(slots):  # dedicated (single-eligible) slots first
        if len(slot.eligible) == 1:
            pos = next(iter(slot.eligible))
            if remaining.get(pos, 0) > 0:
                filled[i] = True
                remaining[pos] -= 1
    for i, slot in enumerate(slots):  # then flex slots from whatever is left
        if len(slot.eligible) > 1 and not filled[i]:
            for pos in slot.eligible:
                if remaining.get(pos, 0) > 0:
                    filled[i] = True
                    remaining[pos] -= 1
                    break
    return filled


def open_startable_by_position(
    filled: Sequence[bool], slots: Sequence[StartingSlot]
) -> dict[Position, int]:
    """How many open (unfilled) starting slots each position is still eligible to fill."""
    counts: dict[Position, int] = {}
    for i, slot in enumerate(slots):
        if not filled[i]:
            for pos in slot.eligible:
                counts[pos] = counts.get(pos, 0) + 1
    return counts


def slot_state_for(pos: Position, open_startable: Mapping[Position, int]) -> SlotState:
    open_count = open_startable.get(pos, 0)
    if open_count == 0:
        return SlotState.SURPLUS
    if open_count == 1:
        return SlotState.LAST_OPEN_STARTABLE
    return SlotState.NORMAL


def puntable_positions(params: EngineParams) -> frozenset[Position]:
    """Positions the punt guard may demote — the ``punt_guard.stream_round`` keys, one source."""
    return frozenset(Position(key) for key in params.punt_guard.get("stream_round", {}))


def is_punted(
    pos: Position,
    round_no: int,
    params: EngineParams,
    *,
    has_open_non_puntable: bool,
) -> bool:
    """Punt guard (R1): demote K/DST out of #1 before their stream round unless the rest of the
    startable roster is full. It re-ranks, never changes the score."""
    stream_round = int(params.punt_guard.get("stream_round", {}).get(pos.value, 0))
    return bool(
        params.punt_guard.get("enabled")
        and pos in puntable_positions(params)
        and round_no < stream_round
        and has_open_non_puntable
    )


def has_open_non_puntable_slot(
    filled: Sequence[bool], slots: Sequence[StartingSlot], puntable: frozenset[Position]
) -> bool:
    """Is any unfilled starting slot one the punt guard is NOT allowed to defer?"""
    return any(
        not filled[i] and not (slot.eligible <= puntable) for i, slot in enumerate(slots)
    )
```

- [ ] **Step 2: Rewire `recommend.py`.** Delete `SlotState`, `lambda_weight`, `_seat_roster`,
      `_open_startable_by_position` and `_slot_state` (lines 42–110) and import instead:

```python
from jaaffl.engine.risk import (
    SlotState,
    has_open_non_puntable_slot,
    is_punted,
    lambda_weight,
    open_startable_by_position,
    puntable_positions,
    seat_roster,
    slot_state_for,
)
```

Update the three call sites in `recommend()`:

```python
    puntable = puntable_positions(params)
    filled = seat_roster(my_roster, context.position, context.starting_slots)
    open_startable = open_startable_by_position(filled, context.starting_slots)
    has_open_non_puntable = has_open_non_puntable_slot(
        filled, context.starting_slots, puntable
    )
```

```python
        slot_state = slot_state_for(pos, open_startable)
```

```python
        punted = is_punted(
            pos, round_no, params, has_open_non_puntable=has_open_non_puntable
        )
```

`from collections import Counter` stays — `recommend()` still uses it for `drafted_at_pos` and
`roster_by_position`.

- [ ] **Step 3: Point `test_risk.py` at the new home.** Change line 12 to:

```python
from jaaffl.engine.risk import SlotState, lambda_weight
```

- [ ] **Step 4: Make `ScoreAgent` apply the same rule.** In
      `backend/src/jaaffl/engine/simulate.py::ScoreAgent.pick`, replace the `lam = _phase_lambda(...)`
      line and the `score`/`return` block with:

```python
        round_no = len(my_roster) + 1
        filled = seat_roster(list(my_roster), ctx.position, ctx.slots)
        open_startable = open_startable_by_position(filled, ctx.slots)
        puntable = puntable_positions(params)
        open_non_puntable = has_open_non_puntable_slot(filled, ctx.slots, puntable)

        def vona(pid: str) -> float:
            pos = ctx.position[pid]
            others = [mlv[q] for q in candidates if ctx.position[q] == pos and q != pid]
            return mlv[pid] - (max(others) if others else 0.0)

        def score(pid: str) -> float:
            pos = ctx.position[pid]
            lam = lambda_weight(round_no, slot_state_for(pos, open_startable), params)
            return (
                mlv[pid]
                + params.kappa * max(0.0, vona(pid))
                - lam * ctx.sigma.get(pid, 0.0)
                + params.alpha * ctx.cliff_bonus.get(pid, 0.0)
            )

        # Punt-sorted exactly as recommend.py ranks: non-punted first, then score descending.
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
```

Add to `simulate.py`'s imports:

```python
from jaaffl.engine.risk import (
    has_open_non_puntable_slot,
    is_punted,
    lambda_weight,
    open_startable_by_position,
    puntable_positions,
    seat_roster,
    slot_state_for,
)
```

Delete `_phase_lambda` — nothing else calls it. Update `ScoreAgent`'s class docstring: its score is
now the shipped score, including the slot override and punt guard.

- [ ] **Step 5: Check the package export surface**

Run: `cd backend && ../.venv/Scripts/python.exe -c "import jaaffl.engine, jaaffl.engine.risk; print('ok')"`
Expected: `ok`. If `jaaffl/engine/__init__.py` re-exports `SlotState` or `lambda_weight` from
`recommend`, repoint those to `risk` in the same commit.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. `test_late_round_legality.py` is the one to watch — it now walks a draft with a
faithful agent against capacity-capped opponents, which measured 0/192 illegal on the fixture. If it
fails, STOP and measure before changing scoring.

- [ ] **Step 7: Commit**

```bash
git add backend/src/jaaffl/engine/risk.py backend/src/jaaffl/engine/recommend.py \
        backend/src/jaaffl/engine/simulate.py backend/tests/test_risk.py
git commit -m "fix(engine): E2/E6 could not see two shipped coefficients (#tier8.3)"
```

---

### Task 4: a permanent guard that the harness can see what it tunes

**Files:**

- Create: `backend/tests/test_harness_fidelity.py`

- [ ] **Step 1: Write the test** (it fails on the pre-Task-3 code and passes after)

```python
"""The harness must be able to MEASURE the vector it is tuning.

The fourth instance of this project's recurring defect. Tier 4: fixture pools left a bit-identical
roster in 96/96 cells with kappa, alpha and lambda all switched off. Tier 5: alpha multiplied a
cliff_bonus map whose 293 entries were all 0.0. Tier 6: the positional modifiers were unpriceable.
Tier 8: ``ScoreAgent`` read neither ``lambda_slot_override`` nor ``punt_guard``, so Tier 7's closing
instruction -- get E2/E6 evidence before touching ``lambda_slot_override`` -- could not be followed.

Each was invisible because the thing that looked healthy (a map SIZE, a roster COUNT, a green
suite) is not the thing that matters. This test asks the only question that does: change the knob,
does any pick move?
"""

from __future__ import annotations

import pytest

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    simulate_draft,
)

SEEDS = (1001, 1002, 1003, 1004, 1005)


def _rosters(params) -> list[tuple[str, ...]]:
    ctx = demo_sim_context()
    return [
        tuple(
            simulate_draft(
                ctx,
                our_slot=slot,
                our_agent=ScoreAgent(params),
                opponents=[NeedBasedAgent(), AdpNoiseAgent()],
                seed=seed,
            )[slot]
        )
        for slot in range(12)
        for seed in SEEDS
    ]


def _mutate(base, **changes):
    return type(base).model_validate({**base.model_dump(), **changes})


@pytest.mark.parametrize(
    ("label", "changes"),
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
        ("alpha", {"alpha": 0.0}),
    ],
)
def test_the_harness_can_see_every_knob_it_tunes(label: str, changes: dict) -> None:
    """Measured 2026-08-07 before the fix: lambda_slot_override and punt_guard each moved 0 of 60
    rosters, while alpha (the control) moved 60 of 60."""
    base = committed_engine_params()
    moved = sum(1 for a, b in zip(_rosters(base), _rosters(_mutate(base, **changes)), strict=True) if a != b)
    assert moved > 0, f"{label} cannot change a single pick — the harness is blind to it"
```

- [ ] **Step 2: Run it**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_harness_fidelity.py -q`
Expected: PASS on all three params (it would have failed on `lambda_slot_override` and `punt_guard`
before Task 3).

- [ ] **Step 3: Prove it by mutation.** Copy `simulate.py` to the scratchpad first (never
      `git checkout --` uncommitted work), revert `ScoreAgent.pick`'s `lambda_weight(...)` to the
      old `_phase_lambda`-equivalent constant, re-run, and confirm the `lambda_slot_override` case
      FAILS with the blindness message. Restore from the copy. Record the observed failure text in
      the PR body.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_harness_fidelity.py
git commit -m "test(calibrate): a knob the harness cannot see is a knob it cannot tune (#tier8.4)"
```

---

### Task 5: re-measure the baseline, because the harness changed again

**Files:** none (measurement only; results go into `ROADMAP.md` and the PR body)

- [ ] **Step 1: Re-run E2 on the real board with replicates**

```bash
./.venv/Scripts/python.exe scripts/tune_engine_params.py --real --trials 30 --seed 1 --train-seeds 2 --eval-seeds 8 --draws 800 --pool-cap 300 --replicates 5
```

Redirect to a file and poll it — `| tail` on a background command buffers stderr and shows nothing
until exit. Expect roughly 150 s per block unloaded and up to ~530 s under load. That is not a hang.

- [ ] **Step 2: Re-run E6**

```bash
./.venv/Scripts/python.exe scripts/run_tournament.py --seeds 8 --draws 800
```

- [ ] **Step 3: Record BOTH objectives.** Every arm gets win probability _and_ expected points,
      with p-values and the replicate count. A one-sided number is how this project keeps fooling
      itself: Tier 5 showed κ buys championship odds by giving up points. Check the direction of
      `promotion_decision(a, b)` before quoting any p-value — it is one-sided with
      `alternative="greater"`, and Tier 6 found Tier 5 had read two p-values backwards.

- [ ] **Step 4: Record, never adopt.** `config/engine.json` is owner-adopted and the CLI is dry-run
      by default. **Never pass `--write`.**

---

### Task 6: measure the `lambda_slot_override` positional bias — the one real engine defect

**Files:** none yet (measurement); a code change only if the evidence supports one.

- [ ] **Step 1: Measure three arms against the Task 5 baseline**, on win probability AND points,
      `--replicates 5`: 1. `lambda_slot_override` zeroed (the config-only arm). 2. **centred σ** — `λ·(σ_p − median σ at that position)`, so a risk tilt means "more or less
      volatile than typical for his position" rather than "plays a volatile position". Implement
      as a `sigma_median: Mapping[Position, float]` on `SimContext`, frozen at precompute (it is
      a property of the player universe, not of who is left) and defaulting to empty = today's
      raw σ. **The centred value must never be written to `ScoreComponents.sigma`**, which is
      constrained `ge=0` and drives the overlay's risk band; only `risk_penalty` changes. 3. **feasibility gate** — the surplus ceiling is suppressed when `picks_remaining − 1` is less
      than the number of unfilled starting slots, i.e. when this pick cannot be a stash. Reuses
      Tier 7's capacity arithmetic and invents no coefficient.

- [ ] **Step 2: Decide honestly.** Recommend a change only if **both** objectives support it at
      `--replicates 5`. If they disagree, say so and recommend nothing — that is the Tier 5 trade,
      and reporting one side of it is the mistake this audit keeps finding. If the evidence supports
      a code fix, implement it TDD-first with the R15 comparison distilled to a unit test:

```python
def test_a_needed_starter_is_not_outbid_by_a_surplus_body_on_variance_alone() -> None:
    """Measured on the real board, R15: a surplus RB with MLV -44.80 beat a kicker filling the last
    open startable slot with MLV 0.00, because a 45.76-point risk swing overturned a 44.80-point
    value verdict. sigma's median spans 20.0 (K) to 106.3 (QB), so lambda_slot_override * sigma is a
    positional bias term of up to 0.8 * 106.3 = 85 points.
    """
```

- [ ] **Step 3: Propose, never apply.** Any `config/engine.json` edit goes to the owner as a diff in
      the PR body. Do not write the file.

---

### Task 7: correct the record

**Files:**

- Modify: `ROADMAP.md` (new Tier 8 status block above Tier 7)
- Modify: `docs/owner-manual-todo.md` §1b

- [ ] **Step 1: `ROADMAP.md`** — a Tier 8 block in the established voice covering: the corrected root
      cause and that it replaces Tier 7's _and_ Tier 8's own first account; the 24/24-vs-0/24 table;
      the 0/60-vs-60/60 blindness table; the σ-by-position table; the re-measured baseline; what was
      NOT done; and that Tier 4–7 numbers are superseded a third time.

- [ ] **Step 2: `docs/owner-manual-todo.md` §1b** — the current text says the engine will not draft
      a kicker and instructs the owner to take one at R16/R17. Against a legal field the engine takes
      one at median R16 at every seat. Correct the reason, keep a one-line "glance at your empty
      slots from R14" habit, and state plainly that the old warning rested on a simulator artifact.

- [ ] **Step 3: Surface the bench-eligibility conflict** in §1b: `config/league.json` specifies a
      bench COUNT with no eligibility; the repo assumes `(QB, RB, WR, TE)`. Ask the owner to confirm
      whether CBS lets him bench a kicker, and note that the answer changes `roster_capacity`.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md docs/owner-manual-todo.md
git commit -m "docs(roadmap,owner): the kicker famine was the opponent model, not the engine (#tier8.5)"
```

---

### Task 8: verify, PR, merge

- [ ] **Step 1: Full local gate — all of it, from the stated directories**

```bash
.venv/Scripts/python.exe -m pytest backend -q
cd backend && ../.venv/Scripts/python.exe -m ruff check . && ../.venv/Scripts/python.exe -m ruff format --check .
```

```bash
pnpm -r typecheck && pnpm -r test && pnpm lint
```

```bash
.venv/Scripts/python.exe scripts/export_schemas.py && git diff --exit-code packages/shared/schemas
node scripts/gen-overlay-tokens.mjs --check
```

- [ ] **Step 2: Invoke `superpowers:verification-before-completion`**, then the `verify` project
      skill (`.claude/skills/verify`) — it drives the real FastAPI surface, which any
      `backend/src/jaaffl` change requires.

- [ ] **Step 3: Invoke `superpowers:requesting-code-review`.**

- [ ] **Step 4: Push, open the PR with every measurement in the body, wait for all four checks**
      (Backend, Node 22, Node 24, Playwright), squash-merge, delete the branch, then
      `git checkout main && git pull`.

---

## Self-review

- **Spec coverage.** Goal 1 (re-measure) → Task 5, correctly sequenced _after_ Tasks 2–3 because
  either invalidates it. Goal 2 (the endgame defect) → Tasks 1–2, which fix the actual cause, plus
  Task 6 for the separate pick-quality defect Tier 7 mistook for it. The `--replicates >= 3` rule is
  honoured at 5. Both objectives are required at every decision point.
- **Placeholders.** None: every step carries real code or a real command.
- **Type consistency.** `roster_capacity(settings) -> dict[Position, int]` defined in Task 1 and used
  identically in Tasks 2 and 6. `SimContext.roster_capacity: Mapping[Position, int]` and
  `sigma_median: Mapping[Position, float]` both default-empty = today's behaviour, the same opt-in
  shape Tier 7 used for `picks_remaining`. `seat_roster` / `open_startable_by_position` /
  `slot_state_for` / `is_punted` / `has_open_non_puntable_slot` / `puntable_positions` are named
  identically in Task 3's three call sites.
- **Scope.** One subsystem — the calibration harness and the one rule it shares with the hot path.
  No contract, schema, or config change. `config/league.json` untouched; `config/engine.json`
  untouched unless the owner accepts a proposed diff.
