# Tier 9: the engine loses to VBD because of a term that fires in round 3, not round 15 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain and close the E6 inversion — our agent scores more points than plain VBD and wins
the championship 5.5× less often — then repair the one instrument that could have caught it four
tiers earlier: E6 has never been replicated, gates on a leg this project already proved was
sampling noise, and prints its two objectives as unrelated blocks with no combined verdict.

**Architecture:** No engine behaviour change, and none is warranted — the measurement says the fix
is the `lambda_slot_override` config decision Tier 8 already put on the owner's desk, and the one
code-shaped alternative Tier 8 left open is now measured and **worse**. What changes is the
tournament: `run_tournament` scores every objective from ONE simulated draft (it re-simulated per
objective, which is why replicates were never affordable), pools disjoint seed blocks, gates on the
noise-aware leg, and emits a **split verdict** when an agent wins one objective and loses another.
E6 also gains a `--real` pool, sharing one loader with `measure_risk_term.py` rather than copying it.

**Tech Stack:** Python 3.12, pytest, numpy, scipy. Backend + two calibration scripts. No contract or
schema change, no new config key, no new coefficient, no edit to `config/engine.json` or
`config/league.json`.

---

## Why this shape (measured 2026-08-09, fixture pool; real-board slot states verified directly)

### The inversion reproduces exactly

`scripts/run_tournament.py --smoke --seeds 8 --draws 800` — the historical single-block scheme,
seeds 1–8:

```
win probability     vbd_only 0.0984  ·  ours 0.0180  ·  adp_only 0.0026
mean lineup value   ours 1562.1      ·  vbd_only 1517.7  ·  adp_only 1157.8
ours vs vbd_only:   win  -0.0805  p=1.0000        points  +44.3  p=0.0017
```

Digit-for-digit Tier 8. Tier 4's headline — "our edge over VBD-only is on championship probability,
not points" — is exactly inverted.

### Where the gap lives — decomposing the objective's own inputs

12 slots × 8 seeds, 800 sampled seasons, instrumenting what `win_probability` actually consumes:

| agent      | p(win)     | realized season mean | realized **sd** | E[field max] | deterministic points | starting slots filled |
| ---------- | ---------- | -------------------- | --------------- | ------------ | -------------------- | --------------------- |
| ours       | **0.0180** | 1583.1               | **116.3**       | 1920.8       | **1562.1**           | 8.00 / 8              |
| `vbd_only` | **0.0984** | 1609.8               | **169.8**       | 1911.9       | 1517.7               | 7.66 / 8              |
| `adp_only` | 0.0026     | 1334.0               | 158.3           | 1913.1       | 1157.8               | 5.00 / 8              |

Three things fall out at once:

1. **`E[field max]` is the same in all three arms** (1911.9–1920.8, a 9-point spread). "Our picks
   leave a stronger field behind" is **refuted** — it is worth ~9 points against a 337-point gap.
2. **Our roster carries 31% less spread** (116.3 vs 169.8) against a bar every team must clear from
   ~2σ below. That, not the mean, is the whole story: 0.0180 vs 0.0984.
3. **The two objectives disagree about the same rosters.** Deterministic points say we are +44.3
   ahead; realized season mean says we are 26.7 **behind**. Both scorers read the identical rosters.

### The mechanism — `lambda_slot_override` fires in round 3, not round 15

`slot_state_for` classifies a position by how many **open startable slots** it still has:
`0 → SURPLUS`, `1 → LAST_OPEN_STARTABLE`, `≥2 → NORMAL`. On this league's nine starting slots
(QB 1, RB 1, WR 3, WR/RB 1, TE 1, K 1, DST 1) that is degenerate. Verified directly against the real
`resolve_league_settings("cbs-local")`:

```
pick 1, empty roster: open_startable = {QB:1, RB:2, WR:4, TE:1, K:1, DST:1}
  QB   last_open_startable   λ(R1)=+0.40   risk on median σ 106.3 = -42.52
  RB   normal                λ(R1)=+0.30   risk on median σ  59.0 = -17.70
  WR   normal                λ(R1)=+0.30   risk on median σ  43.3 = -12.99
  TE   last_open_startable   λ(R1)=+0.40   risk on median σ  29.2 = -11.68
  K    last_open_startable   λ(R1)=+0.40   risk on median σ  20.0 =  -8.00
  DST  last_open_startable   λ(R1)=+0.40   risk on median σ  25.0 = -10.00
```

**A position with exactly one starting slot can never be `NORMAL`.** QB, TE, K and DST are
`LAST_OPEN_STARTABLE` from pick 1 and `SURPLUS` forever after they are filled; they never pass
through the phase schedule at all. `lambda_schedule` — the knob five tiers have tuned — is
reachable only for RB and WR, and only until their slots fill.

The consequence, traced pick-by-pick on the fixture (seat 5, seed 1, committed config):

```
R3  roster={WR:1, TE:1}   TE te14  μ=173.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
R4  roster={WR:1, TE:2}   TE te19  μ=162.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
```

Picks **three and four** go to the 15th- and 20th-ranked tight ends. Both sit **below** the TE
replacement baseline (176.9). Both have MLV **exactly 0.00** — they cannot crack the starting nine.
They are taken because the surplus ceiling pays **+18.69** for saturated σ against a value signal of
zero, while the RB and WR alternatives — MLV +14 to +42 — are in `NORMAL` state and are _charged_
for their σ by the phase λ.

Tier 8 documented this exact mechanism at R15 and called it an endgame defect
(`risk.py:98`, `ROADMAP.md` "larger than the whole MLV signal in the endgame"). **It is a
whole-draft defect that begins the moment any position's slots are full — round 2 for TE.**
That correction is this tier's finding.

The roster it produces is the worst possible stash: our agent holds **2.92 TEs against a roster
capacity of 3**. A surplus TE can only ever displace our own starting TE — one slot — and TE carries
the lowest σ of any skill position (29.2 vs RB 59.0). `vbd_only` stashes RB/WR, which can slot into
four different places.

### The fix, measured — and the control that stops this being another self-deception

Fixture pool, **5 disjoint seed blocks × 8 seeds × 12 slots, 800 draws**, every arm the shipped
`ScoreAgent` under a different `lambda_slot_override`, all sharing ONE `SimContext` so the sampled
seasons stay common random numbers:

| arm                  | win prob   | Δ vs ours   | p          | points     | Δ vs ours | p          | roster sd | season μ   |
| -------------------- | ---------- | ----------- | ---------- | ---------- | --------- | ---------- | --------- | ---------- |
| **ours (committed)** | 0.0159     | —           | —          | 1560.8     | —         | —          | 118.0     | 1580.0     |
| **`override_off`**   | **0.1162** | **+0.1003** | **0.0002** | **1583.6** | **+22.8** | **0.0002** | 174.7     | **1667.0** |
| `surplus_off`        | 0.0219     | +0.0060     | 0.0007     | 1570.7     | +9.9      | 0.0002     | 115.8     | 1597.2     |
| `floor_off`          | 0.0724     | +0.0566     | 0.0002     | 1553.9     | −6.9      | 0.9451     | **198.2** | 1578.7     |
| `vbd_only`           | 0.0802     | +0.0643     | 0.0002     | 1483.6     | −77.2     | 1.0000     | 163.0     | 1581.4     |

Against the baseline the engine exists to beat:

