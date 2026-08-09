# Tier 11: the measuring stick is distorted, and it has no week axis — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two things, in this order. **(A)** The calibration harness applies
`reliability_shrinkage` **twice** on the `--real` path, so every real-board number in this project
was produced by an agent whose K/DST μ is compressed `0.4² = 0.16` instead of `0.4`. Restore the one
invariant that makes the harness a measurement of the shipped engine: `ScoreAgent`'s effective value
must equal `recommend()`'s `context.mu` for the same `EngineParams`. **(B)** The objective has no
week axis, so it prices a bench player between "exactly 0" and "perfect hindsight" and cannot see
`bye_stack`, `handcuff_synergy` or `sos` at all. Add a weekly, correlated, absence-aware objective —
then report, with measurements, which of those three the harness can now actually SEE.

**Architecture:** (A) `SimContext.value` becomes the **pre-shrinkage** μ (which is what the fixture
pool has always carried), so `ScoreAgent` applies R1 exactly once with the params under test. A new
`PlayerProjection.mu_raw` carries it exactly, rather than inverting the transform. (B) A new
`engine/weekly.py` builds `WeeklyOutcomes` — 18 real weeks, real byes, a measured per-position
zero-production process, and a measured same-team correlation applied by per-team Cholesky — plus an
**ex-ante** weekly lineup rule (starters chosen before the week is played, so there is no hindsight
anywhere). Both new objectives are **added alongside** the two Tier 10 reported, never swapped for
them, so every number stays comparable.

**Tech Stack:** Python 3.12, pytest, numpy, scipy. Five engine/calibrate modules and six test
modules. No contract or schema change (`PlayerProjection` is not schema-exported — verified), no new
coefficient in `config/engine.json`, no edit to `config/engine.json` or `config/league.json`.

---

## Why this shape (measured 2026-08-09; every number labelled with its pool)

### The control: Tier 10's real-board headline reproduces digit for digit

Cached real board (581 players capped to 300), 5 disjoint blocks × 8 seeds × 12 slots, 800 sampled
seasons, field `[SoftmaxVbd, NeedBased]` — the Tier 10 design, replayed on shipped code:

| arm                        | Tier 10 published | Tier 11 reproduction |
| -------------------------- | ----------------- | -------------------- |
| `override_off`+fix, win    | 0.1161            | **0.1161**           |
| `override_off`+fix, points | 1716.7            | **1716.7**           |
| `vbd_only`, win            | 0.1066            | **0.1066**           |
| `vbd_only`, points         | 1661.7            | **1661.7**           |
| ours (committed)+fix, win  | 0.0071            | **0.0071**           |
| ours (committed)+fix, pts  | 1450.1            | **1450.1**           |

and the gates: `+fix vs vbd_only` win **+0.0095 (p = 0.1167)**, points **+55.0 (p = 0.0002)** —
Tier 10's exact figures. Everything below rests on this control.

### 🔴 TASK A — the harness shrinks μ twice, and the fixture structurally cannot see it

Traced, then confirmed four ways on the real board.

The chain (all four links read directly):

1. `engine/projections.py:123` — `mu = baseline + reliability * (adj - baseline)`. R1 is applied
   **here**, at precompute, into `PlayerProjection.mu`.
2. `engine/context.py:112` — `mu = {pid: proj.mu ...}`, so `DraftContext.mu` is already shrunk.
   `recommend()` scores **this** and never shrinks again.
3. `calibrate/tune.py:44` — `value=dict(dc.mu)`, so `SimContext.value` is already shrunk.
4. `engine/simulate.py:383` — `ScoreAgent._effective_value` shrinks it **again**.

| check                                                | result                                                            |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| median VOR, live `ctx.value` vs harness `_effective_value` | DST 2.50× · K 2.50× · QB/RB/TE/WR 1.00×                     |
| `max ¦eff − (b + r·r_pre·(raw − b))¦` over 300 players | **1.4e−14** — the double application is an exact identity        |
| baselines recomputed from un-shrunk μ vs `dc.baselines` | **identical to 4 dp at every position** (the shrink is a fixed point of the replacement rank) |
| the fixture (`demo_sim_context`)                     | `value` is RAW, so `_effective_value` shrinks it **once** — correct |

**2.50 is exactly `1 / 0.4`.** The effective compression on the real path is `0.4² = 0.16`.

⚠️ **Sharpen the Tier 10 note, because the ratio alone does not diagnose anything.** The same 2.50×
appears on the fixture pool — where it is *correct*, being the signature of shrinking raw μ once. The
diagnostic is not the ratio, it is the **question of what `SimContext.value` already contains**:
raw on the fixture, shrunk on the real board. That is why no test can see this — there is no
`recommend()` on the fixture path to disagree with.

**Three channels are wrong, not one**, and the plan measures each separately rather than reporting
their sum:

1. **our decisions** — `ScoreAgent` scores μ shrunk twice; `recommend()` scores it shrunk once;
2. **the opponents** — `VbdOnlyAgent` / `NeedBasedAgent` / `SoftmaxVbdAgent` all rank by
   `value_over_replacement(pid, ctx.value, …)`, so on the real board every simulated *opponent*
   ranks K and DST through **our** engine's risk adjustment;
3. **the objective** — `optimal_lineup_value` and `sample_season_outcomes` both read `ctx.value`, so
   the objective scores shrunk μ. `ScoreAgent`'s own docstring states the intended contract: "our
   DECISIONS defer high-variance positions while the OBJECTIVE scores raw μ — a real E2 tuning
   lever." On the real board that contract does not hold.

**And E2's search range is silently mis-scaled.** `run_study` samples `reliability_k`/`reliability_dst`
over `[0.1, 1.0]`, but precompute has already baked in the *committed* 0.4, so the effective factor
the agent uses spans `[0.04, 0.40]` and **can never reach 1.0** (no shrinkage). Every E2 study run on
`--real` searched a range it does not have.

### Measurability first — does correcting it move a pick?

