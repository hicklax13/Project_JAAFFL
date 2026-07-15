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
5. [Platform and Tool Vetting Subagent](#5-platform-and-tool-vetting-subagent)
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

## 5. Platform and Tool Vetting Subagent

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
the top-60 RB/WR by ADP; flex_RB = (RBs in top-60 − 12), flex_WR = (WRs in top-60 − 36); rerun daily.
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

## 7. Subagent 3 — System & Architecture Planning

> **Verbatim report from Subagent 3.** Mandate: integrate the chosen engine (Subagents 1 & 2)
> and the platform findings into concrete, justified build specs mapped onto the existing JAAFFL
> repo. Scope: personal, $0-besides-AI, text-only (ADR 0003). Every tool claim is cited;
> unverifiable items are tagged **[UNVERIFIED]**.

### 7.A Reasoning log (stepwise)

**Step 1 — Anchor the plan to what actually exists, not to a greenfield ideal.** I read the full
scaffold before deciding anything: the domain models, the provider protocol, every engine stub,
the league layer, the warehouse/crosswalk stubs, the API, the shared Zod contracts, the extension,
and the roadmap. **Conclusion: the scaffold's package boundaries already match the chosen engine's
pipeline almost 1:1** — `projections → league(scoring/replacement) → opponents → simulate/optimize
→ recommend`. That is a strong signal to *amend additively, not restructure*. The build plan is a
set of concrete implementations and four targeted schema/tooling changes, not a rewrite. This
honors "Transparent before clever" and ADR 0002 (local-first).

**Step 2 — Identify the smallest set of *breaking* gaps between the scaffold and the chosen
engine.** Exactly four places where the current contracts *cannot* express the engine:
1. `LeagueSettings.scoring` is a flat `list[ScoringRule]` of `(stat, points_per_unit, applies_to)`
   — a purely **linear** map. It structurally cannot represent CBS's **DST points-allowed tiers**,
   **DST yards-allowed tiers**, or the **K 50+ yard bonus**. #1 required schema change.
2. `providers/nflverse.py` imports the **deprecated `nfl_data_py`** and returns **pandas**; the
   chosen backbone is **`nflreadpy`** (Polars) and needs ECR + expected-points, not just history.
3. `RecommendedPick` has no fields for the **score decomposition** (MLV / VONA / risk / cliff). The
   value proposition — and the assistant's "explain" tool — depends on surfacing *why*.
4. The API has ingest (`POST /draft/events` + `WS /draft/ws`) and `GET /recommendation`, but **no
   push channel** to stream recs to the overlay/dashboard.

**Step 3 — Decide the compute topology from the latency constraint backward.** Hard constraint
<2 s/pick, single laptop, no GPU, ≤~22 opponent picks between turns. The only reliable way: **move
everything data-shaped to a pre-draft precompute** (projections μ/σ, league points, replacement
baselines, tiers, ADP join, crosswalk) into an in-memory `DraftContext`, so the **per-pick hot path
is pure arithmetic over arrays**: drop the picked player, recompute survival (closed-form Gaussian,
vectorized NumPy), recompute MLV for a **bounded candidate set** via a tiny Hungarian assignment,
add VONA/risk/cliff, sort. Milliseconds analytically; Monte-Carlo is a *refinement* inside the same
budget, not the default.

**Step 4 — Decide the solver for MLV before writing the optimizer.** MLV is "gain to the optimal
9-slot starting lineup from adding p, including the WR/RB flex" = a **max-weight bipartite
assignment** (players ↔ slots, flex eligibility as a mask) → the **Hungarian algorithm**
(`scipy.optimize.linear_sum_assignment`), microseconds at 9 slots. **Not** OR-Tools CP-SAT on the
hot path: CP-SAT is right for the richer *end-state* 17-slot roster ILP (bench, stacking,
contingency) in the **season simulator (stretch)**, heavyweight for a per-pick assignment. So
**Hungarian per-pick (v1), CP-SAT reserved for stretch** — OR-Tools stays in the `engine` extra.

**Step 5 — Decide Polars-vs-pandas at the provider boundary.** `nflreadpy` is Polars-native and
DuckDB scans Polars/Arrow **zero-copy**. Forcing `pd.DataFrame` adds a round-trip on every load.
**Adopt Polars as the primary frame type at the data/provider boundary**, `.to_pandas()` only where
a downstream lib demands (XGBoost residuals — stretch). Type-hint change to `providers/base.py` +
`polars` in the `data` extra.

**Step 6 — Decide the extension build tool and injection mechanism (where the real risk lives).**
Live capture must run a **MAIN-world** script monkeypatching `WebSocket`/`fetch`/`XHR`. Two
bundlers: **@crxjs/vite-plugin** (reads the existing `manifest.json`, minimal churn, endorsed by the
extension README) vs **WXT** (generates manifest; ships `injectScript`; better-maintained). I
verified WXT supports MAIN-world injection with parent-script messaging, and @crxjs supports
declarative `world:"MAIN"`. **Decision: @crxjs for v1** (keeps `manifest.json` as source of truth,
raw control for the three probes), **WXT as fallback**. Load-bearing manifest change (bundler-
orthogonal): the MAIN-world probe must be `"world":"MAIN"` **`"run_at":"document_start"`** so
`WebSocket` is patched *before* CBS opens its socket (current manifest uses `document_idle` — too
late).

**Step 7 — Decide durability (a mid-draft crash is unrecoverable if wrong).** Of the three stores,
only the **live pick stream** is unrebuildable. So the append-only **draft-event log lives in
SQLite (ACID)** and `DraftState` is a *fold over that log*; ingest writes the log **before**
computing a rec, so a restart replays to the exact state. Parquet (nflverse snapshots) and DuckDB
(analytics/materialized projections) are rebuildable. Crash-safe during the one moment that matters.

**Step 8 — Keep the objective auditable and the heuristics bounded.** `Score(p)=MLV_p +
κ·max(0,VONA_p) − λ(phase,slot)·σ̂_p + α·Cliff_p + capped modifiers`. Every term is computed by a
*named module* and returned in a `ScoreComponents` object; every soft heuristic (bye-stack,
handcuff, injury discount) is **clamped to ±a few points** via `EngineParams` so no rule dominates
the value core. Hyperparameters (κ, λ-table, α, flex split, caps) live in a versioned
`config/engine.json` so calibration tunes them without code changes.

### 7.B Architecture decisions & rationale (incl. changes to the scaffold)

Legend: **[KEEP]** confirm · **[CHANGE]** amend · **[ADD]** new.

| # | Decision | Rationale | Rejected alternative |
|---|----------|-----------|----------------------|
| B1 | **[KEEP]** Python (backend/engine/data) + TS (extension/web); FastAPI on `127.0.0.1:8787`; local-first | Scientific stack + nflverse are Python-native; MV3 must be JS/TS; local-first satisfies ADR 0002/0003 + CBS ToS | Single-language JS engine (loses Polars/SciPy/OR-Tools); Rust (overkill) |
| B2 | **[CHANGE]** `nfl_data_py` → **`nflreadpy`** (Polars); add `polars` to `data` extra; provider return `pd`→`pl.DataFrame` | `nfl_data_py` archived 2025-09-25; `nflreadpy` maintained, Polars, DuckDB zero-copy (verified `load_player_stats/load_ff_rankings/load_ff_opportunity`) | Keep pandas — round-trip every load |
| B3 | **[CHANGE]** `LeagueSettings` full scoring map: keep linear `scoring`, **add** `scoring_tiers` (DST pts+yds allowed) + `scoring_bonuses` (K 50+); mirror in Zod | CBS "standard" DST scores on **both** pts- and yds-allowed tiers; K +2 at 50+; a linear list can't express brackets/thresholds | `scoring_format:"standard"` enum — discards exact values |
| B4 | **[ADD]** Three $0 adapters: `NflreadpyProvider`, `FantasyFootballCalculatorProvider`, `CbsOnPageProvider`; paid ones disabled stubs | Verified $0 non-PPR/12-team stack: nflverse ECR+xEP+history, FFC ADP mean+SD (live 2026, 378-draft), CBS on-page for actual settings/projections/injuries | Hard FantasyPros dependency (violates $0); single source (loses blend) |
| B5 | **[CHANGE]** Capture = **three-probe transport-agnostic**; MAIN-world at **`document_start`**; content script owns the WS; add `scripting` | `webRequest` can't read WS messages; CBS transport **[UNVERIFIED]** → all three probes, de-dup by `pickNumber`; patch `WebSocket` before page constructs it; content-script WS sidesteps SW lifecycle | `webRequest`/`declarativeNetRequest` (can't read WS); SW-owned socket (dies with SW) |
| B6 | **[CHANGE]** Bundler **@crxjs/vite-plugin** (v1); WXT fallback | Reads existing `manifest.json`, minimal churn, raw control for three probes | WXT-first (larger change); plain esbuild (hand-roll HMR) |
| B7 | **[CHANGE]** Per-pick MLV via **`scipy.optimize.linear_sum_assignment`** (Hungarian); CP-SAT reserved for stretch end-state/season ILP | MLV is a pure bipartite assignment (9 slots, flex mask) → Hungarian µs; CP-SAT heavy for hot path | CP-SAT per pick (latency); greedy fill (mishandles flex trade-off) |
| B8 | **[CHANGE]** `RecommendedPick` gains `ScoreComponents` (`mlv, vona, risk_penalty, cliff_bonus, sigma, floor, ceiling, replacement_baseline, modifiers{}`); mirror in Zod | "Transparent before clever": overlay + `explain_recommendation` must show the decomposition | Opaque single `score` (unexplainable) |
| B9 | **[CHANGE]** API: **[KEEP]** `/draft/events`+`/draft/ws`+`/recommendation`; **[ADD]** `WS /recs/ws` push + `GET /league/{id}` | Ingest exists; push channel needed so the overlay updates within <2 s without polling; `/recs/ws` matches the `/draft/ws` convention | Poll `/recommendation` (latency) |
| B10 | **[ADD]** Precompute→hot-path: in-memory `DraftContext` + stateless per-pick `recompute()` | Only way to hit <2 s on a laptop | Recompute projections each pick (blows budget) |
| B11 | **[ADD]** `config/engine.json` (`EngineParams`: κ, λ-table, α, flex split, caps, candidate cap, MC rollouts) via `jaaffl.config` | Calibration tunes without code changes; objective stays declarative | Hard-coded constants (untunable) |
| B12 | **[KEEP]** Web (Next.js + AG Grid + ECharts + TanStack Virtual), read-only; assistant text-only (Responses API) | Free, appropriate; ADR 0003 (no voice) | Realtime/voice (out of scope) |
| B13 | **[ADD]** Schema-parity CI (Pydantic JSON-Schema ↔ Zod round-trip) | Two contract definitions can silently drift | Manual sync (drifts) |