| arm              | win Δ vs `vbd_only` | min slot | p          | beats?  | points Δ   | min slot | p          | beats?  |
| ---------------- | ------------------- | -------- | ---------- | ------- | ---------- | -------- | ---------- | ------- |
| ours (committed) | −0.0643             | −0.0948  | 1.0000     | **no**  | +77.2      | +36.3    | 0.0002     | yes     |
| **override_off** | **+0.0360**         | −0.0055  | **0.0005** | **YES** | **+100.0** | +58.2    | **0.0002** | **YES** |
| `surplus_off`    | −0.0583             | −0.0939  | 1.0000     | no      | +87.1      | +46.2    | 0.0002     | yes     |
| `floor_off`      | −0.0077             | −0.0477  | 0.8669     | no      | +70.3      | +26.8    | 0.0002     | yes     |

**Zeroing both halves of `lambda_slot_override` removes the inversion completely** and is the first
arm in this project's history to beat `vbd_only` on **both** objectives with replicates.

**The refuting control — and it came out the right way.** The obvious alternative explanation is
"the win-probability objective just loves variance, so any arm that raises σ wins." That is
**refuted by `floor_off`**, which has the **highest** roster sd of any arm (198.2 > 174.7) and wins
**less** than `override_off`, while _losing_ points (p = 0.9451). Win probability is not a monotone
function of spread here. `override_off` wins because it raises realized season mean too — 1667.0
against `floor_off`'s 1578.7.

**The halves are not separable.** `surplus_off` alone buys +0.0060; `floor_off` alone buys +0.0566
but costs points. Together they buy +0.1003. Zeroing one half leaves the other still assigning a
sign opposite to the phase λ, so the term stays non-common-mode. Only removing both restores it.

Roster mix confirms the mechanism end to end (average players per team):

```
ours (committed)   TE 2.92  RB 1.30  WR 2.78     <- TE hoarded to the capacity of 3
override_off       TE 1.00  RB 3.72  WR 2.28     <- exactly one TE; depth moves to RB
vbd_only           TE 1.54  RB 2.38  WR 3.00
```

### Tier 8's open code alternative is now measured, and it loses

Tier 8 listed as unmeasured: "letting all three fall through to the phase schedule is a code change
and a different arm." Measured here on the same design (5 blocks × 8 seeds × 12 slots, 800 draws),
by making both override branches return the phase λ:

| arm            | win prob | Δ vs ours | p      | points | Δ vs ours | p      | vs `vbd_only` (win) | p          | beats?  |
| -------------- | -------- | --------- | ------ | ------ | --------- | ------ | ------------------- | ---------- | ------- |
| `override_off` | 0.1162   | +0.1003   | 0.0002 | 1583.6 | +22.8     | 0.0002 | **+0.0360**         | **0.0005** | **YES** |
| `fall_through` | 0.0842   | +0.0683   | 0.0002 | 1585.6 | +24.7     | 0.0002 | +0.0040             | 0.2119     | no      |

`fall_through` is marginally better on points (+102.0 vs +100.0 against `vbd_only`) and clearly
worse on the championship leg, which it fails to win at all. **So no change to the risk rule is
warranted, and this tier ships no engine behaviour change.** The residual difference is the
early-round tax on single-slot positions: `override_off` removes it, `fall_through` keeps it at the
phase rate, and removing it wins.

### The harness could not have caught this, for a reason with a four-tier pedigree

This is the fifth instance of the project's recurring defect, and the first in the **gate** rather
than the pool or the agent:

- **Tier 4** — both fixture pools were params-blind (96/96 identical rosters).
- **Tier 5** — `alpha` multiplied a `cliff_bonus` map of 293 zeros.
- **Tier 6** — three positional modifiers were priced by nothing.
- **Tier 8** — `ScoreAgent` read neither `lambda_slot_override` nor `punt_guard` (0/60 rosters).
- **Tier 9 — E6 itself.** Three concrete defects:

1. **E6 has never been replicated.** `scripts/run_tournament.py` accepts `--smoke --seeds --draws`
   and nothing else. Every E6 number this project has ever published, Tier 8's inversion included,
   is a **single seed block**. Tier 6 established the ≥5-block rule after proving the min-slot leg
   "was not discriminating, it was sampling"; E2 got `--replicates`, E6 never did.
2. **`run_tournament` gates on the leg Tier 6 discredited.** `tune.py:320` calls
   `promotion_decision(per_slot[ref], values)` with **no `slot_noise`**, so `beats` uses the strict
   point-estimate min-slot leg that "a real, positive effect fails most of the time."
3. **The two objectives are printed as unrelated blocks with no combined verdict.**
   `scripts/run_tournament.py:57` loops over the objectives and prints a paragraph each. Tier 8's
   output said `+44.3 points p=0.0017` and `−0.0805 win prob p=1.0000` eight lines apart, and there
   is no line anywhere that says _these two disagree_. That is the whole reason a 5.5× championship
   deficit sat in the roadmap for a tier as a curiosity rather than a bug.

E6 also **simulates every draft twice**, once per objective, which is exactly why replicates looked
unaffordable. Scoring both objectives from one draft pays for the blocks.

### Measurability first — the hard rule, satisfied before the numbers above were trusted

12 slots × 5 seeds = 60 simulated drafts per arm, rosters compared bit-for-bit:

```
surplus_stash_ceiling  -> 0.0 (floor kept)      rosters changed:  60/60   MEASURABLE
last_startable_slot_floor -> 0.0 (ceiling kept) rosters changed:  60/60   MEASURABLE
both -> 0.0 [the measured arm]                  rosters changed:  60/60   MEASURABLE
```

Tier 8's `test_harness_fidelity.py` pins the _combined_ knob only. The half-arms are load-bearing
for the "not separable" finding above, so each half gets its own case.

### Honest caveats to carry into the docs

- **Every number above is the FIXTURE pool** (178 players, 10 roster slots), not the board. Tier 8's
  `lambda_slot_override` measurement (+0.0745 win / +242.73 points per slot) is the **real** 581-player
  board with 17 rounds. The two point to the same conclusion and **must not be quoted against each
  other** — different pools, different roster, different scale. Task 6 builds the real-board E6 so
  that a directly comparable number exists for the first time.
- **The two objectives bracket bench value; neither is right.** `mean_lineup_value_objective` scores
  the optimal nine under fixed μ, so it values a bench player at exactly **0** — 8 of 17 picks in
  the real league. `roster_season_values` re-optimises the lineup with **perfect hindsight** of the
  realised season, which is an upper bound on option value. On the identical rosters they disagree
  by 78 points about ours vs `vbd_only`. This is surfaced, not fixed: changing the objective would
  supersede every number in the project for a fourth time and belongs in the tier that also gives it
  a week axis.
- **A simulator is not a fact about drafting.** The opponents are behavioural agents, not the eleven
  people in the room. These measurements show the shipped coefficient is catastrophic _against these
  bots on these pools_. They do not show what it does on draft night.
- **Nothing is written to `config/engine.json`.** It is owner-adopted. Tier 8's recommendation to
  zero `lambda_slot_override` is still **OPEN** — verified 2026-08-09, the file still reads
  `{last_startable_slot_floor: 0.4, surplus_stash_ceiling: -0.4}`. Task 8 re-states it with the new
  E6 evidence; it does not apply it.
- **`config/league.json` is untouched.** The bench-eligibility question Tier 8 raised
  (`constitution._BENCH_ELIGIBLE`) is still open and still the owner's; nothing here depends on it.