`tests/test_calibrate_pools.py::test_reliability_shrinkage_is_subsumed_by_the_punt_guard` measured
(Tier 8, **fixture**) that driving shrinkage 0.4 → 0.1 moves **0 of 60** rosters, because the punt
guard demotes K/DST absolutely until their stream round. If that also held on the real board this
fix would be invisible and the tier would have to say so. It does not:

Real board, 12 slots × 5 seeds = 60 simulated rosters, corrected context vs current:

| opponent field             | ours (committed)       | `override_off`         |
| -------------------------- | ---------------------- | ---------------------- |
| `[SoftmaxVbd, NeedBased]` (E6) | **60/60** rosters, 377 picks | **60/60** rosters, 421 picks |
| `[NeedBased, AdpNoise]` (fidelity) | **0/60**, 0 picks | **5/60**, 25 picks   |

⚠️ **Do not quote the 60/60 as the size of the effect.** `SoftmaxVbdAgent` is stochastic and draws
from `rng.choice`, so the moment the candidate weights change at all the rng stream diverges and
every later pick differs — that field measures "something changed", not "how much". The clean
instrument is the deterministic-ish `[NeedBased, AdpNoise]` field: **0/60 under the committed config,
5/60 with `lambda_slot_override` zeroed.** The committed 0/60 replicates the Tier 8 finding exactly —
with the override live, `λ = ±0.4` and the punt guard together decide K/DST regardless of μ.

**So Task A's honest headline is a correctness fix whose decision-side effect is small and
config-coupled, and whose objective-side effect is not small at all** — the objective's K/DST μ moves
by 2.5× its distance from replacement, and that is what re-prices every real-board number.

### 🔴 TASK B — what the objective cannot see, and three measurements that decide it

`sample_season_outcomes` draws **one independent season total per player**. Consequences, all still
true at `0e27baa`: `mean_lineup_value_objective` prices a bench player at exactly 0 (8 of 17 picks);
`roster_season_values` re-optimises the lineup with **perfect hindsight** of the realized season;
they bracket bench value and neither is right; and `recommend._positional_modifiers` has declared
`bye_stack`, `handcuff_synergy` and `sos` for six tiers with nothing able to price them.

Three measurements from the free nflverse `ff_opportunity` frame the projections already use,
weekly rows scored under the owner-verified JAAFFL map, **seasons 2023 + 2024 + 2025** so nothing
rests on one year. A player's series runs over every week his team played inside his own
[first seen, last seen] window; **a week with no row scores 0.0**, which is what a fantasy lineup
records.

**1 — the same-team correlation table (pooled; per-season in the last column):**

| pair    | ρ          | se     | n      | 2023 / 2024 / 2025     |
| ------- | ---------- | ------ | ------ | ---------------------- |
| QB×WR   | **+0.1793** | 0.0117 | 8996  | +0.153 / +0.197 / +0.194 |
| QB×TE   | **+0.1496** | 0.0151 | 4795  | +0.141 / +0.132 / +0.176 |
| QB×QB   | **−0.2825** | 0.0442 | 507   | −0.082 / −0.391 / −0.439 |
| QB×RB   | +0.0277    | 0.0134 | 5808  | +0.054 / +0.021 / +0.004 |
| RB×TE   | +0.0176    | 0.0096 | 10820 | +0.040 / +0.012 / +0.001 |
| RB×RB   | −0.0211    | 0.0156 | 4706  | −0.027 / −0.037 / +0.005 |
| RB×WR   | −0.0104    | 0.0069 | 20328 | −0.020 / −0.003 / −0.007 |
| WR×WR   | −0.0092    | 0.0088 | 12884 | −0.005 / −0.007 / −0.017 |
| TE×TE   | −0.0075    | 0.0180 | 3000  | −0.011 / −0.018 / +0.005 |
| TE×WR   | +0.0019    | 0.0075 | 16740 | −0.001 / +0.003 / +0.003 |
| **control: DIFFERENT team, same week** | **+0.0008** | 0.0076 | 17266 | — |

The control lands on zero, which is what says the decomposition is sound rather than picking up a
league-wide week effect. **The entire same-team structure is the quarterback** — QB×(WR¦TE) ≈ +0.17,
QB×QB ≈ −0.28, and every pair not involving a QB is inside ±0.03. A single "team factor" would be
wrong: it would give WR×WR the same +0.17 the data says is −0.009.

**2 — the zero-production (absence) process, pooled over the three seasons:**

| position | p(zero-production week) | player-weeks |
| -------- | ----------------------- | ------------ |
| QB       | 0.1727                  | 2044         |
| RB       | 0.1731                  | 4599         |
| WR       | 0.2336                  | 7115         |
| TE       | 0.2885                  | 3785         |
| **all**  | **0.2225**              | 17543        |

Call it *zero production*, not *injury*: `ff_opportunity` has a row only where there was opportunity,
so a healthy receiver with no targets counts here. For a lineup the two are the same event.

**3 — the handcuff, sized. This is the measurement that refutes the obvious design.** Top-2 RBs by
season points on each team, 32 pairs per season:

| season | RB2 pts/week, RB1 **present** | RB2 pts/week, RB1 **absent** | jump      |
| ------ | ----------------------------- | ---------------------------- | --------- |
| 2023   | 4.47 (se 0.25, n=456)         | 8.78 (se 0.97, n=38)         | **×1.96** |
| 2024   | 4.67 (se 0.24, n=459)         | 7.50 (se 1.06, n=26)         | **×1.61** |
| 2025   | 5.10 (se 0.25, n=451)         | 12.15 (se 1.60, n=22)        | **×2.38** |

The handcuff mechanism is **real and large**. But it is a **regime** effect, and the *unconditional*
RB×RB correlation is **−0.0211 (se 0.0156, not significant)**. A jointly-Gaussian model calibrated to
ρ = −0.02 implies a conditional lift of `−ρ·φ(c)/Φ(c) ≈ +0.03` sd — essentially nothing. **So adding
weekly correlation, however carefully measured, does NOT make `handcuff_synergy` measurable.** That
verdict is a measurement, not an opinion, and the plan does not build a transfer process on a guess.

