# Roadmap

Dependency-ordered build plan, distilled from the
[research report](docs/research/cbs-fantasy-football-draft-tool.md §"Final implementation
roadmap"). Each stage maps to package boundaries already scaffolded in the repo. Build in
order — later stages assume the earlier contracts exist.

> **Execution-ready detail:** the phased, task-level build plan that fills in each stage below —
> with file paths, interfaces, schemas, acceptance criteria, a v1-vs-stretch split, and a
> sequenced backlog — lives in [`docs/implementation-plan.md`](docs/implementation-plan.md)
> (its §10 Phasing maps to these same stages). This roadmap is the index; the implementation
> plan is the how.

Legend: `[ ]` not started · `[~]` scaffolded (stub/contract in place) · `[x]` done

## 📍 Status — 2026-08-09 · Tier 10 (the engine drafted half its roster in dictionary order)

> **Tier 10 of the audit is merged** (PR #62). Tier 9 closed with an unexplained residual: even with
> `lambda_slot_override` zeroed the engine wins the championship **less often than a plain VBD
> draft** (0.0683 vs 0.1066 on the real board, against a 12-team fair share of 0.0833). The cause is
> not a coefficient and never was. Once the starting nine is full, **every remaining candidate scores
> exactly 0.0**, and the ranking degenerates to `context.mu` **dictionary insertion order** — for 8 of
> this league's 17 picks.

### The residual reproduces, digit for digit

Real board (581 players capped to 300), 5 disjoint blocks × 8 seeds × 12 slots, 800 sampled seasons,
field `[SoftmaxVbd, NeedBased]` — the Tier 9 design, replayed:

| comparison, **real** board     | championship probability | expected points     |
| ------------------------------ | ------------------------ | ------------------- |
| ours (committed) vs `vbd_only` | −0.0994 (p = 1.0000)     | −201.8 (p = 1.0000) |
| `override_off` vs `vbd_only`   | −0.0383 (p = 0.9998)     | +51.9 (p = 0.0005)  |

Identical to the Tier 9 block below. The residual is real, stable, and was measured correctly.

### 🔴 THE FINDING — four terms vanish on the same candidates, and the sort key is dict order

`marginal_lineup_value` is `L*(R∪{p}) − L*(R)`. It is **exactly 0.00** for every candidate who
cannot improve the optimal nine — which is not merely the below-replacement tail: with a strong
lineup already seated it includes players far **above** replacement. The rest of the score collapses
with it:

| term               | value            | why                                                              |
| ------------------ | ---------------- | ---------------------------------------------------------------- |
| `MLV`              | **exactly 0.00** | he cracks no starting slot                                       |
| `κ · max(0, VONA)` | **exactly 0.00** | `expected_best_available` ≥ 0 while MLV = 0, so VONA ≤ 0 → clamp |
| `α · cliff_bonus`  | **exactly 0.00** | legitimately 0 below replacement (`engine/tiers.py`)             |
| `− λ · σ`          | **exactly 0.00** | every position is `SURPLUS` once filled → the override's ceiling |
| **score**          | **0.0000**       | for every remaining candidate                                    |

`picks.sort(key=(punted, -score))` is **stable**, so ties keep the order of `candidates`, which is a
stable sort of `available` = `[pid for pid in context.mu if pid not in picked]`.

**Measured on the SHIPPED hot path** — `recommend()`, real board, a real entered `draft_order` so
survival is live (`survival_basis=my_slot`), round 14, `lambda_slot_override` zeroed:

```
candidates sharing the TOP score (0.000000) exactly:  180 of 180
candidates with a POSITIVE vona (so kappa could break the tie):  0
tie order == context.mu insertion order?              True
projected points of the top 12, in ranked order:
    [122.9, 16.0, 21.2, 37.5, 31.7, 127.5, 75.5, 47.9, 61.7, 66.9, 24.7, 57.3]
engine's #1: mu=122.9    vs BEST tied mu=204.2    (gap 81.4 points)
```

**This is not a simulator artifact** — it is what the overlay would have shown on draft night. On the
test fixture the same mechanism ties **119 of 124** ranked candidates, and the best of them is a
264-point receiver sitting **+144** over his own baseline, scored identically to a 10-point kicker.

Behaviourally, in the simulator — re-asking the shipped agent the identical question with the pool
reversed, real board, 3 slots × 3 seeds = 153 of our picks:

| arm                | picks decided by **list order**         | mean VBD of the 8 weakest picks |
| ------------------ | --------------------------------------- | ------------------------------- |
| ours (committed)   | 36/153 (23.5%)                          | −56.06                          |
| **`override_off`** | **70/153 (45.8%)** — every pick R10→R17 | **−121.63**                     |
| `vbd_only`         | **0/153 (0.0%)**                        | **−37.99**                      |

### Two ordering decisions, not one

1. **The candidate cap.** `sorted(available, key=mlv, reverse=True)[:cap]` — at round 14 that chose
   **180 of 425** available players by dict order. A player never scored can never be recommended.
2. **The final rank**, among equal scores.

Only the first needed fixing: `min`/`list.sort` are stable, so the rank inherits the cap's order.
Adding the same tiebreak to the rank key was measured by mutation to move **zero** picks, so it was
dropped — this project deletes code its own tests cannot see.

### Where the gap lives — the field is innocent, and our starting nine was already better

12 slots × 4 seeds × 400 draws, real board:

| arm                          | p(win)     | realized season μ | realized **sd** | E[field max] | points     | slots filled | bench VBD |
| ---------------------------- | ---------- | ----------------- | --------------- | ------------ | ---------- | ------------ | --------- |
| ours (committed)             | 0.0061     | 1529.5            | 211.6           | 2134.6       | 1461.4     | 8.00         | −55.5     |
| `override_off`               | 0.0732     | 1802.0            | 192.4           | 2137.6       | 1710.7     | 9.00         | −122.5    |
| **`override_off` + the fix** | **0.1127** | **1866.2**        | 186.1           | 2135.7       | **1714.5** | 9.00         | **−37.8** |
| `vbd_only`                   | 0.0953     | 1823.1            | 181.7           | 2130.6       | 1648.9     | 8.81         | −38.0     |

`E[field max]` is flat across all four arms (2130.6–2137.6 against a 337-point gap), so **"our picks
leave a stronger field behind" is refuted on the real board** as it was on the fixture. Our starting
nine was **already better** than VBD's — 9.00 vs 8.81 slots filled, +61.8 points. The engine was
losing the championship **purely on the bench**, the half of the draft its own points objective
prices at zero.

### The fix, measured — and the refuting control came out the right way

`optimize.value_over_replacement` (μ − replacement) is not a new signal: `optimize.py`'s own
reduction guarantee already states "empty roster ⇒ MLV_p = μ_p − baseline(pos(p))". VOR **is** MLV
before the lineup floors it at zero, so the candidate cut now uses it as a deterministic secondary
key (then player id). Nothing is added to any score — this **re-ranks and never changes a score**,
exactly as the punt guard does, so every `ScoreComponents` decomposition is untouched.

Real board, 5 blocks × 8 seeds × 12 slots, 800 draws. Every pair gated as E2 gates: one-sided
Wilcoxon across the 12 slots **plus** the noise-aware non-regression leg.

| A vs B                                   | objective | A      | B      | A−B         | min slot | p          | beats?  |
| ---------------------------------------- | --------- | ------ | ------ | ----------- | -------- | ---------- | ------- |
| **`override_off`+fix vs `override_off`** | win       | 0.1161 | 0.0683 | **+0.0478** | +0.0340  | **0.0002** | **YES** |
| **`override_off`+fix vs `override_off`** | points    | 1716.7 | 1713.5 | **+3.1**    | +0.5     | **0.0002** | **YES** |
| `override_off`+fix vs σ-order control    | win       | 0.1161 | 0.0990 | **+0.0171** | +0.0064  | **0.0002** | **YES** |
| `override_off`+fix vs σ-order control    | points    | 1716.7 | 1715.7 | +1.0        | −2.4     | 0.0547     | no      |
| **`override_off`+fix vs `vbd_only`**     | win       | 0.1161 | 0.1066 | +0.0095     | −0.0241  | **0.1167** | **no**  |
| **`override_off`+fix vs `vbd_only`**     | points    | 1716.7 | 1661.7 | **+55.0**   | +1.3     | **0.0002** | **YES** |

⚠️ **State the verdict precisely, because the tempting version is wrong.** Against `vbd_only` the
fixed engine **beats it on points** (+55.0, p = 0.0002, non-negative at every one of the 12 slots)
and is **ahead but NOT significantly ahead on championship probability** (+0.0095, p = 0.1167,
against per-slot paired noise of median ~0.02). **The residual is eliminated, not reversed:** the
comparison moves from a clear loss to a statistical tie with the point estimate in our favour, and
the engine sits above a 12-team fair share (0.1161 vs 0.0833) for the first time. Anyone writing
"the engine now beats best-available on both objectives" is quoting a p-value that does not exist.

**The refuting control.** "The objective just rewards any bench that raises spread" is **refuted**:
an arm breaking the identical ties toward high σ instead of high value loses to the value key by
+0.0171 at p = 0.0002. Any deterministic order beats no order — σ recovers +0.0307 on its own,
because σ is a noisy proxy for value — but value is worth a further 56% on top. Honest limit: on the
**points** leg the two are indistinguishable (p = 0.0547), so the refutation rests on the
championship leg alone. The decomposition agrees it is not variance: the winning arm carries the
**lower** realized sd (186.1 vs 192.4) and wins on realized **mean** (+64.2).

**The probe was faithful.** Every `+fix` number above was first measured with a probe that merely
reordered the pool. Re-running the identical experiment with the probe removed and the tiebreak in
the shipped agent reproduces it exactly: 0.1161 / 1716.7, +0.0095 (p = 0.1167) / +55.0 (p = 0.0002)
against `vbd_only`. The σ-order wrapper becomes **exactly inert** (+0.0000 on both objectives),
which is independent proof the pick no longer depends on the order the pool arrives in.

### ⚠️ The code fix and the config change are COUPLED

| arm, **real** board                | win prob | points |
| ---------------------------------- | -------- | ------ |
| ours (committed), pre-fix          | 0.0072   | 1459.9 |
| ours (committed), **with the fix** | 0.0071   | 1450.1 |
| `override_off`, pre-fix            | 0.0683   | 1713.5 |
| `override_off`, **with the fix**   | 0.1161   | 1716.7 |

The tiebreak is worth **nothing** while `lambda_slot_override` is live — 0.0071 vs 0.0072
(p = 0.5508) and −9.8 points (p = 0.0007) — because `λ = ±0.4` already breaks the ties by σ, and the
candidate-cap change is then a small net negative. It is worth **+0.0478** once the setting is
zeroed. **Neither half is sufficient alone**, and the Tier 8/9 recommendation is still the owner's:
verified 2026-08-09, `config/engine.json` still reads `0.4 / −0.4`.

### ⚠️ A measured side effect on the LIVE path, disclosed rather than fixed

VOR is a positional-scarcity measure, not a roster-marginal one: a spare kicker sits a few points
under his baseline while a 200th-ranked receiver is 120 under his, so VOR calls the kicker better
even when you already hold one. The **simulator** cannot see this — `_rosterable` gates
`roster_capacity` there, so the +0.0478 is measured among players you can actually roster — but
`recommend()` has never had that gate (Tier 8 declined to add it, because it would bet draft night
on `constitution._BENCH_ELIGIBLE`, an owner question that is still open).

Measured by walking full 17-round drafts through `recommend()` at three seats, 51 of our picks:

```
pre-fix :  0 of 51 picks had no legal roster slot
post-fix:  1 of 51 picks had no legal roster slot   (a second K, round 12, one seat of three)
```

**Not gated here.** Gating the hot path resolves an owner question unilaterally, which the
`agent_usage_contract` forbids; it is surfaced in `docs/owner-manual-todo.md` §1b with this
measurement attached, which is far more actionable than the abstract version Tier 8 left.

⚠️ **And there is a second amplifier, found in code review, pointing the same way.** Tier 8 listed
"the reliability double-application was not investigated" as an open item (see its block below).
It is now measured, because Tier 10 promoted it from affecting only the above-replacement head to
deciding roughly half the roster. On the `--real` path the chain is: `engine/projections.py` shrinks
μ toward replacement by `reliability_shrinkage`; `engine/context.py` copies that into
`DraftContext.mu`; `calibrate/tune.py`'s `sim_context_from_draft_context` copies it into
`SimContext.value`; and `ScoreAgent._effective_value` shrinks it **again**. Median VOR on the real
board, live path vs calibration harness:

| position    | live (`ctx.value`) | harness (`_effective_value`) | ratio    |
| ----------- | ------------------ | ---------------------------- | -------- |
| **DST**     | −10.54             | −4.22                        | **2.50** |
| **K**       | −4.57              | −1.83                        | **2.50** |
| QB/RB/TE/WR | (unchanged)        | (unchanged)                  | 1.00     |

2.50 is exactly `1 / 0.4`, the committed `reliability_shrinkage`. So the **harness** rates a spare
kicker 2.5× closer to replacement than the live engine does — the same direction as the side effect
above. `demo_sim_context` builds `value` from a raw curve and shrinks once, so the fixture path is
correct and **no test can see this**. **Not fixed here:** correcting it changes every real-board
number a fourth time and deserves its own tier with its own measurement, not a late edit to this
one. It is the top candidate for Tier 11.

### The instrument, again — instance six, and this time it is the objective

`test_harness_fidelity.py` has asked one question for five tiers: change the knob, does any pick
move? Tier 10 adds the question no knob can ask — **change nothing but the order the pool arrives
in, does any pick move?** It did, for **60 of 60** simulated rosters; 0 of 60 after the fix, verified
by mutation in both directions.

- **Tier 4** — both fixture pools were params-blind (96/96 identical rosters).
- **Tier 5** — `alpha` multiplied a `cliff_bonus` map of 293 zeros.
- **Tier 6** — three positional modifiers were priced by nothing.
- **Tier 8** — `ScoreAgent` read neither `lambda_slot_override` nor `punt_guard` (0/60 rosters).
- **Tier 9** — E6 had no `--replicates` and gated on a leg Tier 6 had discredited.
- **Tier 10 — the OBJECTIVE.** `mean_lineup_value_objective` scores the optimal nine under fixed μ,
  so it prices a bench player at exactly **0** — 8 of 17 picks. The fix moves it by **+3.1** and the
  championship leg by **+0.0478**. The points leg did not merely miss the defect: under
  `override_off` it reported the engine as the **best points-scorer in the field** while it was
  drafting half its roster in dictionary order.

### ⚠️ Surfaced, not fixed: the two objectives still bracket bench value

`mean_lineup_value_objective` prices a bench player at 0; `roster_season_values` re-optimises the
lineup with **perfect hindsight** of the realised season, an upper bound on option value. The truth
is between, so the **size** of +0.0478 is objective-dependent. What is not objective-dependent: a
bench chosen by dictionary order is worse than one chosen by value under any objective that is not
identically zero, and the fix costs nothing on the points leg (+3.1, p = 0.0002). Fixing the
bracketing needs a week axis and belongs to its own tier.

### What Tier 10 did NOT do

- **No coefficient, no config key, no score changed.** The fix is a sort key. `config/engine.json`
  and `config/league.json` are untouched, and the Tier 8/9 `lambda_slot_override` recommendation is
  still **OPEN** with the owner — verified 2026-08-09, the file still reads `0.4 / −0.4`.
- **The engine is LEVEL with `vbd_only` on championship probability, not ahead of it** (+0.0095,
  p = 0.1167). Only the points leg is a win.
- **The live path is not capacity-gated**, and the fix makes it marginally more likely to surface a
  player the roster cannot hold (0/51 → 1/51). Disclosed above, owner's call.
- **The reliability double-application is measured but NOT fixed** (2.50× extra compression at K and
  DST on the `--real` harness path only, table above). Fixing it supersedes every real-board number
  again; it is Tier 11's first job, and no test can currently see it.
- **No week axis.** `sample_season_outcomes` still draws one independent season total per player, so
  `bye_stack`, `handcuff_synergy` and `sos` remain unmeasurable and unimplemented.
- **E2 was not re-run.** Re-running the study before the `lambda_slot_override` decision is made
  would measure noise around a decision nobody has taken.
- **A simulator is not a fact about drafting.** The opponents are behavioural agents, not the eleven
  people in the room.

### ⚠️ What is superseded

- Tier 9's **"the residual is unidentified — that is Tier 10's question, and nothing in this tier
  answers it"**: identified, measured on the shipped hot path, and closed to a statistical tie.
- Tier 9's real-board `override_off` figures (0.0683 / 1713.5) remain correct **as the pre-fix
  measurement** and are labelled as such throughout. Post-fix the same arm is 0.1161 / 1716.7.
- Nothing else. The fix cannot move a comparison where scores already differ, so every measurement
  of a term whose candidates were not tied stands unchanged.

## 📍 Status — 2026-08-09 · Tier 9 (the engine loses to VBD because of a term that fires in round 3)

> **Tier 9 of the audit is merged** (PR #61). Tier 8 left the most serious number in the project on
> the table: our agent scores MORE points than plain VBD and wins the championship **5.5× less
> often**. Tier 9 reproduces it digit-for-digit, finds the mechanism, finds that the instrument
> which reported it could never have chased it — and then, on the first real-board E6 this project
> has ever run, finds the truth is **worse**: there the engine loses to plain VBD on **both**
> objectives, and fixing the coefficient responsible closes most of the gap but **not all of it**.

### The gap is variance, and the field is innocent

Decomposing what `win_probability` actually consumes — fixture pool, 12 slots × 8 seeds, 800
sampled seasons:

| agent      | p(win)     | realized season mean | realized **sd** | E[field max] | deterministic points | slots filled |
| ---------- | ---------- | -------------------- | --------------- | ------------ | -------------------- | ------------ |
| ours       | **0.0180** | 1583.1               | **116.3**       | 1920.8       | **1562.1**           | 8.00 / 8     |
| `vbd_only` | **0.0984** | 1609.8               | **169.8**       | 1911.9       | 1517.7               | 7.66 / 8     |
| `adp_only` | 0.0026     | 1334.0               | 158.3           | 1913.1       | 1157.8               | 5.00 / 8     |

`E[field max]` is the same in all three arms — a 9-point spread against a 337-point gap — so **"our
picks leave a stronger field behind" is refuted.** Our roster simply carries 31% less spread against
a bar every team must clear from ~2σ below. The two objectives also disagree about the identical
rosters: deterministic points say we are +44.3 ahead, realized season mean says we are 26.7 behind.

### 🔴 THE FINDING — `lambda_slot_override` is not an endgame term. It fires in round 3.

`slot_state_for` classifies a position by its **open startable slots**: `0 → SURPLUS`,
`1 → LAST_OPEN_STARTABLE`, `≥2 → NORMAL`. On this league's nine slots that is degenerate — verified
directly against the real `resolve_league_settings("cbs-local")`:

```
pick 1, empty roster: open_startable = {QB:1, RB:2, WR:4, TE:1, K:1, DST:1}
  QB   last_open_startable   λ(R1)=+0.40   risk on median σ 106.3 = -42.52
  RB   normal                λ(R1)=+0.30   risk on median σ  59.0 = -17.70
  TE   last_open_startable   λ(R1)=+0.40   risk on median σ  29.2 = -11.68
```

**A position with exactly one starting slot can never be `NORMAL`.** QB, TE, K and DST are
`LAST_OPEN_STARTABLE` from pick 1 and `SURPLUS` forever after they are filled; they never touch the
phase schedule at all. `lambda_schedule` — the knob five tiers have tuned — is reachable only for RB
and WR, and only until their slots fill.

Traced pick-by-pick (fixture, seat 5, seed 1, committed config):

```
R3  roster={WR:1, TE:1}  TE te14  μ=173.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
R4  roster={WR:1, TE:2}  TE te19  μ=162.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
```

Picks **three and four** go to the 15th- and 20th-ranked tight ends — both below TE replacement
(176.9), both MLV exactly `0.00`, neither able to crack the starting nine. The surplus ceiling pays
**+18.69** for saturated σ against a value signal of zero, while the RB/WR alternatives (MLV +14 to
+42) sit in `NORMAL` and are _charged_ for theirs. The engine ends up holding **2.92 tight ends
against a roster capacity of 3** — the worst possible stash, since a surplus TE can displace only
our own starting TE and TE carries the lowest σ of any skill position.

**Tier 8 measured this term correctly and described its mechanism wrongly**, as an endgame defect
(`engine/risk.py`'s warning, and the Tier 8 block below). Direction, magnitude and significance
stand; the timing does not. `recommend.py` computes the identical `lambda_weight(...) · σ`, so this
is the shipped hot path, not a simulator artifact.

### The fix, and the control that keeps it honest

Fixture pool, **5 disjoint blocks × 8 seeds × 12 slots, 800 draws**, every arm the shipped
`ScoreAgent` under a different `lambda_slot_override`, all sharing ONE `SimContext` so the sampled
seasons stay common random numbers:

| arm                  | win prob   | Δ vs ours   | p          | points     | Δ vs ours | p          | roster sd | season μ   |
| -------------------- | ---------- | ----------- | ---------- | ---------- | --------- | ---------- | --------- | ---------- |
| **ours (committed)** | 0.0159     | —           | —          | 1560.8     | —         | —          | 118.0     | 1580.0     |
| **`override_off`**   | **0.1162** | **+0.1003** | **0.0002** | **1583.6** | **+22.8** | **0.0002** | 174.7     | **1667.0** |
| `surplus_off`        | 0.0219     | +0.0060     | 0.0007     | 1570.7     | +9.9      | 0.0002     | 115.8     | 1597.2     |
| `floor_off`          | 0.0724     | +0.0566     | 0.0002     | 1553.9     | −6.9      | 0.9451     | **198.2** | 1578.7     |
| `vbd_only`           | 0.0802     | +0.0643     | 0.0002     | 1483.6     | −77.2     | 1.0000     | 163.0     | 1581.4     |

On this pool `override_off` beats `vbd_only` on both legs — win **+0.0360** (p = 0.0005), points
**+100.0** (p = 0.0002) — while the committed config loses the win leg by −0.0643 (p = 1.0000).
**On the real board that is not true**, and the real board is the one that counts; see below.

**The refuting control came out the right way.** The obvious alternative account — "the objective
just loves variance, so any high-σ arm wins" — is **refuted by `floor_off`**, which carries the
_highest_ roster sd of any arm (198.2 > 174.7) and wins _less_, while losing points (p = 0.9451).
`override_off` wins because it raises realized season mean too: 1667.0 against `floor_off`'s 1578.7.

**The halves are not separable either.** +0.0060 and +0.0566 alone; +0.1003 together. Zeroing one
half leaves the other still assigning a sign opposite to the phase λ, so the term stays
non-common-mode. Roster mix says the same: committed `TE 2.92 · RB 1.30`, `override_off`
`TE 1.00 · RB 3.72` — depth moves to the position with two startable slots and the highest σ.

### 🔴 THE REAL BOARD — the first precompute-backed E6, and it is worse than the fixture showed

E6 had never been run on anything but the fixture. It has now: 581 players capped to 300, 5 disjoint
blocks × 8 seeds × 12 slots, 800 sampled seasons, field `[SoftmaxVbd, NeedBased]`.

| agent                | win prob   | points     |
| -------------------- | ---------- | ---------- |
| `vbd_only`           | **0.1066** | 1661.7     |
| `override_off`       | 0.0683     | **1713.5** |
| **ours (committed)** | **0.0072** | **1459.9** |
| `adp_only`           | 0.0026     | 1186.6     |

| comparison                   | win prob             | points              | verdict        |
| ---------------------------- | -------------------- | ------------------- | -------------- |
| ours vs `vbd_only`           | −0.0994 (p = 1.0000) | −201.8 (p = 1.0000) | **loses BOTH** |
| `override_off` vs ours       | +0.0611 (p = 0.0002) | +253.7 (p = 0.0002) | **beats BOTH** |
| `override_off` vs `vbd_only` | −0.0383 (p = 0.9998) | +51.9 (p = 0.0005)  | **SPLIT**      |

**On the real board the shipped engine does not merely trade points for championships — it loses to
plain VBD on BOTH objectives.** The fixture's consolation "+44.3 points" does not exist there; the
engine is **201.8 points behind** as well. Tier 4's headline is not inverted on this board, it is
simply gone.

**Two things follow, and the second is the one to carry forward.**

1. **The config change is confirmed, independently.** `override_off` beats the committed config on
   both objectives by a wide margin, and Tier 8's real-board magnitude (+0.0745 win / +242.73
   points, against a `[NeedBased, AdpNoise]` field) **replicates under a different opponent field**
   here (+0.0611 / +253.7). Same board, different opponents, same answer.
2. **`lambda_slot_override` is not the whole deficit.** Even with it off the engine still trails
   plain VBD on championship probability by **−0.0383**, and sits at 0.0683 against a 12-team fair
   share of 0.0833. Something else is costing roughly half a fair share, and it is unidentified.
   **That is Tier 10's question, and nothing in this tier answers it.**

⚠️ **And the fixture pool gave the OPPOSITE verdict on the decisive comparison.** It said
`override_off` beats `vbd_only` on both legs; the real board says it does not. A fixture conclusion
about the engine-vs-baseline question is therefore not evidence about the real board — the pools
agree on the direction of the knob and disagree on whether the knob is sufficient.

### ⚠️ A Tier 8 open item is closed: the code alternative is measured, and it loses

Tier 8 listed "letting all three fall through to the phase schedule" as an unmeasured arm. Measured
here **on the fixture pool**, same design: win 0.0842 (+0.0683 vs ours, p = 0.0002), points 1585.6
(+24.7, p = 0.0002) — but against `vbd_only` only **+0.0040** on win probability at **p = 0.2119**,
where `override_off` gets +0.0360 at p = 0.0005. Zeroing the config is better on the leg that
matters, because `override_off` removes the early-round σ tax on single-slot positions entirely
where fall-through keeps it at the phase rate. **Tier 9 therefore ships no engine behaviour
change**, and the recommendation stays exactly where Tier 8 left it: with the owner.

⚠️ Honest limit on that: the fall-through arm was measured on the **fixture only**, and the fixture
is now known to disagree with the real board about engine-vs-`vbd_only` comparisons. What is
established is that fall-through does not beat `override_off`; it is not established what it does on
the real board.

### The instrument, again — E6 has never been replicated

Fifth instance of this project's recurring defect, and the first in the **gate** rather than the
pool or the agent:

1. `scripts/run_tournament.py` accepted `--smoke --seeds --draws` and nothing else, so **every E6
   number ever published — Tier 8's inversion included — is a single seed block.** Tier 6 set the
   ≥5-block standard after proving the min-slot leg "was not discriminating, it was sampling"; E2
   got `--replicates`, E6 never did.
2. `run_tournament` passed **no `slot_noise`**, so its `beats` gate used exactly that discredited
   leg.
3. The two objectives were printed as unrelated paragraphs with **no combined verdict.** Tier 8's
   output said `+44.3 points p=0.0017` and `−0.0805 win prob p=1.0000` eight lines apart and nothing
   anywhere said _these disagree_.

E6 also re-simulated every draft once per objective, which is exactly why replicates looked
unaffordable. All fixed: one draft scores every objective, blocks are pooled, the gate reads
measured noise, and a `SPLIT` verdict prints whenever the reference wins one objective and loses
another. `tests/test_harness_fidelity.py` now pins each **half** of `lambda_slot_override`
separately (60/60 rosters move for each), because the "not separable" finding rests on those arms.

**And the noise it now reports is a finding in itself.** On the repaired E6, the per-slot sd of the
paired win-probability difference against `vbd_only` is **median 0.0219, max 0.0560** over 5 blocks.
E2 has been gating decisions at 0.001–0.009. **The E6 win-probability leg is an order of magnitude
noisier than the E2 leg**, so single-block E6 figures were even weaker evidence than assumed.

### ⚠️ Surfaced, not fixed: `mean_lineup_value_objective` is bench-blind

It scores the optimal nine under fixed μ, so a bench player is worth exactly **0** — 8 of 17 picks
in this league. `roster_season_values` re-optimises the lineup with **perfect hindsight** of the
realized season, which is an upper bound on option value. On identical rosters the two disagree by
78 points about ours vs `vbd_only`. They **bracket** bench value; neither is right. Changing the
objective would supersede every number in the project a fourth time and belongs in the tier that
also gives it a week axis.

### What Tier 9 did NOT do

- **No engine behaviour changed.** `engine/risk.py`, `engine/recommend.py` and `engine/simulate.py`
  are untouched. `config/engine.json` and `config/league.json` are untouched. The
  `lambda_slot_override` recommendation is still **OPEN** with the owner
  (`docs/owner-manual-todo.md` §1); verified 2026-08-09, the file still reads `0.4 / −0.4`.
- **The residual deficit is NOT explained.** With `lambda_slot_override` off, the engine still
  trails `vbd_only` on real-board championship probability by **−0.0383** and sits below a 12-team
  fair share. Tier 9 identifies one cause and measures it on two pools; it does not claim that cause
  is the only one, and it did not look for the second. Anyone quoting "the override was the problem"
  is quoting half a sentence.
- **E2 was not re-run.** Tier 8's tuned vector bought +0.0017 against a knob worth +0.0745 that
  `run_study` cannot search, so re-running the study before that knob is settled would measure noise
  around a decision nobody has made.
- **No week axis.** `sample_season_outcomes` still draws one independent season total per player, so
  `bye_stack`, `handcuff_synergy` and `sos` remain unmeasurable and unimplemented.
- **The perfect-hindsight lineup re-optimisation is recorded, not changed.**
- **A simulator is not a fact about drafting.** These numbers show the shipped coefficient is
  catastrophic against these bots on these pools. They do not show what it does on draft night, and
  the opponents are still behavioural agents rather than the eleven people in the room.

### ⚠️ What is superseded

- Tier 8's **"endgame"** framing of `lambda_slot_override`: the mechanism is corrected to round 3
  onward. Its direction, significance and recommendation are confirmed, now on a second pool.
- Tier 8's "the remove-the-branches variant is unmeasured": measured, and refuted as an improvement.
- **Every pre-Tier-9 E6 number.** All were single-block, and the CLI now uses the 1001+ disjoint-block
  seed scheme E2 and `measure_risk_term.py` use, so old and new E6 figures are not comparable. The
  Tier 8 block's E6 table below is the last of the old kind.

## 📍 Status — 2026-08-07 · Tier 8 (the endgame defect was never in the engine, and the harness could not see the knob)

> **Tier 8 of the audit is merged** (PR #60). Tier 7 handed it a residual: the engine takes a second
> quarterback over a kicker because `lambda_slot_override` pays for variance. Tier 8 set out to fix
> that with E2/E6 evidence, and found first that **the evidence could not exist**, then that **the
> defect was not in the engine at all**. Both corrections are measured, and the second one reverses
> a conclusion three consecutive tiers reached.

### The kicker famine was the opponent model

Sweeping all 12 seats × 2 opponent fields on the real 581-player board — 24 drafts per arm:

| arm                              | opponents as they were                | opponents that draft **legal** rosters |
| -------------------------------- | ------------------------------------- | -------------------------------------- |
| **committed (shipped config)**   | **24/24 illegal** — `{K: 24, DST: 5}` | **0/24 — legal, K at median R16**      |
| `lambda_slot_override` zeroed    | 0/24, K at median R10                 | 0/24                                   |
| centred σ (candidate fix)        | 24/24 illegal                         | 0/24                                   |
| feasibility gate (candidate fix) | 24/24 illegal                         | 0/24                                   |

**Against a field that drafts legally the shipped engine fills all nine slots at every seat.** Both
candidate engine fixes fail 24/24 against the old field, and zeroing the override "worked" only by
making the engine panic-draft a kicker in **round 10** to beat a field illegally consuming the whole
supply — bad advice in a real room, not a fix.

`NeedBasedAgent` / `VbdOnlyAgent` / `AdpNoiseAgent` / `SoftmaxVbdAgent` had no roster-capacity
concept. Once an agent's dedicated need is met it falls through to greedy VBD, and late in a draft
VBD **favours streaming positions** — a remaining kicker sits within a few points of his baseline
while a 200th-ranked receiver is 60 below his. Measured: the field drafted **33 of 33** draftable
kickers and **31** defenses for 12 teams, holding up to five each; on the fixture, **15 of 15** of
each and **13 players rostered illegally in one draft**. The bench is `(QB, RB, WR, TE)`, so K and
DST have capacity 1. `expand_starting_slots`, `lineup_value` and `optimize_roster` already honoured
that — **only the draft agents did not.**

The tell was in the numbers all along: five different fixes all failed at _exactly_ 96/192 on the
fixture, because the pool was measuring the opponents, not the agent. With legal opponents every arm
is **0/192**.

**Tier 6's §5, Tier 7's residual, and Tier 8's own first pass all diagnosed this as the engine being
unable to draft a kicker. All three were wrong.** Tier 7's specific instance (a second QB at R16,
MLV −72.06, σ 170.08) does not reproduce: at R16 there is no kicker on the board at all, the engine
takes a DST, and the final roster holds `QB:1`.

### The harness could not see two shipped coefficients

`ScoreAgent` — the agent every E2/E6 number is produced by — used a private phase-only λ and had no
punt guard. 12 slots × 5 seeds, rosters compared bit-for-bit:

```
lambda_slot_override sign-flipped              rosters changed:   0/60   *** BLIND ***
punt_guard disabled                            rosters changed:   0/60   *** BLIND ***
lambda_schedule doubled  [POSITIVE CONTROL]    rosters changed:  60/60   MEASURABLE
alpha = 0                [POSITIVE CONTROL]    rosters changed:  60/60   MEASURABLE
```

**So Tier 7's closing instruction — get E2/E6 evidence with `--replicates >= 3` before touching
`lambda_slot_override` — was impossible to satisfy by anyone.** This is Tier 4's "the simulated agent
was not the shipped agent" **half-fixed**: Tier 4 repaired candidate _selection_ and left the _score
function_ diverging. The rule now lives once, in `engine/risk.py`, and
`tests/test_harness_fidelity.py` requires every tuned knob to move at least one pick — verified by
mutation.

### 🔴 THE FINDING — `lambda_slot_override` is the most damaging term ever measured here

Real board, **5 disjoint blocks × 8 seeds × 12 slots, 800 sampled seasons/draft**, every arm the
shipped `ScoreAgent` with a flag (never a subclass) sharing ONE context so the seasons stay common
random numbers:

| arm                 | win prob   | Δ/slot      | min slot    | p          | points      | Δ/slot      | p          | both legs? |
| ------------------- | ---------- | ----------- | ----------- | ---------- | ----------- | ----------- | ---------- | ---------- |
| committed baseline  | 0.0121     | —           | —           | —          | 1462.48     | —           | —          | —          |
| **override zeroed** | **0.0866** | **+0.0745** | **+0.0556** | **0.0002** | **1705.20** | **+242.73** | **0.0002** | **YES**    |
| centred σ           | 0.0761     | +0.0641     | +0.0434     | 0.0002     | 1654.19     | +191.71     | 0.0002     | YES        |
| feasibility gate    | 0.0110     | −0.0010     | −0.0027     | 0.9919     | 1463.04     | +0.56       | 0.1641     | no         |
| centred + gated     | 0.0761     | +0.0641     | +0.0434     | 0.0002     | 1654.19     | +191.71     | 0.0002     | YES        |

**Zeroing `lambda_slot_override` is worth +0.0745 championship probability per slot AND +242.73
points per slot, at p = 0.0002 on both, non-negative at every one of the 12 slots on both.** No
vector in this project's history has passed both legs on both objectives with five replicate blocks.
For scale: the committed baseline wins **0.0121** where fair share in a 12-team field is **0.0833** —
one seventh of it — and the override alone accounts for nearly all of the gap.

The mechanism, and why the two halves must go together: `slot_state` is a property of **position**,
and σ is overwhelmingly positional (median 20.00 at K · 25.00 at DST · 29.20 at TE · 43.30 at WR ·
59.00 at RB · **106.30 at QB**, with **zero** within-position variance at K and DST — every kicker is
20.00). Since the override assigns **opposite signs** to the two candidates being compared, the swing
reaches `0.8·σ ≈ 85` points at QB, larger than the whole MLV signal in the endgame. Observed at R15:

```
K   Zane Gonzalez    MLV   0.00  λ=+0.40  σ=20.00  risk  −8.00   score −8.00
RB  Croskey-Merritt  MLV −44.80  λ=−0.40  σ=94.40  risk +37.76   score −7.04   <- TAKEN
```

A 45.76-point risk swing overturns a 44.80-point value verdict, to take a player whose own MLV says
he **costs** 44.80. The λ _schedule_ does not do this: it applies the same sign to every candidate in
a round, so it is common-mode. **The override is what breaks common-mode.**

**The centred-σ code fix works and is still the wrong answer.** It passes both legs (+0.0641 /
+191.71) but is beaten by simply removing the mechanism, so Tier 8 ships no scoring change. The
feasibility gate is **refuted** — inert on both objectives.

**Recommendation: set `lambda_slot_override` to `{0.0, 0.0}`.** NOT done here — `config/engine.json`
is owner-adopted and a simulator result is not a fact about drafting. See `docs/owner-manual-todo.md`
§1.

### The re-measured baseline (Goal 1), and what it costs

E2 `--real --trials 30 --replicates 5 --eval-seeds 8 --draws 800`:

```
tuned:  kappa=0.559 alpha=0.378 lambda=[0.238, 0.115, 0.0, -0.336, -0.447] rel K=0.233 DST=0.562
win prob 0.0121 -> 0.0138  mean_diff +0.0017  min_slot +0.0000  p=0.0005   -> PROMOTE
points 1462.48 -> 1478.48  mean_diff +16.00   min_slot -2.15    p=0.0093
per-slot noise over 5 blocks: median 0.0008, max 0.0028
```

The gate says PROMOTE for the first time with replicates — **and it is a trap.** The tuned vector buys
**+0.0017** while a knob `run_study` cannot search buys **+0.0745**, forty-four times more. §10.3 does
not list `lambda_slot_override` as a dimension **at all**, so the study is structurally incapable of
finding the largest effect in the system. Tier 6 showed §10.3's ranges exclude the measured optima for
κ, α and λ; Tier 8 adds that one of the two most important knobs is not in §10.3's search space.
**Nothing was written; `--write` was never passed.**

E6 (fixture, 8 seeds, 800 draws) is the other half of the same story:

| agent      | win prob   | points     |
| ---------- | ---------- | ---------- |
| `vbd_only` | **0.0984** | 1517.7     |
| **ours**   | **0.0180** | **1562.1** |
| `adp_only` | 0.0026     | 1157.8     |

**Our agent scores more points than plain VBD (+44.3/slot, p = 0.0017) while winning the championship
5.5× less often (−0.0805, p = 1.0000).** Tier 4's headline — "our edge over VBD-only is on
championship probability, not points" — is now **exactly inverted**.

### ⚠️ A Tier 6 conclusion is corrected: `reliability_shrinkage` is decision-inert

With the punt guard finally live in the agent, shrinkage moves **0 of 60** rosters; with the punt
guard off it moves **51 of 60**. Both mechanisms defer K/DST and the punt guard is absolute, so it
wins. `recommend()` has carried the punt guard since v1, so **Tier 6's "reliability helps, +0.0027,
p = 0.0212 at 32 seeds" was measured on an agent with no punt guard and does not describe the shipped
engine.** `run_study` therefore spends two of five search dimensions on a knob that cannot move a
pick — the same dilution Tier 6 found and removed for `modifier_cap`. Shrinkage still shapes μ in
`build_projections`, so only its _decision_ role is dead; both halves are pinned by a test.

### What Tier 8 did NOT do

- **No scoring code changed.** `engine/risk.py` is an extraction, byte-equivalent in behaviour; the
  two experiment levers (`centre_sigma`, `gate_surplus_stash`) are off by default and unwired from
  the live path. `config/engine.json` and `config/league.json` are untouched.
- **The capacity rule binds the SIMULATOR only, never `recommend()`.** The live path could also
  surface a second kicker (MLV 0, but a SURPLUS `λ = −0.4` pays +8.00). Gating the hot path would bet
  draft night on `constitution._BENCH_ELIGIBLE`, which its own comment calls "a JAAFFL modeling
  choice" — `config/league.json` specifies a bench COUNT with no eligibility. **Surfaced per the
  `agent_usage_contract`, not resolved**; it is an owner question in `docs/owner-manual-todo.md` §1b.
- **The "remove the override branches entirely" variant is unmeasured.** The measured arm sets both
  coefficients to 0.0, which makes LAST_OPEN_STARTABLE and SURPLUS candidates carry **no** risk term
  while NORMAL candidates keep the phase λ. Letting all three fall through to the phase schedule is a
  code change and a different arm.
- **Timing is still not claimed optimal, and `--real` E6 was not run** (the tournament is
  fixture-only). Nor was the reliability double-application investigated: on `--real`,
  `SimContext.value` is already shrunk by `build_projections` and `ScoreAgent._effective_value`
  shrinks it again.
- **A better simulator is still a simulator.** The opponents are behavioural agents, not the eleven
  people in the room.

### ⚠️ Everything numeric in Tiers 4–7 is superseded a third time

Tier 7 invalidated the Tier 4–6 numbers by changing what a roster is worth. Tier 8 changes what the
opponents do **and** what our own agent scores, so every figure moves again. The α = 0 recommendation
remains **suspended**, not withdrawn, and has now been overtaken in importance: α is worth ~0.013
where the override is worth 0.0745. Re-measure before quoting anything.

## 📍 Status — 2026-07-27 · Tier 7 (the engine could not fill a legal roster, and the objective could not see why)

> **Tier 7 of the audit is merged** (PR #58). Tier 6 _found_ the late-round defect and wrote it
> down as an owner warning. Tier 7 asked why six tiers of calibration never caught it, and the
> answer was that **the measuring instrument was blind to it**: the E2/E6 objective scored a roster
> with no quarterback exactly as highly as one with a replacement quarterback. The fix had to start
> there, not at the symptom.

### The root cause is NOT what Tier 6 recorded

Tier 6's one-line root cause — "`max(0, ·)` in MLV makes an empty REQUIRED slot worth exactly what
a thirteenth tight end is worth" — is **wrong as a mechanism**. Instrumenting the real 510-player
board found three separate defects:

1. **The baseline collapsed onto the candidate himself.** `dynamic_replacement_values` floors
   remaining startable demand at 0, so a saturated position took `_value_at_rank(ranked, 1)` — the
   **best available player** — and `lineup_value` credits `max(μ, baseline)` either way, so his own
   MLV was _exactly_ `0.0000` by construction. Measured QB `μ_best − baseline` by round:
   `+51.15 · +9.40 · +0.32 · 0.0000 · 0.0000 …` from R4 on, never recovering. The function's own
   docstring already said it pointed one past remaining demand precisely to avoid "collapsing onto
   the best remaining candidate's own μ" — the zero floor defeated its own stated intent.
2. **The risk term outranked value.** `lambda_slot_override` pays a SURPLUS candidate `λ = −0.4`
   — **+18.69** at the clamp-saturated `σ = 46.72` — while charging the LAST_OPEN_STARTABLE
   candidate `+0.4`. At R17 the kicker's MLV had _not_ collapsed; it was **+13.16**, and he still
   lost, because `13.16 < 18.69`. **Fixing the baseline alone would not have produced a legal
   roster.**
3. **The objective could not see either.** `roster_season_values` delegates to the same
   `lineup_value`, which credited `baselines[QB] = 230.64` for an empty slot.

### The measurement that explains six tiers of silence

Real board, swapping the 3 worst tight ends for the _actual_ R15–R17 leftovers (Davis Mills QB
μ=83.60 · Brandon Aubrey K μ=89.98 · Buffalo DST μ=87.19):

|                                 | points      |
| ------------------------------- | ----------- |
| what the objective reported     | **+15.34**  |
| what the swap is actually worth | **+260.77** |
| visible fraction                | **5.9%**    |

The visible +15.34 is _entirely_ the kicker (89.98 − 74.64). The QB and the DST contributed
**exactly zero**. **No E2/E6 gate could ever have promoted a fix**, because the instrument could
not measure the thing being fixed. That is the whole answer to "why did this survive six tiers".

### The fix, and what it does not claim

One parameter-free rule: **a replacement phantom is only worth counting while a pick remains to
draft it.** `lineup_value` takes `picks_remaining` (`None` = today's behaviour, bit-identical);
`marginal_lineup_value` spends the pick it costs, `L*(R ∪ p, k−1) − L*(R, k)`. It is provably
**inert while `k − 1 ≥ u`**, i.e. rounds 1–14 are unchanged, so the measured early-draft behaviour
is preserved and only the endgame moves. The objective passes `k = 0` — the draft is over. A slot
whose phantom is unaffordable falls back to the best sub-replacement leftover, without which a
rostered-but-weak QB would still score 0 and the blindness would reappear in a new form.

Real-board walk from seat 6, before → after:

```
before                                  {RB:1, TE:13, WR:3}              4 unfillable slots
after (best-available opponents)        {DST:1,K:1,QB:1,RB:2,TE:8,WR:4}  LEGAL, all 9
after (need-based opponents)            {DST:1,QB:2,RB:1,TE:9,WR:4}      K still missing
```

**A carried-forward finding is corrected: that roster leaves FOUR starting slots unfillable, not
three.** Tier 6 counted missing _positions_ (QB/K/DST) and forgot the WR/RB flex, which the 1 RB
and 3 WR drain before it is reached. `docs/owner-manual-todo.md` §1b said "three of your nine" and
has been fixed.

**The residual, stated plainly.** Under need-based opponents the engine still misses a kicker. At
R16 it takes a second quarterback (MLV **−72.06**, σ **170.08**) over the best kicker (MLV
**+2.58**, σ 20.0): the surplus-stash `λ = −0.4` pays **+68.03** for variance a second QB can
never use — you start only one, and the flex is WR/RB — while the last-open-startable `+0.4`
charges the kicker −8.00. So the kicker loses by 1.4 points on risk alone. That is defect 2, it
touches an owner-adopted coefficient, and it needs E2/E6 evidence with `--replicates >= 3`. It is
Tier 8's, and nothing in `config/engine.json` was edited.

### ⚠️ Findings B, C and D are SUPERSEDED, not confirmed

Tier 6's noise floor (B), its kappa/reliability resolution (C) and its §10.3 sweeps (D) were all
measured **under the blind objective**. Changing what a roster is worth changes every one of those
numbers, so they are **not comparable to anything measured after this change** and must be re-run
before any of them is quoted again. They have deliberately NOT been re-measured here — a re-run
costs 5 seed blocks per arm and would have been reported on a half-finished engine, which is the
exact mistake this audit keeps finding. **Tier 7 therefore does not carry a kappa, lambda, alpha
or reliability recommendation of any kind.**

### What Tier 7 did NOT do

- **Goal 2 (points for the kappa/lambda sweeps) — not done, and deliberately so.** It is blocked by
  the objective change above: measuring points under an instrument that is about to change would
  produce a number with a two-hour shelf life.
- **Goal 3 (the σ clamp) — measured, not changed.** `VOL_RATIO_MAX` saturation is now _implicated_
  rather than cosmetic: σ = 46.72 six times in R12–17 makes the late-round tiebreak arbitrary, and
  σ = 170.08 on a surplus QB is what still beats a kicker. Recorded, not tuned.
- **Goal 4 (what the objective cannot see) — unchanged and still true.** `sample_season_outcomes`
  draws one season total per player independently, so there is still **no week axis** and **no
  cross-player correlation**. `bye_stack`, `handcuff_synergy` and `sos` remain unmeasurable and
  unimplemented. Tier 7 makes the objective see _roster legality_; it does not give it a calendar.
- **Timing is not claimed to be optimal.** The fix guarantees a _legal_ roster; whether the engine
  should take a QB at R10 rather than R15 is now measurable for the first time, and is unmeasured.

## 📍 Status — 2026-07-27 · Tier 6 (the remaining terms, and what the harness can actually measure)

> **Tier 6 of the audit is merged** (PRs #53–#56). Tier 5 asked whether any _other_ term was dead.
> Tier 6 asked the harder question — **which terms can this harness measure at all** — and found
> that two "unresolved" terms were resolvable all along, that the promotion gate has been rejecting
> on its own sampling noise, and that the engine cannot fill a legal roster.
>
> ### 1. `bye_week` was rendered by the overlay and populated by nothing (PR #53)
>
> `RecommendedPick.bye_week` is declared on the Pydantic contract, mirrored in Zod, and actively
> rendered — `overlay.ts` pushes a `bye N` chip. **Zero backend writes existed**, so the chip could
> never appear. Same shape as Tier 2's vanishing ESTIMATED badge: wired end to end except for input.
>
> The stub's premise ("bye data is not on the $0 tier") is **false**: `load_schedules(2026)` returns
> **272 regular-season games, all 32 teams, one clean bye each** (weeks 5–14; no team is on bye in
> week 12). A bye is a calendar fact — no coefficient, nothing to calibrate.
>
> Then the real board caught what the suite could not. Naive wiring left **152 of 510 projected
> players (30%) with no bye**, because the two free feeds disagree: `load_ff_playerids` spells teams
> `NOS`/`SFO`/`LAR`, `load_schedules` spells them `NO`/`SF`/`LA`. **9 of 32 teams joined to nothing**
> while 23 resolved perfectly and the map looked populated at **1188 entries** — a COUNT read healthy
> yet again. Team defenses were unaffected (they come from `load_teams`, already in the schedule's
> vocabulary), so **two team vocabularies coexisted in one dict**: DST missed 1 player, RB missed 41.
>
> Fixed by extending the EXISTING `crosswalk.team_norm` (it lacked only `LA`→`LAR`, measured to be
> the sole residual), not a parallel map. Live board: **152 missing → 25**, and all 25 are `FA` free
> agents, who genuinely have no team. `league.coverage.teams_missing_bye_weeks` is the guard, and it
> is **proven on the real board**: deleting three aliases makes preflight print `no bye resolved for
LAR, NOS, SFO` and coverage fall 485→440; restored, 485 of 510 and silence.
>
> ### 2. The promotion gate's min-slot leg was rejecting on noise (PR #54) — Tier 4's deferred question
>
> Every vector ever rejected on this leg failed by **0.0009–0.0016**. Measured (real board, 5 disjoint
> blocks × 8 seeds × 800 draws), the **per-slot SD of a paired difference is 0.0013–0.0089**, to
> 0.0148 on individual slots — five to ten times _inside_ the margin the leg decides on.
>
> Block 0 uses the canonical seed block and **reproduces the Tier 5 control table digit-for-digit on
> all five arms**, so the harness is faithful and the Tier 5 numbers are real.
>
> | α = 0 vs baseline | per block                                                             |
> | ----------------- | --------------------------------------------------------------------- |
> | `min_slot`        | **+0.0009, −0.0295, −0.0231, −0.0094, −0.0139** → promotes **1 of 5** |
> | `mean_diff`       | +0.0133, +0.0063, +0.0033, +0.0133, +0.0086 → positive **5 of 5**     |
>
> **The mean effect of α = 0 is robust; its "passes both legs" headline is a property of seed block
> 1001–1008** — which happened to be the canonical one. Tier 5's claim that it was "the first vector
> in this project's history to pass both legs" should be read as a statement about one seed block.
>
> The failure is **structural, not mere strictness**: `min` over 12 slots is an extreme-order
> statistic, so requiring it to be non-negative as a _point estimate_ demands the worst of twelve
> noisy estimates land above zero — which a real, positive effect fails most of the time.
>
> `promotion_decision(..., slot_noise=...)` now asks whether a slot is **significantly** worse.
> Omitted, the leg is byte-identical to before. `tune_engine_params.py --replicates N` supplies it.
>
> ### 3. κ and reliability_shrinkage are RESOLVED — both HELP
>
> Tier 5 reported them "statistically unresolved" at `p = 0.9355` / `p = 0.9199`. **Those p-values
> are from the reverse-direction test.** `promotion_decision(tuned, baseline)` is one-sided with
> `alternative="greater"`, so `promotion_decision(kappa_off, baseline) → p = 0.9355` tests whether
> _turning κ off helps_ — which nobody believes. The question "does κ help?" is
> `promotion_decision(baseline, kappa_off)`. Re-run in the correct direction, pooling disjoint
> blocks (pooling R blocks of S seeds **is** an R·S-seed evaluation, since per-slot scores are seed
> means):
>
> | blocks | seeds | κ helps                  | reliability helps        |
> | ------ | ----- | ------------------------ | ------------------------ |
> | 1      | 8     | +0.0044, p = 0.0820 — no | +0.0026, p = 0.0967 — no |
> | 2      | 16    | +0.0062, **p = 0.0420**  | +0.0038, **p = 0.0244**  |
> | 4      | 32    | +0.0064, **p = 0.0420**  | +0.0032, **p = 0.0212**  |
> | 5      | 40    | +0.0064, **p = 0.0400**  | +0.0027, **p = 0.0212**  |
>
> **Both terms help, and keep their committed values.** The required N is **16 seeds for κ**;
> reliability crosses at 16 but wobbles back at 24 (`p = 0.0527`) before settling, so treat **32
> seeds** as its honest threshold. Neither is resolvable at the 8 seeds every prior run used — so
> "unresolved" was half a real power problem and half a p-value read backwards. κ's measured cost is
> the trade Tier 5 flagged: it buys win probability and is roughly points-neutral.
>
> ### 4. The positional modifiers: unimplemented, and unmeasurable by this harness (PR #55)
>
> `_positional_modifiers` returning `{}` is an honest stub, not the bug. The bug was
> `config/engine.json` advertising `bye_stack 3.0`, `handcuff_synergy 5.0`, `sos 3.0`,
> `modifier_abs_max 5.0`. **Both** of the stub's stated reasons were re-tested and both were wrong:
> the $0 data exists (schedules + 375k depth-chart rows, both free), and there is **no capped
> mechanism** — no clamping code exists anywhere; the score just adds `sum(mods.values()) = 0.0`.
>
> The real blocker is that **E2 structurally cannot price any of the three.**
> `sample_season_outcomes` draws ONE season total per player from `N(μ, σ)`, **independently per
> player**, and `roster_season_values` optimises the lineup once over those totals. So the objective
> has **no week axis** (bye_stack, SOS have nothing to attach to) and **no cross-player correlation**
> (which is the entire value of a handcuff — it pays out exactly when the starter does not).
> Implementing one would ship an unvalidated coefficient into the live scorer. **These need a
> weekly, correlated objective first.** Caps removed from the config, from `EngineParams`' defaults,
> and from §6.C.7; `test_config` asserts they stay absent.
>
> Also: `run_study` was searching `modifier_cap`, which **nothing reads** — six TPE dimensions on two
> training seeds over thirty trials, one provably inert, diluting the power available to κ, α and λ.
> That is the same power problem Tier 5 blamed for the study disagreeing with the one-factor table.
>
> ### 5. ⛔ THE LATE-ROUND DEFECT — the engine cannot field a legal roster
>
> The most serious finding of this tier, and it is **not** the one the tier expected. Walking a full
> 12×17 draft on the real board from seat 6, the engine's own recommendations produce:
>
> ```
> R1:TE R2:WR R3:WR R4:WR R5:TE R6:TE R7:TE R8:TE R9:TE R10:RB R11:TE R12:TE R13:TE R14:TE R15:TE R16:TE R17:TE
> roster: {RB: 1, TE: 13, WR: 3}       QB 0/1 · K 0/1 · DST 0/1  -> THREE starting slots unfillable
> ```
>
> **Identical under both opponent models** (best-available _and_ realistic need-based), so it is not
> an artifact of the simulated field. And the required positions were abundantly available:
>
> | at my pick | available | rendered rank of the best one |
> | ---------- | --------- | ----------------------------- |
> | QB, R10    | 38        | 150                           |
> | DST, R16   | 20        | 55                            |
> | K, R17     | 21        | 53                            |
>
> The mechanism, consistent with the data: from ~R5 the top candidate's **MLV is 0.00** — every
> remaining player at every needed position is below replacement, and `lineup_value` refuses to start
> a sub-replacement player, so adding one contributes nothing. VONA is then `0 − 0 = 0` and the cliff
> is 0 below replacement, so the score collapses to `−λ·σ`, which with λ negative is `+|λ|·σ`: **take
> the noisiest projection.** And σ saturates at the clamp, so it is a per-position near-constant
> (R12–17 picks all have σ ≈ 46.7) — the tiebreak among below-replacement players is effectively
> arbitrary. R13 took μ = 16.1 over an available μ = 82.9.
>
> So the answer to "is the late tilt picking upside or noise?" is **neither**: it is picking a
> near-constant, and the roster-need signal is invisible to it. **`max(0, ·)` in MLV means an empty
> required slot is worth exactly as much as a 13th tight end.** The punt guard works as designed (DST
> moves 180→55 at R16) but only past _other punted_ players. Not fixed here — a fix changes live
> recommendations and needs E2/E6 evidence and a gate. **This is Tier 7's headline.**
>
> ### 6. §10.3's ranges vs the measurements (surfaced, per the `agent_usage_contract`)
>
> **α's measured optimum (0.0) lies outside its specified `[0.3, 0.5]`**, so `run_study` is
> structurally incapable of finding it. Tier 6 asked whether κ and the λ bands share the defect and
> **measured it** — one-factor sweep, real board, 3 disjoint blocks × 8 seeds × 800 draws:
>
> | κ        | 0.00   | 0.25   | 0.50   | **0.65** (shipped) | **0.80** (§10.3 max) | 1.10   | 1.50       |
> | -------- | ------ | ------ | ------ | ------------------ | -------------------- | ------ | ---------- |
> | win prob | 0.0932 | 0.0947 | 0.0993 | **0.0987**         | **0.1032**           | 0.1053 | **0.1165** |
>
> **κ rises monotonically across the whole probed span and is still climbing at 1.50 — nearly double
> §10.3's ceiling of 0.80.** κ = 1.50 is the argmax in _all three_ blocks independently (0.1102,
> 0.1190, 0.1202), and the shipped 0.65 gives up **+0.0178** against it — larger than the α = 0
> effect. The one non-monotonicity (0.65 dipping 0.0006 below 0.50) is well inside the noise floor.
>
> λ, scaling the whole shipped schedule (within-run, so directly comparable):
>
> | λ scale  | 0.5×       | **1.0×** (shipped) | 1.5×   |
> | -------- | ---------- | ------------------ | ------ |
> | win prob | **0.1233** | 0.0987             | 0.0981 |
>
> **λ at half the shipped magnitude beats it by +0.0246 — the largest single effect measured in this
> project** — and it replicates in all three blocks (0.1142, 0.1287, 0.1270). Halving puts every band _outside_
> its §10.3 range (band 1 → 0.15 vs a 0.20 floor; band 5 → −0.20 vs a −0.30 ceiling), so the tuner
> cannot reach it either. That is consistent with the tuner having twice returned λ values pinned to
> its band FLOORS: it was pushing against a wall.
>
> **All three canonical ranges exclude their measured optimum.** `run_study` searching §10.3 is a
> measurement instrument that cannot report the truth about any of κ, α or λ. **Surfaced per the
> `agent_usage_contract`, deliberately NOT silently widened** — changing the canonical ranges is a
> spec decision, and the ranges are one of the few things a future tier can still trust to be the
> plan's letter rather than this audit's inference.
>
> ⚠️ **Read these with three caveats.** (1) They measure **win probability only** — points were not
> measured for these arms, and Tier 5 showed κ _buys win probability with points_, so a large κ very
> plausibly costs points. (2) Three blocks, not five; the direction replicates in all three and κ's
> dose-response spans seven points, which is the same strength-of-evidence argument Tier 5 used for
> α, but it is not the five-block treatment §2 got. (3) A better simulator is still a simulator.
> **Nothing was adopted.**
>
> ### What Tier 6 did NOT do
>
> `config/league.json` untouched. `config/engine.json` edited **only** to delete four inert keys
> (behaviour-neutral — nothing read them); no tuned vector adopted, and **α is still 0.4** — that
> decision remains the owner's, now with the caveat that its min-slot leg does not replicate. The
> late-round defect is diagnosed, not fixed. The σ-clamp saturation question is still open and is now
> implicated in §5. And a replay is still not a live draft.

## 📍 Status — 2026-07-27 · Tier 5 (the tier-cliff term)

> **Tier 5 of the audit is merged** (PRs #50–#52). Tier 4 handed it a term that moved the result by
> **exactly +0.0000**. That was not a weak effect — the term was structurally dead, and a dead term
> cannot be evaluated. Tier 5 made it real, then measured it. **The measurement says to turn it
> off.**
>
> ### Why it was dead — three measurements, all of which had to change
>
> - **BIC cannot find tiers in this variable.** BIC is a _density-estimation_ criterion ("was this
>   generated by k Gaussians?"). A position's value curve is smooth and monotone, not multimodal, so
>   the honest answer is "by none of them" and BIC falls back to the simplest model. Measured argmin
>   over the draftable top-204: **k=1** for RB, QB, TE and K — on ECR _and_ on μ — and k=2 for WR.
>   Over the whole 510-player board it found **8 boundaries total**: all 31 defenses in ONE tier, a
>   kicker tier holding exactly ONE player, skill tiers of 25–54. Boris-Chen tiering works because
>   each player carries a _distribution_ of expert opinions and tiers emerge where those separate;
>   the `rankings()` feed returns a single consensus scalar, which has had that signal averaged out.
> - **ECR and μ are no longer the same ordering.** Pre-Tier-1, μ was `max(0, 300 − ecr)`, so cutting
>   tiers on ECR and pricing the drop in MLV was self-consistent. Measured now:
>   **Spearman(ECR, μ) = −0.943** over 447 players, and they disagree exactly where cliffs live —
>   the μ-best WR ranks **39.5** by ECR; the ECR-best QB is only **μ-rank 11**.
> - **Tiering the whole board puts every boundary below replacement.** Empty-roster MLV is
>   `max(0, μ_p − baseline_pos)` and the baseline **is** the last startable player, so exactly
>   `(starting slots − positions)` players clear it: **102 of 510** here (9×12 − 6; per position
>   QB 11 · RB 19 · WR 39 · TE 11 · K 11 · DST 11 = demand minus one each). A boundary below that
>   rank prices `max(0.0, 0.00 − 0.00)` **by construction** — which is what all 8 did.
>
> ### The tiering policy (PR #50)
>
> Exact **gap segmentation on μ**: break each position where the drop to the next player exceeds
> that position's own **mean** adjacent drop, keeping the largest such drops up to
> `max_tiers_per_pos`. No new constant — the threshold is the position's own curve. No "draftable
> subset" parameter — sorting by value already puts the big drops at the top, where they can pay.
> Determinism is unconditional rather than conditional on `random_state`. Deliberately **no minimum
> tier size**: measured, requiring 3 players per tier erases the two biggest real cliffs on this
> board (TE1 sits **43.88** points clear of TE2, RB1 **40.13** clear of RB2). **K and DST are not
> special-cased** — the rule self-scales, so a uniform board yields ONE tier and no cliff, and the
> live kicker board tops out at a **2.97**-point cliff on its own.
>
> This departs from §3.6's letter (GaussianMixture on ECR) and its `random_state` acceptance clause.
> Surfaced per `config/league.json`'s `agent_usage_contract`, with the measurements, in
> `engine/tiers.py`'s module docstring. §3.6's _own_ acceptance criterion ("the worst player in a
> non-bottom tier carries a **positive** CliffBonus") was already failing live at 0 of 8 boundaries.
> `scikit-learn` was in the `engine` extra only for the GMM and is now dropped.
>
> Live board, before → after: **8 boundaries → 42**; **0 non-zero cliffs → 16**, at all six
> positions; **447 players tiered → 510** (μ covers every projected player, not just the ones the
> rankings feed reached). Every surviving zero has `weakest = 0.00, best_next = 0.00` — a boundary
> below replacement, where a drop is legitimately worth nothing. That is Tier 3's `survival_basis`
> principle here: a **computed** 0.00, distinguishable from a degraded one.
>
> It reaches the surface, not just the map: walking a full 12×17 draft from seat 6, **11 of the
> top-5 rows across the 17 picks carry a non-zero `applied_cliff`** — rank #1 in rounds 1, 4, 5 and
> 9 — and `explain_pick` renders the tier-cliff sentence on all 11. The R1 best pick carries
> `α·43.88 = 17.55`.
>
> ### THE FINDING — α is live, and it HURTS (PR #52)
>
> Same harness, same conditions as Tier 4 (real pool capped to 300, held-out `[NeedBased,
AdpNoise]`, 8 seeds, 800 sampled seasons/draft), re-run 2026-07-27 with the term working:
>
> | vector                      | win prob   | Δ/slot      | min slot    | p          | points      | Δ/slot    | p          |
> | --------------------------- | ---------- | ----------- | ----------- | ---------- | ----------- | --------- | ---------- |
> | committed baseline (α=0.4)  | 0.0926     | —           | —           | —          | 1748.08     | —         | —          |
> | pure MLV (κ=α=λ=0, rel=1)   | 0.0599     | −0.0328     | −0.0528     | 1.0000     | 1774.35     | +26.27    | 0.0002     |
> | λ OFF only                  | 0.0777     | −0.0149     | −0.0309     | 0.9966     | 1747.23     | −0.85     | 0.9866     |
> | κ OFF only                  | 0.0882     | −0.0044     | −0.0300     | 0.9355     | 1748.64     | +0.56     | 0.9512     |
> | **α OFF only**              | **0.1059** | **+0.0133** | **+0.0009** | **0.0002** | **1753.35** | **+5.28** | **0.0002** |
> | reliability OFF             | 0.0900     | −0.0026     | −0.0164     | 0.9199     | 1749.16     | +1.08     | 0.0312     |
> | λ DOUBLED                   | 0.0852     | −0.0074     | −0.0244     | 0.9954     | 1747.49     | −0.59     | 0.7217     |
> | α DOUBLED (0.8)             | 0.0871     | −0.0055     | −0.0200     | 0.9829     | 1739.54     | −8.54     | 1.0000     |
> | α = 0.5 (§10.3 range top)   | 0.0870     | −0.0056     | −0.0200     | 0.9866     | 1740.63     | −7.45     | 1.0000     |
> | α = 0.3 (§10.3 range floor) | 0.0940     | +0.0014     | −0.0009     | 0.0625     | 1748.64     | +0.56     | 0.0625     |
>
> **`α OFF only` passes BOTH legs of the promotion gate** — significant on the one-sided Wilcoxon
> (p=0.0002) _and_ non-negative at every one of the 12 slots (min `+0.0009`) — on win probability
> _and_ on points. No vector in this project's history had done that before.
>
> The **dose-response is monotone**: α = 0.0 → 0.1059 · 0.3 → 0.0940 · 0.4 (shipped) → 0.0926 ·
> 0.5 → 0.0870 · 0.8 → 0.0871. The measured optimum sits **below** §10.3's specified `[0.3, 0.5]`
> range, so the range floor is binding and the spec's own bounds exclude the best value.
>
> **The numbers are internally consistent, which is why they are trustworthy.** Two arms are
> α-independent by construction and must reproduce Tier 4: `pure MLV` 0.0624 → 0.0599 (−0.0025) and
> `α OFF` 0.1077 → 0.1059 (−0.0018). That ~0.002 is one day of FFC ADP drift, not the tiering
> change. The baseline moved 0.1077 → 0.0926 (−0.0151): ~−0.002 drift plus the **−0.0133** of α
> going live, which is exactly the within-run `α OFF` delta. **Cross-day absolute numbers are not
> comparable; only within-run comparisons are.** The other Tier-4 rows shrank simply because they
> are measured against a baseline that is now worse.
>
> Where it hurts most is the tell: **slot 1**, baseline 0.0958 vs α-OFF **0.1650**. That is the seat
> best placed to take the huge-cliff player (TE1 +43.88, RB1 +40.13) first overall. Consistent with
> α **double-counting scarcity that κ·VONA already prices** — and pricing it worse, because the
> cliff bonus is static and unconditional while VONA is conditioned on survival probability and on
> when you actually pick again. Offered as a mechanism consistent with the data, not as proven.
>
> **The E2 study does NOT contradict this, and is the weaker evidence.** Re-run under the same
> settings (30 trials, seed 1, 2 train / 8 eval seeds, 800 draws) it tuned to κ=0.592 **α=0.500**
> λ=[0.242, 0.102, 0.0, −0.369, −0.472], rel K=0.279 DST=0.332 → win prob 0.0926 → 0.1090
> (`mean_diff +0.0164, p = 0.0005`) but points 1748.08 → 1739.43 (`−8.65/slot`), and
> `min_slot_diff −0.0016` → **KEEP baseline**, failing only the non-negative leg _again_. It picked
> α at the top of its allowed range while the one-factor table says the top of that range is the
> worst value in it. That is not a conflict, it is a power problem: Optuna fits **six dimensions
> jointly on two training seeds over thirty trials**, so it cannot attribute credit to any single
> dimension, whereas the control table varies one term at a time on the held-out seeds under common
> random numbers. Where they disagree about a single coefficient, **believe the one-factor table.**
> Note also that §10.3 bounds α to `[0.3, 0.5]`, so the study is structurally incapable of finding
> α = 0 no matter how many trials it runs.
>
> **Recommendation: set `alpha` to 0.0.** NOT done here — `config/engine.json` is owner-adopted and
> a simulator result is not a fact about drafting. The term stays wired and is now _measurable_, so
> this can be revisited. See `docs/owner-manual-todo.md` §1 for the owner decision.
>
> **A better simulator is still a simulator.** The opponents are behavioral agents, not the eleven
> people in the room; the objective is a total-points championship proxy because
> `config/league.json` specifies no playoff bracket. What raises confidence here above a single
> point estimate is the monotone dose-response across five α values and agreement across two
> independent measures.
>
> ### The guard (PR #51)
>
> `league.coverage.inert_cliff_positions`, alongside `board_coverage_gaps` with the same
> report-never-raise contract: per startable position, _is any drop priced above zero?_ One
> condition covers both live shapes of death (DST had no boundary at all; the other five had
> boundaries that all priced to zero). `precompute` logs `precompute_inert_tier_cliff` and still
> serves the board; `preflight` exits non-zero, but only for **non-puntable** positions, because
> K/DST boards really are flat. **Proven to fire on the real board**, not a fixture: mutating
> tiering to one tier per position makes the real preflight print `FAIL: no tier cliff can ever be
priced at QB, RB, TE, WR` and exit 1 with `0 priced drops over 510 tiered`; unmutated it exits 0
> with `16 priced drops`. The mutation was verified present on disk before the run and gone after.
>
> **E6 is unchanged and re-verified**, because `calibrate/pools.py::demo_sim_context` computes its
> cliffs inline and never calls `assign_tiers`: ours 0.1226 > adp_only 0.1148 > vbd_only 0.1036;
> points ours 1588.3 vs vbd_only 1588.2 (`+0.1, p=0.5750`), ours BEATS adp_only (`+16.4/slot,
p=0.0002`). That the fixture guard passed throughout is exactly the point — **a fixture can prove
> the harness can measure a term, never that the board carries one.**
>
> ### Exit survey — is any OTHER term dead? (measured, so Tier 6 starts from fact)
>
> α went unnoticed for four tiers because nobody asked. Asked of every term, on the live board,
> walking a full 12×17 draft from seat 6 and tallying the **top-10 rendered rows at each of my 17
> picks** (170 rows), with `survival_basis = my_slot` on all 17:
>
> | term                 | rows non-zero    | verdict                              |
> | -------------------- | ---------------- | ------------------------------------ |
> | `risk_penalty` (λ·σ) | 170 / 170 (100%) | live                                 |
> | `mlv`                | 37 / 170 (21.8%) | live, but see below                  |
> | `vona > 0`           | 32 / 170 (18.8%) | live                                 |
> | `cliff_bonus`        | 16 / 170 (9.4%)  | live **as of this tier** (was 0)     |
> | any modifier         | **0 / 170**      | the dict is always empty — see below |
>
> **The first reading of this survey was wrong, and the honesty field caught it.** Run against a
> synthetic `DraftState` it reported `vona > 0` on **0 of 170** rows, which looks exactly like
> another dead term. It was not: `survival_basis` read `degraded_no_slot` on all 17 picks, because
> `opponents._my_overall_picks` needs `settings.draft_order` and `config/league.json` never infers
> one. Injecting the order the CBS room supplies on the night moves VONA to 18.8% (R3 best pick:
> `mlv 78.28 − E[best next] 39.85 = vona 38.43`). Tier 3 added `survival_basis` precisely so a
> degraded 0.00 could not pass for a computed one; this is it earning its keep.
>
> **The modifiers are not a bug.** `recommend._positional_modifiers` returns `{}` unconditionally
> and says so: *"v1 ships the capped mechanism with no active modifier — bye/handcuff/SOS data is
> not on the $0 tier yet, so fabricating one would violate live-data honesty."* That is the right
> call. What is *not* right is that `config/engine.json` advertises three of them with caps
> (`bye_stack 3.0`, `handcuff_synergy 5.0`, `sos 3.0`) that nothing reads — a reader of the config
> would reasonably conclude they are active. Either implement them (nflverse ships schedules and
> depth charts free, so bye weeks and handcuffs are reachable at $0) or stop advertising them.
>
> **MLV is zero on 78% of rendered rows**, and from **round 6 onward at this seat the BEST
> candidate's MLV is 0.00** — `marginal_lineup_value` is computed against the roster you already
> have, so once your starters are seated an extra body adds nothing to the starting lineup. So ~12
> of 17 picks are ranked with no value term at all, leaving `−λ·σ` (which goes _negative_ in R10–17,
> i.e. tilts to ceiling) as effectively the only live signal. That is arguably the design working as
> written rather than a defect — but nothing has ever verified that the late-round ceiling tilt
> picks sensibly, and it is where `handcuff_synergy` was meant to live.
>
> ### What Tier 5 did NOT do
>
> `config/engine.json` is untouched. The σ-clamp-saturation question (47 of the top 200 sit at
> `VOL_RATIO_MAX`) was **not** taken up — E2 can now decide it, but it is a separate measurement.
> κ (`−0.0044, p=0.9355`) and reliability shrinkage (`−0.0026, p=0.9199`) remain **statistically
> unresolved** at 8 seeds — two of five strategic terms whose sign the harness still cannot call.
> The α = 0 recommendation rests on a simulator and wants owner adoption, not an auto-write. And
> everything Tier 3 flagged still stands: a replay is not a live draft.

> ## 📍 Status — 2026-07-25 (verified against code + a live server on a pristine data dir)
>
> **Tier 1 of the spec-vs-code audit is merged** (PRs #29–#31). Three specified inputs existed but
> never reached the engine; all three now do:
>
> - **Projections are real.** μ was `max(0, 300 − ecr)` — linear in expert rank. `build_projections`
>   now consumes `Capability.EXPECTED_POINTS` (nflverse xEP) through `league/xep.py`, scored under
>   the owner-verified `jaaffl_scoring` map, with `xep_season = season − 1` (nflreadpy **raises**
>   for 2026 — xEP is retrospective). σ is per-player from measured weekly residuals; the flat
>   ~50-for-everyone σ floor is replaced by year-over-year drift measured over two season-pairs
>   (`scripts/measure_projection_sigma.py`). Live board: 447 players, 377 with real xEP,
>   267 distinct σ (was 9), adjacent-μ gaps no longer a constant 1.0.
> - **The engine is on by default.** `jaaffl_precompute_enabled` defaulted to `False` and was
>   absent from `.env`, so a fresh clone could never serve a real pick.
> - **The id crosswalk seeds itself** in precompute. This was worse than "drafted players aren't
>   masked": on a fresh clone ADP resolved **0/179** and ECR **0/508**, so `/recommendation`
>   returned 200 with **`vona = 0.00` on every pick** — a dead opponent model behind a healthy
>   status code. Now 147 ADP / 387 ECR / 4,358 CBS links, seeded automatically.
>
> **Stages 0–6 core are built and green** (backend 474 + shared 86 + extension 93 + web 61; the
> backend suite also passes with all non-loopback network hard-blocked — and the blocker itself is
> verified to fire, so that is not a green light over a no-op). The live **$0 recommendation path
> works end-to-end**: real nflverse player universe → transparent engine → decomposed pick pushed
> to the overlay over `WS /recs/ws`.
>
> **Tier 2 of the audit is merged** (PRs #33–#37) — _trust & honesty on the primary surface_. Five
> places where the overlay looked like it was working:
>
> - **The foot renders.** `footRoster`/`footSync` were created, appended, and never assigned, so
>   sync age and recompute ms had never rendered. `recompute_ms` + a roster summary now ride the
>   `Recommendation` contract (the overlay never receives a `DraftState`, and inferring a roster
>   from pick numbers would synthesize draft structure). Sync age is measured **client-side from
>   receipt** and ticks on a timer — a server-stamped age would freeze when the socket died,
>   reading "fresh" forever over rotting data.
> - **Degraded modes are visible.** Nothing ever called `setStatus("manual")`, so a capture failure
>   still looked fully live. Manual provenance is now latched from the real paste path and outranks
>   a _healthy_ socket (never a degraded one). The `ESTIMATED` badge is keyed off **trust**
>   (`!manualBoard && socketState === "live"`), not the displayed status word — keying it off the
>   word made the caveat vanish on "Reconnecting…", i.e. exactly as things got worse.
> - **`?mc=true` is real.** `use_mc_vona` appeared only on `recommend()`'s signature. Wired to a new
>   `simulate.mc_expected_best_available`, which estimates the same quantity as the analytic form
>   but with a _coupled_ opponent model. Measured (239 players, horizon 2, 2000 rollouts): analytic
>   **p95 9 ms** vs MC **p95 1.14 s** (plan budget <2 s), RB VONA 59.51 → 65.96, and **the two
>   disagree on the #1 pick**. The response now states `vona_method`.
> - **`Why?` works, and pin is its own control.** `whyBtn` had no listener at all; `onPin` rode the
>   Copy handler and the content script never passed it. The panel renders locally from
>   `ScoreComponents` (available even when the backend is not) and shows the score **reconciling to
>   the sum of its terms** — §6.5 made checkable rather than promised — plus σ band, reliability,
>   VONA horizon, `E[best available next]`, and the capped modifiers the bars filter out.
> - **Projection provenance is visible.** `PlayerProjection.sources` never left the backend; ~70
>   ECR-only players (no modeled μ, still the `300 − rank` curve) were indistinguishable from
>   xEP-backed ones. Now on `RecommendedPick.projection_sources`, with one shared rule
>   (`packages/shared/src/provenance.ts`) so overlay and dashboard cannot drift.
>
> **Tier 3 of the audit is merged** (PRs #39–#44) — _draft-night readiness_. Every piece was
> individually tested and none had ever run together on real frames. A complete captured 12×14
> draft now replays end to end — raw NUL-terminated frames → `parse.ts` → `handle_event` →
> `fold_state` → `resolve_pick_ids` → `recommend()` — asserting on the **rendered pick**, not on
> health signals. It found four real defects, none of which any unit test could see:
>
> - **The overlay's VONA was structurally 0.00 on draft night.** No CBS frame names the _viewer's_
>   own team, so `parse.ts` cannot emit `my_team_id`; `opponents._my_overall_picks` then raises and
>   survival degrades to "everyone is available". `GET /recommendation?team_id=` supplies the slot —
>   the `/recs/ws` **push** path that actually feeds the overlay did not. Measured on the real
>   capture at pick 25: with the slot, best pick `mlv 83.00 − E[best avail next] 64.91 = vona 18.09`;
>   without it, `E[best available next]` collapses onto the pick's own MLV and vona is exactly 0.00.
>   Fixed via `JAAFFL_MY_TEAM_ID` **and** a new `Recommendation.survival_basis`, because a degraded
>   0.00 is indistinguishable from a computed one on the wire.
> - **Nothing consumed the `subscribe` snapshot.** Not hypothetical: the owner's 2026-07-25 session
>   began recording mid-draft, so its deltas cover overalls **4–168** and picks 1–3 exist only in
>   that snapshot. Replaying deltas alone left three drafted players unmasked and recommendable.
> - **The manual-paste regex split on hyphenated surnames.** `9. 9 - Jaxon Smith-Njigba, WR, SEA`
>   parsed to `team_id "9 - Jaxon Smith"` / `player_name "Njigba"` — a pick that resolves to nobody
>   and is offered again. The code carried a _reasoned comment_ defending the greedy match; real NFL
>   rosters falsify it. The separator is space-surrounded; a surname hyphen is not.
> - **The fixture redactor corrupted its own goldens.** A real one-character team display name in the
>   new capture made `safety_net`'s substring pass rewrite every occurrence of that letter:
>   `"upcomingorder"` → `"upcominTeam 5order"`, `"state":"picking"` → `"pickinTeam 5"` — the two
>   fields the parser reads for draft order and completion.
>
> Also closed from Tier 2's leftovers: projection provenance now marks the **top-5 rows**, not only
> the best pick and the dashboard banner; and MC-VONA is held off the push path by a
> **structural** (mutation-verified) guard rather than a flaky wall-clock gate.
>
> **Tier 4 of the audit is merged** (PRs #47–#49) — _the E2/E6 calibration harness_. E2 kept
> answering "keep baseline"; it turns out it could not have answered anything else. **Five**
> independent reasons, each measured rather than reasoned:
>
> - **The objective could not reward risk.** `optimal_lineup_value` scores a finished roster on the
>   deterministic μ and never reads `SimContext.sigma` — verified: σ×10, σ=0 and the shipped σ all
>   return `915.200000`. So `λ·σ` moved the ranking away from the very μ the scorer paid out on:
>   λ could be **penalised and never rewarded**. Replaced by sampling each player's season from
>   `N(μ, σ)` — keyed by _player id_, so a player realizes the same season on every roster that
>   holds him (common random numbers) — and scoring by **win probability**: `P(highest realized
season total of the 12)`. That choice is the strategy definition, so the two alternatives are
>   rejected _in tests_: a mean-outcome objective rises monotonically with σ (Jensen — the lineup is
>   re-optimised after the fact) and a floor percentile falls monotonically; either fixes λ's sign
>   globally and leaves the λ **schedule** — whose whole content is that λ flips sign between R1 and
>   R17 — as unmeasurable as before. Plan §3.9 already named the target: playoff odds are "the true
>   objective that λ only proxies". Scoped honestly as a **total-points** championship proxy —
>   `config/league.json` specifies no playoff bracket, and inventing one would breach its
>   `agent_usage_contract`.
> - **The baseline had no risk term at all.** `EngineParams()` defaults `lambda_schedule` to `[]`.
>   E2 used bare `EngineParams()` as its baseline arm and E6 as its "ours" contender, while the live
>   engine loads `config/engine.json` (a five-band schedule, +0.3 → −0.4). **Every published E2
>   baseline number described a vector the engine does not run**, and the pure-MLV control was not
>   testing λ: the arm it was compared against already had none.
> - **The fixture pools could not express any strategic term.** Across 96 (slot × seed ×
>   opponent-field) cells on _both_ `_demo_context()`s, turning κ, α **and** λ off left a
>   **bit-identical roster in 96/96**: `cliff_bonus` was `{}`, σ took two values, there were no
>   K/DST players for `reliability_shrinkage` to shrink, and a flat 40.0 baseline for every position
>   inflated MLV into a band where λ·σ can never re-rank. E2 `--smoke` ran Optuna over a constant.
> - **The simulated agent was not the shipped agent.** `ScoreAgent` hardcoded `candidate_cap=50`
>   (config says 180) and capped by _raw value_ where `recommend.py` caps by _MLV_ — which hid K and
>   DST entirely, so it could not draft a DST at all.
> - **`--eval-seeds` was inert.** Every held-out opponent was deterministic; 1 and 6 eval seeds gave
>   bit-identical numbers. Train/held-out are now disjoint _and_ both stochastic (a new
>   `SoftmaxVbdAgent` trains, `AdpNoiseAgent` moves to held-out).
>
> **What the corrected harness measures** (real xEP pool, 300 players, held-out
> `[NeedBased, AdpNoise]`, 8 seeds, 800 sampled seasons/draft; win prob vs the σ-blind points view):
>
> | vector                        | win prob   | Δ/slot      | min slot | p      | points      | Δ/slot     | p      |
> | ----------------------------- | ---------- | ----------- | -------- | ------ | ----------- | ---------- | ------ |
> | committed baseline            | 0.1077     | —           | —        | —      | 1754.51     | —          | —      |
> | **pure MLV** (κ=α=λ=0, rel=1) | **0.0624** | **−0.0454** | −0.0813  | 0.9998 | **1776.16** | **+21.65** | 0.0002 |
> | λ OFF only                    | 0.0710     | −0.0367     | −0.0758  | 1.0000 | 1749.96     | −4.55      | 1.0000 |
> | κ OFF only                    | 0.0993     | −0.0084     | −0.0886  | 0.8174 | 1771.67     | +17.16     | 0.0049 |
> | α OFF only                    | 0.1077     | +0.0000     | +0.0000  | 1.0000 | 1754.51     | +0.00      | 1.0000 |
> | reliability OFF               | 0.1037     | −0.0040     | −0.0106  | 1.0000 | 1755.00     | +0.49      | 0.8438 |
> | λ DOUBLED                     | 0.0920     | −0.0158     | −0.0789  | 0.9983 | 1750.76     | −3.75      | 0.6333 |
>
> **The 2026-07-25 headline reverses.** Pure-MLV still wins on points (+21.65/slot, p=0.0002 — it
> _strengthens_), but it gives away **42% of its championship probability** (0.1077 → 0.0624,
> p=0.9998). The old harness could only see the points half of that trade, which is exactly why it
> concluded pure-MLV wins. **λ is the load-bearing term**: switching it off costs win probability
> _and_ points, and doubling it also hurts — so the shipped magnitude sits near a local optimum
> rather than at a boundary. κ buys win probability with expected points (−0.0084 for +17.16 pts,
> p=0.82 — a real trade, statistically unresolved at 8 seeds).
>
> **E2 re-run** (30 trials, seed 1, 2 train / 8 eval seeds, 800 draws) tuned to κ=0.736 α=0.430
> λ=[0.228, 0.176, 0.0, −0.358, −0.386], rel K=0.194 DST=0.893 → win prob **0.1077 → 0.1207**,
> `mean_diff +0.0130, p = 0.0029` (significant, which the old harness could never show) but
> `min_slot_diff −0.0014` → **fails the non-negative leg only** → gate says **KEEP baseline**.
> Nothing written; `config/engine.json` stays owner-adopted. Note the tuner keeps λ's sign structure
> and near-shipped magnitudes — that is the first real evidence the shipped schedule is close to
> right. It is also a fair criticism of the gate that a −0.0014 single-slot dip is inside MC noise.
>
> **E6 re-run** (fixture pool, 8 seeds, 800 draws): the previously published "our agent beats
> VBD-only, p=0.0002" **does not reproduce**. On points ours 1588.3 vs vbd_only 1588.2 is a dead
> heat (`+0.1, p=0.5750`); what reproduces at p=0.0002 is ours over **ADP-only** (`+16.4/slot`). On
> win probability ours 0.1226 > adp_only 0.1148 > vbd_only 0.1036, `+0.0190 vs vbd_only, p=0.0320`
> but `min_slot −0.0122`, so the gate still reports no edge. Read plainly: our agent's edge over
> VBD-only is on **championship probability, not points**.
>
> **⚠️ α is structurally inert — on the LIVE path, not just in E2.** The `α OFF only` row above is
> `+0.0000` on both measures because `cliff_bonus` has **293 entries and every one is 0.0**.
> `assign_tiers` yields only **8 tier boundaries across the whole 510-player board** (DST gets a
> single tier, so it has none), with tiers holding 25–54 players; only **102 of 510** players are
> above replacement, so the weakest player of a tier and the best of the next tier are _both_ below
> replacement, where `lineup_value` floors MLV at 0 — every boundary computes `max(0, 0.00 − 0.00)`.
> Consequence: `recommend.py`'s `applied_cliff = α · 0.0` is exactly 0.00 for every live pick, the
> overlay's tier-cliff bar can never be non-zero, and `explain.py`'s "the talent drops off after
> this tier" sentence can never render. **Not fixed here** — the fix is a tiering-policy decision
> (how many tiers, over the draftable subset or the whole board, on ECR or on MLV) that changes live
> recommendations and deserves its own design pass, not a bolt-on to a calibration PR.
> _(→ Tier 5 did that pass. The term is live now, and the measurement says it should be off.)_

> **What Tier 3 did NOT do** (scoped honestly): a **replay is not a live draft.** The pipeline has
> now run end to end on real captured frames, but it has still never run against a LIVE CBS room —
> no draft-night rehearsal against a room that is actually ticking. `ESTIMATED` is still driven by a
> degraded _board_, not the forward-year trigger §6.6 names: `xep_season = season − 1` is
> retrospective, so **no forward-year figure exists to flag** — the trigger would have nothing to
> fire on. `Why?` remains a local decomposition, **not** wired to the Responses API (§6.8); an
> `OPENAI_API_KEY` now exists, but that path adds a network call, a cost, and a latency budget to the
> one surface that must not stall mid-draft, so it wants its own design rather than a Tier-3
> bolt-on. MC-VONA still has **no wall-clock CI gate** at 2000 rollouts — local margin to the 2 s
> budget is ~43%, which a slower runner would eat, so the timing stays a local measurement and CI
> asserts the invariant that actually protects the budget: MC cannot reach the push path at all.
> The **settings-page** parse and `CbsPageSnapshot` remain capture-blocked.
>
> The `feat/post-v1-unblocked` branch adds, all TDD'd + verified: the **`GET /state` board +
> pick-log** endpoint and its **dashboard panels**; the **Stage 7 assistant key-free core**
> (`explain_recommendation` prose over `ScoreComponents` + wired tool `dispatch`); and the **E1
> flex-split** and **E3 projection-validation** calibration tooling (both run live — E1 measured
> RB 12 / WR 0 for 2026, kept as dry-run per owner; E3 persistence 2023→2024 Spearman 0.59).
>
> The stretch **simulation + tuning** subsystem is done too (`engine-stretch` extra): CP-SAT
> `optimize_roster`, the `simulate_draft`/agents/MC-VONA simulator, **E2** tuning (Optuna study +
> no-regression gate, run live on real 2026 data — kept the priors), and the **E6** efficacy
> tournament (our agent beats VBD-only + ADP-only baselines on the fixture pool, p=0.0002).
>
> What remains: the **OpenAI Responses API loop** (needs an owner key), the **manager-tendency
> analytics panel** (value-curve + survival-curve panels are done; manager tendencies await ≥1
> recorded draft to accrue `manager_tendencies` rows), and the deeper **stretch** items (XGBoost
> residual projections, per-manager tendency modeling, a large offline real-data E2 study). The
> record-mode capture session is **DONE** (2026-07-24) and its protocol is decoded. Owner-only
> tasks: [`docs/owner-manual-todo.md`](docs/owner-manual-todo.md).

## Stage 1 — CBS sync layer

- [x] MV3 extension that runs only on CBS fantasy league/draft pages (`apps/extension`)
- [x] Content scripts extract league metadata + live pick events; normalize to shared schema
      _(**capture DONE 2026-07-24** — the network-frame vocabulary is now the REAL decoded CBS
      protocol, see [`docs/research/cbs-draft-protocol.md`](docs/research/cbs-draft-protocol.md):
      NUL-terminated frames, `picks/completed`, `fullstatedelta.order`. DOM-selector and
      settings-page vocabularies remain synthetic — they need a settings/board capture)_
- [x] Stream normalized events to the localhost backend (`jaaffl.api`, `jaaffl.ingest`)
- [x] **Decided against `webRequest`/`declarativeNetRequest`** — replaced by the 3-probe MAIN-world
      capture (WebSocket + `fetch`/XHR monkeypatch, React-fiber framework read, `MutationObserver`
      fallback); cookies API not used

## Stage 2 — Normalize league settings

- [~] Parse CBS roster slots, flex eligibility, scoring rules, team count, keeper/dynasty
  flags, and draft order from the live room / settings pages (`jaaffl.league`)
  _(scoring model + JAAFFL2025 values complete; the live draft-room **order** now reads from
  the real `fullstatedelta.order` — never inferred. The settings-PAGE parse is still
  capture-blocked: the 2026-07-24 session captured draft-room frames, not a settings page)_
- [x] Never assume snake order from league size — read the actual draft board _(enforced in
      `parse.ts` + engine horizon; order comes from the board / manual-paste, never inferred)_
- [x] Persist every league snapshot for self-owned historical analysis _(snapshot-every-settings
      into the warehouse, PR #7)_

## Stage 3 — Data warehouse

- [x] DuckDB + Parquet + SQLite local warehouse (`jaaffl.data`)
- [x] Stable player/team/league IDs and crosswalks (CBS, NFL, FantasyPros, nflverse)
- [ ] **[stretch]** Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if multi-user

## Stage 4 — External data tiers

- [x] Provider protocol + registry (`jaaffl.providers`)
- [x] **$0 prototype tier (default):** nflverse / nflfastR historical stats (free) + **FFC ADP** +
      CBS on-page projections/rankings/ADP read via the extension from the user's session
- [ ] **[opt-in, off by default]** Paid tier: FantasyPros rankings/projections/ADP/news/injuries
      _(disabled stub present; needs an owner key + enable flag)_
- [ ] **[out of scope for the prototype]** Commercial tier: SportsDataIO / Sportradar real-time,
      behind the same interface _(disabled stubs present)_

## Stage 5 — Transparent draft engine

- [x] Exact CBS scoring translation + replacement values + tier breaks (`jaaffl.league`)
- [x] Projection ensemble (`jaaffl.engine.projections`) _(PR #29: **real** nflverse xEP
      (`Capability.EXPECTED_POINTS`) + ECR, both scored under the owner-verified `jaaffl_scoring`
      map. Replaces the `300 − ecr` placeholder. Per-player σ from measured weekly residuals;
      per-position drift σ measured, not chosen (`scripts/measure_projection_sigma.py`). CBS
      on-page projections remain a third source once a settings/board capture exists — that path
      is still unreachable, `cbs_page_snapshots` has 0 rows)_
- [x] Opponent pick-probability model — analytic survival (`jaaffl.engine.opponents`)
- [x] Marginal Lineup Value via Hungarian assignment (`jaaffl.engine.optimize`) — the v1 flex-aware
      optimizer the engine actually uses
- [x] **[stretch]** Draft simulator + agents + MC-VONA (`jaaffl.engine.simulate`) — `simulate_draft`
      (full snake to completion), the behavioral/Score agents, and `simulate_drafts` (E[best
      available]); analytic VONA remains the shipped v1 hot-path default. **`?mc=true` is now
      actually wired** (PR #35): `mc_expected_best_available` replaces the analytic per-position
      `E_π` with a coupled rollout, the response states `vona_method`, no readable draft order
      degrades to analytic _and says so_, and `simulate` imports lazily so the analytic path pays
      nothing. Measured: analytic p95 9 ms · MC p95 1.14 s at 2000 rollouts (budget <2 s)
- [x] **[stretch]** Constrained roster optimization via OR-Tools CP-SAT
      (`jaaffl.engine.optimize::optimize_roster`) — the season-simulator end-state ILP _(needs
      `engine-stretch`)_
- [ ] **[stretch]** Only then: XGBoost residual models, injury-risk calibration, 2027 aging curves
- [x] Treat 2027 outputs as **ESTIMATED** unless a forward-year vendor feed is licensed _(policy
      enforced)_

## Stage 6 — Two-surface UI

- [x] Thin in-page overlay: best pick / next-turn risk / why (`apps/extension` overlay) _(Tier 2,
      PRs #33/#34/#36/#37: the **foot** renders roster + a ticking sync age + recompute ms; the
      **manual-paste** and **ESTIMATED** degraded states are driven from the real paste path;
      **`Why?`** opens a local decomposition that shows the score reconciling to its terms; **pin**
      has its own control writing an advisory `chrome.storage.local` log; ECR-only projections are
      **marked**. Verified in real Chromium via the E4 Playwright spec, not only jsdom)_
- [x] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`) _(live
      recommendation feed, **draft board & pick-log** via `GET /state`, and the **value-curve +
      survival-curve** analytics panels via `GET /analytics` — all done; manager-tendency panel
      deferred until ≥1 recorded draft accrues `manager_tendencies` rows)_
- [x] **AG Grid removed by design** (deep-research: overkill for a 204-cell static board);
      distributions/trends render as **bespoke accessible SVG** (no ECharts dependency)

## Stage 7 — AI assistant (wire early, integrate last)

- [x] Typed function tools for DB queries, league-state summaries, news lookups (`jaaffl.assistant`)
      _(dispatch wired: `explain_recommendation` renders `ScoreComponents` prose via
      `explain_pick`, `league_summary` folds settings+state; `query_warehouse`/`player_news` stay
      NotImplementedError until the LLM loop)_
- [ ] OpenAI Responses API: function calling + file search + optional web search _(the only
      key-gated piece — needs an owner `OPENAI_API_KEY`)_
- [ ] **Text-only.** Voice / Realtime is explicitly out of scope for the prototype (see ADR 0003)

## Cross-cutting

- [~] **Calibration (Track J)** — `jaaffl.calibrate` + `scripts/`: **E1** flex-split
  (`calibrate_flex_split.py`), **E3** projection-validation (`validate_projections.py`), and
  **E2** param tuning (`tune_engine_params.py` — Optuna study + no-regression gate; `--real`
  builds a precompute-backed pool), and the **E6** efficacy tournament (`run_tournament.py` —
  our agent vs VBD-only / ADP-only baselines) all done + run live. **Tier 4 (2026-07-26) rebuilt
  the harness** after the 2026-07-25 re-run showed it could not validate the strategic terms at
  all: the scorer was σ-blind, the baseline carried `lambda_schedule = []`, both fixture pools
  were params-blind in 96/96 cells, the simulated agent was not the shipped agent, and
  `--eval-seeds` was inert. Drafts are now scored by **win probability** over seasons sampled
  from `N(μ, σ)`, against a **disjoint stochastic** held-out field, with the **committed**
  `config/engine.json` as the baseline. The verdict is still **KEEP baseline** — but now for an
  informative reason: the tuned vector is _significantly better_ on win probability
  (`+0.0130/slot, p = 0.0029`) and fails only the non-negative-at-every-slot leg
  (`min_slot −0.0014`, inside MC noise). **Pure-MLV's apparent win reverses**: it gains
  `+21.65 pts/slot` while shedding 42% of its championship probability. Full tables in the
  status block above. ⚠️ **α is still structurally inert, and on the LIVE path** — all 293
  `cliff_bonus` values are 0.0 because tiers are far too coarse (8 boundaries across 510
  players) and fall below replacement where MLV is floored. That is the one calibration
  follow-up still open
- [x] **Projection σ measurement** — `scripts/measure_projection_sigma.py` (read-only) measures the
      per-position year-over-year projection error that anchors the risk band, replacing the flat
      v1 σ placeholder. Also settles season-sum vs rate×17 for μ with two-year-pair evidence
- [ ] Playwright kept for testing / emergency draft-room recovery (not the production path)
- [~] Compliance guardrails enforced in code & docs (see `docs/legal-and-compliance.md`)