### 7.C Module-by-module build spec

Notation: **[E]** existing stub to implement · **[A]** amend · **[N]** new.

**7.C.1 `packages/shared` (TS contracts).** **[A] `league.ts`**: add `ScoringTierSchema`
(`{stat, brackets:{lower,upper|null,points}[]}`) + `ScoringBonusSchema` (`{stat,threshold,points}`);
add `scoring_tiers`,`scoring_bonuses` to `LeagueSettingsSchema`. **[A] `events.ts`**: add required
`pick_number` on capture events for **cross-probe de-dup** + optional `source:"ws"|"framework"|"dom"`.
**[A] `recommendation.ts`**: add `ScoreComponentsSchema`, embed as `components` on
`RecommendedPickSchema`. **[N]** canonical example JSON fixtures for schema-parity CI.

**7.C.2 `apps/extension` (capture layer — highest risk).** **[A] `manifest.json`**: third
`content_scripts` entry → `src/inject/cbs-main.inject.ts` with `"world":"MAIN"`,
`"run_at":"document_start"`; add `"scripting"`; keep host perms narrow (CBS + `127.0.0.1:8787`).
**[N] `src/inject/cbs-main.inject.ts` (MAIN world)** — three probes: (1) WS monkeypatch (wrap
`send` + `message`); (2) fetch/XHR monkeypatch; (3) framework-state read (React fiber props);
relay via `window.postMessage({source:"jaaffl-main",...})`. **[A] `src/content/cbs-draft.content.ts`
(ISOLATED — trust boundary)**: receive frames + `MutationObserver` on board/ticker; **de-dup by
`pick_number`**; validate via `parse.ts`; open `WS /draft/ws`; mount overlay. **[E] `src/lib/parse.ts`**:
implement `parseLeagueSettings` (roster slots, flex eligibility, **full scoring incl. DST tiers + K
bonus**, team count, **draft order from board**) + `parseDraftEvent`; golden-fixture-driven. **[E]
`src/overlay/overlay.ts`**: subscribe `WS /recs/ws`; render best pick + top-5 with the `components`
decomposition + next-turn survival %.

**7.C.3 `jaaffl.domain` + `jaaffl.config`.** **[A] `domain/models.py`**: add `ScoringTier`,
`ScoringBonus`, `scoring_tiers`/`scoring_bonuses` on `LeagueSettings`; add `ScoreComponents` on
`RecommendedPick`; add `Capability.EXPECTED_POINTS` (+ optional `DRAFT_PICKS`). **[A] `config.py`**:
add `jaaffl_season`, `jaaffl_enable_ffc=True`, `jaaffl_ffc_scoring="standard"`, `jaaffl_ffc_teams=12`,
`jaaffl_engine_params_path`, `jaaffl_candidate_cap=180`, `jaaffl_mc_rollouts=2000`; **[N] `EngineParams`**
from `config/engine.json`.