### Feasibility, checked before committing to the design

| risk                                                     | measured                                                    |
| -------------------------------------------------------- | ----------------------------------------------------------- |
| is the measured correlation matrix PSD for real rosters?  | 32 multi-player teams, **worst minimum eigenvalue 0.1698**, 0 needing repair |
| does marginal preservation have a solution for everyone?  | **0 of 300** players hit `s² < 0`; production sd is 0.65–1.17× (median 1.07) of `σ/√n` |
| is a vectorised ex-ante weekly lineup affordable?         | **2.53 ms** per roster-scoring at 400 draws × 18 weeks → **≈1 min** for a 4-arm, 5-block tournament |

The board itself supports it: **296 of 300** players carry a real bye (weeks 5–14); all 300 resolve
to one of 32 teams through `team_norm`; 28 teams hold ≥2 RBs and 33 hold ≥2 WRs.

### The design decisions this tier takes deliberately, and surfaces

1. **Championship probability stays "highest season total of the 12".** A week axis makes
   head-to-head expressible for the first time — and `config/league.json` specifies **no** playoff
   bracket and **no** head-to-head schedule. Inventing one would breach the `agent_usage_contract`.
   Declined on purpose, recorded here so a later tier does not think it was overlooked.
2. **The new objectives are ADDED, not swapped.** `win probability` and `mean lineup value` keep
   their exact present definitions so every Tier 9/10 number stays comparable.
3. **Lineups are set EX ANTE** — best legal nine by μ among players available that week, then scored
   on what they realized. No hindsight anywhere. That is a **lower** bound on bench value (a real
   manager also reacts to in-season information), and it is stated as one.
4. **Every player's season marginal is preserved exactly.** `m` and `s` are solved so that
   `E[Σ_w] = μ_p` and `Var[Σ_w] = σ_p²` under the absence process. Correlation changes only the
   joint. So any difference between the weekly objective and the season objective is attributable to
   **structure** (weeks, byes, absence, correlation, ex-ante lineups) and never to a changed marginal.
5. **`σ_week = σ_season / √n` is not an invention.** `league/xep.py:188` already builds σ as
   `pstdev(weekly residuals) × √17`. The weekly decomposition is the inverse of the transform this
   project already ships.

### Honest caveats to carry into the docs

- **A simulator is not a fact about drafting.** The opponents are behavioural agents, not the eleven
  people in the room.
- **The absence process reallocates the board's σ; it does not add to it.** `league/xep.py` measures
  weekly residuals only over weeks a player appeared, so the shipped σ **excludes** missed-game
  variance and is therefore too small. This tier does not change σ — that would supersede everything
  a fifth time — it only gets the *structure* of the existing σ right. Recorded as an open item.
- **K and DST get no correlation and no absence.** `ff_opportunity` covers skill positions only, so
  there is nothing measured to use, and fabricating one is the defect this project keeps finding.
- **`cliff_bonus` stays on the live path's shrunk-μ basis.** It is a `DraftContext` artifact the live
  engine also uses; recomputing it for the harness would put the harness and the engine on different
  cliffs. Disclosed, not changed.
- **`lambda_slot_override` is untouched.** Verified 2026-08-09: `config/engine.json` still reads
  `{last_startable_slot_floor: 0.4, surplus_stash_ceiling: −0.4}`, so the Tier 8/9/10 recommendation
  is **still OPEN with the owner**. Task 12 re-states it with the Tier 10 coupling finding intact.
- **Nothing is written to `config/engine.json` or `config/league.json`.**

---

## File structure

| File                                        | Responsibility                              | Change                              |
| ------------------------------------------- | ------------------------------------------- | ----------------------------------- |
| `backend/src/jaaffl/engine/projections.py`  | the projection blend + R1/R4                | add `PlayerProjection.mu_raw`       |
| `backend/src/jaaffl/calibrate/tune.py`      | DraftContext → SimContext; E2/E6 plumbing   | read `mu_raw`; register 2 objectives |
| `backend/src/jaaffl/engine/weekly.py`       | **NEW** — the weekly correlated outcome model + ex-ante lineup | create      |
| `backend/src/jaaffl/engine/simulate.py`     | E2/E6 agents + season objective             | docstring only (no behaviour change) |
| `backend/tests/test_projections.py`         | projection unit cover                       | add 2 tests                         |
| `backend/tests/test_tune.py`                | harness plumbing cover                      | add 2 tests                         |
| `backend/tests/test_weekly.py`              | **NEW** — the weekly model's own guards     | create                              |
| `backend/tests/test_harness_fidelity.py`    | the harness must see what it measures       | add 2 tests + docstring             |
| `backend/tests/test_calibrate_pools.py`     | pool sensitivity                            | update 1 docstring                  |
| `ROADMAP.md`, `docs/owner-manual-todo.md`   | the corrected record                        | modify                              |

---

## Task 1: `PlayerProjection.mu_raw` — the pre-shrinkage μ, carried not inverted

**Files:**

- Modify: `backend/src/jaaffl/engine/projections.py:49-141`
- Test: `backend/tests/test_projections.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mu_raw_is_the_pre_shrinkage_blend() -> None:
    """`mu` is shrunk toward replacement by R1; `mu_raw` is the same blend BEFORE that shrink.

    The calibration harness needs the un-shrunk value because it re-applies R1 itself with the
    params under test. Inverting `mu` would divide by `reliability`, which a config may set to 0;
    carrying the value is exact and total.
    """
    params = EngineParams.model_validate(
        {"reliability_shrinkage": {"K": 0.4}, "flex_split": {"RB": 8, "WR": 4}}
    )
    proj = assemble_projections(
        {"src": {pid: value for pid, value in _KICKER_POINTS.items()}},
        _KICKER_POSITIONS,
        params,
        _settings(),
        sigma_floor={Position.K: 10.0},
    )
    best = proj["k0"]
    assert best.reliability == pytest.approx(0.4)
    # mu sits 40% of the way from the baseline to mu_raw, by construction.
    baseline = proj["k11"].mu  # the 12th kicker IS the replacement rank for 12 teams x 1 K slot
    assert best.mu == pytest.approx(baseline + 0.4 * (best.mu_raw - baseline))
    assert best.mu_raw > best.mu  # an above-replacement kicker is pulled DOWN by the shrink


def test_mu_raw_equals_mu_when_reliability_is_one() -> None:
    """No shrink -> the two views coincide, so a pool with no shrinkage is bit-identical."""
    params = EngineParams.model_validate({"flex_split": {"RB": 8, "WR": 4}})
    proj = assemble_projections(
        {"src": _WR_POINTS}, _WR_POSITIONS, params, _settings(), sigma_floor={Position.WR: 30.0}
    )
    for p in proj.values():
        assert p.mu == pytest.approx(p.mu_raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_projections.py -k mu_raw -v`
