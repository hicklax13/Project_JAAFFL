# JAAFFL — Optimal Live Draft System: Research, Design & Build Plan

> **Single comprehensive deliverable** for designing the optimal live drafting system for the
> league defined below. Produced by a multi-subagent research effort with an orchestrator
> synthesis. Companion persistent memory: [`../config/league.json`](../config/league.json)
> and [`../CLAUDE.md`](../CLAUDE.md).

**Reasoning-first mandate.** Per the task's instructions, this document presents *all
supporting research and explicit chain-of-thought reasoning first*, and only then draws
conclusions. **Final conclusions, recommendations, and the build plan live in
[§10 Reflection & Synthesis](#10-reflection--synthesis-orchestrator)** — read the earlier
sections for the reasoning that supports them.

## Table of contents

1. [Purpose & how to read this document](#1-purpose--how-to-read-this-document)
2. [Memorialized league settings & constraints (immutable)](#2-memorialized-league-settings--constraints-immutable)
3. [Orchestration methodology (subagents & process)](#3-orchestration-methodology-subagents--process)
4. [Subagent 1 — Research Validation & Algorithm Selection](#4-subagent-1--research-validation--algorithm-selection)
5. [Subagent (Platform & Tool Vetting)](#5-subagent--platform--tool-vetting)
6. [Subagent 2 — Feature & Factor Expansion](#6-subagent-2--feature--factor-expansion)
7. [Subagent 3 — System & Architecture Planning](#7-subagent-3--system--architecture-planning)
8. [Subagent 4 — Documentation & Fidelity Review](#8-subagent-4--documentation--fidelity-review)
9. [Orchestrator verification log](#9-orchestrator-verification-log)
10. [Reflection & Synthesis (orchestrator)](#10-reflection--synthesis-orchestrator)

---

## 1. Purpose & how to read this document

The goal is to **design, plan, and document the optimal live drafting system** for one
specific fantasy football league (a 12-team, standard-scoring snake draft on CBS Sports —
full settings in §2), using state-of-the-art quantitative methods and deep, cited research.

This is both a **research report** (what the state-of-the-art is, and why) and a **build
plan** (how to implement it in the existing JAAFFL repository). Every major claim is cited;
claims that could not be verified against a primary source are explicitly tagged
`UNVERIFIED`.

**Document structure & the reasoning-first rule.** Sections 4–8 contain each subagent's
*verbatim* report — their explicit stepwise reasoning (labeled "Step 1…, Step 2…"), findings,
and sources. Section 9 is the orchestrator's independent verification. Section 10 synthesizes
everything into the final strategy and build plan. Conclusions deliberately appear **after**
the reasoning that supports them.

Evidence-quality tags used throughout: **[Peer-reviewed]**, **[Empirical-practitioner]**
(data-backed but not peer-reviewed), **[Practitioner-opinion]**, **[UNVERIFIED]**.

---

## 2. Memorialized league settings & constraints (immutable)

These settings are **owner-provided and fixed**. They must never be paraphrased, summarized,
or changed. They are also stored machine-readably in
[`../config/league.json`](../config/league.json) (the persistent memory file), which any
coding/agent work must load before beginning.

### 2.1 Constraints, league & draft settings (verbatim)

- **Draft Type:** Snake
- **Teams:** 12
- **Draft Order:** Decided in-person, then entered into CBS Sports system
- **Scoring Format:** Standard
- **Draft Rounds:** 17
- **Roster Slots per Team:**
  - QB = 1
  - RB = 1
  - WR = 3
  - WR/RB = 1
  - TE = 1
  - K = 1
  - DST = 1
  - Bench = 8

### 2.2 Derived facts (not new constraints — arithmetic on the above)

- **Starters = 9** (QB 1 + RB 1 + WR 3 + WR/RB flex 1 + TE 1 + K 1 + DST 1). **Bench = 8.**
  **Total roster = 17 = draft rounds** — every pick fills a roster slot.
- The **flex (`WR/RB`) is WR *or* RB only** — no TE, no QB.
- **Standard = non-PPR** (0 points per reception).
- **Draft order is not a plain snake inferred from team count** — it is set in person and
  entered into CBS; the tool must read the *actual* order from the live room.
- **League-wide starter demand (12 teams):** QB 12, TE 12, K 12, DST 12, and a combined
  RB+WR starting pool of 12 (RB) + 36 (WR) + 12 (WR/RB flex) = **60 RB/WR starters**
  (12 × 9 = 108 total starters). This asymmetry drives every replacement baseline in §§4–10.

---

## 3. Orchestration methodology (subagents & process)

This deliverable was produced by an **orchestrator + specialized subagents** process, as
required. Each subagent reasoned independently, performed its own web research, reported its
stepwise reasoning and findings, and the orchestrator verified and synthesized the results.

| Role | Mandate | Depends on |
| --- | --- | --- |
| **Subagent 1** — Research Validation & Algorithm Selection | Deep web review + adversarial validation of quantitative snake-draft optimization methods; identify the live-recommendation state-of-the-art; rank an engine core | — |
| **Subagent (Platform & Tool Vetting)** | Validate/refresh CBS integration realities, $0 data sources, and the live-draft tech stack against current (2025–2026) sources; map to the repo | repo scaffold |
| **Subagent 2** — Feature & Factor Expansion | Expand every feature/input/factor/weighting for the selected methods, scoped to this exact roster; justify inclusion/exclusion and weights | Subagent 1, Platform |
| **Subagent 3** — System & Architecture Planning | Justify build specs, architecture, tools/platforms, CBS scope; fold subagent findings into concrete decisions | Subagents 1, 2, Platform |
| **Subagent 4** — Documentation & Fidelity Review | Review the assembled document + memory file for completeness and fidelity to all constraints | all |
| **Orchestrator** (this synthesis) | Independently verify key claims; reflect; synthesize the final strategy + build plan | all |

**Process notes.** The orchestrator independently verified the highest-impact claims with
its own web searches (see §9): the academic state-of-the-art references, the
`nfl_data_py → nflreadpy` deprecation, the free Fantasy Football Calculator ADP API, and the
"Zero-RB is counter-indicated in standard scoring" strategic conclusion. The persistent
memory file (§2 / `config/league.json`) was written **before** any research, so the fixed
settings anchored every subagent.

---

## 4. Subagent 1 — Research Validation & Algorithm Selection

> **Verbatim report from Subagent 1.** Mandate: deep web review + adversarial validation of
> quantitative snake-draft optimization methods; identify the live-recommendation
> state-of-the-art; rank an engine core. Scoped to the fixed settings (§2).

**Scope:** 12-team, snake, **Standard (non-PPR)**, 17 rounds. Starters: QB1 / RB1 / WR3 /
**WR-RB flex1** / TE1 / K1 / DST1 + 8 bench. Evidence-quality tags: **[Peer-reviewed]**,
**[Empirical-practitioner]** (data-backed but not peer-reviewed), **[Practitioner-opinion]**,
**[UNVERIFIED]** (could not access primary text / self-reported single-instance).

### 4.A Reasoning log (explicit stepwise chain-of-thought)

**Step 1 — Frame the problem class before choosing tools.** A live snake draft is a
*sequential, adversarial, partially-observable team-formation problem under uncertainty* with
a hard real-time constraint (a recommendation in a few seconds per pick). Three of these
properties each independently constrain the algorithm: (a) *sequential + adversarial* means my
pick value depends on what opponents will take before my next turn — pure static ranking is
insufficient; (b) *partially-observable/uncertain* means player projections are noisy inputs,
so a point estimate understates the real decision; (c) *real-time* rules out anything requiring
online training or exhaustive search of the true state space. I hold these three constraints as
filters against every candidate method.

**Step 2 — Establish the objective function honestly.** The mission wants to maximize *win
outcomes* (ideally playoff/championship odds), not raw projected points. Evidence:
championships are disproportionately won by a few high-ceiling "league-winners," and steady
mid-range projected-points players do not reliably produce titles ([Fantasy Points, "Upside
Wins Championships"](https://www.fantasypoints.com/nfl/articles/season/2020/upside-wins-championships))
**[Practitioner-opinion]**. Only one source optimizes wins *directly* (Becker & Sun, a
win-likelihood MIP). The dominant tractable practice optimizes *roster projected points via
marginal/replacement value* as a **proxy** for wins. The objective should therefore be layered
— expected marginal points drives regular-season win expectation (an accumulation game
rewarding floor + total points), while variance/ceiling matters for the single-elimination
championship phase. This argues for `utility = E[marginal points] ± λ·σ`, with λ shifting
across draft phase and roster slot, rather than a naked point total (pending the Step 6 check).

**Step 3 — Derive THIS league's replacement baselines from first principles.** VBD is only as
good as its baseline, a pure function of *starter demand*, which this roster changes. Across 12
teams: QB 12, TE 12, K 12, DST 12, and RB+WR = 12 (RB) + 36 (WR) + 12 (flex) = **60 RB/WR
starters** (12×9 = 108 ✓). Consequences: **WR baseline is very deep** (~**WR40**, far deeper
than a 2WR+flex league's ~WR30); **RB baseline moderate/shallow** (~**RB18–22**; exact flex
RB/WR split **[UNVERIFIED]**); **QB/TE/K/DST shallow** (~index-12 → *defer* candidates).

**Step 4 — Overlay Standard (non-PPR) scoring; this is where generic advice breaks.** Non-PPR
removes 0.5–1.0 pt/reception, which (i) *compresses WR scoring and flattens the WR curve* —
e.g., Justin Jefferson ~21.7 PPR → ~14.2 standard PPG, WRs "fall closer to the RBs around
them" ([FantasySixPack](https://fantasysixpack.net/fantasy-football-standard-ppr-half-ppr/))
**[Empirical-practitioner]**; (ii) *preserves/elevates early-down TD-and-carry RBs* while
demoting pass-catching RBs (Ekeler ~21.9→15.6); (iii) makes **Zero-RB actively ill-advised** —
a PPR-era strategy "not recommended" in standard ([Sleeper](https://sleeper.com/blog/zero-rb-strategy/),
[FantasyPros Zero-RB](https://www.fantasypros.com/2025/08/zero-rb-draft-strategy-targets-fantasy-football/))
**[Practitioner-opinion]**. Resolution of the tension (deep WR demand vs. shrunk WR per-player
edge): **WR value here is breadth (starter count), not per-player edge**, whereas **RB value is
top-end scarcity + marginal gap**. Correct roster-derived baselines + standard projections will
*naturally* recommend securing 1–2 scarce high-marginal RBs early while accumulating WR volume
mid-draft — without hard-coded rules — and correctly make **Zero-RB a non-starter here**.

**Step 5 — Positional value-curve shape confirms the scarcity ordering empirically.** In
*standard scoring*, RB/WR/TE decline steeply (logarithmic, big early cliffs), QB declines
gently/linearly, K/DST nearly flat; predictability R² ≈ 0.80 for skill positions vs ~0.50 for
K/DST ([Fantasy Football Analytics, "Expected Points by Position Rank"](https://fantasyfootballanalytics.net/2013/07/expected-points-by-position-rank-in-fantasy-football.html))
**[Empirical-practitioner]**. Prioritize scarce steep-curve positions (RB; WR for volume;
elite TE only), defer flat-curve positions (QB mid, K/DST last). With 17 rounds and an 8-man
bench, roster exactly one K and one DST (stream targets), leaving ~15 picks for RB/WR/QB/TE.

**Step 6 — Check whether optimizing points is a defensible proxy for winning.** (a)
Game-theoretically, VBD-with-a-sensible-baseline behaves like a *minimax/near-equilibrium*
strategy ([Advanced Football Analytics](http://www.advancedfootballanalytics.com/2008/08/game-theory-and-fantasy-draft-strategy.html);
[Cornell summary](https://blogs.cornell.edu/info2040/2015/09/22/game-theory-and-equilibrium-in-fantasy-football-drafting/))
**[Practitioner-opinion; equilibrium claim is simulation-based and assumes all opponents play
VBD]**. (b) Empirically, a large study (1,350 leagues / 12,590 teams / 188k picks) found human
drafts are highly *homogeneous/"groupthink,"* that *less-common roster builds outperformed
popular ones*, and *handcuffing produced no win-rate edge* (51.04% vs 50.56%, n.s.)
([Lee & Liu, Judgment and Decision Making](https://sjdm.org/~baron/journal/22/220318/jdm220318.html))
**[Peer-reviewed, large-sample, observational/single-season]**. This says value-based VBD
willing to deviate from consensus can beat the field, and single clever tactics add little vs
variance. Conclusion: the point/marginal-value proxy is defensible as the **core**, provided
(1) baselines are league-correct, (2) a risk term is layered, and (3) opponents are modeled.

**Step 7 — The sequential/adversarial constraint forces (cheap) opponent modeling.** The
relevant question at each pick is Fry, Lundberg & Ohlmann's framing: *"what set of players is
not going to be available when your turn comes up"* ([JQAS 2007](https://ideas.repec.org/a/bpj/jqsprt/v3y2007i2n5.html);
[ScienceDaily](https://www.sciencedaily.com/releases/2007/08/070823170012.htm))
**[Peer-reviewed]**. They proved the *exact* stochastic DP intractable and used a deterministic
heuristic — a direct warning that full DP/MDP is off the table for live use. The tractable
substitute is **Monte Carlo simulation of opponent picks driven by ADP mean + SD** →
*survival/availability probabilities* → **VONA (Value Over Next Available)** (opportunity cost
of waiting). This is what the leading commercial tool does ([FantasyPros Draft Wizard](https://support.fantasypros.com/hc/en-us/articles/115001300547-What-is-Draft-Wizard))
**[Empirical-practitioner]** and what independent builders do ([Jensen — mean-variance
utility](https://bcjense6.medium.com/simulating-the-snake-an-ai-assisted-fantasy-football-draft-strategy-4064c98940f7);
[approximatemethods — beta-fit availability](https://www.approximatemethods.com/fantasy.html))
**[Practitioner-opinion / UNVERIFIED outcomes]**. FantasyFootballCalculator publishes
**non-PPR, 12-team ADP with dispersion** ([FFC](https://fantasyfootballcalculator.com/adp)).

**Step 8 — The uncertainty constraint forces distributions, not point estimates.** Projections
are only moderately accurate (year-to-year fantasy-PPG R² ≈ 0.59) ([Isaac Petersen, *Fantasy
Football Analytics* textbook, simulation chapter](https://isaactpetersen.github.io/Fantasy-Football-Analytics-Textbook/simulation.html))
**[Empirical-practitioner]**. Bootstrap/Monte-Carlo across multiple projection sources → fit
per-player normal/skew-normal distributions → floor/ceiling and P(exceeds threshold), feeding
both the risk term and opponent-availability noise, and late-round *upside* bench stashes.

**Step 9 — The roster-construction constraint (the WR/RB flex) needs an assignment step.**
Value must be measured as *marginal contribution to the 9 starting slots* (incl. a flex that
can be WR or RB). Cleanest formalization: a small constrained optimization — given my roster +
a candidate, solve the optimal starter assignment (bipartite/lightweight ILP) and value the
candidate by the *lineup* improvement. This is the spirit of Becker & Sun's draft MIP (maximize
likelihood of *winning matchups*, re-solved before each pick — [JQAS 2016](https://ideas.repec.org/a/bpj/jqsprt/v12y2016i1p17-30n1.html))
**[Peer-reviewed; quantitative results UNVERIFIED — paywalled]** and of DFS integer-programming
optimizers ([Hunter, Vielma & Zaman, arXiv:1604.01455](https://arxiv.org/abs/1604.01455))
**[Peer-reviewed]** — transferring only the *roster-feasibility + win-probability objective*
machinery, kept lightweight to run live.

**Step 10 — Rule out heavyweight AI for the core, with reasons.** Full **stochastic DP/MDP** is
intractable (Fry et al.). **Belief-state MDP + Bayesian Q-learning** is proven excellent but for
*Fantasy Premier League* team formation (top ~1% vs 2.5M — [Matthews et al. 2012](https://eprints.soton.ac.uk/340382/))
**[Peer-reviewed]**, not a snake draft. Recent **deep-RL** wins are in *fantasy cricket*
salary-cap selection (PPO ~62–67th pct — [arXiv:2412.19215](https://arxiv.org/html/2412.19215v1))
**[Peer-reviewed]**, explicitly not applicable to snake drafts. The one hobby **snake-draft RL**
agent optimized points (not wins) with no rigorous baseline (n=1) **[UNVERIFIED]**. RL/DP are
data-hungry, brittle, and non-transferring → offline/stretch role at most, not the live core.
Evidence points to a **VBD + Monte-Carlo-opponent-simulation + risk-aware assignment**
architecture as the deployable state-of-the-art.

### 4.B Methods catalog (each method validated, with evidence quality)

**1. Value-Based Drafting (VBD) / VOR / VORP / VOLS / VONA — the marginal-value family.**
*Optimizes* projected points **above a positional replacement baseline** (marginal
value/scarcity). *Variants:* **VORP** = value over best waiver player (deep baseline →
risk-averse, bench depth); **VOLS** = value over last *starter* (rewards elite starters);
**VONA** = value over best player expected at your *next* pick (the only *dynamic* baseline);
**BEER/"man-games"** = baseline sized by *games actually played* (bye/injury-adjusted);
Subvertadown's **BEER+** blends VOLS+BEER with variance/Sharpe risk-adjustment. Sources:
[FantasyPros VORP/VOLS/VONA](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/),
[FantasyPros support](https://support.fantasypros.com/hc/en-us/articles/115005868747-What-is-value-based-drafting-What-do-player-draft-values-mean-VORP-VONA-VOLS-VBD),
[Subvertadown baselines](https://subvertadown.com/article/guide-to-understanding-the-different-baselines-in-value-based-drafting-vbd-vols-vs-vorp-vs-man-games-and-beer-),
[FFA "Win Your Snake Draft"](https://fantasyfootballanalytics.net/2013/04/win-your-snake-draft-calculating-value.html).
*Inputs:* season projections + league starter counts (+ ADP for VONA). *Strengths:* encodes
scarcity; near-equilibrium; O(n log n) cheap; industry standard. *Weaknesses:* baseline- and
projection-dependent; static VORP/VOLS ignore draft flow (VONA fixes). *Live:* **excellent.**
*Evidence:* **[Empirical-practitioner]**. Originated with Joe Bryant (Footballguys, mid-1990s).

**2. Positional replacement-level theory / marginal value / scarcity.** *Optimizes* the *shape*
of each position's value curve to set the baseline. Standard curves: RB/WR/TE steep, QB gentle,
K/DST flat ([FFA Expected Points by Rank](https://fantasyfootballanalytics.net/2013/07/expected-points-by-position-rank-in-fantasy-football.html)).
The theory *under* VBD, precomputed. *Evidence:* **[Empirical-practitioner]**, standard-specific.

**3. ADP-based opponent modeling / pick-probability / survival modeling.** *Optimizes* P(player
survives to my next pick) → VONA/opportunity-cost. Implementations: ADP mean+SD →
Gaussian/empirical survival; beta distributions fit to mock data (approximatemethods); ADP+noise
in Monte Carlo (Jensen, Draft Wizard). Data: [FFC non-PPR 12-team ADP](https://fantasyfootballcalculator.com/adp).
*Weaknesses:* ADP lags real rooms; ignores specific opponents' needs unless modeled. *Live:*
**excellent.** *Evidence:* **[Empirical-practitioner]** (method) / **[UNVERIFIED]** (accuracy).

**4. Tier-based drafting (Boris Chen Gaussian-mixture clustering).** *Optimizes* grouping of
statistically-indistinguishable players to expose *cliffs* and prevent false precision. Chen
aggregates FantasyPros ranks and clusters with a **GMM** ([borischen.co](http://www.borischen.co/),
[Huey Kwik explainer](https://medium.com/@hueykwik/using-data-science-to-win-in-fantasy-football-8a073d0f22fa)).
*Weakness:* *not an optimizer* — a representation; pair with value/opportunity-cost. *Live:*
**excellent as an interpretation/guard layer.** *Evidence:* **[Empirical-practitioner]**.

**5. Monte Carlo draft simulation.** *Optimizes* expected outcome of "take now vs wait" by
simulating the rest of the draft many times (opponents via #3), then scoring rosters. Utility in
the wild: `E[two-pick points] − λ·σ` (Jensen); Draft Wizard runs full mock sims for live recs.
*Weaknesses:* GIGO on projections+ADP; self-reported edges are single-instance. *Live:*
**excellent** (hundreds–thousands of sims/second). *Evidence:* **[Empirical-practitioner]**
method / **[UNVERIFIED]** outcomes. Sources: [Jensen](https://bcjense6.medium.com/simulating-the-snake-an-ai-assisted-fantasy-football-draft-strategy-4064c98940f7),
[joewlos simulator](https://github.com/joewlos/fantasy_football_monte_carlo_draft_simulator),
[Draft Wizard](https://draftwizard.fantasypros.com/).

**6. Dynamic programming / MDP / optimal-stopping.** Fry, Lundberg & Ohlmann formalize the draft
as a stochastic DP, **prove it intractable at realistic size**, and use a deterministic DP
heuristic; their operational insight (*"what won't be available at my next turn"*) is exactly
VONA ([JQAS 2007](https://ideas.repec.org/a/bpj/jqsprt/v3y2007i2n5.html)). *Live:* **poor
as-is; its insight survives inside Monte-Carlo VONA.** *Evidence:* **[Peer-reviewed]**.

**7. Bayesian RL / belief-state MDP / deep RL.** Best result: Matthews et al. belief-state MDP +
Bayesian Q-learning, top ~1% of 2.5M — **for FPL**, not snake ([ePrints Soton](https://eprints.soton.ac.uk/340382/)).
Deep-RL PPO wins are **fantasy cricket** salary-cap (~62–67th pct — [arXiv:2412.19215](https://arxiv.org/html/2412.19215v1)).
Snake-draft RL exists only as hobby work (position abstraction, points objective, no baseline —
[approximatemethods](https://www.approximatemethods.com/fantasy.html); [Stanford CS221 poster](https://web.stanford.edu/class/archive/cs/cs221/cs221.1192/2018/restricted/posters/macdow/poster.pdf)).
*Live:* **poor for the core; offline/stretch only.** *Evidence:* **[Peer-reviewed]** off-format
/ **[UNVERIFIED]** for snake.

**8. Game-theoretic / adversarial drafting.** Core result: VBD ≈ minimax/Nash-equilibrium
*robust* baseline; exploiting predictable opponent errors (position runs, hometown bias) via
VONA is the *exploitative* refinement ([AFA game theory](http://www.advancedfootballanalytics.com/2008/08/game-theory-and-fantasy-draft-strategy.html);
[Cornell](https://blogs.cornell.edu/info2040/2015/09/22/game-theory-and-equilibrium-in-fantasy-football-drafting/)).
*Weakness:* "unique equilibrium baseline" claim is simulation-based, assumes opponents also play
VBD. *Live:* **conceptual layer over #1/#3.** *Evidence:* **[Practitioner-opinion]**.

**9. Constrained roster optimization (ILP / MIP / CP-SAT).** Becker & Sun's draft model targets
**win-likelihood** directly, re-solved each pick ([JQAS 2016](https://ideas.repec.org/a/bpj/jqsprt/v12y2016i1p17-30n1.html));
DFS IP maximizes **P(winning)** with variance floors + stacking ([Hunter/Vielma/Zaman](https://arxiv.org/abs/1604.01455)).
*Strength:* correctly handles the WR/RB flex and "value = marginal starting-lineup gain."
*Weakness:* cited works are salary-cap, not sequential snake; full MIP each pick is heavier.
*Live:* **good if kept lightweight (assignment/greedy).** *Evidence:* **[Peer-reviewed]**
methods; Becker/Sun results **[UNVERIFIED]** (paywalled).

**10. Risk models (floor/ceiling, boom/bust, injury/games-played survival).** *Optimizes* the
distribution — bootstrap/Monte-Carlo over multi-source projections (floor/ceiling, P>threshold)
([Petersen textbook](https://isaactpetersen.github.io/Fantasy-Football-Analytics-Textbook/simulation.html)),
coefficient-of-variation consistency ([PFN Consistency Score](https://www.profootballnetwork.com/introduction-to-the-fantasy-football-consistency-score/)),
**man-games/BEER** for availability. Championship equity leans on **ceiling** ([Upside Wins
Championships](https://www.fantasypoints.com/nfl/articles/season/2020/upside-wins-championships)).
*Live:* **good** (distributions precomputed). *Evidence:* **[Empirical-practitioner]**; the
"upside" thesis is best-ball-flavored — apply cautiously in a managed weekly-lineup redraft
(floor matters for *making* the playoffs).

**11. Objective: win-probability vs raw projected points.** Only Becker & Sun optimize wins
directly; the field uses marginal-points VBD as a tractable, near-equilibrium proxy.
Large-sample support that *value-based deviation beats groupthink and single tactics add ~0 win
rate* comes from [Lee & Liu, JDM](https://sjdm.org/~baron/journal/22/220318/jdm220318.html)
**[Peer-reviewed]**. Use marginal-points as core + a variance term for the win/points gap +
(stretch) a season-simulation to convert rosters → playoff/championship odds.

### 4.C State-of-the-art assessment

- **Peer-reviewed SOTA does not target the live snake draft directly.** The strongest academic
  results (Matthews Bayesian RL; deep-RL cricket; DFS integer programming) solve *salary-cap
  team selection*, a different game. The only peer-reviewed snake-draft models (Fry et al. DP;
  Becker & Sun MIP) either prove the exact problem intractable or are paywalled/unverified on
  outcomes. **There is no published, peer-reviewed, empirically-validated optimal live
  snake-draft solver.** Anyone claiming one is overstating the evidence.
- **The de-facto deployable SOTA for LIVE recommendations is a hybrid:** roster-correct
  **VBD/VONA** value + **Monte-Carlo simulation of opponent picks from ADP dispersion**
  (survival probabilities) + a **risk/variance term** + a **lightweight constrained roster/flex
  assignment**, with **tiers** as the interpretation layer. This is precisely the architecture
  of the leading commercial tool (FantasyPros Draft Wizard with Live Sync) and of every serious
  independent build. It is the only family that simultaneously satisfies *sequential-adversarial
  awareness*, *uncertainty handling*, *flex/roster feasibility*, and *few-seconds-per-pick*.
- **Best-in-class objective** is a *blend*: marginal projected points (regular-season win proxy,
  near-equilibrium) with a tunable variance term (floor to bank a playoff berth; ceiling on late
  bench lottery tickets). Direct win/championship-odds optimization is the theoretical ceiling
  but a *stretch* layer, not a v1 requirement.
- **What is NOT SOTA:** raw projected-points ranking (ignores scarcity), pure ADP-following
  (encodes beatable groupthink), online deep-RL/exact-DP (intractable or non-transferring).

### 4.D Ranked recommendation for the engine core (scoped to this league)

**Recommended architecture: a Monte-Carlo-augmented Value-Based Drafting engine with a
risk-aware, flex-correct assignment objective — "VBD/VONA core + opponent simulation + risk
layer + tiers."** Ranked by priority:

1. **CORE — VBD with league-correct, dynamically-updated baselines (highest priority).**
   Marginal value = projection − replacement, where replacement is derived from *this roster's*
   starter counts under *standard* scoring (WR ~WR40 deep; RB ~RB18–22; QB/TE/K/DST ~index-12
   shallow). Use a **BEER/man-games** (bye/injury-adjusted) baseline blended toward VOLS for the
   scarce top end. *Justification:* industry standard, near-equilibrium/robust, corroborated by
   standard-scoring curves, and the *only* component that correctly encodes this roster's
   scarcity (endogenously producing "secure 1–2 elite RBs, accumulate WR volume, defer
   QB/TE/K/DST" — and making **Zero-RB a non-starter here**).
2. **VONA via Monte-Carlo opponent simulation (co-essential for "live").** Each pick, simulate
   opponents from **non-PPR 12-team ADP mean+SD** (optionally opponent-need-weighted), compute
   survival probabilities to your next 1–2 picks, rank by opportunity cost `value_now −
   E[best value available next turn]`. *Justification:* Fry et al.'s DP insight made tractable;
   matches Draft Wizard/Jensen; runs in <1s; exploits predictable position runs.
3. **Risk/uncertainty layer.** Precompute per-player projection distributions (bootstrap across
   sources; floor/ceiling/σ). Objective `utility = E[marginal pts] − λ·σ`, with **λ
   phase/slot-aware**: floor-tilt for your starting core (bank a playoff berth), ceiling-tilt for
   late bench stashes (championship upside). *Justification:* projections are only moderately
   accurate; floor wins the regular season, ceiling wins titles.
4. **Lightweight constrained roster/flex assignment.** Value each candidate by its *marginal
   gain to the optimal 9-man starting lineup* (bipartite assignment over slots incl. the WR/RB
   flex), not raw roster points. Keep it greedy/Hungarian (sub-second). *Justification:* the
   WR/RB-only flex and "3 WR + 1 RB" asymmetry make lineup-marginal value diverge from list
   value.
5. **Tiers (Boris Chen GMM) as interpretation + guard rail.** Cluster to expose cliffs; use as
   tie-breaker and to prevent reaching across a tier gap when VONA says a position can wait.
   *Justification:* robust to noise, strong UX, prevents false precision. Not an optimizer.
6. **STRETCH / optional (not required for a strong v1):** (a) a rest-of-season **Monte-Carlo
   season simulator** to convert rosters into playoff/championship odds — the true objective, but
   higher cost; (b) an **offline-trained policy** (RL) purely as an audit/benchmark. Both are
   evidence-thin for snake drafts and compute-heavier.

**Explicitly de-prioritized / rejected for the core:** raw-projected-points ranking; pure
ADP-following (groupthink, beatable per Lee & Liu); exact stochastic DP/MDP (intractable — Fry
et al.); online deep-RL (non-transferring, brittle, unexplainable live); and any **Zero-RB**
default (PPR-specific; counter-indicated in standard).

### 4.E Sources (deduplicated, actually used)

- FantasyPros — [VBD: VORP, VOLS, VONA (2025)](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/) ·
  [VBD (2026)](https://www.fantasypros.com/2026/06/fantasy-football-draft-strategy-value-based-drafting-2026/) ·
  [What is VBD (support)](https://support.fantasypros.com/hc/en-us/articles/115005868747-What-is-value-based-drafting-What-do-player-draft-values-mean-VORP-VONA-VOLS-VBD)
- Subvertadown — [Guide to VBD baselines: VOLS vs VORP vs man-games and BEER+](https://subvertadown.com/article/guide-to-understanding-the-different-baselines-in-value-based-drafting-vbd-vols-vs-vorp-vs-man-games-and-beer-)
- Fantasy Football Analytics — [Win Your Snake Draft: VOR in R](https://fantasyfootballanalytics.net/2013/04/win-your-snake-draft-calculating-value.html) ·
  [Winning with Projections, VOR & VBD (2024)](https://fantasyfootballanalytics.net/2024/08/winning-fantasy-football-with-projections-value-over-replacement-and-value-based-drafting.html) ·
  [Expected Points by Position Rank](https://fantasyfootballanalytics.net/2013/07/expected-points-by-position-rank-in-fantasy-football.html) ·
  [Projection accuracy scatterplot](https://fantasyfootballanalytics.net/2015/07/accuracy-of-fantasy-football-projections-interactive-scatterplot-in-r.html)
- Fry, Lundberg & Ohlmann (2007), *A Player Selection Heuristic for a Sports League Draft*, JQAS —
  [abstract](https://ideas.repec.org/a/bpj/jqsprt/v3y2007i2n5.html) · [ScienceDaily](https://www.sciencedaily.com/releases/2007/08/070823170012.htm)
- Becker & Sun (2016), *An Analytical Approach for Fantasy Football Draft and Lineup Management*,
  JQAS — [abstract](https://ideas.repec.org/a/bpj/jqsprt/v12y2016i1p17-30n1.html) *(full text
  not accessible; quantitative results UNVERIFIED)*
- Lee & Liu, *Drafting strategies in fantasy football: competitive sequential human decision
  making*, JDM — [article](https://sjdm.org/~baron/journal/22/220318/jdm220318.html) ·
  [Cambridge Core](https://www.cambridge.org/core/journals/judgment-and-decision-making/article/drafting-strategies-in-fantasy-football-a-study-of-competitive-sequential-human-decision-making/2AB841B3F446833348D784C0FC54DAD2)
- Matthews, Ramchurn & Chalkiadakis (2012), *Competing with Humans at Fantasy Football* —
  [ePrints Soton](https://eprints.soton.ac.uk/340382/)
- Hunter, Vielma & Zaman, *Picking Winners in Daily Fantasy Sports Using Integer Programming* —
  [arXiv:1604.01455](https://arxiv.org/abs/1604.01455)
- *Optimizing Fantasy Sports Team Selection with Deep RL* (2024, cricket) —
  [arXiv:2412.19215](https://arxiv.org/html/2412.19215v1)
- Stanford CS221 (MacDow, 2018), RL for fantasy football —
  [poster](https://web.stanford.edu/class/archive/cs/cs221/cs221.1192/2018/restricted/posters/macdow/poster.pdf)
- Boris Chen — [tiers via GMM](http://www.borischen.co/) · [PPR draft tiers & clustering](http://www.borischen.co/2013/08/ppr-draft-tiers-and-clustering_7.html) ·
  Huey Kwik, [Using Data Science to Win in Fantasy Football](https://medium.com/@hueykwik/using-data-science-to-win-in-fantasy-football-8a073d0f22fa)
- Ben Jensen — [Simulating the Snake (Monte-Carlo + mean-variance utility)](https://bcjense6.medium.com/simulating-the-snake-an-ai-assisted-fantasy-football-draft-strategy-4064c98940f7)
- approximatemethods — [Drafting with Deep RL (snake; ADP-beta survival)](https://www.approximatemethods.com/fantasy.html)
- joewlos — [Monte Carlo Draft Simulator (GitHub)](https://github.com/joewlos/fantasy_football_monte_carlo_draft_simulator)
- Isaac Petersen — [*Fantasy Football Analytics* textbook, Simulation chapter](https://isaactpetersen.github.io/Fantasy-Football-Analytics-Textbook/simulation.html)
- Advanced Football Analytics — [Game Theory and Fantasy Draft Strategy](http://www.advancedfootballanalytics.com/2008/08/game-theory-and-fantasy-draft-strategy.html) ·
  Cornell — [Game Theory and Equilibrium in Fantasy Football Drafting](https://blogs.cornell.edu/info2040/2015/09/22/game-theory-and-equilibrium-in-fantasy-football-drafting/)
- FantasyPros Draft Wizard — [What is Draft Wizard](https://support.fantasypros.com/hc/en-us/articles/115001300547-What-is-Draft-Wizard) ·
  [Draft Wizard site](https://draftwizard.fantasypros.com/)
- Standard-scoring / Zero-RB / risk — [Sleeper: Zero-RB](https://sleeper.com/blog/zero-rb-strategy/) ·
  [FantasyPros: Zero-RB](https://www.fantasypros.com/2025/08/zero-rb-draft-strategy-targets-fantasy-football/) ·
  [FantasySixPack: Standard vs PPR value shift](https://fantasysixpack.net/fantasy-football-standard-ppr-half-ppr/) ·
  [PFN: Consistency Score (CV)](https://www.profootballnetwork.com/introduction-to-the-fantasy-football-consistency-score/) ·
  [Fantasy Points: Upside Wins Championships](https://www.fantasypoints.com/nfl/articles/season/2020/upside-wins-championships)
- League data — [FFC non-PPR 12-team ADP (with dispersion)](https://fantasyfootballcalculator.com/adp) ·
  [FFC Standard rankings](https://fantasyfootballcalculator.com/rankings/standard)

**Handoff note (Subagent 1 → design team):** the load-bearing conclusions for this league are
(1) baselines must be *computed from this roster's starter counts* (WR ~WR40, RB ~RB18–22, rest
~index-12), (2) **standard scoring makes Zero-RB counter-indicated** and elevates scarce
workhorse-RB marginal value while flattening WR per-player edge (WR value = breadth), (3) the
only live-viable SOTA is **VBD/VONA + Monte-Carlo opponent simulation + risk term + flex-aware
assignment**, and (4) **no peer-reviewed optimal live snake-draft solver exists** — practitioner
outcome claims are **[UNVERIFIED]** (method validation, not efficacy proof). The exact flex
WR/RB split (~8/4 assumed) is **[UNVERIFIED]** and should be measured from non-PPR 12-team
mock/ADP data before finalizing baselines.

---

## 5. Subagent (Platform & Tool Vetting)

> **Verbatim report.** Mandate: validate/refresh CBS integration realities, $0 data sources,
> and the live-draft tech stack against current (2025–2026) sources, and map them onto the
> existing repo scaffold. Scoped to the fixed settings (§2). Personal use, genuinely $0 (AI
> credits excepted).

### 5.A Reasoning log (stepwise)

**Step 1 — Establish the baseline from the repo.** Read the prior research
(`docs/research/cbs-fantasy-football-draft-tool.md`), `ARCHITECTURE.md`, `README.md`. The
scaffold's core bets: (a) MV3 browser extension reading the user's own authenticated CBS
session; (b) a local FastAPI backend on `127.0.0.1`; (c) DuckDB/SQLite/Parquet warehouse; (d) a
pluggable provider interface with **nflverse/nfl_data_py** + **CBS on-page** as the $0 tier and
FantasyPros/SportsDataIO/Sportradar as opt-in paid; (e) ADR 0003 = personal / $0 / text-only /
no voice. Task: validate each bet against current sources and turn it into concrete tool
choices.

**Step 2 — Test the single most load-bearing data claim.** The scaffold names `nfl_data_py` as
the free historical backbone. Current evidence: `nfl_data_py` was **deprecated and archived
read-only on 2025-09-25**, explicitly redirecting to **`nflreadpy`**
([nfl_data_py repo](https://github.com/nflverse/nfl_data_py)). Concrete required refresh: the $0
tier must pin `nflreadpy` (Polars-based, MIT), not `nfl_data_py`.

**Step 3 — Probe the hardest requirement (live CBS capture) at the mechanism level.** The prior
doc argued "browser extension in the user's session" but did not resolve *how* live picks are
read under MV3. Binding constraint verified: MV3 `webRequest` can observe the **WebSocket
handshake but cannot read individual WebSocket messages**
([chrome.webRequest docs](https://developer.chrome.com/docs/extensions/reference/api/webRequest);
[Chromium MV3 WebSocket thread](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/23pCzk69Ueo/m/z9GH0J7WBQAJ)).
Therefore live pick capture cannot rely on `webRequest`. The workable mechanism is a
**MAIN-world content script** that monkeypatches `WebSocket`/`fetch`/`XHR` in the page context
and relays payloads to the isolated content script
([content-scripts `world` docs](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts);
[inject-global MV3](https://davidwalsh.name/inject-global-mv3)), with a **`MutationObserver`**
DOM fallback ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver)).

**Step 4 — Pin the exact scoring the engine must compute.** Standard/non-PPR is FIXED, so I
retrieved authoritative CBS values (receptions = **0 pts**; K = FG 3 with **+2 bonus at 50+**,
PAT 1; DST has **both** points-allowed and yards-allowed tiers) from
[CBS's "what is a standard-scoring league" article](https://www.cbssports.com/fantasy/football/news/what-is-a-standard-scoring-league/).
CBS quirk: even "standard" DST scores on yardage-allowed → design rule: read scoring live from
the league settings, don't hardcode.

**Step 5 — Re-tier the data sources for *genuine* $0.** The FantasyPros API is **paid**
(personal keys bundled with MVP/HOF from **$5.99/mo**) ([FantasyPros API](https://www.fantasypros.com/api-data/)),
which contradicts a literal-$0 reading if required. Two genuinely-free replacements: nflverse
**redistributes FantasyPros ECR** (`load_ff_rankings`) and **expected fantasy points**
(`load_ff_opportunity`) under CC-BY 4.0, and **Fantasy Football Calculator's ADP REST API** is
free for personal *and* commercial use with standard + 12-team parameters
([FFC ADP API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api)). A true-$0
standard-scoring stack is achievable without paid opt-ins.

**Step 6 — Check the compliance caveat is still real.** The CBS/Paramount terms were
reorganized (old `cbsinteractive.com/info/tou` now 301s to a Paramount page), but the CBS
mock-draft terms still bind users to the "General Legal Terms" and "CBS Interactive Inc. Terms
of Use" ([CBS FMD terms](https://www.cbssports.com/info/about/tos/fmd)). Personal/non-commercial
+ anti-automation posture stands; *exact current-URL verbatim quotes* are UNVERIFIED due to the
reorg.

**Step 7 — Size the compute budget.** For 12-team/17-round snake, the horizon between the
user's consecutive picks is at most ~22 opponent picks (at the turn). Monte-Carlo rollouts over
~22 picks × N samples plus a small end-state roster ILP (≤17 slots over a few hundred
candidates) is comfortably a **sub-second-to-few-second** job on a laptop — no cloud, no GPU.
Local-first budget holds.

**Step 8 — Map to the repo.** Everything maps onto the existing scaffold with additive changes
(swap `nfl_data_py`→`nflreadpy`, add FFC ADP + CBS-on-page providers, add a MAIN-world injector,
add a `/ws/draft` endpoint). Details in 5.D.

### 5.B CBS integration findings (validated, with caveats)

**B1. Still no dependable public CBS fantasy API — validated.** No current first-party CBS
fantasy developer platform. Community tooling treats the CBS API as deprecated/brittle: the
[`cbs_fantasy_sports_api_token_fetcher`](https://github.com/geoffharcourt/cbs_fantasy_sports_api_token_fetcher)
gem and the R package [`ffscrapr`](https://cran.r-project.org/web/packages/ffscrapr/ffscrapr.pdf)
(lists CBS via unofficial endpoints/token flows). **Treat any CBS "API" as a best-effort,
disable-able fallback, never the backbone.**

**B2. The user's-own-session extension pattern is the right call.** CBS ships an official
first-party companion extension ([chrome-stats](https://chrome-stats.com/d/com.cbs.sports.fantasy)),
and third-party sync products read live drafts across platforms incl. CBS
([Draft Sharks league sync](https://www.draftsharks.com/kb/fantasy-football-league-sync)).
Independent build write-ups confirm the pattern and its fragility: picks are read from the
running **draft chat/event log** or the **draft-results view**, with the trap that
framework-rendered results are "only present in the DOM when the user clicks on it"
([DraftKick: building draft sync](https://draftkick.com/blog/building-draft-sync/);
[DraftKick: how to build sync](https://draftkick.com/blog/how-to-build-sync/)).

**B3. The MV3 capture mechanism is the key technical finding.** (Build in 5.D2.) MV3
`webRequest` sees the WS handshake but not WS messages
([chrome.webRequest](https://developer.chrome.com/docs/extensions/reference/api/webRequest)), and
`declarativeNetRequest` is match/modify only. Live capture must use a **MAIN-world** page-context
script (monkeypatch `WebSocket.prototype`/`fetch`/`XHR`, or read framework state such as React
fiber props) that `postMessage`s to the isolated content script
([`world: "MAIN"`](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts);
[inject-global MV3](https://davidwalsh.name/inject-global-mv3)), with `MutationObserver` on the
board as fallback ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver)).

**B4. CBS draft-room transport is UNVERIFIED — design transport-agnostic.** Could not confirm
whether CBS's current draft room uses WebSockets, SSE, or polling, or which framework renders it.
The capture layer should install *all three* probes (WS/fetch monkeypatch, framework-state read,
DOM observer) and let whichever fires first be the source of truth, de-duplicating by pick number.

**B5. Draft-order detection — validated caution.** CBS commissioner leagues allow custom draft
order; this league sets order in-person then enters it into CBS. The tool must **read the actual
draft board/slots** from the live room and only infer snake order as a fallback — never assume
snake-from-team-count.

**B6. Compliance caveat — still real, personal-use only.** CBS mock-draft terms bind participants
to the CBS Interactive Terms of Use ([FMD terms](https://www.cbssports.com/info/about/tos/fmd)).
The canonical ToU URL now redirects into Paramount Skydance's reorganized legal pages (so the
*specific verbatim* robots/scraping/personal-use quotes are **UNVERIFIED at a stable current
URL**), but the substantive posture — personal, non-commercial use; prohibition on unauthorized
automated access — is unchanged and is why this project is scoped personal-use, user-authorized,
local-only. Keep `docs/legal-and-compliance.md` as the gate.

### 5.C Data sources ($0 personal-use tiering, standard-scoring specifics)

**C1. The genuinely-$0 tier (all you need for the fixed league):**

| Source | What it gives (standard, redraft) | Access | Cost / License | Notes |
|---|---|---|---|---|
| **`nflreadpy`** (replaces `nfl_data_py`) | Play-by-play, weekly/seasonal player & team stats, rosters, schedules, **draft picks**, **cross-source IDs**, snap counts, depth charts | Python (Polars), pip | **$0**, MIT / CC-BY 4.0 ([repo](https://github.com/nflverse/nflreadpy), [docs](https://nflreadpy.nflverse.com/), [PyPI](https://pypi.org/project/nflreadpy/)) | `nfl_data_py` **archived read-only 2025-09-25** — migrate. Polars, not pandas. |
| **`load_ff_rankings()`** (nflverse) | **FantasyPros ECR** (redistributed via DynastyProcess), weekly | Same package | **$0**, CC-BY 4.0 ([ref](https://nflreadr.nflverse.com/reference/load_ff_rankings.html)) | Free ECR *without* a FantasyPros subscription. Personal use clearly fine; commercial verify upstream. |
| **`load_ff_opportunity()`** (nflverse) | **Expected fantasy points** (`ffopportunity`) | Same package | **$0**, CC-BY 4.0 ([ref](https://nflreadr.nflverse.com/reference/load_ff_opportunity.html)) | Opportunity-based (historical) — projection **prior / backtest baseline**, not a forward vendor projection. |
| **Fantasy Football Calculator ADP API** | Consensus **ADP** with `scoring=standard`, `teams=12`, `year`, `position` — JSON | REST: `https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year=2026` | **$0**, free personal **and** commercial; attribution requested; **daily** updates ([API KB](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api), [ADP page](https://fantasyfootballcalculator.com/adp)) | Natively supports non-PPR / 12-team. Don't poll faster than daily. |
| **CBS on-page** (your session) | CBS projections, rankings, ADP, **injury designations**, and the **authoritative league scoring/roster settings** | Extension reads authenticated DOM/state | **$0**, personal/user-authorized | The only $0 source of *your league's actual* settings + CBS first-party projections. Snapshot every draft locally. |
| **Official NFL / CBS injury pages** | Current injury/practice status | Browse / light fetch | $0 | Practical $0 live-injury path (see gap below). |

**This tier alone is a complete, standard-scoring, $0 data layer. No FantasyPros subscription
required.**

**C2. Optional paid upgrades (opt-in, OFF by default — behind the provider interface):**
FantasyPros MVP/HOF **from $5.99/mo** unlocks **personal production API keys** (first-party
rankings, projections, ADP, news, injuries); commercial needs a separate plan
([FantasyPros API](https://www.fantasypros.com/api-data/)) — cleanest *fresh first-party
projections + injuries* upgrade, but **not $0**. Fantasy Nerds API — paid; free tier
**UNVERIFIED** (pricing 403) ([docs](https://api.fantasynerds.com/docs/nfl)). SportsDataIO /
Sportradar — commercial real-time; disabled stubs only.

**C3. VERIFIED GAP — free live injuries is the weak link.** nflverse's data schedule historically
flagged that its injury source lapsed after 2024 with no ETA
([nflverse data schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)),
while `nflreadpy`'s feature list *advertises* "injury statuses and participation data" — these
**partially conflict** → treat 2025+ free injury coverage via nflverse as
**UNVERIFIED/incomplete**. $0 mitigation: read **CBS's own on-page injury designations** at draft
time, backstopped by the official NFL injury report. A guaranteed-fresh injury feed is the one
thing worth the $5.99 FantasyPros upgrade if desired.

**C4. Standard (non-PPR) scoring specifics — the exact map the engine must compute**
([CBS standard-scoring article](https://www.cbssports.com/fantasy/football/news/what-is-a-standard-scoring-league/);
[CBS commissioner help](https://help.football.cbssports.com/s/article/How-do-I-set-up-my-leagues-Scoring-System);
[printyourbrackets summary](https://www.printyourbrackets.com/fantasy-football-point-scoring-system-for-cbs-sports.html)):

- **Passing:** 1 pt / 25 yds · TD 6 · INT −2
- **Rushing:** 1 pt / 10 yds · TD 6
- **Receiving:** 1 pt / 10 yds · TD 6 · **Reception = 0 pts (non-PPR — confirmed)**
- **Misc:** 2-pt conversion +2 · Fumble lost −2
- **Kicker (K, 1 starter):** FG **3 pts**, **+2 bonus for 50+ yds** (i.e., 5 for a 50-yarder) ·
  PAT **1 pt**
- **DST (1 starter):** Def/ST TD 6 · Sack 1 · INT 2 · Fumble recovery 2 · Safety 2 ·
  **Points-allowed tiers** 8 (0–6) → 6 (7–13) → 4 (14–20) → 2 (21–27) → lower/negative above ·
  **plus yards-allowed tiers** 12 (0–49) → … → 2 (250–299).

**Design rule:** CBS "standard" DST scores on **both points *and* yards allowed**, and
commissioner leagues can customize anything — so the tool must **parse the league's actual
scoring table from the authenticated session** and use the values above only as a validation
default / offline fallback. This is why `LeagueSettings` must carry the full scoring map
(including both DST tier tables), not a "standard" enum flag.

**Replacement-baseline implication (for the engine track):** starters QB1/RB1/WR3/TE1/K1/DST1 +
one WR-or-RB flex over 12 teams → WR replacement runs deep (~12 × (3 + flex share) ≈ 40th–48th
WR); RB replacement ~12 × (1 + flex share) ≈ 18th–24th RB. K and DST are near-replacement-flat →
last-rounds/stream candidates in a 17-round board.

### 5.D Live-draft technical stack + build specs (mapped to the existing repo)

Everything below is **additive** — no structural rewrite. Concrete changes are **[CHANGE]**.

**D1. Overall dataflow** (unchanged from `ARCHITECTURE.md`, capture mechanism pinned): `CBS
draft room (authenticated tab) → MAIN-world injector → isolated content script →
ws://127.0.0.1:8787/ws/draft → jaaffl.ingest → jaaffl.data (snapshot) + jaaffl.engine.recommend
→ Recommendation → extension overlay + apps/web dashboard.`

**D2. `apps/extension/` — the capture layer (where the real risk lives).** Build a **three-probe,
transport-agnostic** capture (CBS transport is UNVERIFIED, B4):
1. **MAIN-world injector** (`content_scripts` with `"world": "MAIN"`, or
   `chrome.scripting.registerContentScripts` from the SW): wrap `window.WebSocket` (patch `send`
   + `addEventListener('message')`), and `fetch`/`XHR`; serialize captured frames and
   `window.postMessage` to the isolated script — the only MV3-viable way to read live WS pick
   messages ([world docs](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts);
   [inject-global MV3](https://davidwalsh.name/inject-global-mv3);
   [webRequest can't read WS messages](https://developer.chrome.com/docs/extensions/reference/api/webRequest)).
2. **Framework-state read** (MAIN world): if React-rendered, read pick state off fiber props as a
   second source.
3. **`MutationObserver` DOM fallback** (isolated world): observe the board/results node; also
   observe the pick ticker/chat log to handle the "results only render on tab click" trap
   ([DraftKick](https://draftkick.com/blog/building-draft-sync/)).

**Isolated content script = the trust boundary:** validate/normalize page-derived data (never
trust MAIN-world data blindly), de-duplicate picks by pick number across the three probes,
forward to the backend. **[CHANGE]** Keep the SW alive during the draft via an open
`chrome.runtime` port — or simpler, **have the content script open the WebSocket to localhost
directly** and keep the SW minimal
([MV3 WebSocket guidance](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/23pCzk69Ueo/m/z9GH0J7WBQAJ);
[MV3 2026 guide](https://blog.codercops.com/blog/chrome-extensions-manifest-v3-guide-2026/)).
**Manifest:** MV3; `host_permissions` scoped **only** to CBS fantasy draft/league URLs;
permissions `scripting`, `storage` (+`activeTab`); **no** `declarativeNetRequest`; overlay in a
Shadow DOM.

**D3. `backend/` — Python FastAPI companion (127.0.0.1:8787).**
- **[CHANGE] `jaaffl.data`:** pin **`nflreadpy`** (not `nfl_data_py`); it returns **Polars**
  frames → add `polars`. **DuckDB** queries Polars/Arrow and scans **Parquet** directly (incl.
  nflverse Parquet release URLs): DuckDB = analytics/backtest, Parquet = nflverse snapshots,
  SQLite = app state + append-only draft-event log.
- **[CHANGE] `jaaffl.providers`:** add concrete adapters behind the existing protocol —
  `NflreadpyProvider` (historical + IDs + `load_ff_rankings` ECR + `load_ff_opportunity` expected
  pts), `FantasyFootballCalculatorProvider` (free standard/12-team ADP), `CbsOnPageProvider` (fed
  by the extension: league scoring/roster + CBS projections/injuries). Keep `FantasyProsProvider`,
  `SportsDataIOProvider`, `SportradarProvider` as **disabled stubs**.
- **`jaaffl.league`:** scoring parser consumes the **live CBS scoring map** (5.C4 values as
  default/fallback); model both DST tier tables + K distance bonus.
- **[CHANGE] `jaaffl.api`:** add `WS /ws/draft` (extension → backend) and `WS /ws/recs` (backend →
  overlay/dashboard); keep REST `/recommend`, `/league`, `/snapshot`.
- **Latency budget:** target **< 2 s** per pick. Feasible on a laptop: horizon ≤ ~22 opponent
  picks; Monte-Carlo N≈1–5k rollouts (sub-second) with a vectorized NumPy/Polars sampler, then a
  small end-state roster ILP via OR-Tools CP-SAT (ms–low-seconds). Precompute
  projections/VORP/ADP joins **before** the draft so per-pick work is only "recompute survivors +
  re-optimize."

**D4. `packages/shared/` — contracts.** **[CHANGE]** `LeagueSettings` (Zod + Pydantic) must carry
the **full scoring map** — DST **points-allowed and yards-allowed** tier arrays + K distance-bonus
table — plus explicit roster slots (`WR:3`, `FLEX:{WR,RB}:1`, `K:1`, `DST:1`, `BENCH:8`) and a
`draftOrder` from the live board (not inferred). `DraftEvent` needs a stable `pickNumber` for
cross-probe de-dup. `Recommendation` unchanged.

**D5. `apps/web/` — dashboard.** No change to the intended stack (Next.js App Router + AG Grid
Community + ECharts + TanStack Virtual) — appropriate and free; a **read-only** consumer over
REST/WS. Text-only assistant per ADR 0003.

**D6. Net changes to record as ADRs/notes:** (1) data backbone `nfl_data_py`→`nflreadpy`; (2) $0
fantasy data via nflverse redistribution (`load_ff_rankings`, `load_ff_opportunity`) + FFC free
ADP, removing any *hard* paid-FantasyPros dependency; (3) live capture = MAIN-world monkeypatch +
framework-state + MutationObserver (MV3 `webRequest`/`declarativeNetRequest` can't read WS
messages); (4) `LeagueSettings` must carry the full CBS scoring map (DST dual tiers + K bonus),
read live, defaulted to 5.C4.

### 5.E Sources (markdown links actually used)

**CBS integration & compliance:** [CBS FMD/mock-draft terms](https://www.cbssports.com/info/about/tos/fmd) ·
[CBS Fantasy official extension (chrome-stats)](https://chrome-stats.com/d/com.cbs.sports.fantasy) ·
[cbs_fantasy_sports_api_token_fetcher](https://github.com/geoffharcourt/cbs_fantasy_sports_api_token_fetcher) ·
[ffscrapr](https://cran.r-project.org/web/packages/ffscrapr/ffscrapr.pdf) ·
[Draft Sharks league sync](https://www.draftsharks.com/kb/fantasy-football-league-sync) ·
[DraftKick — building draft sync](https://draftkick.com/blog/building-draft-sync/) ·
[DraftKick — how to build sync](https://draftkick.com/blog/how-to-build-sync/)

**MV3 extension mechanism:** [chrome.webRequest](https://developer.chrome.com/docs/extensions/reference/api/webRequest) ·
[content_scripts `world: "MAIN"`](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts) ·
[Inject a global in MV3 (David Walsh)](https://davidwalsh.name/inject-global-mv3) ·
[Chromium MV3 WebSocket thread](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/23pCzk69Ueo/m/z9GH0J7WBQAJ) ·
[MDN MutationObserver](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver) ·
[Chrome Extensions MV3 guide 2026](https://blog.codercops.com/blog/chrome-extensions-manifest-v3-guide-2026/)

**Data sources:** [nfl_data_py archived → nflreadpy](https://github.com/nflverse/nfl_data_py) ·
[nflreadpy repo](https://github.com/nflverse/nflreadpy) · [nflreadpy docs](https://nflreadpy.nflverse.com/) ·
[nflreadpy PyPI](https://pypi.org/project/nflreadpy/) ·
[load_ff_rankings (ECR)](https://nflreadr.nflverse.com/reference/load_ff_rankings.html) ·
[load_ff_opportunity (expected pts)](https://nflreadr.nflverse.com/reference/load_ff_opportunity.html) ·
[nflverse data schedule (injury gap)](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html) ·
[FFC ADP REST API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api) ·
[FFC non-PPR 12-team ADP](https://fantasyfootballcalculator.com/adp) ·
[FantasyPros API ($5.99/mo)](https://www.fantasypros.com/api-data/) ·
[Fantasy Nerds API docs](https://api.fantasynerds.com/docs/nfl)

**Standard scoring:** [CBS "What is a standard-scoring league?"](https://www.cbssports.com/fantasy/football/news/what-is-a-standard-scoring-league/) ·
[CBS commissioner help — scoring](https://help.football.cbssports.com/s/article/How-do-I-set-up-my-leagues-Scoring-System) ·
[printyourbrackets — CBS scoring summary](https://www.printyourbrackets.com/fantasy-football-point-scoring-system-for-cbs-sports.html)

**UNVERIFIED / caveats:** exact current-URL verbatim CBS/Paramount anti-scraping quotes (ToU
reorganized; `cbsinteractive.com/info/tou` 301s away); CBS draft-room transport/framework (WS vs
polling, React) not publicly documented — design transport-agnostic; free 2025+ injury coverage
via nflverse (advertised but nflverse schedule flagged a lapsed source); Fantasy Nerds free tier;
FantasyPros $5.99 figure (as advertised — verify current).

---

## 6. Subagent 2 — Feature & Factor Expansion

> **Verbatim report from Subagent 2.** Mandate: expand every feature/input/factor/weighting for
> the selected engine components, scoped to this exact roster; justify inclusion/exclusion and
> weights; fully specify the objective math. Scope lock: **12-team, snake, 17 rounds, NON-PPR
> standard, roster QB1/RB1/WR3/(W-R)FLEX1/TE1/K1/DST1 + 8 bench.** Where the answer changes
> because of *zero PPR*, the *WR/RB-only flex*, or *only one mandatory RB*, it is called out.

### 6.A Reasoning log (stepwise)

**Step 1 — Establish the currency: everything reduces to marginal, league-relative points, not
raw points.** Raw projected points are not comparable across positions (a QB ~300, a WR ~180).
The decision-relevant quantity is *how many more points a player gives your starting lineup than
the freely-available alternative at that slot* — VOR/VBD ([FantasyPros VBD](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/);
[FFA](https://fantasyfootballanalytics.net/2024/08/winning-fantasy-football-with-projections-value-over-replacement-and-value-based-drafting.html)).
The master feature list splits into **(Tier-1) features that enter the objective directly**
(VOR/marginal-lineup-value, VONA, risk σ, tier cliffs) and **(Tier-2) features that only refine
the projection μ and its spread σ *before* they hit the objective** (snap share, carry share,
age, red-zone usage, etc.). Confusing the two is the most common design error; usage stats do
**not** get their own additive weight — they move μ/σ. This framing governs the whole report.

**Step 2 — Fix the replacement baselines from THIS roster's starter demand.** League-wide demand
(12 teams): QB 12, TE 12, K 12, DST 12; combined RB/WR pool = RB 12 + WR 36 + flex 12 = **60
RB/WR slots**. Flex is WR-or-RB only → QB/TE/K/DST baselines at **index ≈ 12–13** (shallow → VOR
collapses to near-zero just past elite → *defer/stream*). RB and WR baselines depend on the flex
split (Step 6). Reference framework: Subvertadown VOLS vs VORP vs man-games/BEER
([baselines](https://subvertadown.com/article/guide-to-understanding-the-different-baselines-in-value-based-drafting-vbd-vols-vs-vorp-vs-man-games-and-beer-)).

**Step 3 — Standard scoring re-shapes position value in two quantifiable ways.** (a) *WR value
becomes breadth, not top-end* — removing the reception point strips ~1 pt/catch; a 90-catch
possession WR loses ~90 pts vs PPR while a 45-catch deep threat loses ~45 → non-PPR **compresses
the WR curve, pushes the WR baseline deep (~WR40)**, and re-weights the desirable-WR profile
toward **yards + TDs (air yards, aDOT, deep/red-zone targets)** and away from raw reception
volume. (b) *RB value becomes top-end scarcity* — the elite-RB cliff is steep and flattens fast
(~RB20). This is why **Zero-RB is counter-indicated here** and QBs are *relatively* more valuable
in non-PPR ([DraftSharks 12-team standard](https://www.draftsharks.com/article/fantasy-football-draft-strategy-guide/12-team-standard)).

**Step 4 — Timing is opportunity cost: add VONA/survival on top of static VOR.** Static VOR says
*how good*; VONA says *draft now vs wait* by discounting a player's value by the best value you
expect still available at that position at your **next** pick ([FantasyPros](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/);
[Stanford Stevens](https://stanfordstevens.com/value_of_vona.html)). This needs survival
probabilities → ADP **mean + SD** — and the FFC API delivers per-player `adp`, `stdev`, `high`,
`low`, `times_drafted` (verified live). VONA makes the assistant "live."

**Step 5 — Uncertainty is first-class: carry the whole distribution, tune λ by phase/slot.**
Consensus-averaged projections beat any single source and give a **cross-source spread** → σ/floor/
ceiling ([FFA projection accuracy](https://fantasyfootballanalytics.net/2024/12/which-fantasy-football-projections-are-most-accurate.html)).
`utility = value − λ·σ`; λ is **phase- and slot-aware** (floor-tilt for starters, ceiling-tilt
for cheap late bench). RB durability (~27% of RBs play a full season — [Footballguys](https://www.footballguys.com/article/2025-running-back-milage-myth-what-numbers-say-about-workload-injuries))
is a direct σ-widener concentrated at RB.

**Step 6 — Resolve the flex split empirically, not by assumption.** The split *is* the RB and WR
baselines, so measure it (three $0 ways in Section 6.E). Non-PPR tilts the flex toward RB (WR
curve compressed); prior is RB-heavy. Adopt **8 RB / 4 WR (RB baseline ≈ 20, WR ≈ 40)** default,
expose as the single most important tunable, show how baselines move at 6/6 or 10/2.

**Step 7 — Tiers as the guard rail; K/DST/QB/TE timing as corollaries.** Boris-Chen GMM tiers on
ECR expose *cliffs* the continuous score hides ([Boris Chen draft kit](http://www.borischen.co/p/draft-kit.html))
→ prevent reaching across a tier gap; fire "last-in-tier" urgency. Shallow baselines dictate: **K
last (R17), DST second-to-last (R16), both streamed** (least predictable — only ~4/10 top-drafted
Ks stay K1: [SI](https://www.si.com/onsi/fantasy/nfl/fantasy-football-strategy-guide-when-draft-kicker-defense);
[FantasyPros](https://www.fantasypros.com/2025/06/fantasy-football-strategy-tips-dont-draft-a-kicker/));
**QB/TE deferred** unless elite — exception: an **elite TE's edge over TE12 can exceed WR1's over
WR24**, so a top-2/3 TE at value is a legitimate positional-advantage pick ([Sharp Football](https://www.sharpfootballanalysis.com/fantasy/fantasy-football-te-tiers/)).

### 6.B Master feature / factor table

Legend — **Class:** T1 = enters objective directly; T2 = refines projection μ; T2σ = refines
spread σ/floor/ceiling; MOD = live draft modulator. **Weight** = relative importance for THIS
league (Punt ≈ ignore; Low/Med/High/Core). Numeric defaults that feed the objective are in
Section 6.C and marked *tunable*.

**6.B.1 — Tier-1 objective features (the score is built from these)**

| Feature | Source | Computation | Include/Exclude + why (this league) | Weight | Position/phase modulation |
|---|---|---|---|---|---|
| **Projected fantasy pts μ (per CBS scoring)** | CBS on-page (authoritative settings + projections) blended w/ nflverse `load_ff_rankings` ECR-implied pts + `load_ff_opportunity` xEP prior; optional FP API | Recompute each stat line under exact CBS map (Pass 1/25, TD6, INT−2; Rush 1/10, TD6; Rec 1/10, TD6, **Rec 0**). Simple average of sources | **INCLUDE — Core.** Everything else refines this; must be computed under *zero-PPR* or every skill value is wrong | **Core (1.0)** | Basis for all; recomputed live as CBS updates |
| **Projection spread σ / floor / ceiling** | Cross-source dispersion + historical position weekly residual σ (nflreadpy) | σ_p = blend(cross-source SD, historical same-tier weekly SD); Floor≈10th pct, Ceiling≈90th | **INCLUDE — Core.** Enables risk term; non-PPR RB fragility & TE TD-dependence make σ position-specific | **Core** (risk arm) | RB & TE widest σ; bench weights ceiling; starters weight floor |
| **Positional replacement baseline pts** | Derived from THIS roster + `load_ff_rankings` ranks | Baseline = projected pts at replacement index (QB13, TE13, K13, DST13, RB≈20–24, WR≈40–42), man-games-adjusted, VOLS-blended | **INCLUDE — Core.** Makes positions comparable; set *from this roster's starter counts* | **Core** | Deep WR (breadth), moderate/scarce RB, shallow QB/TE/K/DST |
| **VOR / Marginal-Lineup-Value (flex-aware)** | Computed | MLV_p = gain to optimal replacement-filled 9-man lineup from adding p (bipartite incl. WR/RB flex) — §6.C | **INCLUDE — Core.** Generalizes VOR; auto-encodes roster need + flex; reduces to VOR on empty roster | **Core (currency)** | Falls to bench value once slot filled; flex lets a 4th WR add value |
| **ADP mean** | FFC API (`adp`, non-PPR 12-tm, daily) + CBS on-page ADP | Consensus expected draft slot | **INCLUDE — High.** Drives survival/VONA + "is he a reach?" | **High** | Mid-draft value gaps exploitable |
| **ADP dispersion (stdev, high, low)** | FFC API (`stdev`,`high`,`low`,`times_drafted`) — **verified present** | Survival S_j(N)=1−Φ((N−m_j)/s_j) | **INCLUDE — High.** Without SD, survival is a point-mass; SD is the engine of VONA realism | **High** | Wider SD (rookies/role-change) → hedge earlier |
| **VONA / survival-discounted value** | Computed from ADP mean+SD + your snake schedule | VONA_p = MLV_p − E[MLV of best surviving player at pos(p) by next pick] | **INCLUDE — High.** Draft-now-vs-wait; the "live" differentiator | **High** (κ≈0.5–0.8) | High for RB (scarce), low for WR (deep); rises near your turn & during runs |
| **Tier membership + gap-to-next-tier** | Boris-Chen GMM on ECR (`load_ff_rankings`) | 1-D GMM clustering; flag "last in tier" + inter-tier gap | **INCLUDE — Med/High.** Guard cliffs; last-in-tier urgency | **Med-High** (α≈0.3–0.5) | Steep early cliffs (elite RB, top-3 TE, top-5 QB); flat late |
| **Bye week** | FFC API (`bye`) / nflreadpy | Penalize ≥3 starters sharing a bye; don't stack top-2 RB byes | **INCLUDE — Low.** Real but small; roster-construction constraint | **Low** (≤~3 pts) | Binds mid/late once starters set |
| **Roster-state / slots filled** | Live (your picks) | Feeds MLV need weighting | **INCLUDE — High (structural).** Core to marginal value | **High** | Every pick |
| **Positional-run detector** | Live CBS board vs FFC ADP | If position picks outpace ADP → boost that position's VONA | **INCLUDE — Med.** Runs = main live scarcity shock | **Med** (MOD) | Mid-draft RB runs classic |

**6.B.2 — Tier-2 features that refine projection μ (usage/opportunity)** — these get **no additive
score weight**; they adjust μ (recommend **capped ±10–15%**) and set confidence. Descending non-PPR
importance:

| Feature | Source | Computation | Include/Exclude + why | μ-influence | Modulation |
|---|---|---|---|---|---|
| **Snap share %** | nflreadpy snap counts | Trailing role %, 3–4 game window | **INCLUDE — High.** Durable leading indicator; ≥70% snaps ≈ 2× pts of <50% ([SIS/FRA](https://fantasyrankingsauthority.com/target-share-and-snap-count-rankings)) | High | RB & WR role security; flag committees |
| **Carry share / rush attempts** | nflreadpy weekly/pbp | Share of team RB carries; volume | **INCLUDE — High (RB).** Non-PPR RB value ≈ volume + TDs | High (RB) | RB core; ~0 elsewhere |
| **Opportunity share / weighted opp + xEP** | nflreadpy + `load_ff_opportunity` (xgboost xEP) | Carries+targets weighted by scoring value; actual−xEP = regression signal | **INCLUDE — High.** Stable prior + over/under-performer flag ([ffopportunity](https://ffopportunity.ffverse.com/)) | High | RB (carries+GL), WR/TE (targets) |
| **Target share** | nflreadpy weekly/pbp | Share of team targets | **INCLUDE — Med/High WR/TE.** *Down-weighted vs PPR:* value the yards/TDs targets create, not catch count | Med-High (WR/TE) | Pair with aDOT; short-target WR worth less here |
| **Air yards / aDOT / WOPR / deep-target share** | nflreadpy pbp | WOPR=1.5·tgt-share+0.7·air-yard-share | **INCLUDE — Med/High WR (non-PPR-specific).** Non-PPR rewards big plays/TDs → deep WRs gain | Med-High (WR) | Elevate boom WRs; standard-scoring re-weight |
| **Red-zone & goal-line (inside-5)** | nflreadpy pbp | Weight goal-line > raw RZ; TD-rate prior | **INCLUDE — Med/High.** TDs 6 pts, non-PPR TD-heavy; use goal-line ([xTD](https://www.fantasypoints.com/nfl/articles/2023/xtd-touchdown-regression-candidates)) | Med-High | RB (GL carries), TE (RZ targets), WR |
| **Route participation % / YPRR** | nflreadpy (routes) | Route %, yards per route run | **INCLUDE — Med WR/TE.** Role security + breakout | Med (WR/TE) | Confirms snaps; breakout ID |
| **Team pace / plays / PROE** | nflreadpy pbp | Plays/game, pass-over-expected | **INCLUDE — Med.** Volume multiplier | Med | Pass-pace lifts WR/TE; run lifts RB |
| **QB / passing-environment quality** | nflreadpy + projections | Team pass eff, QB proj | **INCLUDE — Med WR/TE.** Pass-catcher ceiling capped by QB | Med (WR/TE) | — |
| **Target/carry competition & vacated volume** | nflreadpy depth charts, rosters | Teammate hierarchy; vacated targets/carries | **INCLUDE — Med.** Best breakout signal | Med | Rookie WR into vacated targets; new lead RB |
| **O-line quality** | Proxy: nflreadpy adj-line-yards / rush eff | Team rush-eff proxy | **INCLUDE (proxy) — Low/Med RB.** Noisy at $0 | Low-Med (RB) | RB only; mark proxy/UNVERIFIED |
| **Team implied total / Vegas** | Not in $0 list | Proxy via team offensive projection | **PARTIAL/EXCLUDE core.** No clean $0 Vegas feed | Low (proxy) | K/DST streaming benefits most |

**6.B.3 — Tier-2σ features (intrinsic risk/availability — refine σ, floor, μ-haircut)**

| Feature | Source | Computation | Include/Exclude + why | Weight | Modulation |
|---|---|---|---|---|---|
| **Age (position aging curve)** | nflreadpy rosters | WR peak 25–28 (~26.95), decline >30; RB peak ~25.5, cliff after 28 ([PFF](https://www.pff.com/news/fantasy-football-metrics-that-matter-aging-curves-by-position); [4for4](https://www.4for4.com/2025/preseason/production-curves-positional-breakouts-prime-years-and-falloffs-age)) | **INCLUDE — Med (position-specific).** RB age hard signal; WR softer | Med (RB)/Low-Med (WR) | RB μ-haircut + σ-widen ≥28; WR mild >30; QB/TE age-agnostic in range |
| **Injury designation / current status** | CBS on-page + nflreadpy | Q/D/O → availability haircut, floor down | **INCLUDE — High when flagged.** Live, decisive | High (conditional) | Any position; live |
| **Durability / games-missed history** | nflreadpy (career games) | Games-missed rate → σ widener, floor down | **INCLUDE — Med, concentrated at RB.** ~27% RBs full season; high-risk miss ~3× ([Footballguys](https://www.footballguys.com/article/2025-running-back-milage-myth-what-numbers-say-about-workload-injuries)) | Med (RB)/Low | Raises handcuff value of that RB's backup |
| **Rookie / draft capital** | nflreadpy draft picks | Draft round → opportunity prior; wider σ | **INCLUDE — Med.** Capital predicts usage; rookies boom/bust | Med | Rookie RB (early capital) can leapfrog; rookie WR wide σ |
| **Role-change flag (new team/promotion)** | nflreadpy roster+depth diffs | Flag changed team/depth rank | **INCLUDE — Med.** Widens σ | Med | Reduce confidence; ceiling-tilt if late |
| **Historical weekly consistency / boom-bust** | nflreadpy weekly | Weekly σ, % boom & bust games | **INCLUDE — Med.** Calibrates floor/ceiling for λ | Med | Boom-bust fine for bench, bad for must-start |
| **Experience / breakout-age (WR yr-3)** | nflreadpy | Years in league | **INCLUDE — Low.** Minor WR breakout prior | Low | WR only |

**6.B.4 — Schedule & matchup (deliberately down-weighted)**

| Feature | Source | Computation | Include/Exclude + why | Weight | Modulation |
|---|---|---|---|---|---|
| **Full-season SOS (positional)** | nflreadpy-derived / FantasyPros | Sum opponent positional pts-allowed | **INCLUDE — Low (tiebreaker).** Pre-season 17-wk SOS unstable; must not override volume ([Athlon](https://athlonsports.com/fantasy/fantasy-football-strength-of-schedule-for-beginners)) | Low | Tiebreak near-equal players |
| **Early-season SOS (wks 1–4)** | derived | Opp quality wks 1–4 | **INCLUDE — Low.** Most stable slice | Low | Slight lean early starters |
| **Playoff-weeks SOS (wks 15–17)** | derived | Opp quality wks 15–17 | **INCLUDE — Low.** Championship-week tiebreak | Low | Late bench/streamer tiebreak |

**6.B.5 — K / DST (punt tier)**

| Feature | Source | Computation | Include/Exclude + why | Weight | Modulation |
|---|---|---|---|---|---|
| **K: team implied total / dome / FG-rate** | nflreadpy + proxy | Weak TD/FG-volume prior | **INCLUDE — Punt.** Least predictable; VOR≈0 → **draft R17, then stream** | Punt | Never reach; matchup-stream |
| **DST: sacks/INT/TD + pts- & yds-allowed tiers + SOS** | nflreadpy + schedule | Project turnovers/sacks; weight BOTH our pts- and yds-allowed tiers; favor DSTs vs low-total offenses | **INCLUDE — Punt (slight top-tier edge).** **Draft R16, stream by matchup** | Punt/Very-Low | Stream weak-offense opponents; wks 1–3 SOS |

### 6.C Objective function & core math (fully specified for THIS roster)

**6.C.0 Notation.** Starting slots `S = {QB, RB, WR1, WR2, WR3, FLEX(RB|WR), TE, K, DST}`; rostered
players `R`. Per player: μ_p (season pts, CBS scoring), σ_p, floor f_p, ceiling c_p, ADP mean m_p,
ADP SD s_p.

**6.C.1 Stage 0 — Projection blend (produce μ_p, σ_p)**
```
μ_p = Σ_s w_s · proj_{s,p}   over sources s ∈ {CBS_onpage, ECR→pts (load_ff_rankings),
                                              xEP prior (load_ff_opportunity), [FP API opt]}
default w_s = 1/n  (simple average — empirically ≥ weighted; wisdom of crowd)
σ_p = blend( SD across sources , historical same-position/tier weekly-residual SD )
f_p = μ_p − z_lo·σ_p ,  c_p = μ_p + z_hi·σ_p   (z≈1.28 for 10/90 pct)
```
All `proj` recomputed under the **exact CBS map** (Rec = 0). This step is where non-PPR is
enforced. ([Projection-averaging evidence](https://fantasyfootballanalytics.net/2024/12/which-fantasy-football-projections-are-most-accurate.html))

**6.C.2 Replacement baselines — the load-bearing computation for THIS roster.**
Raw starter demand (12 teams): `QB 12 | TE 12 | K 12 | DST 12`; `RB/WR pool = 12·RB(1) + 12·WR(3)
+ 12·flex = 60`. Flex split (default **8 RB / 4 WR**): `RB demand = 12+8 = 20 → VOLS RB20`;
`WR demand = 36+4 = 40 → VOLS WR40`.

**Man-games (BEER) deepening** — rostered starters miss games (byes+injury), covered from the same
pool, so *effective* replacement is deeper. Extra bodies ≈ (starters × games_missed)/17:
```
RB: 20 × ~4 = 80/17 ≈ +4.7 → ≈ RB25   (RBs: only ~27% full season)
WR: 40 × ~2.5 = 100/17 ≈ +5.9 → ≈ WR46
QB: 12 × ~2 = 24/17 ≈ +1.4 → QB13–14
TE: 12 × ~2.5 = 30/17 ≈ +1.8 → TE13–14
```
**Blend toward VOLS for the scarce top end** (`baseline = 0.5·VOLS + 0.5·man-games`):

| Pos | VOLS idx | Man-games idx | **Recommended baseline (tunable)** | Behavior |
|---|---|---|---|---|
| QB | 12 | 13–14 | **QB13** | shallow → **defer** |
| RB | 20 | 25 | **RB22–24** | moderate/scarce top → **anchor early** |
| WR | 40 | 46 | **WR42** | deep → **breadth, wait** |
| TE | 12 | 13–14 | **TE13** | shallow → **defer unless elite** |
| K | 12 | 12–13 | **K13** | flat → **round 17** |
| DST | 12 | 13 | **DST13** | flat → **round 16** |

**Flex-split sensitivity:** 6 RB/6 WR → RB18/WR42; 10 RB/2 WR → RB22/WR38. RB baseline swings ±2
ranks ≈ 2–4 pts VOR on the RB20 bubble — enough to flip mid-round RB-vs-WR → *measure it live*.
**Dynamic VBD:** recompute baselines during the draft from *remaining* startable slots as
positions deplete (a mid-draft RB run raises the effective RB baseline) — the bridge into VONA.

**6.C.3 Stage 1 — Flex-aware Marginal Lineup Value (the value currency).** Define the
replacement-filled baseline lineup `B(R)`: fill every *empty* starting slot with a phantom
replacement at that slot's position (flex phantom = max(RB_base, WR_base)); take the optimal
assignment value.
```
L*(R) = max over position-legal assignments of  Σ_slot μ(player_in_slot)
MLV_p = L*( B(R ∪ {p}) ) − L*( B(R) )
```
Properties: **empty roster** → MLV = μ − baseline = classic VOR (cross-position comparable; does
*not* over-rank raw QB points); **WR/RB flex native** (flex phantom = max(RB_base, WR_base); a 4th
WR still beats the flex phantom); **need automatic** (once QB slot holds a real QB, a 2nd QB's MLV
≈ μ_QB2 − μ_QB1 → auto-deferred; no hand-tuned "need multiplier"). Assignment = Hungarian on 9
slots (or trivially best RB→RB, best 3 WR→WR1-3, flex = max(next RB, next WR)).

**6.C.4 Stage 2 — VONA / survival (opportunity cost, the live engine).** For player `j`, future
overall pick `N`, FFC ADP mean `m_j`, SD `s_j`:
```
Survival  S_j(N) = P(slot_j > N) = 1 − Φ( (N − m_j) / s_j )
N* = your next overall pick (snake schedule)
E[BestAvail_π(N*)] = survival-weighted expected max MLV among position-π players (≈ MLV of the
                     π-player whose cumulative survival first crosses ~0.5)
VONA_p = MLV_p − E[BestAvail_{pos(p)}(N*)]
```
**Worked example:** you hold 3.01 (overall 25); next pick 4.12 (overall 48), 23 away. WR `m=30,
s=8`: `S(48)=1−Φ(2.25)=0.012` → ~1% lasts → high VONA now. RB `m=55, s=10`: `S(48)=1−Φ(−0.7)=0.758`
→ **76%** available → low VONA → safe to wait. Exactly the WR-vs-RB call, from data FFC returns.

**6.C.5 Stage 3 — Risk term & the λ schedule.**
```
Value_p   = MLV_p + κ · max(0, VONA_p)        # value + scarcity urgency, κ≈0.5–0.8 (avoid double-count)
Utility_p = Value_p − λ(phase, slot) · σ̂_p     # σ̂ = σ normalized to season-pts scale
```
λ schedule (**λ>0 = floor-tilt**, **λ<0 = ceiling-tilt**; *tunable*):

| Phase (rounds) | Intent | Default λ | Rationale |
|---|---|---|---|
| R1–2 anchors | mild floor | **+0.2 to +0.4** | protect premium capital; bank the berth |
| R3–6 core starters | mild floor | **+0.1 to +0.3** | reliable weekly starters |
| R7–9 flex/starter fill | neutral | **≈ 0** | best value |
| R10–13 bench upside | ceiling | **−0.2 to −0.4** | cheap lottery tickets |
| R14–17 deep bench | strong ceiling | **−0.3 to −0.5** | pure swings (K/DST exempt = punt) |

**Slot override (dominates phase):** filling your **last open startable slot** at a position →
force floor-tilt (+); surplus depth/stash → force ceiling-tilt (−). Upgrade path: a Stage-6
Monte-Carlo season simulator (maximize P(playoffs)/P(title)) endogenizes this, with λ as the live
proxy.

**6.C.6 Stage 4 — Tier cliff guard.** From Boris-Chen GMM tiers on ECR:
```
CliffBonus_p = (MLV_p − MLV_{best player in next tier down at pos(p)})  if p is LAST in tier, else 0
```
Add `α · CliffBonus_p`, α≈0.3–0.5; hard-flag "about to reach across a tier gap to a needier
position." ([Boris Chen](http://www.borischen.co/2013/08/ppr-draft-tiers-and-clustering_7.html))

**6.C.7 Final canonical score.**
```
Score(p) =  MLV_p                       # flex-aware value core (replacement + need + flex)
          + κ · max(0, VONA_p)          # scarcity urgency (survival from ADP mean+SD), κ≈0.5–0.8
          − λ(phase,slot) · σ̂_p         # risk, λ per schedule
          + α · CliffBonus_p            # tier-cliff urgency, α≈0.3–0.5
          + Σ modifiers                 # bye-stack −, handcuff-synergy +, SOS tiebreak ± (capped ≤~3–5 pts)
```
Rank candidates by `Score(p)`; surface top-N with tier, survival %, VONA, floor/ceiling. **All
Greek-letter weights are tunables with the defaults above.**

### 6.D Position-by-position feature/weighting playbook

**QB (1 · baseline QB13 · DEFER).** VOR ≈ 0 past top ~4–5 → wait (R7–10) unless elite falls.
Non-PPR nudges QBs *slightly* earlier than PPR ([DraftSharks](https://www.draftsharks.com/article/fantasy-football-draft-strategy-guide/12-team-standard))
but they still lose to elite RB/WR. **Dominant feature: rushing yards/TDs**, then pass volume,
team total, weapons, pass-block. λ small. Draft exactly **one**; 2nd QB only a late stash.

**RB (1 mandatory + flex · baseline RB22–24 · ANCHOR EARLY).** Scarcity position: non-PPR + one
mandatory RB makes the elite tier steep, flat by ~RB20 → **Zero-RB counter-indicated**; secure
1–2 bellcows R1–3. **μ features: carry share, snap share, goal-line carries, weighted opp/xEP,
pass-down role. σ: age (cliff 28–29), durability (27% full-season) → widest σ.** VONA urgency
**high**. Handcuffs = premium late ceiling stashes (championship leverage).

**WR (3 + flex · baseline WR40–42 · BREADTH, ACCUMULATE).** Deep baseline → each marginal WR worth
less than PPR, but you need 3–4 → **volume-draft WRs mid-rounds**. **Non-PPR profile: weight air
yards/aDOT/deep-target/red-zone/TD-rate UP, raw reception/target *count* DOWN.** VONA urgency
**low** (breadth) except during a WR run. λ: floor for WR1, ceiling-tolerant WR3/flex/bench.

**TE (1 · baseline TE13 · DEFER unless elite).** Non-premium → TE6–12 flat/replaceable → default
**defer/stream**. **Exception: a top-2/3 elite TE whose edge over TE12 can exceed WR1's over WR24**
([Sharp Football](https://www.sharpfootballanalysis.com/fantasy/fantasy-football-te-tiers/)) — worth
a mid-round pick; below it, punt/stream. High TD-dependence → wide σ.

**K (1 · baseline K13 · ROUND 17, STREAM).** Least predictable (~4/10 top Ks stay K1); edge ≈ 0.
**Never reach; draft last; stream on team-total/dome/matchup.** ([SI](https://www.si.com/onsi/fantasy/nfl/fantasy-football-strategy-guide-when-draft-kicker-defense);
[FantasyPros](https://www.fantasypros.com/2025/06/fantasy-football-strategy-tips-dont-draft-a-kicker/))

**DST (1 · baseline DST13 · ROUND 16, STREAM).** Wildly variable; thin top-tier edge. **Draft
second-to-last; stream weak-offense opponents.** Scoring has **both points- AND yards-allowed
tiers** → favor DSTs facing low-total, low-yardage offenses; wks 1–3 SOS for the drafted one.

**Flex (WR/RB only).** Its league composition *is* the RB/WR baseline (§6.C.2); default 8 RB/4 WR,
**measure live**. On your roster, filled by the §6.C.3 assignment.

**Bench (8 spots, ~R9–17 minus 1 K + 1 DST → ~6 skill stashes).** **Ceiling-tilt (λ<0), high-σ
lottery tickets** — handcuffs, upside young WRs, role-change breakouts. **Skew RB-heavy** (thin
position + injury churn — [DraftSharks](https://www.draftsharks.com/article/fantasy-football-draft-strategy-guide/12-team-standard)).
Early-bench (R9–11) = safer bye/injury insurance; last picks = pure upside swings.

### 6.E Open questions / tunables to calibrate + Sources

**Primary tunable — the flex RB/WR split (sets RB & WR baselines).** Default 8 RB/4 WR → RB≈20,
WR≈40. Three $0 ways to pin it: (1) **ADP-implied** — from FFC non-PPR 12-team ADP, count RB vs WR
in the top-108; flex_RB = (RBs in top-108 − 12), flex_WR = (WRs in top-108 − 36); rerun daily.
(2) **Optimizer-implied** — run the §6.C.3 optimizer over projections across simulated rosters;
tally optimal flex RB vs WR. (3) **Backtest** — from nflreadpy weekly, compute season-long optimal
flex for top-60 RB/WR. Prior RB-heavy; expect 6/6 → 10/2. Sensitivity: 6/6→RB18/WR42; 10/2→RB22/WR38.

**Other tunables (defaults given; knobs):** **κ (VONA)** 0.5–0.8 (raise near your turn/during runs;
*UNVERIFIED optimum — mock-draft backtest*); **λ schedule** (R1–2 sign debatable — A/B vs a
playoff-odds sim); **α (cliff)** 0.3–0.5; **projection-blend weights** start simple-average;
**μ-refinement cap** ±10–15%; **man-games missed assumptions** (RB~4, WR~2.5, QB/TE~2 → swap in
nflreadpy history); **O-line/team-total** proxies only (UNVERIFIED at $0; FP API $5.99/mo would
firm up); **red-zone** prefer goal-line/inside-5; **survival model** normal-approx default (truncated/
skew or direct Monte-Carlo opponent draw as refinement).

**Sources:** [FantasyPros VBD](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/) ·
[FantasyPros glossary](https://support.fantasypros.com/hc/en-us/articles/115005868747) ·
[FP VBD rankings](https://www.fantasypros.com/nfl/rankings/vbd.php) ·
[FFA VOR/VBD](https://fantasyfootballanalytics.net/2024/08/winning-fantasy-football-with-projections-value-over-replacement-and-value-based-drafting.html) ·
[FFA projection accuracy](https://fantasyfootballanalytics.net/2024/12/which-fantasy-football-projections-are-most-accurate.html) ·
[Subvertadown baselines](https://subvertadown.com/article/guide-to-understanding-the-different-baselines-in-value-based-drafting-vbd-vols-vs-vorp-vs-man-games-and-beer-) ·
[Subvertadown snake scarcity](https://subvertadown.com/article/fantasy-snake-drafts-and-strategizing-for-scarcity----snake-value-based-drafting) ·
[VONA value](https://stanfordstevens.com/value_of_vona.html) ·
[FFC ADP API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api) ·
[FFC non-PPR ADP](https://fantasyfootballcalculator.com/adp) ·
[Boris Chen draft kit](http://www.borischen.co/p/draft-kit.html) ·
[Boris Chen clustering](http://www.borischen.co/2013/08/ppr-draft-tiers-and-clustering_7.html) ·
[ffopportunity xEP](https://ffopportunity.ffverse.com/) ·
[load_ff_opportunity](https://nflreadr.nflverse.com/reference/load_ff_opportunity.html) ·
[PFF aging curves](https://www.pff.com/news/fantasy-football-metrics-that-matter-aging-curves-by-position) ·
[4for4 production curves](https://www.4for4.com/2025/preseason/production-curves-positional-breakouts-prime-years-and-falloffs-age) ·
[snap/target-share predictiveness](https://fantasyrankingsauthority.com/target-share-and-snap-count-rankings) ·
[xTD / red-zone regression](https://www.fantasypoints.com/nfl/articles/2023/xtd-touchdown-regression-candidates) ·
[SOS = tiebreaker](https://athlonsports.com/fantasy/fantasy-football-strength-of-schedule-for-beginners) ·
[TE tiers](https://www.sharpfootballanalysis.com/fantasy/fantasy-football-te-tiers/) ·
[When to draft K/DST](https://www.si.com/onsi/fantasy/nfl/fantasy-football-strategy-guide-when-draft-kicker-defense) ·
[Don't draft a kicker](https://www.fantasypros.com/2025/06/fantasy-football-strategy-tips-dont-draft-a-kicker/) ·
[Non-PPR 12-team strategy](https://www.draftsharks.com/article/fantasy-football-draft-strategy-guide/12-team-standard) ·
[RB durability](https://www.footballguys.com/article/2025-running-back-milage-myth-what-numbers-say-about-workload-injuries) ·
[injury finder](https://www.playerprofiler.com/article/nfl-injured-players-injury-finder/)

---