---

## File structure

| File                                      | Responsibility                    | Change                           |
| ----------------------------------------- | --------------------------------- | -------------------------------- |
| `backend/src/jaaffl/calibrate/tune.py`    | E2/E6 objectives + gates          | add 2 functions; rewrite one     |
| `backend/src/jaaffl/calibrate/pools.py`   | the shared calibration pools      | add `real_sim_context`           |
| `scripts/run_tournament.py`               | the E6 CLI                        | replicates, `--real`, verdict    |
| `scripts/measure_risk_term.py`            | the Tier 8 arms CLI               | drop its private `--real` loader |
| `backend/tests/test_tune.py`              | E6/E2 unit cover                  | modify 1 test, add 4             |
| `backend/tests/test_harness_fidelity.py`  | every tuned knob must move a pick | add 2 cases                      |
| `backend/tests/test_calibrate_pools.py`   | pool cover                        | add 1 test                       |
| `ROADMAP.md`, `docs/owner-manual-todo.md` | the corrected record              | modify                           |

---

### Task 1: `evaluate_agent_objectives` — one simulated draft, every objective

E6 re-simulates the whole tournament per objective. That is pure waste and it is why replicates
looked unaffordable.

**Files:**

- Modify: `backend/src/jaaffl/calibrate/tune.py` (insert after `evaluate_agent`, ~line 184)
- Test: `backend/tests/test_tune.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tune.py`:

```python
def test_evaluate_agent_objectives_simulates_each_draft_once(monkeypatch) -> None:
    """E6 scored the SAME drafts once per objective. Two objectives meant two full tournaments,
    which is why --replicates never looked affordable. One draft, every objective."""
    import jaaffl.calibrate.tune as tune_mod
    from jaaffl.calibrate.tune import evaluate_agent_objectives, mean_lineup_value_objective

    calls = 0
    real = tune_mod.simulate_draft

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(tune_mod, "simulate_draft", counting)
    scores = evaluate_agent_objectives(
        VbdOnlyAgent(),
        _small_ctx(),
        opponents=[VbdOnlyAgent()],
        seeds=[1, 2],
        objectives={"a": mean_lineup_value_objective, "b": mean_lineup_value_objective},
    )
    assert calls == 12 * 2  # slots x seeds -- NOT x objectives
    assert set(scores) == {"a", "b"}
    assert len(scores["a"]) == 12


def test_evaluate_agent_objectives_agrees_with_evaluate_agent() -> None:
    """The one-draft path must be numerically identical to the per-objective path it replaces."""
    from jaaffl.calibrate.tune import (
        evaluate_agent,
        evaluate_agent_objectives,
        mean_lineup_value_objective,
    )

    ctx = _small_ctx()
    single = evaluate_agent(VbdOnlyAgent(), ctx, opponents=[VbdOnlyAgent()], seeds=[1, 2])
    many = evaluate_agent_objectives(
        VbdOnlyAgent(),
        ctx,
        opponents=[VbdOnlyAgent()],
        seeds=[1, 2],
        objectives={"pts": mean_lineup_value_objective},
    )
    assert many["pts"] == single
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k evaluate_agent_objectives`
Expected: FAIL — `ImportError: cannot import name 'evaluate_agent_objectives'`

- [ ] **Step 3: Implement** in `backend/src/jaaffl/calibrate/tune.py`, directly after
      `evaluate_agent`:

```python
def evaluate_agent_objectives(
    agent: DraftAgent,
    ctx: SimContext,
    *,
    opponents: Sequence[DraftAgent],
    seeds: Sequence[int],
    teams: int = 12,
    objectives: Mapping[str, SimObjective | None],
) -> dict[str, list[float]]:
    """Per-slot mean score under EVERY named objective, from ONE simulated draft per (slot, seed).

    :func:`evaluate_agent` scores a single objective, so E6 — which reports two — ran the whole
    tournament twice over the same seeds and threw the first set of rosters away. Two objectives on
    one draft is not an optimisation, it is what makes ``--replicates`` affordable: five disjoint
    blocks at the old cost is exactly the standard Tier 6 set for E2 and E6 never met.

    A ``None`` objective means :func:`mean_lineup_value_objective`, matching
    :func:`evaluate_agent`'s default, so callers can pass the E6 pair as ``{"win probability":
    WinProbabilityObjective(...), "mean lineup value": None}``.
    """
    scored: dict[str, SimObjective] = {
        name: objective or mean_lineup_value_objective for name, objective in objectives.items()
    }
    per_slot: dict[str, list[float]] = {name: [] for name in scored}
    for slot in range(teams):
        totals: dict[str, list[float]] = {name: [] for name in scored}
        for seed in seeds:
            rosters = simulate_draft(
                ctx, our_slot=slot, our_agent=agent, opponents=opponents, seed=seed, teams=teams
            )
            for name, objective in scored.items():
                totals[name].append(objective(rosters, our_slot=slot, ctx=ctx, seed=seed))
        for name, values in totals.items():
            per_slot[name].append(mean(values))
    return per_slot
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k evaluate_agent_objectives`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/calibrate/tune.py backend/tests/test_tune.py
git commit -m "perf(calibrate): score every E6 objective from one simulated draft"
```

---

### Task 2: `tournament_verdict` — say out loud when the two objectives disagree

**Files:**

- Modify: `backend/src/jaaffl/calibrate/tune.py` (insert before `run_tournament`, ~line 294)
- Test: `backend/tests/test_tune.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_tune.py`:

```python
def test_tournament_verdict_flags_a_split_decision() -> None:
    """The defect that let Tier 9's finding sit unexamined for a tier: E6 printed
    '+44.3 points p=0.0017' and '-0.0805 win prob p=1.0000' eight lines apart and never said
    the two disagree. A split is the headline, not a footnote."""
    from jaaffl.calibrate.tune import tournament_verdict

    report = {
        "win probability": {"vs_baselines": {"vbd_only": {"beats": False}}},
        "mean lineup value": {"vs_baselines": {"vbd_only": {"beats": True}}},
    }
    verdict = tournament_verdict(report)
    assert verdict["vbd_only"]["split"] is True
    assert verdict["vbd_only"]["beats_all"] is False
    assert verdict["vbd_only"]["beats_on"] == ["mean lineup value"]
    assert verdict["vbd_only"]["loses_on"] == ["win probability"]


