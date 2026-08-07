# Tier 7: the engine cannot fill a legal roster — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the engine recommending a thirteenth tight end while a REQUIRED starting slot is
empty — and, first, make the E2/E6 objective able to _see_ that it is empty.

**Architecture:** One parameter-free change to `engine/optimize.py::lineup_value`: a replacement
phantom may be credited only for a starting slot that a _remaining pick can still fill_. Capacity
is passed as `picks_remaining`; `None` (the default) preserves today's behaviour exactly, so every
existing caller is bit-identical until it opts in. `marginal_lineup_value` decrements capacity for
the pick the candidate consumes (`L*(R ∪ p, k−1) − L*(R, k)`), which is what makes an unfillable
slot show up as a _loss_. The objective (`roster_season_values`, `optimal_lineup_value`) passes
`k = 0` — the draft is over, there are no more picks, an unfilled slot yields nothing.

**Tech Stack:** Python 3.12, pytest, numpy. Backend only; no contract/schema change, no new
config key, no new coefficient.

---

## Why this shape (measured 2026-07-27, real 510-player board)

Two distinct defects, both confirmed by instrumented reproduction. The Tier 6 one-line root cause
("`max(0, ·)` in MLV") is **not** the mechanism and is corrected here.

**Defect 1 — the baseline collapses onto the candidate himself.**
`league/replacement.py:118` computes `remaining = max(0, static_demand − drafted_at_pos)` and takes
`_value_at_rank(ranked, remaining + 1)`. When a position's league-wide startable demand saturates,
`remaining = 0`, so `remaining + 1 = 1` — **rank 1 is the best available player**, and his MLV is
therefore _exactly_ `0.0000` by construction. Measured QB `μ_best − baseline` by round:
`R1 +51.15 · R2 +9.40 · R3 +0.32 · R4 0.0000 · R5 0.0000 …`. DST collapses the same way at R16.
The function's own docstring states it points one past remaining demand precisely to avoid
"collapsing onto the best remaining candidate's own μ" — the `max(0, …)` floor defeats that intent.

**Defect 2 — the risk term outranks value.** `lambda_slot_override` gives a SURPLUS-position
candidate `λ = −0.4` and the LAST_OPEN_STARTABLE candidate `λ = +0.4`. At σ = 46.72 (the
`VOL_RATIO_MAX` clamp saturating) a surplus tight end collects a **+18.69** risk bonus with no
value backing. At R17 the kicker's MLV had _not_ collapsed — it was **+13.16** — and he still lost,
because `13.16 < 18.69`. **Fixing the baseline alone would not have produced a legal roster.**

**Defect 3 — and the reason this survived six tiers: the objective cannot see either.**
`simulate.py::roster_season_values` delegates to the same `lineup_value`, which credits
`baselines[QB] = 230.64` for an empty QB slot. Measured on the real board, swapping the 3 worst
tight ends for the _actual_ R15–R17 leftovers (Davis Mills QB μ=83.60, Brandon Aubrey K μ=89.98,
Buffalo DST μ=87.19):

|                                              | points      |
| -------------------------------------------- | ----------- |
| objective's verdict (`optimal_lineup_value`) | **+15.34**  |
| truth (unfilled required slot scores 0)      | **+260.77** |
| visible fraction                             | **5.9%**    |

The visible +15.34 is _entirely_ the kicker (89.98 − 74.64). The QB and the DST contribute
**exactly zero** — a roster holding them is worth precisely as much as a roster with neither.
**No E2/E6 gate could ever have promoted a fix**, because the instrument could not measure the
thing being fixed. That is why the objective is fixed first, in the same change.

### Why capacity, and why it is safe

`u` = starting slots that take a phantom; `k` = picks remaining. Crediting at most `k` phantoms is
**inert whenever `k − 1 ≥ u`** — both `L*(R, k)` and `L*(R ∪ p, k−1)` credit all `u`, so MLV is
unchanged. With `u = 3` (QB/K/DST) that means **rounds 1–14 are bit-identical**; the rule binds
only at R15/16/17, exactly the three picks needed for the three empty slots. Hand-worked from the
instrumented run (R15 dynamic baselines QB 98.83 · K 72.06 · DST 93.17):

