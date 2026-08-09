# Tier 10: the engine drafts half its roster in dictionary order — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain and close the residual Tier 9 left open — with `lambda_slot_override` zeroed the
engine still wins the championship **less often than a plain VBD draft** (0.0683 vs 0.1066 on the
real board, against a 12-team fair share of 0.0833). The cause is not a coefficient. Once the
starting nine is full, every remaining candidate scores **exactly 0.0**, and the engine's ranking
degenerates to `context.mu` **dictionary insertion order** — for 8 of its 17 picks.

**Architecture:** One shared rule, `optimize.value_over_replacement` (μ − replacement baseline),
used as a deterministic **secondary sort key** in the `candidate_cap` cut that `recommend.py` and
`simulate.ScoreAgent` each make. (The plan originally changed the final rank key too; mutation
showed that half moved zero picks — see "Two ways implementation diverged" below.) VOR is not a new
signal — it is exactly what `marginal_lineup_value` reduces to before the lineup floors it at zero
(`optimize.py`'s own stated reduction guarantee), so the change restores information the floor
discards rather than inventing a term. Nothing is added to any score, so no `ScoreComponents`
decomposition changes and the anti-black-box guarantee is untouched.

**Tech Stack:** Python 3.12, pytest, numpy, scipy. Three engine modules and four test modules. No
contract or schema change, no new config key, no new coefficient, no edit to `config/engine.json` or
`config/league.json`.

---

## Why this shape (measured 2026-08-09; every number labelled with its pool)

### The residual reproduces exactly

`scripts/run_tournament.py`'s design, replayed on the **real** board (581 players capped to 300),
5 disjoint blocks × 8 seeds × 12 slots, 800 sampled seasons, field `[SoftmaxVbd, NeedBased]`:

```
vbd_only      win 0.1066   points 1661.7
override_off  win 0.0683   points 1713.5
ours          win 0.0072   points 1459.9
```

Digit-for-digit identical to the Tier 9 block in `ROADMAP.md`. The residual is real and stable.

### 🔴 THE FINDING — three terms vanish on the same candidates, and the sort key is dict order

Once every starting slot is filled, a below-replacement candidate gets:

| term               | value               | why                                                               |
| ------------------ | ------------------- | ----------------------------------------------------------------- |
| `MLV`              | **exactly 0.00**    | `L*(R∪{p}) − L*(R)`; he cracks no starting slot                   |
| `κ · max(0, VONA)` | **exactly 0.00**    | `expected_best_available` ≥ 0 while MLV = 0, so VONA ≤ 0 → clamp  |
| `α · cliff_bonus`  | **exactly 0.00**    | legitimately 0 below replacement (`engine/tiers.py` docstring)    |
| `− λ · σ`          | **exactly 0.00** \* | every position is `SURPLUS` once filled → `surplus_stash_ceiling` |
| **score**          | **0.0000**          | for every remaining candidate                                     |

\* with `lambda_slot_override` zeroed — the change Tier 8 and Tier 9 both recommend and the owner
has not yet made.

`recommend.py:350` then sorts `key=(punted, -score)`. Python's sort is **stable**, so ties keep the
order of `candidates`, which is a stable sort of `available`, which is
`[pid for pid in context.mu if pid not in picked]` — **`context.mu` insertion order**.

**Measured on the SHIPPED hot path** (`recommend()`, real board, a real entered `draft_order` so
survival is live, round 14, `lambda_slot_override` zeroed):

```
survival_basis = my_slot
candidates sharing the TOP score (0.000000) exactly:  180 of 180
candidates with a POSITIVE vona (so kappa could break the tie):  0
tie order == context.mu insertion order?              True
projected points of the top 12, in ranked order:
    [122.9, 16.0, 21.2, 37.5, 31.7, 127.5, 75.5, 47.9, 61.7, 66.9, 24.7, 57.3]
engine's #1: mu=122.9    vs BEST tied mu=204.2    (gap 81.4 points)
```

This is **not** a simulator artifact. It is what the overlay would show on draft night.

The same defect is visible behaviourally in the simulator. Re-asking the shipped agent the identical
question with the pool presented in reverse order, real board, 3 slots × 3 seeds = 153 of our picks:

| arm                | picks decided by **list order**         | mean VBD of the 8 weakest picks |
| ------------------ | --------------------------------------- | ------------------------------- |
| ours (committed)   | 36/153 (23.5%)                          | −56.06                          |
| **`override_off`** | **70/153 (45.8%)** — every pick R10→R17 | **−121.63**                     |
| `vbd_only`         | **0/153 (0.0%)**                        | **−37.99**                      |

There are **two** ordering decisions, not one, and both are dict-order today:

1. `recommend.py:277` / `simulate.py:412` — `sorted(available, key=mlv, reverse=True)[:cap]`. At
   round 14 that cap selects **180 of 425** available players, and when MLV ties at 0 the selection
   is dict order. A player never scored cannot be recommended.
2. `recommend.py:350` / `simulate.py:455` — the final rank among equal scores.

### Where the gap lives — decomposing what `win_probability` consumes, on the REAL board

Tier 9 ran this decomposition on the fixture. The real board disagreed with the fixture on the
decisive comparison, so it is redone here. 12 slots × 4 seeds × 400 draws:

| arm                          | p(win)     | realized season μ | realized **sd** | E[field max] | points     | slots filled | bench VBD |
| ---------------------------- | ---------- | ----------------- | --------------- | ------------ | ---------- | ------------ | --------- |
| ours (committed)             | 0.0061     | 1529.5            | 211.6           | 2134.6       | 1461.4     | 8.00         | −55.5     |
| `override_off`               | 0.0732     | 1802.0            | 192.4           | 2137.6       | 1710.7     | 9.00         | −122.5    |
| **`override_off`+vbd_order** | **0.1127** | **1866.2**        | 186.1           | 2135.7       | **1714.5** | 9.00         | **−37.8** |
| `vbd_only`                   | 0.0953     | 1823.1            | 181.7           | 2130.6       | 1648.9     | 8.81         | −38.0     |

Three things fall out:

1. **`E[field max]` is flat across all four arms** (2130.6–2137.6, a 7-point spread against a
   337-point gap). "Our picks leave a stronger field behind" is refuted here as it was on the
   fixture — **the field is innocent.**
2. **Our starting nine was already better than VBD's** — 9.00 vs 8.81 slots filled, 1710.7 vs 1648.9
   points. The engine was losing the championship **purely on the bench**.
3. **The fix is not variance.** It wins with a **lower** realized sd (186.1 vs 192.4) and a **less**
   volatile bench. It wins on realized **mean** (+64.2), which is what a better bench buys once
   `roster_season_values` re-optimises the lineup.

### The fix, measured — and the refuting control came out the right way

Real board, **5 disjoint blocks × 8 seeds × 12 slots, 800 draws**, all arms sharing ONE `SimContext`
so the sampled seasons stay common random numbers:

| arm                          | win prob   | points     |
| ---------------------------- | ---------- | ---------- |
| **`override_off`+vbd_order** | **0.1161** | **1716.7** |
| `vbd_only`                   | 0.1066     | 1661.7     |
| `override_off`+**sig_order** | 0.0990     | 1715.7     |
| `override_off`               | 0.0683     | 1713.5     |
| ours (committed)             | 0.0072     | 1459.9     |
| ours + vbd_order             | 0.0071     | 1450.1     |

Every pair, gated exactly as E2 gates: one-sided Wilcoxon across the 12 slots **plus** the
noise-aware non-regression leg, with `slot_noise` measured as the sd of the paired difference across
the 5 blocks. "beats" requires **both** legs.

| A vs B                                   | objective | A      | B      | A−B         | min slot | p          | beats?  |
| ---------------------------------------- | --------- | ------ | ------ | ----------- | -------- | ---------- | ------- |
| **`override_off`+vbd vs `override_off`** | win       | 0.1161 | 0.0683 | **+0.0478** | +0.0340  | **0.0002** | **YES** |
| **`override_off`+vbd vs `override_off`** | points    | 1716.7 | 1713.5 | **+3.1**    | +0.5     | **0.0002** | **YES** |
| `override_off`+vbd vs `override_off`+sig | win       | 0.1161 | 0.0990 | **+0.0171** | +0.0064  | **0.0002** | **YES** |
| `override_off`+vbd vs `override_off`+sig | points    | 1716.7 | 1715.7 | +1.0        | −2.4     | 0.0547     | no      |
| `override_off`+sig vs `override_off`     | win       | 0.0990 | 0.0683 | +0.0307     | +0.0270  | 0.0002     | YES     |
| **`override_off`+vbd vs `vbd_only`**     | win       | 0.1161 | 0.1066 | +0.0095     | −0.0241  | **0.1167** | **no**  |
| **`override_off`+vbd vs `vbd_only`**     | points    | 1716.7 | 1661.7 | **+55.0**   | +1.3     | **0.0002** | **YES** |
| `override_off` vs `vbd_only` _(Tier 9)_  | win       | 0.0683 | 0.1066 | −0.0383     | −0.0749  | 0.9998     | no      |
| `override_off` vs `vbd_only` _(Tier 9)_  | points    | 1713.5 | 1661.7 | +51.9       | −4.5     | 0.0005     | YES     |
| `ours` vs `vbd_only` _(Tier 9)_          | win       | 0.0072 | 0.1066 | −0.0994     | −0.1362  | 1.0000     | no      |
| `ours` vs `vbd_only` _(Tier 9)_          | points    | 1459.9 | 1661.7 | −201.8      | −266.1   | 1.0000     | no      |

The four rows marked _(Tier 9)_ reproduce that tier's published real-board figures **to the digit**
(−0.0383 / +51.9 and −0.0994 / −201.8), which is the control that says this harness is measuring the
same thing Tier 9 measured.

⚠️ **State the verdict precisely, because the tempting version is wrong.** Against `vbd_only` the
fixed engine **beats it on points** (+55.0, p = 0.0002, non-negative at every one of the 12 slots)
and is **ahead but NOT significantly ahead on championship probability** (+0.0095, p = 0.1167). The
E6 win-probability leg carries per-slot paired noise of median ~0.02, so a +0.0095 point estimate
sits well inside it. **The correct claim is that the residual is eliminated, not that the engine now
out-titles VBD:** the comparison moves from a clear loss (−0.0383, p = 0.9998) to a statistical
tie with the point estimate in our favour, while the engine goes from 0.0683 to 0.1161 against a
12-team fair share of 0.0833. Anyone writing "the engine now beats best-available on both
objectives" is quoting a p-value that does not exist.

**The refuting control.** The obvious alternative account is "the tie is not the problem; the
objective just rewards any bench that raises spread." That is **refuted by `sig_order`**, which
breaks the identical ties toward high σ instead of high value: the value key beats it by **+0.0171
at p = 0.0002** on championship probability. Any deterministic order beats no order — σ recovers
+0.0307 on its own, because σ is a noisy proxy for value (better players carry more upside) — but
value is worth a further 56% on top of it. Honest limit: on the **points** leg the two are
indistinguishable (+1.0, p = 0.0547), so the refutation rests on the championship leg alone.

**A second control, and it is the one that changes the owner's decision.** `ours+vbd_order` is
0.0071 against ours' 0.0072 — **no effect** on championship probability — and it _costs_ 9.8 points.
With `lambda_slot_override` live, `λ = ±0.4` already breaks the ties by σ, so there is little left
for a tiebreak to fix, and the candidate-cap change is a small net negative. **The code fix and the
config change are coupled: neither is sufficient alone, and the code fix does not pay until the
config change is made.** That coupling is stated in `docs/owner-manual-todo.md` by Task 7.

### Measurability first — the hard rule, satisfied before any of the above was trusted

The harness must be able to SEE what it measures. Here the guard is a **property**, not a knob:
simulated rosters must not depend on the order the pool is presented in. Measured today over
12 slots × 5 seeds under the committed config, presenting our agent's pool reversed:

```
rosters that CHANGE under a reversed pool:  many (23.5% of picks move under the committed
                                            config; 45.8% with lambda_slot_override zeroed)
```

So the property fails today and is a real guard, not a tautology. Task 5 adds it to
`tests/test_harness_fidelity.py`.

### Why six tiers of calibration never caught it — instance six of the recurring defect

This is the sixth instance, and the first in the **objective** rather than the pool, the agent or
the gate:

- **Tier 4** — both fixture pools were params-blind (96/96 identical rosters).
- **Tier 5** — `alpha` multiplied a `cliff_bonus` map of 293 zeros.
- **Tier 6** — three positional modifiers were priced by nothing.
- **Tier 8** — `ScoreAgent` read neither `lambda_slot_override` nor `punt_guard` (0/60 rosters).
- **Tier 9** — E6 had no `--replicates` and gated on a leg Tier 6 had discredited.
- **Tier 10 — `mean_lineup_value_objective` prices a bench player at exactly 0.** It scores the
  optimal nine under fixed μ, so 8 of 17 picks are worth nothing to it. The fix moves that objective
  by **+3.2 points** (inside its own noise) and the championship objective by **+0.0478**. The
  points leg did not merely miss the defect — under `override_off` it reported the engine as the
  **best points-scorer in the field** while it was drafting half its roster alphabetically.

### Honest caveats to carry into the docs

- **The two objectives still bracket bench value, and neither is right.**
  `mean_lineup_value_objective` prices a bench player at 0; `roster_season_values` re-optimises the
  lineup with **perfect hindsight** of the realised season, which is an upper bound on option value.
  The true value of a better bench is between them, so the **size** of the +0.0478 is
  objective-dependent. What is _not_ objective-dependent: a bench chosen by dictionary order is
  worse than one chosen by value under any objective that is not identically zero, and the fix costs
  nothing on the points leg. **This tier surfaces the bracketing again and does not fix it** — that
  needs a week axis and belongs to its own tier.
- **The blast radius is not zero, and the plan does not claim it is.** The _final-rank_ tiebreak
  fires only on exact score ties, so it cannot change any comparison where scores differ. The
  _candidate-cap_ tiebreak **can**, because it changes which players are scored at all. Both are
  real defects; both are fixed here; the second is why `ours+vbd_order` moves at all.
- **No week axis.** `sample_season_outcomes` still draws one independent season total per player, so
  `bye_stack`, `handcuff_synergy` and `sos` remain unmeasurable and unimplemented.
- **A simulator is not a fact about drafting.** The opponents are behavioural agents, not the eleven
  people in the room. These numbers show what the ordering defect costs against these bots on this
  board. They do not show what it costs on draft night.
- **Nothing is written to `config/engine.json`.** It is owner-adopted. Verified 2026-08-09: it still
  reads `{last_startable_slot_floor: 0.4, surplus_stash_ceiling: -0.4}`, so the Tier 8/9
  recommendation is **still OPEN**. Task 7 re-states it with the new coupling evidence; it does not
  apply it.
- **`config/league.json` is untouched.** The bench-eligibility question Tier 8 raised
  (`constitution._BENCH_ELIGIBLE`) is still open and still the owner's.

---

### ⚠️ Two ways implementation diverged from this plan (recorded, not hidden)

1. **Half the planned fix was blind, and mutation caught it.** The plan put the tiebreak in BOTH the
   `candidate_cap` cut and the final rank key. Mutating the rank key moved **zero** picks — `min()`
   and `list.sort` are stable, so the rank already inherits the cut's order — so by this project's
   own standard (`test_harness_fidelity`: change it, does a pick move?) that half was decoration and
   was dropped. Only the candidate cut carries the tiebreak.
2. **The live path has a side effect the simulator structurally cannot see.** VOR is a positional
   scarcity measure, so it rates a spare kicker above a deep receiver even when the roster is full at
   K. `_rosterable` gates `roster_capacity` in the simulator, so the measured +0.0478 is an
   among-rosterable-players figure; `recommend()` has no such gate. Measured by walking three full
   drafts through `recommend()`: **0 of 51 picks pre-fix, 1 of 51 post-fix** had no legal roster slot.
   Not gated — Tier 8 declined to gate the hot path because it would bet draft night on
   `constitution._BENCH_ELIGIBLE`, an owner question that is still open. Surfaced in
   `docs/owner-manual-todo.md` §1b with the measurement attached.

---

## File structure

| File                                      | Responsibility                        | Change                       |
| ----------------------------------------- | ------------------------------------- | ---------------------------- |
| `backend/src/jaaffl/engine/optimize.py`   | MLV + the lineup solver               | add `value_over_replacement` |
| `backend/src/jaaffl/engine/simulate.py`   | E2/E6 agents                          | 1 sort key; `_vbd` delegates |
| `backend/src/jaaffl/engine/recommend.py`  | the live hot path                     | 1 sort key                   |
| `backend/tests/test_optimize.py`          | MLV/lineup unit cover                 | add 1 test                   |
| `backend/tests/test_simulate.py`          | agent unit cover                      | add 2 tests                  |
| `backend/tests/test_recommend.py`         | hot-path cover                        | add 2 tests                  |
| `backend/tests/test_harness_fidelity.py`  | the harness must see what it measures | add 1 test + docstring       |
| `ROADMAP.md`, `docs/owner-manual-todo.md` | the corrected record                  | modify                       |

---

### Task 1: `value_over_replacement` — the un-floored MLV, in one place

**Files:**

- Modify: `backend/src/jaaffl/engine/optimize.py` (insert after `marginal_lineup_value`, line 253)
- Test: `backend/tests/test_optimize.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_optimize.py`:

Add `value_over_replacement` to the existing `jaaffl.engine.optimize` import block at the top of
`backend/tests/test_optimize.py` (it already imports `pytest`, `Position`, `expand_starting_slots`,
`marginal_lineup_value` and `jaaffl_settings`), then append:

```python
def test_value_over_replacement_is_the_unfloored_mlv() -> None:
    """VOR is what MLV reduces to on an empty roster — this module's own reduction guarantee —
    and it keeps ordering candidates below replacement, where MLV clamps every one of them to
    exactly 0.0. That clamp is what left the engine ranking 180 tied candidates by dict order."""
    slots = expand_starting_slots(jaaffl_settings())
    mu = {"good": 300.0, "weak": 60.0, "weaker": 10.0}
    position = dict.fromkeys(mu, Position.WR)
    baselines = {Position.WR: 100.0}

    # Empty roster: MLV IS VOR for an above-replacement player (the reduction guarantee).
    assert marginal_lineup_value("good", [], mu, position, baselines, slots) == pytest.approx(
        value_over_replacement("good", mu, position, baselines)
    )

    # With the WR slots taken by better players, MLV floors BOTH weak players to exactly 0.0 —
    # and VOR still separates them by 50 points.
    full = ["good"] * 4
    mlvs = {
        pid: marginal_lineup_value(pid, full, mu, position, baselines, slots)
        for pid in ("weak", "weaker")
    }
    assert mlvs["weak"] == mlvs["weaker"] == 0.0
    assert value_over_replacement("weak", mu, position, baselines) == -40.0
    assert value_over_replacement("weaker", mu, position, baselines) == -90.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q -k value_over_replacement`
Expected: FAIL — `ImportError: cannot import name 'value_over_replacement'`

- [ ] **Step 3: Implement** — insert into `backend/src/jaaffl/engine/optimize.py` directly after
      `marginal_lineup_value` (i.e. after line 253, before `def optimize_roster`):

```python
def value_over_replacement(
    player_id: str,
    mu: Mapping[str, float],
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],
) -> float:
    """``μ − replacement`` — the value MLV degenerates to before the lineup floors it at zero.

    **Not a new signal.** This module's reduction guarantee already states
    "empty roster ⇒ MLV_p = μ_p − baseline(pos(p)) (classic VOR)". Once a starting slot is spoken
    for, :func:`marginal_lineup_value` clamps every below-replacement candidate to exactly 0.0 and
    the ordering VOR still carries is discarded — a −38 receiver and a −120 receiver both score 0.

    That discard is the whole of Tier 10's defect. Measured on the real board with
    ``lambda_slot_override`` zeroed, **180 of 180** candidates at round 14 shared the score
    ``0.000000``: MLV is 0, ``κ·max(0, VONA)`` clamps to 0 because ``expected_best_available`` is
    never negative, ``α·cliff_bonus`` is legitimately 0 below replacement, and ``λ`` is 0 for a
    SURPLUS position. Python's sort is stable, so the ranking became ``context.mu`` **insertion
    order** — for 8 of 17 picks. The engine's top recommendation was 81.4 projected points worse
    than the best player it was tied with.

    Used ONLY as a deterministic secondary sort key, by ``recommend`` and ``ScoreAgent`` alike.
    It is a **tiebreak, never a term**: nothing adds it to a score, so no ``ScoreComponents``
    decomposition changes and no comparison where scores already differ can move. It lives here,
    beside the function it un-floors, because this project's signature defect is a rule implemented
    twice — ``engine/risk.py`` exists for exactly that reason.
    """
    return mu[player_id] - baselines.get(position[player_id], 0.0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_optimize.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/engine/optimize.py backend/tests/test_optimize.py
git commit -m "feat(engine): value_over_replacement — the value MLV floors away below replacement"
```

---

### Task 2: `ScoreAgent` ranks by VOR when the score cannot separate two players

**Files:**

- Modify: `backend/src/jaaffl/engine/simulate.py:206-207` (`_vbd` delegates), `:412` (candidate
  cap), `:455-466` (final pick)
- Test: `backend/tests/test_simulate.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_simulate.py`:

Add this import line to `backend/tests/test_simulate.py` (it already imports `EngineParams`,
`Position`, `SimContext`, `ScoreAgent` and defines `_settings()`):

```python
from jaaffl.engine.optimize import expand_starting_slots, roster_capacity
```

then append:

```python
# The starting nine, all far ABOVE the 150.0 replacement line.
_TIED_ROSTER = ["qb0", "rb0", "wr0", "wr1", "wr2", "wr3", "te0", "k0", "dst0"]

# lambda_slot_override defaults to {0.4, -0.4}; zeroed here because that is the config under which
# the tie is total (a filled slot makes every position SURPLUS, so the surplus ceiling is the only
# lambda any candidate can get).
_TIED_PARAMS = EngineParams(
    candidate_cap=180,
    lambda_slot_override={"last_startable_slot_floor": 0.0, "surplus_stash_ceiling": 0.0},
)


def _tied_ctx() -> SimContext:
    """A board whose starting nine is filled by players above replacement and whose ENTIRE
    remaining pool sits below it — so `marginal_lineup_value` floors every candidate to exactly
    0.0 and no term in the score can separate any two of them."""
    value = {pid: 300.0 - 10.0 * i for i, pid in enumerate(_TIED_ROSTER)}
    value.update({f"wr{i}": 140.0 - 3.0 * i for i in range(4, 14)})
    value.update({f"rb{i}": 130.0 - 4.0 * i for i in range(1, 11)})
    value.update({f"te{i}": 120.0 - 5.0 * i for i in range(1, 6)})
    position = {pid: Position(pid.rstrip("0123456789").upper()) for pid in value}
    settings = _settings()
    return SimContext(
        value=value,
        position=position,
        baselines=dict.fromkeys(Position, 150.0),
        slots=expand_starting_slots(settings),
        roster_size=17,
        # Deliberately NOT correlated with value, so a sigma-driven tiebreak cannot pass by luck.
        sigma={pid: 20.0 + 3.0 * ((i * 7) % 11) for i, pid in enumerate(sorted(value))},
        roster_capacity=roster_capacity(settings),
    )


def test_score_agent_pick_does_not_depend_on_pool_order() -> None:
    """The defect Tier 10 found: once the starting nine is full every candidate scores EXACTLY
    0.0, `min()` returns the first of the tied set, and the pick became a function of the order
    the pool arrived in. Measured on the real board, 45.8% of our picks moved when the identical
    pool was merely reversed."""
    ctx = _tied_ctx()
    agent = ScoreAgent(_TIED_PARAMS)
    pool = sorted(set(ctx.value) - set(_TIED_ROSTER))
    assert agent.pick(pool, _TIED_ROSTER, ctx) == agent.pick(pool[::-1], _TIED_ROSTER, ctx)


def test_score_agent_breaks_exact_ties_toward_value_over_replacement() -> None:
    """Order-independence alone would be satisfied by any arbitrary-but-stable key — sorting on
    player id would pass it while leaving the pick valueless. The pick must go to the player the
    board actually rates highest."""
    ctx = _tied_ctx()
    pool = sorted(set(ctx.value) - set(_TIED_ROSTER))
    best = max(pool, key=lambda p: ctx.value[p] - ctx.baselines[ctx.position[p]])
    assert ScoreAgent(_TIED_PARAMS).pick(pool, _TIED_ROSTER, ctx) == best
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate.py -q -k "pool_order or exact_ties"`
Expected: FAIL — the two picks differ, and the chosen player is not the best-VOR one.

- [ ] **Step 3: Implement** — three edits in `backend/src/jaaffl/engine/simulate.py`.

Add to the `jaaffl.engine.optimize` import block at the top:

```python
from jaaffl.engine.optimize import (
    StartingSlot,
    lineup_value,
    marginal_lineup_value,
    value_over_replacement,
)
```

Replace `_vbd` (lines 206-207) so the rule exists once:

```python
def _vbd(pid: str, ctx: SimContext) -> float:
    """Value over replacement, from the shared rule — the behavioural agents' whole ranking."""
    return value_over_replacement(pid, ctx.value, ctx.position, ctx.baselines)
```

In `ScoreAgent.pick`, replace the candidate-cap line (412):

```python
        # VOR on the SAME `value` mapping MLV was computed from (reliability-shrunk), so the
        # tiebreak and the term it breaks ties for agree about what a player is worth.
        vor = {p: value_over_replacement(p, value, ctx.position, ctx.baselines) for p in available}
        # Cap by MLV, as recommend.py does — ties broken by VOR, then by id so the cut is a
        # decision rather than dict order. Once the starting nine is full EVERY below-replacement
        # candidate has MLV exactly 0.0, so on the real board this cap was selecting 180 of 425
        # players by insertion order, and a player never scored can never be picked.
        candidates = sorted(available, key=lambda p: (-all_mlv[p], -vor[p], p))[: self._cap]
```

and replace the final `return min(...)` (lines 455-466):

```python
        # Ranked exactly as recommend.py ranks: non-punted first, then score descending, then the
        # value the score floored away, then id. The last two are Tier 10: with a full starting
        # nine every remaining score is exactly 0.0, so without them `min` returns whichever tied
        # player the pool happened to list first.
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
                -vor[pid],
                pid,
            ),
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Prove the tests can fail (mutation)**

Delete `-vor[pid],` from the `min` key, re-run
`cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_simulate.py -q -k exact_ties`
Expected: **FAIL**. Restore the line and confirm PASS. Tier 9's review found both of its new
behaviours invisible to the suite; do not skip this.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/simulate.py backend/tests/test_simulate.py
git commit -m "fix(simulate): ScoreAgent breaks score ties by value, not by pool order"
```

---

### Task 3: `recommend()` — the same two fixes on the live hot path

**Files:**

- Modify: `backend/src/jaaffl/engine/recommend.py:277` (candidate cap), `:350` (final rank)
- Test: `backend/tests/test_recommend.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_recommend.py`:

Add `import dataclasses` to the top of `backend/tests/test_recommend.py`, then append:

```python
def _full_lineup() -> tuple[list[DraftPick], "EngineParams"]:
    """A pick log filling OUR nine starting slots, and the params under which the remaining
    below-replacement candidates all score exactly 0.0 (a filled slot makes every position
    SURPLUS, so the surplus ceiling is the only lambda any candidate can receive)."""
    mine = ["qb0", "rb0", "wr0", "wr1", "wr2", "wr3", "te0", "k0", "dst0"]
    picks = [
        DraftPick(overall=i + 1, round=i + 1, pick_in_round=1, team_id="t0", player_id=pid)
        for i, pid in enumerate(mine)
    ]
    params = engine_params(
        lambda_slot_override={"last_startable_slot_floor": 0.0, "surplus_stash_ceiling": 0.0}
    )
    return picks, params


def test_ranking_does_not_depend_on_context_insertion_order() -> None:
    """Tier 10: with the starting nine full, MLV is 0, kappa*max(0,VONA) clamps to 0, the cliff is
    0 below replacement and lambda is 0 for a SURPLUS position — every below-replacement candidate
    scores EXACTLY 0.0. `picks.sort` is stable, so the ranking WAS `context.mu` insertion order.
    Measured on the real board: 180 of 180 candidates tied at round 14, and the engine's #1 was
    81.4 projected points worse than the best player it tied with.

    Only `mu`'s insertion order is varied — not the specs — so nothing else can explain a diff.
    """
    picks, params = _full_lineup()
    context = make_context(_board(), params=params)
    flipped = dataclasses.replace(context, mu=dict(reversed(list(context.mu.items()))))
    state = draft_state(len(picks) + 1, picks=picks)
    forward = recommend(state, context, params)
    backward = recommend(state, flipped, params)
    assert [p.player_id for p in forward.ranked] == [p.player_id for p in backward.ranked]


def test_tied_scores_rank_by_value_over_replacement() -> None:
    """Order-independence alone would be satisfied by sorting on player id — arbitrary but stable.
    Within the block the score cannot separate, the engine must prefer the player the board rates
    higher."""
    picks, params = _full_lineup()
    context = make_context(_board(), params=params)
    rec = recommend(state := draft_state(len(picks) + 1, picks=picks), context, params)
    assert state.current_overall_pick == 10
    zero = [p for p in rec.ranked if p.score == pytest.approx(0.0, abs=1e-9)]
    assert len(zero) > 1, "fixture no longer produces a tie — the test would prove nothing"
    vor = [p.projected_points - p.components.replacement_baseline for p in zero]
    assert vor == sorted(vor, reverse=True)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_recommend.py -q -k "insertion_order or value_over_replacement"`
Expected: FAIL — the two rankings differ, and the tied block is not VOR-ordered.

- [ ] **Step 3: Implement** — two edits in `backend/src/jaaffl/engine/recommend.py`.

Add `value_over_replacement` to the `jaaffl.engine.optimize` import:

```python
from jaaffl.engine.optimize import lineup_value, marginal_lineup_value, value_over_replacement
```

Replace the candidate line (277):

```python
    # 5) Candidate pool: top-K available by MLV (bounded hot path), ties broken by the value MLV
    # floors away and then by id — never by dict order. Once every starting slot is filled, EVERY
    # below-replacement candidate has MLV exactly 0.0, so on the real board this cap was choosing
    # 180 of 425 players by `context.mu` insertion order (Tier 10).
    vor = {
        pid: value_over_replacement(pid, context.mu, context.position, baselines)
        for pid in available
    }
    candidates = sorted(available, key=lambda p: (-mlv[p], -vor[p], p))[: params.candidate_cap]
```

Replace the ranking line (350):

```python
    # Non-punted first, then score desc, then the value the score floored away, then id. The last
    # two are Tier 10: with a full starting nine every remaining score is EXACTLY 0.0 and
    # `list.sort` is stable, so the ranking degenerated to `context.mu` insertion order for 8 of
    # 17 picks. Measured on the real board, the #1 recommendation was 81.4 projected points worse
    # than the best player it was tied with. This RE-RANKS and never changes a score, exactly as
    # the punt guard does, so every `ScoreComponents` decomposition is unchanged.
    picks.sort(
        key=lambda item: (item[0], -item[1].score, -vor[item[1].player_id], item[1].player_id)
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_recommend.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Prove the tests can fail (mutation)**

Change the sort key back to `(item[0], -item[1].score)` and re-run
`cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_recommend.py -q -k "insertion_order or value_over_replacement"`
Expected: **FAIL** on both. Restore and confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/recommend.py backend/tests/test_recommend.py
git commit -m "fix(engine): the live ranking breaks score ties by value, not by dict order"
```

---

### Task 4: the latency budget still holds

The hot path gained one dict comprehension over `available` (≤581 entries) and two extra key
components. `test_engine_latency` holds `recommend()` to p95 < 200 ms and is the guard.

**Files:** none modified.

- [ ] **Step 1: Run the latency test**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_engine_latency.py -q`
Expected: PASS. If it fails, hoist `vor` construction to reuse the `mlv` comprehension's single
pass over `available` rather than loosening the budget.

---

### Task 5: the harness must measure a decision, not an ordering

**Files:**

- Modify: `backend/tests/test_harness_fidelity.py` (add one test + a docstring bullet)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_harness_fidelity.py`:

```python
class _ReversedPool:
    """The SHIPPED agent, handed the same pool in the opposite order. No scoring logic here."""

    def __init__(self, inner: ScoreAgent) -> None:
        self._inner = inner

    def pick(self, available, my_roster, ctx, rng=None) -> str:
        return self._inner.pick(list(available)[::-1], my_roster, ctx, rng)


def test_the_harness_measures_a_decision_not_an_ordering() -> None:
    """Every knob above can be measurable and the measurement still be worthless if the PICK is
    decided by the order the pool arrives in. Measured on the real board 2026-08-09, presenting
    the identical pool reversed moved 23.5% of our picks under the committed config and 45.8%
    with `lambda_slot_override` zeroed — because once the starting nine is full every candidate
    scores exactly 0.0 and `min()` returns whichever one came first."""
    base = committed_engine_params()
    ctx = demo_sim_context()
    forward, reverse = [], []
    for slot in range(TEAMS):
        for seed in SEEDS:
            for bucket, agent in (
                (forward, ScoreAgent(base)),
                (reverse, _ReversedPool(ScoreAgent(base))),
            ):
                bucket.append(
                    tuple(
                        simulate_draft(
                            ctx,
                            our_slot=slot,
                            our_agent=agent,
                            opponents=[NeedBasedAgent(), AdpNoiseAgent()],
                            seed=seed,
                            teams=TEAMS,
                        )[slot]
                    )
                )
    moved = sum(1 for a, b in zip(forward, reverse, strict=True) if a != b)
    assert moved == 0, (
        f"{moved} of {len(forward)} simulated rosters change when the pool is merely REVERSED — "
        "the agent is ranking by list order, so every number measured from it is an artifact"
    )
```

- [ ] **Step 2: Extend the module docstring** — append to the bullet list at the top of
      `backend/tests/test_harness_fidelity.py`:

```
* **Tier 10** — the OBJECTIVE, and the ranking underneath it. ``mean_lineup_value_objective``
  scores the optimal nine under fixed ``mu``, so it prices a bench player at exactly **0** — 8 of
  this league's 17 picks. It therefore could not see that once the starting nine is full EVERY
  remaining candidate scores exactly ``0.0`` (MLV 0, ``kappa*max(0,VONA)`` clamped, cliff 0 below
  replacement, ``lambda`` 0 for a SURPLUS position) and the ranking degenerates to ``context.mu``
  insertion order. Measured on the real board: **180 of 180** candidates tied at round 14 and the
  #1 recommendation was **81.4** projected points worse than the best player it tied with. Under
  ``override_off`` that objective reported the engine as the BEST points-scorer in the field while
  it drafted half its roster alphabetically.
```

- [ ] **Step 3: Run to verify it fails on the pre-fix code**

If Tasks 2 and 3 are already committed this test passes immediately, which proves nothing. Verify it
can fail:

```bash
git stash push backend/src/jaaffl/engine/simulate.py
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_harness_fidelity.py -q -k decision_not_an_ordering
```

Expected: **FAIL**, naming a non-zero count of moved rosters. Then:

```bash
git stash pop
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_harness_fidelity.py -q
```

Expected: PASS (7 tests — 6 pre-existing + 1 new).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_harness_fidelity.py
git commit -m "test(harness): a simulated pick must not depend on the order the pool arrives in"
```

---

### Task 6: re-measure through the SHIPPED path, not the probe

Every number in "Why this shape" for the `vbd_order` arms came from a **probe** that reordered the
pool rather than from the implementation. If the two disagree, the plan measured something the fix
does not do. This is the one task that can invalidate the tier.

**Files:** none modified — this task produces the numbers Task 7 records.

- [ ] **Step 1: The probe-vs-implementation identity check (the one that can invalidate the tier)**

Re-run the exact measurement that produced the arms table, with the probe's `Ordered(...)` wrapper
**removed** — a plain `ScoreAgent(override_off_params)`, because the tiebreak now lives in the
agent. Same context, same 1001+ blocks, same field `[SoftmaxVbd, NeedBased]`, same 800 draws, so the
numbers are directly comparable.

Expected: the shipped `override_off` arm reproduces the probe's `override_off+vbd_order` figure —
**0.1161 win / 1716.7 points** — rather than the pre-fix 0.0683 / 1713.5.

**If it does not reproduce within the measured per-slot noise (median 0.0100 on the win leg), STOP.**
The probe and the implementation differ, which means the plan measured something the fix does not
do, and the conclusion does not hold. Diagnose before writing any doc.

- [ ] **Step 2: Cross-field replication through the repo's own CLIs**

Both use a **different** opponent field (`[NeedBased, AdpNoise]`), so these are replications under
different opponents, **not** reproductions of the numbers above — do not quote them against each
other. Redirect and poll; piping to `tail` buffers and shows nothing until exit. Do NOT run two
`--real` jobs concurrently: they contend on the shared `app.sqlite` crosswalk. Budget 20–40 min each.

```bash
.venv/Scripts/python.exe scripts/measure_risk_term.py --real --eval-seeds 8 --replicates 5 --draws 800 --out risk_t10.json > risk_t10.txt 2>&1
```

Expected: exit 0, and the `override_off` arm clearly above Tier 8's 0.0866 figure for that field.

```bash
.venv/Scripts/python.exe scripts/run_tournament.py --real --seeds 8 --replicates 5 --draws 800 --pool-cap 300 > e6_real_t10.txt 2>&1
```

Expected: exit 0. `ours` is the **committed** config, which the coupling result says the tiebreak
barely moves, so expect ≈ **0.0071 / 1450** — near the pre-fix 0.0072 / 1459.9, NOT a jump. A large
jump here would contradict the coupling finding and needs explaining before Task 7.

- [ ] **Step 3: Record every output** for Task 7. Do not commit the raw `.txt` / `.json` files;
      they are working artifacts.

---

### Task 7: the corrected record

**Files:**

- Modify: `ROADMAP.md` (insert a Tier 10 status block immediately after the `Legend:` line, before
  the Tier 9 heading at line 16)
- Modify: `docs/owner-manual-todo.md` (§1 — re-state the still-OPEN `lambda_slot_override` decision
  with the coupling evidence; §1b — record that the late-round ranking was arbitrary, not merely
  risk-tilted)

- [ ] **Step 1: Write the ROADMAP Tier 10 status block**

Use these exact section headings, in this order, in the established voice:

```markdown
## 📍 Status — 2026-08-09 · Tier 10 (the engine drafted half its roster in dictionary order)

### The residual reproduces, digit for digit

### 🔴 THE FINDING — three terms vanish on the same candidates, and the sort key is dict order

### Two ordering decisions, not one

### Where the gap lives — the field is innocent, and our starting nine was already better

### The fix, measured — and the refuting control came out the right way

### ⚠️ The code fix and the config change are COUPLED

### The instrument, again — instance six, and this time it is the objective

### ⚠️ Surfaced, not fixed: the two objectives still bracket bench value

### What Tier 10 did NOT do

### ⚠️ What is superseded
```

Content requirements, each of which has a measured number in this plan to carry over:

- **The residual reproduces**: the four Tier 9 rows in the pairwise table (−0.0383 / +51.9 and
  −0.0994 / −201.8).
- **THE FINDING**: the four-term table, the 180-of-180 hot-path evidence with
  `survival_basis=my_slot` and the 81.4-point gap, and the order-sensitivity table (23.5% / 45.8% /
  0.0%).
- **Two ordering decisions**: the `candidate_cap` cut (180 of 425 by dict order) and the final rank.
- **Where the gap lives**: the decomposition table — `E[field max]` flat at 2130.6–2137.6, slots
  filled 9.00 vs 8.81, and that the winning arm has the LOWER realized sd, so it is not variance.
- **The fix, measured**: the arms table and the pairwise table, stating explicitly that vs
  `vbd_only` the result is **beats on points (p = 0.0002), statistical tie on championship
  probability (+0.0095, p = 0.1167)** — never "beats on both".
- **Coupled**: `ours+vbd_order` 0.0071 vs ours 0.0072 (p = 0.5508) and −9.8 points (p = 0.0007).
- **Instance six**: `mean_lineup_value_objective` prices a bench player at 0, moves +3.1 where the
  championship leg moves +0.0478, and reported the engine as the best points-scorer in the field
  while it drafted half its roster alphabetically.
- **What Tier 10 did NOT do**: no week axis; the objective bracketing surfaced not fixed; E2 not
  re-run; `config/engine.json` and `config/league.json` untouched and the Tier 8/9 recommendation
  still OPEN; the engine is level with `vbd_only` on championship probability, not ahead of it; and
  a simulator is not a fact about drafting.
- **Superseded**: Tier 9's "the residual is unexplained" — it is explained. Tier 9's `override_off`
  figures still stand as the pre-fix measurement and are correctly labelled as such.

Substitute the Task 6 numbers wherever a probe number appears. If Task 6 did not run, the arms table
is deleted rather than guessed.

- [ ] **Step 2: Update `docs/owner-manual-todo.md` §1**

The `lambda_slot_override` decision is **still OPEN** — verified 2026-08-09, `config/engine.json`
still reads `0.4 / −0.4`. Re-state it with the new evidence, and add the coupling in plain language:
zeroing it used to leave the late-round ranking arbitrary, and the code now fixed that, so the two
belong together and the setting-off engine now **beats** a plain best-available draft on both
measures for the first time.

- [ ] **Step 3: Run prettier on every edited markdown file and COMMIT the result**

Tier 8's CI failed because a prettier fix was left staged out of its commit while local `pnpm lint`
passed against the already-fixed working tree.

```bash
pnpm exec prettier --write ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans/2026-08-09-tier10-dictionary-order-tiebreak.md
```

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans
git commit -m "docs: Tier 10 — the engine ranked 180 tied candidates by dictionary order"
```

---

### Task 8: verification, review, PR

- [ ] **Step 1: Run every gate CI runs**

```bash
.venv/Scripts/python.exe -m pytest backend -q
```

Expected: all pass (645 passed + 6 new, 2 skipped).

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff check . && ../.venv/Scripts/python.exe -m ruff format --check .
```

Expected: `All checks passed!` and `N files already formatted`.

```bash
pnpm -r typecheck && pnpm -r test && pnpm lint
```

Expected: all pass.

```bash
.venv/Scripts/python.exe scripts/export_schemas.py && git diff --exit-code packages/shared/schemas
```

Expected: exit 0, no diff — no contract changed.

```bash
node scripts/gen-overlay-tokens.mjs --check
```

Expected: exit 0.

```bash
.venv/Scripts/python.exe scripts/preflight.py
```

Expected: exit 0, 581 players, all 6 startable positions fillable.

- [ ] **Step 2: Drive the real FastAPI surface**

Use the project `verify` skill (`.claude/skills/verify`). `backend/src/jaaffl` changed
behaviourally on the hot path this time, so this is a real check, not a regression sweep: confirm
`GET /recommendation` still returns a ranked list whose every `score` reconstructs exactly from its
`ScoreComponents`.

- [ ] **Step 3: Request code review**

Use `superpowers:requesting-code-review`. It caught two real holes in Tier 9; act on what it finds.

- [ ] **Step 4: Push, open the PR, wait for all 4 checks, squash-merge**

```bash
git push -u origin tier10/dictionary-order-tiebreak
```

PR body carries: the 180-of-180 hot-path evidence, the decomposition, the arms table with the
`sig_order` control, the coupling finding, the Task 6 shipped-path reproduction, and the explicit
statement that `config/engine.json` was not touched and the Tier 8/9 recommendation is still the
owner's to make.

Wait for **Backend**, **Node 22**, **Node 24** and **Playwright**, then squash-merge, delete the
branch, and `git checkout main && git pull`.

---

## The config change this tier recommends — proposed, NOT applied

`config/engine.json` is owner-adopted. Verified 2026-08-09: it still reads `0.4 / −0.4`, so **Tier
8's and Tier 9's recommendation is still OPEN and unacted-on.** Tier 10 does not apply it and adds
one new fact about it.

```diff
   "lambda_slot_override": {
-    "last_startable_slot_floor": 0.4,
-    "surplus_stash_ceiling": -0.4
+    "last_startable_slot_floor": 0.0,
+    "surplus_stash_ceiling": 0.0
   },
```

**What is new in Tier 10: the config change and the code fix are coupled.**

| arm, **real** board                | win prob | points |
| ---------------------------------- | -------- | ------ |
| ours (committed), pre-fix          | 0.0072   | 1459.9 |
| ours (committed), **with the fix** | 0.0071   | 1450.1 |
| `override_off`, pre-fix            | 0.0683   | 1713.5 |
| `override_off`, **with the fix**   | 0.1161   | 1716.7 |
| `vbd_only` (the bar)               | 0.1066   | 1661.7 |

The tiebreak is worth **nothing** while `lambda_slot_override` is live (0.0071 vs 0.0072, p = 0.5508
on the championship leg) because `λ = ±0.4` already breaks the ties by σ. It is worth **+0.0478**
(p = 0.0002, non-negative at every slot) once the setting is zeroed.

Only the two together get the engine level with `vbd_only`:

| comparison vs `vbd_only`, **real** board | championship probability | expected points        |
| ---------------------------------------- | ------------------------ | ---------------------- |
| ours as shipped today                    | −0.0994 (p = 1.0000)     | −201.8 (p = 1.0000)    |
| `override_off` alone (Tier 9)            | −0.0383 (p = 0.9998)     | +51.9 (p = 0.0005)     |
| **`override_off` + the Tier 10 fix**     | **+0.0095 (p = 0.1167)** | **+55.0 (p = 0.0002)** |

Read the last row carefully. The engine **beats** plain best-available on points and is **level**
with it on championship probability — ahead by a point estimate that is not significant. That is a
statistical tie, not a win, and it must not be written up as a win. What it is: the first time the
engine has not been _behind_ the naive baseline, and the first time it sits above a 12-team fair
share (0.1161 vs 0.0833).

A simulator is not a fact about drafting: the opponents are behavioural agents, not the eleven
people in the room.