def test_tournament_verdict_reports_a_clean_sweep() -> None:
    from jaaffl.calibrate.tune import tournament_verdict

    report = {
        "win probability": {"vs_baselines": {"vbd_only": {"beats": True}}},
        "mean lineup value": {"vs_baselines": {"vbd_only": {"beats": True}}},
    }
    verdict = tournament_verdict(report)
    assert verdict["vbd_only"]["beats_all"] is True
    assert verdict["vbd_only"]["split"] is False
    assert verdict["vbd_only"]["loses_on"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k tournament_verdict`
Expected: FAIL — `ImportError: cannot import name 'tournament_verdict'`

- [ ] **Step 3: Implement** in `backend/src/jaaffl/calibrate/tune.py`, directly before
      `run_tournament`:

```python
def tournament_verdict(objectives: Mapping[str, Mapping]) -> dict[str, dict]:
    """Per baseline, which objectives the reference agent beats it on and which it loses on.

    E6 reported each objective in its own paragraph and never combined them, so an agent that
    scores MORE points than plain VBD while winning the championship 5.5x LESS often produced two
    unremarkable-looking lines and no alarm. A split decision is the single most informative thing
    a two-objective tournament can say — Tier 5 found ``kappa`` buying championship odds by giving
    up points, and Tier 9 found the shipped ``lambda_slot_override`` doing the reverse — so it is
    computed here rather than left to a reader.

    Objective names are sorted so the output is stable across runs.
    """
    baselines: set[str] = set()
    for report in objectives.values():
        baselines.update(report["vs_baselines"])
    verdict: dict[str, dict] = {}
    for baseline in sorted(baselines):
        beats_on = sorted(
            name
            for name, report in objectives.items()
            if report["vs_baselines"].get(baseline, {}).get("beats")
        )
        loses_on = sorted(name for name in objectives if name not in beats_on)
        verdict[baseline] = {
            "beats_on": beats_on,
            "loses_on": loses_on,
            "split": bool(beats_on and loses_on),
            "beats_all": not loses_on,
        }
    return verdict
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k tournament_verdict`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/calibrate/tune.py backend/tests/test_tune.py
git commit -m "feat(calibrate): E6 states when its two objectives disagree"
```

---

### Task 3: `run_tournament` takes disjoint seed blocks and gates on measured noise

**Files:**

- Modify: `backend/src/jaaffl/calibrate/tune.py:294-332` (replace `run_tournament` entirely)
- Test: `backend/tests/test_tune.py:166-186` (replace
  `test_run_tournament_ranks_our_agent_against_baselines`)

- [ ] **Step 1: Write the failing tests**

Replace `test_run_tournament_ranks_our_agent_against_baselines` in `backend/tests/test_tune.py`
with:

```python
def test_run_tournament_ranks_our_agent_against_baselines() -> None:
    """E6 (efficacy): our ScoreAgent vs VBD-only and ADP-only baselines, each at every slot vs a
    common field. Structure + Wilcoxon on BOTH objectives, not a fixture-pool win claim."""
    from jaaffl.calibrate.tune import run_tournament

    contenders = {
        "score": ScoreAgent(EngineParams()),
        "vbd": VbdOnlyAgent(),
        "adp": AdpNoiseAgent(),
    }
    report = run_tournament(
        _small_ctx(),
        contenders=contenders,
        opponents=[VbdOnlyAgent(), AdpNoiseAgent()],
        seed_blocks=[[1, 2]],
        draws=8,
    )
    assert report["reference"] == "score"
    assert report["blocks"] == 1
    assert set(report["objectives"]) == {"win probability", "mean lineup value"}
    for objective in report["objectives"].values():
        assert set(objective["mean"]) == {"score", "vbd", "adp"}
        assert len(objective["per_slot"]["score"]) == 12
        assert set(objective["vs_baselines"]) == {"vbd", "adp"}
        for comparison in objective["vs_baselines"].values():
            assert {"p_value", "mean_diff", "min_slot_diff", "beats"} <= comparison.keys()
    assert set(report["verdict"]) == {"vbd", "adp"}


def test_run_tournament_pools_disjoint_seed_blocks() -> None:
    """Every E6 number this project has published came from ONE seed block, Tier 8's inversion
    included. Tier 6 proved a single block samples its own noise and gave E2 --replicates; E6
    never got them, so its gate has always used the leg Tier 6 discredited."""
    from jaaffl.calibrate.tune import run_tournament

    report = run_tournament(
        _small_ctx(),
        contenders={"score": ScoreAgent(EngineParams()), "vbd": VbdOnlyAgent()},
        opponents=[VbdOnlyAgent(), AdpNoiseAgent()],
        seed_blocks=[[1, 2], [3, 4]],
        draws=8,
    )
    assert report["blocks"] == 2
    for objective in report["objectives"].values():
        for comparison in objective["vs_baselines"].values():
            assert len(comparison["slot_noise"]) == 12
            assert all(sd >= 0.0 for sd in comparison["slot_noise"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k run_tournament`
Expected: FAIL — `TypeError: run_tournament() got an unexpected keyword argument 'seed_blocks'`

- [ ] **Step 3: Implement** — replace the whole of `run_tournament` in
      `backend/src/jaaffl/calibrate/tune.py`:

```python
def run_tournament(
    ctx: SimContext,
    *,
    contenders: Mapping[str, DraftAgent],
    opponents: Sequence[DraftAgent],
    seed_blocks: Sequence[Sequence[int]],
    teams: int = 12,
    reference: str | None = None,
    objectives: Mapping[str, SimObjective | None] | None = None,
    draws: int = 400,
) -> dict:
    """E6 efficacy proof (design §9.3 / §3.9): every named contender at all 12 slots against a
    common field, compared to ``reference`` (default: the first — our agent) on EVERY objective.

    ``seed_blocks`` are DISJOINT seed blocks, not a flat seed list. Pooling R blocks of S seeds is
    exactly an R*S-seed evaluation AND yields the per-slot sampling SD of the paired difference,
    which is fed to :func:`promotion_decision` as ``slot_noise``. Before Tier 9 this function took a
    flat ``seeds`` and passed no noise, so ``beats`` used the strict point-estimate min-slot leg
    that Tier 6 measured as "not discriminating, it was sampling" — on a single block, which is the
    standard E2 has met since Tier 6 and E6 never has.

    Every objective is scored from ONE simulated draft per (slot, seed); the report carries a
    :func:`tournament_verdict` that names the objectives the reference wins and loses on, because
    an agent can beat a baseline on points while losing to it on championship probability and E6
    used to print those as two unrelated paragraphs.
    """
    scored: Mapping[str, SimObjective | None] = objectives or {
        "win probability": WinProbabilityObjective(n_draws=draws),
        "mean lineup value": None,
    }
    # name -> agent -> block -> per-slot scores
    raw: dict[str, dict[str, list[list[float]]]] = {name: {} for name in scored}
    for agent_name, agent in contenders.items():
        for name in scored:
            raw[name][agent_name] = []
        for block in seed_blocks:
            block_scores = evaluate_agent_objectives(
                agent, ctx, opponents=opponents, seeds=block, teams=teams, objectives=scored
            )
            for name, values in block_scores.items():
                raw[name][agent_name].append(values)

    ref = reference or next(iter(contenders))
    report: dict[str, dict] = {}
    for name in scored:
        pooled = {
            agent_name: pooled_per_slot(blocks)[0] for agent_name, blocks in raw[name].items()
        }
        ref_blocks = raw[name][ref]
        vs_baselines: dict[str, dict] = {}
        for agent_name, blocks in raw[name].items():
            if agent_name == ref:
                continue
            # The noise that matters is the sd of the PAIRED difference, per baseline -- not a
            # single number for the objective. Pooling it across baselines would average away the
            # very heterogeneity the second leg is supposed to test against.
            diffs = [
                [r - b for r, b in zip(ref_block, block, strict=True)]
                for ref_block, block in zip(ref_blocks, blocks, strict=True)
            ]
            _, slot_noise = pooled_per_slot(diffs)
            decision = promotion_decision(
                pooled[ref],
                pooled[agent_name],
                slot_noise=slot_noise if len(seed_blocks) > 1 else None,
            )
            vs_baselines[agent_name] = {
                "mean_diff": decision["mean_diff"],
                "min_slot_diff": decision["min_slot_diff"],
                "p_value": decision["p_value"],
                "beats": decision["promote"],
                "slot_noise": slot_noise,
            }
        report[name] = {
            "per_slot": pooled,
            "mean": {agent_name: mean(values) for agent_name, values in pooled.items()},
            "vs_baselines": vs_baselines,
        }
    return {
        "reference": ref,
        "blocks": len(seed_blocks),
        "objectives": report,
        "verdict": tournament_verdict(report),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/src/jaaffl/calibrate/tune.py backend/tests/test_tune.py
git commit -m "fix(calibrate): E6 pools disjoint seed blocks and gates on measured noise"
```

---

### Task 4: `real_sim_context` — one `--real` loader, not two

`scripts/measure_risk_term.py::_real_context` is the only precompute-backed `SimContext` builder.
E6 needs it too. Copying it would be the exact defect Tier 8 removed from the risk rule.

**Files:**

- Modify: `backend/src/jaaffl/calibrate/pools.py` (append at end of file)
- Modify: `scripts/measure_risk_term.py:50-74` (delete `_real_context`, call the shared one)
- Test: `backend/tests/test_calibrate_pools.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_calibrate_pools.py`:

```python
def test_real_sim_context_is_importable_without_touching_the_network() -> None:
    """The --real pool loader lived in scripts/measure_risk_term.py, so E6 would have had to copy
    it. One rule implemented twice diverges -- Tier 8 removed exactly that from the risk rule.
    Importing must not pull nflverse or open the warehouse; only calling it may."""
    from jaaffl.calibrate.pools import real_sim_context

    assert callable(real_sim_context)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_calibrate_pools.py -q -k real_sim_context`
Expected: FAIL — `ImportError: cannot import name 'real_sim_context'`

- [ ] **Step 3: Implement** — append to `backend/src/jaaffl/calibrate/pools.py`:

```python
def real_sim_context(cap: int = 300, *, per_position: int = 20) -> SimContext:
    """A precompute-backed :class:`SimContext` — real projections + FFC ADP. **NETWORK + slow.**

    Lives here rather than in a script because two calibration CLIs need it (E6 and the Tier 8
    risk-term arms) and the one thing this project has learned five times is that a rule
    implemented twice diverges silently. Every heavy import is function-local, so importing this
    module stays free.

    Capped by :func:`~jaaffl.calibrate.tune.cap_sim_pool`, which keeps the top ``per_position`` of
    each position as well as the top ``cap`` by value — a plain value cap drops K and DST.
    """
    import sys

    from jaaffl.calibrate.tune import cap_sim_pool, sim_context_from_draft_context
    from jaaffl.config import get_settings
    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import build_registry_context_source
    from jaaffl.providers.nflverse import NflreadpyProvider

    settings = get_settings()
    if not settings.jaaffl_season:
        raise SystemExit("[pools] set jaaffl_season to build the real pool")
    warehouse = Warehouse(settings.jaaffl_data_dir)
    crosswalk = Crosswalk(warehouse.app_sqlite)
    print("[pools] building the real DraftContext ...", file=sys.stderr)
    NflreadpyProvider(crosswalk=crosswalk).seed_crosswalk()
    source = build_registry_context_source(
        settings, warehouse=warehouse, crosswalk=crosswalk, season=settings.jaaffl_season
    )
    dc = source(settings.jaaffl_league_id)
    if dc is None:
        raise SystemExit("[pools] precompute returned no context")
    ctx = sim_context_from_draft_context(dc)
    print(f"[pools] real pool: {len(ctx.value)} players -> top {cap}", file=sys.stderr)
    return cap_sim_pool(ctx, cap, per_position=per_position)
```

- [ ] **Step 4: Point `measure_risk_term.py` at it** — in `scripts/measure_risk_term.py`, delete
      the whole `_real_context` function (lines 53–74) and its now-unused imports, then change the
      context line in `main`:

```python
    ctx = (
        real_sim_context(args.pool_cap)
        if (args.real and not args.smoke)
        else demo_sim_context()
    )
```

and update the import at the top:

```python
from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context, real_sim_context
```

Then delete the now-unused imports from that file: `sys` stays (it is used by the progress prints),
`Path` stays (used by `--out`), and `SimContext` and `get_settings` become unused — remove
`SimContext` from the `jaaffl.engine.simulate` import list and `get_settings` from the
`jaaffl.config` import list.

- [ ] **Step 5: Run to verify**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_calibrate_pools.py -q`
Expected: PASS

Run: `.venv/Scripts/python.exe scripts/measure_risk_term.py --smoke --eval-seeds 2 --replicates 1 --draws 32`
Expected: exit 0, prints the arms table (the `--smoke` path must still work after the edit)

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/calibrate/pools.py backend/tests/test_calibrate_pools.py scripts/measure_risk_term.py
git commit -m "refactor(calibrate): one --real pool loader, shared by both calibration CLIs"
```

---

### Task 5: the E6 CLI — `--replicates`, `--real`, and a verdict line

**Files:**

- Modify: `scripts/run_tournament.py` (rewrite `main`, add `build_parser`)
- Test: `backend/tests/test_tune.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tune.py`:

```python
def _load_e6_script():
    """Import scripts/run_tournament.py by path -- it is not an installed package."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "run_tournament.py"
    spec = importlib.util.spec_from_file_location("e6_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e6_cli_exposes_replicates_and_a_real_pool() -> None:
    """E6 accepted only --smoke/--seeds/--draws, so every E6 number ever published is a single
    seed block -- the standard E2 has met since Tier 6."""
    args = _load_e6_script().build_parser().parse_args(
        ["--smoke", "--seeds", "8", "--replicates", "5"]
    )
    assert args.replicates == 5
    assert args.seeds == 8
    assert hasattr(args, "real")
    assert hasattr(args, "pool_cap")


def test_e6_cli_runs_multiple_blocks_end_to_end() -> None:
    """The smallest possible real run: the whole script path, two disjoint blocks."""
    module = _load_e6_script()
    assert module.main(["--smoke", "--seeds", "1", "--draws", "8", "--replicates", "2"]) == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k e6_cli`
Expected: FAIL — `AttributeError: module 'e6_script' has no attribute 'build_parser'`

- [ ] **Step 3: Implement** — replace `scripts/run_tournament.py` below the imports with:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="E6: offline efficacy tournament.")
    parser.add_argument("--smoke", action="store_true", help="Fixture pool (default).")
    parser.add_argument("--real", action="store_true", help="Precompute pool (network, slow).")
    parser.add_argument("--seeds", type=int, default=8, help="Draft seeds per block.")
    parser.add_argument(
        "--replicates",
        type=int,
        default=5,
        help=(
            "Evaluate over N DISJOINT seed blocks. >1 measures the gate's own per-slot noise and "
            "switches the min-slot leg from a point estimate to a significance test. Every E6 "
            "number published before Tier 9 used a single block."
        ),
    )
    parser.add_argument("--draws", type=int, default=800, help="Sampled seasons per scored draft.")
    parser.add_argument("--pool-cap", type=int, default=300, help="--real pool size cap.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = real_sim_context(args.pool_cap) if (args.real and not args.smoke) else demo_sim_context()
    pool = "real" if (args.real and not args.smoke) else "fixture"

    # The vector the engine RUNS. E6 used bare EngineParams(), whose empty lambda_schedule made
    # "ours" a risk-free agent — so the tournament never tested the shipped risk schedule at all.
    params = committed_engine_params()
    contenders = {
        "ours": ScoreAgent(params),
        "vbd_only": VbdOnlyAgent(),
        "adp_only": AdpNoiseAgent(),
    }
    field = [SoftmaxVbdAgent(), NeedBasedAgent()]
    # Disjoint blocks on the same 1001+ scheme E2 and measure_risk_term.py use, so the three CLIs
    # are comparable to each other. NOT comparable to any pre-Tier-9 E6 number, which used
    # seeds 1..N in a single block.
    blocks = [
        list(range(1001 + i * 1000, 1001 + i * 1000 + args.seeds))
        for i in range(max(1, args.replicates))
    ]

    report = run_tournament(
        ctx,
        contenders=contenders,
        opponents=field,
        seed_blocks=blocks,
        draws=args.draws,
    )
    print(
        f"[E6] {pool} pool ({len(ctx.value)} players) · {len(blocks)} blocks x {args.seeds} seeds "
        f"x 12 slots · {args.draws} sampled seasons/draft"
    )
    for label, objective in report["objectives"].items():
        digits = 4 if label == "win probability" else 1
        print(f"[E6] {label} (per agent, across 12 slots):")
        for name, value in sorted(objective["mean"].items(), key=lambda kv: -kv[1]):
            print(f"[E6]   {name:9s} {value:>9.{digits}f}")
        for name, cmp in objective["vs_baselines"].items():
            verdict = "BEATS" if cmp["beats"] else "no significant edge over"
            print(
                f"[E6]   ours {verdict} {name}: mean_diff={cmp['mean_diff']:+.{digits}f}  "
                f"min_slot_diff={cmp['min_slot_diff']:+.{digits}f}  p={cmp['p_value']:.4f}"
            )
            if len(blocks) > 1 and cmp["slot_noise"]:
                noise = sorted(cmp["slot_noise"])
                print(
                    f"[E6]     per-slot noise of that paired diff over {len(blocks)} blocks: "
                    f"median {noise[len(noise) // 2]:.{digits}f}  max {noise[-1]:.{digits}f}"
                )

    print("[E6] VERDICT:")
    for baseline, verdict in report["verdict"].items():
        if verdict["beats_all"]:
            print(f"[E6]   ours BEATS {baseline} on BOTH objectives.")
        elif verdict["split"]:
            print(
                f"[E6]   ⚠ SPLIT vs {baseline}: ours WINS on {', '.join(verdict['beats_on'])} "
                f"and LOSES on {', '.join(verdict['loses_on'])}. A one-sided number is how this "
                f"project keeps fooling itself — do not quote either leg alone."
            )
        else:
            print(f"[E6]   ours does NOT beat {baseline} on any objective.")
    if pool == "fixture":
        print("[E6] fixture pool; a full efficacy claim needs --real.")
    return 0
```

and replace the import block at the top of the file (keeping `from __future__ import annotations`
and `import argparse`, both of which the new code still needs) with:

```python
from __future__ import annotations

import argparse

from jaaffl.calibrate.pools import committed_engine_params, demo_sim_context, real_sim_context
from jaaffl.calibrate.tune import run_tournament
from jaaffl.engine.simulate import (
    AdpNoiseAgent,
    NeedBasedAgent,
    ScoreAgent,
    SoftmaxVbdAgent,
    VbdOnlyAgent,
)
```

`WinProbabilityObjective` is no longer imported here — `run_tournament` builds the objective pair
itself from `--draws`, so the CLI cannot accidentally construct a second one and break the common
random numbers.

Also update the module docstring's usage block to:

```
    .venv/Scripts/python.exe scripts/run_tournament.py --smoke --seeds 8 --replicates 5
    .venv/Scripts/python.exe scripts/run_tournament.py --real --seeds 8 --replicates 5
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tune.py -q -k e6_cli`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_tournament.py backend/tests/test_tune.py
git commit -m "feat(e6): replicate blocks, a --real pool, and a split-decision verdict"
```

---

### Task 6: `test_harness_fidelity.py` — each HALF of the override must move a pick

The "the halves are not separable" finding rests on measuring each half alone. Tier 8's guard pins
only the combined knob, so those two arms are currently unverified.

**Files:**

- Modify: `backend/tests/test_harness_fidelity.py:61-89` (add two parametrize cases)

- [ ] **Step 1: Add the failing-if-blind cases**

Insert into the `@pytest.mark.parametrize` list in `backend/tests/test_harness_fidelity.py`,
directly after the existing `lambda_slot_override` entry:

```python
        # Tier 9: the two halves are measured SEPARATELY (surplus alone buys +0.0060 win prob,
        # floor alone +0.0566 but -6.9 points, both together +0.1003), so each half needs its own
        # visibility guard. The combined case above cannot catch a half going blind.
        (
            "lambda_slot_override.surplus_stash_ceiling",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": 0.4,
                    "surplus_stash_ceiling": 0.0,
                }
            },
        ),
        (
            "lambda_slot_override.last_startable_slot_floor",
            {
                "lambda_slot_override": {
                    "last_startable_slot_floor": 0.0,
                    "surplus_stash_ceiling": -0.4,
                }
            },
        ),
```

- [ ] **Step 2: Extend the module docstring** — append to the bullet list in
      `backend/tests/test_harness_fidelity.py`:

```
* **Tier 9** — E6 itself. ``scripts/run_tournament.py`` had no ``--replicates``, so every E6 number
  this project has published (including Tier 8's 5.5x championship inversion) came from a SINGLE
  seed block, and ``run_tournament`` passed no ``slot_noise`` so its ``beats`` gate used the strict
  min-slot leg Tier 6 measured as "not discriminating, it was sampling". The engine defect it hid —
  ``lambda_slot_override`` paying +18.69 for a zero-MLV tight end in ROUND 3, not round 15 — was
  visible in the numbers for a whole tier.
```

- [ ] **Step 3: Run to verify all four knobs are measurable**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_harness_fidelity.py -q`
Expected: PASS (6 passed — 4 pre-existing + 2 new)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_harness_fidelity.py
git commit -m "test(harness): each half of lambda_slot_override must move a pick on its own"
```

---

### Task 7: run the measurements the docs will quote

**Files:** none modified — this task produces the numbers Task 8 records.

- [ ] **Step 1: Fixture E6, replicated, on the repaired CLI**

Run (redirect and poll; piping to `tail` buffers and shows nothing until exit):

```bash
.venv/Scripts/python.exe scripts/run_tournament.py --smoke --seeds 8 --replicates 5 --draws 800 > e6_fixture.txt 2>&1
```

Expected: exit 0. Expect `ours` to LOSE the win-probability leg to `vbd_only` and WIN the points
leg, and the verdict block to print the `⚠ SPLIT` line. That split line is the deliverable — it is
what E6 could not say before.

- [ ] **Step 2: Real-board E6 — the number that has never existed**

Do NOT run this concurrently with any other `--real` job; they contend on the shared
`app.sqlite` crosswalk. Budget 30–60 minutes.

```bash
.venv/Scripts/python.exe scripts/run_tournament.py --real --seeds 8 --replicates 5 --draws 800 --pool-cap 300 > e6_real.txt 2>&1
```

Expected: exit 0. Record the per-agent means, both `vs_baselines` blocks, the per-slot noise, and
the verdict. **Label every number `real pool`** — it is not comparable to the fixture numbers.

- [ ] **Step 3: Record both outputs** into the Tier 9 measurement notes for Task 8. Do not commit
      the raw `.txt` files; they are working artifacts.

---

### Task 8: the corrected record

**Files:**

- Modify: `ROADMAP.md` (insert a Tier 9 block immediately after the Legend line, before the Tier 8
  block at line 16)
- Modify: `docs/owner-manual-todo.md` (§1 — re-state the OPEN `lambda_slot_override` decision with
  the E6 evidence; §1b — correct "endgame" to "from round 3")

- [ ] **Step 1: Write the ROADMAP Tier 9 status block**

Insert immediately after the `Legend:` line in `ROADMAP.md` (before the Tier 8 heading at line 16).
The full text follows. Every number in it is already measured **except** the two marked
`<<from e6_real.txt>>`, which come from Task 7 Step 2 and must be substituted before committing —
if that run has not happened, the section headed "The real board" is deleted rather than guessed.

````markdown
## 📍 Status — 2026-08-09 · Tier 9 (the engine loses to VBD because of a term that fires in round 3)

> **Tier 9 of the audit is merged** (PR #NN). Tier 8 left the most serious number in the project on
> the table: our agent scores MORE points than plain VBD and wins the championship **5.5× less
> often**. Tier 9 reproduces it digit-for-digit, finds the cause, and finds that the instrument that
> reported it could never have chased it.

### The gap is variance, and the field is innocent

Decomposing what `win_probability` actually consumes — 12 slots × 8 seeds, 800 sampled seasons:

| agent      | p(win)     | realized season mean | realized **sd** | E[field max] | deterministic points | slots filled |
| ---------- | ---------- | -------------------- | --------------- | ------------ | -------------------- | ------------ |
| ours       | **0.0180** | 1583.1               | **116.3**       | 1920.8       | **1562.1**           | 8.00 / 8     |
| `vbd_only` | **0.0984** | 1609.8               | **169.8**       | 1911.9       | 1517.7               | 7.66 / 8     |
| `adp_only` | 0.0026     | 1334.0               | 158.3           | 1913.1       | 1157.8               | 5.00 / 8     |

`E[field max]` is the same in all three arms (a 9-point spread against a 337-point gap), so **"our
picks leave a stronger field behind" is refuted.** Our roster simply carries 31% less spread against
a bar every team must clear from ~2σ below. The two objectives also disagree about the identical
rosters: deterministic points say we are +44.3 ahead, realized season mean says we are 26.7 behind.

### 🔴 THE FINDING — `lambda_slot_override` is not an endgame term. It fires in round 3.

`slot_state_for` classifies a position by its **open startable slots**: `0 → SURPLUS`,
`1 → LAST_OPEN_STARTABLE`, `≥2 → NORMAL`. On this league's nine slots that is degenerate — verified
against the real `resolve_league_settings("cbs-local")`:

```
pick 1, empty roster: open_startable = {QB:1, RB:2, WR:4, TE:1, K:1, DST:1}
  QB   last_open_startable   λ(R1)=+0.40   risk on median σ 106.3 = -42.52
  RB   normal                λ(R1)=+0.30   risk on median σ  59.0 = -17.70
  TE   last_open_startable   λ(R1)=+0.40   risk on median σ  29.2 = -11.68
```

**A position with exactly one starting slot can never be `NORMAL`.** QB, TE, K and DST are
`LAST_OPEN_STARTABLE` from pick 1 and `SURPLUS` forever after they are filled. `lambda_schedule` —
the knob five tiers have tuned — is reachable only for RB and WR, and only until their slots fill.

Traced pick-by-pick (fixture, seat 5, seed 1, committed config):

```
R3  roster={WR:1, TE:1}   TE te14  μ=173.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
R4  roster={WR:1, TE:2}   TE te19  μ=162.6  MLV=+0.00  λ=-0.40  σ=46.72  risk=+18.69  score=+21.33  <- TAKEN
```

Picks **three and four** go to the 15th- and 20th-ranked tight ends — both below TE replacement,
both MLV exactly 0.00, both unable to crack the starting nine. The surplus ceiling pays **+18.69**
for saturated σ against a value signal of zero, while the RB/WR alternatives (MLV +14 to +42) sit in
`NORMAL` and are _charged_ for theirs. The engine ends up holding **2.92 tight ends against a roster
capacity of 3** — the worst possible stash, since a surplus TE can displace only our own starting TE
and TE carries the lowest σ of any skill position.

**Tier 8 measured this term correctly and described its mechanism wrongly**, as an endgame defect
(`risk.py`, and this roadmap's Tier 8 block). Direction and significance stand; the timing does not.

### The fix, and the control that keeps it honest

Fixture pool, 5 disjoint blocks × 8 seeds × 12 slots, 800 draws, one shared `SimContext`:

| arm                  | win prob   | Δ vs ours   | p          | points     | Δ vs ours | p          | roster sd | season μ   |
| -------------------- | ---------- | ----------- | ---------- | ---------- | --------- | ---------- | --------- | ---------- |
| **ours (committed)** | 0.0159     | —           | —          | 1560.8     | —         | —          | 118.0     | 1580.0     |
| **`override_off`**   | **0.1162** | **+0.1003** | **0.0002** | **1583.6** | **+22.8** | **0.0002** | 174.7     | **1667.0** |
| `surplus_off`        | 0.0219     | +0.0060     | 0.0007     | 1570.7     | +9.9      | 0.0002     | 115.8     | 1597.2     |
| `floor_off`          | 0.0724     | +0.0566     | 0.0002     | 1553.9     | −6.9      | 0.9451     | **198.2** | 1578.7     |
| `vbd_only`           | 0.0802     | +0.0643     | 0.0002     | 1483.6     | −77.2     | 1.0000     | 163.0     | 1581.4     |

Against the baseline the engine exists to beat, `override_off` is the **first arm in this project's
history to win both legs against `vbd_only` with replicates**: win **+0.0360** (p=0.0005), points
**+100.0** (p=0.0002). The committed config loses the win leg by −0.0643 (p=1.0000).

**The refuting control came out the right way.** The obvious alternative — "the objective just loves
variance, so any high-σ arm wins" — is refuted by `floor_off`, which has the **highest** roster sd
of any arm (198.2 > 174.7) and wins **less** while _losing_ points (p=0.9451). `override_off` wins
because it raises realized season mean too (1667.0 vs 1578.7). **The halves are also not
separable:** +0.0060 and +0.0566 alone, +0.1003 together.

Roster mix tells the same story: committed `TE 2.92 · RB 1.30`; `override_off` `TE 1.00 · RB 3.72`.

### ⚠️ A Tier 8 open item is closed: the code alternative is measured, and it loses

Tier 8 listed "letting all three fall through to the phase schedule" as an unmeasured arm. Measured
on the same design: win 0.0842 (+0.0683 vs ours, p=0.0002), points 1585.6 (+24.7, p=0.0002) — but
against `vbd_only` only **+0.0040** on win probability at **p=0.2119**, i.e. it does not beat it.
Zeroing the config is strictly better on the leg that matters. **Tier 9 therefore ships no engine
behaviour change**, and the recommendation stays exactly where Tier 8 left it: with the owner.

### The instrument, again — E6 has never been replicated

Fifth instance of this project's recurring defect, and the first in the **gate** rather than the
pool or the agent:

1. `scripts/run_tournament.py` accepted `--smoke --seeds --draws` and nothing else, so **every E6
   number ever published — Tier 8's inversion included — is a single seed block.** Tier 6 set the
   ≥5-block standard after proving the min-slot leg "was not discriminating, it was sampling"; E2
   got `--replicates`, E6 never did.
2. `run_tournament` passed **no `slot_noise`**, so its `beats` gate used exactly that discredited
   leg.
3. The two objectives were printed as unrelated paragraphs with **no combined verdict**. Tier 8's
   output said `+44.3 points p=0.0017` and `−0.0805 win prob p=1.0000` eight lines apart and nothing
   anywhere said _these disagree_.

E6 also re-simulated every draft once per objective, which is why replicates looked unaffordable.
Fixed: one draft scores every objective, blocks are pooled, the gate reads measured noise, and a
`⚠ SPLIT` verdict is printed whenever the reference wins one objective and loses another.
`tests/test_harness_fidelity.py` now pins each **half** of `lambda_slot_override` separately
(60/60 rosters move for each), because the "not separable" finding rests on measuring them alone.

### The real board <<from e6_real.txt>>

`scripts/run_tournament.py --real --seeds 8 --replicates 5 --draws 800 --pool-cap 300` — the first
precompute-backed E6 this project has run. <<substitute the per-agent means, both `vs_baselines`
blocks and the verdict here; label them `real pool` and do NOT compare their magnitudes to the
fixture numbers above>>

### ⚠️ Surfaced, not fixed: `mean_lineup_value_objective` is bench-blind

It scores the optimal nine under fixed μ, so a bench player is worth exactly **0** — 8 of 17 picks
in this league. `roster_season_values` re-optimises the lineup with **perfect hindsight** of the
realized season, an upper bound on option value. On identical rosters they disagree by 78 points
about ours vs `vbd_only`. The two bracket bench value; neither is right. Changing the objective
would supersede every number in the project a fourth time and belongs in the tier that also gives it
a week axis.

### What Tier 9 did NOT do

- **No engine behaviour changed.** `engine/risk.py`, `engine/recommend.py` and `engine/simulate.py`
  are untouched. `config/engine.json` and `config/league.json` are untouched. The
  `lambda_slot_override` recommendation is still **OPEN** with the owner (`docs/owner-manual-todo.md`
  §1), and as of 2026-08-09 the file still reads `0.4 / −0.4`.
- **E2 was not re-run.** Tier 8's tuned vector bought +0.0017 against a knob worth +0.0745 that
  `run_study` cannot search; re-running the study before that knob is settled would measure noise
  around a decision nobody has made.
- **No week axis.** `sample_season_outcomes` still draws one independent season total per player, so
  `bye_stack`, `handcuff_synergy` and `sos` remain unmeasurable and unimplemented.
- **The perfect-hindsight lineup re-optimisation is recorded, not changed.**
- **A simulator is not a fact about drafting.** These numbers show the shipped coefficient is
  catastrophic against these bots on these pools. They do not show what it does on draft night, and
  the opponents are still behavioural agents rather than the eleven people in the room.

### ⚠️ What is superseded

- Tier 8's **"endgame"** framing of `lambda_slot_override`: the mechanism is corrected to round 3
  onward. Its direction, significance and recommendation are confirmed, on a second pool.
- Tier 8's "the remove-the-branches variant is unmeasured": measured, and refuted as an improvement.
- **Every pre-Tier-9 E6 number.** All were single-block, and the CLI now uses the 1001+ disjoint-block
  seed scheme E2 and `measure_risk_term.py` use, so old and new E6 figures are not comparable.
````

- [ ] **Step 2: Update `docs/owner-manual-todo.md` §1**

The `lambda_slot_override` recommendation is **still open** — verified 2026-08-09,
`config/engine.json` still reads `0.4 / -0.4`. Re-state it (do not assume it was acted on) and add
the E6 evidence: with the setting off, the engine goes from **losing** to plain VBD on championship
probability to **beating** it on both measures. Keep the "nothing has been changed" framing and the
two-line diff.

- [ ] **Step 3: Correct §1b's mechanism**

§1b currently describes the late-round bonus as a late-round problem. Add a short correction: the
same setting is spending **round 3 and round 4** picks on tight ends the roster cannot start. Keep
the 30-second rule unchanged — it is still good advice.

- [ ] **Step 4: Format and verify**

```bash
pnpm exec prettier --write ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans/2026-08-09-tier9-e6-inversion-and-tournament-replicates.md
```

Expected: files reformatted in place. **Commit the reformatted files** — Tier 8's CI failed because
a prettier fix was left staged out of its commit while local `pnpm lint` passed against an
already-fixed working tree.

- [ ] **Step 5: Commit**

```bash
git add ROADMAP.md docs/owner-manual-todo.md docs/superpowers/plans/
git commit -m "docs: Tier 9 — the override fires in round 3, and E6 has never been replicated"
```

---

### Task 9: full verification, then the PR

- [ ] **Step 1: Run every gate CI runs**

```bash
.venv/Scripts/python.exe -m pytest backend -q
```

Expected: all pass (632 passed + the new tests, 2 skipped).

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

Expected: exit 0, no diff (no contract changed).

```bash
node scripts/gen-overlay-tokens.mjs --check
```

Expected: exit 0.

```bash
.venv/Scripts/python.exe scripts/preflight.py
```

Expected: exit 0, 581 players, all 6 startable positions fillable.

- [ ] **Step 2: Drive the real FastAPI surface**

Use the project `verify` skill (`.claude/skills/verify`). Nothing in `backend/src/jaaffl` changed
behaviourally, so this is a regression check that the calibration refactor did not disturb the API.

- [ ] **Step 3: Request code review**

Use `superpowers:requesting-code-review`. Tier 8 skipped this step; do not.

- [ ] **Step 4: Push, open the PR, wait for all 4 checks, squash-merge**

```bash
git push -u origin tier9/e6-inversion-and-tournament-replicates
```

PR body carries the arms table, the `floor_off` control, the fall-through result, both E6 runs with
their pool labels, and the explicit statement that `config/engine.json` was not touched and the
Tier 8 recommendation is still the owner's to make.

Wait for **Backend**, **Node 22**, **Node 24** and **Playwright** to pass, then squash-merge and
delete the branch, then `git checkout main && git pull`.

---

## The config change this tier recommends — proposed, NOT applied

`config/engine.json` is owner-adopted. This is a diff for the owner to accept or reject, and Tier 8
already put the same change on the table; Tier 9 adds the E6 evidence.

```diff
   "lambda_slot_override": {
-    "last_startable_slot_floor": 0.4,
-    "surplus_stash_ceiling": -0.4
+    "last_startable_slot_floor": 0.0,
+    "surplus_stash_ceiling": 0.0
   },
```

| evidence                                   | win probability    | expected points    | both legs? |
| ------------------------------------------ | ------------------ | ------------------ | ---------- |
| Tier 8, **real** board, 5 blocks × 8 seeds | +0.0745 (p=0.0002) | +242.73 (p=0.0002) | YES        |
| Tier 9, **fixture** E6, 5 blocks × 8 seeds | +0.1003 (p=0.0002) | +22.8 (p=0.0002)   | YES        |
| Tier 9, fixture E6, vs `vbd_only`          | +0.0360 (p=0.0005) | +100.0 (p=0.0002)  | YES        |

Different pools; the magnitudes are not comparable to each other, only the direction and the
significance are. A simulator is not a fact about drafting.