- take a 14th TE → `L*(R∪TE, 2) − L*(R, 3)` = `192.00 − 264.06` = **−72.06**
- take the best K (μ 89.98) → `281.98 − 264.06` = **+17.92**

The tight end goes from winning on a +18.69 risk bonus to losing by 72 points of lineup value.
No coefficient was invented to achieve that.

### Honest caveats to carry into the docs

- **`k = 0` in the objective invalidates every historical E2/E6 number.** Findings B, C and D
  (noise floor, kappa/reliability resolution, the §10.3 sweeps) were measured under the blind
  objective. They are not comparable to anything measured after this change. Task 6 re-measures the
  baseline; nothing is promoted against a stale one.
- **No waiver wire is modelled.** Real fantasy lets you stream a replacement; `config/league.json`
  specifies no waiver rules and inventing one would breach its `agent_usage_contract`. Scoring an
  unfilled slot at 0 is the faithful reading of "this is the roster the draft produced", and the
  caveat is stated rather than papered over.
- **This guarantees legality, not optimal timing.** Filling QB at R15 is legal but late. Whether
  the engine should take a QB at R10 instead is a _measurable_ question for the first time — it is
  Task 7, not an assumption baked into Task 2.

---

## File structure

| File                                        | Responsibility                                       | Change                                                                   |
| ------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ |
| `backend/src/jaaffl/engine/optimize.py`     | the capacity rule itself                             | modify `lineup_value`, `lineup_value_hungarian`, `marginal_lineup_value` |
| `backend/src/jaaffl/engine/simulate.py`     | objective passes `k=0`; `ScoreAgent` passes real `k` | modify `optimal_lineup_value`, `roster_season_values`, `ScoreAgent.pick` |
| `backend/src/jaaffl/engine/recommend.py`    | hot path passes real `k`                             | modify the MLV call sites                                                |
| `backend/src/jaaffl/league/coverage.py`     | new guard: does a walked draft end LEGAL?            | add `unfillable_starting_slots`                                          |
| `backend/tests/test_optimize.py`            | capacity unit tests                                  | add                                                                      |
| `backend/tests/test_simulate_outcomes.py`   | objective can now see an empty slot                  | add                                                                      |
| `backend/tests/test_late_round_legality.py` | regression: walk a draft, assert a LEGAL roster      | create                                                                   |
| `backend/tests/test_coverage_guards.py`     | the new guard fires                                  | add                                                                      |

---

### Task 1: `lineup_value` learns capacity

**Files:**

- Modify: `backend/src/jaaffl/engine/optimize.py:59-109`
- Test: `backend/tests/test_optimize.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_lineup_value_default_is_unchanged_by_the_capacity_parameter() -> None:
    """picks_remaining=None must be bit-identical to the pre-Tier-7 behaviour."""
    ids, mu, pos, base, slots = _tiny_board()
    assert lineup_value(ids, mu, pos, base, slots) == lineup_value(
        ids, mu, pos, base, slots, picks_remaining=None
    )


def test_an_unfilled_slot_earns_no_phantom_when_no_picks_remain() -> None:
    """The draft is over: an empty required slot yields nothing, not replacement value."""
    ids, mu, pos, base, slots = _tiny_board()
    full = lineup_value([], mu, pos, base, slots, picks_remaining=None)
    none_left = lineup_value([], mu, pos, base, slots, picks_remaining=0)
    assert full > 0.0
    assert none_left == 0.0


def test_capacity_credits_the_most_valuable_slots_first() -> None:
    """With one pick and two empty slots you fill the better one, so the cheaper phantom drops."""
    ids, mu, pos, base, slots = _tiny_board()
    one = lineup_value([], mu, pos, base, slots, picks_remaining=1)
    assert one == max(base[p] for p in base)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q -k capacity or phantom`
Expected: FAIL — `lineup_value() got an unexpected keyword argument 'picks_remaining'`

- [ ] **Step 3: Implement**

In `lineup_value`, collect phantoms instead of adding them inline, then keep only the top
`picks_remaining`:

```python
def lineup_value(
    player_ids, mu, position, baselines, slots, *, picks_remaining: int | None = None
) -> float:
    ...
    total = 0.0
    phantoms: list[float] = []
    for slot in dedicated:
        ...
        if i < len(available) and available[i] >= phantom:
            total += available[i]
            cursor[pos] = i + 1
        else:
            phantoms.append(phantom)
    for slot in flex:
        ...
        if best_pos is not None:
            cursor[best_pos] += 1
            total += best_value
        else:
            phantoms.append(best_value)
    if picks_remaining is not None:
        phantoms.sort(reverse=True)
        del phantoms[picks_remaining:]
    return total + sum(phantoms)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q`
Expected: PASS, and every pre-existing test in the file still passes (they all use the default).

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/optimize.py backend/tests/test_optimize.py
git commit -m "feat(engine): a replacement phantom needs a pick left to fill it (#tier7.1)"
```

---

### Task 2: `marginal_lineup_value` spends a pick

**Files:**

- Modify: `backend/src/jaaffl/engine/optimize.py:147-161`
- Test: `backend/tests/test_optimize.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mlv_of_a_surplus_body_is_negative_when_a_required_slot_is_at_risk() -> None:
    """The headline: with 1 pick and 2 empty required slots, a bench body COSTS you a slot."""
    ids, mu, pos, base, slots = _tiny_board()
    roster: list[str] = []
    surplus = _a_player_whose_slot_is_already_covered(ids, pos)
    assert marginal_lineup_value(
        surplus, roster, mu, pos, base, slots, picks_remaining=1
    ) < 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q -k surplus`
Expected: FAIL — unexpected keyword `picks_remaining`.

- [ ] **Step 3: Implement**

```python
def marginal_lineup_value(
    candidate_id, roster, mu, position, baselines, slots, *,
    base_value: float | None = None, picks_remaining: int | None = None,
) -> float:
    """MLV_p = L*(B(R ∪ {p}), k−1) − L*(B(R), k).

    Taking ``p`` SPENDS a pick, so the candidate roster is valued with one less. That decrement is
    the whole mechanism: it is what turns "a slot I can no longer fill" into a measured loss
    rather than a silent zero. Inert while ``k − 1 >= u`` (u = slots taking a phantom), which on
    this league's roster means rounds 1-14 are bit-identical.
    """
    if base_value is None:
        base_value = lineup_value(
            roster, mu, position, baselines, slots, picks_remaining=picks_remaining
        )
    after = None if picks_remaining is None else max(0, picks_remaining - 1)
    with_candidate = lineup_value(
        [*roster, candidate_id], mu, position, baselines, slots, picks_remaining=after
    )
    return with_candidate - base_value
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/optimize.py backend/tests/test_optimize.py
git commit -m "feat(engine): MLV spends the pick it costs (#tier7.2)"
```

---

### Task 3: the objective stops crediting phantoms it cannot fill

**Files:**

- Modify: `backend/src/jaaffl/engine/simulate.py:47-57` (`optimal_lineup_value`), `:92-116`
  (`roster_season_values`)
- Test: `backend/tests/test_simulate_outcomes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_objective_can_tell_an_unfillable_roster_from_a_legal_one() -> None:
    """Pre-Tier-7 these scored IDENTICALLY: the empty QB slot was credited its baseline.

    Measured on the real board, the blind objective saw 5.9% of a 260.77-point gap.
    """
    ctx = _pool_ctx()
    legal = ["qb0", "rb0", "wr0", "te0", "k0", "dst0"]
    illegal = [p for p in legal if not p.startswith("qb")] + ["te1"]
    assert optimal_lineup_value(illegal, ctx) < optimal_lineup_value(legal, ctx)