**7.C.4 `jaaffl.{ingest, league, data, providers}`.** **[E] `ingest/cbs.py`**: implement
`normalize_league_settings`/`normalize_draft_state`; **[N] `ingest/log.py`**: append every
`DraftEvent` to the SQLite log (monotonic `seq`, `pick_number`) *before* engine work; `fold_state`
rebuilds `DraftState` (crash-safe replay). **[A] `league/scoring.py`**: extend `league_points` to
evaluate linear rules **+ tiered brackets (DST pts/yds allowed) + threshold bonuses (K 50+)**. **[E]
`league/replacement.py`**: keep `starter_demand`; implement `replacement_values` = rank by league
points within position, value at **dedicated demand + allocated flex share** (flex split from
`EngineParams`); baselines RB≈22–24, WR≈40–42, QB/TE/K/DST≈13; **[N]** BEER/man-games blended toward
VOLS at the scarce top end. **[A] `providers/nflverse.py` → `NflreadpyProvider`**: `nflreadpy`;
caps `{HISTORICAL_STATS, RANKINGS, EXPECTED_POINTS}`; history→`load_player_stats`, ECR→`load_ff_rankings`,
xEP→`load_ff_opportunity`; map ids via nflverse crosswalk (`load_ff_playerids`/`load_players` —
confirm exact Python name **[VERIFY minor]**). **[N] `providers/ffc.py`**: cap `ADP`; GET
`.../api/v1/adp/{scoring}?teams=12&year={season}`; parse → `{canonical_id:{adp,stdev,high,low,
times_drafted,bye}}`; **cache daily**; note FFC mocks are 15-round → ADP thins past ~180, fall back
to ECR for deep-round survival. **[N] `providers/cbs_onpage.py`**: caps `{PROJECTIONS,INJURIES,
RANKINGS}` + authoritative `LeagueSettings`; **reads the CBS snapshot from the warehouse** (fed by
the extension), not a network fetch. **[E] `data/warehouse.py`** + **[E] `data/crosswalk.py`**:
deterministic nflverse-ID join + fuzzy fallback (name+team+pos), resolutions persisted in SQLite.

**7.C.5 `jaaffl.engine` — the pipeline.** **[A] `projections.py::build_projections`** *(S0)*: blend
CBS on-page + ECR + xEP [+ optional FP], **all recomputed under the exact CBS map** via
`league.scoring`; **[A]** return `{stat_line, mu, sigma, floor, ceiling}`; σ/floor/ceiling from
cross-source spread. **[N] `tiers.py`** *(S4)*: `sklearn.mixture.GaussianMixture` on ECR → `tier` +
`cliff_bonus` (adds `scikit-learn` to `engine` extra). **[A] `optimize.py`**: **[N]
`marginal_lineup_value(...)`** via `scipy.optimize.linear_sum_assignment` over 9 slots (flex mask,
replacement-filled); **[E]** keep `optimize_roster` as CP-SAT for stretch. **[E]
`opponents.py::pick_probabilities`** *(S2)*: closed-form `S_j(N)=1−Φ((N−m_j)/s_j)` (vectorized NumPy);
horizon from the live board; **[N]** optional per-manager priors from `manager_tendencies`. **[E]
`simulate.py::simulate_drafts`** *(MC refinement + stretch)*: vectorized MC rollouts for VONA's
`E[best available]` when analytic is insufficient; the **stretch season simulator** reuses it → 
playoff/championship odds. **[E] `recommend.py::recommend`** *(orchestrator)*: assemble the score,
populate `ScoreComponents`, sort; reads `DraftContext` + live `DraftState`; **analytic VONA is the
v1 default**, MC opt-in within budget.

**7.C.6 `jaaffl.{api, assistant}`.** **[A] `api/app.py`**: keep existing; **[N]** `WS /recs/ws`,
`GET /league/{id}`; ingest handler: append log → fold state → `recommend` → broadcast on `/recs/ws`.
**[E] `assistant/tools.py::dispatch`** *(Stage 7, text-only)*: wire typed tools to warehouse/engine;
`explain_recommendation` returns the `ScoreComponents` breakdown in prose; Responses API; no voice.

**7.C.7 `apps/web`.** **[KEEP]** stack; consume `/recommendation` + `WS /recs/ws`; board (AG Grid),
distributions/tiers (ECharts), survival curves, manager-tendency panel as history accrues. Secondary
to the overlay for v1.

### 7.D Compute & latency plan + library choices

**Budget:** target **<2 s/pick**; **<200 ms** analytic, **<2 s** with MC VONA at N≈1–2k. Worst case
= pick 1 (~300-player pool, horizon ~22).

**Pre-draft precompute (once) → `DraftContext`:** projections μ/σ/floor/ceiling; league points per
player; replacement baselines + flex allocation; tiers + cliff bonuses; FFC ADP mean/SD joined by
canonical id; crosswalk. Materialized to DuckDB/Parquet, held in memory.

**Per-pick hot path (stateless `recompute()`):** (1) drop picked player (O(1) mask); (2) vectorized
survival `1−Φ((N−m)/s)` over available (~µs/300 players); (3) bounded candidates top-K
(`candidate_cap≈180`); (4) MLV per candidate via `linear_sum_assignment` on a 9×(owned+replacement+
candidate) matrix, base lineup cached, dominance shortcut (~tens of ms); (5) analytic VONA/risk/cliff/
modifiers (MC only if enabled); (6) assemble + sort.

**Libraries:** **NumPy** (vectorized survival/expected-max), **Polars** (nflverse-native, zero-copy
to DuckDB) **[ADD `data`]**, **SciPy `linear_sum_assignment`** (Hungarian MLV), **OR-Tools CP-SAT**
(stretch end-state/season ILP), **scikit-learn `GaussianMixture`** (tiers) **[ADD `engine`]**,
**DuckDB+Parquet+SQLite** (analytics/cold/ACID), **Optuna** (offline tuning, never hot path).
Single-thread suffices; MC is embarrassingly parallel (NumPy batch). No cloud/GPU.

### 7.E Calibration, backtesting & testing plan

- **E1 — Measure the flex RB/WR split from FFC ADP.** Rank RB+WR by ADP; fill 12 dedicated RB + 36
  dedicated WR first; the next 12 by ADP fill the flex → `flex_RB=(#RB in top-60)−12`, `flex_WR=(#WR
  in top-60)−36`; add MC variance from `stdev`. **Honest caveat: the measured split may differ from
  Subagent 2's default — non-PPR RB scarcity can push a more RB-heavy flex; measuring is the point.**
  → `EngineParams.flex_split`. `scripts/calibrate_flex_split.py`.
- **E2 — Tune κ, λ-table, α, caps via mock-draft backtests.** Opponents draft by ADP+noise (FFC
  `stdev`); our agent by `Score(p)`; score final rosters by projected **starting-lineup** points
  (stretch: simulated-season wins). **Optuna** over (κ, λ, α, caps, flex_split) maximizing mean
  value/playoff-odds **across all 12 slots**; also evaluate vs non-ADP opponents (VBD-only,
  need-based) to avoid self-reference. `scripts/tune_engine_params.py` → `config/engine.json`.