Expected: FAIL — `AttributeError: 'PlayerProjection' object has no attribute 'mu_raw'`

- [ ] **Step 3: Write minimal implementation**

In `backend/src/jaaffl/engine/projections.py`, add the field to the dataclass (after `mu`):

```python
    mu: float  # E[season league points], post-shrinkage/situation
    # μ BEFORE the R1 reliability shrink (and AFTER the R4 situation nudge) — i.e. the blend the
    # shrink is applied TO. Carried rather than inverted because `calibrate` re-applies R1 itself
    # with the params under test, and inverting would divide by `reliability` (which a config may
    # legitimately set to 0). Equal to `mu` wherever `reliability == 1.0`, which is every position
    # but K and DST, so nothing outside the calibration path can observe a difference.
    mu_raw: float
```

and populate it in the per-player loop (the value is already in hand as `adj`):

```python
        out[pid] = PlayerProjection(
            player_id=pid,
            position=pos,
            mu=mu,
            mu_raw=adj,
            sigma=sigma,
            ...
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_projections.py -v`
Expected: PASS. Then `.venv\Scripts\python.exe -m pytest backend -q` — any other construction site
of `PlayerProjection` (`backend/tests/engine_fixtures.py:131`,
`backend/tests/test_scaffold_contracts.py:62`) must be updated to pass `mu_raw`.

- [ ] **Step 5: Prove the test can fail (mutation)**

Copy `projections.py` aside (**do not** `git checkout --` it — that destroys uncommitted work), set
`mu_raw=mu`, and confirm `test_mu_raw_is_the_pre_shrinkage_blend` FAILS while
`test_mu_raw_equals_mu_when_reliability_is_one` still passes (it must — that is the point of having
both). Restore from the copy.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/projections.py backend/tests/test_projections.py backend/tests/engine_fixtures.py backend/tests/test_scaffold_contracts.py
git commit -m "feat(engine): carry the pre-shrinkage mu on PlayerProjection"
```

---

## Task 2: the harness stops shrinking twice — and a test that pins it to `recommend()`

**Files:**

- Modify: `backend/src/jaaffl/calibrate/tune.py:39-58`
- Test: `backend/tests/test_tune.py`

- [ ] **Step 1: Write the failing test**

This is the invariant the whole tier exists for: the agent the harness scores must value a player
exactly as the shipped hot path values him.

```python
def test_score_agent_effective_value_equals_recommend_context_mu() -> None:
    """THE harness-fidelity invariant for value.

    `recommend()` scores `context.mu` — μ with R1 applied ONCE at precompute. `ScoreAgent` applies
    R1 itself, so the context it is handed must carry the PRE-shrinkage μ or the two disagree.
    Before Tier 11 `sim_context_from_draft_context` copied `dc.mu` (already shrunk) into
    `SimContext.value`, so the harness compressed K and DST by 0.4**2 = 0.16 while the live engine
    used 0.4 — a 2.50x distortion measured on the real board, in the objective AND in every
    simulated opponent's VBD.
    """
    dc = _draft_context_with_kickers()          # committed reliability_shrinkage {"K": 0.4}
    ctx = sim_context_from_draft_context(dc)
    effective = ScoreAgent(dc.params)._effective_value(ctx)
    for pid in dc.mu:
        assert effective[pid] == pytest.approx(dc.mu[pid]), pid