def test_a_sub_replacement_starter_beats_an_empty_slot() -> None:
    """A below-replacement QB you can START is worth more than a phantom you cannot."""
    ctx = _pool_ctx()
    worst_qb = min(
        (p for p in ctx.value if ctx.position[p] is Position.QB), key=lambda p: ctx.value[p]
    )
    assert optimal_lineup_value([worst_qb], ctx) > optimal_lineup_value([], ctx)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate_outcomes.py -q -k unfillable or sub_replacement`
Expected: FAIL — both assertions compare equal.

- [ ] **Step 3: Implement**

```python
def optimal_lineup_value(roster: Sequence[str], ctx: SimContext) -> float:
    """...

    **Scored as a FINAL roster** (``picks_remaining=0``): the draft is over, so a starting slot the
    roster cannot fill yields nothing rather than its replacement baseline. Before Tier 7 the
    phantom was credited unconditionally, which made a roster with no QB worth exactly as much as
    one with a replacement QB — measured on the real board, this objective saw 5.9% of a
    260.77-point gap, so no gate could ever have promoted a fix for it. No waiver wire is modelled;
    ``config/league.json`` specifies none and inventing one would breach its usage contract.
    """
    return lineup_value(
        roster, ctx.value, ctx.position, ctx.baselines, ctx.slots, picks_remaining=0
    )
```

and in `roster_season_values`, both the empty-roster short circuit and the per-draw call gain
`picks_remaining=0`.

- [ ] **Step 4: Run the whole simulate suite**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate_outcomes.py tests/test_simulate.py -q`
Expected: PASS — **including** the σ=0 equivalence pin, which compares two functions that both now
pass `picks_remaining=0`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/simulate.py backend/tests/test_simulate_outcomes.py
git commit -m "fix(engine): the objective could not see an unfillable roster (#tier7.3)"
```

---

### Task 4: the live hot path and `ScoreAgent` pass real capacity

**Files:**

- Modify: `backend/src/jaaffl/engine/recommend.py` (the `marginal_lineup_value` call sites)
- Modify: `backend/src/jaaffl/engine/simulate.py::ScoreAgent.pick:293-322`
- Test: `backend/tests/test_engine_latency.py` (must still pass, unchanged)

- [ ] **Step 1: Write the failing test** in `backend/tests/test_late_round_legality.py`

```python
def test_score_agent_finishes_with_every_required_slot_filled() -> None:
    """Tier 6 walked this draft and got {RB:1, TE:13, WR:3} -- 3 unfillable starting slots."""
    ctx = demo_sim_context()
    rosters = simulate_draft(
        ctx, our_slot=5, our_agent=ScoreAgent(committed_engine_params()),
        opponents=[NeedBasedAgent(), AdpNoiseAgent()], seed=1001,
    )
    assert unfillable_starting_slots(rosters[5], ctx.position, ctx.slots) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_late_round_legality.py -q`
Expected: FAIL — the roster leaves QB/K/DST unfilled.

- [ ] **Step 3: Implement.** In `ScoreAgent.pick`:

```python
        k = max(0, ctx.roster_size - len(my_roster))
        base = lineup_value(
            list(my_roster), value, ctx.position, ctx.baselines, ctx.slots, picks_remaining=k
        )
        all_mlv = {
            p: marginal_lineup_value(
                p, my_roster, value, ctx.position, ctx.baselines, ctx.slots,
                base_value=base, picks_remaining=k,
            )
            for p in available
        }
```

In `recommend.py`, compute `picks_remaining = roster_size - len(my_roster)` once and thread it into
the base `lineup_value` and every `marginal_lineup_value` call.

- [ ] **Step 4: Run the test, then the latency budget**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_late_round_legality.py tests/test_engine_latency.py -q`
Expected: PASS. The added work is one extra sort of a ≤9-element list per `lineup_value` call, so
the p95 < 200 ms budget must be unaffected — if it is not, stop and measure before proceeding.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/recommend.py backend/src/jaaffl/engine/simulate.py backend/tests/test_late_round_legality.py
git commit -m "fix(engine): the engine drafts a roster it can actually start (#tier7.4)"
```

---

### Task 5: the guard, and proof that it fires

**Files:**

- Modify: `backend/src/jaaffl/league/coverage.py` (append `unfillable_starting_slots`)
- Modify: `backend/tests/test_coverage_guards.py`
- Modify: `scripts/preflight.py` (report, do not fail — it has no roster to check pre-draft)

- [ ] **Step 1: Write the failing test**

```python
def test_unfillable_starting_slots_names_every_empty_required_slot() -> None:
    settings, position, slots = _league()
    roster = ["te0"] * 13 + ["wr0", "wr1", "wr2", "rb0"]
    assert unfillable_starting_slots(roster, position, slots) == ["DST", "K", "QB"]