- **E3 — Validate the projection blend.** Backtest μ_p vs realized points 2021–2024 (`load_player_stats`
  recomputed under CBS map); MAE/RMSE/Spearman of blend vs each single source; require blend ≥ best
  single source; calibrate σ_p by interval coverage (~80% of realized inside the 80% band); split by
  season. `scripts/validate_projections.py`.
- **E4 — Regression-test capture (transport UNVERIFIED).** Save observed frames as **golden
  fixtures**; unit-test `parse.ts` + three-probe **de-dup**; **Playwright** drives a saved draft-room
  HTML fixture for the `MutationObserver` path; **manual-paste fallback** test.
- **E5 — Schema-parity CI.** JSON Schema from Pydantic; round-trip canonical payloads through
  Pydantic + Zod; fail on divergence.
- **E6 — Engine offline evaluation.** Simulated-league tournament (our agent every slot vs ADP
  opponents); report mean starting-lineup points + **stretch** MC playoff/championship odds vs
  **VBD-only** and **ADP-only** baselines; success = ≥ baselines with significance across slots.
  The honest efficacy check Subagent 1 flagged is missing from the literature.
- **E7 — Latency tests.** Benchmark `recompute()` worst case; assert p95 <2 s; CI perf gate.

### 7.F Phased build plan (mapped to ROADMAP; v1 vs stretch)

Tags: **[v1]** deployable, **[str]** stretch.

- **Stage 1 — CBS sync [v1].** @crxjs; MAIN-world injector (`document_start`, three probes); isolated
  content script (de-dup, WS); `ingest/log.py` SQLite log + `fold_state`. *Exit:* picks stream +
  replay after restart.
- **Stage 2 — Normalize league settings [v1].** `parse.ts` + `ingest/cbs.py`; **B3 scoring change**
  (tiered DST + K bonus) end-to-end; draft order from board; snapshot leagues. *Exit:* `LeagueSettings`
  round-trips the exact CBS scoring map.
- **Stage 3 — Warehouse [v1].** `warehouse.py` (Parquet/DuckDB/SQLite) + `crosswalk.py`. *Exit:*
  snapshots materialized; ids resolve.
- **Stage 4 — Data tiers [v1].** `NflreadpyProvider`, `FantasyFootballCalculatorProvider`,
  `CbsOnPageProvider`; paid off. *Exit:* projections/ECR/xEP/ADP/CBS-on-page queryable behind the
  protocol.
- **Stage 5 — Transparent engine [v1 core].** `league.scoring`/`replacement` → `projections` (S0) →
  `tiers` (S4) → `optimize.marginal_lineup_value` (S1) → `opponents` survival + analytic VONA (S2) →
  risk (S3) → `recommend` + `ScoreComponents`. **[str]:** MC VONA; **rest-of-season Monte-Carlo
  simulator → playoff/championship odds** (CP-SAT end-state); XGBoost residuals; offline RL audit.
  *Exit:* `GET /recommendation` returns a decomposed, tuned rec in <2 s.
- **Stage 6 — Two-surface UI.** Overlay (best pick + decomposition + survival %) **[v1]**; Next.js
  dashboard **[v1 lite / str for depth]**; `WS /recs/ws` **[v1]**.
- **Stage 7 — AI assistant [v1 lite].** Wire typed tools; `explain_recommendation` prose over
  `ScoreComponents`; text-only. **[str]:** file-search league rules, web-search injuries.
- **Cross-cutting.** E1–E3 **[v1]** (feed `config/engine.json` before the draft); E4 golden fixtures
  **[v1]**; E5 parity CI **[v1]**; E6 tournament **[str]**; E7 perf gate **[v1]**; per-manager
  tendencies **[str]** (wire the log day one, model once history accrues).

**v1 definition of done:** live CBS picks → decomposed, league-correct, risk-aware, flex-aware
recommendation in the overlay within 2 s, on the $0 data tier, with calibrated params and crash-safe
replay. **Stretch = the season simulator (true playoff/championship-odds objective), MC-rollout VONA,
residual ML, per-manager modeling, RL audit.**

### 7.G Risks & mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **CBS draft-room transport UNVERIFIED** | High | Three-probe transport-agnostic capture + de-dup; DOM `MutationObserver` fallback; **manual-paste fallback**; golden-fixture tests once frames observed; `document_start` timing |
| **Free live-injury gap** (nflverse source lapsed post-2024) | Med | CBS on-page injury designations + official NFL report; optional $5.99 FantasyPros behind the flag |
| **$0 projection quality** | Med | Blend CBS + ECR + xEP under the exact CBS map; validate (E3); label forward-year **ESTIMATED** |
| **MV3 SW lifecycle** | Med | Content script (not SW) owns the WS; minimal SW; heartbeat/reconnect |
| **FFC ADP thin past R15 / off-season empty** (`year=2025` returns "No ADP data") | Low-Med | Query current `season` only; fall back to ECR for deep-round survival |
| **Calibration overfits ADP opponents** | Med | Evaluate vs VBD-only + need-based; cross-slot generalization; hold-out seasons |
| **Contract drift (Zod vs Pydantic)** | Low-Med | Schema-parity CI (E5) |
| **ToS / personal-use compliance** | High-if-ignored | Local-only, user's own session, no redistribution, narrow host perms, compliance doc as gate, non-commercial license; **no** `webRequest`/`declarativeNetRequest` |
| **nflreadpy ID-crosswalk exact fn name [VERIFY]** | Low | Confirm from load-functions ref; fuzzy fallback covers CBS/FFC |

### 7.H Sources

