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