def test_sim_context_baselines_are_unmoved_by_using_raw_mu() -> None:
    """The R1 shrink is a FIXED POINT of the replacement baseline (it pulls toward that baseline,
    so the value AT the replacement rank is unchanged, and the within-position order is preserved).
    Measured on the real board 2026-08-09: baselines recomputed from un-shrunk μ match
    `DraftContext.baselines` to 4 dp at all six positions. Pinned here so a future change to
    `replacement_values` that breaks it is caught rather than silently re-scaling every VOR.
    """
    dc = _draft_context_with_kickers()
    ctx = sim_context_from_draft_context(dc)
    recomputed = replacement_values(
        dc.settings,
        dict(ctx.value),                       # the RAW μ the harness now carries
        dc.players,
        flex_split=dc.flex_split,
    )
    for pos, baseline in dc.baselines.items():
        assert recomputed[pos] == pytest.approx(baseline), pos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_tune.py -k "effective_value or baselines_are_unmoved" -v`
Expected: the first FAILS (kicker values differ by a factor of 0.4); the second PASSES already
(it is a property of `replacement_values`, pinned here because Task 2 starts depending on it).

- [ ] **Step 3: Write minimal implementation**

In `backend/src/jaaffl/calibrate/tune.py::sim_context_from_draft_context`, replace
`value=dict(dc.mu)` and expand the docstring:

```python
def sim_context_from_draft_context(dc: DraftContext) -> SimContext:
    """Adapt a precompute :class:`DraftContext` into a :class:`SimContext`, so E2 can tune on REAL
    projections + FFC ADP. σ is read per-player from ``projections``; everything else maps 1:1.

    ``value`` is the **pre-shrinkage** μ (``PlayerProjection.mu_raw``), NOT ``dc.mu``. R1 reliability
    shrinkage is applied at precompute into ``dc.mu``, and :class:`ScoreAgent` applies it AGAIN from
    ``params.reliability_shrinkage`` — so copying ``dc.mu`` here compressed K and DST by ``0.4**2``
    while ``recommend()`` used ``0.4``. Measured on the real board 2026-08-09: median value over
    replacement 2.50x closer to replacement at DST and K (exactly ``1 / 0.4``), 1.00x elsewhere.

    Three things were wrong, not one: our agent's decisions, the OBJECTIVE (``optimal_lineup_value``
    and ``sample_season_outcomes`` both read ``value``), and every behavioural OPPONENT — all three
    rank K/DST through ``value_over_replacement(pid, ctx.value, ...)``. Carrying raw μ restores the
    contract ``ScoreAgent`` already documented: decisions defer high-variance positions, the
    objective scores raw μ, and ``reliability_shrinkage`` is a real E2 lever again (on the real path
    ``run_study``'s ``[0.1, 1.0]`` range was effectively ``[0.04, 0.40]`` and could never reach 1.0).

    ``demo_sim_context`` has always built ``value`` from a raw curve, so the fixture pool was already
    correct and **no test on it could ever have seen this** — which is why it survived to Tier 11.
    """
    sigma = {pid: proj.sigma for pid, proj in dc.projections.items()}
    return SimContext(
        value={pid: proj.mu_raw for pid, proj in dc.projections.items()},
        ...
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_tune.py -v`
Expected: PASS.

- [ ] **Step 5: Prove the test can fail (mutation), component by component**

Copy `tune.py` aside. Then, one at a time:

1. revert to `value=dict(dc.mu)` → `test_score_agent_effective_value_equals_recommend_context_mu`
   must FAIL;
2. set `value={pid: proj.mu_raw * 1.001 ...}` → the same test must FAIL (it is not just checking
   "some transform happened");
3. leave `value` correct but set `sigma={}` → the value test must still PASS, proving it is
   measuring the value channel alone.

Restore from the copy after each.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/calibrate/tune.py backend/tests/test_tune.py
git commit -m "fix(calibrate): stop applying reliability_shrinkage twice on the --real path"
```

---

## Task 3: re-measure Tier 10's headline through the corrected harness

**Files:**

- Create: `scratchpad/` runner only — **no repo file changes in this task**

- [ ] **Step 1: Re-run the Tier 10 design on the corrected harness**

Arms: `override_off`, `vbd_only`, `ours(committed)`. Real board, 5 disjoint blocks × 8 seeds × 12
slots, 800 draws, field `[SoftmaxVbd, NeedBased]`, gated pairwise exactly as E2 gates (one-sided
Wilcoxon across the 12 slots **plus** the noise-aware non-regression leg with `slot_noise` = sd of
the paired difference across blocks).

- [ ] **Step 2: Decompose the three channels**

Re-run with the correction applied to **one channel at a time**, via a context-substituting wrapper
so nothing in the engine changes:

```python
class _WithContext:
    """The SHIPPED agent, handed a different context. No scoring logic here."""

    def __init__(self, inner, ctx):
        self._inner, self._ctx = inner, ctx

    def pick(self, available, my_roster, ctx, rng=None):
        return self._inner.pick(available, my_roster, self._ctx, rng)
```

| arm                | our agent sees | opponents see | objective scores |
| ------------------ | -------------- | ------------- | ---------------- |
| `pre`              | shrunk         | shrunk        | shrunk           |
| `ours_only`        | **raw**        | shrunk        | shrunk           |
| `opponents_only`   | shrunk         | **raw**       | shrunk           |
| `objective_only`   | shrunk         | shrunk        | **raw**          |
| `post` (the fix)   | **raw**        | **raw**       | **raw**          |

- [ ] **Step 3: Record BOTH objectives, both pools, and say plainly whether the headline moved**

Report the corrected `override_off` vs `vbd_only` comparison beside Tier 10's, with p-values,
replicate count and the per-slot noise. If the sign of any Tier 10 verdict changes, say so in the
first sentence of the ROADMAP block, not the fifth.

- [ ] **Step 4: Commit the measurement into the plan document**

No code change; the numbers land in `ROADMAP.md` at Task 11.

---

## Task 4: `engine/weekly.py` — the weekly, correlated, absence-aware outcome model

**Files:**

- Create: `backend/src/jaaffl/engine/weekly.py`
- Test: `backend/tests/test_weekly.py`

- [ ] **Step 1: Write the failing test — the marginal must be preserved exactly**

```python
def test_weekly_totals_reproduce_the_season_marginal() -> None:
    """The whole comparability argument: summing the weekly draws must reproduce each player's
    (mu, sigma) EXACTLY, so any difference between the weekly objective and the season objective is
    attributable to STRUCTURE (weeks, byes, absence, correlation, ex-ante lineups) and never to a
    changed marginal.
    """
    ctx = demo_sim_context()
    model = WeeklyModel.from_context(ctx, bye_week={}, team={})
    outcomes = model.sample(n_draws=40_000, seed=7)
    totals = outcomes.season_totals()          # (n_draws, n_players)
    for pid in ("rb0", "wr10", "k3", "dst2"):
        i = outcomes.index[pid]
        assert totals[:, i].mean() == pytest.approx(ctx.value[pid], rel=0.02)
        assert totals[:, i].std() == pytest.approx(ctx.sigma[pid], rel=0.05)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_weekly.py -k marginal -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jaaffl.engine.weekly'`

- [ ] **Step 3: Write the implementation**

`backend/src/jaaffl/engine/weekly.py`. The measured constants live at module top with their
provenance, exactly as `calibrate/pools.py` documents its sigma anchors:

```python
"""A WEEKLY, correlated, absence-aware season model — the objective's missing axis (Tier 11).

``simulate.sample_season_outcomes`` draws ONE independent season total per player. That has three
consequences the engine has been unable to see for six tiers: a bench player is worth exactly 0 to
``mean_lineup_value_objective`` and an upper bound to ``roster_season_values`` (which re-optimises
the lineup with perfect hindsight); ``bye_stack`` and ``sos`` have no week to attach to; and
``handcuff_synergy`` has no cross-player dependence to attach to.

This module supplies the axis. Every parameter is MEASURED from the same free nflverse
``ff_opportunity`` frame ``league/xep.py`` already reads, over seasons 2023-2025, scored under the
owner-verified JAAFFL map — never chosen by feel.

**Each player's season marginal is preserved exactly.** Given per-week absence probability ``q`` and
``n`` playable weeks::

    m = mu / (n * (1 - q))                      # per-week mean WHEN PRESENT
    s^2 = (sigma^2 / n - q * (1 - q) * m^2) / (1 - q)

gives ``E[sum_w] = mu`` and ``Var[sum_w] = sigma^2``. Correlation changes only the JOINT. Verified on
the real board: 0 of 300 players hit ``s^2 < 0``.

**``sigma_week = sigma_season / sqrt(n)`` is not an invention** — ``league/xep.py`` builds sigma as
``pstdev(weekly residuals) * sqrt(17)``, so this is the inverse of the transform already shipped.

⚠️ **The absence process REALLOCATES the board's sigma, it does not add to it.** ``league/xep.py``
measures residuals only over weeks a player appeared, so the shipped sigma EXCLUDES missed-game
variance and is too small. Fixing that would supersede every number in the project again; this
module only gets the STRUCTURE of the existing sigma right.
"""

# Measured 2026-08-09 from nflverse ff_opportunity, seasons 2023+2024+2025, absence-aware, scored
# under jaaffl_scoring. Pooled rho of standardised weekly residuals for same-team pairs; the
# DIFFERENT-team control came out at +0.0008 (se 0.0076), which is what says this is a team effect
# and not a league-wide week effect. The entire structure is the QUARTERBACK: QB x pass-catcher
# ~ +0.17, QB x QB ~ -0.28, and every pair without a QB is inside +/-0.03. A single shared "team
# factor" is therefore WRONG -- it would give WR x WR the +0.17 the data says is -0.009.
SAME_TEAM_RHO: dict[frozenset[Position], float] = {...}

# Measured the same way: the share of weeks INSIDE a player's own [first seen, last seen] window
# with no ff_opportunity row. Called zero-production rather than injury on purpose -- the frame has
# a row only where there was opportunity -- but for a lineup the two are the same event. K and DST
# are 0.0 because ff_opportunity covers skill positions only, and fabricating a rate is the defect
# this project keeps finding.
ZERO_PRODUCTION_RATE: dict[Position, float] = {...}

REGULAR_SEASON_WEEKS = 18   # league/xep.py MAX_FANTASY_WEEK, the same calendar fact
```

The sampler:

- group players by `team_norm(nfl_team)`; a player with no resolvable team is his own group;
- per group build the correlation matrix from `SAME_TEAM_RHO` (diagonal 1.0), assert
  `eigvalsh().min() > 0` (measured worst 0.1698 on the real board) and Cholesky it — **raise** on a
  non-PSD matrix rather than silently repairing, because a silent repair is an unmeasured model
  change;
- draw `e ~ N(0, I)` of shape `(n_draws, weeks, n_players)`, apply the per-group factor;
- absence: `Bernoulli(q_pos)` independent across players (see the handcuff verdict — a Gaussian
  copula cannot carry the regime effect, so pretending otherwise would be worse than declaring it);
- a bye week is a hard zero for that player;
- `weekly[d, w, p] = 0 if (bye or absent) else m_p + s_p * z[d, w, p]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_weekly.py -v`
Expected: PASS.

- [ ] **Step 5: Add the structural tests, each with its own mutation**

```python
def test_a_bye_week_is_a_hard_zero() -> None:
    """bye_stack has nothing to attach to without this."""


def test_same_team_qb_and_wr_are_correlated_and_two_wrs_are_not() -> None:
    """The measured structure, pinned: QB x WR ~ +0.18, WR x WR ~ -0.01. A single shared team
    factor would fail this test, which is exactly why the model does not use one."""


def test_a_non_psd_correlation_table_raises_rather_than_being_repaired() -> None:
    """A silent nearest-PSD projection is an unmeasured model change. Fail loudly instead."""


def test_absence_makes_a_bench_player_worth_more_than_zero() -> None:
    """The bracketing this tier exists to close: under the ex-ante weekly lineup a 10th player must
    add strictly positive expected points, where `mean_lineup_value_objective` gives him exactly 0."""
```

Mutations that must break exactly one test each: set every `SAME_TEAM_RHO` value to 0.0 (the
correlation test fails, the marginal test passes); set every `ZERO_PRODUCTION_RATE` to 0.0 (the bench
test fails, the marginal test passes); ignore `bye_week` (the bye test fails, the rest pass).

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/weekly.py backend/tests/test_weekly.py
git commit -m "feat(engine): a weekly, correlated, absence-aware season model"
```

---

## Task 5: the ex-ante weekly lineup — no hindsight, and vectorised

**Files:**

- Modify: `backend/src/jaaffl/engine/weekly.py`
- Test: `backend/tests/test_weekly.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ex_ante_lineup_never_benefits_from_hindsight() -> None:
    """The starters are chosen BEFORE the week is played, by mu among the players available that
    week, and then scored on what they realized. So the ex-ante total can never exceed the
    hindsight total on the same draw -- and on a roster with no bench and no absences the two are
    equal, which is the reduction pin.
    """
    ex_ante = weekly_lineup_totals(roster, outcomes, ctx, hindsight=False)
    hindsight = weekly_lineup_totals(roster, outcomes, ctx, hindsight=True)
    assert (ex_ante <= hindsight + 1e-9).all()


def test_with_no_byes_no_absence_and_no_bench_the_weekly_total_matches_lineup_value() -> None:
    """sigma=0, q=0, exactly nine players -> the weekly sum must equal `optimal_lineup_value`, so
    the new objective is a strict GENERALISATION of the one it sits beside, not a different scale.
    """
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_weekly.py -k lineup -v`
Expected: FAIL — `weekly_lineup_totals` undefined.

- [ ] **Step 3: Write the implementation**

Ex-ante selection is by μ, and μ-order is fixed, so the choice depends only on the availability
**mask** — which is what makes it vectorisable over `(draw, week)`:

```python
def _nth_available(mask, values, cols, rank):
    """(value, valid) of the ``rank``-th available player among ``cols``, over draw x week.

    `cumsum` over the player axis turns "the r-th player still available at this position" into a
    single `argmax`, so a whole tournament's lineups are a handful of numpy ops instead of a Python
    loop per (draw, week, roster). Measured 2026-08-09: 2.53 ms per roster-scoring at 400 draws x 18
    weeks, i.e. ~1 min for a 4-arm 5-block tournament -- comparable to the season objective it sits
    beside, which it has to be or replicates stop being affordable.
    """
```

Fill dedicated slots in μ-order per position, then each flex slot takes the best remaining eligible
**by μ** — the same greedy `optimize.lineup_value` uses and optimal for this roster's
"dedicated + one WR/RB flex" structure, for the reason that function's docstring already gives.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_weekly.py -v`
Expected: PASS.

- [ ] **Step 5: Prove it can fail**

Mutate the flex rule to always take a WR → `test_with_no_byes_no_absence_and_no_bench...` fails.
Mutate ex-ante selection to pick by realized value → `test_ex_ante_lineup_never_benefits_from
_hindsight` still passes (it becomes hindsight) but the reduction pin still holds, so add the
assertion that a bench player's marginal contribution **drops** when hindsight is removed; that one
must fail under the mutation.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/weekly.py backend/tests/test_weekly.py
git commit -m "feat(engine): ex-ante weekly lineups, vectorised over draws"
```

---

## Task 6: two new objectives, registered beside the existing two

**Files:**

- Modify: `backend/src/jaaffl/calibrate/tune.py`
- Test: `backend/tests/test_tune.py`

- [ ] **Step 1: Write the failing test**

```python
def test_weekly_objectives_are_added_not_swapped() -> None:
    """Tier 9/10 numbers must stay comparable, so `win probability` and `mean lineup value` keep
    their exact present definitions and the weekly pair sits beside them."""
    report = run_tournament(ctx, contenders=..., opponents=..., seed_blocks=[[1001, 1002]])
    assert set(report["objectives"]) == {
        WIN_PROBABILITY, MEAN_LINEUP_VALUE, WEEKLY_WIN_PROBABILITY, WEEKLY_POINTS
    }


def test_the_weekly_objective_prices_a_bench_player_above_zero() -> None:
    """`mean_lineup_value_objective` gives a 10th player exactly 0.00 -- 8 of this league's 17
    picks. Under the weekly objective he covers byes and zero-production weeks, so he is worth
    strictly more than nothing. This is the bracketing Tier 9 and Tier 10 both surfaced and neither
    could close."""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_tune.py -k weekly -v`
Expected: FAIL — `WEEKLY_WIN_PROBABILITY` undefined.

- [ ] **Step 3: Write the implementation**

`WeeklyWinProbabilityObjective` and `WeeklyPointsObjective`, both reading ONE cached
`WeeklyOutcomes` per `(ctx, seed)` exactly as `WinProbabilityObjective` caches `SeasonOutcomes` —
common random numbers are what keep the 12-slot paired gate sensitive. Both are scored from the
same sampled block, so the second costs nothing.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_tune.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/calibrate/tune.py backend/tests/test_tune.py
git commit -m "feat(calibrate): weekly win-probability and weekly points objectives"
```

---

## Task 7: the harness must SEE the new objective — instance seven, pre-empted

**Files:**

- Modify: `backend/tests/test_harness_fidelity.py`

- [ ] **Step 1: Write the failing test**

Six tiers have measured something that could not move a pick, and Tier 10's instance was in the
objective itself. This tier adds a new objective, so it must answer the same question about it
**before** any number is quoted:

```python
def test_the_weekly_objective_can_see_a_bye_conflict() -> None:
    """Two rosters with IDENTICAL season marginals, one stacking three starters on the same bye
    week. If the objective cannot separate them it has no week axis, whatever the code says."""


def test_the_weekly_objective_can_see_a_same_team_stack() -> None:
    """Two rosters with identical marginals, one pairing a QB with his own WR. Correlation is the
    only thing that can separate them."""


def test_the_weekly_objective_cannot_see_a_handcuff() -> None:
    """DELIBERATE, and the reason is measured, not assumed.

    A handcuff is a REGIME effect: measured on nflverse 2023-2025, RB2 scores x1.61-x2.38 as much in
    the weeks RB1 is absent (+2.8 to +7.1 pts/week, 4-7 se). But the UNCONDITIONAL same-team RB x RB
    correlation is -0.0211 (se 0.0156, not significant), and a jointly-Gaussian model calibrated to
    that implies a conditional lift of ~+0.03 sd. So a bench RB behind our own starter is worth
    exactly what any other bench RB of equal mu is worth, and `handcuff_synergy` stays UNMEASURABLE.

    This test pins the negative so a later tier cannot quietly implement the modifier on the
    assumption that the week axis fixed it. Making it measurable needs a workload-transfer process,
    which is named in ROADMAP.md and NOT built on a guess here.
    """
```

- [ ] **Step 2–4: Run, implement nothing, confirm the first two fail on a bye-blind / correlation-blind model**

The tests are written against `weekly.py` as built in Tasks 4–5; run them, then mutate `weekly.py`
(ignore `bye_week`; zero `SAME_TEAM_RHO`) and confirm each test fails for its own reason and no
other test does.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_harness_fidelity.py
git commit -m "test(harness): the weekly objective must see byes and stacks, and provably cannot see handcuffs"
```

---

## Task 8: re-measure Tier 10's headline under the NEW objective

**Files:** scratchpad runner only.

- [ ] **Step 1: Run the four arms under all four objectives**

`override_off`, `vbd_only`, `ours(committed)`, plus the σ-order control Tier 10 used as its
refutation, on the corrected harness. 5 blocks × 8 seeds × 12 slots. Report every pair on all four
objectives with p-values and per-slot noise.

- [ ] **Step 2: State where the objectives disagree, and which is believed**

Tier 9's lesson was that the fixture and the real board gave opposite verdicts and the real board
won. The analogue here is the season and weekly objectives disagreeing on the same rosters. Name the
disagreement, name which is believed, and say why — do not average them.

- [ ] **Step 3: Report the bracket, narrowed**

`mean_lineup_value` (bench = 0) · **weekly ex-ante** (bench = bye + zero-production cover, no
hindsight) · `win probability` over `roster_season_values` (bench = perfect season hindsight). The
middle term is the tier's contribution; report all three side by side rather than claiming the
middle one is the truth.

---

## Task 9: the latency budget still holds

**Files:** none — verification only.

- [ ] **Step 1: Confirm the hot path is untouched**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_engine_latency.py backend/tests/test_mc_off_hot_path.py -v`
Expected: PASS. `engine/weekly.py` is imported only by `calibrate/tune.py`; `recommend()` must not
import it, and `test_mc_off_hot_path.py`'s pattern (assert the heavy import is absent) is the model
to follow if a new guard is needed.

---

## Task 10: drive the real FastAPI surface

**Files:** none — verification only.

- [ ] **Step 1: Run the project `verify` skill**

`backend/src/jaaffl/engine/projections.py` changed, so the REST + WebSocket surfaces must be driven
for real, not just unit-tested. `POST /draft/events` first — `/recommendation` 404s with "unknown
league" until draft events exist — and confirm `projected_points` on a returned pick is unchanged
(the live path must be bit-identical: `mu` is untouched, only `mu_raw` is new).

---

## Task 11: the corrected record

**Files:**

- Modify: `ROADMAP.md` (new Tier 11 status block at the top, in the established voice)
- Modify: `docs/owner-manual-todo.md`

- [ ] **Step 1: Write the ROADMAP block**

Sections, in the established order: what reproduced · 🔴 the finding (Task A) · measurability first ·
🔴 the finding (Task B) with the three measurements · the measurability verdicts · what is superseded
· **What Tier 11 did NOT do** · the instrument, again.

Must state explicitly: whether Tier 10's headline moved; that `sigma` still excludes missed-game
variance; that `handcuff_synergy` and `sos` remain unimplemented **and now with a measured reason**;
that no config key changed.

- [ ] **Step 2: Update `docs/owner-manual-todo.md`**

Only if an owner-facing number changed. The `lambda_slot_override` decision is **re-stated, not
resolved** — see Task 12.

- [ ] **Step 3: Prettier + commit**

```bash
pnpm exec prettier --write ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans/2026-08-09-tier11-double-shrinkage-and-the-week-axis.md
git add ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans
git commit -m "docs: Tier 11 record"
```

Tier 8's CI failed because a prettier fix was left staged out of its commit while local `pnpm lint`
passed against the already-fixed tree. Run prettier, then `git add`, then commit.

---

## Task 12: the config change this tier RE-STATES — proposed, NOT applied

**Files:** none. `config/engine.json` is owner-adopted.

- [ ] **Step 1: Verify the file, do not assume**

```bash
grep -A3 lambda_slot_override config/engine.json
```

Verified 2026-08-09, before any Tier 11 work: it still reads

```json
  "lambda_slot_override": {
    "last_startable_slot_floor": 0.4,
    "surplus_stash_ceiling": -0.4
  },
```

- [ ] **Step 2: Re-state the recommendation and the Tier 10 coupling, with Tier 11's numbers**

The proposed diff is unchanged from Tier 8/9/10 — both values to `0.0` — and **the Tier 10 coupling
finding stands**: the dictionary-order fix pays **nothing** while the override is live (0.0071 vs
0.0072, p = 0.5508; −9.8 points) and **+0.0478** once it is zeroed. Present it as a diff for the
owner. **Do not write the file.**

---

## Task 13: verification, review, PR

- [ ] **Step 1: Full local gates, in CI's order**

```bash
.venv\Scripts\python.exe -m pytest backend -q
cd backend && ..\.venv\Scripts\python.exe -m ruff check . && ..\.venv\Scripts\python.exe -m ruff format --check .
pnpm -r typecheck && pnpm -r test && pnpm lint
.venv\Scripts\python.exe scripts\export_schemas.py && git diff --exit-code packages\shared\schemas
node scripts\gen-overlay-tokens.mjs --check
.venv\Scripts\python.exe scripts\preflight.py
```

Re-run `ruff format` after editing test files — Tier 10 needed a second pass.

- [ ] **Step 2: `superpowers:requesting-code-review`, and act on what it finds**

It caught a 2.50× measurement distortion and an owner-doc overclaim in Tier 10. Do not skip it.

- [ ] **Step 3: `superpowers:verification-before-completion` before any claim**

- [ ] **Step 4: Branch, push, PR, wait for all 4 checks, squash-merge, delete branch, pull main**

Branch `tier11/double-shrinkage-and-the-week-axis`. PR body carries the measurement tables with
p-values, replicate counts, both objectives, and the pool label on every number.

---

## Self-review

- **Spec coverage.** Task A → Tasks 1–3, 9, 10. Task B → Tasks 4–8. Measurability → Tasks 2 (step 5),
  4 (step 5), 5 (step 5), 7. Deliverable 4 (modifier verdicts) → Task 7 + Task 11. Deliverable 6
  (config diff) → Task 12. Commit/merge → Task 13.
- **Placeholders.** The `{...}` in Task 4's constant tables are filled from the measured tables in
  "Why this shape" above — every value is in this document.
- **Type consistency.** `mu_raw` (Task 1) is read in Task 2; `WeeklyModel` / `WeeklyOutcomes` /
  `weekly_lineup_totals` (Tasks 4–5) are used in Task 6; `WEEKLY_WIN_PROBABILITY` / `WEEKLY_POINTS`
  (Task 6) are asserted in Task 6 and used in Task 8.
- **Known risk.** Task 5's ex-ante flex rule is a second implementation of a selection this project
  already has one of. It is pinned by a reduction test against `optimize.lineup_value` (Task 5,
  Step 1) for exactly that reason — this project's signature defect is a rule implemented twice.