**Verified for this plan:** nflreadpy — [docs](https://nflreadpy.nflverse.com/) ·
[load functions](https://nflreadpy.nflverse.com/api/load_functions/) · [PyPI](https://pypi.org/project/nflreadpy/) ·
[repo](https://github.com/nflverse/nflreadpy) *(confirmed `load_player_stats`, `load_ff_rankings`,
`load_ff_opportunity`; Polars)*; FFC ADP API — [KB](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api) ·
live `https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year=2026` *(2026 non-PPR/
12-team; per-player `adp, adp_formatted, stdev, high, low, times_drafted, bye, name, position, team,
player_id`; `meta.total_drafts=378`; daily; 15-round)*; WXT — [content scripts](https://wxt.dev/guide/essentials/content-scripts.html) ·
[MAIN-world options](https://wxt.dev/api/reference/wxt/interfaces/mainworldcontentscriptentrypointoptions);
@crxjs — [npm](https://www.npmjs.com/package/@crxjs/vite-plugin) · [site](https://crxjs.dev/) ·
[2025 framework comparison](https://redreamality.com/blog/the-2025-state-of-browser-extension-frameworks-a-comparative-analysis-of-plasmo-wxt-and-crxjs/);
[SciPy `linear_sum_assignment`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html);
[OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver);
[sklearn `GaussianMixture`](https://scikit-learn.org/stable/modules/generated/sklearn.mixture.GaussianMixture.html);
[`world:"MAIN"` content scripts](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts);
[chrome.webRequest](https://developer.chrome.com/docs/extensions/reference/api/webRequest);
[MDN MutationObserver](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver);
[DuckDB Polars](https://duckdb.org/docs/guides/python/polars.html).

**[UNVERIFIED] / caveats:** CBS draft-room transport & framework (design transport-agnostic); exact
nflreadpy ID-crosswalk function name (confirm from load-functions ref); exact CBS DOM/state shapes
(map from live capture); Subagent 2's flex-split default (must be measured — E1, likely revises
RB-heavy in non-PPR); FantasyPros $5.99/mo (as advertised).

---

## 8. Subagent 4 — Documentation & Fidelity Review

> **Verbatim report from Subagent 4.** Adversarial audit of `docs/draft-system-design.md` (§1–§7
> as it stood pre-synthesis), `config/league.json`, and `CLAUDE.md`. Line numbers below reference
> the pre-§8 draft the auditor read; they are evidence of the audit, not live anchors. The
> orchestrator applied the C1 fix and the §5 label/anchor cleanup before publishing, and closes the
> Part-D items in §10.

*Adversarial audit. Every finding cites a file/section/line. Verdict in Part E.*

### 8.A Fidelity audit — are the fixed settings preserved EXACTLY?

**Result: PASS in all three files. Zero deviations, paraphrases, or arithmetic errors in the
settings themselves.** Every number and label is reproduced verbatim.

| Setting (authoritative) | doc §2 | `config/league.json` | `CLAUDE.md` | Status |
|---|---|---|---|---|
| Draft Type: **Snake** | L60 | L9 + verbatim L49 | L14 | ✓ exact |
| Teams: **12** | L61 | L10 + verbatim L50 | L15 | ✓ exact |
| Draft Order: **Decided in-person, then entered into CBS Sports system** | L62 | L12 + verbatim L51 | L16 | ✓ exact (verbatim, all 3) |
| Scoring Format: **Standard** | L63 | L16 + verbatim L52 | L17 | ✓ exact |
| Draft Rounds: **17** | L64 | L18 + verbatim L53 | L18 | ✓ exact |
| QB **1** / RB **1** / WR **3** / WR-RB **1** / TE **1** / K **1** / DST **1** / Bench **8** | L66–73 | L20–27 + verbatim L54 | L18 | ✓ exact (incl. **WR=3** and the **WR/RB** flex) |
| Derived: **9 starters + 8 bench = 17 = rounds** | L77 | L31–35 | L20 | ✓ consistent |
| Flex = **WR or RB only** (no TE/QB) | L78 | L36–40 (`excludes: TE,QB,K,DST`) | L20–21 | ✓ consistent |
| **Standard = non-PPR** (0/reception) | L80 | L17 | L21 | ✓ consistent |
| League starter demand math (60 RB/WR of 108) | L84–86 | — | — | ✓ arithmetic checks (12+36+12=60; 12×9=108) |

**Cross-checks performed and passed:** no body section contradicts a fixed setting. Searched the
full doc for `PPR`, `10/14-team`, `15/16/18-round`, `WR=2`, `auction`, `non-snake` — every
`non-PPR`/`12-team`/`17-round`/`Standard`/`snake` usage is correct. The only `15-round` references
correctly describe **FFC's external mock-draft data format** (flagged as a limitation vs. our
17-round league, with an ECR fallback for deep rounds) — not a misstatement of league settings. The
persistent-memory file carries an `immutable:true` flag, an `agent_usage_contract`, and a "never
paraphrase/change" comment.

### 8.B Completeness checklist

| # | Required element | Status | Location | Note |
|---|---|---|---|---|
| a | Deep research on quantitative snake-draft methods + claim validation + SOTA ID | **PRESENT** | §4 (4.A 10-step reasoning; 4.B 11-method catalog w/ evidence tags; 4.C SOTA; 4.D ranked core) | Genuinely adversarial ("no peer-reviewed optimal live snake-draft solver exists"; equilibrium claim flagged simulation-based; Becker & Sun UNVERIFIED/paywalled) |
| b | Feature/factor/weighting expansion + include/exclude justification, scoped | **PRESENT** | §6.B (5 tables, each "Include/Exclude + why (this league)" + Weight); §6.C math; §6.D playbook | Strong T1/T2/T2σ separation |
| c | System/architecture/build specs + tool selection rationale + CBS scope | **PRESENT** | §5 (CBS B1–B6, data tiers, stack); §7 (B1–B13 w/ rejected alts, 7.C module spec, 7.D latency, 7.F phased, 7.G risks) | |
| d | Each subagent's explicit STEPWISE reasoning, clearly labeled | **PRESENT** | §4.A (Steps 1–10), §5.A (1–8), §6.A (1–7), §7.A (1–8) — all "Step N —" | |
| e | Citations/links throughout | **PRESENT** | §4.E, §5.E, §6.E, §7.H + dense inline links | Abundant; evidence-quality tags defined |
| f | Persistent memory established AND referenced as required-before-work | **PRESENT** | `config/league.json` (`agent_usage_contract`); `CLAUDE.md` ("read first"); §2; §3 ("written before any research") | |
| g | Draft-strategy recommendations scoped to settings | **PARTIAL** | §4.D, §6.D (defer QB/TE, anchor RB, WR breadth, Zero-RB counter-indicated, K R17/DST R16) | Present but **distributed**; no single round-by-round playbook yet → **§10 must consolidate** |

### 8.C Inconsistencies & errors found (with exact fixes)

**C1 — [PRIMARY / substantive] Flex-split MEASUREMENT universe contradicts itself: "top-108" vs
"top-60".** §6.E method (1) said "count RB vs WR in the **top-108**…"; §6.E method (3) and §7.E1 use
"**top-60**". Only **top-60** is self-consistent: the RB/WR startable pool is 60 (12 RB + 36 WR + 12
flex), so `flex_RB + flex_WR = 60 − 48 = 12`. **Fix:** §6.E method (1) "top-108" → "**top-60 (RB/WR
startable pool)**"; canonical method = §7.E1. *(Orchestrator: applied.)*

**C2 — [presentational drift, reconcilable] Three coexisting replacement-baseline ranges.** §4:
RB18–22/WR40/index-12; §5: RB 18–24 / WR 40–48; §6 & §7: RB22–24 / WR40–42 / ≈13. Not a hard
contradiction — §6.C.2 bridges them (VOLS RB20 → man-games RB25 → 0.5/0.5 blend → RB22–24). **Fix:**
§10 states **one canonical set (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13)** and labels RB18–22/WR40/index-12
the first-principles pre-deepening anchors.

**C-note (requested check — no action):** the feared **"8 WR / 4 RB" transposition does NOT exist**.
Every flex-split statement is the canonical **8 RB / 4 WR (RB baseline ≈20, WR ≈40)**; sensitivity
cases (6/6→RB18/WR42; 10/2→RB22/WR38) are all RB-anchored and arithmetically correct. **Do NOT flip
any section WR-heavy — that would introduce an error.**

**Consistency checks that PASSED:** objective function identical where repeated (§6.C.7 == §7 Step 8);
κ (0.5–0.8) and α (0.3–0.5) consistent; **K R17, DST R16** consistent across §6; verified/UNVERIFIED
tags consistent (FFC fields verified; flex split measure-live; nflreadpy crosswalk `[VERIFY]`; Becker
& Sun paywalled). The worked VONA example is numerically correct (3.01=overall 25; 4.12=overall 48;
survival 1.2% / 76%).

**C3 — [minor] TOC anchor for item 5 likely broken** (double vs single hyphen from the removed
parenthesis). **Fix:** correct the anchor / relabel. *(Orchestrator: relabeled §5 to "Platform and
Tool Vetting Subagent" with a matching anchor.)*

**C4 — [minor readability] Subagent numbering non-contiguous** (§5 platform agent unnumbered between
1 and 2). *(Orchestrator: relabeled for clarity.)*

**C5 — [minor] Partial roster-slot enumeration in an example** (§5.D4 lists only WR/FLEX/K/DST/BENCH).
Illustrative; ensure the actual `LeagueSettings` schema enumerates **all 8** slot types.

### 8.D Gaps the synthesis (§10) MUST close

1. **Executive recommendation** — one-paragraph "the system is X, the strategy is Y," carrying
   forward the honest caveat that **no peer-reviewed optimal live snake-draft solver exists** so the
   build is not oversold.
2. **Consolidated round-by-round draft-strategy playbook (R1–R17)** — the element-(g) gap. Fold §4.D
   + §6.D into one table.
3. **One canonical replacement-baseline statement** (resolves C2): RB≈22–24, WR≈40–42, QB/TE/K/DST≈13.
4. **One canonical objective-function + tunable-defaults block**: `Score(p)=MLV + κ·max(0,VONA) −
   λ(phase,slot)·σ̂ + α·Cliff + capped mods`, κ 0.5–0.8, the λ schedule, α 0.3–0.5, flex **8 RB/4 WR**.
5. **Canonical flex-split MEASUREMENT method** (resolves C1): standardize on **top-60**.
6. **Consolidated tunables / open-items / next-steps**, naming: measure the flex split (E1); confirm
   the nflreadpy crosswalk fn `[VERIFY]`; CBS transport UNVERIFIED → three-probe mitigation; free
   live-injury gap → CBS on-page + optional FantasyPros; efficacy unproven → the E6 offline
   tournament is the validation gate.
7. **Explicit v1-vs-stretch line**: v1 = live decomposed rec in <2 s on the $0 tier; stretch = season
   simulator / MC-VONA / residual ML / RL audit.

### 8.E Overall verdict

**Faithful: YES (unqualified).** All fixed settings appear verbatim and unaltered in the doc §2,
`config/league.json`, and `CLAUDE.md` — including **WR=3**, the **WR/RB-only flex**, **Standard=non-PPR**,
**in-person→CBS draft order**, and **9 starters / 8 bench / 17 rounds**.

**Complete: YES, with one consolidation gap** — draft-strategy recommendations are present but not yet
consolidated into a single round-by-round playbook (§10's job, itemized in Part D).

**Internally consistent: MOSTLY — one substantive fix required (C1: §6.E "top-108" → "top-60").**
Everything else is reconcilable presentational drift (C2, to converge in §10) or cosmetic (C3/C4/C5).
The suspected "8 WR / 4 RB" transposition does not exist — the doc is uniformly "8 RB / 4 WR".

**Gate recommendation: PASS conditional on (1) applying the C1 top-60 fix, and (2) §10 delivering the
Part-D consolidations.** *(Orchestrator: C1 applied; §10 delivers the Part-D consolidations below.)*

---

## 9. Orchestrator verification log

The orchestrator independently re-verified the highest-impact, load-bearing claims from the
subagent reports with its own web searches/fetches, rather than trusting them on report. Outcomes:

| # | Claim (source) | Verification method | Outcome |
|---|---|---|---|
| V1 | The academic state-of-the-art references are real and correctly characterized (Subagent 1 §4) | WebSearch on draft-optimization DP/MDP literature | **CONFIRMED.** Fry, Lundberg & Ohlmann (stochastic DP, proven intractable → heuristic), Becker & Sun (MIP for draft + lineup), Lee & Liu / Cambridge JDM (competitive sequential decision-making, the large-sample "groupthink is beatable" study), and Matthews et al. (belief-state MDP + Bayesian Q-learning, **FPL not snake**) all exist and are characterized correctly, including the honest "**no peer-reviewed optimal live snake-draft solver exists**" conclusion. |
| V2 | `nfl_data_py` is deprecated in favor of `nflreadpy` (Platform §5 / Subagent 3 §7) | WebSearch | **CONFIRMED.** `nfl_data_py` deprecated; repo **archived read-only 2025‑09‑25**; users directed to `nflreadpy` (Polars). The scaffold's `nfl_data_py` reference is a real, required correction. |
| V3 | The Fantasy Football Calculator ADP API is genuinely free and supports non-PPR + 12-team (Platform §5, Subagent 2 §6) | WebFetch of the FFC API docs | **CONFIRMED.** "Free for personal **and** commercial use"; endpoint `…/api/v1/adp/{scoring}?teams=12&year=…`; JSON; updates daily; attribution requested. |
| V4 | The FFC ADP response carries a per-player **`stdev`** (the dispersion the entire VONA/survival engine consumes) (Subagent 2 §6.C.4) | WebFetch of the **live** endpoint `…/adp/standard?teams=12&year=2024` | **CONFIRMED live.** Each player object has `player_id, name, position, team, adp, adp_formatted, times_drafted, high, low, stdev, bye` (e.g., McCaffrey `stdev: 0.5`). The VONA data plumbing works end-to-end on the $0 tier. |
| V5 | **Standard (non-PPR) scoring makes Zero-RB counter-indicated** — the single most actionable strategic conclusion (Subagent 1 §4.A Step 4, Subagent 2 §6) | WebSearch on Zero-RB in non-PPR | **CONFIRMED.** Multiple sources: "Zero RB is a terrible idea in any non-PPR league"; pass-catching RBs lose their reception value; the recommended non-PPR alternative is **Hero-RB** (one anchor RB early, then accumulate) — which is exactly the emergent behavior of the recommended engine for this roster. |

**Cross-report consistency (orchestrator check).** After the C1 fix, the four subagent reports are
mutually consistent on the load-bearing quantities: the objective function, the replacement
baselines (once §4/§5's first-principles anchors are read as pre-man-games figures — reconciled in
§10), κ/λ/α defaults, the **8 RB / 4 WR** flex default, and the K‑R17/DST‑R16 timing. The fidelity
audit (§8) confirms the immutable settings are reproduced verbatim in all three artifacts.

**What remains genuinely UNVERIFIED (carried into §10's open items — not hidden):**
- **CBS draft-room transport & DOM/state shapes** — not publicly documented; the mitigation is the
  three-probe, transport-agnostic capture + de-dup, confirmed *after* live frames are observed.
- **Exact `nflreadpy` ID-crosswalk function name** (`load_ff_playerids` / `load_players`) — confirm
  from the load-functions reference; a fuzzy name+team+position fallback covers CBS/FFC regardless.
- **The flex RB/WR split** (default 8/4) — must be *measured* from live non-PPR 12-team FFC ADP
  (§10 method, top-60); non-PPR may push it more RB-heavy.
- **Engine efficacy** — no external proof exists (V1); the project's own **offline simulated-league
  tournament (§7.E6)** is the validation gate, not a vendor claim.
- **Free live-injury coverage post-2024** — incomplete via nflverse; mitigated by CBS on-page
  designations (+ optional $5.99 FantasyPros).

---

## 10. Reflection & Synthesis (orchestrator)

This section draws the conclusions the earlier sections earned. It consolidates the four subagent
reports and the verification log into (10.1) an executive recommendation, (10.2) the synthesized
system, (10.3) the canonical engine spec, (10.4) a round-by-round draft playbook, (10.5) the build
plan at a glance, (10.6) the tunables/open-items list, and (10.7) scope & compliance.

### 10.1 Executive recommendation

**The system:** a **local-first, $0 (besides AI), personal-use CBS live-draft assistant** — a
Manifest V3 browser extension that reads the draft from your own authenticated CBS session (via a
transport-agnostic three-probe capture) and streams picks to a local FastAPI backend, which runs a
**transparent, Monte-Carlo-augmented Value-Based-Drafting engine** and pushes a decomposed
recommendation to an in-page overlay (and a Next.js dashboard) in **under two seconds per pick**.

**The strategy the engine produces (for *this* roster):** because scoring is **Standard (non-PPR)**
and the roster demands **3 WR + a WR/RB-only flex with only one mandatory RB**, the correct,
data-derived play is **anchor/Hero-RB, not Zero-RB**: secure **1–2 scarce workhorse RBs early**,
**accumulate WR volume** through the middle rounds (valuing yards/TDs/air-yards over raw catches),
**defer QB and TE** unless an elite tier falls (an elite TE is the one positional-advantage
exception), stream **DST in Round 16 and K in Round 17**, and fill the **8-man bench with RB-skewed,
high-ceiling stashes** (handcuffs + breakouts). **Zero-RB is explicitly counter-indicated here.**

**Honest bound on the claim (do not oversell):** the research found **no peer-reviewed, empirically
validated optimal live snake-draft solver** — the strongest academic results solve a *different*
game (salary-cap team selection), and practitioner "edge" numbers are unverified. What is
recommended is the **deployable state-of-the-art** (roster-correct VBD/VONA + opponent simulation +
risk + flex-aware assignment + tiers), and its efficacy for this league is proven **by the project's
own offline simulated-league tournament (§7.E6)**, not by a vendor claim.

**v1 vs. stretch, at executive altitude:** **v1** = a live, league-correct, risk-aware, flex-aware,
*decomposed* recommendation in the overlay within 2 s on the free data tier, with calibrated
parameters and crash-safe replay. **Stretch** = a rest-of-season Monte-Carlo **season simulator**
that optimizes true playoff/championship odds, Monte-Carlo VONA, XGBoost residual projections,
per-manager tendency modeling, and an offline RL audit.

### 10.2 The synthesized system (one picture)

```
CBS draft room (your authenticated tab)
  │  three-probe capture (MAIN-world WS/fetch/XHR monkeypatch @document_start
  │  + framework-state read + MutationObserver DOM fallback), de-duped by pick_number
  ▼
apps/extension  ──ws://127.0.0.1:8787/draft/ws──►  backend (FastAPI, local)
                                                     │  jaaffl.ingest → append-only SQLite log
                                                     │                → fold_state(DraftState)
   overlay ◄──ws /recs/ws──┐                         │  jaaffl.engine.recommend(DraftContext, state)
   (best pick + WHY +      │                         │    Stage0 projections μ/σ (exact CBS scoring)
    survival %)            │                         │    Stage1 flex-aware MLV  (Hungarian)
apps/web dashboard ◄───────┘                         │    Stage2 VONA/survival  (FFC ADP mean+SD)
   (board, tiers, curves)                            │    Stage3 risk λ(phase,slot)·σ̂
                                                     │    Stage4 tier cliff (GMM)
   data tiers ($0): nflreadpy (history/ECR/xEP) ─────┤    → Recommendation + ScoreComponents
   FFC ADP (mean+SD) · CBS on-page (live settings) ──┘    (precompute → <2s stateless per-pick recompute)
```

### 10.3 Canonical engine spec (resolves C1 & C2)

**Canonical replacement baselines for this roster** (the one true set; §4/§5's RB18–22/WR40/index-12
are the *first-principles, pre-man-games anchors* that deepen to these after bye/injury adjustment
and VOLS-blending — see §6.C.2):

| Position | Canonical replacement baseline | Draft behavior |
|---|---|---|
| RB | **≈ RB22–24** (VOLS RB20 → man-games RB25, 0.5/0.5 blend) | scarce top end → **anchor early** |
| WR | **≈ WR40–42** (deep) | breadth → **accumulate mid-rounds** |
| QB | **≈ QB13** (shallow) | **defer** (target ~R7–10) |
| TE | **≈ TE13** (shallow) | **defer unless elite** (top‑2/3 exception) |
| K | **≈ K13** (flat) | **Round 17**, then stream |
| DST | **≈ DST13** (flat) | **Round 16**, then stream |

**Canonical objective function** (identical to §6.C.7 / §7 Step 8):
```
Score(p) =  MLV_p                        # flex-aware Marginal Lineup Value (Hungarian over the 9 starting slots)
          + κ · max(0, VONA_p)           # scarcity/opportunity-cost urgency from ADP survival
          − λ(phase, slot) · σ̂_p         # risk: floor-tilt for starters, ceiling-tilt for bench
          + α · CliffBonus_p             # tier-cliff urgency (Boris-Chen GMM on ECR)
          + Σ capped modifiers           # bye-stack −, handcuff-synergy +, SOS tiebreak ± (each ≤ ~3–5 pts)
```
**Canonical tunable defaults** (versioned in `config/engine.json`): **κ = 0.5–0.8**; **α = 0.3–0.5**;
**flex split = 8 RB / 4 WR**; **λ schedule** — R1–2 **+0.2…+0.4**, R3–6 **+0.1…+0.3**, R7–9 **≈0**,
R10–13 **−0.2…−0.4**, R14–17 **−0.3…−0.5** (with a *slot override*: last open startable slot → floor,
surplus/stash → ceiling). VONA survival is analytic Gaussian by default: `S_j(N) = 1 − Φ((N − m_j)/s_j)`.

**Canonical flex-split measurement (resolves C1 — use top-60, not top-108):** rank all RB+WR by
non-PPR 12-team FFC ADP; the **top-60** are the startable RB/WR pool (12 RB + 36 WR + 12 flex).
Then `flex_RB = (#RB in top-60) − 12` and `flex_WR = (#WR in top-60) − 36`, so `flex_RB + flex_WR =
60 − 48 = 12`. Re-measure daily pre-draft; non-PPR scarcity may push the split **more RB-heavy** than
the 8/4 default — this is the single highest-value calibration.

### 10.4 Consolidated round-by-round draft playbook (element g)

A slot-agnostic round-band guide for a **12-team, Standard (non-PPR), 17-round snake** with this
roster. The engine adapts to the **actual** draft order (read live from CBS — never assumed) and to
the board; this table is the human-readable strategy the engine encodes. Targets are *positions/
profiles*, not named players (which are season-specific).

| Round(s) | Primary target | Why (this league) | Risk (λ) |
|---|---|---|---|
| **R1–2** | **Anchor: 1–2 elite workhorse RBs** (take an elite WR/rare elite TE only if MLV clearly says so) | RB is the scarce, steep-cliff position in non-PPR; securing top-end RB marginal value is the highest-leverage move; **Zero-RB is counter-indicated** | floor-tilt (+0.2…+0.4) |
| **R3–4** | **Second core piece**: best RB *or* WR by MLV/VONA; aim for ~2 RB + 1–2 WR by end of R4; grab an **elite TE** here if one falls | Lock the scarce RB tier before it empties; begin WR accumulation; elite-TE edge over TE12 can beat WR1-over-WR24 | floor-tilt (+0.1…+0.3) |
| **R5–6** | **Fill starting WRs** (you need 3 + a WR/RB flex): best-value RB/WR; heed **VONA** during position runs | WR value here is *breadth*; weight air-yards/aDOT/deep & red-zone targets over raw catch volume | ~neutral |
| **R7–9** | **Complete the starting nine**: your **QB** lands here (a top‑8‑ish QB) unless an elite fell; keep adding WR/RB; last shot at a startable TE if you punted | QB baseline is shallow (QB13) → deferring costs little; prioritize rushing-QB upside | ~neutral |
| **R10–11** | **Bench insurance**: safer bye/injury cover for your starters; **handcuff your anchor RBs** | Protect the starting lineup first; RB injury churn (~27% full-season) makes handcuffs high-value | mild ceiling |
| **R12–15** | **Upside swings** (ceiling-tilt): young breakout WRs, high-upside backup RBs with standalone value, optional 2nd QB/TE if streaming-averse; **skew RB-heavy** | Championships are won by ceiling; cheap lottery tickets; bench should carry more RBs than WRs | ceiling (−0.2…−0.4) |
| **R16** | **DST** (stream target) | Draft one DST facing a weak/low-total offense in Wks 1–3; our scoring rewards it via **both** points- and yards-allowed tiers | punt |
| **R17** | **K** (stream target) | Least predictable position; never reach; pick on team-total/dome/matchup | punt |

**Standing rules the engine enforces:** measure value as **marginal gain to your optimal 9-man
starting lineup** (the WR/RB flex is filled by whichever of your best remaining RB/WR helps most);
use **VONA** to decide *take-now-vs-wait* (high urgency on RB, low on WR); never draft K/DST before
R16/R17; treat forward-year (2027) outputs as **ESTIMATED**.

### 10.5 Build plan at a glance (v1 vs stretch — full detail in §7.F)

- **Stage 1** CBS sync (`@crxjs`; MAIN-world `document_start` three-probe; SQLite append-only log) — **v1**
- **Stage 2** Normalize league settings incl. the **full CBS scoring map** (DST dual tiers + K bonus) — **v1**
- **Stage 3** DuckDB/SQLite/Parquet warehouse + ID crosswalk — **v1**
- **Stage 4** `$0` providers: `nflreadpy` + FFC ADP + CBS-on-page (paid off) — **v1**
- **Stage 5** Transparent engine: projections → league scoring/replacement → Hungarian MLV → analytic
  VONA → risk → `recommend` + `ScoreComponents` — **v1 core**; MC-VONA + **season simulator (playoff/
  championship odds)** + XGBoost residuals + RL audit — **stretch**
- **Stage 6** Overlay (best pick + decomposition + survival %) — **v1**; Next.js dashboard — **v1‑lite/stretch**
- **Stage 7** Text-only assistant (`explain_recommendation` over `ScoreComponents`) — **v1‑lite**
- **Four required scaffold changes** (from §7): (1) `LeagueSettings` gains `scoring_tiers`+`scoring_bonuses`;
  (2) `nfl_data_py`→`nflreadpy` (Polars); (3) `RecommendedPick` gains `ScoreComponents`; (4) add `WS /recs/ws`.

### 10.6 Consolidated tunables & open items (next steps, in priority order)

1. **Measure the flex RB/WR split** from live non-PPR 12-team FFC ADP (§10.3 top-60 method) → set
   `EngineParams.flex_split`. *Highest-value calibration; likely more RB-heavy than 8/4 in non-PPR.*
2. **Calibrate κ, the λ schedule, α, and modifier caps** via the mock-draft backtest (§7.E2, Optuna),
   evaluated across all 12 draft slots and against non-ADP opponent models.
3. **Validate the projection blend** (§7.E3) against 2021–2024 realized points under the exact CBS map;
   require the blend to beat the best single source; calibrate σ by interval coverage.
4. **Confirm the `nflreadpy` ID-crosswalk function name** (`load_ff_playerids`/`load_players`) `[VERIFY]`;
   fuzzy name+team+position fallback covers CBS/FFC regardless.
5. **Capture-layer golden fixtures** once real CBS frames are observed (§7.E4); keep the **manual-paste
   fallback** for the UNVERIFIED transport.
6. **Injury freshness:** wire CBS on-page injury designations; optionally enable the $5.99 FantasyPros
   feed behind its flag if you want a guaranteed feed.
7. **Prove efficacy offline** (§7.E6 simulated-league tournament vs VBD-only and ADP-only baselines) —
   this is the project's own validation gate, since none exists in the literature.

### 10.7 Scope & compliance recap

Everything above is scoped to a **personal, non-commercial, user-authorized, local-only** tool
(ADR 0003; `docs/legal-and-compliance.md`): CBS data is read only from your own session, no
`webRequest`/`declarativeNetRequest`, narrow host permissions, no redistribution, and the repo's
personal, non-commercial license. Paid providers stay **off** by default; the whole v1 runs at **$0
besides AI usage**, text-only (no voice). The immutable league settings (§2) govern every baseline
and must never be paraphrased or changed — they live in `config/league.json`, which any coding agent
must load before work.

**Bottom line:** the research validates a clear, buildable, honest path from the current scaffold to
a first production-grade prototype: implement the four scaffold changes and Stages 1–7 (v1),
calibrate the flex split and risk parameters, prove it offline, and only then reach for the season-
simulator stretch. The strategy it will produce for your league is anchor-RB + WR-breadth + late
QB/TE + streamed K/DST — the correct, evidence-backed response to Standard scoring and a WR-heavy,
one-mandatory-RB roster.

---

*End of document. Persistent memory: [`../config/league.json`](../config/league.json) · project
memory: [`../CLAUDE.md`](../CLAUDE.md). This document and the memory file must be kept in sync with
any change to league settings — which, per the constitution, do not change.*