def test_a_legal_roster_reports_nothing() -> None:
    settings, position, slots = _league()
    assert unfillable_starting_slots(_a_legal_roster(), position, slots) == []
```

- [ ] **Step 2: Run to verify it fails.** Expected: `ImportError`.

- [ ] **Step 3: Implement**, modelled on `inert_cliff_positions` — report, never raise:

```python
def unfillable_starting_slots(
    roster: Sequence[str],
    position: Mapping[str, Position],
    slots: Sequence[StartingSlot],
) -> list[str]:
    """Starting slots this roster cannot fill, by label, sorted. Empty in the healthy case.

    The fourth instance of this module's one question. A roster SIZE read healthy for six tiers:
    17 of 17 picks made, and three of the nine starting slots unfillable. Counts the slots the
    flex-aware assignment leaves empty, so the WR/RB flex is honoured rather than assumed.
    """
```

- [ ] **Step 4: Prove the guard fires by mutation — on the REAL board, not a fixture**

Revert Task 4's `ScoreAgent` change in the working tree only (`cp` the file to the scratchpad
first — never `git checkout --` uncommitted work), re-run
`tests/test_late_round_legality.py`, and confirm it FAILS naming QB/K/DST. Restore from the copy.
Record the observed failure text in the PR body.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/league/coverage.py backend/tests/test_coverage_guards.py scripts/preflight.py
git commit -m "feat(league): a fourth board guard -- can this roster start nine players (#tier7.5)"
```

---

### Task 6: re-measure the baseline, because the objective changed

**Files:** none (measurement only; results go into `ROADMAP.md`)

- [ ] **Step 1: Re-run E2 on the real board with replicates**

```bash
./.venv/Scripts/python.exe scripts/tune_engine_params.py --real --trials 30 --seed 1 --train-seeds 2 --eval-seeds 8 --draws 800 --pool-cap 300 --replicates 3
```

Have it write incremental JSON to a file and poll that file — `| tail` on a background command
buffers stderr and shows nothing until exit. Expect ~150 s per block unloaded, up to ~530 s if
HEATER's 40-60 python processes are running. That is not a hang.

- [ ] **Step 2: Record, do not adopt.** `config/engine.json` is owner-adopted and the CLI is
      dry-run by default. Never pass `--write`.

- [ ] **Step 3: State plainly in `ROADMAP.md` that findings B, C and D were measured under the
      blind objective and are superseded**, with the new numbers beside them where re-measured and an
      explicit "not re-measured" where not.

---

### Task 7 (deferred to Tier 8 unless time allows): is R15 the right round?

Task 4 guarantees a **legal** roster; it does not claim the _timing_ is optimal. With the objective
fixed, "should the engine take a QB at R10 instead of R15?" is measurable for the first time. Do
not fold an answer into Task 4 — measure it separately, with `--replicates >= 3`, and check the
direction of the one-sided test before quoting any p-value.

---

## Self-review

- **Spec coverage.** Tier 7 goal 1 → Tasks 1-5. Goal 2 (points for the kappa/lambda sweeps) is
  **blocked by Task 3**: those sweeps must be re-run under the fixed objective, so they move to
  Tier 8 rather than being reported against a superseded instrument. Goal 3 (the σ clamp) is
  implicated in Defect 2 and is recorded with its measurement. Goal 4 (what the objective cannot
  see) is answered in the docs from the `_positional_modifiers` evidence.
- **Placeholders.** None: every step carries real code or a real command.
- **Type consistency.** `picks_remaining: int | None` keyword-only on `lineup_value` and
  `marginal_lineup_value`; `unfillable_starting_slots(roster, position, slots) -> list[str]`
  used identically in Tasks 4 and 5.
