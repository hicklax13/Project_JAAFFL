# JAAFFL — Implementation & Build Plan (current state → production-grade prototype)

> **Execution-ready build plan.** This document turns the settled conclusions of
> [`docs/draft-system-design.md`](draft-system-design.md) (§1–§10, the merged research deliverable) into a
> phased, testable path from the current scaffold to a first **production-grade prototype** of the JAAFFL
> live-draft assistant. It does **not** re-derive the research — read that document for the *why*; read this
> one for the *how, in what order, and how we know it works*.
>
> Companion persistent memory: [`config/league.json`](../config/league.json) (immutable) and
> [`CLAUDE.md`](../CLAUDE.md). The immutable league settings below govern every baseline, schema, and UI and
> **must never be paraphrased or changed**.

**How to read this plan.** §0 is the executive summary + the canonical facts every section builds on. §§1–12
are the twelve build tracks (architecture, database, engine, providers, extension, UI, assistant, API,
calibration/testing, phasing, dev/CI/deploy, risks/backlog). Each track is concrete — file paths, interfaces,
schemas, acceptance criteria, and a per-track **Definition of done**. Appendix A is the consolidated
round-by-round draft playbook the engine encodes and the product surfaces. Appendix B links the published
luxury UI mockups.

---

## 0. Executive summary & canonical facts

### 0.1 What we are building (one paragraph)

A **local-first, $0-besides-AI, personal-use CBS live-draft assistant**: a Manifest V3 browser extension reads
the draft from the user's **own authenticated CBS session** (via a transport-agnostic three-probe capture) and
streams picks to a local FastAPI backend, which runs a **transparent, Monte-Carlo-augmented Value-Based-Drafting
engine** and pushes a **decomposed** recommendation to an in-page overlay (and a Next.js dashboard) in **under
two seconds per pick**. A text-only AI assistant explains each recommendation. The strategy the engine produces
for *this* roster is **anchor/Hero-RB, not Zero-RB**: secure 1–2 scarce workhorse RBs early, accumulate WR
breadth in the middle rounds (valuing yards/TDs over raw catches in non-PPR), defer QB and TE unless an elite
tier falls, stream **DST in Round 16 and K in Round 17**, and fill the 8-man bench with RB-skewed, high-ceiling
stashes.

### 0.2 Honest bound on the claim (do not oversell)

The research found **no peer-reviewed, empirically-validated optimal live snake-draft solver** — the strongest
academic results solve a *different* game (salary-cap team selection), and practitioner "edge" numbers are
unverified. What we build is the **deployable state-of-the-art** (roster-correct VBD/VONA + Monte-Carlo opponent
simulation + a risk term + flex-aware assignment + tiers). Its efficacy for this league is proven **by the
project's own offline simulated-league tournament (§9, E6)** against VBD-only and ADP-only baselines — not by a
vendor claim. Forward-year (2027) outputs are always labeled **ESTIMATED**.

### 0.3 v1 vs. stretch (at a glance)

- **v1 (deployable):** live CBS picks → a **decomposed, league-correct, risk-aware, flex-aware** recommendation
  in the overlay **within 2 s**, on the **$0** data tier, with **calibrated** parameters and **crash-safe
  replay**.
- **Stretch:** a rest-of-season **Monte-Carlo season simulator** (true playoff/championship-odds objective;
  OR-Tools CP-SAT end-state), **Monte-Carlo VONA**, **XGBoost residual** projections, **per-manager** tendency
  modeling, and an offline **RL audit**.

### 0.4 Immutable league settings (verbatim — never paraphrase, change, or "optimize")

- **Draft Type:** Snake
- **Teams:** 12
- **Draft Order:** Decided in-person, then entered into CBS Sports system
- **Scoring Format:** Standard (non-PPR)
- **Draft Rounds:** 17
- **Roster Slots per Team:** QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

**Derived (arithmetic, not new constraints):** 9 starters + 8 bench = **17** = draft rounds; the **WR/RB flex is
WR-or-RB only** (no TE/QB). League-wide starter demand across 12 teams: QB 12, TE 12, K 12, DST 12, and an RB+WR
startable pool of 12 (RB) + 36 (WR) + 12 (flex) = **60** (of 108 total starters). The tool reads the **actual**
draft order live from the CBS room — it **never** infers snake order from team count. These values live in
[`config/league.json`](../config/league.json) (`immutable: true`) and must be loaded before any draft-system work.

### 0.5 Canonical engine spec (from design §10.3 — the one true set)

**Replacement baselines for this roster:** RB ≈ **22–24**, WR ≈ **40–42**, QB/TE/K/DST ≈ **13**.

**Canonical score** (every term is computed by a named module and surfaced in `ScoreComponents` — never a black box):

```
Score(p) =  MLV_p                        # flex-aware Marginal Lineup Value (Hungarian over the 9 starting slots)
          + κ · max(0, VONA_p)           # scarcity / opportunity-cost urgency from ADP survival
          − λ(phase, slot) · σ̂_p         # risk: floor-tilt for starters, ceiling-tilt for bench
          + α · CliffBonus_p             # tier-cliff urgency (Boris-Chen GMM on ECR)
          + Σ capped modifiers           # bye-stack −, handcuff-synergy +, SOS tiebreak ± (each ≤ ~3–5 pts)
```

- **MLV** — gain to the optimal 9-starter lineup from adding *p*, via `scipy.optimize.linear_sum_assignment`
  (Hungarian) over the 9 slots with a WR/RB flex mask, replacement-filled. Empty roster ⇒ MLV = μ − baseline
  = classic VOR.
- **VONA** — `MLV_p − E[best surviving MLV at pos(p) by your next 1–2 picks]` (**turn-aware**, §3.10 R2);
  survival is analytic Gaussian `S_j(N) = 1 − Φ((N − m_j^eff)/s_j)` from FFC ADP mean `m_j` + stdev `s_j`,
  **board-conditioned** so a live positional run lowers survival and raises urgency (§3.10 R3). Full
  remaining-draft Monte-Carlo VONA is a stretch refinement. Low-reliability positions (K/DST) have their
  projections shrunk toward replacement first, so projection noise cannot inflate their value (§3.10 R1).
- **λ schedule** (floor-tilt λ>0, ceiling-tilt λ<0): R1–2 **+0.2…+0.4**; R3–6 **+0.1…+0.3**; R7–9 **≈0**;
  R10–13 **−0.2…−0.4**; R14–17 **−0.3…−0.5**. **Slot override dominates phase:** last open startable slot →
  floor; surplus/stash → ceiling.
- **Tiers/CliffBonus** — `sklearn.mixture.GaussianMixture` on ECR.

**Canonical tunable defaults** (versioned in [`config/engine.json`](../config/engine.json) as `EngineParams`):
**κ = 0.5–0.8**, **α = 0.3–0.5**, **flex split = 8 RB / 4 WR** (measured live — see below), projection blend =
simple average, μ-refinement cap ±10–15%, modifier caps ≤ ~3–5 pts, `candidate_cap ≈ 180`, `mc_rollouts ≈ 2000`.

**Flex-split measurement (canonical — top-60):** rank all RB+WR by non-PPR 12-team FFC ADP; the **top-60** are
the startable RB/WR pool (12 RB + 36 WR + 12 flex). Then `flex_RB = (#RB in top-60) − 12` and
`flex_WR = (#WR in top-60) − 36`, so `flex_RB + flex_WR = 12`. Re-measure daily pre-draft; **non-PPR scarcity may
push the split more RB-heavy** than the 8/4 default — this is the single highest-value calibration (§9, E1).

### 0.6 The four required scaffold changes (design §7 / §10.5)

1. **`LeagueSettings`** gains **`scoring_tiers`** (DST **points-allowed AND yards-allowed** brackets) +
   **`scoring_bonuses`** (K 50+ yard bonus) — mirrored in Pydantic (`jaaffl.domain`) and Zod (`packages/shared`).
2. **`nfl_data_py` → `nflreadpy`** (Polars) at the provider/data boundary.
3. **`RecommendedPick`** gains a **`ScoreComponents`** decomposition (`mlv, vona, risk_penalty, cliff_bonus,
   sigma, floor, ceiling, replacement_baseline, modifiers{}`).
4. **Add `WS /recs/ws`** — the backend→overlay/dashboard push channel (keep `/draft/ws` ingest + REST).

Full schema diffs are in **§1**; the API contract for `/recs/ws` is in **§8**.

### 0.7 Data stores & topology (design §7)

- **DuckDB** — analytics / backtest. **Parquet** — nflverse snapshots. **SQLite** — ACID app state + the
  **append-only draft-event log**. `DraftState` is a **fold** over that log (crash-safe replay): ingest appends
  the event *before* computing a rec, so a restart replays to the exact state (§2).
- **Latency:** pre-draft **precompute → in-memory `DraftContext`**, then a **stateless per-pick `recompute()`**
  holds the hot path under **2 s** on a laptop (§3, §11 perf gate).

### 0.8 $0 data tier & compliance (design §5, ADR 0003)

- **`NflreadpyProvider`** (history/ECR/xEP), **`FantasyFootballCalculatorProvider`** (ADP mean + stdev, cached
  daily), **`CbsOnPageProvider`** (live settings/projections/injuries fed by the extension). FantasyPros /
  SportsDataIO / Sportradar ship as **disabled stubs** (§4).
- **Personal, non-commercial, local-first**, the user's **own** authenticated CBS session only; **$0** besides AI
  usage; **text-only** assistant (no voice/Realtime); narrow host permissions; **no** `webRequest` /
  `declarativeNetRequest`. See [`docs/legal-and-compliance.md`](legal-and-compliance.md).

### 0.9 Repo map (exact paths this plan targets)

| Area | Paths |
|---|---|
| Backend (Python) | `backend/src/jaaffl/` → `domain/models.py`, `config.py`, `api/{app,__main__}.py`, `ingest/cbs.py` (+ new `ingest/log.py`), `league/{scoring,replacement}.py`, `data/{warehouse,crosswalk}.py`, `providers/{base,registry,nflverse,fantasypros}.py` (+ new `ffc.py`, `cbs_onpage.py`), `engine/{projections,opponents,simulate,optimize,recommend}.py` (+ new `tiers.py`), `assistant/tools.py`, `tests/` |
| Shared contracts (TS) | `packages/shared/src/{events,league,recommendation,index}.ts` |
| Extension (MV3) | `apps/extension/manifest.json`, `src/{background/service-worker,content/cbs-draft.content,content/cbs-league.content,overlay/overlay,lib/parse,lib/transport}.ts` (+ new `src/inject/cbs-main.inject.ts`) |
| Web dashboard | `apps/web/app/{page,layout}.tsx`, `app/globals.css`, `lib/api.ts` |
| Config | `config/league.json` (immutable), `config/engine.json` (new) |
| CI / tooling | `.github/workflows/ci.yml`, `Makefile`, `backend/pyproject.toml`, `package.json` |

### 0.10 Track index

1. [System architecture & the four scaffold changes](#1-system-architecture--the-four-scaffold-changes)
2. [Database & warehouse design](#2-database--warehouse-design)
3. [Backend engines — the transparent pipeline](#3-backend-engines--the-transparent-pipeline)
4. [Data providers ($0 tier behind the interface)](#4-data-providers-0-tier-behind-the-interface)
5. [CBS sync extension (MV3, @crxjs)](#5-cbs-sync-extension-mv3-crxjs)
6. [Luxury-grade UI/UX frontend](#6-luxury-grade-uiux-frontend)
7. [AI assistant (text-only, OpenAI Responses API)](#7-ai-assistant-text-only-openai-responses-api)
8. [API & WebSocket contracts](#8-api--websocket-contracts)
9. [Calibration, testing & evaluation](#9-calibration-testing--evaluation)
10. [Phasing — ROADMAP Stages 1–7, v1 vs stretch](#10-phasing--roadmap-stages-17-v1-vs-stretch)
11. [Dev env, CI/CD, deployment & observability + end-to-end runbook](#11-dev-env-cicd-deployment--observability--end-to-end-runbook)
12. [Risks, mitigations & sequenced task backlog](#12-risks-mitigations--sequenced-task-backlog)
- [Appendix A — Consolidated round-by-round playbook](#appendix-a--consolidated-round-by-round-playbook)
- [Appendix B — Published luxury UI mockups](#appendix-b--published-luxury-ui-mockups)

---

## 1. System architecture & the four scaffold changes

This section is the architectural spine of the build plan. It fixes the end-to-end dataflow, maps
every package to a roadmap stage and a role in the engine pipeline, pins the compute topology that
makes the <2 s/pick budget achievable, and specifies — to the field and type — the **four scaffold
changes** the merged design (design §7 Step 2, §10.5) requires before engine work can begin. It
builds on, and does not re-derive, the research; see design §7 (architecture) and §10.2–§10.3
(synthesized system + canonical engine spec).

**Immutable league anchor (verbatim — `config/league.json`, `immutable:true`; never paraphrase, re-order, or "optimize"):**

- Draft Type: Snake
- Teams: 12
- Draft Order: Decided in-person, then entered into CBS Sports system
- Scoring Format: Standard (non-PPR)
- Draft Rounds: 17
- Roster Slots per Team: QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Derived (compute every baseline against *this* roster): 9 starters + 8 bench = 17 rounds; the `WR/RB`
flex is **WR-or-RB ONLY** (no TE/QB/K/DST). League-wide starter demand across the 12 teams: QB12, TE12,
K12, DST12, and an RB+WR startable pool of 12 RB + 36 WR + 12 flex = 60 (of 108 total starters). The
live draft order is **read from the CBS room** — it is **never** inferred as a plain snake from team
count. This section changes none of these values; it builds the machinery that honors them.

### 1.1 End-to-end dataflow (annotated)

The canonical picture is design §10.2. Annotated for this build plan, with the four scaffold changes
marked **[SC1]**–**[SC4]** and the precompute/hot-path split made explicit:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ CBS DRAFT ROOM  (the user's own authenticated tab — the only credentialed surface)            │
│   three-probe, transport-agnostic capture (design §5/§7 Step 6; CBS transport UNVERIFIED):     │
│     (1) MAIN-world content script @ run_at:"document_start" — monkeypatch WebSocket+fetch+XHR   │
│     (2) framework-state read (React fiber props)                                                │
│     (3) MutationObserver DOM fallback (isolated world)                                          │
└───────────────────────────────┬─────────────────────────────────────────────────────────────┘
        window.postMessage       │  ISOLATED content script = trust boundary; de-dup by pick_number
        {source:"jaaffl-main"}   ▼  (design §7.C.2); owns the localhost socket; manual-paste fallback
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ apps/extension  ──── DraftEvent (packages/shared, Zod) ── ws://127.0.0.1:8787/draft/ws ──────► │
└───────────────────────────────┬─────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ backend  FastAPI @ 127.0.0.1:8787  (jaaffl.api)                                                 │
│  jaaffl.ingest.log  ── append DraftEvent to append-only SQLite log (seq, pick_number) ────────┐ │
│                          BEFORE any engine work  → crash-safe replay (design §7 Step 7)       │ │
│  jaaffl.ingest.log  ── fold_state(log) → DraftState  (a fold over the log)                     │ │
│                                                                                                 │ │
│  ┌────────────────────  PRE-DRAFT PRECOMPUTE (once)  ───────────────────────────────────────┐ │ │
│  │ jaaffl.engine.context.build_draft_context(...) → in-memory DraftContext:                  │ │ │
│  │   projections μ/σ/floor/ceiling  · league points (EXACT CBS map [SC1])                    │ │ │
│  │   replacement baselines + flex allocation · tiers + cliff bonuses                         │ │ │
│  │   FFC ADP mean/SD joined by canonical id · crosswalk        (design §7.D)                 │ │ │
│  │   fed by: jaaffl.providers  NflreadpyProvider [SC2] (history/ECR/xEP, Polars),            │ │ │
│  │           FantasyFootballCalculatorProvider (ADP mean+SD),  CbsOnPageProvider             │ │ │
│  │           via jaaffl.data warehouse (DuckDB + Parquet) + crosswalk                        │ │ │
│  └───────────────────────────────────────────────────────────────────────────────────────────┘ │ │
│                                 │ held in memory                                                │ │
│  ┌────────  PER-PICK HOT PATH (stateless)  jaaffl.engine.recommend.recompute() ───────────────┐ │ │
│  │  mask picked player → vectorized survival S_j(N)=1−Φ((N−m)/s) → top-K candidates            │ │ │
│  │  → MLV via scipy.optimize.linear_sum_assignment (Hungarian, 9-slot flex mask)               │ │ │
│  │  → analytic VONA · risk λ(phase,slot)·σ̂ · cliff bonus · capped modifiers → assemble+sort    │ │ │
│  │  → Recommendation{ ranked: RecommendedPick{ ..., components: ScoreComponents [SC3] } }       │ │ │
│  └───────────────────────────────────────────────────────────────────────────────────────────┘ │ │
└───────────────────────────────┬─────────────────────────────────────────────────────────────┘ │
        Recommendation (Zod/Pydantic)                                                              │
        ├── ws /recs/ws  [SC4] ───────────► apps/extension  overlay  (Shadow DOM: best pick + WHY  │
        │   push, backend→client                            + top-5 + next-turn survival %)        │
        └── ws /recs/ws  [SC4] / GET /recommendation ─────► apps/web  dashboard (board, tiers,      │
                                                            distributions, survival curves)         │
```

Annotations:

- **Ingest-before-compute** is load-bearing: `jaaffl.ingest.log` appends the event to SQLite *before*
  `recompute()` runs, so a mid-draft crash replays to the exact state (design §7 Step 7). Only the
  live pick stream is unrebuildable; Parquet/DuckDB are regenerable.
- **`[SC1]` LeagueSettings scoring tiers/bonuses** enter at precompute time (projections are recomputed
  under the *exact* CBS map, including DST dual tiers + K 50+); a wrong scoring map poisons every
  downstream number.
- **`[SC2]` nflreadpy (Polars)** is the provider-boundary frame type; DuckDB scans Polars/Arrow
  zero-copy (design §7 Step 5).
- **`[SC3]` ScoreComponents** rides on every `RecommendedPick` so the overlay and `explain_recommendation`
  can show *why* (design §7 Step 8, "Transparent before clever").
- **`[SC4]` `WS /recs/ws`** is the backend→client push channel; the overlay updates within the budget
  without polling. Full wire contract lives in §8; it is *named and reserved* here.
- **Compliance envelope (ADR 0003; `docs/legal-and-compliance.md`).** The entire pipeline is
  **local-first**: it runs on the user's own machine and reads only the user's **own authenticated
  CBS session** (the sole credentialed surface); no pick or account data crosses the
  `127.0.0.1:8787` boundary. The assistant is **text-only** (no voice/Realtime). The build is
  **$0 out-of-pocket besides AI usage** — the default data tier (nflverse + FFC + CBS on-page) is free;
  paid providers are **opt-in/off**. Use is **personal and non-commercial**.
- **Honesty caveat (ADR 0003).** No peer-reviewed *optimal* live snake-draft solver exists; this
  engine's efficacy is established only by the project's **own offline simulated-league tournament vs
  VBD-only and ADP-only baselines** (design §7.E), never by vendor claims. Forward-year (2027)
  projections are treated as **ESTIMATED**.

### 1.2 Component / responsibility map

Every package, its path, its roadmap stage, its role in the engine pipeline (design §7.C), and which
of the four scaffold changes touch it. `[E]` = existing stub to implement, `[A]` = amend, `[N]` = new,
`[KEEP]` = unchanged.

| Package / path | Stage | Engine-pipeline role | Scaffold change |
|---|---|---|---|
| `packages/shared/src/{events,league,recommendation,index}.ts` | — | One JS-side vocabulary (Zod) mirrored by `jaaffl.domain` | **[A]** SC1 (`league.ts`), SC3 (`recommendation.ts`); SC4 event shapes |
| `backend/src/jaaffl/domain/models.py` | — | Pydantic contracts (mirror of `packages/shared`) | **[A]** SC1, SC3 |
| `backend/src/jaaffl/config.py` | — | Typed `Settings`; **[N]** `EngineParams` loader (`config/engine.json`) | **[A]** new `EngineParams` path + FFC/season keys |
| `backend/pyproject.toml` | 4–5 | Dependency extras (`data`/`engine`/`assistant`) | **[A]** SC2 (`data` extra: `nfl_data_py`+`pandas` → `nflreadpy`+`polars`); `engine` extra gains `scikit-learn` (GaussianMixture) + `pandas` (XGBoost, stretch) |
| `backend/src/jaaffl/api/app.py` + `api/__main__.py` | 1 | HTTP/WS surface; ingest handler → recommend → broadcast | **[A]** SC4 (`WS /recs/ws`) + `GET /league/{id}` |
| `backend/src/jaaffl/ingest/cbs.py` | 1–2 | Normalize raw CBS payloads → `DraftEvent`/`LeagueSettings` | — |
| `backend/src/jaaffl/ingest/log.py` **[N]** | 1 | Append-only SQLite event log; `fold_state` (crash-safe replay) | — |
| `backend/src/jaaffl/league/scoring.py` | 2 | `league_points`: linear rules **+ tiered brackets + threshold bonuses** | **[A]** SC1 (consumes it) |
| `backend/src/jaaffl/league/replacement.py` | 2 | `starter_demand`, `replacement_values` (baselines + flex share) | — |
| `backend/src/jaaffl/data/warehouse.py` | 3 | DuckDB (analytics/backtest) + Parquet (nflverse snapshots) + SQLite (state) | — |
| `backend/src/jaaffl/data/crosswalk.py` | 3 | nflverse-ID join + fuzzy name+team+pos fallback | — |
| `backend/src/jaaffl/providers/{base,registry}.py` | 4 | Provider protocol + toggling; return type `pd`→`pl` | **[A]** SC2 |
| `backend/src/jaaffl/providers/nflverse.py` → `NflreadpyProvider` | 4 | history/ECR/xEP via `nflreadpy` (Polars) | **[A]** SC2 |
| `backend/src/jaaffl/providers/ffc.py` **[N]** | 4 | FFC ADP mean+stdev (`Capability.ADP`), cached daily | — |
| `backend/src/jaaffl/providers/cbs_onpage.py` **[N]** | 4 | CBS on-page settings/projections/injuries from warehouse snapshot | reads SC1 output |
| `backend/src/jaaffl/providers/fantasypros.py` `[E]` (+ `sportsdataio.py`/`sportradar.py` **[N]** stubs) | 4 | Disabled stubs (off by default) | — |
| `backend/src/jaaffl/engine/context.py` **[N]** | 5 | **Owns `DraftContext`** + `build_draft_context()` (precompute) | consumes SC1/SC2 |
| `backend/src/jaaffl/engine/projections.py` | 5 (S0) | `build_projections` → `{stat_line, mu, sigma, floor, ceiling}` under CBS map | — |
| `backend/src/jaaffl/engine/tiers.py` **[N]** | 5 (S4) | `GaussianMixture` on ECR → `tier` + `cliff_bonus` | — |
| `backend/src/jaaffl/engine/optimize.py` | 5 (S1) | **[N]** `marginal_lineup_value` (Hungarian); **[E]** CP-SAT `optimize_roster` (stretch) | feeds SC3 |
| `backend/src/jaaffl/engine/opponents.py` | 5 (S2) | `pick_probabilities` — analytic Gaussian survival | feeds SC3 |
| `backend/src/jaaffl/engine/simulate.py` | 5 (str) | MC-VONA refinement + stretch season simulator | — |
| `backend/src/jaaffl/engine/recommend.py` | 5 | **Owns stateless `recompute()`**; assemble `Score`, populate `ScoreComponents` | **[A]** SC3 |
| `backend/src/jaaffl/assistant/tools.py` | 7 | Typed tools; `explain_recommendation` over `ScoreComponents` | reads SC3 |
| `apps/extension/manifest.json` + `src/{background,content,overlay,lib}` | 1,6 | Capture → normalize → stream; overlay subscribes `/recs/ws` | **[A]** SC4 (overlay), SC1 (`parse.ts`) |
| `apps/web/app/*` + `lib/api.ts` | 6 | Dashboard; consumes `/recommendation` + `WS /recs/ws` | **[A]** SC4 |
| `config/league.json` (IMMUTABLE) | — | Persistent league memory; never altered | — |
| `config/engine.json` **[N]** | 5 | `EngineParams` (κ, λ-table, α, flex_split, caps, candidate_cap, mc_rollouts) | new |
| `.github/workflows/ci.yml` | — | ruff + pytest (py); tsc + test (js); **[A]** schema-parity gate (E5) | guards SC1/SC3 |

### 1.3 Compute topology: precompute → DraftContext → stateless `recompute()`

**Why (the constraint).** The design fixes a hard **<2 s/pick** budget on a single laptop with no GPU,
with ≤~22 opponent picks between the user's turns in this 12-team snake (design §7 Step 3, §7.D).
Recomputing projections, league points, replacement baselines, tiers, and the ADP join on every pick
blows that budget. The only reliable topology is **move everything data-shaped to a one-time pre-draft
precompute, then make the per-pick path pure arithmetic over in-memory arrays.**

**The three phases:**

1. **Pre-draft PRECOMPUTE (once).** `jaaffl.engine.context.build_draft_context(league, providers,
   engine_params)` materializes, from the warehouse, everything that does not depend on *which* players
   have been picked: per-player projections μ/σ/floor/ceiling, league points under the exact CBS map,
   replacement baselines (**RB≈22–24, WR≈40–42, QB/TE/K/DST≈13**) + flex allocation, tiers + cliff
   bonuses, FFC ADP mean/SD joined by canonical id, and the crosswalk. Persisted to DuckDB/Parquet and
   held in memory (design §7.D).

2. **In-memory `DraftContext` (owned by `jaaffl.engine.context`).** A frozen dataclass holding the
   precomputed arrays plus immutable `LeagueSettings` and `EngineParams`. **`jaaffl.engine.context` is
   the module that owns `DraftContext`** (definition + builder). It is read-only during the draft; the
   only mutable state is `DraftState`, which is a fold over the SQLite log (§1.1), not part of the
   context.

3. **Per-pick stateless `recompute()` (owned by `jaaffl.engine.recommend`).** `recompute(ctx:
   DraftContext, state: DraftState) -> Recommendation` takes the immutable context + the current state
   and returns a fresh recommendation with no hidden mutation — so a replayed state always yields the
   same rec. Hot-path steps (design §7.D):

| # | Step | Module | Cost |
|---|---|---|---|
| 1 | Drop picked players (boolean mask over the available set) | `recommend` | O(1) |
| 2 | Vectorized survival `S_j(N) = 1 − Φ((N − m_j)/s_j)` over ~300 players | `opponents` | ~µs |
| 3 | Bound candidates to top-K (`candidate_cap ≈ 180`) | `recommend` | O(n log n) |
| 4 | MLV per candidate via `scipy.optimize.linear_sum_assignment` (9×(owned+replacement+candidate), base lineup cached, dominance shortcut) | `optimize` | ~tens of ms |
| 5 | Analytic VONA · risk `λ(phase,slot)·σ̂` · cliff · capped modifiers (MC only if enabled) | `recommend`/`opponents`/`tiers` | ~ms |
| 6 | Assemble `ScoreComponents`, sort, emit `Recommendation` | `recommend` | ~ms |

**Latency budget (design §7.D):** analytic path **<200 ms**; **<2 s** with MC-VONA at `mc_rollouts ≈
2000`. Worst case is pick 1 (largest pool, horizon ~22). CP-SAT (OR-Tools) is reserved for the stretch
season simulator, **never** the hot path. A CI perf gate (E7) asserts p95 < 2 s.

**v1 vs stretch (topology scope, design §10).** The **analytic** hot path above *is* v1: live CBS
picks → a decomposed, league-correct, risk-aware, flex-aware recommendation in the overlay within 2 s,
on the $0 data tier, with calibrated params and crash-safe replay. Everything Monte-Carlo or
constrained is **STRETCH** and is kept off the v1 hot path: **MC-VONA** refinement (`mc_enabled`,
`engine/simulate.py`), the rest-of-season **Monte-Carlo season simulator** (playoff/championship odds;
**CP-SAT** end-state via OR-Tools), **XGBoost** residual projections, per-manager tendency modeling,
and the offline RL audit.

### 1.4 The four required scaffold changes

Each change is specified with (i) the **exact current shape** (file-cited), (ii) the **exact new shape**
as fenced code for **both** Pydantic (`backend/src/jaaffl/domain/models.py`) **and** Zod
(`packages/shared/src/*.ts`), and (iii) a **sync note**. The two contract definitions are kept in
lockstep by the **schema-parity CI gate** (§1.6, design §7.E5 / decision B13): the Pydantic models are
the source of truth; Zod mirrors them; canonical fixtures round-trip through both and CI fails on
divergence. **Every Pydantic field added below has an exactly-corresponding Zod field, and vice versa.**

#### 1.4.1 (a) `LeagueSettings.scoring_tiers` + `scoring_bonuses` — the full CBS scoring map

**Why.** CBS "standard" scores DST on **both** a points-allowed bracket **and** a yards-allowed bracket,
and awards a K bonus at 50+ yards. The current `scoring` field is a flat linear map and *structurally
cannot* express brackets or thresholds (design §7 Step 2.1, decision B3).

**Current shape** — `backend/src/jaaffl/domain/models.py` (`LeagueSettings`, line 79) carries only:

```python
scoring: list[ScoringRule] = Field(default_factory=list)   # (stat, points_per_unit, applies_to) — LINEAR only
```

and `ScoringRule` (lines 41–48) is `{stat: str, points_per_unit: float, applies_to: list[Position] | None}`.
Zod mirror: `packages/shared/src/league.ts` `LeagueSettingsSchema.scoring: z.array(ScoringRuleSchema)`.

**New shape — Pydantic** (`backend/src/jaaffl/domain/models.py`; add three models, extend `LeagueSettings`):

```python
class ScoringBracket(BaseModel):
    """One inclusive-lower bracket of a tiered stat. Points awarded when lower <= stat < upper
    (upper=None => open-ended top bracket)."""
    lower: float = Field(description="Inclusive lower bound of the bracket, in stat units.")
    upper: float | None = Field(default=None, description="Exclusive upper bound; None = open-ended.")
    points: float = Field(description="Points awarded when the stat falls in this bracket.")


class ScoringTier(BaseModel):
    """A bracketed (non-linear) scoring stat, e.g. CBS DST points-allowed / yards-allowed."""
    stat: str = Field(description="e.g. 'dst_points_allowed', 'dst_yards_allowed'.")
    applies_to: list[Position] | None = Field(default=None, description="Restrict to positions, e.g. [DST].")
    brackets: list[ScoringBracket] = Field(default_factory=list)


class ScoringBonus(BaseModel):
    """A threshold bonus, e.g. K field goal of 50+ yards => +N points."""
    stat: str = Field(description="e.g. 'field_goal_distance'.")
    threshold: float = Field(description="Award when stat >= threshold (stat units).")
    points: float = Field(description="Bonus points at/over the threshold.")
    applies_to: list[Position] | None = Field(default=None, description="e.g. [K].")


# LeagueSettings gains (additive; existing linear `scoring` stays):
class LeagueSettings(BaseModel):
    # ... existing fields ...
    scoring: list[ScoringRule] = Field(default_factory=list)          # linear rules (unchanged)
    scoring_tiers: list[ScoringTier] = Field(default_factory=list)    # NEW: DST pts- AND yds-allowed brackets
    scoring_bonuses: list[ScoringBonus] = Field(default_factory=list) # NEW: K 50+ yard bonus, etc.
```

**New shape — Zod** (`packages/shared/src/league.ts`; add three schemas, extend `LeagueSettingsSchema`):

```ts
export const ScoringBracketSchema = z.object({
  lower: z.number(),
  upper: z.number().nullable().default(null), // null = open-ended top bracket
  points: z.number(),
});
export type ScoringBracket = z.infer<typeof ScoringBracketSchema>;

export const ScoringTierSchema = z.object({
  stat: z.string(),
  applies_to: z.array(PositionSchema).nullable().optional(),
  brackets: z.array(ScoringBracketSchema).default([]),
});
export type ScoringTier = z.infer<typeof ScoringTierSchema>;

export const ScoringBonusSchema = z.object({
  stat: z.string(),
  threshold: z.number(),
  points: z.number(),
  applies_to: z.array(PositionSchema).nullable().optional(),
});
export type ScoringBonus = z.infer<typeof ScoringBonusSchema>;

export const LeagueSettingsSchema = z.object({
  // ... existing fields ...
  scoring: z.array(ScoringRuleSchema).default([]),
  scoring_tiers: z.array(ScoringTierSchema).default([]),   // NEW
  scoring_bonuses: z.array(ScoringBonusSchema).default([]),// NEW
});
```

**Example (illustrative — exact CBS bracket values are read live from the league scoring page; see
`config/league.json` `league.scoring_note`; UNVERIFIED until captured):**

```json
{
  "scoring_tiers": [
    {"stat": "dst_points_allowed", "applies_to": ["DST"], "brackets": [
      {"lower": 0, "upper": 1,  "points": 10}, {"lower": 1, "upper": 7,  "points": 7},
      {"lower": 7, "upper": 14, "points": 4},  {"lower": 14,"upper": 21, "points": 1},
      {"lower": 21,"upper": 28, "points": 0},  {"lower": 28,"upper": 35, "points": -1},
      {"lower": 35,"upper": null,"points": -4}
    ]},
    {"stat": "dst_yards_allowed", "applies_to": ["DST"], "brackets": [
      {"lower": 0, "upper": 100, "points": 5}, {"lower": 100,"upper": 200,"points": 3},
      {"lower": 200,"upper": 300,"points": 2}, {"lower": 300,"upper": 400,"points": 0},
      {"lower": 400,"upper": null,"points": -3}
    ]}
  ],
  "scoring_bonuses": [
    {"stat": "field_goal_distance", "threshold": 50, "points": 2, "applies_to": ["K"]}
  ]
}
```

**Sync note.** `league/scoring.py::league_points` must evaluate linear `scoring` **plus** `scoring_tiers`
(bracket lookup, one contribution per tier — DST accumulates *both* pts- and yds-allowed) **plus**
`scoring_bonuses` (per-event threshold). Add a canonical `LeagueSettings` fixture exercising both new
fields to the schema-parity set (§1.6). Never fold these into the immutable `config/league.json`
constraints — they describe the CBS *scoring map*, not the league constitution.

#### 1.4.2 (b) `nfl_data_py` → `nflreadpy` (Polars) at the provider boundary

**Why.** `nfl_data_py` is archived (design §7 decision B2); `nflreadpy` is maintained, Polars-native,
and scans zero-copy into DuckDB. Forcing pandas adds a round-trip on every load (design §7 Step 5).

**Current shape.**
- `backend/pyproject.toml` `[project.optional-dependencies].data`:
  ```toml
  data = ["duckdb>=0.10", "pyarrow>=15", "pandas>=2.2", "nfl_data_py>=0.3.2"]
  ```
- `backend/src/jaaffl/providers/base.py` — `historical_stats(self, season: int) -> pd.DataFrame`
  (line 68) with `if TYPE_CHECKING: import pandas as pd` (line 16). `Capability` (lines 21–27) lacks
  `EXPECTED_POINTS`.

**New shape.**
- `data` extra (drop `nfl_data_py`+`pandas`, add `nflreadpy`+`polars`; pandas + scikit-learn move to
  the `engine` extra):
  ```toml
  data = ["duckdb>=0.10", "pyarrow>=15", "polars>=1.0", "nflreadpy>=0.1"]
  # engine extra additionally carries pandas>=2.2 (XGBoost .to_pandas(), stretch) and
  # scikit-learn>=1.4 (GaussianMixture cliff tiers, engine/tiers.py)
  ```
- `providers/base.py` — Polars return type + new capability:
  ```python
  if TYPE_CHECKING:
      import polars as pl              # was: import pandas as pd
      from jaaffl.domain import Player

  class Capability(StrEnum):
      HISTORICAL_STATS = "historical_stats"
      PROJECTIONS = "projections"
      ADP = "adp"
      RANKINGS = "rankings"            # ECR (nflreadpy load_ff_rankings)
      EXPECTED_POINTS = "expected_points"   # NEW: xEP (nflreadpy load_ff_opportunity)
      INJURIES = "injuries"
      NEWS = "news"

  def historical_stats(self, season: int) -> pl.DataFrame:   # was -> pd.DataFrame
      self._require(Capability.HISTORICAL_STATS)
      raise NotImplementedError

  def expected_points(self, season: int, week: int | None = None) -> pl.DataFrame:  # NEW
      self._require(Capability.EXPECTED_POINTS)
      raise NotImplementedError
  ```
- `providers/nflverse.py` becomes `NflreadpyProvider`: `historical_stats`→`load_player_stats`,
  `rankings`(ECR)→`load_ff_rankings`, `expected_points`(xEP)→`load_ff_opportunity`; id mapping via the
  nflverse crosswalk (`load_ff_playerids` / `load_players` — **exact Python name [VERIFY minor]**, design
  §7 B2/§10.6.4; fuzzy name+team+pos fallback covers CBS/FFC regardless).

**Sync note.** No Zod counterpart — this is a **Python-only** dependency/return-type change. The
parity CI is unaffected; the CI *build* matrix must install the `data` extra so import of `polars`/
`nflreadpy` is exercised. Keep `.to_pandas()` calls out of the hot path (design §7 Step 5).

#### 1.4.3 (c) `RecommendedPick.ScoreComponents` — the score decomposition

**Why.** The value proposition and the assistant's `explain_recommendation` tool depend on surfacing
*why* a pick is recommended (design §7 Step 8, decision B8, "Transparent before clever"). The single
opaque `score` cannot be audited.

**Current shape** — `backend/src/jaaffl/domain/models.py` `RecommendedPick` (lines 130–141):
`player_id, score, projected_points, vorp, adp, next_turn_availability, tier, rationale`. No
decomposition. Zod mirror: `packages/shared/src/recommendation.ts` `RecommendedPickSchema` (same set).

**New shape — Pydantic** (`backend/src/jaaffl/domain/models.py`; add `ScoreComponents`, embed on
`RecommendedPick`):

```python
class ScoreComponents(BaseModel):
    """Auditable decomposition of Score(p) (design §10.3 / §6.C.7).

    Reconstruction (κ, weights from EngineParams):
        score ≈ mlv + kappa*max(0.0, vona) - risk_penalty + cliff_bonus + sum(modifiers.values())
    Convention: `vona` is RAW (pre-κ, may be negative — the overlay shows urgency even when gated to 0);
    `risk_penalty` and `cliff_bonus` are the APPLIED signed contributions; `sigma`/`floor`/`ceiling`/
    `replacement_baseline` are descriptive, not summed.
    """
    mlv: float = Field(description="Flex-aware Marginal Lineup Value (Hungarian, 9 slots). Weight 1.")
    vona: float = Field(description="Raw Value Over Next Available (pre-κ, pre-max-gate). May be < 0.")
    risk_penalty: float = Field(description="Applied signed risk term λ(phase,slot)·σ̂; Score SUBTRACTS it.")
    cliff_bonus: float = Field(description="Applied tier-cliff term α·CliffBonus_p (points).")
    sigma: float = Field(ge=0.0, description="Projection stdev σ̂_p used for the risk term.")
    floor: float = Field(description="Downside (≈p10) projection, league points.")
    ceiling: float = Field(description="Upside (≈p90) projection, league points.")
    replacement_baseline: float = Field(description="Positional replacement baseline (league points) for MLV fill.")
    modifiers: dict[str, float] = Field(
        default_factory=dict,
        description="Named capped modifiers already in points, e.g. "
        "{'bye_stack': -1.5, 'handcuff_synergy': 2.0, 'sos': 0.5}; each within EngineParams caps.",
    )


class RecommendedPick(BaseModel):
    player_id: str
    score: float
    projected_points: float | None = None
    vorp: float | None = None
    adp: float | None = None
    next_turn_availability: float | None = Field(default=None, ge=0.0, le=1.0)
    tier: int | None = None
    rationale: str | None = None
    components: ScoreComponents | None = None   # NEW: populated by engine.recommend for every v1 rec
```

**New shape — Zod** (`packages/shared/src/recommendation.ts`):

```ts
export const ScoreComponentsSchema = z.object({
  mlv: z.number(),
  vona: z.number(),
  risk_penalty: z.number(),
  cliff_bonus: z.number(),
  sigma: z.number().nonnegative(),
  floor: z.number(),
  ceiling: z.number(),
  replacement_baseline: z.number(),
  modifiers: z.record(z.number()).default({}),
});
export type ScoreComponents = z.infer<typeof ScoreComponentsSchema>;

export const RecommendedPickSchema = z.object({
  player_id: z.string(),
  score: z.number(),
  projected_points: z.number().nullable().optional(),
  vorp: z.number().nullable().optional(),
  adp: z.number().nullable().optional(),
  next_turn_availability: z.number().min(0).max(1).nullable().optional(),
  tier: z.number().int().nullable().optional(),
  rationale: z.string().nullable().optional(),
  components: ScoreComponentsSchema.nullable().optional(), // NEW
});
```

**Field summary (every field + type):**

| Field | Type (Py / Zod) | Meaning | In `score`? |
|---|---|---|---|
| `mlv` | `float` / `number` | Flex-aware Marginal Lineup Value (weight 1) | + |
| `vona` | `float` / `number` | Raw VONA (pre-κ, pre-gate; may be < 0) | + κ·max(0,·) |
| `risk_penalty` | `float` / `number` | Applied signed `λ(phase,slot)·σ̂` | − |
| `cliff_bonus` | `float` / `number` | Applied `α·CliffBonus_p` | + |
| `sigma` | `float ≥0` / `number ≥0` | Projection stdev σ̂_p | descriptive |
| `floor` | `float` / `number` | ≈p10 projection | descriptive |
| `ceiling` | `float` / `number` | ≈p90 projection | descriptive |
| `replacement_baseline` | `float` / `number` | Positional replacement baseline (league pts) | descriptive |
| `modifiers` | `dict[str,float]` / `record<number>` | Named capped modifiers (points) | + Σ values |

**Sync note.** `components` is `Optional`/`nullable` on both sides so pre-engine (Stage 1–4) payloads
validate; **the Stage 5 engine populates it on every `RecommendedPick`**. Add a canonical
`Recommendation` fixture with a fully-populated `components` to the parity set (§1.6). The overlay
(`overlay.ts`) and `assistant/tools.py::explain_recommendation` both read this object.

#### 1.4.4 (d) `WS /recs/ws` — the recommendation push channel

**Why.** The API today has ingest (`POST /draft/events` + `WS /draft/ws`) and `GET /recommendation`
(currently `501`, `api/app.py:57`), but **no push channel** — the overlay would have to poll, missing
the <2 s budget (design §7 Step 2.4, decision B9).

**Current shape** — `backend/src/jaaffl/api/app.py` exposes: `GET /health`, `POST /draft/events`,
`WS /draft/ws` (ingest), `GET /recommendation` (`501` until Stage 5). No outbound stream.

**New shape** — add the SC4 push channel (and, additively alongside it, `GET /league/{id}`); keep
everything above (import `LeagueSettings` from `jaaffl.domain`):

```python
# backend/src/jaaffl/api/app.py — additive
@app.websocket("/recs/ws")
async def recs_ws(ws: WebSocket) -> None:
    """PUSH channel: backend → overlay/dashboard. Emits a Recommendation JSON frame each time a
    newly-ingested pick is folded and recompute() produces a fresh rec. Read-only to the client."""
    await ws.accept()
    # register ws with the broadcast hub; on each ingest: append log → fold_state → recompute → broadcast
    ...

@app.get("/league/{league_id}", response_model=LeagueSettings)   # additive convenience, not part of SC4
def league(league_id: str) -> LeagueSettings: ...
```

The ingest handler (`POST /draft/events` and `WS /draft/ws`) is extended to, after appending to the
log and folding state (§1.1), call `engine.recommend.recompute(...)` and **broadcast the
`Recommendation` on `/recs/ws`**. Clients: `apps/extension` overlay (`overlay.ts`) and `apps/web`
(`lib/api.ts`).

**Sync note.** The channel is **named and reserved here**; its full wire contract (frame envelope,
handshake, heartbeat/reconnect, error frames) is authored in **§8** and must reuse the `Recommendation`
Zod/Pydantic contract verbatim — no bespoke rec shape on the socket.

### 1.5 `config/engine.json` (EngineParams)

**Why (decision B11).** The objective stays declarative and calibration (design §7.E1–E2, Optuna)
tunes behavior without code changes. All engine hyperparameters live in a **versioned**
`config/engine.json`, loaded via `jaaffl.config`. `config/engine.json` is the **single source of truth**
for the tunables below; `config.py` gains only the *path* + provider/runtime env fields (below).

**Full default file** (`config/engine.json` — every required key with defaults from design §10.3):

```json
{
  "version": 1,
  "scoring_format": "standard",
  "kappa": 0.65,
  "alpha": 0.40,
  "projection_blend": "simple_average",
  "flex_split": {"RB": 8, "WR": 4},
  "lambda_schedule": [
    {"rounds": [1, 2],   "lambda": 0.30},
    {"rounds": [3, 6],   "lambda": 0.20},
    {"rounds": [7, 9],   "lambda": 0.00},
    {"rounds": [10, 13], "lambda": -0.30},
    {"rounds": [14, 17], "lambda": -0.40}
  ],
  "lambda_slot_override": {"last_startable_slot_floor": 0.40, "surplus_stash_ceiling": -0.40},
  "replacement_blend": {"vols_weight": 0.5, "mangames_weight": 0.5},
  "caps": {"mu_refinement_pct": 0.15},
  "candidate_cap": 180,
  "mc_enabled": false,
  "mc_rollouts": 2000
}
```

**Key reference:**

| Key | Default | Design range (§10.3) | Meaning |
|---|---|---|---|
| `kappa` (κ) | `0.65` | 0.5–0.8 | Weight on `max(0, VONA)` (scarcity urgency) |
| `alpha` (α) | `0.40` | 0.3–0.5 | Weight on `CliffBonus` (tier-cliff urgency) |
| `flex_split` | `{RB:8, WR:4}` | 8/4 default | WR/RB flex demand allocation — **MEASURE LIVE** (top-60 method, §10.3 E1; likely more RB-heavy in non-PPR) |
| `lambda_schedule` | see file | R1–2 +0.2…+0.4; R3–6 +0.1…+0.3; R7–9 ≈0; R10–13 −0.2…−0.4; R14–17 −0.3…−0.5 | Risk `λ(phase)` per round band (floor-tilt >0, ceiling-tilt <0) |
| `lambda_slot_override` | `+0.40 / −0.40` | slot dominates phase | Force floor at last open startable slot; ceiling for surplus/stash |
| `replacement_blend` | `0.5 / 0.5` | VOLS/man-games (§10.3) | Blend for replacement baselines (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13) |
| `projection_blend` | `"simple_average"` | simple average | Cross-source μ blend method |
| `caps.modifier_abs_max` | *(removed)* | ≤~3–5 pts | ⛔ Bound on the positional modifiers — **unimplemented, and removed from `config/engine.json` in Tier 6**. Nothing read it, and `run_study` was spending one of six search dimensions on it. See §6.C.7. |
| `caps.mu_refinement_pct` | `0.15` | ±10–15% | μ-refinement cap on the projection blend |
| `candidate_cap` | `180` | ≈180 | Top-K candidate bound on the hot path |
| `mc_enabled` | `false` | analytic default | Toggle MC-VONA refinement |
| `mc_rollouts` | `2000` | ≈2000 | MC rollouts when `mc_enabled` |
| `reliability_shrinkage` | `{K:0.4, DST:0.4}` (others 1.0) | K/DST ≈0.35–0.5 | Shrink μ toward replacement for low-R² positions (§3.10 R1) — the kicker/DST fix |
| `punt_guard` | `{enabled:true, stream_round:{K:17, DST:16}}` | — | Never surface K/DST as the #1 rec before their stream round unless the roster is full (§3.10 R1) |
| `vona_horizon_picks` | `2` | 1=one-step, 2=turn-aware | How many upcoming picks VONA looks ahead (§3.10 R2) |
| `board_survival_weight` (β) | `0.5` | 0=static ADP | Weight of observed run pressure on effective ADP / survival (§3.10 R3) |
| `situation_adjust` | `{enabled:true, mu_cap_pct:0.15, vacated_regression:0.5, rookie_capital_weight:0.6, sigma_widen_on_change:1.25}` | caps ±10–15% | Opportunity/situation μ/σ adjustment for team change, vacated volume, rookie competition (§3.10 R4) |

**Loader (`backend/src/jaaffl/config.py` — additive; `Path` and `lru_cache` are already imported):**

```python
from pydantic import BaseModel   # add alongside existing pydantic_settings import

class EngineParams(BaseModel):
    version: int = 1
    scoring_format: str = "standard"
    kappa: float = 0.65
    alpha: float = 0.40
    projection_blend: str = "simple_average"
    flex_split: dict[str, int] = Field(default_factory=lambda: {"RB": 8, "WR": 4})
    lambda_schedule: list[dict] = Field(default_factory=list)   # [{"rounds":[lo,hi],"lambda":float}, ...]
    lambda_slot_override: dict[str, float] = Field(
        default_factory=lambda: {"last_startable_slot_floor": 0.40, "surplus_stash_ceiling": -0.40})
    replacement_blend: dict[str, float] = Field(
        default_factory=lambda: {"vols_weight": 0.5, "mangames_weight": 0.5})
    caps: dict = Field(default_factory=lambda: {
        "modifier_abs_max": 5.0, "mu_refinement_pct": 0.15,
        "modifiers": {"bye_stack": 3.0, "handcuff_synergy": 5.0, "sos": 3.0}})
    candidate_cap: int = 180
    mc_enabled: bool = False
    mc_rollouts: int = 2000
    # §3.10 v1.1 round-aware refinements
    reliability_shrinkage: dict[str, float] = Field(default_factory=lambda: {"K": 0.4, "DST": 0.4})  # others → 1.0
    punt_guard: dict = Field(default_factory=lambda: {"enabled": True, "stream_round": {"K": 17, "DST": 16}})
    vona_horizon_picks: int = 2         # 1 = one-step (legacy); 2 = turn-aware v1 default
    board_survival_weight: float = 0.5  # β; 0 = pure static ADP
    situation_adjust: dict = Field(default_factory=lambda: {  # §3.10 R4 opportunity/situation layer
        "enabled": True, "mu_cap_pct": 0.15, "vacated_regression": 0.5,
        "rookie_capital_weight": 0.6, "sigma_widen_on_change": 1.25})

class Settings(BaseSettings):
    # ... existing fields ...
    jaaffl_season: int = 2026
    jaaffl_enable_ffc: bool = True
    jaaffl_ffc_scoring: str = "standard"
    jaaffl_ffc_teams: int = 12
    jaaffl_engine_params_path: Path = Path("./config/engine.json")

@lru_cache
def get_engine_params() -> EngineParams:
    import json  # noqa: F401  (or model_validate_json directly)
    return EngineParams.model_validate_json(get_settings().jaaffl_engine_params_path.read_text())
```

`EngineParams` is passed into `build_draft_context()` (precompute) and read on the hot path; it is
part of the immutable `DraftContext`. Calibration scripts (`scripts/calibrate_flex_split.py`,
`scripts/tune_engine_params.py`, design §7.E) write back to `config/engine.json`, bumping `version`.
`config/engine.json` is a *tunable* file and is expressly **not** part of the immutable
`config/league.json` constitution; `jaaffl_ffc_teams=12` mirrors the fixed 12-team setting but never
overrides it.

### 1.6 Keeping the contracts in sync — schema-parity CI (E5 / B13)

Two contract definitions (Pydantic in `jaaffl.domain`, Zod in `packages/shared`) can silently drift.
The gate (design §7.E5) added to `.github/workflows/ci.yml`:

1. Emit JSON Schema from the Pydantic models (`LeagueSettings.model_json_schema()`,
   `Recommendation.model_json_schema()`).
2. Round-trip **canonical example fixtures** (committed under `packages/shared`, one per changed model,
   including a `LeagueSettings` with both `scoring_tiers` + `scoring_bonuses` and a `Recommendation`
   with a fully-populated `ScoreComponents`) through **both** Pydantic `.model_validate()` and Zod
   `.parse()`.
3. **Fail** the build on any validation divergence or field-set mismatch across the two.

Pydantic is the source of truth; a Zod change without the matching Pydantic change (or vice versa)
fails CI. This gate is the mechanical guarantee behind every "sync note" in §1.4.

### 1.7 Acceptance criteria

- [ ] The immutable league anchor is reproduced **verbatim** (Snake; 12 teams; in-person→CBS order;
      Standard/non-PPR; 17 rounds; QB=1/RB=1/WR=3/WR-RB=1/TE=1/K=1/DST=1/Bench=8); the flex is stated
      **WR-or-RB only**; the draft order is **read live, never inferred from team count**; and nothing
      in the section restates a setting differently.
- [ ] The **compliance envelope** (local-first, user's own authenticated CBS session, text-only, $0
      besides AI usage, personal/non-commercial) and the **honesty caveat** (no proven optimal live
      snake-draft solver; efficacy via the project's own offline sim tournament vs VBD-only/ADP-only;
      2027 outputs ESTIMATED) are both stated.
- [ ] The annotated end-to-end dataflow (§1.1) matches design §10.2 and every hop names a real
      package/path; the four scaffold changes are located on the diagram.
- [ ] The component map (§1.2) covers **every** package in the repo map with its roadmap stage, engine
      role, and scaffold-change touchpoints; new modules (`engine/context.py`, `ingest/log.py`,
      `engine/tiers.py`, `providers/ffc.py`, `providers/cbs_onpage.py`) are marked `[N]`.
- [ ] `jaaffl.engine.context` is named as the **owner of `DraftContext`**; `jaaffl.engine.recommend`
      owns the stateless `recompute()`; the precompute→context→recompute split and its <2 s / <200 ms
      budget are stated with per-step costs; the v1 (analytic) vs stretch (MC/CP-SAT/XGBoost) boundary
      is explicit.
- [ ] **SC1:** `ScoringBracket`/`ScoringTier`/`ScoringBonus` given in full for **both** Pydantic and Zod;
      `LeagueSettings` gains `scoring_tiers` + `scoring_bonuses`; DST scores on **both** points- and
      yards-allowed tiers; K 50+ bonus representable; exact CBS bracket values flagged UNVERIFIED.
- [ ] **SC2:** provider boundary returns `pl.DataFrame`; `data` extra swaps `nfl_data_py`+`pandas` →
      `nflreadpy`+`polars`; `Capability.EXPECTED_POINTS` added; crosswalk fn name flagged `[VERIFY]`;
      `scikit-learn` (GaussianMixture) present in the `engine` extra.
- [ ] **SC3:** `ScoreComponents` lists all nine fields (`mlv, vona, risk_penalty, cliff_bonus, sigma,
      floor, ceiling, replacement_baseline, modifiers`) with types in both Pydantic and Zod, embedded as
      `RecommendedPick.components`, with the `score` reconstruction formula.
- [ ] **SC4:** `WS /recs/ws` named as the backend→client push channel, existing endpoints preserved,
      full contract deferred to §8.
- [ ] `config/engine.json` lists **every** key (κ, α, λ-table + slot override, flex_split, caps,
      candidate_cap, mc_rollouts, replacement_blend, projection_blend) with defaults from design §10.3
      and a loader via `jaaffl.config`; baselines RB≈22–24, WR≈40–42, QB/TE/K/DST≈13 are stated.
- [ ] Immutable league settings (`config/league.json`) are untouched; `flex_split` is flagged
      **measure-live** (top-60 method); forward-year outputs treated as ESTIMATED.

### 1.8 Definition of done

- [ ] `backend/src/jaaffl/domain/models.py` compiles with `ScoringBracket`, `ScoringTier`,
      `ScoringBonus`, `ScoreComponents`, and the new fields on `LeagueSettings` + `RecommendedPick`.
- [ ] `packages/shared/src/{league,recommendation}.ts` mirror them exactly; `pnpm -r typecheck` passes.
- [ ] `providers/base.py` returns `pl.DataFrame`, declares `EXPECTED_POINTS`; `backend/pyproject.toml`
      `data` extra = `duckdb, pyarrow, polars, nflreadpy` and the `engine` extra carries `scikit-learn`;
      `ruff check` + import of the `data` extra pass.
- [ ] `backend/src/jaaffl/api/app.py` declares `WS /recs/ws` + `GET /league/{id}` alongside the existing
      routes; ingest → log → fold → recompute → broadcast wiring is stubbed.
- [ ] `config/engine.json` exists with the §1.5 defaults; `jaaffl.config.EngineParams` + `get_engine_params()`
      load it; `Settings` carries `jaaffl_season`, `jaaffl_enable_ffc`, `jaaffl_ffc_scoring`,
      `jaaffl_ffc_teams`, `jaaffl_engine_params_path`.
- [ ] Schema-parity CI (E5) job added to `.github/workflows/ci.yml` with canonical fixtures for the two
      changed models; the job fails on injected Pydantic⇄Zod drift (verified once).
- [ ] `config/league.json` diff is empty.

---

## 2. Database & warehouse design

JAAFFL's warehouse is three local stores under `JAAFFL_DATA_DIR` (default `./data`; `Settings.jaaffl_data_dir` in `backend/src/jaaffl/config.py`), each chosen for the *durability class* of the data it owns, not for convenience. The organizing principle (design §7 Step 7): **of everything the system holds, only the live pick stream is unrebuildable, so it — and only it — gets ACID durability with an append-before-compute discipline.** Everything else is either a re-pullable upstream snapshot or a pure function of such snapshots, and lives in a rebuildable store.

**Grounding (immutable — [`config/league.json`](config/league.json) `immutable:true`; never paraphrase or "optimize").** Every stored point projection, replacement baseline, and ADP join is computed against *this* roster, verbatim:

> - Draft Type: Snake
> - Teams: 12
> - Draft Order: Decided in-person, then entered into CBS Sports system
> - Scoring Format: Standard
> - Draft Rounds: 17
> - Roster Slots per Team: QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Standard = **non-PPR**. The `WR/RB` flex is **WR-or-RB only** (no TE/QB). The **draft order is read live from the CBS room and stored in the append-only log — it is NEVER inferred from team count** (ROADMAP Stage 2: "Never assume snake order from league size — read the actual draft board"; league.json `draft_order.infer_from_team_count:false`). This constraint is enforced at the exact layer that owns pick order (§2.6).

**Compliance & honesty (ADR 0003, [`docs/legal-and-compliance.md`](docs/legal-and-compliance.md)).** The warehouse holds only the user's own authenticated CBS session data, local-first, personal, non-commercial, $0 besides AI usage, text-only (no voice). There is **no peer-reviewed optimal live snake-draft solver** — efficacy is validated by the project's OWN offline simulated-league tournament vs VBD-only and ADP-only baselines (§2.8), which the snapshot corpus below exists to make possible.

**Store-ownership matrix (the one true split):**

| Store | File(s) under `data/` | Owns | Durability class | Rebuildable? |
|---|---|---|---|---|
| **SQLite** (ACID) | `app.sqlite` (+ `-wal`, `-shm`) | `draft_event_log`, `league_snapshots`, `players`, `id_crosswalk`, `manager_tendencies`, `schema_migrations` | Crash-safe (WAL, fsync) | **No** for the pick stream & raw CBS captures; identity resolutions are *decisions* we refuse to re-make |
| **DuckDB** (analytics) | `warehouse.duckdb` | `projections`, `adp`, backtest/analysis tables | Disposable | **Yes** — `make warehouse` recomputes from Parquet + SQLite |
| **Parquet** (cold columnar) | `parquet/nflverse/*`, `parquet/ffc/*`, `snapshots/draft_*/*` | raw nflverse pulls, FFC daily ADP cache, per-draft exports | Disposable | **Yes** — re-pull from nflverse release URLs / FFC API |

This implements the `Warehouse` stub (`backend/src/jaaffl/data/warehouse.py`: `init()`, `snapshot_league()`, `snapshot_draft_state()`) and the `Crosswalk` stub (`backend/src/jaaffl/data/crosswalk.py`: `resolve()`, `upsert()`), plus one new module `backend/src/jaaffl/ingest/log.py` (design §7.C.4 `[N] ingest/log.py`).

### 2.1 Why only the live pick stream is unrebuildable (design §7 Step 7)

| Data | Source of truth | Why (not) rebuildable |
|---|---|---|
| nflverse history / ECR / xEP | nflverse Parquet release URLs | Re-pullable any time → **rebuildable** (Parquet snapshot for reproducibility only) |
| FFC ADP (mean+SD+…) | `fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year={season}` | Re-pullable daily → **rebuildable**; we keep dated snapshots because ADP drifts through preseason |
| `projections`, tiers, replacement baselines | pure fn of the above + immutable CBS Standard scoring | Deterministically recomputable under `scoring_version` → **rebuildable** |
| `id_crosswalk` (fuzzy/manual rows) | our resolution decisions | *Mostly* reproducible (deterministic nflverse join), but fuzzy/manual matches are decisions → **persist, don't re-derive** |
| `league_snapshots` (raw CBS payloads) | the user's authenticated CBS session | CBS may not retain history; captured live, once → **not rebuildable**. ARCHITECTURE.md: the system "builds its own long-term manager-tendency dataset instead of depending on CBS history remaining accessible." |
| **`draft_event_log`** (live picks) | the CBS draft room, in real time | **THE unrebuildable store.** Each pick exists once, streamed from a tab that won't replay it. No free feed can reconstruct who took whom, in what order. |

**The crux:** a mid-draft crash is catastrophic *only* if a pick is lost, because a lost pick cannot be re-derived from any source. Therefore the pick stream is an **append-only log in SQLite (ACID)**, `DraftState` is a **fold over that log**, and ingest **commits the append before it runs any (slow, fallible) engine work**. Parquet and DuckDB can be deleted and rebuilt; `app.sqlite` is the only file whose loss is unrecoverable — so it is the only one that gets fsync durability and a per-draft backup export.

### 2.2 File layout under `data/`

```
data/
  README.md  .gitkeep                         # only git-tracked entries; everything else under data/ is git-ignored
  app.sqlite  app.sqlite-wal  app.sqlite-shm  # SQLite: ACID app state + append-only log
  warehouse.duckdb                            # DuckDB: materialized analytics (ATTACHes app.sqlite)
  parquet/
    nflverse/
      player_stats_{season}.parquet            # load_player_stats  → history
      ff_rankings_{season}_{yyyymmdd}.parquet   # load_ff_rankings   → ECR
      ff_opportunity_{season}.parquet           # load_ff_opportunity→ xEP
      ff_playerids.parquet                      # load_ff_playerids / load_players  [VERIFY minor]
    ffc/
      adp_{scoring}_{teams}_{season}_{yyyymmdd}.json     # raw FFC response (daily cache)
      adp_{scoring}_{teams}_{season}_{yyyymmdd}.parquet  # parsed
  snapshots/
    draft_{league_id}_{yyyymmdd'T'hhmmss'Z'}/   # written at draft_complete (snapshot-every-draft)
      events.parquet         # export of this draft's draft_event_log rows (backtest corpus)
      final_state.json       # fold_state(...) at draft_complete
      league_settings.json   # the LeagueSettings in force
      recommendations.jsonl  # every Recommendation emitted (offline audit vs VBD/ADP baselines)
```

`Warehouse.init()` creates `data/`, the Parquet/snapshot dirs, opens `app.sqlite` with the pragmas below, runs `schema_migrations`, and creates `warehouse.duckdb`. All of `data/` is git-ignored except `README.md` (which documents the ignore) + `.gitkeep`.

### 2.3 SQLite — ACID app state + append-only log (source of truth)

Connection pragmas (set on every open in `warehouse.py`):

```sql
PRAGMA journal_mode = WAL;      -- durable + concurrent reads while appending
PRAGMA synchronous  = FULL;     -- fsync WAL on commit: the pick is on disk BEFORE we recommend
                                --   (survives OS crash / power loss; NORMAL is the faster floor that
                                --    survives kill -9 but can lose the last commit on power loss)
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

#### `draft_event_log` — the crown jewel (unrebuildable)

```sql
CREATE TABLE IF NOT EXISTS draft_event_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,      -- monotonic total order; fold replays in seq order
    league_id   TEXT    NOT NULL,
    event_type  TEXT    NOT NULL
                  CHECK (event_type IN ('league_settings','draft_state',
                                        'on_the_clock','pick_made','draft_complete')),
    pick_number INTEGER,                                -- overall pick; NULL for non-pick events
    payload     TEXT    NOT NULL CHECK (json_valid(payload)),  -- normalized DraftEvent.data (JSON)
    source      TEXT    CHECK (source IN ('ws','framework','dom','manual')),  -- winning probe (provenance)
    captured_at TEXT    NOT NULL,                       -- extension capture time (ISO-8601 UTC)
    ingested_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

-- Cross-probe de-dup (design: "de-dup by pick_number"): a numbered event is stored once.
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_pick
    ON draft_event_log(league_id, event_type, pick_number) WHERE pick_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_event_league_seq
    ON draft_event_log(league_id, seq);
```

- `seq AUTOINCREMENT` gives a strict, never-reused monotonic order — the fold is a left-fold over `ORDER BY seq`.
- The `event_type` domain is exactly `domain.DraftEventType` (`league_settings`, `draft_state`, `on_the_clock`, `pick_made`, `draft_complete`); `payload` is the validated `DraftEvent.data` for that concrete per-type model.
- `source` is the winning probe of the **three-probe, transport-agnostic capture** (design §5/§7.C.2): `ws` (MAIN-world WebSocket/fetch/XHR monkeypatch), `framework` (React-fiber state read), `dom` (MutationObserver fallback), plus `manual` (manual-paste fallback).
- The **partial unique index** enforces de-dup at the storage layer: the three probes may deliver the *same* `pick_made`/`on_the_clock` for a `pick_number`; append with `INSERT OR IGNORE` → first write wins, redundant probes are dropped. `draft_state` re-syncs and `league_settings` carry `pick_number IS NULL` and are intentionally *not* de-duped (each is a legitimate new snapshot the fold consumes).

#### `league_snapshots` — raw CBS payloads over time (unrebuildable, live-captured)

```sql
CREATE TABLE IF NOT EXISTS league_snapshots (
    snapshot_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id    TEXT NOT NULL,
    kind         TEXT NOT NULL
                   CHECK (kind IN ('settings','projections','injuries','draft_board','other')),
    payload      TEXT NOT NULL CHECK (json_valid(payload)),  -- raw CBS JSON exactly as observed
    content_hash TEXT NOT NULL,                              -- sha256(payload): skip byte-identical repeats
    source       TEXT,
    captured_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX        IF NOT EXISTS ix_snap_league_time ON league_snapshots(league_id, kind, captured_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_snap_dedup       ON league_snapshots(league_id, kind, content_hash);
```

`Warehouse.snapshot_league(settings)` writes a `kind='settings'` row from `LeagueSettings.raw`. These rows are the warehouse feed that **`CbsOnPageProvider` (`providers/cbs_onpage.py`, `[N]`) reads (latest per `(league_id, kind)`), NOT a network fetch** (design §7.C.4). `content_hash` de-dups CBS's repeated identical pushes.

#### `players` — canonical player dimension (authoritative identity)

```sql
CREATE TABLE IF NOT EXISTS players (
    player_id  TEXT PRIMARY KEY,          -- JAAFFL canonical id (seed 'gsis:00-0034796', else 'jaaffl:<uuid>')
    name       TEXT NOT NULL,
    position   TEXT NOT NULL CHECK (position IN ('QB','RB','WR','TE','K','DST','DL','LB','DB')),
    nfl_team   TEXT,                       -- team abbr; DST uses team abbr; NULL for FAs
    name_norm  TEXT NOT NULL,             -- fuzzy key: lower, punctuation-stripped, Jr/Sr/III removed
    status     TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX IF NOT EXISTS ix_players_match ON players(position, nfl_team, name_norm);  -- fuzzy candidate lookup
```

Backs `domain.Player` (`player_id`, `name`, `position`, `nfl_team`, `external_ids`); the `position` CHECK is exactly the `domain.Position` enum. `external_ids` is reconstructed from `id_crosswalk` at load. The `player_id` *assignment* is a durable decision → authoritative here, never in DuckDB.

#### `id_crosswalk` — resolutions persisted (edge table)

```sql
CREATE TABLE IF NOT EXISTS id_crosswalk (
    source        TEXT NOT NULL
                    CHECK (source IN ('gsis','pfr','cbs','ffc','fantasypros',
                                      'sleeper','espn','yahoo','nflverse')),
    source_id     TEXT NOT NULL,
    canonical_id  TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    method        TEXT NOT NULL CHECK (method IN ('deterministic','fuzzy','manual')),
    confidence    REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    match_features TEXT CHECK (match_features IS NULL OR json_valid(match_features)),
                                        -- {name_score, team_match, pos_match, runners_up:[...]} — fuzzy audit
    resolved_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (source, source_id)      -- resolve(source, source_id) is one indexed row
) STRICT, WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_crosswalk_canonical ON id_crosswalk(canonical_id);
```

`(source, source_id)` PK ⇒ `Crosswalk.resolve(source, source_id)` is a single-row lookup returning `canonical_id`. `method` + `confidence` + `match_features` are the "resolution method + confidence" the deliverable requires and the audit trail for every fuzzy match. This is "resolutions persisted in SQLite" (design §7.C.4) verbatim.

#### Additional SQLite app-state tables (brief)

```sql
CREATE TABLE IF NOT EXISTS manager_tendencies (      -- accrued across drafts → engine/opponents.py priors
    league_id TEXT NOT NULL, team_id TEXT NOT NULL, position TEXT NOT NULL,
    reaches INTEGER DEFAULT 0, picks INTEGER DEFAULT 0, updated_at TEXT NOT NULL,
    PRIMARY KEY (league_id, team_id, position)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS schema_migrations (       -- Warehouse.init() runs pending migrations
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
) STRICT;
```

### 2.4 DuckDB — materialized analytics (rebuildable)

`warehouse.duckdb` reads identity live and scans Parquet directly — no data is duplicated:

```sql
INSTALL sqlite; LOAD sqlite;
ATTACH 'app.sqlite' AS app (TYPE SQLITE);          -- read players / id_crosswalk without copying
-- precompute joins scan Parquet in place, e.g.:
--   SELECT * FROM read_parquet('parquet/nflverse/player_stats_2026.parquet');
```

#### `projections` (materialized; design §7.C.5 `build_projections`)

```sql
CREATE TABLE IF NOT EXISTS projections (
    player_id       VARCHAR   NOT NULL,   -- canonical
    season          INTEGER   NOT NULL,
    source          VARCHAR   NOT NULL,   -- 'cbs' | 'nflverse_ecr' | 'nflverse_xep' | 'fantasypros' | 'blend'
    scoring_version VARCHAR   NOT NULL,   -- hash of the effective CBS Standard scoring map (below)
    stat_line       JSON,                 -- projected components {pass_yds, rush_td, receptions, ...}
    mu              DOUBLE    NOT NULL,   -- league-scored projected points (mean)
    sigma           DOUBLE,               -- cross-source spread
    floor           DOUBLE,               -- ~p10
    ceiling         DOUBLE,               -- ~p90
    computed_at     TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, source, scoring_version)
);
```

The `'blend'` row (**simple-average** blend, the EngineParams default) is what the engine loads into `DraftContext`. `scoring_version` is a hash of the **exact CBS Standard scoring map** recomputed via `league/scoring.py` — the linear rules **plus** the scaffold-change-#1 additions: DST **points-allowed AND yards-allowed** tier brackets (`LeagueSettings.scoring_tiers`) and the K 50+ yard bonus (`LeagueSettings.scoring_bonuses`). When `league_snapshots(kind='settings')` changes, `scoring_version` changes → re-materialize (never silently reuse stale points). σ/floor/ceiling come from cross-source spread.

#### `adp` (materialized from the FFC daily cache)

```sql
CREATE TABLE IF NOT EXISTS adp (
    player_id     VARCHAR NOT NULL,       -- canonical (FFC id/name → crosswalk → canonical)
    season        INTEGER NOT NULL,
    scoring       VARCHAR NOT NULL DEFAULT 'standard',  -- immutable league scoring
    teams         INTEGER NOT NULL DEFAULT 12,          -- immutable league size
    adp           DOUBLE  NOT NULL,       -- FFC mean draft position → m_j
    stdev         DOUBLE,                 -- FFC stdev → s_j;  survival S_j(N)=1−Φ((N−m_j)/s_j)
    high          INTEGER,
    low           INTEGER,
    times_drafted INTEGER,
    bye           INTEGER,
    captured_at   DATE    NOT NULL,       -- daily snapshot date (ADP drifts → keep the series)
    PRIMARY KEY (player_id, season, scoring, teams, captured_at)
);
```

Exactly the FFC fields (design §5.C). `adp` (→ `m_j`) + `stdev` (→ `s_j`) feed the analytic VONA survival `S_j(N)=1−Φ((N−m_j)/s_j)` directly; the engine reads the newest `captured_at`. Note (design §5.C): FFC mocks are **15-round**, so ADP thins past ~180 → the engine falls back to ECR for deep-round survival.

### 2.5 Parquet — raw upstream snapshots (rebuildable)

Immutable, columnar, nflverse-native (DuckDB scans zero-copy). Written by the providers during pre-draft materialization:

| File | Provider call | Cadence |
|---|---|---|
| `nflverse/player_stats_{season}.parquet` | `NflreadpyProvider` (`providers/nflverse.py`) → `load_player_stats` | per materialize |
| `nflverse/ff_rankings_{season}_{yyyymmdd}.parquet` | `load_ff_rankings` (ECR) | per materialize (dated) |
| `nflverse/ff_opportunity_{season}.parquet` | `load_ff_opportunity` (xEP) | per materialize |
| `nflverse/ff_playerids.parquet` | `load_ff_playerids` / `load_players` **[VERIFY minor]** | per materialize |
| `ffc/adp_standard_12_{season}_{yyyymmdd}.json`/`.parquet` | `FantasyFootballCalculatorProvider` (`providers/ffc.py`, `[N]`) | **cached daily** (skip if today's exists) |

### 2.6 `DraftState` as a fold over the log (`backend/src/jaaffl/ingest/log.py`)

New module (design §7.C.4 `[N] ingest/log.py`). Append is durable and de-duped; the fold is a **pure, deterministic** left-fold — no I/O, no wall-clock — so identical logs yield byte-identical `DraftState` on any machine.

```python
# backend/src/jaaffl/ingest/log.py
from collections.abc import Iterable
from sqlite3 import Connection
from typing import NamedTuple

from jaaffl.domain import DraftEvent, DraftPick, DraftState

class LoggedEvent(NamedTuple):
    seq: int; league_id: str; event_type: str
    pick_number: int | None; data: dict; source: str | None; captured_at: str

def append_event(conn: Connection, event: DraftEvent, *, pick_number: int | None,
                 source: str | None, captured_at: str) -> int | None:
    """Durably append ONE normalized event; return its seq, or None if de-duped.
    INSERT OR IGNORE against ux_event_pick. Commits (synchronous=FULL) BEFORE returning:
    the pick is on disk before any engine work is scheduled.
    pick_number/source/captured_at are supplied by the ingest handler from event.data + envelope."""

def read_events(conn: Connection, league_id: str, *, through_seq: int | None = None) -> list[LoggedEvent]:
    """All events for a league in ascending seq order (full history for replay)."""

def fold_state(events: Iterable[LoggedEvent]) -> DraftState:
    """Pure, deterministic left-fold of the log into a DraftState. No I/O, no clock."""
```

**Reducer semantics** (`fold_state`, one case per `DraftEventType`):

| `event_type` | Transition on the running `DraftState` |
|---|---|
| `league_settings` | Bind `league_id`, `my_team_id` (if present); no pick change |
| `draft_state` | **Full re-sync**: replace `picks`, `current_overall_pick`, `on_the_clock_team_id`, `available_player_ids` from the snapshot (authoritative reset; base for later picks — handles reconnects/late joins). The snapshot's order is the **live CBS order**, never a snake pattern inferred from the 12-team count |
| `on_the_clock` | Set `on_the_clock_team_id`, `current_overall_pick` |
| `pick_made` | Append `DraftPick(overall, round, pick_in_round, team_id, player_id)` **iff `overall` absent** (idempotent); advance `current_overall_pick`; drop `player_id` from `available_player_ids`. All fields are taken from the normalized payload (the live board); the fold never reconstructs draft order from team count (immutable: order is decided in-person and entered into CBS) |
| `draft_complete` | Mark terminal |

**Ingest ordering invariant** — wired in `jaaffl.ingest.handle_event` (the routed handler that `api/app.py` calls from both `POST /draft/events` and `WS /draft/ws`; design §7.C.6, ARCHITECTURE data-flow "validate, persist raw + normalized" → warehouse → recommend). *Append before engine work:*

1. Normalize raw CBS payload → `DraftEvent` (`ingest/cbs.py`: `normalize_league_settings` / `normalize_draft_state`).
2. `snapshot_league(...)` raw payloads → `league_snapshots` (for `CbsOnPageProvider`).
3. **`append_event(...)` → SQLite commit + fsync (DURABLE).**
4. `state = fold_state(read_events(conn, league_id))`.
5. `rec = recommend(context, state)`; broadcast on `WS /recs/ws`.

Because step 3 is durable **before** steps 4–5, a `kill -9` anywhere in 4–5 loses only recompute work — never a pick. On restart, `fold_state(read_events(conn, league_id))` reconstructs the **exact** pre-crash `DraftState`, and the next incoming pick continues seamlessly. Re-delivery after reconnect is harmless: `INSERT OR IGNORE` drops duplicate appends and the `pick_made` reducer is idempotent per `overall`.

### 2.7 ID crosswalk strategy (`backend/src/jaaffl/data/crosswalk.py`)

Two-stage resolution; authoritative store = SQLite `players` + `id_crosswalk`. `resolve(source, source_id)` is a PK lookup; `upsert(player)` merges `external_ids`, running the stages below and persisting every outcome.

**Stage A — deterministic nflverse-id join** (`method='deterministic'`, `confidence=1.0`). Seed `players` + `id_crosswalk` from the nflverse playerids crosswalk (`load_ff_playerids` / `load_players` — exact name **[VERIFY minor]**), which maps `gsis ⇄ pfr ⇄ sleeper ⇄ espn ⇄ yahoo ⇄ fantasypros ⇄ cbs` where present. `canonical_id` is seeded from the stable nflverse `gsis` id; every present source column becomes a deterministic `id_crosswalk` row. CBS/FFC ids that appear in this map resolve by exact join.

**Stage B — fuzzy fallback** (`method='fuzzy'`, `confidence=score`) for ids absent from Stage A (CBS custom ids, FFC name-keyed rows, rookies): compute `name_norm` (lower, strip punctuation + Jr/Sr/III, DST → team abbr), require exact `position` match and `nfl_team` match (team-agnostic for FAs), then rank `players` candidates by name similarity (`rapidfuzz.token_sort_ratio` / `WRatio`). Best candidate ≥ threshold τ (default `0.90`, configurable) → write a `fuzzy` row with `match_features` (name_score, team/pos match, runners-up) for audit. Below τ → leave unresolved and surface for manual mapping.

- **CBS ids:** pick events carry a CBS id + name/team/pos from the DOM. `resolve('cbs', cbs_id)` → Stage A hit, else Stage B on the co-captured (name_norm, team, pos). Persisted → next lookup is O(1).
- **FFC ids:** ADP rows carry name/team/pos (± id). Same A→B path; persisted so the `adp` join to `canonical_id` is stable.
- **Precedence on conflict:** `manual` > `deterministic` > highest-`confidence` `fuzzy`. A `manual` override (`confidence=1.0`) always wins and survives re-precompute (persisted, never recomputed away).

### 2.8 Data lifecycle

**Pre-draft materialization (once, offline — the §7.D precompute):**
1. Providers pull free data → **Parquet** (nflverse `load_*`; FFC daily ADP, skip if today's cached).
2. Resolve identities → **SQLite** (`players` + `id_crosswalk`: Stage A then B).
3. Materialize analytics → **DuckDB**: `ATTACH app.sqlite`, scan Parquet, compute league-scored `projections` (μ/σ/floor/ceiling under the exact CBS Standard map + `'blend'` row) and canonical-joined `adp`; compute tiers/cliff + replacement baselines — **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13** (design §10.3) — applying the flex allocation (default **8 RB / 4 WR**, MEASURED LIVE via the **top-60** method — likely more RB-heavy in non-PPR) from `EngineParams`.
4. Load `DraftContext` into memory → the per-pick hot path is a stateless recompute (no DuckDB on the hot path).

**During the draft:** extension → `WS /draft/ws` → `handle_event` runs the §2.6 invariant: raw CBS → `league_snapshots`; normalized events appended to `draft_event_log` **before** `recommend`. `CbsOnPageProvider` reads `league_snapshots` — never the network.

**Snapshot-every-draft (at `draft_complete`):** `Warehouse.snapshot_draft_state(state)` writes `snapshots/draft_{league_id}_{ts}/` — `events.parquet` (this draft's log rows), `final_state.json`, `league_settings.json`, `recommendations.jsonl`. This is the offline backtest corpus for the project's **own simulated-league tournament vs VBD-only / ADP-only baselines** (ADR 0003 — the only honest efficacy evidence, since no proven optimal solver exists) and the `manager_tendencies` training set; it also feeds the **STRETCH** rest-of-season Monte-Carlo season simulator (v1 needs none of it — v1 is only live append→fold→recommend). DuckDB reads these Parquet exports directly.

**Retention:**
- **SQLite crown jewels** (`draft_event_log`, `league_snapshots`, `id_crosswalk`, `players`, `manager_tendencies`): keep forever (small; the point is to *own* history).
- **Parquet upstream** (`nflverse/`, `ffc/`): keep latest-per-season + dated FFC through the season; prune prior-season daily FFC (rebuildable → safe).
- **DuckDB** `warehouse.duckdb`: disposable; the new `make warehouse` target rebuilds it from Parquet + SQLite. Deleting it is never data loss.

### 2.9 Graduation path — Postgres `jsonb` + Redis Streams (ROADMAP Stage 3; future, NOT v1)

Schemas are kept graduation-friendly per `warehouse.py`'s docstring ("stable enough to graduate to PostgreSQL `jsonb` + Redis Streams later without changing callers") and ROADMAP Stage 3 ("Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if multi-user"):

- JSON columns (`draft_event_log.payload`, `league_snapshots.payload`, `projections.stat_line`, `id_crosswalk.match_features`) map 1:1 to Postgres `jsonb`.
- The append-only, monotonic-`seq` `draft_event_log` maps 1:1 to a **Redis Stream** (`XADD`/`XREAD` + consumer groups) for multi-user real-time fan-out; `fold_state` stays **identical** (a pure fold over the ordered stream).
- `players` / `id_crosswalk` / `adp` / `projections` become Postgres tables (same columns).

v1 remains local SQLite + DuckDB + Parquet; this path is invoked only if the project goes multi-user.

### 2.10 Acceptance criteria

- **Durability (the headline):** `kill -9` the backend at any point across a 17-round draft; on restart, `fold_state(read_events(conn, league_id))` yields a `DraftState` **byte-identical** to pre-crash (same `picks` in order, `current_overall_pick`, `available_player_ids`), and the next CBS pick ingests + recommends normally.
- **Append-before-engine:** a fault injected in `recommend()` (raise before broadcast) still leaves the pick durably in `draft_event_log`; restart replays it.
- **De-dup:** the same pick delivered by all three probes (`ws`/`framework`/`dom`) yields exactly **one** `draft_event_log` row (`ux_event_pick`) and exactly one `DraftPick` after fold.
- **Determinism:** `fold_state(events)` is pure — identical input ⇒ identical `DraftState` across processes/machines (property test).
- **Draft-order fidelity:** picks fold in the exact live-board order carried by the events; no test path ever reconstructs order from the 12-team count (immutable settings).
- **Identity coverage:** 100% of picked CBS players resolve to a `canonical_id` before `recommend` (deterministic, fuzzy ≥ τ, or manual); every fuzzy row persists `method` + `confidence` + `match_features`; a `manual` override survives re-precompute.
- **Rebuildability:** deleting `warehouse.duckdb` + `parquet/` and running `make warehouse` reproduces identical `projections`/`adp` for a fixed `scoring_version` + upstream; deleting `app.sqlite` is the **only** unrecoverable loss.
- **Hot-path isolation / latency:** per-pick work touches only SQLite (append + indexed log read for fold ≤ a few hundred rows, sub-ms) + in-memory `DraftContext`; **no DuckDB/Parquet query on the hot path**; end-to-end **< 2 s/pick (analytic path < 200 ms)** (design §7.D).
- **Config:** every file lives under `JAAFFL_DATA_DIR` (default `./data`); nothing but `README.md` + `.gitkeep` is git-tracked.

### 2.11 Definition of done

- [ ] `Warehouse.init()` creates `data/` + Parquet/snapshot dirs, opens `app.sqlite` with WAL + `synchronous=FULL` + `foreign_keys=ON`, creates `warehouse.duckdb`, and runs `schema_migrations`.
- [ ] SQLite DDL applied for `draft_event_log`, `league_snapshots`, `players`, `id_crosswalk`, `manager_tendencies`, `schema_migrations`, incl. `ux_event_pick`, `ux_snap_dedup`, and match/canonical indexes.
- [ ] DuckDB DDL applied for `projections`, `adp`; `ATTACH app.sqlite (TYPE SQLITE)` + Parquet scan verified.
- [ ] `backend/src/jaaffl/ingest/log.py` implements `append_event` (`INSERT OR IGNORE`, returns `seq`/`None`, commits before returning), `read_events`, and pure `fold_state`.
- [ ] `jaaffl.ingest.handle_event` (called by `api/app.py` `POST /draft/events` + `WS /draft/ws`) wired in the §2.6 order: normalize → snapshot → **append (durable)** → fold → recommend → `WS /recs/ws` broadcast.
- [ ] `Crosswalk.resolve` / `Crosswalk.upsert` implement Stage A (deterministic nflverse join) + Stage B (rapidfuzz name+team+pos, τ default 0.90), persist `method`/`confidence`/`match_features`, honor `manual > deterministic > fuzzy` precedence.
- [ ] `Warehouse.snapshot_league` → `league_snapshots`; `Warehouse.snapshot_draft_state` → per-draft `snapshots/draft_*/` export.
- [ ] New `make warehouse` target (re)materializes DuckDB from Parquet + SQLite; the rebuild/clean step removes `warehouse.duckdb` + `parquet/` but **never** `app.sqlite` (the existing `make clean` already leaves `data/` untouched).
- [ ] Tests: `fold_state` determinism property test; `kill -9` mid-draft → exact-replay integration test; three-probe de-dup test; live-order-preserved (no snake-from-team-count) test; crosswalk fuzzy-resolution + manual-override test; `scoring_version` re-materialization test.
- [ ] `[VERIFY minor]` nflverse crosswalk fn (`load_ff_playerids` vs `load_players`) confirmed; `[UNVERIFIED]` CBS payload shapes feeding `league_snapshots`/`draft_event_log` validated against golden fixtures.

---

## 3. Backend engines — the transparent pipeline

This section turns design §4.D, §6.C, §7.C.5 and §7.D into an execution-ready build spec for
`backend/src/jaaffl/engine/` plus its two `league/` dependencies. It is the heart of v1: live CBS
picks → a **decomposed**, league-correct, risk-aware, flex-aware recommendation in <2 s on the $0
data tier. Notation follows §7.C: **[E]** implement an existing stub · **[A]** amend · **[N]** new.

> **Computed against THIS roster (immutable — `config/league.json`, `immutable:true`; never paraphrase, re-order, or "optimize"):**
> Draft Type: Snake · Teams: 12 · Draft Order: Decided in-person, then entered into CBS Sports
> system · Scoring Format: Standard (non-PPR) · Draft Rounds: 17 · Roster Slots per Team: QB=1,
> RB=1, WR=3, WR/RB=1, TE=1, K=1, DST=1, Bench=8. Derived: 9 starters + 8 bench = 17 rounds; the
> WR/RB flex is **WR-or-RB only** (no TE/QB). The 9 starting slots the engine optimizes are `QB, RB,
> WR, WR, WR, FLEX(RB|WR), TE, K, DST`. The draft order is read **live from the CBS room** — never
> inferred as a plain snake from team count.

**The pipeline is a fold, not a black box.** Every number the overlay shows traces to one term of
the canonical score (design §6.C.7). We reproduce it here once as the contract the whole section
builds toward — do not re-derive it, cite it as "design §6.C.7":

```text
Score(p) =  MLV_p                     # Stage 1: flex-aware Marginal Lineup Value (value core)
          + κ · max(0, VONA_p)        # Stage 2: scarcity urgency (survival from FFC ADP mean+SD)
          − λ(phase,slot) · σ̂_p       # Stage 3: risk tilt (floor early, ceiling late)
          + α · CliffBonus_p          # Stage 4: tier-cliff urgency (Boris-Chen GMM)
          + Σ capped modifiers        # bye-stack −, handcuff + , SOS ± (each ≤ ~3–5 pts)
```

Data flow (one-time precompute → per-pick hot path; see §3.8):

```text
providers ─► build_draft_context() ─────────────────────────► DraftContext (in-memory, immutable)
  (Stage 0 projections μ/σ/floor/ceiling under exact CBS map,        │
   league points, replacement baselines + flex split,                │  precompute once
   GMM tiers + cliff bonuses, FFC ADP mean/SD, crosswalk)            │
                                                                      ▼
live DraftState ──► recommend(state, ctx, params) == stateless recompute():
   mask picked → survival S_j(N*) → top-K candidates → MLV (Hungarian)
   → VONA → risk → cliff → modifiers → assemble ScoreComponents → sort
```

### 3.0 Contracts & config the engine consumes (scaffold changes #1–#3 + `EngineParams`; #4 is transport)

The engine cannot compile until the design §7 / §10.5 scaffold changes land in
`backend/src/jaaffl/domain/models.py` and a new `EngineParams`. Keep Pydantic ⇄ Zod in sync
(`packages/shared/src/{recommendation,league}.ts`); `EngineParams` is backend-only (no Zod mirror).
Three of the four §7/§10.5 scaffold changes are engine-facing and specified here (**#1** tiered
scoring, **#2** nflreadpy→Polars provider returns, **#3** `ScoreComponents`). **Scaffold change #4
(the `/recs/ws` backend→overlay push channel) is transport, not engine** — it lives in the
API/extension section (design §7/§10.5); the engine only produces the `Recommendation` that channel
pushes, alongside the existing `/draft/ws` ingest socket.

**[A] `domain/models.py` — `ScoreComponents` (scaffold change #3), embedded on `RecommendedPick`.**

```python
class ScoreComponents(BaseModel):
    """Full decomposition of Score(p); every field is renderable in the overlay/assistant."""
    mlv: float                                  # Stage 1 flex-aware value core
    vona: float                                 # Stage 2 raw VONA_p (may be <0; score uses max(0,·))
    risk_penalty: float                         # Stage 3 signed λ·σ̂  (Score SUBTRACTS this term)
    cliff_bonus: float                          # Stage 4 CliffBonus_p (pre-α)
    sigma: float                                # σ̂_p, season-points scale
    floor: float                                # μ_p − z_lo·σ_p
    ceiling: float                              # μ_p + z_hi·σ_p
    replacement_baseline: float                 # baseline league pts at pos(p) used for MLV
    modifiers: dict[str, float] = Field(default_factory=dict)   # named, each already capped
    # §3.10 v1.1 additive/optional — round-aware explainability (default None; safe for the Phase-0 scaffold)
    reliability: float | None = None            # r_pos applied to μ (§3.10 R1)
    vona_horizon: int | None = None             # picks VONA looked ahead (§3.10 R2)
    best_available_next: float | None = None    # E[best MLV still available at pos by N_H*] (§3.10 R2)
```

`RecommendedPick` gains `components: ScoreComponents | None = None`. Field convention for the
existing fields: `score = Score(p)`, `projected_points = μ_p`, `vorp = MLV_p` (flex-aware VOR —
the empty-roster reduction, §3.3), `adp = adp_mean`, `next_turn_availability = S_p(N*)`,
`tier = tiers[p]`, `rationale` = one-line prose over the dominant component.

**[A] `domain/models.py` — tiered scoring (scaffold change #1)**, mirrored in `league.ts`
(`ScoringTierSchema {stat, brackets:{lower,upper|null,points}[]}`, `ScoringBonusSchema
{stat,threshold,points}`):

```python
class ScoringBracket(BaseModel):
    lower: float
    upper: float | None            # None = open-ended top bracket (e.g. DST 35+ pts allowed)
    points: float

class ScoringTier(BaseModel):
    stat: str                      # "dst_points_allowed", "dst_yards_allowed"
    brackets: list[ScoringBracket] # ordered, non-overlapping; matched by value ∈ [lower, upper)

class ScoringBonus(BaseModel):
    stat: str                      # count of qualifying events, e.g. "fg_made_50plus"
    threshold: float               # documents the qualifying edge (50.0); ingest pre-buckets
    points: float                  # awarded per qualifying event

class LeagueSettings(BaseModel):
    # ...existing fields (league_id, team_count, roster_slots, scoring, draft_order, ...)...
    scoring_tiers: list[ScoringTier] = Field(default_factory=list)
    scoring_bonuses: list[ScoringBonus] = Field(default_factory=list)
```

Position is **implicit via stat presence** (only DST stat lines carry `dst_points_allowed`; only K
carries `fg_made_50plus`) — this keeps the schema exactly `{stat, brackets}` / `{stat, threshold,
points}` and avoids an `applies_to` drift point. **[VERIFY]** the exact CBS "Standard" DST
brackets and K FG-distance values from the league scoring page before the draft; CBS scores DST on
**both** points-allowed **and** yards-allowed tiers (design §5.C, §6.D).

**[A] `providers/base.py`** — add `Capability.EXPECTED_POINTS = "expected_points"` (scaffold data
tier; `NflreadpyProvider` declares it via `load_ff_opportunity`). Provider return type migrates
pandas → **Polars** with the `nflreadpy` swap (scaffold change #2, design §7.C.4); the engine only
ever sees canonical-id-keyed dicts, so the Polars change is contained to `providers/` + `data/warehouse.py`.

**[N] `EngineParams`** — every Greek-letter weight is a tunable, versioned in `config/engine.json`
(path from a new `config.py` `Settings.jaaffl_engine_params_path`), fed by calibration E1/E2
(design §7.E). Defaults are design §10.3:

```python
class LambdaSchedule(BaseModel):        # λ>0 floor-tilt, λ<0 ceiling-tilt (design §6.C.5)
    r1_2:  float = 0.30     # +0.2…+0.4
    r3_6:  float = 0.20     # +0.1…+0.3
    r7_9:  float = 0.00     # ≈0
    r10_13: float = -0.30   # −0.2…−0.4
    r14_17: float = -0.40   # −0.3…−0.5

class EngineParams(BaseModel):
    version: int = 1
    kappa: float = 0.6                  # κ, VONA weight (0.5–0.8; avoid double-count)
    alpha: float = 0.4                  # α, cliff-bonus weight (0.3–0.5)
    lambda_schedule: LambdaSchedule = LambdaSchedule()
    flex_split_rb: int = 8              # of 12 flex slots — MEASURE LIVE (E1, top-60); likely RB-heavier
    flex_split_wr: int = 4
    vols_weight: float = 0.5            # baseline = 0.5·VOLS + 0.5·man-games (scarce top end)
    z_lo: float = 1.28                  # 10th-pct floor
    z_hi: float = 1.28                  # 90th-pct ceiling
    mu_refine_cap: float = 0.15         # xEP/context μ refinement capped at ±10–15% of base μ
    modifier_cap: float = 4.0           # each modifier ≤ ~3–5 pts; Σ also clamped
    candidate_cap: int = 180            # top-K hot-path bound
    mc_rollouts: int = 2000             # MC VONA / season sim (opt-in, stretch)

def load_engine_params(path: Path) -> EngineParams: ...   # config/engine.json → EngineParams
```

**Acceptance:** `pytest` round-trips a canonical `RecommendedPick.components` and a tiered-DST +
K-bonus `LeagueSettings` through Pydantic **and** Zod (schema-parity CI E5); `EngineParams` loads
from `config/engine.json` with the §10.3 defaults when the file is absent.

---

### 3.1 Stage 0 — Projection blend · `engine/projections.py::build_projections` [A]

Produce, per player, a stat line and its season-point distribution **recomputed under the exact CBS
map (Rec = 0)** — this is the one place non-PPR is enforced (design §6.C.1). Simple-average blend of
the $0 sources (CBS on-page + ECR→pts + xEP), optional FantasyPros when the flag is on.

**Return type** (amended from the stub's `dict[str, dict[str, float]]` per design §7.C.5; `params`
inserted so blend weights/`z`/`μ`-cap come from `EngineParams`):

```python
@dataclass(frozen=True, slots=True)
class PlayerProjection:
    player_id: str
    position: Position
    stat_line: dict[str, float]     # blended stats, canonical keys (match ScoringRule.stat)
    mu: float                       # E[season league points] under exact CBS scoring
    sigma: float                    # season-points SD (σ̂ lives on this scale)
    floor: float                    # mu − z_lo·sigma
    ceiling: float                  # mu + z_hi·sigma
    sources: dict[str, float]       # per-source league points {"cbs":…,"ecr":…,"xep":…} for transparency

def build_projections(
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    params: EngineParams,
    season: int,
    week: int | None = None,
) -> dict[str, PlayerProjection]: ...
```

**Algorithm.**
1. For each enabled provider, pull its native capability and convert to **league points via
   `league.scoring.league_points`** (§3.2) under `settings.scoring` + `scoring_tiers` +
   `scoring_bonuses`:
   - `Capability.PROJECTIONS` (CBS on-page, opt. FantasyPros): stat line → points directly.
   - `Capability.RANKINGS` (`load_ff_rankings` ECR): rank → points via `_ecr_to_points(pos, ecr)`,
     the position's historical **league-points-at-positional-rank** curve (fit once from
     `load_player_stats` 2021–2024 recomputed under the CBS map; monotone, cached in the warehouse).
   - `Capability.EXPECTED_POINTS` (`load_ff_opportunity` xEP): opportunity → expected points prior
     under the CBS map; used both as a blend source **and** as a bounded μ refinement
     (`|Δμ| ≤ params.mu_refine_cap · μ_base`).
2. **μ_p = simple average** of available source points (default `w_s = 1/n`; empirically ≥ weighted,
   design §6.C.1). Store each source in `sources` for CI + the assistant's explanation.
3. **σ_p = blend(** cross-source SD **,** historical same-position/tier weekly-residual SD **)** — a
   single source cannot self-report dispersion, so the historical residual is the floor on σ.
4. `floor = μ − z_lo·σ`, `ceiling = μ + z_hi·σ` (z≈1.28 ⇒ 10/90 band).

Missing crosswalk id ⇒ fuzzy name+team+pos fallback already resolved upstream in
`data/crosswalk.py`; `build_projections` only sees canonical ids.

**Acceptance (feeds E3):** for a fixture player, `mu` equals the hand-computed CBS-scored blend;
Rec appears **nowhere** in the point total; `sources` has one entry per enabled provider; 80% of
realized 2021–2024 points fall inside `[floor, ceiling]` (interval-coverage calibration).

---

### 3.2 League points & replacement baselines · `league/scoring.py`, `league/replacement.py`

**`league_points` [A]** — extend the existing linear evaluator with tiered brackets + threshold
bonuses (design §6.C.1, §7.C.4). Keep the current `(stat_line, scoring, position)` positional core;
add two keyword-only passes:

```python
def league_points(
    stat_line: Mapping[str, float],
    scoring: list[ScoringRule],
    position: Position,
    *,
    tiers: list[ScoringTier] | None = None,      # DST points- AND yards-allowed brackets
    bonuses: list[ScoringBonus] | None = None,   # K 50+ yard bonus
) -> float:
    total = 0.0
    for rule in scoring:                                  # (existing) linear points-per-unit
        if rule.applies_to is not None and position not in rule.applies_to:
            continue
        total += stat_line.get(rule.stat, 0.0) * rule.points_per_unit
    for tier in tiers or []:                              # tiered brackets, matched by stat presence
        if tier.stat not in stat_line:
            continue
        v = stat_line[tier.stat]
        for b in tier.brackets:                           # ordered [lower, upper); upper None = open
            if v >= b.lower and (b.upper is None or v < b.upper):
                total += b.points
                break
    for bonus in bonuses or []:                           # threshold bonuses (per qualifying event)
        total += stat_line.get(bonus.stat, 0.0) * bonus.points
    return total
```

DST evaluates **both** `dst_points_allowed` and `dst_yards_allowed` tiers and sums them (design
§6.D). K's FG-distance scoring may be cleaner as its own `ScoringTier` on `fg_distance` than a bonus
— follow whichever the CBS page dictates **[VERIFY]**; the evaluator supports both.

**`replacement_values` [E]** — implement the design §6.C.2 baseline (the load-bearing computation
for THIS roster). `starter_demand` already returns dedicated demand `{QB:12, RB:12, WR:36, TE:12,
K:12, DST:12}` — dedicated slots × 12 teams (QB 1×12, RB 1×12, WR 3×12, TE/K/DST 1×12; the flex is
intentionally excluded). The 12 `WR/RB` flex slots are allocated below, so league-wide the startable
RB+WR pool is 12 RB + 36 WR + 12 flex = **60 of the 108 total starters** (9 × 12). Add flex
allocation + man-games deepening + VOLS blend:

```python
def replacement_values(
    settings: LeagueSettings,
    projected_points: dict[str, float],       # μ_p from Stage 0
    players: dict[str, Player],
    *,
    flex_split: tuple[int, int],              # (rb, wr) from EngineParams; default (8, 4)
    vols_weight: float = 0.5,                 # baseline = w·VOLS + (1−w)·man-games
    games_missed: Mapping[Position, float] | None = None,   # BEER man-games (calibrated E1/E2); RB≈4 → RB25 per §10.3
) -> dict[Position, float]:
    demand = starter_demand(settings)                     # dedicated slots × teams
    demand[Position.RB] += flex_split[0]                  # → VOLS RB20 (12 + 8)
    demand[Position.WR] += flex_split[1]                  # → VOLS WR40 (36 + 4)
    out: dict[Position, float] = {}
    for pos, vols_idx in demand.items():
        gm = (games_missed or {}).get(pos, 0.0)
        mg_idx = vols_idx + round(vols_idx * gm / 17)     # man-games deepening (17-round season)
        rank = max(1, round(vols_weight * vols_idx + (1 - vols_weight) * mg_idx))
        ranked = sorted(
            (μ for pid, μ in projected_points.items() if players[pid].position == pos),
            reverse=True,
        )
        out[pos] = ranked[rank - 1] if rank <= len(ranked) else (ranked[-1] if ranked else 0.0)
    return out
```

Yields the design §6.C.2/§10.3 targets: **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13** — steep RB top
(anchor early), deep WR (breadth/wait), shallow-flat everything else (defer). Design §10.3 pins the
RB path exactly: VOLS RB20 → man-games RB25 → 0.5/0.5 blend ⇒ RB≈22–24; the deeper/flatter pools
barely deepen, so `games_missed` for WR/QB/TE/K/DST is small and set by calibration (E1/E2).
**The flex split is the single most sensitive knob** (RB18↔RB22 across 6/6↔10/2) — MEASURE IT LIVE
(E1, top-60 method: rank RB+WR by non-PPR 12-team FFC ADP, `flex_RB = #RB in top-60 − 12`,
`flex_WR = #WR in top-60 − 36`, so `flex_RB + flex_WR = 12`); default 8/4 is a placeholder likely
too WR-heavy for non-PPR.

**Dynamic in-draft recompute [N]** — the bridge into VONA (design §6.C.2 "Dynamic VBD"): as
positions deplete, recompute the baseline from **remaining startable demand** over **still-available**
players, so a mid-draft RB run raises the effective RB baseline and re-prices every RB.

```python
def dynamic_replacement_values(context: DraftContext, state: DraftState) -> dict[Position, float]:
    """Baseline[pos] = μ of the (remaining league-wide startable demand at pos)-th best AVAILABLE player."""
    ...
```

**Acceptance:** with the §10.3 flex split and man-games, `replacement_values` returns RB∈[22,24],
WR∈[40,42], others∈[13,14] on the calibration fixture; `dynamic_replacement_values` monotonically
raises a position's baseline as its startable pool shrinks.

---

### 3.3 Stage 1 — Flex-aware Marginal Lineup Value · `engine/optimize.py::marginal_lineup_value` [N]

The **value currency** of the whole engine (design §6.C.3): a candidate's marginal gain to the
**optimal 9-starter lineup**, solved as a bipartite assignment over the 9 slots with the WR/RB flex
mask and a replacement-filled baseline lineup.

```python
@dataclass(frozen=True, slots=True)
class StartingSlot:
    label: str                     # "QB","RB","WR","WR","WR","FLEX","TE","K","DST"
    eligible: frozenset[Position]  # FLEX -> {RB, WR}  (NO TE/QB — league flex is WR/RB only)

def expand_starting_slots(settings: LeagueSettings) -> list[StartingSlot]:
    """Expand roster_slots (starting=True) by count → the 9-slot list for THIS roster."""

def marginal_lineup_value(
    candidate_id: str,
    roster: Sequence[str],                     # your currently rostered player_ids
    mu: Mapping[str, float],                   # μ_p, league points (from DraftContext)
    position: Mapping[str, Position],
    baselines: Mapping[Position, float],       # replacement phantoms (static or dynamic)
    slots: Sequence[StartingSlot],
) -> float: ...
```

**Definitions (design §6.C.3).** The replacement-filled baseline lineup `B(R)` fills every *empty*
starting slot with a phantom replacement at that slot's position (flex phantom μ = `max(RB_base,
WR_base)`). `L*(R)` is the optimal position-legal assignment value:

```text
L*(R) = max over legal assignments of  Σ_slot μ(player_in_slot)
MLV_p = L*( B(R ∪ {p}) ) − L*( B(R) )
```

**Matrix construction** for `L*`: rows = the 9 `StartingSlot`s; columns = `roster ∪ {one phantom
per slot} ∪ {candidate}`. Cost `C[i, j] = −μ_eff(j)` if `position[j] ∈ slots[i].eligible` else a
large `BIG` (ineligible); phantom-j for slot i carries `μ_eff = baselines[pos(slot i)]` (flex phantom
= `max(RB_base, WR_base)`). Solve with **`scipy.optimize.linear_sum_assignment(C)`**; `L* =
−C[row, col].sum()`. Compute `L*(B(R))` once per pick (cached on `DraftContext`/recompute), then one
solve per candidate with `p` added.

**Properties to assert in tests:**
- **Empty roster ⇒ MLV_p = μ_p − baseline(pos(p)) = classic VOR** (cross-position comparable; does
  *not* over-rank raw QB points). This is the reduction test.
- **WR/RB flex is native**: a 4th WR is evaluated against the flex phantom `max(RB_base, WR_base)`;
  it earns MLV only if it beats that phantom (or your current flex occupant).
- **Need is automatic**: once the QB slot holds a real QB, a 2nd QB's MLV ≈ `μ_QB2 − μ_QB1 → ~0`
  (auto-deferred; no hand-tuned "need multiplier").
- **Pure bench stashes ⇒ MLV ≈ 0 by design** — a player who cracks no starting slot adds nothing to
  the *starting* lineup; their value is carried by the ceiling tilt (Stage 3, λ<0) and future-injury
  VONA (an MC stretch refinement), not MLV.

**Fast path (dominance shortcut, §7.D step 4).** For this fixed 9-slot roster the assignment has a
trivial greedy optimum — best RB→RB, best 3 WR→WR1–3, `FLEX = max(next RB, next WR)`, best at each
single-eligible slot — so a candidate that cannot displace the current worst startable at an eligible
slot gets `MLV = 0` without a solve. Use the greedy value as the default and reserve
`linear_sum_assignment` for the general/verification path and any future multi-flex league.

**Acceptance:** empty-roster MLV equals `μ − baseline` for all positions (VOR reduction); a 2nd QB
on a QB-filled roster scores `≈ μ_QB2 − μ_QB1`; greedy and Hungarian agree on 1000 random rosters.

---

### 3.4 Stage 2 — VONA / survival · `engine/opponents.py::pick_probabilities` [E]

Opportunity cost is what makes the engine *live* (design §6.C.4). Closed-form Gaussian survival from
FFC ADP mean + SD, vectorized in NumPy; Monte-Carlo is a refinement/stretch (§3.9), **analytic is the
v1 default**.

```python
def next_overall_pick(settings: LeagueSettings, state: DraftState) -> int:
    """Your next overall pick N* from the ACTUAL entered draft_order + snake reflection.
    NEVER infer order from team_count — read settings.draft_order (immutable league rule)."""

def pick_probabilities(
    state: DraftState,
    settings: LeagueSettings,
    adp: Mapping[str, float],                  # FFC ADP mean m_j
    adp_sd: Mapping[str, float],               # FFC ADP stdev s_j
    *,
    horizon: int | None = None,                # picks until your next turn; default from snake schedule
    my_next_overall: int | None = None,        # N*; default next_overall_pick(...)
) -> dict[str, float]:
    """player_id -> P(taken before your next pick) = Φ((N* − m_j)/s_j) = 1 − S_j(N*).
    Vectorized: z = (N* − m)/s over available; cdf via scipy.stats.norm.cdf or 0.5*(1+erf(z/√2))."""
```

Survival (what the overlay shows as availability) and the VONA baseline:

```text
S_j(N) = P(slot_j > N) = 1 − Φ( (N − m_j) / s_j )          # availability at pick N (= 1 − pick_probabilities)
N*     = next_overall_pick(...)                            # from the ACTUAL snake order
```

```python
def expected_best_available(
    candidates: Sequence[str],                 # available at pos π, sorted by MLV desc
    mlv: Mapping[str, float],
    survival: Mapping[str, float],             # S_j(N*)
    replacement: float,                        # tail value if all named candidates are gone
) -> float:
    """E[best surviving MLV at π by N*].
    Exact expected-max:  Σ_k MLV_k · S_k · Π_{i<k}(1−S_i)  + replacement · Π_all(1−S_i)
    Cheap shortcut (design §6.C.4): MLV of the π-player whose cumulative survival first crosses ~0.5."""
```

Then, for a candidate `p` at position `π = pos(p)`:

```text
VONA_p = MLV_p − expected_best_available(π, …)
```

**Worked example (design §6.C.4, reproduce as the golden test).** You hold **3.01 (overall 25)**;
your next pick is **4.12 (overall 48)** — 23 picks away, computed from the *actual* entered order,
not assumed. `N* = 48`.

| Candidate | FFC m_j | FFC s_j | z = (48−m)/s | S(48) = 1−Φ(z) | Read |
|---|---|---|---|---|---|
| WR | 30 | 8 | +2.25 | 1 − 0.988 = **0.012** | ~1% survives → **high VONA now** |
| RB | 55 | 10 | −0.70 | 1 − 0.242 = **0.758** | **76%** survives → **low VONA → wait** |

Exactly the WR-vs-RB call, straight from the two numbers FFC returns. **FFC caveat (design §5.C):**
mocks are 15-round, so ADP thins past ~180 — fall back to ECR-derived survival for deep rounds;
always query the current draft `season` (`teams=12&year={season}`), since a year with no mock-draft
data yet returns "No ADP data".

**Acceptance:** the worked example reproduces S(48)=0.012 (WR) and 0.758 (RB) to 3 dp; vectorized
survival over a 300-player board matches a scalar loop; `expected_best_available`'s exact
expected-max and its 0.5-crossing shortcut agree within tolerance on the fixture, and both fall back
to `replacement` when the candidate pool is exhausted.

---

### 3.5 Stage 3 — Risk term & the λ schedule · `engine/recommend.py` (helper)

Tilt toward floor when banking a starter, toward ceiling when swinging on a bench stash (design
§6.C.5). σ̂_p is already on the season-points scale from Stage 0, so `σ̂_p = σ_p`.

```python
class SlotState(StrEnum):
    LAST_OPEN_STARTABLE = "last_open_startable"   # p fills your final open startable slot at its pos
    SURPLUS = "surplus"                            # depth/stash beyond startable need
    NORMAL = "normal"

def lambda_weight(round_no: int, slot_state: SlotState, params: EngineParams) -> float:
    """Phase default from the λ schedule, then slot override (override DOMINATES phase)."""
    sched = params.lambda_schedule
    base = (sched.r1_2 if round_no <= 2 else sched.r3_6 if round_no <= 6
            else sched.r7_9 if round_no <= 9 else sched.r10_13 if round_no <= 13 else sched.r14_17)
    if slot_state is SlotState.LAST_OPEN_STARTABLE:
        return abs(base) if base != 0 else 0.2     # force floor-tilt (+)
    if slot_state is SlotState.SURPLUS:
        return -abs(base) if base != 0 else -0.2   # force ceiling-tilt (−)
    return base

# risk_penalty (signed) = lambda_weight(...) * projection.sigma   → Score SUBTRACTS it
```

Full schedule (design §6.C.5; **λ>0 = floor-tilt, λ<0 = ceiling-tilt**; all in `EngineParams`):

| Phase (rounds) | Intent | Default λ | Rationale |
|---|---|---|---|
| R1–2 anchors | mild floor | **+0.2 to +0.4** | protect premium capital; bank the berth |
| R3–6 core starters | mild floor | **+0.1 to +0.3** | reliable weekly starters |
| R7–9 flex/starter fill | neutral | **≈ 0** | best value |
| R10–13 bench upside | ceiling | **−0.2 to −0.4** | cheap lottery tickets |
| R14–17 deep bench | strong ceiling | **−0.3 to −0.5** | pure swings (K/DST exempt = punt) |

**Slot override dominates phase:** filling your **last open startable slot** at a position → force
floor-tilt; surplus depth/stash → force ceiling-tilt. `slot_state` is derived from `DraftState` +
`expand_starting_slots` (how many startable slots at pos(p) remain unfilled). K/DST in R16/R17 are a
punt — λ is irrelevant (stream).

**Acceptance:** an R1 pick gets λ≥+0.2; an R15 stash gets λ≤−0.3; a player filling the last WR
starter slot in R11 is forced positive despite the R10–13 ceiling default (override test).

---

### 3.6 Stage 4 — Tier cliffs · `engine/tiers.py` [N]

Boris-Chen tiers via `sklearn.mixture.GaussianMixture` on ECR (adds `scikit-learn` to the `engine`
extra, design §7.C.5) — interpretation + guard rail, not an optimizer.

```python
def assign_tiers(
    ecr: Mapping[str, float],                  # expert consensus rank per player
    position: Mapping[str, Position],
    *,
    max_tiers_per_pos: int = 8,
    random_state: int = 0,
) -> dict[str, int]:
    """Per position: fit GaussianMixture on 1-D ECR, pick component count by BIC (≤ max_tiers),
    order components by mean ECR → 1-indexed tier. Deterministic via random_state."""

def cliff_bonuses(
    tiers: Mapping[str, int],
    mlv: Mapping[str, float],
    position: Mapping[str, Position],
) -> dict[str, float]:
    """CliffBonus_p = MLV_p − MLV_{best player in next tier down at pos(p)}  if p is LAST in its tier,
    else 0.0  (design §6.C.6). The last player in the bottom tier has no tier below → 0.0.
    Flags 'last before the cliff'; Score adds α·CliffBonus_p."""
```

Both are precomputed into `DraftContext` (ECR and tiers are static pre-draft); the hot path only
reads `context.cliff_bonus[p]`. Cliff bonus prevents reaching across a tier gap to a needier
position when VONA says the current position can wait.

**Acceptance:** GMM tiers are deterministic for a fixed `random_state`; the worst-ECR player in a
non-bottom tier carries a positive `CliffBonus`, all others in that tier (and the bottom tier's last
player) carry 0; tier count per position ≤ `max_tiers_per_pos`.

---

### 3.7 Orchestrator · `engine/recommend.py::recommend` [A] + `engine/context.py::build_draft_context` [N]

**Precompute artifact** — build once from providers, hold immutable in memory (design §7.D):

```python
@dataclass(frozen=True, slots=True)
class DraftContext:
    settings: LeagueSettings
    params: EngineParams
    projections: dict[str, PlayerProjection]      # Stage 0: μ/σ/floor/ceiling under exact CBS map
    mu: dict[str, float]                          # league points (μ_p) view
    position: dict[str, Position]
    baselines: dict[Position, float]              # static replacement baselines (dynamic recomputed per pick)
    flex_split: tuple[int, int]
    tiers: dict[str, int]
    cliff_bonus: dict[str, float]                 # Stage 4 precomputed
    adp_mean: dict[str, float]                    # FFC m_j
    adp_sd: dict[str, float]                      # FFC s_j
    ecr: dict[str, float]
    starting_slots: list[StartingSlot]            # expand_starting_slots(settings), the 9 slots
    players: dict[str, Player]

def build_draft_context(
    settings: LeagueSettings,
    providers: Sequence[FantasyDataProvider],
    params: EngineParams,
    season: int,
) -> DraftContext: ...
```

**Orchestrator** — stateless given `(state, context, params)`; this *is* `recompute()` (§3.8). The
stub's `recommend(state, settings, providers, *, season, n_sims)` signature is superseded (providers
are consumed at precompute); keep a thin API wrapper that builds the context on first ingest and
caches it, then calls:

```python
def recommend(
    state: DraftState,
    context: DraftContext,
    params: EngineParams,
    *,
    use_mc_vona: bool = False,          # analytic VONA is the v1 default; MC opt-in within budget
) -> Recommendation: ...
```

**Assembly (the canonical Score(p), design §6.C.7):**
1. **Mask** picked players from `context` using `state.picks` → `available`
   (O(1) set diff over `{pick.player_id for pick in state.picks if pick.player_id}`). Derive
   `my_roster = [pick.player_id for pick in state.picks if pick.team_id == state.my_team_id and
   pick.player_id]` and the current `round_no = (state.current_overall_pick − 1) //
   settings.team_count + 1` (team_count = 12).
2. **Dynamic baselines** = `dynamic_replacement_values(context, state)` (§3.2) — depletion-aware.
3. **Survival** `S_j(N*) = 1 − pick_probabilities(state, settings, context.adp_mean, context.adp_sd,
   my_next_overall=N*)[j]` over `available` (§3.4 returns P(taken); availability/survival is its
   complement); `N* = next_overall_pick(settings, state)`.
4. **Candidates** = top-`params.candidate_cap` (≈180) `available` by static MLV (bounded hot path).
5. Per candidate `p`:
   - `mlv = marginal_lineup_value(p, my_roster, context.mu, context.position, baselines, slots)`
   - `vona = mlv − expected_best_available(pos(p), …, S, baseline)` (or MC when `use_mc_vona`)
   - `risk = lambda_weight(round_no, slot_state(p), params) · σ_p`   *(signed; subtracted)*
   - `cliff = context.cliff_bonus[p]`
   - `mods = positional_modifiers(p, my_roster, context, params)` — bye-stack −, handcuff-synergy
     +, SOS ± ; each clamped to `±params.modifier_cap`, `Σ` re-clamped.
   - `score = mlv + params.kappa·max(0, vona) − risk + params.alpha·cliff + sum(mods.values())`
   - populate `ScoreComponents(mlv, vona, risk_penalty=risk, cliff_bonus=cliff, sigma=σ_p,
     floor, ceiling, replacement_baseline=baselines[pos(p)], modifiers=mods)`.
6. **Sort** desc by `score`; build `RecommendedPick`s (field mapping in §3.0); one-line `rationale`
   naming the dominant term; return `Recommendation(league_id=state.league_id,
   as_of_overall_pick=state.current_overall_pick, ranked=…)`.

The strategy this *produces* (never hard-codes) matches design §10.3/§6.D: anchor/Hero-RB (Zero-RB
counter-indicated in standard), accumulate WR breadth mid-rounds, defer QB/TE unless elite, DST R16
+ K R17 stream, RB-skewed high-ceiling bench.

**Acceptance:** `Score(p)` equals the sum of its `ScoreComponents` (`risk_penalty` subtracted,
`max(0,vona)` applied, `α`/`κ` weights); `ranked` is sorted desc and stable; every `RecommendedPick`
carries a populated `components`; the R1 recommendation is an elite RB/WR (not a QB) on the
calibration board.

---

### 3.8 The <2 s budget · precompute → `DraftContext` → stateless `recompute()`

Target **<2 s/pick**, **<200 ms** analytic, **<2 s** with MC VONA at N≈1–2k (design §7.D). Worst
case = pick 1 (~300-player pool, horizon ~22).

**Pre-draft precompute (once) → `DraftContext`**, materialized to the warehouse (Parquet nflverse
snapshots + DuckDB analytics store) and held in memory: projections μ/σ/floor/ceiling; league points
per player; replacement baselines + flex allocation; GMM tiers + cliff bonuses; FFC ADP mean/SD
joined by canonical id; crosswalk. Base-lineup `L*(B(R))` for the empty roster cached here.

**Per-pick hot path (`recompute()` == `recommend`), with rough costs:**

| # | Step | Mechanism | Rough cost |
|---|---|---|---|
| 1 | Drop picked player | O(1) set mask over `available` | µs |
| 2 | Dynamic baselines | re-rank remaining startable pool | < 1 ms |
| 3 | Vectorized survival `1−Φ((N−m)/s)` | NumPy over ~300 available | ~µs/player |
| 4 | Bounded candidates | top-K, `candidate_cap ≈ 180` | < 1 ms |
| 5 | MLV per candidate | `linear_sum_assignment` on 9×(owned+phantoms+cand), base cached, greedy-dominance shortcut | tens of ms |
| 6 | VONA / risk / cliff / modifiers | analytic (MC only if `use_mc_vona`) | few ms |
| 7 | Assemble + sort | build `ScoreComponents`, sort K | < 1 ms |

Single-thread suffices; MC (stretch) is embarrassingly parallel as NumPy batches. Libraries (design
§7.D): **NumPy** (survival/expected-max), **SciPy `linear_sum_assignment`** (MLV), **scikit-learn
`GaussianMixture`** (tiers), **Polars** (nflverse-native), **DuckDB** (analytics/backtest) +
**Parquet** (nflverse snapshots) + **SQLite** (ACID app state + append-only draft-event log),
**Optuna** (offline tuning only, never hot path). No cloud/GPU.

**Crash-safe replay (design §7 Step 7):** ingest appends each `DraftEvent` to the SQLite log
(`ingest/log.py` [N], monotonic `seq`; picks idempotent by `DraftPick.overall` — the extension
de-dups its raw feed by `pick_number` upstream) **before** `recompute()`; `DraftState` is a fold
over that log, so a restart replays to the exact state — the engine stays stateless and the hot path
is pure `(state, context, params) → Recommendation`.

**Acceptance (E7 perf gate in CI):** benchmark `recompute()` at the pick-1 worst case; assert **p95
< 2 s** end-to-end and **< 200 ms** analytic-only; a mid-draft restart replays the log to a
byte-identical `DraftState`.

---

### 3.9 Reserved for stretch — CP-SAT, MC, residual ML, RL (with the honesty caveat)

Explicitly **not** on the v1 hot path (design §4.D#6, §7.C.5, §7.F):

- **`optimize.py::optimize_roster` (OR-Tools CP-SAT) [E]** — keep the stub as the **end-state /
  season-simulator** ILP (binary pick vars, slot-eligibility incl. flex, roster caps, optional
  stacking/contingency). Reserved for the STRETCH rest-of-season simulator, **never** the per-pick
  path.
- **`simulate.py::simulate_drafts` (Monte-Carlo) [E]** — vectorized rollouts (a) as an
  `E[best available]` **refinement** to analytic VONA when `use_mc_vona=True` within budget, and (b)
  reused by the STRETCH **rest-of-season Monte-Carlo season simulator** → playoff/championship odds
  (the true objective that λ only proxies). `mc_rollouts ≈ 2000`.
- **XGBoost residual projections** and an **offline RL audit/benchmark** — stretch only;
  evidence-thin for snake drafts, compute-heavier, and unexplainable live.

**Compliance + honesty caveat (ADR 0003, `docs/legal-and-compliance.md`, design §4.C/§10.7):** this
engine is **personal-use, local-first, text-only, $0-besides-AI** — it reads only the user's own
authenticated CBS session, has **no voice**, and keeps paid providers off by default. Be honest:
there is **no** peer-reviewed optimal live snake-draft solver — exact stochastic DP/MDP is
intractable (Fry et al.) and online deep-RL is brittle/non-transferring. This engine's efficacy is
proven **only** by the project's own offline simulated-league tournament (our agent at every slot vs
**VBD-only** and **ADP-only** baselines, E6), not by any vendor or literature claim. Any
forward-year (2027) projection surfaced by the engine is labeled **ESTIMATED**.

---

### 3.10 Round-aware valuation & draft-state guarantees (v1.1 refinements)

This subsection makes the per-pick `Score(p)` robustly **round-aware** and pins down exactly how the
live draft state enters the value. Refinements **R1–R3 are v1** (cheap, closed-form, on the hot path);
the full remaining-draft Monte-Carlo generalization stays stretch (§3.9). They close two gaps the base
spec left implicit: (a) low-reliability positions (K/DST) could accrue value from *projection noise*,
and (b) one-step VONA is myopic across the snake turn.

**3.10.1 Design guarantees — how each draft input enters the value.** The engine is **Markovian over
`DraftState`**: the optimal pick depends only on the current state, never on regret about players you
passed. Concretely:

| Draft input | Where it enters | Effect |
|---|---|---|
| Players **you** rostered | `my_roster` → the MLV baseline lineup `B(R)` (§3.3) | every candidate is priced *relative to what you already have*; positional "need" is automatic (a 2nd QB ≈ `μ_QB2 − μ_QB1`) |
| Players **anyone** drafted (yours + others') | masked from `available` (§3.7 step 1) **and** deplete `dynamic_replacement_values` (§3.2) | a run *raises that position's baseline* and re-prices every survivor |
| Players **still available** | the candidate pool (top-`candidate_cap` by MLV) | only real options are scored |
| Players **you passed on** | re-priced from scratch each pick — no sunk-cost, no anchoring | if a passed player is still the best `Score(p)` now, he's recommended now; if taken, he's simply masked |
| **Cross-position** comparability | MLV is one unit — marginal starting-lineup points vs *each position's own* replacement | a QB/RB/WR/TE/K/DST are directly comparable; "take the scarce one now?" is answered by `κ·VONA`, and the **WR/RB flex** trade-off is resolved *inside* the Hungarian assignment (a scarcer RB can beat a higher-raw WR when VONA says the WR survives — §3.3–§3.4) |

**3.10.2 R1 — Position-reliability shrinkage + punt guard (fixes "a kicker is ranked/recommended too
early").** MLV trusts `μ_p`, but K/DST projections carry a wide *nominal* spread that is almost all
noise: the realized K1−K13 gap is ~1.5 pts/week (~24 pts/season) and no DST finishes #1 in
back-to-back years ([SI: when to draft K/DST](https://www.si.com/onsi/fantasy/nfl/fantasy-football-strategy-guide-when-draft-kicker-defense);
design §6.D). Without regressing low-reliability projections, MLV can hand a kicker a mid-round-sized
value. **Fix** (Stage 0, `projections.py`): shrink each projection toward its own replacement baseline
by a per-position reliability factor `r_pos ∈ (0,1]`:

```text
μ*_p = baseline(pos) + r_pos · ( μ_p − baseline(pos) )      # used everywhere downstream as μ
r_pos ≈ 1.0  for RB/WR/QB/TE  (predictable, rank R² ≈ 0.80)
r_pos ≈ 0.35–0.5  for K/DST   (rank R² ≈ 0.50 — mostly noise)
```

This collapses K/DST MLV toward ~0 so they can never out-rank a real starter from noise, while leaving
skill positions essentially unchanged. **Guard** (belt-and-suspenders, `recommend.py`): a hard
`punt_guard` never surfaces K or DST as the **#1** recommendation before its `stream_round` (K:17,
DST:16) *unless every other startable slot is already filled* — it only demotes, never forces. New
`EngineParams`: `reliability_shrinkage` (default `{K:0.4, DST:0.4}`, others `1.0`) and
`punt_guard` (`{enabled:true, stream_round:{K:17, DST:16}}`), both calibrated/validated in E2.

**3.10.3 R2 — Turn-aware (multi-pick) VONA horizon (v1); full-draft Monte-Carlo (stretch).** One-step
VONA (to your *very next* pick `N₁*`) is myopic: in a snake you pick twice around the turn and then wait
a long gap, so a scarce player can survive `N₁*` yet be gone before you can actually use a pick on the
position. **Fix** (§3.4): evaluate the opportunity cost at the horizon of your **H-th** upcoming pick,
not just the next one:

```text
VONA_p = MLV_p − E[ best MLV still available at pos(p) by your H-th upcoming pick N_H* ]
H = params.vona_horizon_picks   (1 = legacy one-step; 2 = turn-aware v1 default)
survival S_j(N_H*) = 1 − Φ((N_H* − m_j)/s_j),  N_H* from the ACTUAL entered snake order
```

Looking to `N_H*` (the *further* reachable pick) lowers the survival baseline for genuinely scarce
positions → higher VONA → the engine says "move now" on the QB/RB that truly won't last, and stays
patient on the deep WR that will. This is precisely the "value you can still get by round" the base
spec under-modeled. The exact multi-pick *allocation* across your remaining turns is what the
**remaining-draft Monte-Carlo VONA** solves (opponent draws from ADP+board over *all* your future
picks); it stays the stretch refinement (§3.9, `mc_enabled`) that this closed form approximates. New
`EngineParams`: `vona_horizon_picks: int = 2`. (Practitioner basis: round-by-round VONA and MC
pick-odds — [Stanford Stevens](https://stanfordstevens.com/value_of_vona.html),
[Jensen, *Simulating the Snake*](https://bcjense6.medium.com/simulating-the-snake-an-ai-assisted-fantasy-football-draft-strategy-4064c98940f7).)

**3.10.4 R3 — Board-conditioned survival (use what *this* room is doing, not just static ADP).**
Survival off static FFC ADP ignores how *your* room is actually drafting; a separate additive "run"
modifier is weaker than conditioning survival itself. **Fix** (§3.4): pull a position's effective ADP
earlier under observed run pressure, folding the old run detector *into* the survival model (no
double-count):

```text
run_pressure(pos) = (picks at pos since your last turn) − (ADP-expected picks at pos over that span)
m_j^eff = m_j − β · run_pressure(pos(j)) ,   β = params.board_survival_weight   (0 = pure static ADP)
S_j(N) = 1 − Φ((N − m_j^eff)/s_j)
```

A position going faster than ADP gets *lower* survival → higher VONA → an earlier nudge. Per-manager
tendency priors (from `manager_tendencies`, accrued across drafts — §2) remain the **stretch** upgrade.
New `EngineParams`: `board_survival_weight: float = 0.5`.

**3.10.5 Explainability.** `ScoreComponents` gains three **additive, optional** fields (default
`None`, so the Phase-0/Stage-3 scaffold is unaffected) so the overlay/assistant can *show* the
round-value reasoning: `reliability` (the `r_pos` applied), `vona_horizon` (picks looked ahead), and
`best_available_next` (the `E[best available]` the VONA subtracted — lets the overlay say "if you wait,
the best RB you'll likely get is ≈X"). Surfaced in §6 (overlay "value-by-round" line + dashboard
survival-by-round curve).

**Acceptance (also folded into the §3.11 DoD and §9 E2/E6):**
- R1: on the projection fixture, best-K and best-DST post-shrinkage MLV ≤ ~2 pts; the punt guard keeps
  K/DST out of the #1 slot before their stream round unless the roster is otherwise full.
- R2: `vona_horizon_picks=1` reproduces the one-step §3.4 worked example exactly; with `=2`, a
  turn-pick fixture raises urgency for a scarce position that would survive `N₁*` but not `N₂*`.
- R3: `board_survival_weight=0` reproduces static-ADP survival exactly; a simulated positional run with
  `β>0` measurably lowers that position's survival and raises its VONA.
- All three are tuned by Optuna in E2 across all 12 slots and must **not reduce** the E6 tournament
  margin vs the VBD-only / ADP-only baselines.

**3.10.6 R4 — Opportunity & situation model: value *this year's* points, not last year's box score.**
The most common projection error is extrapolating a prior-season stat line into a *changed* situation.
The engine must value a player's **opportunity to score in his current role** — new team, new
competition, new depth chart — translated into the exact CBS (non-PPR) scoring. This makes the design
§6.B.2 / §6.B.3 feature set an explicit Stage-0 layer. Per design §6.A, usage/situation **never gets
its own additive score term** — it moves `μ_p` (capped) and `σ_p`, and the value pipeline (§3.1–§3.7)
prices the adjusted projection.

*Two failure cases this fixes (your examples):*
- **Team change** (a long-time alpha WR joins a new team): his old target share / WOPR does **not**
  carry over — reproject his share against the **new** target competition, QB, and pass volume; widen σ
  for scheme/rapport uncertainty.
- **New backfield competition** (a breakout RB, then a high-capital rookie drafted over him): last
  year's carry share is stale — lower the incumbent's projected carry/snap share by the rookie's
  expected encroachment (draft capital is the prior), flag "committee" (ceiling down), widen σ.

*Stable backbone — project share, then translate to points.* Opportunity **share** is far more stable
year-over-year than fantasy points, so project it and convert to points rather than projecting points
directly (target/air-yard share and **WOPR** = `1.5·target_share + 0.7·air_yard_share` are among the
most stable fantasy inputs; opportunity is the backbone of expected fantasy points). From nflreadpy
(all $0, design §6.B.2): snap share, carry share (+ **goal-line / inside-5**), target share, air
yards / aDOT / WOPR, route %, team pace / PROE, and the `load_ff_opportunity` expected-points (xEP)
prior. **Non-PPR weighting is the point:** weight carries, goal-line carries, air yards, deep/red-zone
targets and TD equity **up**, and raw reception *count* **down** (a catch is 0 pts) — "opportunity to
score" measured in *this* league's currency.

*Situation-change layer — what to adjust, and by how much* (change signals from nflreadpy rosters +
depth charts + draft picks + recent snap/route trends; each applies a **capped** μ nudge via the
existing `caps.mu_refinement_pct` (±10–15%) plus σ-widening + a surfaced flag):

| Signal | μ effect (capped) | σ / flag |
|---|---|---|
| **Team change** (roster diff) | reproject target/carry share in the new offense vs new competition | σ↑; "new team — role unconfirmed" |
| **Vacated volume** (departed players' targets/carries) | redistribute to remaining + incoming by role / depth rank / draft capital — a **regressed prior, not 1:1** (vacated volume is descriptive, not predictive — [FTN](https://ftnfantasy.com/nfl/vacated-opportunities-in-fantasy-football-before-2026-free-agency)) | σ↑ until confirmed |
| **New competition / rookie** (draft capital, depth chart) | lower incumbent carry/snap/target share by expected encroachment; split committees ([FantasyPros rookie RBs](https://www.fantasypros.com/2026/06/12-impact-rookie-running-backs-2026-fantasy-football/)) | σ↑; "committee / rookie threat" |
| **QB / pass environment** (team pass eff, PROE, QB proj) | cap a pass-catcher's ceiling by QB quality + team pass volume | σ per environment |
| **Age / role change / injury** (design §6.B.3) | RB age-cliff (~28) μ haircut; Q/D/O availability haircut | σ↑; injury flag (CBS on-page) |

*Honesty at $0.* The **primary anchor is current-season vendor projections** — CBS on-page + ECR
(`load_ff_rankings`) already re-price team changes, rookies and depth charts (experts have reprojected
the moved WR and the new backfield). The situation layer therefore (a) makes the reasoning
**transparent** (the overlay shows *why* a projection moved), (b) **catches source disagreement/lag**
and nudges μ within the cap, and (c) **sets σ**, so the risk term (§3.5) down-weights uncertain,
newly-changed situations for your must-start core and lets them ride as ceiling bench swings. A full ML
opportunity model (Predicted-Targets / PWOPR, XGBoost on the change features) is **stretch** (§3.9);
the v1 layer is stable shares + a rules-based, capped adjustment.

*Data + interfaces.* Adds opportunity columns to the `projections` warehouse table (§2) —
`snap_share, carry_share, gl_carries, target_share, air_yards_share, wopr, rz_touches, route_pct,
team_proe, xep` — and a `situation` blob (`team_change, vacated_share, competition_delta,
draft_capital_rank, qb_env, age, injury_status`); `NflreadpyProvider` gains the `EXPECTED_POINTS`
capability (§4). `build_projections` (§3.1) consumes these to produce `μ*` (post-reliability-shrinkage,
§3.10.2) and `σ`. New `EngineParams`: `situation_adjust: {enabled:true, mu_cap_pct:0.15,
vacated_regression:0.5, rookie_capital_weight:0.6, sigma_widen_on_change:1.25}`.

*Acceptance (E3, §9).* (a) On 2021–2024 holdouts, an opportunity-share→points projection beats naive
prior-year points extrapolation on MAE/Spearman **for players who changed team or role**; (b) the
team-change and rookie-competition fixtures fire the correct flags and move μ within the cap with σ up;
(c) receptions carry **0** μ weight (non-PPR check); (d) no situation μ-nudge exceeds `mu_cap_pct`.

**3.10.7 Weighting & calibration — how all the factors combine (and how their weights are set).**
The single most important rule (design §6.A): factors are weighted in **two different places, never on
one flat scale.**

- **Layer A — projection inputs (μ, σ).** Opportunity / usage / situation (snap-carry-target share,
  WOPR, vacated volume, team change, rookie competition, QB env, age, injury — §3.10.6) and the
  multi-source blend **do not get additive score weights**; they set `μ_p` and `σ_p`. The μ blend is a
  **simple average** across sources (empirically ≥ any hand-weighting — wisdom of crowds); opportunity
  features are weighted by **year-over-year stability** (shares / WOPR high, raw counts low — non-PPR
  down-weights receptions); every situation nudge is **capped to ±`caps.mu_refinement_pct` (10–15%)**
  and widens σ; low-reliability positions are shrunk (K/DST `r≈0.4`, §3.10.2).
- **Layer B — objective terms (the Greek weights), combined in points-space:**

```text
Score(p) = MLV_p             # value core — implicit weight 1.0 (the currency everything else is measured against)
         + κ·max(0,VONA_p)   # κ = 0.5–0.8 (default 0.65)                     scarcity / urgency
         − λ(phase,slot)·σ̂_p # λ schedule +0.2…+0.4 → −0.3…−0.5, slot ±0.40   risk tilt (floor early, ceiling late)
         + α·CliffBonus_p    # α = 0.3–0.5 (default 0.40)                      tier-cliff urgency
         + Σ capped modifiers # each ≤ ~3–5 pts (bye −, handcuff +, SOS ±)     bounded tie-breakers
```

**Deliberate magnitude hierarchy** — so the transparent value core always leads and no heuristic can
dominate: `MLV` is tens of points → `κ·VONA` ~5–10 in scarce spots → `λ·σ̂` and `α·Cliff` a few points
→ modifiers hard-capped ≤3–5 → Layer-A situation moves bounded to ±10–15% of μ. A soft heuristic can
break a tie or nudge a ranking; it can never flip the value order.

**The weights are calibrated, not hand-picked.** The defaults are literature / first-principles
**priors**; the correct values for this league come from the calibration pipeline (§9) and are
versioned in `config/engine.json`:
- **E1** measures `flex_split` from live ADP (top-60) — it sets the RB/WR baselines (most sensitive knob).
- **E3** validates the μ blend + situation caps + `reliability_shrinkage` vs 2021–2024 realized points
  (MAE / Spearman; σ by interval coverage).
- **E2** runs **Optuna** over `(κ, λ-table, α, modifier caps, board β, vona_horizon,
  reliability_shrinkage, situation_adjust)` to maximize mean starting-lineup points / playoff odds
  **across all 12 draft slots**, evaluated against several opponent models (ADP, VBD-only, need-based)
  so the weights don't overfit one style.
- **E6** (efficacy gate) confirms the tuned set beats the ADP-only and VBD-only baselines.

Honest bound: there is **no proven-optimal weight set** for a live snake draft — these are tuned to
*our* offline tournament, re-tunable via `config/engine.json` without code changes, and every weight is
surfaced in `ScoreComponents` so a recommendation stays auditable.

**3.10.8 Research-backed weighting — recommended priors and the combination method.** "Optimal" weights
are set in **two stages**: each *sub-component* has an evidence-backed **form/prior**, and the
*combined* score weights are found by **Bayesian optimization** over backtests — there is no published
closed-form optimum for the full live-draft objective (the honest bound of §3.9), so the magnitudes are
league-calibrated, not asserted.

| Factor | Recommended form / starting prior | Evidence basis | Tuned by |
|---|---|---|---|
| **VBD baseline** (replacement) | **0.5·VOLS + 0.5·man-games (BEER+)** — balances elite starters vs bench de-risking (VOLS alone rewards elite QBs; VORP alone over-favors the bench) | [Subvertadown VBD baselines](https://subvertadown.com/article/guide-to-understanding-the-different-baselines-in-value-based-drafting-vbd-vols-vs-vorp-vs-man-games-and-beer-); [FantasyPros VBD](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/) | `replacement_blend` (E2) |
| **Projection blend** (μ) | **simple average** of sources — consensus ≥ weighted (wisdom of crowds); optionally weight WR by prior-season MAE (FFA-Weighted led WR at 4.94 MAE) | [FFA — which projections are most accurate](https://fantasyfootballanalytics.net/2024/12/which-fantasy-football-projections-are-most-accurate.html) | `projection_blend` (E3) |
| **Risk λ** | **utility = μ − λ·σ**; λ = "points of mean traded per 1σ"; phase/slot schedule +0.2…+0.4 → −0.3…−0.5 (mean-variance nets ~3–5 starting pts/wk) | [Jensen — mean-variance snake sim](https://bcjense6.medium.com/simulating-the-snake-an-ai-assisted-fantasy-football-draft-strategy-4064c98940f7); [FFA risk levels](https://fantasyfootballanalytics.net/2013/04/calculate-fantasy-players-risk-levels.html) | `lambda_schedule` (E2) |
| **κ (VONA)** | **0.5–0.8** — scarcity/opportunity-cost urgency; **no literature optimum** | practitioner (Draft Wizard / VONA) | Optuna (E2) |
| **α (tier cliff)** | **0.3–0.5** — guard-rail weight; **no literature optimum** | Boris-Chen tiers | Optuna (E2) |
| **Opportunity → μ** | **WOPR = 1.5·target_share + 0.7·air_yard_share**; weight shares by year-over-year **stability** (shares/WOPR high, raw counts low); non-PPR up-weights carries/air-yards/TDs | established WOPR; PFF/4for4 stability (§3.10.6) | `situation_adjust` caps (E3) |
| **Modifiers** (bye/handcuff/SOS) | ⛔ **UNIMPLEMENTED** (Tier 6) — `_positional_modifiers` returns `{}`; no clamping code exists and the caps are removed from `config/engine.json`. **E2 structurally cannot price them**: its objective samples ONE season total per player, independently, so there is no week axis (bye/SOS) and no cross-player correlation (handcuff). Needs a weekly, correlated objective first. | design §6.C.7 | — |

**Combining them (the "all together" answer).** Treat the full weight vector — `replacement_blend, κ,
λ-table, α, caps, β, vona_horizon, reliability_shrinkage, situation_adjust` — as hyperparameters and
optimize **jointly**; do **not** hand-tune one at a time, because they interact (κ trades off against
the baseline depth; λ against σ). The method (§9 E2, `scripts/tune_engine_params.py`):
1. **Bayesian optimization (Optuna / TPE)** — the right tool in this ~10–15-dimensional space: it
   "learns from past results to decide where to search next," far more sample-efficient than grid or
   random search in high dimensions ([grid vs random vs Bayesian](https://medium.com/@pacosun/the-tuners-toolbox-grid-search-random-search-and-bayesian-optimization-unpacked-648abd7a8ff6)).
2. **Objective** = mean starting-lineup points (stretch: simulated-season wins, à la the Becker–Sun
   draft+lineup MIP — [JQAS 2016](https://ideas.repec.org/a/bpj/jqsprt/v12y2016i1p17-30n1.html))
   **averaged across all 12 draft slots**, evaluated against **multiple opponent models** (ADP-noise,
   VBD-only, need-based) with **held-out seasons**, so the weights don't overfit one opponent style.
3. **Coarse discrete knobs** (e.g., `vona_horizon_picks ∈ {1,2,3}`) can nest a small **grid search**
   inside the study.
4. **Gate:** the tuned vector must beat the ADP-only and VBD-only baselines in the offline tournament
   (E6) — the only efficacy proof, since no peer-reviewed optimum exists.

So the *forms* above are fixed from evidence; the *magnitudes* are league-calibrated, versioned in
`config/engine.json`, and re-tunable without code changes.

---

### 3.11 Section 3 — Definition of done

- [ ] `domain/models.py`: `ScoreComponents` + `RecommendedPick.components`; `ScoringBracket` /
  `ScoringTier` / `ScoringBonus` + `LeagueSettings.scoring_tiers` / `scoring_bonuses`;
  `Capability.EXPECTED_POINTS` — all mirrored in Zod (`recommendation.ts`, `league.ts`) and passing
  schema-parity CI (E5). Scaffold #4 (`/recs/ws`) is tracked in the API/transport section, not here.
- [ ] `EngineParams` + `load_engine_params` load `config/engine.json` via a new
  `Settings.jaaffl_engine_params_path` (design §10.3 defaults; graceful default when absent).
- [ ] `projections.py::build_projections` returns `dict[str, PlayerProjection]` (μ/σ/floor/ceiling,
  per-source breakdown) with **Rec = 0** enforced; validated against E3.
- [ ] `league/scoring.py::league_points` evaluates linear + DST points-**and**-yards tiers + K
  threshold bonus; CBS-page values **[VERIFY]** recorded.
- [ ] `league/replacement.py::replacement_values` yields RB≈22–24, WR≈40–42, QB/TE/K/DST≈13;
  `dynamic_replacement_values` depletion-aware; `flex_split` sourced from `EngineParams` and slated
  for live measurement (E1, top-60).
- [ ] `optimize.py::marginal_lineup_value` via `scipy.optimize.linear_sum_assignment` (flex mask,
  replacement-filled) with the greedy-dominance fast path; empty-roster VOR reduction + auto-need
  properties tested; `optimize_roster` CP-SAT left as the stretch stub.
- [ ] `opponents.py::pick_probabilities` closed-form vectorized survival off the **actual** entered
  draft order (`next_overall_pick`, never team-count-inferred); `expected_best_available` + `VONA_p`;
  the §6.C.4 worked example is a golden test.
- [ ] Risk `lambda_weight` implements the full phase table + slot override; `tiers.py` GMM tiers +
  `cliff_bonuses` deterministic and precomputed.
- [ ] `engine/context.py::build_draft_context` precomputes `DraftContext`;
  `recommend.py::recommend` assembles the canonical `Score(p)`, populates `ScoreComponents`, sorts,
  and defaults to analytic VONA (MC opt-in).
- [ ] E7 perf gate green: p95 `recompute()` < 2 s, analytic < 200 ms; crash-safe log-replay
  verified.
- [ ] **R1** (§3.10.2): `reliability_shrinkage` applied in Stage 0 + `punt_guard` in `recommend`;
  best-K/best-DST post-shrinkage MLV ≤ ~2 pts and K/DST are never the #1 rec before their stream round
  unless the roster is otherwise full — tested.
- [ ] **R2** (§3.10.3): turn-aware VONA (`vona_horizon_picks=2`) with the `=1` one-step reduction
  test; **R3** (§3.10.4): board-conditioned survival (`board_survival_weight β`) folding the run
  detector into survival, with the `β=0` static-ADP reduction test.
- [ ] `ScoreComponents` additive fields `reliability` / `vona_horizon` / `best_available_next`
  populated and mirrored in Zod (optional, default null; schema-parity green).
- [ ] **R4** (§3.10.6): opportunity/situation layer feeds `μ*`/σ from nflreadpy shares + change
  signals (team-change, vacated-volume regressed, rookie/committee, QB env, age/injury), non-PPR-weighted
  (receptions = 0), every nudge capped by `caps.mu_refinement_pct`; team-change + rookie fixtures fire
  the right flags (E3). `situation_adjust` in `EngineParams`.
- [ ] **Weighting** (§3.10.7–3.10.8): the two-layer split (μ/σ vs score-terms) holds; the sub-component
  forms match the research-backed priors (BEER+ baseline, simple-average blend, μ−λ·σ risk, WOPR
  1.5/0.7); the full weight vector is **jointly** Optuna-tuned (not hand-tuned); every weight/cap is read
  from `config/engine.json` (no hard-coded magic numbers).
- [ ] Stretch items (CP-SAT season sim, MC VONA, XGBoost, RL) remain stubs; the "personal-use /
  text-only / no proven solver / efficacy via own E6 tournament / 2027 = ESTIMATED" caveat is stated
  in the module docstrings.

---

## 4. Data providers ($0 tier behind the interface)

The data layer is a set of **adapters behind one Python protocol** (`jaaffl.providers.base.FantasyDataProvider`). The engine never imports a concrete adapter, `httpx`, `nflreadpy`, or CBS DOM shapes — it depends only on the protocol, the `Capability` enum, and the registry (see §4.7). This section restates that protocol with the deltas design §7.C.4 requires, then specifies every adapter: constructor, capabilities, method signatures, return types (Polars where nflverse-native), cache policy, and the crosswalk/warehouse dependencies. Builds on design §5.C (source tiering + the free-injury gap) and §7.C.4 (module spec). All provider returns are keyed by **canonical JAAFFL `player_id`** (resolved through `jaaffl.data.Crosswalk`) *before* they cross into the engine.

### 4.1 The provider protocol (capabilities + ABC)

File: `backend/src/jaaffl/providers/base.py` — **[E] extend in place**. Three changes vs. the current scaffold:

1. **Add `EXPECTED_POINTS`** to `Capability` (nflverse `load_ff_opportunity`, design §7.C.3/§7.C.4).
2. **Retype nflverse-native returns pandas → Polars.** `historical_stats` and the new `expected_points` return `pl.DataFrame` (design §5.D: nflreadpy is Polars-native; DuckDB scans Polars/Arrow directly). The `TYPE_CHECKING` import flips `import pandas as pd` → `import polars as pl`. **This is scaffold change #2 (design §7/§10.5) and it lives HERE** (also §4.3, §4.8).
3. **Widen `adp()`** from `dict[str, float]` to `dict[str, AdpRecord]` — the survival math `S_j(N)=1−Φ((N−m_j)/s_j)` (design §10.3, §7.C.5) needs the **stdev**, not just the mean, so ADP mean-only is insufficient at the protocol level.

```python
from __future__ import annotations
import abc
from enum import StrEnum
from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict          # NEW import

if TYPE_CHECKING:
    import polars as pl                              # was: import pandas as pd
    from jaaffl.domain import Player


class Capability(StrEnum):
    HISTORICAL_STATS = "historical_stats"
    PROJECTIONS      = "projections"
    ADP              = "adp"
    RANKINGS         = "rankings"
    INJURIES         = "injuries"
    NEWS             = "news"
    EXPECTED_POINTS  = "expected_points"             # NEW (design §7.C.3/§7.C.4)


class AdpRecord(BaseModel):
    """One provider's ADP row for a canonical player. Frozen; stdev drives survival."""
    model_config = ConfigDict(frozen=True)
    adp: float                       # mean draft position m_j
    stdev: float | None = None       # s_j  (None → engine falls back to ECR spread)
    high: float | None = None        # earliest observed pick
    low: float | None = None         # latest observed pick
    times_drafted: int | None = None
    bye: int | None = None
```

`ProviderError` / `CapabilityNotSupported` and the `name` / `capabilities` / `enabled` / `supports()` / `_require()` surface are unchanged. The capability methods every concrete provider overrides (declared ones only; the rest raise via `_require`):

```python
def players(self, season: int) -> list[Player]: ...                                   # HISTORICAL_STATS
def historical_stats(self, season: int) -> pl.DataFrame: ...                          # pandas → POLARS
def expected_points(self, season: int) -> pl.DataFrame: ...                           # NEW, EXPECTED_POINTS
def projections(self, season: int, week: int | None = None
                ) -> dict[str, dict[str, float]]: ...                                 # canonical_id -> stat_line
def adp(self, season: int) -> dict[str, AdpRecord]: ...                               # WIDENED float -> AdpRecord
def rankings(self, season: int, week: int | None = None) -> dict[str, float]: ...     # canonical_id -> ECR
def injuries(self, season: int, week: int | None = None) -> dict[str, str]: ...       # canonical_id -> status
```

> `NEWS` has **no ABC method in v1** — only the (off-by-default) FantasyPros stub declares it; a `news()` method is added if/when that provider is enabled. All other capabilities have the method above.

> **Contract-sync note (keep Pydantic ⇄ Zod in sync where they actually mirror).** `Capability`, `AdpRecord`, `EXPECTED_POINTS`, and these signatures are **backend-internal** — they do **not** cross the wire and have **no Zod mirror**. Of the four scaffold changes (design §7/§10.5): **#1** (`scoring_tiers`+`scoring_bonuses` on `LeagueSettings`) and **#3** (`ScoreComponents` on `RecommendedPick`) are the shared TS/Pydantic contracts handled in §7.C.1/§7.C.3; **#4** (`WS /recs/ws`) is §7.C.6; **#2** (`nfl_data_py`→`nflreadpy`, pandas→Polars) is *this* section (§4.3/§4.8). Widening `adp()` is a breaking backend signature change: the `FantasyProsProvider` stub's `adp()` must adopt `dict[str, AdpRecord]` too (§4.6).

**Capability coverage matrix** (registry preference order left→right within a capability; `*` = config-gated, off by default):

| Capability | `nflverse` (Nflreadpy) | `ffc` | `cbs_onpage` | `fantasypros`* | `sportsdataio`* | `sportradar`* |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| HISTORICAL_STATS | ✓ (1st) | — | — | — | — | — |
| EXPECTED_POINTS | ✓ (1st) | — | — | — | — | — |
| RANKINGS (ECR) | ✓ (1st) | — | ✓ (2nd, CBS rank) | ✓ | — | — |
| ADP | — | ✓ (1st) | — | ✓ | — | — |
| PROJECTIONS | — | — | ✓ (1st) | ✓ | ✓ | ✓ |
| INJURIES | — | — | ✓ (1st) | ✓ | ✓ | ✓ |
| NEWS | — | — | — | ✓ | — | — |

`league_settings()` (authoritative CBS scoring/roster) is a **non-capability** method on `CbsOnPageProvider` (§4.5), consumed by `jaaffl.ingest`/`jaaffl.league`, not via capability dispatch.

### 4.2 The registry

File: `backend/src/jaaffl/providers/registry.py` — **[E]**. Wire the three free adapters (always on) plus the gated paid stubs. FFC and CBS need a `Crosswalk` (source-id / name+team+pos → canonical id) and CBS needs a `Warehouse` reader, so `build_registry` gains injected dependencies with lazy defaults.

```python
from jaaffl.config import Settings, get_settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.providers.base import Capability, FantasyDataProvider
from jaaffl.providers.nflverse import NflreadpyProvider
from jaaffl.providers.ffc import FantasyFootballCalculatorProvider
from jaaffl.providers.cbs_onpage import CbsOnPageProvider
from jaaffl.providers.fantasypros import FantasyProsProvider
from jaaffl.providers.sportsdataio import SportsDataIOProvider   # NEW stub
from jaaffl.providers.sportradar import SportradarProvider       # NEW stub


def build_registry(
    settings: Settings | None = None,
    *,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
) -> list[FantasyDataProvider]:
    settings = settings or get_settings()
    warehouse = warehouse or Warehouse()
    crosswalk = crosswalk or Crosswalk()

    providers: list[FantasyDataProvider] = [
        NflreadpyProvider(crosswalk=crosswalk),                    # free $0 base
        FantasyFootballCalculatorProvider(settings, crosswalk),    # free $0 ADP
        CbsOnPageProvider(warehouse, crosswalk),                   # free $0 CBS snapshot
    ]
    for gated in (
        FantasyProsProvider(settings),
        SportsDataIOProvider(settings),
        SportradarProvider(settings),
    ):
        if gated.enabled:
            providers.append(gated)
    return providers


def providers_supporting(
    capability: Capability,
    settings: Settings | None = None,
    *,
    warehouse: Warehouse | None = None,
    crosswalk: Crosswalk | None = None,
) -> list[FantasyDataProvider]:
    """Active providers supporting `capability`, in registry (preference) order."""
    reg = build_registry(settings, warehouse=warehouse, crosswalk=crosswalk)
    return [p for p in reg if p.supports(capability)]
```

Registry order **is** preference order: the precompute layer takes the first supporter and (for RANKINGS/ADP) uses later supporters as deep-round fallback (§4.4). Gated providers **append after** the three free ones, so enabling one adds a *lower-preference* supplier (except where precompute explicitly prefers/merges it for a capability — see the injury note in §4.6). The default registry — nflverse + ffc + cbs_onpage, no key present — **is** the $0 tier.

### 4.3 `NflreadpyProvider` — `providers/nflverse.py` (renamed/retyped) **[A]**

Rename `NflverseProvider` → `NflreadpyProvider` (stable `name` key stays `"nflverse"` so existing config/log references hold). Swap `nfl_data_py` → `nflreadpy` (design §5.C: `nfl_data_py` archived read-only 2025-09-25). Polars-native.

| Aspect | Value |
|---|---|
| `name` | `"nflverse"` |
| `capabilities` | `{HISTORICAL_STATS, RANKINGS, EXPECTED_POINTS}` |
| `enabled` | `True` (always; free) |
| Constructor | `NflreadpyProvider(crosswalk: Crosswalk \| None = None)` |
| Dependency | optional `data` extra (`nflreadpy`, `polars`) — lazy import |
| Cache | nflreadpy built-in cache (memory/disk); pulled frames persisted to Parquet under `JAAFFL_DATA_DIR/nflverse/*.parquet` via `Warehouse` (design §7 Step 7: Parquet = nflverse snapshots). Refresh **once per draft-prep** (preseason updates weekly), never per-pick |

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from jaaffl.providers.base import (AdpRecord, Capability, FantasyDataProvider, ProviderError)
if TYPE_CHECKING:
    import polars as pl
    from jaaffl.data import Crosswalk


def _import_nflreadpy():
    try:
        import nflreadpy  # noqa: PLC0415
    except ImportError as exc:                      # pragma: no cover
        raise ProviderError(
            "nflverse provider needs the 'data' extra: pip install -e '.[data]'"
        ) from exc
    return nflreadpy


class NflreadpyProvider(FantasyDataProvider):
    def __init__(self, crosswalk: "Crosswalk | None" = None) -> None:
        self._crosswalk = crosswalk

    @property
    def name(self) -> str: return "nflverse"

    @property
    def capabilities(self):
        return frozenset({Capability.HISTORICAL_STATS,
                          Capability.RANKINGS, Capability.EXPECTED_POINTS})

    def historical_stats(self, season: int) -> "pl.DataFrame":
        return _import_nflreadpy().load_player_stats(seasons=[season])          # design §7.C.4

    def expected_points(self, season: int) -> "pl.DataFrame":
        return _import_nflreadpy().load_ff_opportunity(seasons=[season])        # ffopportunity xEP

    def rankings(self, season: int, week: int | None = None) -> dict[str, float]:
        ecr = _import_nflreadpy().load_ff_rankings()   # FantasyPros ECR redistributed (CC-BY 4.0)
        # filter to `season`/`week`, resolve id -> canonical via self._crosswalk, return {id: ecr}
        ...
```

**Method → source map:** `historical_stats` → `load_player_stats`; `expected_points` → `load_ff_opportunity`; `rankings` (ECR) → `load_ff_rankings` (design §7.C.4). **ID crosswalk seed:** build/refresh canonical ids from the nflverse crosswalk — `load_ff_playerids()` / `load_players()`; **[VERIFY minor]** confirm the exact Python name in installed `nflreadpy` and pass results to `Crosswalk.upsert(...)` (fuzzy name+team+pos fallback per design §7.C.4 covers CBS/FFC ids). **Do NOT** offer `INJURIES` here: nflverse's injury source lapsed after the 2024 season / 2025+ coverage is UNVERIFIED (design §5.C) — injuries come from CBS on-page (§4.5).

### 4.4 `FantasyFootballCalculatorProvider` — `providers/ffc.py` (NEW) **[N]**

Free ADP for the immutable **Standard (non-PPR)**, **12-team** league — with **stdev**, the survival input the analytic VONA needs. Uses `httpx` (already a base dependency; **no new extra**).

| Aspect | Value |
|---|---|
| `name` | `"ffc"` |
| `capabilities` | `{ADP}` |
| `enabled` | `True` (free; no key). Optional kill-switch `jaaffl_enable_ffc` (default `True`) |
| Constructor | `FantasyFootballCalculatorProvider(settings, crosswalk, *, client: httpx.Client \| None = None)` |
| Endpoint | `GET https://fantasyfootballcalculator.com/api/v1/adp/{scoring}?teams={teams}&year={season}` → `.../adp/standard?teams=12&year={season}` |
| Format/teams | `{scoring}` is the **path segment** = `standard` (immutable non-PPR); `teams=12` is a **query param** (immutable). Both default from `jaaffl_ffc_scoring`/`jaaffl_ffc_teams` (§4.8), which **mirror `config/league.json`** (`Scoring Format: Standard`, `Teams: 12`) and must never diverge from it — never hardcoded twice |
| Cache | **DAILY** (24 h TTL): file `JAAFFL_DATA_DIR/cache/ffc/adp_standard_12_{season}.json` + in-memory memo. Never poll faster than daily (FFC etiquette, design §5.C) |
| Return | `dict[str, AdpRecord]` keyed canonical id |

```python
def adp(self, season: int | None = None) -> dict[str, AdpRecord]:
    season = season or self._settings.jaaffl_season or _active_draft_season()   # today: 2026
    payload = self._get_cached(season)             # 24h file+memo; httpx GET on miss
    if payload.get("status") != "Success" or not payload.get("players"):
        raise ProviderError(f"FFC returned no ADP for season={season} "
                            "(query the CURRENT draft season only)")   # e.g. year=2025 -> 'No ADP data'
    out: dict[str, AdpRecord] = {}
    for row in payload["players"]:                 # row: name, position, team, adp, stdev,
        cid = self._crosswalk.resolve_name(        #      high, low, times_drafted, bye  [VERIFY fields]
            name=row["name"], team=row.get("team"), pos=row["position"])
        if cid is None:
            continue                               # unresolved -> logged, skipped (engine tolerates)
        out[cid] = AdpRecord(adp=row["adp"], stdev=row.get("stdev"),
                            high=row.get("high"), low=row.get("low"),
                            times_drafted=row.get("times_drafted"), bye=row.get("bye"))
    return out
```

**Crosswalk resolution surface (add in `data/crosswalk.py` **[E]**, design §7.C.4).** FFC rows carry no stable source id, so FFC resolves each row by name — a method the current scaffold lacks and must gain alongside the existing `resolve`:

```python
def resolve(self, source: str, source_id: str) -> str | None: ...                  # existing: deterministic source-id join
def resolve_name(self, name: str, team: str | None, pos: str) -> str | None: ...   # NEW: fuzzy name+team+pos fallback
```

FFC → `resolve_name(...)`; CBS → `resolve("cbs", cbs_id)` with `resolve_name` as the fuzzy fallback (§4.5). Resolutions persist in SQLite (design §7.C.4).

**Current-season-only rule.** FFC serves ADP for the **active** draft season only; an off/past year (`year=2025`) returns `status != "Success"` / empty `players` with a "No ADP data" message. Default `season` to `settings.jaaffl_season` (else the active draft season from `DraftContext`, today 2026); on an empty/failed payload raise `ProviderError` and **never cache the empty result** as authoritative.

**15-round thinning → ECR fallback (design §7.C.4).** FFC mocks are 15-round (`meta.rounds == 15`), so ADP thins past ~pick 180. The precompute join must **left-join FFC ADP onto the candidate board and fill deep-round gaps from `rankings` (nflverse ECR)** so survival curves exist for every candidate through **round 17** — FFC where present, ECR-derived `AdpRecord(stdev≈ECR spread)` past the thinning cliff. This is a precompute-layer join (§4.7), keeping each provider single-responsibility.

### 4.5 `CbsOnPageProvider` — `providers/cbs_onpage.py` (NEW) **[N]**

The only $0 source of **your league's actual settings** + CBS first-party projections/injuries/rankings. **Reads the CBS snapshot from the warehouse (fed by the extension), NOT a network fetch** (design §5.D, §7.C.4). Pure reader; the extension→ingest path writes.

| Aspect | Value |
|---|---|
| `name` | `"cbs_onpage"` |
| `capabilities` | `{PROJECTIONS, INJURIES, RANKINGS}` |
| Extra | authoritative `league_settings()` (non-capability method) |
| `enabled` | `True` (always; methods degrade gracefully to empty until a snapshot exists) |
| Constructor | `CbsOnPageProvider(warehouse: Warehouse, crosswalk: Crosswalk, league_id: str \| None = None)` — stores `self._league_id`; `None` → warehouse resolves the **sole active league** (single-user, ADR 0002) |
| Source | `warehouse.latest_cbs_snapshot(self._league_id)` — latest extension-fed snapshot |
| Cache | none of its own; freshness = last extension write; staleness surfaced via `snapshot.captured_at` |

```python
def projections(self, season, week=None) -> dict[str, dict[str, float]]:
    snap = self._warehouse.latest_cbs_snapshot(self._league_id)
    if snap is None: return {}                     # no snapshot yet -> empty, logged
    return {self._crosswalk.resolve("cbs", cbs_id): line
            for cbs_id, line in snap.projections.items()}

def injuries(self, season, week=None) -> dict[str, str]: ...   # snap.injuries, cbs->canonical
def rankings(self, season, week=None) -> dict[str, float]: ... # snap.rankings/adp, cbs->canonical

def league_settings(self, league_id: str | None = None) -> "LeagueSettings | None":
    """AUTHORITATIVE CBS scoring (both DST pts- AND yards-allowed tiers + K 50+ bonus) and
    roster (design §5.C). Consumed by jaaffl.league/jaaffl.ingest, not capability dispatch.
    config/league.json values are the validation default / offline fallback only — parse
    the live table (scaffold change #1: scoring_tiers + scoring_bonuses)."""
    snap = self._warehouse.latest_cbs_snapshot(league_id or self._league_id)
    return snap.league_settings if snap else None
```

**Warehouse read surface (add in `data/warehouse.py` **[E]**):**

```python
def snapshot_cbs_page(self, league_id: str, snapshot: CbsPageSnapshot) -> None: ...       # ingest writes
def latest_cbs_snapshot(self, league_id: str | None = None) -> "CbsPageSnapshot | None": ...  # provider reads; None -> sole active league
```

`CbsPageSnapshot` fields the provider needs (exact schema defined with the ingest section; **[VERIFY]** tied to the UNVERIFIED extension capture, design §5.D / §7.C.2): `projections: dict[cbs_id, stat_line]`, `injuries: dict[cbs_id, status]`, `rankings: dict[cbs_id, float]`, `league_settings: LeagueSettings`, `captured_at: datetime`. CBS ids resolve to canonical via `Crosswalk.resolve("cbs", cbs_id)` (fuzzy `resolve_name` name+team+pos fallback, §4.4).

### 4.6 Paid / commercial providers (disabled stubs)

All OFF by default, gated by existing `config.py` flags. Capability methods raise `NotImplementedError("stage 4: …")` until subscribed; `enabled` is the only wired behavior.

| Provider | File | Flag (default) | Key | Capabilities | Status |
|---|---|---|---|---|---|
| `FantasyProsProvider` | `providers/fantasypros.py` (exists) | `jaaffl_enable_fantasypros` (`false`) | `fantasypros_api_key` | `{PROJECTIONS, ADP, RANKINGS, INJURIES, NEWS}` | stub; update `adp()` → `dict[str, AdpRecord]` |
| `SportsDataIOProvider` | `providers/sportsdataio.py` **[N]** | `jaaffl_enable_sportsdataio` (`false`) | `sportsdataio_api_key` | `{PROJECTIONS, INJURIES}` (declare on impl) | disabled stub |
| `SportradarProvider` | `providers/sportradar.py` **[N]** | `jaaffl_enable_sportradar` (`false`) | `sportradar_api_key` | `{PROJECTIONS, INJURIES}` (declare on impl) | disabled stub |

Stub pattern (mirror `FantasyProsProvider`):

```python
class SportsDataIOProvider(FantasyDataProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
    @property
    def name(self) -> str: return "sportsdataio"
    @property
    def enabled(self) -> bool:
        return bool(self._settings.jaaffl_enable_sportsdataio
                    and self._settings.sportsdataio_api_key)
    # capability methods raise NotImplementedError until a plan is active
```

**Free-live-injury gap mitigation (design §5.C).** The one weak link in the $0 tier is fresh injuries. Primary $0 path: **CBS on-page injury designations** (`CbsOnPageProvider.injuries`, the first INJURIES supporter), backstopped by the official NFL injury report. The clean paid upgrade is **FantasyPros (low monthly cost)** behind `jaaffl_enable_fantasypros`: enabling it **appends** `FantasyProsProvider` after the free tier as a guaranteed-fresh INJURIES/PROJECTIONS/NEWS supplier; because gated providers append last, the precompute INJURIES step must be told to **prefer or merge** FantasyPros for freshness (it will not be first by default). Nothing forces this; the tool is complete at $0. Treat any forward-year (e.g. 2027) projection/ADP as ESTIMATED (design §10, compliance).

### 4.7 Provider → engine boundary rule

- **The engine imports only `jaaffl.providers.base` (`Capability`, `AdpRecord`, `FantasyDataProvider`) and `registry.providers_supporting(...)`** — never a concrete adapter, `httpx`, `nflreadpy`, or a CBS shape. Swapping/adding a provider changes zero engine code.
- **All provider I/O happens in PRECOMPUTE** (design §7.D / LATENCY): pre-draft, `engine.projections.build_projections` *(S0)* and `engine.opponents.pick_probabilities` *(S2)* call `providers_supporting(...)`, take the first supporter (with ADP→ECR deep-round fill, §4.4), and materialize the in-memory `DraftContext` — projections μ/σ/floor/ceiling under the exact CBS scoring map, FFC ADP mean/SD joined by canonical id, tiers/cliff bonuses, and the **replacement baselines for THIS roster (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13; design §10.3/§7.C.4 `league/replacement.py`) plus the flex allocation (default 8 RB / 4 WR, MEASURED live via the top-60 method — likely more RB-heavy in non-PPR)**. The per-pick **hot path `recompute()` touches no provider** (target **<2 s/pick**, analytic **<200 ms**).
- **Canonical-id normalization is the crossing contract:** every value entering the engine is keyed by canonical `player_id`. Unresolved source rows are logged and skipped, never passed through raw. Provider-internal types (`AdpRecord`, Polars frames) stay backend-side and never serialize to the TS contracts.

### 4.8 Config & dependency changes

**`config.py` **[E]** additions** (defaults keep the $0 tier fully on; design §7.C.3):

```python
jaaffl_season: int | None = None               # active draft season; None -> derive current (today 2026)
jaaffl_enable_ffc: bool = True                  # kill-switch for the free FFC ADP provider
jaaffl_ffc_scoring: str = "standard"            # MIRRORS config/league.json "Scoring Format: Standard" (non-PPR); path segment
jaaffl_ffc_teams: int = 12                      # MIRRORS config/league.json "Teams: 12"; query param
jaaffl_ffc_cache_ttl_hours: int = 24            # DAILY cache; do not lower below 24
jaaffl_ffc_base_url: str = "https://fantasyfootballcalculator.com/api/v1"
```

`jaaffl_ffc_scoring`/`jaaffl_ffc_teams` are convenience defaults that **must equal** the immutable `config/league.json` values (`Standard`/`12`) — surface, never silently change, any divergence (`config/league.json` stays the source of truth and is never altered). Existing flags reused unchanged: `jaaffl_enable_fantasypros`, `jaaffl_enable_sportsdataio`, `jaaffl_enable_sportradar`, and the `*_api_key` fields. `jaaffl_data_dir` roots the FFC file cache and nflverse Parquet snapshots.

**`backend/pyproject.toml` **[CHANGE]** `data` extra** — drop `nfl_data_py`, add `nflreadpy` + `polars`:

```toml
data = [
  "duckdb>=0.10",
  "pyarrow>=15",
  "nflreadpy>=0.1.0",   # was: nfl_data_py>=0.3.2 (archived read-only 2025-09-25)
  "polars>=1.0",        # NEW — nflreadpy returns Polars; DuckDB scans it directly
]
```

FFC needs no new dependency (`httpx` is a base dep). `pandas` is removed from `data` unless a legacy caller still needs it.

### Acceptance criteria

- [ ] `Capability` includes `EXPECTED_POINTS`; `historical_stats`/`expected_points` are typed `pl.DataFrame`; `adp()` returns `dict[str, AdpRecord]` across the ABC and every override (incl. the FantasyPros stub).
- [ ] `build_registry()` with no keys returns exactly `[NflreadpyProvider, FantasyFootballCalculatorProvider, CbsOnPageProvider]`; setting a `jaaffl_enable_*` flag **and** its key appends the matching gated provider (after the free tier), and only then.
- [ ] `providers_supporting(Capability.ADP)` → `[ffc]` ($0 default); `Capability.RANKINGS` → `[nflverse, cbs_onpage]`; `Capability.PROJECTIONS`/`INJURIES` → `[cbs_onpage]`.
- [ ] `NflreadpyProvider` pulls `load_player_stats` / `load_ff_opportunity` / `load_ff_rankings`, returns Polars for the first two, and raises the `.[data]`-extra `ProviderError` when `nflreadpy` is absent.
- [ ] `data/crosswalk.py` gains `resolve_name(name, team, pos)`; FFC resolves by name and CBS falls back to it; unresolved rows are skipped (not raised).
- [ ] `FantasyFootballCalculatorProvider.adp(<active season>)` hits `/adp/standard?teams=12&year=<season>` (format = path segment, teams = query), returns `AdpRecord`s with populated `stdev`; a stale/past year raises `ProviderError` and writes **no** cache entry; a second call within 24 h serves from cache (no second HTTP GET).
- [ ] `CbsOnPageProvider` performs **zero** network calls (reads `warehouse.latest_cbs_snapshot`); a bare `CbsOnPageProvider(warehouse, crosswalk)` resolves the sole active league; `league_settings()` returns the authoritative `LeagueSettings` when a snapshot exists and `None` otherwise; capability methods return `{}` (not raise) before the first snapshot.
- [ ] `CapabilityNotSupported` raises for any undeclared capability on every provider (e.g. `NflreadpyProvider.injuries`).
- [ ] `grep` shows no engine module importing a concrete provider, `httpx`, or `nflreadpy`; all provider returns crossing into the engine are keyed by canonical `player_id`.
- [ ] `jaaffl_ffc_scoring`/`jaaffl_ffc_teams` defaults equal `config/league.json` (`standard`/`12`); a divergence is surfaced, and `config/league.json` is left unmodified.
- [ ] `ruff check` + `ruff format --check` clean; unit tests pass with recorded FFC/CBS fixtures (no live network in CI).

### Definition of done

- [ ] `providers/base.py` extended (`EXPECTED_POINTS`, `AdpRecord`, Polars/`adp` retypes); `pandas`→`polars` in `TYPE_CHECKING`.
- [ ] `providers/nflverse.py` → `NflreadpyProvider` (nflreadpy, Polars, crosswalk seed via `load_ff_playerids`/`load_players` **[VERIFY minor]**).
- [ ] `providers/ffc.py` **new** (standard-path/12/current-season, `AdpRecord`, 24 h file+memo cache, empty-payload guard, `resolve_name` id resolution, ECR deep-round fallback documented for precompute).
- [ ] `providers/cbs_onpage.py` **new** (warehouse-reader; `{PROJECTIONS, INJURIES, RANKINGS}` + `league_settings()`; optional `league_id`); `warehouse.py` gains `snapshot_cbs_page` / `latest_cbs_snapshot`; `crosswalk.py` gains `resolve_name`.
- [ ] `providers/sportsdataio.py` + `providers/sportradar.py` **new** disabled stubs; `FantasyProsProvider.adp()` widened.
- [ ] `registry.py` wires all six with `warehouse`/`crosswalk` injection and preference order.
- [ ] `config.py` FFC + season settings added (`jaaffl_season`, `jaaffl_enable_ffc`, `jaaffl_ffc_scoring`, `jaaffl_ffc_teams`, `jaaffl_ffc_cache_ttl_hours`, `jaaffl_ffc_base_url`); `pyproject.toml` `data` extra swapped to `nflreadpy` + `polars`.
- [ ] Fixtures + tests for capability dispatch, registry gating, FFC cache/guard, CBS warehouse-read, and canonical-id normalization.
- [ ] **[VERIFY] flagged in code comments:** nflverse crosswalk fn name; FFC field names (`stdev/high/low/times_drafted/bye`); CBS snapshot schema (extension capture UNVERIFIED, design §5.D / §7.C.2); no reliance on nflverse 2025+ injuries (design §5.C).

---

## 5. CBS sync extension (MV3, @crxjs)

The extension is the **capture layer** — design §5.B4/§5.D2 call it the highest-risk subsystem because **CBS's draft-room transport is UNVERIFIED** (WebSocket vs SSE vs polling, and which framework renders the board are not publicly documented). This section specifies a **three-probe, transport-agnostic** capture that installs *all* probes and lets whichever fires first win, de-duplicated by `pick_number`. It builds on design §5.B (integration findings), §5.D2 (three-probe mechanism), and §7.C.2 (module spec); do not re-derive those.

Everything in this section is **v1** (the live-capture layer that turns live CBS picks into ingest events within the <2 s/pick budget). Nothing here is stretch — the stretch Monte-Carlo season simulator lives in the engine track (design §7.F/§10.5), not the extension.

Two hard rules inherited from the immutable settings and the `agent_usage_contract`:

1. **Draft order is `Decided in-person, then entered into CBS Sports system`** — so the parser **READS IT FROM THE LIVE BOARD and NEVER infers a snake order from team count** (design §5.B5). The parser emits `draft_order: null` if it cannot read it — it must **never** synthesize a snake order.
2. The parser **reports what the CBS room actually says** and **surfaces** (never silently reconciles) any conflict with `config/league.json` immutable values — **Snake; 12 teams; Standard (non-PPR); 17 rounds; QB1/RB1/WR3/WR-RB1/TE1/K1/DST1/Bench8; the WR/RB flex is WR-or-RB ONLY** (never TE/QB/K/DST). Reconciliation is a backend ingest concern (Section 3/4).

### 5.1 File layout — new / amended / implement

Notation: **[N]** new · **[A]** amend · **[E]** implement existing stub.

| Path | Status | Role |
|---|---|---|
| `apps/extension/manifest.json` | **[A]** | add MAIN-world `document_start` inject entry; add `scripting`; bump draft isolated entry to `document_start` |
| `apps/extension/vite.config.ts` | **[N]** | `@crxjs/vite-plugin` build (emits loadable `dist/`) |
| `apps/extension/src/inject/cbs-main.inject.ts` | **[N]** | **Probe 1 + Probe 2** (MAIN world): WS/fetch/XHR monkeypatch + React-fiber read; relays via `postMessage` |
| `apps/extension/src/content/cbs-draft.content.ts` | **[A]** | **TRUST BOUNDARY** (isolated): receive relays + **Probe 3** MutationObserver; validate; de-dup; own the localhost WS; mount overlay |
| `apps/extension/src/content/cbs-league.content.ts` | **[A]** | emit `league_settings` via amended parser (unchanged wiring) |
| `apps/extension/src/lib/parse.ts` | **[E]** | `parseLeagueSettings` + `parseDraftEvent` over a `RawSource` union + `parsePastedResults`; golden-fixture-driven |
| `apps/extension/src/lib/transport.ts` | **[A]** | `DraftSocket` class: content-script-owned WS `/draft/ws`, heartbeat/reconnect; retain `sendEvent` REST fallback |
| `apps/extension/src/overlay/overlay.ts` | **[A]** | subscribe `WS /recs/ws`; render best pick + top-5 with `components`; host manual-paste UI |
| `apps/extension/src/overlay/manual-paste.ts` | **[N]** | manual-paste fallback textarea → `parsePastedResults` |
| `apps/extension/src/background/service-worker.ts` | **[A]** | stays minimal; holds only the **fallback** dynamic MAIN registration (plan-B) |
| `apps/extension/tests/fixtures/**` + `*.test.ts` | **[N]** | captured CBS payloads (redacted) + expected normalized outputs; `vitest` |
| `packages/shared/src/events.ts` | **[A]** | add `pick_number` + `source` for cross-probe de-dup (Zod ⇄ Pydantic parity) |

### 5.2 `manifest.json` — before / after

The current draft content script runs at `document_idle`, which is **too late**: to read live WebSocket frames we must patch `window.WebSocket` **before CBS opens its socket**, i.e. at `document_start`, in the **MAIN** world (design §5.B3 — MV3 `webRequest` sees the WS *handshake* but never WS *messages*, and `declarativeNetRequest` is match/modify only).

**BEFORE** (current — lines 6–26):

```json
"permissions": ["storage"],
"host_permissions": ["https://*.cbssports.com/*", "http://127.0.0.1:8787/*"],
"content_scripts": [
  {
    "matches": ["https://*.cbssports.com/fantasy/*", "https://*.football.cbssports.com/*"],
    "js": ["src/content/cbs-league.content.ts"],
    "run_at": "document_idle"
  },
  {
    "matches": ["https://*.cbssports.com/fantasy/draft/*", "https://*.football.cbssports.com/*draft*"],
    "js": ["src/content/cbs-draft.content.ts", "src/overlay/overlay.ts"],
    "run_at": "document_idle"
  }
]
```

**AFTER**:

```json
"permissions": ["storage", "scripting"],
"host_permissions": ["https://*.cbssports.com/*", "http://127.0.0.1:8787/*"],
"content_scripts": [
  {
    "matches": ["https://*.cbssports.com/fantasy/draft/*", "https://*.football.cbssports.com/*draft*"],
    "js": ["src/inject/cbs-main.inject.ts"],
    "world": "MAIN",
    "run_at": "document_start"
  },
  {
    "matches": ["https://*.cbssports.com/fantasy/*", "https://*.football.cbssports.com/*"],
    "js": ["src/content/cbs-league.content.ts"],
    "run_at": "document_idle"
  },
  {
    "matches": ["https://*.cbssports.com/fantasy/draft/*", "https://*.football.cbssports.com/*draft*"],
    "js": ["src/content/cbs-draft.content.ts"],
    "world": "ISOLATED",
    "run_at": "document_start"
  }
]
```

Changes, each load-bearing:

- **New first entry** = Probe 1/2 injector, `"world":"MAIN"` + `"run_at":"document_start"`. MAIN world = page's JS realm (can see/patch `window.WebSocket`); `document_start` = before CBS's bundle constructs its socket.
- **Draft isolated entry bumped to `document_start`** (and `"world":"ISOLATED"` made explicit) so its `window.addEventListener("message", …)` is installed **before** the first relay; DOM-touching work (overlay mount, MutationObserver) is deferred to `DOMContentLoaded` inside the script (`document.body` is null at `document_start`). Cross-world ordering at the same `run_at` is not guaranteed, but the isolated listener only needs to exist before the first WS *message*, which arrives after CBS's bundle boots — comfortably later. A MAIN-side ring buffer (§5.4.1) flushes early frames on the isolated side's first `ack` (re-posted on a short retry so a lost initial `ack` still flushes), closing the residual race.
- **`overlay/overlay.ts` removed from the `js` array** — it is a module `import`ed by `cbs-draft.content.ts` (via `mountOverlay`), not a second content-script entry; listing it separately would double-execute its top level under bundling.
- **`"scripting"` added** — required for the plan-B dynamic `chrome.scripting.registerContentScripts` MAIN registration (§5.3) and future `activeTab` flows.
- **Deliberately NOT added:** `webRequest`, `declarativeNetRequest`, `cookies`, `<all_urls>`. `host_permissions` stays narrow (CBS + `127.0.0.1:8787` only). This is the compliance posture (design §5.D2, §5.B6; `docs/legal-and-compliance.md`).

**Definition of done — manifest**
- [ ] Loading unpacked on a CBS draft URL shows exactly three content scripts in `chrome://extensions` → *Inspect views*; MAIN entry visible in the page realm.
- [ ] `permissions` == `["storage","scripting"]`; `host_permissions` == CBS + `127.0.0.1:8787`; grep confirms **no** `webRequest`/`declarativeNetRequest`.

### 5.3 Build tooling — `@crxjs/vite-plugin` (WXT fallback)

The manifest references `.ts` entry points; today there is **no bundler** (`package.json` only `tsc --noEmit`). Add Vite + `@crxjs/vite-plugin`, which reads `manifest.json`, bundles each entry (resolving the `@jaaffl/shared` workspace dep), rewrites `.ts`→`.js` in the emitted manifest, and wires HMR.

`apps/extension/vite.config.ts` **[N]**:

```ts
import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.json" with { type: "json" };

export default defineConfig({
  plugins: [crx({ manifest })],
  build: { outDir: "dist", target: "esnext", sourcemap: true },
  server: { port: 5173, strictPort: true, hmr: { port: 5173 } },
});
```

`package.json` script/dep changes:

```jsonc
"scripts": {
  "dev": "vite",                 // was: tsc --noEmit --watch
  "build": "vite build",         // was: tsc --noEmit
  "typecheck": "tsc --noEmit",   // keep for CI parity
  "test": "vitest run",          // was: echo (no tests)
  "lint": "echo \"(lint: add eslint)\" && exit 0"
},
"devDependencies": {
  "@crxjs/vite-plugin": "^2",
  "vite": "^6",
  "vitest": "^2",
  "@types/chrome": "0.0.x",
  "typescript": "^5.7.2"
}
```

**UNVERIFIED / risk:** `@crxjs/vite-plugin` has historically been rough at emitting `"world":"MAIN"` + `document_start` static content scripts (it may route them through `web_accessible_resources`). Two fallbacks, in order:

1. **WXT** (`wxt`): first-class MAIN-world/`document_start` support via `defineContentScript({ world: "MAIN", runAt: "document_start" })`; migration is mechanical (move entries under `entrypoints/`, keep `src/lib` + `src/overlay` as-is).
2. **Dynamic registration from the SW** (plan-B, needs the `scripting` perm we added): keep the static isolated scripts and register the MAIN injector at runtime. This is the design §5.D2 alternative ("or `chrome.scripting.registerContentScripts` from the SW"):

```ts
// service-worker.ts (fallback only)
chrome.runtime.onInstalled.addListener(async () => {
  try {
    await chrome.scripting.registerContentScripts([{
      id: "jaaffl-main",
      js: ["src/inject/cbs-main.inject.js"],
      matches: ["https://*.cbssports.com/fantasy/draft/*", "https://*.football.cbssports.com/*draft*"],
      world: "MAIN", runAt: "document_start", persistAcrossSessions: true,
    }]);
  } catch (e) { console.warn("[jaaffl] MAIN registration failed", e); }
});
```

(If plan-B is used, add `src/inject/cbs-main.inject.js` to `web_accessible_resources` for the CBS matches; the static-manifest primary path does **not** need WAR.)

### 5.4 The three-probe capture (transport-agnostic)

```
                          MAIN world (page realm)                 ISOLATED world (extension realm)
CBS draft room JS ──▶  ┌───────────────────────────┐          ┌──────────────────────────────────────┐
                       │ Probe 1  WS/fetch/XHR patch│          │ cbs-draft.content.ts  = TRUST BOUNDARY │
   window.WebSocket ──▶│ Probe 2  React-fiber read  │─post ───▶│  validate → parse.ts → Zod            │
                       └───────────────────────────┘  Message  │  de-dup by pick_number               │
                                                                │  Probe 3  MutationObserver(board+ticker)│
                                                                │  DraftSocket ▶ ws://127.0.0.1:8787/draft/ws│
                                                                │  mountOverlay()  ◀ ws /recs/ws         │
                                                                └──────────────────────────────────────┘
```

All three probes emit the same **relay envelope**; the isolated side is the sole normalizer. Shared type (declare in `src/lib/transport.ts`, imported by both worlds):

```ts
export type ProbeSource = "ws" | "framework" | "dom" | "paste";

export interface MainRelay {
  source: "jaaffl-main";                 // fixed tag for origin check
  kind: "ws-message" | "ws-send" | "fetch" | "xhr" | "framework";
  url?: string;
  body: string;                          // serialized text; binary → "\u0000binary" sentinel
  ts: number;
  seq: number;                           // monotonic; used by the early-frame flush
}
```

#### 5.4.1 Probe 1 — MAIN-world WS/fetch/XHR monkeypatch (`src/inject/cbs-main.inject.ts` [N])

```ts
import type { MainRelay } from "../lib/transport";

(() => {
  if ((window as any).__jaafflMain) return;      // idempotent
  (window as any).__jaafflMain = true;

  const origin = location.origin;
  let seq = 0;
  const ring: MainRelay[] = [];                  // buffers frames emitted before isolated acks
  let acked = false;

  const DRAFT_URL = /draft|pick|roster|league|adp|board|results/i;
  const isDraftUrl = (u?: string) => !!u && DRAFT_URL.test(u);

  const serialize = (d: unknown): string => {
    if (typeof d === "string") return d;
    try { return JSON.stringify(d); } catch { return "\u0000binary"; }
  };

  function relay(kind: MainRelay["kind"], url: string | undefined, body: string) {
    const msg: MainRelay = { source: "jaaffl-main", kind, url, body, ts: Date.now(), seq: seq++ };
    if (!acked) ring.push(msg);                   // also hold until isolated confirms it is listening …
    window.postMessage(msg, origin);              // … but post immediately too; isolated de-dups either way
  }

  // Isolated side posts {source:"jaaffl-iso", ack:true} once its listener is up → flush the ring.
  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== origin) return;
    const d: any = e.data;
    if (d?.source === "jaaffl-iso" && d.ack && !acked) {
      acked = true;
      for (const m of ring) window.postMessage(m, origin);
      ring.length = 0;
    }
  });

  // --- WebSocket (primary suspected transport) ---
  const NativeWS = window.WebSocket;
  function PatchedWS(this: WebSocket, url: string | URL, protocols?: string | string[]) {
    const ws = protocols === undefined ? new NativeWS(url) : new NativeWS(url, protocols);
    const u = String(url);
    ws.addEventListener("message", (ev) => relay("ws-message", u, serialize((ev as MessageEvent).data)));
    const nativeSend = ws.send.bind(ws);
    ws.send = (data: any) => { relay("ws-send", u, serialize(data)); return nativeSend(data); };
    return ws;
  }
  PatchedWS.prototype = NativeWS.prototype;
  (["CONNECTING", "OPEN", "CLOSING", "CLOSED"] as const).forEach((k) => ((PatchedWS as any)[k] = (NativeWS as any)[k]));
  window.WebSocket = PatchedWS as unknown as typeof WebSocket;

  // --- fetch (SSE/long-poll/REST fallback transports) ---
  const nativeFetch = window.fetch;
  window.fetch = async (...args: Parameters<typeof fetch>) => {
    const res = await nativeFetch(...args);
    try {
      const u = typeof args[0] === "string" ? args[0] : (args[0] as Request)?.url;
      if (isDraftUrl(u)) res.clone().text().then((b) => relay("fetch", u, b)).catch(() => {});
    } catch {}
    return res;
  };

  // --- XHR ---
  const xo = XMLHttpRequest.prototype.open, xs = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m: string, url: string, ...r: any[]) {
    (this as any).__u = url; return xo.call(this, m, url, ...(r as [boolean]));
  };
  XMLHttpRequest.prototype.send = function (body?: Document | XMLHttpRequestBodyInit | null) {
    this.addEventListener("load", () => {
      try { if (isDraftUrl((this as any).__u)) relay("xhr", (this as any).__u, this.responseText); } catch {}
    });
    return xs.call(this, body as any);
  };

  scanFiberLoop();                                // Probe 2, below
})();
```

Notes: constructor-wrap preserves `prototype` + static readyState constants so CBS code is unaffected; `res.clone()` avoids consuming the body; `isDraftUrl` is deliberately **permissive** (the isolated parser is the real filter — better a noisy relay than a missed pick). Binary frames are marked with a sentinel and dropped by the parser.

#### 5.4.2 Probe 2 — framework-state read (React fiber, MAIN world)

Second independent source: if the board is React-rendered, pick state lives on fiber `memoizedProps`. Poll a resilient board container and relay a snapshot when the pick count changes.

```ts
function readFiber(el: Element): any {
  const k = Object.keys(el).find((n) => n.startsWith("__reactFiber$") || n.startsWith("__reactInternalInstance$"));
  return k ? (el as any)[k] : null;
}
function scanFiberLoop() {
  let lastCount = -1;
  const tick = () => {
    try {
      // UNVERIFIED selector set — refine against the live room; try several, first hit wins.
      const root = document.querySelector('[data-testid*="draft" i],[class*="draft-board" i],[id*="draftBoard" i]');
      let fib = root && readFiber(root);
      for (let hops = 0; fib && hops < 40; hops++, fib = fib.return) {
        const p = fib.memoizedProps;
        const picks = p?.picks ?? p?.draftResults ?? p?.selections;
        if (Array.isArray(picks) && picks.length !== lastCount) {
          lastCount = picks.length;
          relay("framework", location.href, JSON.stringify({ picks, order: p?.draftOrder ?? p?.slots }));
          break;
        }
      }
    } catch {}
    setTimeout(tick, 500);
  };
  setTimeout(tick, 800);                           // let React mount first
}
```

`relay`/helpers are the same closure as §5.4.1 (single file). Prop names are **UNVERIFIED** placeholders — the golden fixtures (§5.7) pin the real shape once captured.

#### 5.4.3 Probe 3 — MutationObserver DOM fallback (isolated world)

Last-resort source, immune to transport. Observe **both** the draft board/results node **and** the pick ticker/chat log, because CBS results are known to render **only when the user clicks the results tab** (design §5.B2 — the "results only render on tab click" trap). Mitigation: also watch the always-updating ticker/chat, and, if the results pane is collapsed, programmatically nudge it (`el.click()` on our own page — permissible in the user's own session) or fall back entirely to the ticker. Implementation lives in the isolated content script (§5.5) so it shares the de-dup path.

### 5.5 Isolated content script = the trust boundary (`src/content/cbs-draft.content.ts` [A])

MAIN world is the **page's** realm — page scripts (or a hostile ad) could forge a `jaaffl-main` message. The isolated script therefore **never trusts a relay blindly** (design §5.D2): it checks `event.source`/`event.origin`, runs the payload through `parse.ts` + Zod, and only then forwards. It also owns Probe 3, the de-dup, the localhost WS, and the overlay mount. The validate→de-dup→send tail is factored into `forward()` so **live probes and manual paste (§5.9) converge on the identical path** after parsing.

```ts
import { parseDraftEvent, type RawSource } from "../lib/parse";
import { DraftEventSchema, type DraftEvent } from "@jaaffl/shared";
import { DraftSocket } from "../lib/transport";
import type { MainRelay } from "../lib/transport";
import { mountOverlay } from "../overlay/overlay";

const socket = new DraftSocket();                 // owns ws://127.0.0.1:8787/draft/ws (§5.6)
const seen = new Set<string>();                   // cross-probe de-dup keys

function dedupKey(ev: DraftEvent): string {
  const pn = (ev as any).pick_number;
  if (ev.event_type === "pick_made" && pn != null) return `pick:${pn}`;   // first probe to report a pick wins
  if (ev.event_type === "on_the_clock") return `otc:${(ev.data as any).current_overall_pick}`;
  if (ev.event_type === "draft_state") return `state:${(ev.data as any).current_overall_pick}`;
  return `${ev.event_type}:${ev.data && JSON.stringify(ev.data)}`;
}

/** Validate → cross-probe de-dup → send. Shared tail for every probe AND manual paste. */
function forward(candidate: DraftEvent) {
  const res = DraftEventSchema.safeParse(candidate);   // Zod = the validation gate
  if (!res.success) { console.debug("[jaaffl] dropped invalid event", res.error.issues); return; }
  const ev = res.data;
  const key = dedupKey(ev);
  if (seen.has(key)) return;
  seen.add(key);
  socket.send(ev);
}

/** Parse one raw probe payload, then forward. Silent on non-draft frames. */
function emit(raw: RawSource) {
  const parsed = parseDraftEvent(raw);            // may return null (not a draft frame)
  if (parsed) forward(parsed);
}

// Receive Probe 1 + Probe 2 relays.
window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const d = e.data as MainRelay;
  if (d?.source !== "jaaffl-main" || typeof d.body !== "string" || d.body === "\u0000binary") return;
  const via = d.kind === "framework" ? "framework" : "ws";   // network kinds all normalize the same way
  emit({ via, url: d.url, body: d.body });
});
window.postMessage({ source: "jaaffl-iso", ack: true }, location.origin);   // triggers MAIN ring flush

// Probe 3 (DOM) + overlay: deferred to DOMContentLoaded (body is null at document_start).
function onReady() {
  mountOverlay({ onPaste: (evs) => evs.forEach(forward) });   // subscribes /recs/ws (§5.9); hosts manual paste
  const target =
    document.querySelector('[class*="draft-board" i],[data-testid*="draft" i]') ??
    document.querySelector('[class*="ticker" i],[class*="chat" i],[class*="pick-log" i]') ??
    document.body;
  const mo = new MutationObserver(() => emit({ via: "dom", root: document }));
  mo.observe(target, { childList: true, subtree: true, characterData: true });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onReady);
else onReady();

console.debug("[jaaffl] draft content script active (trust boundary)");
```

De-dup semantics: **first probe to report a given `pick_number` wins**; picks are immutable once made, so later duplicates from slower probes are dropped. `on_the_clock`/`draft_state` dedup on `current_overall_pick` so redundant re-renders don't spam the backend. The append-only SQLite log on the backend (design §7 Step 7) is the durable de-dup of record; this Set is a cheap first line.

### 5.6 Transport — content-script-owns-WS + heartbeat/reconnect (`src/lib/transport.ts` [A])

The content script owns the WebSocket to localhost (not the SW) to sidestep MV3's SW lifecycle (design §5.D2). One socket per concern: **`/draft/ws`** here (ingest, extension→backend); the overlay opens **`/recs/ws`** (push, backend→overlay, §5.9). REST `POST /draft/events` stays as the fail-soft fallback via the existing `sendEvent` helper (retained in this module); `DraftSocket.send` reuses it to mirror anything it cannot put on the wire.

> **Endpoint naming:** the build plan standardizes on `/draft/ws` (ingest) and `/recs/ws` (push) per design §7.C.2/§7.C.6, §7.B (B9), §10.2, and the canonical engine context (scaffold change 4). Design §5.D1/§5.D3's earlier `/ws/draft`,`/ws/recs` spelling is superseded.

```ts
import type { DraftEvent } from "@jaaffl/shared";
// sendEvent(): existing fail-soft REST helper, retained in this same module (§5.1).

const WS_URL = "ws://127.0.0.1:8787/draft/ws";
const HEARTBEAT_MS = 15_000, BACKOFF_MAX_MS = 5_000;

export class DraftSocket {
  private ws: WebSocket | null = null;
  private queue: DraftEvent[] = [];
  private backoff = 500;
  private hb?: ReturnType<typeof setInterval>;
  private alive = false;

  constructor() { this.connect(); }

  private connect() {
    try { this.ws = new WebSocket(WS_URL); } catch { return this.scheduleReconnect(); }
    this.ws.onopen = () => {
      this.backoff = 500; this.alive = true;
      for (const e of this.queue.splice(0)) this.raw(e);
      this.hb = setInterval(() => {
        if (!this.alive) { this.ws?.close(); return; }         // missed liveness → force reconnect
        this.alive = false;
        this.ws?.send(JSON.stringify({ control: "ping" }));    // control frame — NOT a DraftEvent
      }, HEARTBEAT_MS);
    };
    this.ws.onmessage = () => { this.alive = true; };           // any frame (incl. {control:"pong"}) proves liveness
    this.ws.onclose = () => { clearInterval(this.hb); this.ws = null; this.scheduleReconnect(); };
    this.ws.onerror = () => this.ws?.close();
  }

  private scheduleReconnect() {
    setTimeout(() => this.connect(), this.backoff);
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
  }

  private raw(e: DraftEvent) { this.ws!.send(JSON.stringify(e)); }

  send(e: DraftEvent) {
    if (this.ws?.readyState === WebSocket.OPEN) { this.raw(e); return; }
    this.queue.push(e);        // flush over WS on reconnect …
    void sendEvent(e);         // … and mirror over REST now (fail-soft; backend de-dups by pick_number)
  }
}
```

**Heartbeat contract:** heartbeats are `{control:"ping"}` **control frames, not `DraftEvent`s**. The `/draft/ws` handler (design §7.C.6) MUST recognize and **drop them BEFORE the append-only log / ingest fold** — otherwise crash-safe replay (design §7 Step 7) would be corrupted — and MUST reply with any frame (e.g. `{control:"pong"}`) so a half-open socket is detectable; without a reply the client would reconnect each cycle. Reconnect-flush may re-send events already delivered over REST; the backend's `pick_number` de-dup absorbs the overlap.

**Latency:** the capture→ingest hop is network-local (localhost, single-digit ms), leaving the whole <2 s/pick budget (design §7 Step 3, §7.D) to the engine's analytic recompute (<200 ms) and the `/recs/ws` push back to the overlay.

**UNVERIFIED / risk — page-CSP on the localhost WS.** A content-script-initiated `WebSocket` can be blocked by the **CBS page's** `connect-src` CSP (content-script `fetch` to a `host_permissions` host is exempt; `WebSocket` is not always). Mitigation ladder, in order: (1) primary WS `/draft/ws`; (2) if `onerror` fires immediately and repeatedly, the buffered REST `POST /draft/events` path (CSP-exempt, via `sendEvent`) carries every event with zero data loss — recs still arrive on the overlay's `/recs/ws`; (3) if even that is blocked, relay through the SW via `chrome.runtime` messaging (SW is not subject to page CSP). The extension degrades to REST automatically; nothing is dropped.

### 5.7 Parsers (`src/lib/parse.ts` [E]) — golden-fixture-driven

Both parsers accept a discriminated `RawSource` so every probe funnels through one normalizer. This is a **superset** of the current stub signatures (`parseLeagueSettings(doc)`, `parseDraftEvent(root)`), which remain valid as the `{via:"dom"}` case.

```ts
import type { DraftEvent, LeagueSettings } from "@jaaffl/shared";

export type RawSource =
  | { via: "ws" | "framework" | "fetch" | "xhr"; url?: string; body: string }   // network / fiber snapshot (JSON)
  | { via: "dom"; root: ParentNode }                                            // MutationObserver / league page
  | { via: "paste"; text: string };                                             // manual fallback

/** Emit a normalized DraftEvent (pick_made / on_the_clock / draft_state / draft_complete) or null. */
export function parseDraftEvent(src: RawSource): DraftEvent | null;

/** Emit full LeagueSettings — roster slots, flex eligibility, FULL scoring, team count, draft order. */
export function parseLeagueSettings(src: RawSource | Document): LeagueSettings | null;

/** Manual-paste path: many events from a copied results table / pick log; each stamped source:"paste". */
export function parsePastedResults(text: string): DraftEvent[];
```

**`parseDraftEvent` must produce**, for a `pick_made`, a `data` payload carrying enough for the backend crosswalk (design §7 `data/crosswalk.py`) and the required top-level `pick_number` for de-dup:

```jsonc
{
  "event_type": "pick_made",
  "league_id": "<cbs league id>",
  "pick_number": 25,                 // overall (1..204 for 12×17) — REQUIRED for cross-probe de-dup
  "source": "ws",                    // which probe won (ws|framework|dom|paste)
  "data": {
    "overall": 25, "round": 3, "pick_in_round": 1,
    "team_id": "<cbs team id from the board>",
    "cbs_player_id": "<cbs id>", "player_name": "…", "player_team": "PHI", "position": "RB"
  }
}
```

**`parseLeagueSettings` must produce** the **amended** `LeagueSettings` (scaffold change 1, design §7.C.1 / §10.5) — the current schema lacks `scoring_tiers` + `scoring_bonuses`; those fields are added in `packages/shared/src/league.ts` (Section 4's contract work) and the parser must populate them. CBS "standard" (non-PPR) DST scores on **both** points-allowed **and** yards-allowed tiers, and K has a 50+ yard bonus (design §5.C4):

```jsonc
{
  "league_id": "…", "platform": "cbs", "team_count": 12, "draft_type": "snake",
  "roster_slots": [
    { "slot": "QB",   "eligible_positions": ["QB"],       "count": 1, "starting": true },
    { "slot": "RB",   "eligible_positions": ["RB"],       "count": 1, "starting": true },
    { "slot": "WR",   "eligible_positions": ["WR"],       "count": 3, "starting": true },
    { "slot": "WR/RB","eligible_positions": ["WR","RB"],  "count": 1, "starting": true },   // WR-or-RB ONLY — never TE/QB/K/DST
    { "slot": "TE",   "eligible_positions": ["TE"],       "count": 1, "starting": true },
    { "slot": "K",    "eligible_positions": ["K"],        "count": 1, "starting": true },
    { "slot": "DST",  "eligible_positions": ["DST"],      "count": 1, "starting": true },
    { "slot": "BENCH","eligible_positions": ["QB","RB","WR","TE","K","DST"], "count": 8, "starting": false }
  ],
  "scoring": [
    { "stat": "pass_yd", "points_per_unit": 0.04 }, { "stat": "pass_td", "points_per_unit": 6 },
    { "stat": "pass_int", "points_per_unit": -2 },  { "stat": "rush_yd", "points_per_unit": 0.1 },
    { "stat": "rush_td", "points_per_unit": 6 },    { "stat": "rec_yd", "points_per_unit": 0.1 },
    { "stat": "rec_td", "points_per_unit": 6 },     { "stat": "reception", "points_per_unit": 0 },   // non-PPR (Standard)
    { "stat": "fumble_lost", "points_per_unit": -2 }, { "stat": "two_pt", "points_per_unit": 2 },
    { "stat": "fg", "points_per_unit": 3 }, { "stat": "pat", "points_per_unit": 1 },
    { "stat": "dst_td", "points_per_unit": 6 }, { "stat": "dst_sack", "points_per_unit": 1 },
    { "stat": "dst_int", "points_per_unit": 2 }, { "stat": "dst_fr", "points_per_unit": 2 }, { "stat": "dst_safety", "points_per_unit": 2 }
  ],
  "scoring_tiers": [
    { "stat": "dst_points_allowed", "brackets": [
      {"lower":0,"upper":6,"points":8},{"lower":7,"upper":13,"points":6},{"lower":14,"upper":20,"points":4},
      {"lower":21,"upper":27,"points":2},{"lower":28,"upper":34,"points":0},{"lower":35,"upper":null,"points":-2}] },
    { "stat": "dst_yards_allowed", "brackets": [
      {"lower":0,"upper":49,"points":12}, /* … */ {"lower":250,"upper":299,"points":2}] }
  ],
  "scoring_bonuses": [ { "stat": "fg_distance", "threshold": 50, "points": 2 } ],   // 50+ yd FG = 5 total
  "draft_order": ["team_7","team_3", "…"]   // READ FROM THE BOARD; null if unreadable — NEVER a synthesized snake
}
```

Parser internals (helpers, all fixture-tested): `parseRosterSlots`, `parseFlexEligibility` (asserts exactly `["WR","RB"]`), `parseScoringTable`, `parseDstTiers` (both tables), `parseKickerBonus`, `parseTeamCount`, `parseDraftOrderFromBoard`. The §5.C4 values above are the **default/fallback**; the live CBS scoring table is **authoritative** and overrides them. Any mismatch with `config/league.json` immutables (team_count≠12, flex includes TE/QB/K/DST, non-Standard scoring, draft_type≠snake) is **reported as-read and surfaced** to the backend, never silently corrected (`agent_usage_contract`).

The normalized `league_settings` (plus the CBS projections/injuries snapshot from the league page) is what feeds **`CbsOnPageProvider`** (design §7.C.4) — that provider **reads the CBS snapshot from the warehouse, NOT a network fetch** — keeping the whole data path on the $0 tier (design §5.C).

**Golden fixtures** — `apps/extension/tests/fixtures/`:

```
league-settings.cbs.json        →  league-settings.expected.json
pick-made.ws.json               →  pick-made.expected.json
draft-state.fetch.json          →  draft-state.expected.json
draft-board.html                →  draft-order.expected.json   (draft_order read, not inferred)
results-paste.txt               →  results-paste.expected.json (parsePastedResults)
```

`parse.test.ts` (vitest): each fixture asserts `parseX(raw)` deep-equals `expected` **and** `DraftEventSchema`/`LeagueSettingsSchema.parse()` succeeds — this doubles as schema-parity regression armor against CBS DOM/transport churn. Fixtures are **redacted, de-identified** captures from the user's own session (no cookies/PII).

### 5.8 Contract additions — `pick_number` + `source` (Zod ⇄ Pydantic parity)

`packages/shared/src/events.ts` gains two fields on the envelope (design §7.C.1). Keep the Pydantic mirror (`domain/models.py`, Section 4) byte-for-byte aligned or CI schema-parity fails.

```ts
export const DraftEventSchema = z.object({
  event_type: DraftEventTypeSchema,
  league_id: z.string(),
  pick_number: z.number().int().min(1).nullable().optional(),    // NEW — required-when-present for pick_made
  source: z.enum(["ws", "framework", "dom", "paste"]).optional(),// NEW — which probe won (superset of §7.C.1's ws|framework|dom)
  data: z.record(z.unknown()).default({}),
});
```

### 5.9 Overlay wiring (`src/overlay/overlay.ts` [A]) + manual-paste fallback

`mountOverlay(opts?: { onPaste?: (events: DraftEvent[]) => void })` keeps its Shadow-DOM host (styles can't leak either way) and adds: (1) a `/recs/ws` subscription (scaffold change 4) rendering best pick + top-5 with the `ScoreComponents` decomposition (scaffold change 3 — `mlv, vona, risk_penalty, cliff_bonus, sigma, floor, ceiling, replacement_baseline, modifiers{}`) plus `next_turn_availability` (analytic Gaussian survival, design §7.C.2); (2) a **manual-paste** panel (`src/overlay/manual-paste.ts` [N]) for when live capture yields nothing — a textarea into which the user pastes CBS's copied results/pick log. On submit it runs `parsePastedResults(text)` and hands the resulting `DraftEvent[]` to the injected `onPaste` sink, which the content script wires to `forward` (§5.5) — so **manual paste and live capture converge on the same validate→de-dup→send tail** and produce identical normalized events (source `"paste"`). Full recommendation-panel visual design is deferred to the web/overlay section; here we only guarantee the socket + render hook + paste fallback exist. `components` is a forward-looking contract field added by scaffold change 3 (Section 4's `recommendation.ts`).

```ts
// inside mountOverlay(), after the shadow root is built:
const recs = new WebSocket("ws://127.0.0.1:8787/recs/ws");
recs.onmessage = (e) => renderRecs(shadow, JSON.parse(e.data));
//   payload: { ranked: [{ player_id, score, components, next_turn_availability }, …] }
// manual-paste panel: mountManualPaste(shadow, opts?.onPaste ?? (() => {}));
```

### 5.10 Security & compliance posture

- **User's own authenticated session only**, personal/non-commercial, local-first (design §5.B6, ADR 0003, `docs/legal-and-compliance.md`). No credential/cookie access — `permissions` is `storage`+`scripting`; no `cookies`, no `webRequest`/`declarativeNetRequest`.
- **Text-only assistant — NO voice/Realtime** (ADR 0003; design §7.C.6 `explain_recommendation` returns prose only).
- **$0 out-of-pocket besides AI usage** — the extension uses only the $0 data tier (CBS on-page in the user's own session; no paid providers) (design §5.C, ADR 0003).
- **Narrow host scope:** CBS fantasy + `127.0.0.1:8787` only.
- **MAIN world is untrusted:** the isolated content script validates origin (`event.source===window`, `event.origin===location.origin`, `source==="jaaffl-main"`), Zod-parses every payload, and never `eval`s page data.
- **Overlay in a Shadow DOM** (`:host { all: initial }`) — no style bleed either direction.
- **No outbound network except localhost** — every relay terminates at `127.0.0.1:8787`; nothing leaves the machine.
- Fixtures are redacted; no PII/cookies committed.
- **Efficacy honesty:** no peer-reviewed optimal live snake-draft solver exists; the recommendations surfaced in the overlay are validated only by the project's OWN offline simulated-league tournament vs VBD-only / ADP-only baselines (ADR 0003, design §4.C), never by vendor claims. Any forward-year (2027) projections shown are **ESTIMATED**.

### 5.11 Acceptance criteria & Definition of done

**Acceptance criteria**

| # | Criterion | How verified |
|---|---|---|
| A1 | MAIN injector patches `window.WebSocket` **before** CBS opens its socket | console marker timestamp precedes first `ws-message` relay; `document_start`+MAIN confirmed in `chrome://extensions` |
| A2 | At least one probe yields a normalized `pick_made` for every real pick | live draft / replayed fixtures: 204/204 picks (12×17) captured |
| A3 | Exactly one event per `pick_number` when 2–3 probes fire | de-dup unit test + live: `seen` set + backend log show no dup `pick:N` |
| A4 | `parseLeagueSettings` emits full scoring incl. **DST points-AND-yards tiers** + **K 50+ bonus**, roster (WR3 / WR/RB flex / K1 / DST1 / Bench8), `team_count=12`, `draft_type=snake`, `draft_order` from board (or `null`) | `league-settings` + `draft-board` fixtures deep-equal expected; flex eligibility asserted `["WR","RB"]` |
| A5 | Draft order is **never synthesized** from team count | code review + fixture with unreadable order → `draft_order:null`, no snake fabricated |
| A6 | Localhost WS survives a backend restart | kill+restart `backend-dev` mid-draft → reconnect ≤ backoff, buffered events flush, zero loss |
| A7 | Manual-paste produces normalized events **byte-identical** to live capture | `results-paste` fixture == live-capture expected; both traverse `forward()` |
| A8 | Page-CSP WS block degrades to REST with zero data loss | simulate `WebSocket` error → REST `POST /draft/events` (via `sendEvent`) carries all events |
| A9 | Permissions audit passes | manifest == `storage`+`scripting`, hosts == CBS+`127.0.0.1`, no `webRequest`/DNR |
| A10 | Heartbeat never pollutes the event log | `{control:"ping"}` frames dropped pre-ingest by `/draft/ws`; append-only log contains only real `DraftEvent`s |
| A11 | Golden-fixture tests green in CI | `pnpm --filter @jaaffl/extension test` (vitest) + `typecheck` pass |

**Definition of done**
- [ ] `manifest.json` amended per §5.2 (MAIN `document_start` inject, isolated bumped to `document_start`, `scripting` added, overlay de-listed, no `webRequest`/DNR).
- [ ] `vite.config.ts` + `@crxjs/vite-plugin` build emits a loadable `dist/`; `pnpm --filter @jaaffl/extension build` clean; WXT + SW-dynamic-registration fallbacks documented in README.
- [ ] `src/inject/cbs-main.inject.ts` implements Probe 1 (WS+fetch+XHR) + Probe 2 (fiber), origin-scoped `postMessage`, idempotent, early-frame ring buffer with `ack` retry.
- [ ] `src/content/cbs-draft.content.ts` is the trust boundary: origin+Zod validation, Probe 3 (board+ticker MutationObserver with the tab-click-trap handling), `pick_number` de-dup via shared `forward()`, `DraftSocket`, deferred overlay mount.
- [ ] `src/lib/transport.ts` `DraftSocket`: `/draft/ws` owned by the content script, 15 s heartbeat via `{control:"ping"}` control frames (dropped pre-ingest; pong-refreshed liveness), exponential backoff (≤5 s), REST `/draft/events` fallback reusing `sendEvent`.
- [ ] `src/lib/parse.ts` implements `parseDraftEvent` / `parseLeagueSettings` / `parsePastedResults` over `RawSource`; full scoring (DST dual tiers + K bonus), roster, flex eligibility `["WR","RB"]`, draft-order-from-board; feeds `CbsOnPageProvider` via the warehouse snapshot.
- [ ] `packages/shared/src/events.ts` gains `pick_number` + `source`; Pydantic mirror updated (Section 4); schema-parity CI green.
- [ ] `src/overlay/overlay.ts` subscribes `/recs/ws` and renders the `ScoreComponents` decomposition + survival; `src/overlay/manual-paste.ts` fallback wired through `onPaste`→`forward()`.
- [ ] Golden fixtures + `parse.test.ts` committed; CI runs `typecheck` + `vitest`.
- [ ] Security posture verified: Shadow DOM overlay, localhost-only egress, MAIN treated as hostile, redacted fixtures, text-only + $0 + personal-use compliance recorded.
- [ ] **UNVERIFIED flags recorded** for follow-up against the live room: CBS transport (WS/SSE/poll), React fiber prop names + board selectors, page-CSP behavior on the localhost WS, `@crxjs` MAIN-world/`document_start` emission.

---

## 6. Luxury-grade UI/UX frontend

This section turns design §5.D, §7.B (B8/B9/B12), §7.C.2/§7.C.7 and the three merged mockups in
`design/mockups/{style-tile,overlay,dashboard}.html` into an execution-ready front-end build plan.
It does **not** re-derive the engine (see design §10.3) — it binds the engine's output to pixels so
every recommendation is **glanceable and defensible under a running clock**, and never a black box.

**Published, interactive mockups (view now; full index in [Appendix B](#appendix-b--published-luxury-ui-mockups)):**
[design system / style tile](https://claude.ai/code/artifact/e85311a6-cc55-4c8b-b3f4-3a34ec50cbe8) ·
[in-draft overlay](https://claude.ai/code/artifact/93986f24-fe3d-47d5-b93a-d004dd2a57a2) ·
[analytics dashboard](https://claude.ai/code/artifact/b276d135-0d2e-472a-a269-2f6a3a8c17af). These are the
self-contained, theme-aware, WCAG-AA visual contract for this section; their tokens/components are the
authoritative source promoted to the shared foundation in §6.1.

### 6.0 Scope, surfaces, and the compliance envelope

Three front-end surfaces, each mapped to the v1 / stretch split of design §10.5:

| Surface | File root | Tier | Purpose |
|---|---|---|---|
| **A — In-draft overlay** (primary) | `apps/extension/src/overlay/overlay.ts` | **v1** | Docked beside the live CBS board in an isolated Shadow DOM; answers "who, and why" per pick. |
| **B — Analytics dashboard** | `apps/web/app/page.tsx` (+ `layout.tsx`, `globals.css`, `lib/api.ts`) | **v1-lite → stretch** | Read-only board, value curves, tiers, survival, manager tendencies, scenario/season sim. |
| **C — "Explain the pick" affordance** | overlay `Why?` button + dashboard drawer → `assistant/tools.py::explain_recommendation` | **v1-lite** | Text-only (Responses API; **no voice**) prose over the `ScoreComponents` decomposition. |

**Immutable league settings (verbatim — rendered as read-only badges; never editable, never inferred):**

- **Draft Type:** Snake
- **Teams:** 12
- **Draft Order:** Decided in-person, then entered into CBS Sports system
- **Scoring Format:** Standard (non-PPR)
- **Draft Rounds:** 17
- **Roster Slots per Team:** QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8
- The **WR/RB flex is WR-or-RB only** (no TE/QB). The draft board renders the **actual** order read
  live from the CBS room — **never a snake order inferred from team count** (design §2, §10.7).

**Compliance envelope the UI must honor (ADR 0003, `docs/legal-and-compliance.md`, design §10.7):**
personal, non-commercial, **local-first**, the user's own authenticated CBS session only; **$0 besides
AI usage**; **text-only (no voice/Realtime)**. Critically, **the overlay is advisory and never writes a
pick to CBS** — no automation, no `webRequest`/`declarativeNetRequest`; the human makes the pick in the
CBS UI. This corrects the illustrative `Draft James Cook` label in `overlay.html`: the primary action
**copies the player name / pins intent to the local log**, it does not auto-submit (see §6.3).

**Honesty rendered in the product (design §10.7 / §7.E6):** the "why" is always **decomposed** (no
opaque single score); any forward-year (2027) figure carries an **ESTIMATED** badge; the About/footer
states plainly that **no peer-reviewed optimal live snake-draft solver exists** and that efficacy is
proven only by the project's **own offline simulated-league tournament vs VBD-only and ADP-only
baselines** — not by vendor claims.

### 6.1 Design system — "The Draft Room" tokens (promote mockups → shared foundation)

The three mockups already share one token block ("a quant terminal with the poise of a private club").
Promote that block to two consumers with **one source of truth**:

- `apps/web/app/globals.css` — replace the current placeholder (`.wrap/.muted` only) with the full
  token set + component classes; dashboard components consume CSS variables.
- `apps/extension/src/overlay/overlay.ts` — the identical tokens are inlined into the Shadow-DOM
  `<style>` (the overlay must be **self-contained**: no external fonts/CDN, matching the extension CSP
  and the `$0`/local-first envelope).

Keep the two copies in lockstep via a checked-in `design/tokens/draft-room.css` that both import/inline
(a CI diff guard fails if they drift). Token groups (values are authoritative from the mockups):

| Group | Tokens (examples) | Rule |
|---|---|---|
| **Theme** | `color-scheme:light dark`; `:root` = light, `@media (prefers-color-scheme:dark)` + `:root[data-theme]` overrides | Dark-first, fully theme-aware; a `data-theme` toggle wins in **both** directions. |
| **Grounds & ink** | `--plane --surface --card --card-2`; `--ink --ink-2 --ink-3`; `--hairline(-2) --wash` | Warm neutrals biased to brass; WCAG-**AA** body/label contrast in both themes. |
| **Accent** | `--brass --brass-solid --brass-bright --brass-ink --brass-glow`; `--pine` | Brass is the **single** accent — reserved for the recommended pick + primary affordance. |
| **Status** | `--good #0ca30c` (safe to wait) · `--warning #fab219` (run) · `--critical #d03b3b` (scarce now) | Semantic only; always paired with an icon + word (never color-alone). |
| **Position categoricals** | `--pos-qb --pos-rb --pos-wr --pos-te --pos-k --pos-dst` (CVD-validated, per-theme) | Always rendered **beside the position letter** (`.pos-QB…`) — identity is never color-alone. |
| **Type** | `--font-display` (serif, player names/headers) · `--font-ui` (sans) · `--font-mono` (all numbers, tabular) | Scores/σ/survival % are mono + `font-variant-numeric:tabular-nums` so figures align like a ledger. |
| **Scale/rhythm** | `--fs-xxs…--fs-3xl`; spacing 4·8·12·16·24·32·48; `--r-xs…--r-pill`; `--e1 --e2 --e3` | e1 board · e2 card · e3 floating overlay. |
| **Motion** | `--ease cubic-bezier(.2,.7,.2,1)`; `--t-fast 120ms --t 200ms --t-slow 380ms` | `@media (prefers-reduced-motion:reduce)` collapses all transitions/animations to ~0. |

**Component kit** (the vocabulary both surfaces assemble from — class names are already in the mockups):
`.pos`/`.pos-{QB,RB,WR,TE,K,DST}` position chips · `.chip` settings badges · `.stat-pill.is-{good,
warning,critical}` alerts · `.btn`/`.btn-primary` · `.sc-row/.sc-track/.sc-fill/.sc-mid` **Score-
Components "why" bars** · the recommended-pick card (`.reco`) · the clock ring · the survival SVG · the
`.alt` top-5 rows. Chart marks follow one spec (design-system data-viz): 2px lines, ≥8px markers,
recessive `--grid`, emphasized endpoints, legend whenever ≥2 series share a frame.

### 6.2 Contracts the UI binds to (Zod ⇄ Pydantic parity — scaffold changes #1, #3, #4)

All front-end types come from `@jaaffl/shared` (Zod), kept in lockstep with `backend/…/domain/models.py`
(Pydantic) by the schema-parity CI of design B13. The four scaffold changes surface in the UI as:

**#3 — `RecommendedPick` gains `ScoreComponents`** (`packages/shared/src/recommendation.ts`,
mirrored in `models.py`). This is the payload the "why" renders from:

```ts
// packages/shared/src/recommendation.ts  (scaffold change #3)
export const ScoreComponentsSchema = z.object({
  mlv: z.number(),                    // flex-aware Marginal Lineup Value (Hungarian over the 9 starters)
  vona: z.number(),                   // MLV − E[best surviving MLV at pos by your next pick]
  risk_penalty: z.number(),           // −λ(phase,slot)·σ̂  (sign carries floor/ceiling tilt)
  cliff_bonus: z.number(),            // α·CliffBonus (Boris-Chen GMM tier edge)
  sigma: z.number(),                  // σ̂ (projection dispersion)
  floor: z.number(), ceiling: z.number(),
  replacement_baseline: z.number(),   // e.g. RB23 → drives the "replacement RBk" sub-line
  modifiers: z.record(z.number()).default({}),  // capped ≤ ~3–5 pts each: bye-stack −, handcuff +, SOS ±
});
export const RecommendedPickSchema = z.object({
  player_id: z.string(), score: z.number(),
  projected_points: z.number().nullable().optional(),
  next_turn_availability: z.number().min(0).max(1).nullable().optional(), // survival % badge
  tier: z.number().int().nullable().optional(),
  components: ScoreComponentsSchema.nullable().optional(),                 // the decomposition the UI shows
  rationale: z.string().nullable().optional(),
});
```

**#1 — `LeagueSettings` gains `scoring_tiers` + `scoring_bonuses`** (`packages/shared/src/league.ts`).
The dashboard's league panel renders these verbatim so the user can see the exact CBS **Standard**
map — CBS "standard" DST scores on **both** points-allowed **and** yards-allowed tiers, and K gets a
**50+ yard bonus**:

```ts
export const ScoringTierSchema  = z.object({ stat: z.string(),
  brackets: z.array(z.object({ lower: z.number(), upper: z.number().nullable(), points: z.number() })) });
export const ScoringBonusSchema = z.object({ stat: z.string(), threshold: z.number(), points: z.number() });
// LeagueSettingsSchema gains: scoring_tiers: ScoringTierSchema[], scoring_bonuses: ScoringBonusSchema[]
```

**#4 — `WS /recs/ws` push channel** is the UI's live data source. Channels the front end touches:

| Channel | Direction | UI use |
|---|---|---|
| `WS /recs/ws` | backend → UI | **Primary.** Overlay + dashboard subscribe; new `Recommendation` pushed on each pick within the <2 s budget — no polling. |
| `GET /recommendation?league_id=` | UI → backend | REST fallback / initial hydrate (`apps/web/lib/api.ts::fetchRecommendation` already exists). |
| `GET /league/{id}` | UI → backend | Fetch normalized `LeagueSettings` (badges, scoring panel). |
| `/draft/events`, `/draft/ws` | extension → backend | **Ingest only** — not a UI channel; downstream of the **three-probe** capture (MAIN-world WS/fetch/XHR monkeypatch @`document_start` + framework-state read + MutationObserver DOM fallback, de-duped by `pick_number`; design §5/§7). The overlay is **downstream** of capture, never a capture probe itself. |

`API_BASE` stays `http://127.0.0.1:8787` (`apps/web/lib/api.ts`); WS origin `ws://127.0.0.1:8787`.
The UI **never** reads DuckDB/Parquet/SQLite directly — those stores (DuckDB = analytics/backtest;
Parquet = nflverse snapshots; SQLite = ACID app state + append-only draft-event log) live behind the
API/WS boundary (design §7, Step 7). Extend the typed clients:

```ts
// apps/web/lib/api.ts  (add; keep existing fetchRecommendation)
export function subscribeRecs(leagueId: string,
  on: { rec: (r: Recommendation) => void; status: (s: RecsSocketState) => void }): () => void;  // returns unsubscribe
export async function fetchLeague(leagueId: string): Promise<LeagueSettings | null>;
// apps/extension/src/lib/recs.ts  (NEW; overlay-side WS client, reconnect + backoff)
export function subscribeRecs(url: string, on: RecsHandlers): () => void;
```

### 6.3 Surface A — the in-draft overlay (v1, primary)

Replace the placeholder body of `apps/extension/src/overlay/overlay.ts` with a data-bound render. It is
mounted by the **ISOLATED** content script (`src/content/cbs-draft.content.ts`, the trust boundary that
owns the localhost WS), inside `attachShadow({mode:"open"})` with `:host{all:initial}` and
`z-index:2147483647`, so CBS styles never leak **in or out**.

**Public surface (typed, stateless-render):**

```ts
// apps/extension/src/overlay/overlay.ts
import type { Recommendation, RecommendedPick, ScoreComponents } from "@jaaffl/shared";
export interface OverlayHandle {
  update(rec: Recommendation): void;            // paint best pick + top-5 + why + survival
  setStatus(s: OverlaySyncState): void;          // "live" | "stale" | "disconnected" | "waiting" | "manual"
  setClock(secondsLeft: number, pick: string): void;  // e.g. 48, "3.03 · #27"
  destroy(): void;
}
export function mountOverlay(opts: { recsUrl: string }): OverlayHandle;  // wires subscribeRecs internally
```

**Anatomy** (each block maps to `overlay.html`; every element binds to a field above):

1. **Head** — `● Live · CBS synced` heartbeat + the **clock ring** (SVG arc depletes; turns `--critical`
   ≤10 s; respects reduced-motion) + on-the-clock label `On the clock — you · 3.03 · #27`.
2. **Recommended block** — `.pos` chip + serif **name** + mono **score in brass** (`components`-driven),
   with the **replacement sub-line** `BUF · bye 7 · replacement baseline RB23` sourced from
   `components.replacement_baseline`. Actions: **primary = "Copy name" / "Pin my pick"** (advisory,
   local-log only — **never submits to CBS**); secondary **`Why?`** opens the text-only explanation.
3. **The why · score components** — four `.sc-row` bars binding `ScoreComponents` (see §6.5), plus a
   `▲ RB run` `stat-pill` when a positional run is live.
4. **Next-turn survival** — analytic Gaussian curve to your next pick, from `next_turn_availability`
   (survival `S_j(N)=1−Φ((N−m_j)/s_j)` on FFC ADP mean+SD; MC is a design refinement, not v1), with
   `● take RB now` / `◗ WR can wait` pills.
5. **Next best — top 5** — `.alt` rows (rank · pos · name · score · survival %) from `rec.ranked[1..5]`.
6. **Foot** — `Roster 2/17 · RB … · WR …` + freshness `synced 0.4s ago · recompute 380ms`.

**Latency contract (design §7.D):** end-to-end **pick → repainted overlay < 2 s** (analytic engine
< 200 ms); the overlay is **push-driven** (no polling) and does **no** engine compute client-side, so
its own repaint budget is one frame (< 16 ms) — a pure re-render of pushed data. It surfaces the
backend `recompute` ms and sync age so the budget is visible and auditable.

### 6.4 Surface B — the Next.js analytics dashboard (v1-lite → stretch)

Replace the placeholder in `apps/web/app/page.tsx`. Stack per design B12 (all free, local): **Next.js**
(App Router) + **AG Grid** (board/log grids) + **ECharts** (curves, tiers, survival) + **TanStack
Virtual** (long candidate lists). **Read-only**; subscribes `WS /recs/ws`, hydrates via
`fetchRecommendation` + `fetchLeague`. Panels (mapped to `dashboard.html` + design §7.C.7), each tagged
by tier:

| Panel | Binds to | Tier |
|---|---|---|
| **On-the-clock + roster rail** (roster by slot, verbatim: QB 1 · RB 1 · WR 3 · WR/RB 1 · TE 1 · K 1 · DST 1 · Bench 8) | `DraftState`, `LeagueSettings.roster_slots` | v1-lite |
| **Recommendation banner** | `rec.best` + `components` | v1-lite |
| **Draft board** (12 teams × 17 rounds, snake, **order read live — never inferred from team count**) | `DraftState.picks`, live `draft_order` | v1-lite |
| **Pick log + run alerts** | `DraftState.picks`, run detector | v1-lite |
| **Positional value curve** (VOR by position rank; **replacement baselines RB≈22–24, WR≈40–42, QB/TE/K/DST≈13** drawn as vertical rules; flex allocation from the measured split, §6.5) | precompute VOR table | v1-lite |
| **RB tiers & survival + cliff** (Boris-Chen GMM tiers; `α·CliffBonus`) | `tier`, `components.cliff_bonus` | v1-lite |
| **Survival curves to next pick** | `next_turn_availability` series | v1-lite |
| **Manager tendencies** (RB/WR lean, reach-vs-ADP) — *populates as history accrues* | per-manager priors | **stretch** |
| **Scenario comparison / season simulator** ("what happens if…", playoff/championship odds) | Monte-Carlo season sim (CP-SAT end-state) | **stretch** |
| **League scoring panel** (renders `scoring_tiers` = DST points- **and** yards-allowed brackets; `scoring_bonuses` = K 50+; **Standard = non-PPR**) + **data-provenance chips** (the `$0` providers) | `LeagueSettings` | v1-lite |

**Data-provenance chips** name the `$0` tier so the user sees where each number came from (design §5):
`nflreadpy` (history/ECR/xEP), `FFC ADP` (mean+SD, cached daily), `CBS on-page` (live settings/
projections/injuries, read from the warehouse snapshot). Paid providers (FantasyPros / SportsDataIO /
Sportradar) are **off by default** and, when disabled, render no chip.

### 6.5 The "why" rendering spec — binding `Score(p)` to pixels (the anti-black-box guarantee)

Every recommendation renders the **canonical score** (design §10.3) term-for-term; nothing is hidden:

```
Score(p) = MLV_p + κ·max(0, VONA_p) − λ(phase,slot)·σ̂_p + α·CliffBonus_p + Σ capped modifiers
```

| Bar (`.sc-row`) | Field | Fill / axis rule | Color |
|---|---|---|---|
| **MLV** | `components.mlv` | left-anchored, ≥0 | `--pos-{pos}` (identity to the position) |
| **VONA** | `components.vona` (shown as `κ·max(0,VONA)`, **κ=0.5–0.8**) | left-anchored; **clamped at 0** (never negative) | `--brass-solid` |
| **Risk** | `components.risk_penalty = −λ·σ̂` | **diverging around 0** via `.sc-mid`: penalty left/red (floor-tilt, λ>0), bonus right/pine (ceiling-tilt, λ<0) | `--critical` / `--pine` |
| **Cliff** | `α·components.cliff_bonus` (**α=0.3–0.5**) | left-anchored, ≥0 | `--pine` |
| **Modifiers** | `components.modifiers{}` | small chips, **each capped ≤ ~3–5 pts** | status hues |

The **risk sign convention follows the λ schedule verbatim**: R1–2 **+0.2…+0.4**, R3–6 **+0.1…+0.3**,
R7–9 **≈0**, R10–13 **−0.2…−0.4**, R14–17 **−0.3…−0.5**, with the **slot override dominating phase**
(last open startable slot → floor-tilt; surplus/stash → ceiling-tilt). The `replacement_baseline`
field renders the `replacement RBk` sub-line and the value-curve rules. The **flex split** (default
**8 RB / 4 WR**, but **measured live via the top-60 method** — rank RB+WR by non-PPR 12-team FFC ADP,
`flex_RB = (#RB in top-60) − 12`, `flex_WR = (#WR in top-60) − 36`; likely **more RB-heavy** in
Standard) is shown as a small caption on the value-curve panel so the user sees the live allocation
driving the RB/WR baselines.

### 6.6 States, degraded modes, and the manual-paste fallback

| State | Trigger | Rendering |
|---|---|---|
| **Waiting / pre-draft** | connected, no picks yet | "Watching the board…"; roster rail + settings badges shown. |
| **Live** | `/recs/ws` fresh (< ~3 s) | full render; green heartbeat; `synced Xs ago`. |
| **Stale** | last push aged | dim + amber `stale · synced Ns ago`; last known rec kept, not cleared. |
| **Disconnected** | WS closed | reconnect w/ backoff; `● reconnecting`; controls disabled. |
| **Manual-paste fallback** | **UNVERIFIED CBS transport** can't be captured (design §5/§7) | a paste box (settings/board text) → normalized locally; overlay shows `manual` badge. |
| **Engine not wired** | Stage 5 pending | honest placeholder (as today's overlay/`page.tsx`): "Recommendations appear once the engine is wired." |
| **ESTIMATED** | any forward-year (2027) figure | `ESTIMATED` badge on the number. |

### 6.7 Accessibility, theming & performance budgets

- **AA contrast** in both themes; **CVD-safe**: position hues are always paired with the position
  letter and a table/label view exists (never color-alone). Status uses icon + word + color.
- **Reduced-motion**: `@media (prefers-reduced-motion:reduce)` collapses the clock animation and all
  transitions; the clock still updates numerically.
- **Keyboard/focus**: `:focus-visible` brass ring on all controls; `Why?`, `Copy name`, and top-5 rows
  are reachable/operable; charts carry descriptive `aria-label`s (as in the mockups).
- **Numbers**: `--font-mono` + `tabular-nums` everywhere figures appear.
- **Self-contained / `$0` / local-first**: **no external fonts, CDNs, or network calls** beyond
  `127.0.0.1:8787` — system font stacks only; overlay CSS inlined in the Shadow DOM.
- **Budgets**: overlay update repaint < 16 ms (push-driven, no client compute); end-to-end
  pick → overlay < **2 s** (design §7.D); dashboard first meaningful paint < 1.5 s on a laptop; bundle
  ships without third-party fonts.

### 6.8 Build tasks

- [ ] Extract `design/tokens/draft-room.css` from the mockups; inline into `overlay.ts` and import into
      `apps/web/app/globals.css`; add a CI diff guard so the two token copies can't drift.
- [ ] Add `ScoreComponentsSchema` + `components` to `packages/shared/src/recommendation.ts`;
      `ScoringTierSchema`/`ScoringBonusSchema` + fields to `league.ts`; mirror in `domain/models.py`;
      extend schema-parity CI (design B13) with example JSON fixtures.
- [ ] Implement `apps/extension/src/lib/recs.ts` (`subscribeRecs`, reconnect+backoff) and
      `apps/extension/src/overlay/overlay.ts` (`mountOverlay`, `OverlayHandle`, the six anatomy blocks).
- [ ] Relabel the overlay primary action to advisory **Copy name / Pin my pick** (local-log write only)
      + `Why?`; assert in code + test that the overlay issues **no** CBS-write.
- [ ] Extend `apps/web/lib/api.ts` (`subscribeRecs`, `fetchLeague`); rebuild `apps/web/app/page.tsx`
      with the v1-lite panels (AG Grid board/log, ECharts value-curve/tiers/survival) and the league
      scoring panel; gate manager-tendencies + scenario/season-sim behind a **stretch** flag.
- [ ] Wire the `Why?` drawer to `assistant/tools.py::explain_recommendation` (text-only, Responses API).
- [ ] Implement all §6.6 states incl. the **manual-paste fallback** and the **ESTIMATED** badge.

### 6.9 Acceptance criteria

- **Verbatim settings.** The settings badges and roster rail read exactly: Snake · Teams 12 · Draft
  Order "Decided in-person, then entered into CBS Sports system" · Standard (non-PPR) · 17 rounds ·
  QB=1, RB=1, WR=3, WR/RB=1, TE=1, K=1, DST=1, Bench=8 · **WR/RB flex is WR-or-RB only**. The board's
  team order is the **live** CBS order, never inferred from the team count.
- **Decomposition faithful to canon.** The "why" renders MLV, `κ·max(0,VONA)` (**κ=0.5–0.8**, clamped
  ≥0), `−λ·σ̂` with the correct **floor/ceiling diverging sign** per the λ schedule (R1–2 +0.2…+0.4 …
  R14–17 −0.3…−0.5, slot override wins), `α·CliffBonus` (**α=0.3–0.5**), and capped modifiers (≤~3–5
  pts). Replacement baselines shown as **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13**; the flex caption shows
  the live-measured split (default **8 RB / 4 WR**, top-60 method).
- **Live & fast.** Recommendations arrive via `WS /recs/ws` (no polling); a new pick repaints the
  overlay within the **< 2 s** budget; sync age + `recompute` ms are visible.
- **Read-only & compliant.** The UI performs **no CBS write**, no automation, no `webRequest`; talks only
  to `127.0.0.1:8787`; text-only (no voice); loads no external fonts/CDN. Forward-year figures show
  **ESTIMATED**; the About states no proven solver exists (efficacy is offline-validated).
- **Robust & accessible.** All §6.6 states (incl. manual-paste fallback) render; theme toggle works both
  ways; AA + CVD gates pass; reduced-motion honored; overlay is Shadow-DOM-isolated.
- **Contracts in sync.** `pnpm -r typecheck` passes; Zod ⇄ Pydantic schema-parity CI green.

### 6.10 Definition of done

- [ ] `design/tokens/draft-room.css` is the single source; overlay + `globals.css` consume it; drift guard green.
- [ ] `ScoreComponents`, `scoring_tiers`, `scoring_bonuses` exist in Zod **and** Pydantic; parity CI passes with fixtures.
- [ ] Overlay renders all six anatomy blocks from a real `Recommendation`; primary action is advisory and provably issues no CBS-write; `Why?` opens the text-only explanation.
- [ ] Dashboard `page.tsx` renders the v1-lite panels from `/recs/ws` + `fetchRecommendation`/`fetchLeague`; manager-tendencies and scenario/season-sim are present but **stretch-flagged**.
- [ ] Verbatim league-settings badges + roster rail verified; draft board uses the **live** order.
- [ ] `< 2 s` pick→overlay budget met in a local dry-run; sync-age/recompute surfaced; all §6.6 states demonstrated incl. manual-paste and ESTIMATED.
- [ ] AA + CVD + reduced-motion + theme-toggle verified; no external network beyond `127.0.0.1:8787`; `make test` + `pnpm -r typecheck` green.

---

## 7. AI assistant (text-only, OpenAI Responses API)

A **text-only** conversational layer over the same warehouse + engine that drive the overlay. It answers "why this pick?", "compare A vs B", "who survives to my next turn?", "where are the tier cliffs?" by calling **typed function tools** that return *engine numbers*, then narrating them. It is **v1-lite** (design §7.F / §10.5, ROADMAP Stage 7): the value is the engine (design §5–§6, §10.3); the assistant makes the engine's decomposition legible. **No voice, no Realtime** (ADR 0003, `docs/legal-and-compliance.md`). It reads the pre-draft `DraftContext` (precomputed off the **$0 data tier** — nflreadpy + FFC ADP + CBS on-page snapshot, design §5) and the live `DraftState` (design §7.D); it never mutates draft state, never calls a paid provider mid-draft, and never invents a statistic. Grounding rule, enforced at the tool boundary and in the system prompt: **cite only numbers a tool returned; label forward-year (2027) values ESTIMATED and modeled assumptions UNVERIFIED.** There is **no peer-reviewed optimal live snake-draft solver** — efficacy is claimed only from the project's own offline simulated-league tournament vs VBD-only/ADP-only baselines (design §10, `docs/legal-and-compliance.md`).

Cross-references: canonical engine + `ScoreComponents` (design §10.3 / §6.C.7, **scaffold change #3**); the `WS /recs/ws` push channel the assistant piggybacks on (**scaffold change #4**); `assistant/tools.py::dispatch` (design §7.C, module-by-module build spec); precompute + **<2 s/pick** latency plan (design §7.D); v1-vs-stretch placement (design §7.F / §10.5).

### 7.1 Scope, config, and graceful degradation

| Tool / capability | v1 | Stretch | Backing |
|---|---|---|---|
| `get_recommendation` | ✅ | | cached `Recommendation` / `engine.recommend` |
| `explain_recommendation` | ✅ | | `assistant/explain.py::render_score_components` |
| `query_player` | ✅ | | `DraftContext` player table + crosswalk |
| `compare_players` | ✅ | | `DraftContext` + score delta |
| `league_state_summary` | ✅ | | `LeagueSettings` + `DraftState` fold |
| `survival_probability` | ✅ | | `engine.opponents.pick_probabilities` analytic `S_j(N)` |
| `tier_report` | ✅ | | `DraftContext` precomputed GMM tiers (design §10.3 / §6.C.6) |
| `query_warehouse` (utility escape hatch) | ✅ | | `data.warehouse` read-only (DuckDB analytics + Parquet) |
| `manager_tendencies` | | ✅ | per-manager model (design stretch) |
| `web_search` (breaking injuries/news) — hosted | | ✅ | OpenAI hosted tool, config-gated |
| `file_search` (uploaded league rules PDF) — hosted | | ✅ | OpenAI hosted tool, vector store |

All v1 tools read the in-memory `DraftContext` + SQLite fold (no provider/network call), keeping the hot path inside the **<2 s/pick** budget (analytic recompute <200 ms, design §7.D).

**Config keys** (`jaaffl.config.Settings`, read via `get_settings()`):

```python
# EXISTING (backend/src/jaaffl/config.py) — do not rename:
openai_api_key: str | None = None                 # optional; None => assistant disabled, engine unaffected
jaaffl_assistant_model: str = "gpt-4.1-mini"
jaaffl_assistant_enable_web_search: bool = False  # default OFF (stretch)

# [ADD] Stage 7 (keep the jaaffl_assistant_* prefix; both optional, safe defaults):
jaaffl_assistant_vector_store_id: str | None = None   # enables file_search when set (stretch)
jaaffl_assistant_max_tool_iters: int = 6              # bound the function-calling loop
```

**Degradation:** if `openai_api_key is None`, `run_turn` returns `AssistantTurn(available=False, text=ASSISTANT_DISABLED_MSG)` — the overlay/engine keep working. `web_search` is appended only when `jaaffl_assistant_enable_web_search`; `file_search` only when `jaaffl_assistant_vector_store_id` is set. Default posture is **no network calls beyond the model endpoint** (personal-use, local-first, ADR 0003).

### 7.2 Runtime context the tools read (`AssistantContext`)

Tools are **pure read functions** over one immutable context object assembled per request by the API layer. No tool touches providers or the network (except the two hosted tools, which the *model* invokes, not `dispatch`).

```python
# backend/src/jaaffl/assistant/context.py  [N]
from dataclasses import dataclass
from jaaffl.domain import DraftState, LeagueSettings, Recommendation
from jaaffl.engine.context import DraftContext   # [N] Stage-7.D precompute bundle (design §7.D)
from jaaffl.data.warehouse import Warehouse

@dataclass(frozen=True)
class AssistantContext:
    league_id: str
    settings: LeagueSettings          # immutable config (config/league.json) + parsed CBS scoring
                                      #   incl. scoring_tiers + scoring_bonuses (scaffold change #1)
    draft_context: DraftContext       # in-memory precompute (design §7.D / §10.3):
                                      #   projections μ/σ/floor/ceiling, league pts, VORP,
                                      #   replacement baselines RB≈22–24 · WR≈40–42 · QB/TE/K/DST≈13,
                                      #   flex split (default 8 RB / 4 WR — MEASURED live, top-60),
                                      #   GMM tiers + cliff bonuses, FFC ADP mean/SD, crosswalk, season
    draft_state: DraftState           # fold over the append-only SQLite event log (design §7 Step 7)
    last_recommendation: Recommendation | None  # most recent recommend() output (also on WS /recs/ws)
    warehouse: Warehouse              # read-only handle for query_warehouse (DuckDB + Parquet)
```

**Store roles (design §7 Step 7):** `DraftState` is a **fold over the append-only SQLite draft-event log** (crash-safe replay — ingest appends the event *before* computing a rec); `DraftContext` is the in-memory precompute; `query_warehouse` reads the **DuckDB** analytics store + **Parquet** nflverse snapshots (read-only).

How data reaches it: `POST /assistant/message` (see §7.4) reads the current fold (`DraftState`), the process-held `DraftContext`, `LeagueSettings`, and the cached `last_recommendation` (populated whenever the ingest handler runs `recommend` and broadcasts on `/recs/ws`, scaffold change #4), constructs `AssistantContext`, and passes it into `run_turn`. `get_recommendation` returns `last_recommendation` when its `as_of_overall_pick == draft_state.current_overall_pick` (the <2 s common case), else triggers the same stateless recompute via `engine.recommend(draft_state, settings, providers, season=ctx.draft_context.season)` where `providers` are the registered **$0** adapters (nflreadpy/FFC cached daily, CBS on-page from the warehouse — no mid-draft network).

### 7.3 The typed function-tool catalog

Function tools use the flat Responses-API shape already in `FUNCTION_TOOLS` (`{"type":"function","name",...,"parameters"}`). Every return shape is JSON-serializable and every numeric field originates in the engine/warehouse. Return shapes that embed `components` reuse the `ScoreComponents` schema (mirror the Zod `ScoreComponentsSchema`, scaffold change #3 — keep Pydantic ⇄ Zod in sync).

**`get_recommendation`** (v1)

```json
// params
{"type":"object","required":["league_id"],"properties":{
  "league_id":{"type":"string"},
  "top_k":{"type":"integer","minimum":1,"maximum":25,"default":5},
  "position":{"type":"string","enum":["QB","RB","WR","TE","K","DST"],"description":"Optional filter."}}}
// returns
{"league_id":"str","as_of_overall_pick":0,"on_the_clock_team_id":"str|null","my_next_overall_pick":0,
 "ranked":[{"player_id":"str","name":"str","position":"RB","nfl_team":"str|null",
   "score":0.0,"projected_points":0.0,"vorp":0.0,"adp":0.0,"next_turn_availability":0.0,"tier":0,
   "components":{"mlv":0.0,"vona":0.0,"risk_penalty":0.0,"cliff_bonus":0.0,"sigma":0.0,
     "floor":0.0,"ceiling":0.0,"replacement_baseline":0.0,
     "modifiers":{"bye_stack":0.0,"handcuff":0.0,"injury_discount":0.0}}}]}
```

`name`/`position`/`nfl_team` are joined from `Player`; `score`/`projected_points`/`vorp`/`adp`/`next_turn_availability`/`tier` are `RecommendedPick` fields; `components` is the new `ScoreComponents` (scaffold change #3).

**`explain_recommendation`** (v1) — renders the decomposition in prose (see §7.5).

```json
// params
{"type":"object","required":["league_id","player_id"],"properties":{
  "league_id":{"type":"string"},
  "player_id":{"type":"string","description":"Canonical JAAFFL id from get_recommendation."}}}
// returns
{"player_id":"str","name":"str","position":"RB",
 "prose":"str (deterministically templated from components; numbers verbatim)",
 "components":{"...":"ScoreComponents, same shape as above"},
 "caveats":["ESTIMATED: 2027 projections ...","UNVERIFIED: analytic survival / measured flex split ..."]}
```

**`query_player`** (v1)

```json
// params
{"type":"object","required":["player_ref"],"properties":{
  "player_ref":{"type":"string","description":"Canonical id, or free text 'Name TEAM POS'; resolved via nflverse crosswalk with fuzzy name+team+pos fallback."},
  "league_id":{"type":"string"}}}
// returns
{"player_id":"str","name":"str","position":"RB","nfl_team":"str|null","bye_week":0,
 "projected_points":0.0,"mu":0.0,"sigma":0.0,"floor":0.0,"ceiling":0.0,
 "vorp":0.0,"replacement_baseline":0.0,"tier":0,"cliff_bonus":0.0,
 "adp":0.0,"adp_stdev":0.0,"adp_high":0,"adp_low":0,"times_drafted":0,
 "injury_flag":"str|null","drafted":false,"drafted_by_team_id":"str|null",
 "external_ids":{"cbs":"...","gsis":"...","fantasypros":"..."},
 "caveats":["ESTIMATED: forward-year (2027) values ..."]}
```

**`compare_players`** (v1)

```json
// params
{"type":"object","required":["player_refs"],"properties":{
  "player_refs":{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":6},
  "league_id":{"type":"string","description":"Required for the current-pick preference + score delta."}}}
// returns
{"players":[{"...":"query_player card per player"}],"at_overall_pick":0,
 "engine_preference":{"player_id":"str","name":"str","reason_summary":"str"},
 "pairwise_score_delta":[{"a":"pid","b":"pid","delta_score":0.0,
   "driver":"mlv|vona|risk_penalty|cliff_bonus"}],
 "caveats":["..."]}
```

**`league_state_summary`** (v1) — replaces the stub `league_summary`.

```json
// params
{"type":"object","required":["league_id"],"properties":{"league_id":{"type":"string"}}}
// returns
{"league_id":"str","team_count":12,"scoring_format":"standard","draft_type":"snake","draft_rounds":17,
 "roster_slots":{"QB":1,"RB":1,"WR":3,"WR/RB":1,"TE":1,"K":1,"DST":1,"Bench":8},
 "current_overall_pick":0,"current_round":0,"on_the_clock_team_id":"str|null","my_team_id":"str|null",
 "my_roster":[{"slot":"WR","player_id":"str","name":"str"}],"open_slots":["RB","WR","TE"],
 "needs":[{"position":"RB","filled":0,"startable_demand":1,"urgency":"high|med|low"}],
 "best_available":{"RB":[{"player_id":"str","name":"str","score":0.0}],"WR":[]},
 "my_upcoming_overall_picks":[0,0],"picks_until_my_turn":0}
```

> `team_count` (**12**), `draft_type` (**Snake**), `draft_rounds` (**17**), `scoring_format` (**Standard**, non-PPR), and `roster_slots` (**QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8**) are surfaced from the immutable league config (`config/league.json`) — never re-derived, "optimized", or re-ordered. The **WR/RB flex is WR-or-RB only (no TE/QB)**. Draft order is read live from the CBS room — **never inferred from team count**. `needs[].startable_demand` and `best_available` derive from this roster's replacement baselines + the flex split (default **8 RB / 4 WR**, measured live via the **top-60** method: the top-60 RB+WR by non-PPR 12-team FFC ADP = 12 RB + 36 WR + 12 flex; design §10.3 / §6.C.2) — the assistant surfaces, never re-computes, these.

**`survival_probability`** (v1) — analytic Gaussian `S_j(N) = 1 − Φ((N − m_j)/s_j)` (design §10.3 / §6.C.4); computed as `survival = 1 − engine.opponents.pick_probabilities(...)`.

```json
// params
{"type":"object","required":["league_id","player_ids"],"properties":{
  "league_id":{"type":"string"},
  "player_ids":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":40},
  "target_overall":{"type":"integer","minimum":1,"description":"Optional; defaults to your next overall pick N* (snake schedule)."}}}
// returns
{"target_overall":0,"horizon_picks":0,
 "players":[{"player_id":"str","name":"str","position":"RB","survival":0.0,
   "adp_mean":0.0,"adp_stdev":0.0,"source":"ffc|ecr_fallback"}],
 "caveats":["UNVERIFIED: analytic survival assumes ADP-driven independent picks; Monte-Carlo VONA is a stretch refinement.",
            "FFC mocks are 15-round → ADP thins past ~180; deep picks fall back to ECR-derived SD."]}
```

**`tier_report`** (v1) — Boris-Chen tiers via `sklearn.mixture.GaussianMixture` on ECR, **precomputed** into `DraftContext` (read from `ctx.draft_context`, not recomputed per call; design §10.3 / §6.C.6).

```json
// params
{"type":"object","required":["league_id"],"properties":{
  "league_id":{"type":"string"},
  "position":{"type":"string","enum":["QB","RB","WR","TE","K","DST"],"description":"Optional; omit for all."}}}
// returns
{"as_of_overall_pick":0,
 "positions":{"RB":{"tiers":[{"tier":1,"cliff_bonus":0.0,"players_left":0,"at_cliff":true,
   "members":[{"player_id":"str","name":"str","drafted":false}]}]}},
 "caveats":["Tiers are unsupervised (GMM on ECR); boundaries shift as ECR updates."]}
```

**`manager_tendencies`** (STRETCH) — returns `{"available":false,"reason":"stretch: per-manager tendency modeling not enabled","managers":[…],"caveats":["ESTIMATED from small samples; weak priors only."]}` until the stretch model ships. Params `{league_id (req), team_id (opt)}`.

**`query_warehouse`** (v1 utility) — keep the stub's read-only NL escape hatch for ad-hoc questions the typed tools don't cover; params `{"question":"str"}`; returns `{"columns":[…],"rows":[…],"sql":"str (for transparency)"}`. Backed by a Stage-7 read-only accessor on `Warehouse` (e.g. `Warehouse.query_readonly(sql)`) over the DuckDB analytics store; **rejects writes**.

**Hosted tools (stretch, model-invoked):** `web_search` (breaking injuries/news — replaces the stub `player_news`; appended only when `jaaffl_assistant_enable_web_search`) and `file_search` (search an uploaded league constitution / CBS rules PDF; appended only when `jaaffl_assistant_vector_store_id` is set).

**Migration from the current stub (`assistant/tools.py`):** `league_summary → league_state_summary` (renamed, expanded); `player_news →` v1 `injury_flag` field on `query_player` + stretch hosted `web_search`; `query_warehouse` kept; `explain_recommendation` kept with expanded params/return; `dispatch(name, arguments)` → `dispatch(name, arguments, ctx)`.

### 7.4 Wiring — the Responses API function-calling loop

`build_tools()` (amended) assembles function tools + config-gated hosted tools:

```python
def build_tools() -> list[dict[str, Any]]:
    tools = list(FUNCTION_TOOLS)                       # the typed catalog above
    s = get_settings()
    if s.jaaffl_assistant_enable_web_search:
        tools.append({"type": "web_search"})
    if s.jaaffl_assistant_vector_store_id:             # stretch: league-rules file search
        tools.append({"type": "file_search",
                      "vector_store_ids": [s.jaaffl_assistant_vector_store_id]})
    return tools
```

`dispatch` becomes a registry over pure handlers, each taking the `AssistantContext`:

```python
_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_recommendation":     _get_recommendation,      # cached rec or engine.recommend(...)
    "explain_recommendation": _explain_recommendation,  # -> render_score_components (§7.5)
    "query_player":           _query_player,
    "compare_players":        _compare_players,
    "league_state_summary":   _league_state_summary,
    "survival_probability":   _survival_probability,    # 1 - engine.opponents.pick_probabilities
    "tier_report":            _tier_report,             # ctx.draft_context precomputed GMM tiers
    "query_warehouse":        _query_warehouse,         # read-only warehouse (DuckDB)
    # stretch: "manager_tendencies": _manager_tendencies,
}

def dispatch(name: str, arguments: dict[str, Any], ctx: AssistantContext) -> dict[str, Any]:
    """Execute one tool call; pure read over ctx; JSON-serializable result."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return handler(ctx, **arguments)
    except Exception as exc:                            # never crash the loop on a bad tool call
        log.warning("tool_error", tool=name, error=str(exc))
        return {"error": f"{name} failed: {exc}"}
```

The loop drives the Responses API: call → run every `function_call` item through `dispatch` → feed `function_call_output` items back → repeat until the model emits a text message or the iteration cap is hit. Every `dispatch` is an in-memory read over `ctx`, so a full turn makes exactly one outbound host (the model endpoint) unless a hosted tool is enabled.

```python
def run_turn(user_text: str, *, ctx: AssistantContext,
             history: list[dict] | None = None) -> "AssistantTurn":
    s = get_settings()
    if not s.openai_api_key:
        return AssistantTurn(text=ASSISTANT_DISABLED_MSG, tool_calls=[], available=False)
    client = OpenAI(api_key=s.openai_api_key)
    input_items: list[dict] = (history or []) + [{"role": "user", "content": user_text}]
    used: list[str] = []
    for _ in range(s.jaaffl_assistant_max_tool_iters):
        resp = client.responses.create(
            model=s.jaaffl_assistant_model,
            instructions=SYSTEM_PROMPT,      # pins immutable settings + grounding rules (below)
            tools=build_tools(),
            tool_choice="auto",
            input=input_items,
        )
        calls = [it for it in resp.output if it.type == "function_call"]
        if not calls:
            return AssistantTurn(text=resp.output_text, tool_calls=used, available=True)
        input_items += resp.output           # carry the model's function_call items forward
        for call in calls:
            used.append(call.name)
            args = json.loads(call.arguments or "{}")
            result = dispatch(call.name, args, ctx)
            input_items.append({"type": "function_call_output",
                                "call_id": call.call_id,
                                "output": json.dumps(result, default=str)})
    return AssistantTurn(text=TOOL_BUDGET_MSG, tool_calls=used, available=True)
```

`AssistantRequest` and `AssistantTurn` are Pydantic **wire** models in `domain/models.py` (mirrored by Zod in `packages/shared/src`; scaffold-parity CI): `AssistantTurn = {text: str, tool_calls: list[str], available: bool}`; `AssistantRequest = {league_id: str, message: str, history: list[dict] = []}`. `AssistantContext` stays a frozen dataclass in `assistant/context.py` (runtime handles, not serialized).

**System prompt (`SYSTEM_PROMPT`) — required clauses:**
- **Immutable league settings, verbatim** (never paraphrase, "optimize", or re-order):
  - Draft Type: Snake
  - Teams: 12
  - Draft Order: Decided in-person, then entered into CBS Sports system
  - Scoring Format: Standard (non-PPR)
  - Draft Rounds: 17
  - Roster Slots per Team: QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8
  - The WR/RB flex is **WR-or-RB only** (no TE/QB). Draft order is read **live** from the CBS room — **never inferred from team count**.
- **Grounding:** answer only from tool results; never state a projection, ADP, tier, or probability the tools did not return; if a tool returns `error` or empty, say so.
- **Honesty:** label 2027/forward-year values **ESTIMATED**; surface **UNVERIFIED** assumptions (analytic survival independence; flex split measured live, not assumed; upstream CBS capture transport); there is **no peer-reviewed optimal live snake-draft solver** — efficacy comes only from the project's own offline tournament (design §10, `docs/legal-and-compliance.md`).
- **Transparency stance:** prefer `explain_recommendation` when asked "why"; show the decomposition, not a black-box verdict.
- Text-only, personal-use, local-first. No betting/financial-advice framing.

**API transport [ADD] (`api/app.py`, alongside the existing `/health`, `/draft/events`, `/draft/ws`, `/recommendation`; design §7.C):**

```python
@app.post("/assistant/message", response_model=AssistantTurn)
def assistant_message(body: AssistantRequest) -> AssistantTurn:
    ctx = build_assistant_context(body.league_id)   # DraftContext + fold + settings + last rec
    return run_turn(body.message, ctx=ctx, history=body.history)
```

This is the only new HTTP surface the assistant needs; it reuses the same in-memory `DraftContext` and SQLite fold that back `/recommendation` and `WS /recs/ws`.

### 7.5 `explain_recommendation` prose contract

`explain_recommendation` calls a **deterministic** renderer so the numbers are grounded at the tool boundary — the model narrates around the returned `prose` but must not alter its figures. The same function fills `RecommendedPick.rationale`.

The prose narrates the canonical score (design §10.3 / §6.C.7):

```
Score(p) = MLV_p + κ·max(0, VONA_p) − λ(phase,slot)·σ̂_p + α·CliffBonus_p + Σ capped modifiers
```

**Component semantics (so the numbers are directly readable):** `ScoreComponents` carries each term *as it enters* `Score(p)`, except `vona` which is raw so κ can be shown:
- `mlv` = flex-aware Marginal Lineup Value (Hungarian over the 9 starting slots, design §6.C.3), enters at weight 1.
- `vona` = **raw** `VONA_p` (the MLV gap vs your next pick); the reply shows κ, contribution = `κ·max(0, vona)`, **κ = 0.5–0.8**.
- `risk_penalty` = `λ(phase,slot)·σ̂_p` (signed; enters as `−risk_penalty`). **σ̂ is σ *normalized* per design §6.C.5**, so this is a small floor/ceiling nudge — *not* `λ × raw_sigma`. λ schedule (config/engine.json / `EngineParams`): R1–2 **+0.2…+0.4**, R3–6 **+0.1…+0.3**, R7–9 **≈0**, R10–13 **−0.2…−0.4**, R14–17 **−0.3…−0.5**; **slot override dominates phase** (last open startable slot → floor `λ>0`; surplus/stash → ceiling `λ<0`).
- `cliff_bonus` = **α·CliffBonus_p** (the α-weighted contribution, **α = 0.3–0.5**; Boris-Chen GMM tiers, design §6.C.6).
- `sigma`/`floor`/`ceiling` = **raw** season-pts SD and the μ ± z·σ range (descriptive; drives floor/ceiling, *not* the λ term).
- `replacement_baseline` = league points at this roster's canonical replacement **rank** (design §10.3: **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13**).
- `modifiers{}` = capped contributions (≤ ~3–5 pts each; design §6.C.7: bye-stack −, handcuff-synergy +, SOS tiebreak ±).

```python
# backend/src/jaaffl/assistant/explain.py  [N]
def render_score_components(pick: RecommendedPick, *, name: str, position: Position,
                            phase: str, slot_context: str,
                            next_overall_pick: int, kappa: float) -> tuple[str, list[str]]:
    """Return (prose, caveats). Every number is taken verbatim from pick.components /
    pick fields; nothing is computed or embellished here beyond formatting."""
```

**Field → clause mapping** (each clause emitted only when its component is present/non-trivial):

| `ScoreComponents` field | Prose clause (template) |
|---|---|
| `mlv` | "Adds **{mlv:.1f}** pts to your optimal 9-man starting lineup right now (flex-aware marginal lineup value)." |
| `replacement_baseline` | "A replacement-level {position} here is ~**{replacement_baseline:.1f}** league pts; {name} clears that bar." |
| `vona` (>0) | "Waiting has a cost: the best {position} likely on the board at your next pick (~#{next_overall_pick}) projects ~**{vona:.1f}** pts worse, so picking now banks that edge (scarcity weight κ={kappa})." |
| `vona` (≈0) | "Little scarcity pressure — comparable {position} value should still be there at your next pick." |
| `next_turn_availability` | "P(still available at your next pick) ≈ **{next_turn_availability:.0%}**." |
| `risk_penalty`>0 / `sigma`/`floor`/`ceiling` | "We tilt toward the **floor** ({slot_context}, {phase}): σ̂ range **{floor:.0f}–{ceiling:.0f}** (σ=**{sigma:.1f}**) → a **{risk_penalty:.1f}** safety adjustment." |
| `risk_penalty`<0 | "We tilt toward the **ceiling** ({slot_context}, {phase}): upside to **{ceiling:.0f}** earns a **{abs(risk_penalty):.1f}** credit." |
| `cliff_bonus` (>0) | "Last player before a **tier cliff** — **+{cliff_bonus:.1f}**, because the next {position} tier drops off." |
| `modifiers{}` | one capped clause each (±a few pts): `bye_stack`, `handcuff`, `injury_discount`. |

**Worked example** — components in → prose out:

```json
{"mlv":8.4,"vona":3.1,"risk_penalty":0.6,"cliff_bonus":1.2,"sigma":24.0,
 "floor":168,"ceiling":242,"replacement_baseline":150.0,
 "modifiers":{"injury_discount":-0.8}}
```

> "**Bijan Robinson (RB)** is the pick. He adds **8.4** pts to your optimal starting lineup right now, well above the ~**150** a replacement RB would give here. Waiting hurts: the best RB likely on the board at your next pick (~#28) projects about **3.1** pts worse (κ=0.6). It's your first open startable RB slot in Round 2, so we lean to the **floor** — range **168–242** (σ=**24**) — a **0.6** safety nudge. He's the **last back before a tier cliff** (**+1.2**), minus a small **0.8** injury discount. P(available next turn) ≈ **31%**. *Projections blend free nflverse + CBS on-page sources; 2027 components are ESTIMATED; survival is an analytic approximation (UNVERIFIED).*"

Note the two σ's: `sigma`=24 is the **raw** season-pts SD that sets the 168–242 range; the **0.6** risk term is `λ·σ̂` with σ̂ **normalized** (design §6.C.5), which is why an R1–2 floor-tilt reads as a mild nudge rather than `λ × 24`.

**Guardrails (enforced):** the renderer only formats `pick.components` values — it cannot fabricate a stat; if a field is `None` its clause is dropped (never guessed); the `caveats` list always carries the ESTIMATED (forward-year) and UNVERIFIED (analytic survival / measured flex split) notes so the model surfaces them.

### 7.6 Guardrails, honesty & compliance

- **No fabricated stats.** Numbers appear in a reply only if a tool returned them; the system prompt forbids invention; `render_score_components` is number-preserving by construction.
- **ESTIMATED / UNVERIFIED, always surfaced:** 2027 values ESTIMATED; analytic survival independence, live-measured flex split, and upstream CBS capture transport (three-probe, transport-agnostic; UNVERIFIED at source) flagged UNVERIFIED; **no claim of a peer-reviewed optimal live-draft solver** — efficacy only from the project's own offline tournament.
- **Text-only, local-first, personal-use** (ADR 0003): no voice/Realtime; no network beyond the model endpoint unless `web_search`/`file_search` are explicitly enabled; operates only on the user's own authenticated CBS session data already in the warehouse; **$0 out-of-pocket besides AI usage**.
- **Immutable settings** echoed verbatim (Snake · 12 teams · in-person→CBS order · Standard/non-PPR · 17 rounds · QB1/RB1/WR3/WR-RB flex1/TE1/K1/DST1/Bench8, flex WR-or-RB only); the assistant never re-derives roster/scoring/order or infers snake order from team count.

### 7.7 Testing plan

- **Per-tool determinism:** golden fixtures — build a fixed `AssistantContext` from a canned `DraftContext` + `DraftState`; assert each handler's exact return dict (`get_recommendation`, `query_player`, `compare_players`, `league_state_summary`, `survival_probability`, `tier_report`).
- **Immutable-settings echo:** assert `league_state_summary` returns `team_count=12`, `draft_type="snake"`, `draft_rounds=17`, `scoring_format="standard"`, and `roster_slots == {"QB":1,"RB":1,"WR":3,"WR/RB":1,"TE":1,"K":1,"DST":1,"Bench":8}` — byte-for-byte from `config/league.json`, no re-derivation.
- **`render_score_components` golden test:** the example above (components JSON → expected prose + caveats); assert every number in the prose is present in the input and none is added; assert dropped clauses for `None` fields; assert `sigma`/`risk_penalty` render as distinct quantities (σ̂-normalization note).
- **Loop test with a mocked OpenAI client:** stub `client.responses.create` to emit a `function_call` then a final message; assert `dispatch` runs, a `function_call_output` is fed back, and `run_turn` returns the text; assert the iteration cap terminates cleanly with `TOOL_BUDGET_MSG`.
- **Config gating:** `build_tools()` has no `web_search` by default and `file_search` only when a vector store id is set; `openai_api_key=None` → `available=False`.
- **No-network assertion:** with hosted tools off, a full turn makes exactly one outbound host (the model endpoint) and no provider/CBS/FFC calls.
- **Schema parity:** `components` in tool returns validate against Zod `ScoreComponentsSchema`; `AssistantTurn`/`AssistantRequest` validate against their Zod mirrors (reuse the Pydantic ⇄ Zod parity fixtures, design §7.E).

### 7.8 Acceptance criteria

- [ ] `assistant/tools.py` exposes the v1 catalog (`get_recommendation`, `explain_recommendation`, `query_player`, `compare_players`, `league_state_summary`, `survival_probability`, `tier_report`, `query_warehouse`) with the params + return shapes above; `manager_tendencies`, `web_search`, `file_search` are present but stretch/off-by-default.
- [ ] `dispatch(name, arguments, ctx)` executes every v1 tool as a pure read over `AssistantContext`, returns JSON-serializable results, and never raises into the loop (errors returned as `{"error": …}`).
- [ ] `run_turn` completes a real function-calling turn on the Responses API using `jaaffl_assistant_model`, honors `jaaffl_assistant_enable_web_search` / `jaaffl_assistant_vector_store_id`, respects `jaaffl_assistant_max_tool_iters`, and returns `available=False` when `openai_api_key` is unset.
- [ ] `explain_recommendation` returns prose whose every number matches `ScoreComponents` (with `risk_penalty = λ·σ̂` distinct from raw `sigma`), drops clauses for absent fields, and always includes the ESTIMATED + UNVERIFIED caveats.
- [ ] `league_state_summary` echoes the immutable settings verbatim (12 teams, Snake, Standard/non-PPR, 17 rounds, QB1/RB1/WR3/WR-RB1/TE1/K1/DST1/Bench8; flex WR-or-RB only) and never infers draft order from team count.
- [ ] `POST /assistant/message` builds `AssistantContext` from the live fold + in-memory `DraftContext` + cached `Recommendation` and returns an `AssistantTurn`, within the <2 s/pick budget.
- [ ] Default posture makes no network calls beyond the model endpoint.

### Definition of done

- [ ] Catalog, `AssistantContext` (`assistant/context.py`), `dispatch` registry, `run_turn`, `build_tools()`, and `render_score_components` (`assistant/explain.py`) implemented; `DraftContext` (`engine/context.py [N]`) and a read-only `Warehouse` query accessor exist; `[ADD]` config keys added to `jaaffl.config`; `AssistantTurn`/`AssistantRequest` added to `domain/models.py`.
- [ ] `ScoreComponents` return shapes mirror the Zod `ScoreComponentsSchema` (scaffold change #3); `AssistantTurn`/`AssistantRequest` mirrored in `packages/shared/src`; parity CI green.
- [ ] Tests in §7.7 pass (`pytest`) with the OpenAI client mocked — no live key or network required in CI; `ruff check` + `ruff format --check` clean.
- [ ] Stub migration applied (`league_summary → league_state_summary`; `player_news → query_player.injury_flag` + stretch `web_search`; `dispatch` gains `ctx`); no dangling references.
- [ ] Manual smoke: with a real key and a replayed draft log, "why is X the pick?" returns a grounded decomposition citing only engine numbers (Score terms, canonical baselines), and "who survives to my next turn?" returns analytic survival probabilities with the FFC-depth caveat.

---

## 8. API & WebSocket contracts

This section specifies the complete wire surface of the FastAPI companion service that runs on
`127.0.0.1:8787` (`backend/src/jaaffl/api/app.py`, entrypoint `jaaffl.api.__main__` → `uvicorn`,
console script `jaaffl-api = "jaaffl.api:main"`). It documents every HTTP route and both WebSocket
channels against the shared contracts in `packages/shared/src/*.ts` (Zod, source of truth) and their
Pydantic mirrors in `backend/src/jaaffl/domain/models.py`. It realizes design decision **B9** (§7.B)
and the module spec **§7.C.6**: *keep* `POST /draft/events` + `WS /draft/ws` + `GET /recommendation`;
*add* `WS /recs/ws` (push — **scaffold change #4**) and `GET /league/{id}`. It supersedes the earlier
provisional path names in design **§5.D1/§5.D3** (`/ws/draft`, `/ws/recs`, `/recommend`, `/league`,
`/snapshot`): the canonical §7 convention is `/draft/ws`, `/recs/ws`, `/recommendation`,
`/league/{id}` (no separate `/snapshot` — the CBS snapshot lives in the warehouse) — and the live
scaffold in `app.py` already uses them.

Design invariants honored here: local-first/loopback-only (ADR 0002/0003); the ingest hot path
appends to the SQLite append-only log **before** any engine work so a crash replays exactly (§7 Step
7, §7.C.4 `ingest/log.py`); the per-pick answer is a decomposed, flex-aware `Recommendation`
carrying `ScoreComponents` (scaffold change #3); the push channel meets the **<2 s/pick** budget
(analytic path **<200 ms**, design §7.D) without polling; and payload shapes are kept in
Zod⇄Pydantic parity by CI (**B13**). The engine baselines every value against **this** immutable
roster (§8.3.2); no route ever paraphrases, re-orders, or "optimizes" the league constitution.

### 8.1 Surface overview

| Method | Path | Direction | Request schema | Response / push schema | Status |
|---|---|---|---|---|---|
| GET | `/health` | client → svc | — | liveness JSON | **[EXISTS]** (returns `{status,version}`; add `schema_version`) |
| GET | `/league/{league_id}` | client → svc | path param | `LeagueSettingsSchema` | **[N]** (§7.C.6) |
| GET | `/recommendation` | client → svc | query params (§8.3.3) | `RecommendationSchema` | **[EXISTS]** stub (501) → Stage 5 |
| POST | `/draft/events` | extension → svc | `DraftEventSchema` | ingest ack | **[EXISTS]** (fallback; today returns `{accepted:true}`) |
| WS | `/draft/ws` | extension → svc | `DraftEventSchema` frames | ack frames | **[EXISTS]**, **[A]** envelope + heartbeat |
| WS | `/recs/ws` | svc → overlay/web | subscribe/pong frames | `RecommendationSchema` frames | **[N]** (§7.C.6; **scaffold change #4**) |

`/draft/ws` is the primary ingest transport; `POST /draft/events` is the HTTP fallback used by the
extension's manual-paste path and by tests (design §5, "manual-paste fallback"). `/recs/ws` is the
push channel (scaffold change #4 — *keep* `/draft/ws` ingest + REST) that lets the Shadow-DOM overlay
(§7.C.2) and the Next.js dashboard (§7.C.7) update within the **<2 s** budget without polling.

### 8.2 Named shared schemas (the contract surface)

Every payload below validates against one of these four named schemas (plus their embedded
sub-schemas). Full definitions live in the shared-contracts spec (§7.C.1) and `domain/models.py`;
this section only re-states the **new** `ScoreComponentsSchema` because it is load-bearing for the
`/recommendation` response and is one of the four required scaffold changes.

- **`DraftEventSchema`** (`events.ts` ⇄ `DraftEvent`) — the ingest envelope: `event_type`,
  `league_id`, `data`. Scaffold amendment (§7.C.1): capture events additionally carry a top-level
  **`pick_number: number`** (required on `pick_made`/`on_the_clock`) for cross-probe de-dup and an
  optional **`source: "ws" | "framework" | "dom"`** tagging which of the three capture probes emitted
  the frame (`ws` = MAIN-world `WebSocket`/`fetch`/`XHR` monkeypatch at `document_start`; `framework`
  = React-fiber state read; `dom` = `MutationObserver` fallback — design §5.D2/§7.C.2).
- **`LeagueSettingsSchema`** (`league.ts` ⇄ `LeagueSettings`) — normalized league config, extended
  by **scaffold change #1** with `scoring_tiers` (`ScoringTierSchema`: DST **points-allowed** and
  **yards-allowed** brackets) and `scoring_bonuses` (`ScoringBonusSchema`: K 50+ yard bonus). CBS
  "Standard" scores DST on **both** points- and yards-allowed tiers.
- **`RecommendationSchema`** (`recommendation.ts` ⇄ `Recommendation`) — `{league_id,
  as_of_overall_pick, ranked: RecommendedPick[], reasoning}`. Each `RecommendedPickSchema` embeds an
  **optional `components: ScoreComponents`** (**scaffold change #3**; present unless
  `include_components=false`, §8.3.3).
- **`ScoreComponentsSchema`** — the decomposition of the canonical objective (design §6.C.7 /
  §10.3 / §7 Step 8). The canonical score is
  `Score(p) = MLV_p + κ·max(0,VONA_p) − λ(phase,slot)·σ̂_p + α·CliffBonus_p + Σ capped modifiers`,
  where **MLV** is the flex-aware Marginal Lineup Value via `scipy.optimize.linear_sum_assignment`
  (Hungarian) over the **9 starting slots** with a **WR/RB flex mask** on a replacement-filled
  baseline lineup, and **CliffBonus** comes from Boris-Chen tiers = `sklearn.mixture.GaussianMixture`
  on ECR:

```ts
// packages/shared/src/recommendation.ts  [A] (Zod = source of truth)
export const ScoreComponentsSchema = z.object({
  mlv: z.number(),                     // flex-aware Marginal Lineup Value: gain to the optimal 9-starter
                                       //   lineup from adding p (Hungarian over 9 slots, WR/RB flex mask,
                                       //   replacement-filled) — scipy.optimize.linear_sum_assignment
  vona: z.number(),                    // MLV_p − E[best surviving MLV at pos(p) by your next pick];
                                       //   survival S_j(N)=1−Φ((N−m_j)/s_j) from FFC ADP mean+stdev (raw, unweighted by κ)
  risk_penalty: z.number(),           // λ(phase,slot)·σ̂_p, ALREADY SCALED & SIGNED (λ>0 floor-tilt penalizes;
                                       //   λ<0 ceiling-tilt rewards); subtracted in score. σ̂ = σ normalized to season-pts (§6.C.5)
  cliff_bonus: z.number(),             // α·CliffBonus_p, ALREADY SCALED (Boris-Chen GMM tier cliff on ECR)
  sigma: z.number().nonnegative(),     // σ̂_p RAW projection spread σ_p (season-pts) that generates floor/ceiling
  floor: z.number(),                   // low-percentile projection
  ceiling: z.number(),                 // high-percentile projection
  replacement_baseline: z.number(),    // league points at this roster's canonical replacement index
                                       //   (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13; design §10.3)
  modifiers: z.record(z.number()).default({}), // capped ≤~3–5 pts each: bye_stack(−), handcuff_synergy(+), sos(±)
});
export type ScoreComponents = z.infer<typeof ScoreComponentsSchema>;
// RecommendedPickSchema gains:  components: ScoreComponentsSchema.nullable().optional()
//   ⇄ Pydantic  components: ScoreComponents | None = None   (parity: optional on BOTH sides)
```

```python
# backend/src/jaaffl/domain/models.py  [A] (Pydantic mirror; field names + order identical)
class ScoreComponents(BaseModel):
    mlv: float
    vona: float
    risk_penalty: float
    cliff_bonus: float
    sigma: float = Field(ge=0.0)
    floor: float
    ceiling: float
    replacement_baseline: float
    modifiers: dict[str, float] = Field(default_factory=dict)

class RecommendedPick(BaseModel):
    ...
    components: ScoreComponents | None = None   # populated by engine.recommend (Stage 5); omitted when include_components=false
```

**λ(phase,slot) risk schedule** (design §6.C.5/§10.3, echoed per-response, versioned in
`config/engine.json`): R1–2 **+0.2…+0.4** · R3–6 **+0.1…+0.3** · R7–9 **≈0** · R10–13 **−0.2…−0.4**
· R14–17 **−0.3…−0.5**. **Slot override dominates phase:** filling your last open startable slot →
force floor-tilt (λ>0); surplus depth/stash → force ceiling-tilt (λ<0). Tunable defaults: **κ =
0.5–0.8**, **α = 0.3–0.5**, **flex split default 8 RB / 4 WR** (MEASURED live via the top-60 method,
§8.3.3 — likely more RB-heavy in non-PPR).

**Score reconstruction identity** (used by the overlay and by the audit/parity test):
`score == mlv + κ·max(0, vona) − risk_penalty + cliff_bonus + Σ modifiers.values()`, where **κ** is
`EngineParams` from `config/engine.json` (§7.C.3, **B11**) and is echoed once per response in
`Recommendation.reasoning` (see §8.3.3). `risk_penalty` and `cliff_bonus` are stored **already
scaled** (λ·σ̂ and α·Cliff), and `vona` is stored **raw** (κ and `max(0,·)` are applied at
reconstruction), so an implementer rebuilds `score` from the stored components plus κ alone — **not**
from λ or σ. Note: `risk_penalty` uses σ̂ = σ *normalized to the season-points scale* (§6.C.5),
whereas the `sigma` field carries the *raw* projection spread σ_p (which also generates
`floor`/`ceiling`); therefore `risk_penalty ≠ λ·sigma` in general — reconstruct only from the stored
(already-scaled) `risk_penalty`.

### 8.3 REST endpoints

#### 8.3.1 GET `/health`

Liveness + build/schema version probe. No params. Always 200 while the process is up.

```json
// 200 OK
{ "status": "ok", "version": "0.0.0", "schema_version": "1.0.0" }
```

`version` echoes `jaaffl.__version__` (currently `0.0.0`); `schema_version` echoes the
`@jaaffl/shared` `SCHEMA_VERSION` (§8.8) and is added by the versioning work — the current stub
returns `{status, version}` and is amended to include it. The two version axes are independent (app
build vs contract schema) and may differ.

#### 8.3.2 GET `/league/{league_id}` → `LeagueSettingsSchema`

Returns the normalized, authoritative `LeagueSettings` for a league (parsed by
`ingest/cbs.normalize_league_settings` from the CBS snapshot in the warehouse; design §7.C.4). This
is the exact roster the engine baselines against.

| Param | In | Type | Required | Notes |
|---|---|---|---|---|
| `league_id` | path | string | yes | e.g. `cbs-1029384` |

```json
// GET /league/cbs-1029384  → 200 OK  (validates against LeagueSettingsSchema)
{
  "league_id": "cbs-1029384",
  "platform": "cbs",
  "name": "JAAFFL",
  "team_count": 12,
  "draft_type": "snake",
  "roster_slots": [
    { "slot": "QB",    "eligible_positions": ["QB"],        "count": 1, "starting": true },
    { "slot": "RB",    "eligible_positions": ["RB"],        "count": 1, "starting": true },
    { "slot": "WR",    "eligible_positions": ["WR"],        "count": 3, "starting": true },
    { "slot": "WR/RB", "eligible_positions": ["WR","RB"],   "count": 1, "starting": true },
    { "slot": "TE",    "eligible_positions": ["TE"],        "count": 1, "starting": true },
    { "slot": "K",     "eligible_positions": ["K"],         "count": 1, "starting": true },
    { "slot": "DST",   "eligible_positions": ["DST"],       "count": 1, "starting": true },
    { "slot": "BENCH", "eligible_positions": ["QB","RB","WR","TE","K","DST"], "count": 8, "starting": false }
  ],
  "scoring": [
    { "stat": "rushing_yards",    "points_per_unit": 0.1,  "applies_to": null },
    { "stat": "rushing_td",       "points_per_unit": 6.0,  "applies_to": null },
    { "stat": "receiving_yards",  "points_per_unit": 0.1,  "applies_to": null },
    { "stat": "receiving_td",     "points_per_unit": 6.0,  "applies_to": null },
    { "stat": "reception",        "points_per_unit": 0.0,  "applies_to": null }
  ],
  "scoring_tiers": [
    { "stat": "dst_points_allowed", "brackets": [
      { "lower": 0,  "upper": 0,    "points": 10 },
      { "lower": 1,  "upper": 6,    "points": 7  },
      { "lower": 7,  "upper": 13,   "points": 4  },
      { "lower": 14, "upper": 20,   "points": 1  },
      { "lower": 21, "upper": 27,   "points": 0  },
      { "lower": 28, "upper": 34,   "points": -1 },
      { "lower": 35, "upper": null, "points": -4 } ] },
    { "stat": "dst_yards_allowed", "brackets": [
      { "lower": 0,   "upper": 99,   "points": 5 },
      { "lower": 100, "upper": 199,  "points": 3 },
      { "lower": 200, "upper": 299,  "points": 2 },
      { "lower": 300, "upper": 349,  "points": 0 },
      { "lower": 350, "upper": 399,  "points": -1 },
      { "lower": 400, "upper": null, "points": -3 } ] }
  ],
  "scoring_bonuses": [
    { "stat": "field_goal_distance", "threshold": 50, "points": 2 }
  ],
  "draft_order": null,
  "keeper": false,
  "dynasty": false,
  "raw": {}
}
```

> **Immutable league constitution (verbatim — `config/league.json`, `immutable:true`).** The object
> above reproduces, and MUST byte-for-byte match, these owner-provided settings — never paraphrased,
> re-ordered, or "optimized":
> **Draft Type: Snake · Teams: 12 · Draft Order: Decided in-person, then entered into CBS Sports
> system · Scoring Format: Standard · Draft Rounds: 17 · Roster Slots per Team: QB = 1, RB = 1,
> WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8.**
> The `WR/RB` flex is **WR-or-RB only** (no TE/QB). `draft_order` stays `null` until read live from
> the CBS room — **never** inferred from `team_count`. Per the `agent_usage_contract`, this endpoint
> surfaces conflicts (never silently changes them).

`scoring` shows a **representative subset** (rushing/receiving) and is overwritten by the live CBS
map at parse time (Standard = non-PPR → `reception: 0.0`); the full linear map (passing yards/TD,
interceptions, fumbles, returns, 2-pt, etc.) **plus** the DST dual tiers and K 50+ bonus are
populated verbatim from the live CBS scoring page — exactly the CBS-"standard" facts that scaffold
change #1 exists to represent (§7.B B3). Confirm precise yardage/TD/turnover/K/DST values from CBS
before relying on them (`config/league.json` `scoring_note`). Errors: unknown `league_id` → **404**
(§8.7).

#### 8.3.3 GET `/recommendation` → `RecommendationSchema`

Returns the current decomposed recommendation. In v1 the engine loads the folded `DraftState` and
`LeagueSettings` from the warehouse and calls `jaaffl.engine.recommend(DraftContext, state)`
(§7.C.5); the hot path is the stateless per-pick `recompute()` (§7.D — target **<2 s**, analytic
**<200 ms**). This route is the pull equivalent of the `/recs/ws` push; both emit the identical
`Recommendation`.

| Param | In | Type | Req | Default | Notes |
|---|---|---|---|---|---|
| `league_id` | query | string | yes | — | 404 if unknown |
| `as_of_overall_pick` | query | int ≥1 | no | current folded pick | audit a past pick; 409 if draft not started |
| `team_id` | query | string | no | `DraftState.my_team_id` | whose lineup MLV is computed against (this roster) |
| `limit` | query | int 1–50 | no | 5 | ranked entries returned (overlay wants best + top-5); engine still scores up to `candidate_cap≈180` internally |
| `include_components` | query | bool | no | `true` | set `false` to omit `ScoreComponents` (smaller payload) |
| `mc` | query | bool | no | `false` | opt-in Monte-Carlo VONA refinement (§7.C.5, `mc_rollouts≈2000`); analytic Gaussian survival is the v1 default (MC is a refinement/stretch) |

```json
// GET /recommendation?league_id=cbs-1029384&limit=2  → 200 OK  (validates against RecommendationSchema)
{
  "league_id": "cbs-1029384",
  "as_of_overall_pick": 5,
  "ranked": [
    {
      "player_id": "jaaffl:00-0036223",
      "score": 42.1,
      "projected_points": 268.4,
      "vorp": 62.1,
      "adp": 6.4,
      "next_turn_availability": 0.18,
      "tier": 1,
      "rationale": "Last elite anchor-RB tier before the cliff; low survival to your R2 turn.",
      "components": {
        "mlv": 33.7, "vona": 12.5, "risk_penalty": 2.1, "cliff_bonus": 3.4,
        "sigma": 41.0, "floor": 214.0, "ceiling": 322.0, "replacement_baseline": 118.6,
        "modifiers": { "handcuff_synergy": 0.0, "bye_stack": -0.4 }
      }
    },
    {
      "player_id": "jaaffl:00-0037845",
      "score": 39.4,
      "projected_points": 254.0,
      "vorp": 47.7,
      "adp": 7.1,
      "next_turn_availability": 0.44,
      "tier": 1,
      "rationale": "Elite WR; higher survival — VONA says you can wait one turn.",
      "components": {
        "mlv": 34.9, "vona": 6.2, "risk_penalty": 1.8, "cliff_bonus": 2.6,
        "sigma": 33.5, "floor": 205.0, "ceiling": 300.0, "replacement_baseline": 96.2,
        "modifiers": {}
      }
    }
  ],
  "reasoning": "R1P5 · floor-tilt λ=+0.3 · κ=0.6 · α=0.4 · flex_split=8RB/4WR (EngineParams v1.0.0; flex MEASURED live via top-60, may skew RB-heavy in non-PPR). Anchor-RB: RB scarcity (VONA 12.5) + tier cliff outweigh the WR's slightly higher MLV."
}
```

Both entries satisfy the §8.2 identity at κ=0.6: pick 1 = `33.7 + 0.6·12.5 − 2.1 + 3.4 + (−0.4) =
42.1`; pick 2 = `34.9 + 0.6·6.2 − 1.8 + 2.6 + 0 = 39.4`. `reasoning` carries the resolved
`EngineParams` (κ, λ for this phase/slot, α, flex split, params version) so any consumer can
reconstruct `score` from `components`. **`flex_split` is measured live pre-draft via the top-60
method** (rank RB+WR by non-PPR 12-team FFC ADP; `flex_RB = (#RB in top-60) − 12`, `flex_WR = (#WR
in top-60) − 36`; design §7.E1/§10.3), defaulting to 8 RB / 4 WR. Errors: unknown `league_id` →
**404**; draft not yet started (no state folded) → **409**; engine/precompute not ready → **503**
(pre-Stage-5 the current stub returns **501** "engine not yet implemented" until `recommend` lands —
`app.py:61`). See §8.7.

#### 8.3.4 POST `/draft/events` → ingest ack (`DraftEventSchema`)

HTTP fallback for a single normalized event (manual-paste path; tests). Same body and same
append-log→fold→recommend→broadcast pipeline as `/draft/ws` (§8.4), just one event per request.

```json
// POST /draft/events   Content-Type: application/json   (body validates against DraftEventSchema)
{
  "event_type": "pick_made",
  "league_id": "cbs-1029384",
  "pick_number": 4,
  "source": "ws",
  "data": { "overall": 4, "round": 1, "pick_in_round": 4, "team_id": "t4", "player_id": "jaaffl:00-0034796" }
}
```

```json
// 200 OK
{ "accepted": true, "seq": 4, "pick_number": 4 }
```

`seq` is the monotonic append-log sequence assigned by `ingest/log.py` (§7.C.4). **[EXISTS]** today
the handler returns `{accepted:true}` only; `seq`/`pick_number` land with `ingest/log.py` (Stage 1).
Re-POSTing the same `pick_number` is idempotent (deduped server-side against the log's unique
`pick_number`) and returns the existing `seq`. Malformed body → **422** (§8.7).

### 8.4 WebSocket `/draft/ws` (ingest: extension → backend)

Owned by the **ISOLATED-world content script** (`apps/extension/src/content/cbs-draft.content.ts`),
never the service worker, so the socket survives MV3 SW eviction (§7.C.2; risk "MV3 SW lifecycle").

**Handshake.** Standard WS upgrade to `ws://127.0.0.1:8787/draft/ws`. No subprotocol required;
clients MAY offer `Sec-WebSocket-Protocol: jaaffl.v1` and the server echoes it when present. The
server SHOULD validate the `Origin` header (allow `chrome-extension://*` and
`http://localhost:3000`) and close with **1008** otherwise (§8.9). On accept the server logs
`draft_ws_connected` (see `app.py:48`).

**Client → server frames** (text JSON, discriminated by `type`; a frame with no recognized control
`type` is parsed as a **bare `DraftEvent`**, preserving the current `app.py` behavior at line 51–52):

```json
{ "type": "event", "v": 1, "ts": "2026-08-30T18:04:11Z",
  "event": {
    "event_type": "pick_made", "league_id": "cbs-1029384", "pick_number": 5, "source": "framework",
    "data": { "overall": 5, "round": 1, "pick_in_round": 5, "team_id": "t5", "player_id": "jaaffl:00-0036223" }
  } }
{ "type": "pong", "v": 1 }
```

**Server → client frames:**

```json
{ "type": "ack",  "v": 1, "seq": 5, "pick_number": 5, "accepted": true }
{ "type": "ping", "v": 1, "ts": "2026-08-30T18:04:20Z" }
{ "type": "error","v": 1, "code": 4422, "detail": "DraftEvent validation failed", "errors": [ /* §8.7 */ ] }
```

**Ingest pipeline (per accepted event, §7.C.6 / §7 Step 7):**
1. Validate the frame's `event` against `DraftEvent` (`DraftEvent.model_validate`).
2. **Append to the SQLite append-only log first** (`ingest/log.py`: monotonic `seq`, unique
   `pick_number`) — this is the durability point; a crash after this replays exactly. (Design §7
   Step 7: **SQLite** = ACID app state + append-only draft-event log; **DuckDB**/**Parquet** hold
   analytics/backtest + nflverse snapshots and are **not** on the ingest hot path.)
3. `fold_state()` re-derives `DraftState` as a **fold over the log** (crash-safe replay).
4. On a state-advancing event (`pick_made`, `on_the_clock`, `draft_state`), call
   `jaaffl.engine.recommend(DraftContext, state)`; `draft_complete` finalizes the log and emits a
   terminal recommendation/no-op.
5. **Broadcast** the resulting `Recommendation` to all `/recs/ws` subscribers of that `league_id`
   (§8.5).
6. Send `ack` back on `/draft/ws`. (Today `handle_event` is an observable no-op and the socket
   replies `{"accepted": true}`; steps 2–5 land across Stages 1–5.)

**De-dup.** By `pick_number` at step 2 — the **three capture probes** (§7.C.2: MAIN-world
WS/fetch/XHR monkeypatch at `document_start`; React-fiber read; `MutationObserver` DOM fallback) may
each emit the same pick. Duplicates are acked idempotently and do **not** re-trigger a broadcast.

**Heartbeat.** Server sends `{"type":"ping"}` every **15 s**; client replies `{"type":"pong"}` (and
vice-versa if the client pings). Two consecutive missed pongs → server closes **1011** and the
content script reconnects.

**Reconnect / resume.** Exponential backoff **250 ms → 500 → 1 s → 2 s → 5 s cap**, ±20 % jitter. On
reconnect the extension re-sends any events it has not seen an `ack` for; server-side `pick_number`
de-dup makes replay safe (at-least-once client, idempotent server → effectively-once).

**Back-pressure.** Ingest is low-rate (≤ ~1 pick/few-seconds) so the receive side is bounded by a
small per-connection queue; if a client floods, the server stops reading and lets TCP back-pressure
apply, and closes **1013** if the queue exceeds a cap. The heavy direction is push (`/recs/ws`),
handled in §8.5.

### 8.5 WebSocket `/recs/ws` (push: backend → overlay + dashboard)

New channel (**B9**, §7.C.6; **scaffold change #4** — *keep* `/draft/ws` ingest + REST). Consumers:
the overlay (`apps/extension/src/overlay/overlay.ts`, subscribes and renders best pick + top-5 +
`components` + survival %) and the web dashboard (§7.C.7).

**Handshake.** WS upgrade to `ws://127.0.0.1:8787/recs/ws`. Same optional `jaaffl.v1` subprotocol
and Origin check as §8.4. Immediately after accept, the server sends a `hello`, then a `snapshot` of
the current best `Recommendation` (so a late-joining overlay is correct without waiting for the next
pick):

```json
{ "type": "hello", "v": 1, "server_version": "0.0.0", "schema_version": "1.0.0" }
{ "type": "snapshot", "v": 1, "recommendation": { /* full Recommendation, §8.3.3 */ } }
```

**Client → server frames** (optional): scope the subscription to a league and answer pings.

```json
{ "type": "subscribe", "v": 1, "league_id": "cbs-1029384" }
{ "type": "pong", "v": 1 }
```

If no `subscribe` is sent, the client receives recommendations for the single active league.

**Server → client frames.** One `rec` per new pick, plus heartbeat:

```json
{ "type": "rec",  "v": 1, "recommendation": { /* full Recommendation, validates RecommendationSchema */ } }
{ "type": "ping", "v": 1, "ts": "2026-08-30T18:04:20Z" }
```

**Heartbeat / reconnect.** Identical policy to §8.4 (15 s ping, 2-missed close, 250 ms→5 s jittered
backoff). On reconnect the server re-sends `hello` + `snapshot`, so no rec is ever lost across a drop
— the overlay resynchronizes from the current state rather than replaying a stream.

**Back-pressure (the channel that needs it).** `Recommendation`s are **idempotent snapshots** keyed
by `as_of_overall_pick`; only the latest matters. Each subscriber therefore has an outbound queue of
**size 1 that coalesces to the newest** `Recommendation` — if a slow overlay hasn't drained the
previous frame, it is overwritten, never buffered. If even the single-slot send stalls past a
timeout, the server drops that subscriber with close **1013** ("try again later") and relies on the
client's reconnect+resync. Dropping stale recs is always safe because the newest snapshot fully
supersedes older ones.

### 8.6 Shared WebSocket envelope & close codes

Both channels use **text JSON** frames with a common envelope: a `type` discriminator, an integer
protocol version `v` (currently `1`), and — for control frames — an ISO-8601 `ts`. Domain payloads
ride under a named key (`event`, `recommendation`) so heartbeat/control frames never collide with
schema payloads. Close codes:

| Code | Meaning | Sender |
|---|---|---|
| 1000 | normal closure | either |
| 1001 | going away (tab/overlay closed, SW teardown) | client |
| 1008 | policy violation (bad `Origin` / unknown protocol version) | server |
| 1011 | internal error / heartbeat timeout | server |
| 1013 | try again later (back-pressure shed) | server |
| 4400 | malformed/undecodable frame | server |
| 4404 | unknown `league_id` on `subscribe` | server |
| 4409 | draft not started | server |
| 4422 | schema validation failed (`DraftEvent`) | server |

The 44xx codes mirror the REST status codes in §8.7 so the same error taxonomy applies on both
transports.

### 8.7 Error model

REST validation uses FastAPI's default 422 (Pydantic v2 error list); application errors are
`HTTPException` with a stable `detail` string and a machine-readable `code`.

| Condition | REST status | WS close/error code | Body `detail` |
|---|---|---|---|
| Body/query fails schema | **422** | 4422 | Pydantic error array (below) |
| Unknown `league_id` | **404** | 4404 | `unknown league 'cbs-x'` |
| Draft not started (no folded state) | **409** | 4409 | `draft not started for league 'cbs-x'` |
| Engine/precompute not ready | **503** | 1011 | `engine warming up` |
| Engine not yet implemented (pre-Stage 5) | **501** | — | `engine not yet implemented (roadmap stage 5)` |
| Malformed WS frame | — | 4400 | `undecodable frame` |

```json
// 422 Unprocessable Entity — GET /recommendation  (missing required league_id)
{ "detail": [
  { "type": "missing", "loc": ["query", "league_id"], "msg": "Field required", "input": null }
] }
```

```json
// 404 Not Found — GET /league/cbs-does-not-exist
{ "detail": "unknown league 'cbs-does-not-exist'", "code": "unknown_league" }
```

```json
// WS /draft/ws — invalid DraftEvent frame
{ "type": "error", "v": 1, "code": 4422, "detail": "DraftEvent validation failed",
  "errors": [ { "type": "enum", "loc": ["event_type"], "msg": "Input should be 'league_settings','draft_state','on_the_clock','pick_made' or 'draft_complete'" } ] }
```

WS validation errors are **non-fatal**: the server emits a `type:"error"` frame and keeps the socket
open (a single bad capture frame must not tear down a live-draft ingest session). Fatal conditions
(bad origin, back-pressure, internal error) close with the codes in §8.6.

### 8.8 Versioning & compatibility

- **Schema version.** A single `SCHEMA_VERSION` constant tracks the `@jaaffl/shared` package semver;
  exported from `packages/shared/src/index.ts` and mirrored on the Python side. It is surfaced in
  `GET /health.schema_version`, the `/recs/ws` `hello`, and the response header
  **`X-JAAFFL-Schema-Version`** on every REST response.
- **WS protocol version.** The integer `v` in every WS envelope. `v:1` for this contract. A client
  MAY negotiate via the `jaaffl.vN` subprotocol; unknown versions → close **1008**.
- **Compatibility policy.** Additive-only within a major (`v1` / `1.x`): new optional fields and new
  `modifiers.*` keys are non-breaking; consumers MUST ignore unknown fields. Removing/renaming a
  field or changing a type is a major bump and ships behind a parallel path (`/v2/...`, `jaaffl.v2`),
  never an in-place mutation. URLs stay unversioned on loopback; the version travels in the header
  and envelope.

### 8.9 Localhost-only, CORS & compliance posture

- **Bind.** The service binds `settings.jaaffl_api_host = "127.0.0.1"`, `jaaffl_api_port = 8787`
  (`config.py`). It is never exposed off the loopback interface (ADR 0002/0003, local-first).
- **CORS.** `CORSMiddleware` with `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`
  (`app.py:27–32`). This is acceptable **because** the socket is loopback-bound and carries **no
  credentials and no auth token** — a remote origin cannot reach `127.0.0.1:8787` from another
  machine, and there is nothing to steal via CSRF (single local user). Optional hardening (does not
  change v1 behavior): pin `allow_origins` to `["chrome-extension://<the-JAAFFL-id>",
  "http://localhost:3000"]` once the packed extension id is known.
- **WS origin.** WebSockets bypass CORS, so both channels SHOULD check the `Origin` header and close
  **1008** for anything other than `chrome-extension://*` / `http://localhost:3000` (§8.4/§8.5). This
  is the only network-facing guard and is cheap; it is recommended for v1.
- **No authentication** is a deliberate decision (loopback + single user, ADR 0003). Do not add
  tokens/keys; do not widen the bind address.
- **Compliance & honesty (ADR 0003, `docs/legal-and-compliance.md`).** This wire surface serves a
  **personal, non-commercial, local-first** assistant over the user's **own authenticated CBS
  session**; **$0 out-of-pocket besides AI usage** (free `$0` data tier — nflreadpy + FFC + CBS
  on-page; paid providers off by default); the assistant is **text-only** (no voice/Realtime).
  There is **no peer-reviewed optimal live-snake-draft solver** — the recommendations these contracts
  carry are validated by the project's **own offline simulated-league tournament vs VBD-only and
  ADP-only baselines** (design §7.E6), not by vendor claims. Forward-year (2027) projections that
  ride in `ScoreComponents`/`Recommendation` are treated as **ESTIMATED**.

### 8.10 Schema-parity CI (keeps Zod ⇄ Pydantic in sync)

Realizes decision **B13** (and calibration/testing item **E5**). The four named schemas plus
`ScoreComponentsSchema`, `RecommendedPickSchema`, `ScoringTierSchema`, and `ScoringBonusSchema` have
exactly one source of truth (Zod) and a hand-mirrored Pydantic twin; CI proves they cannot drift:

1. **Fixtures.** `packages/shared` ships canonical example JSON (§7.C.1 `[N]`) — one per schema,
   e.g. the payloads in §8.3.2/§8.3.3/§8.3.4 above.
2. **JS side** (`ci.yml` **`js`** job, `pnpm -r typecheck` + `pnpm -r test`, Vitest): each fixture
   must `SCHEMA.parse(fixture)` successfully and round-trip (`parse` → serialize → `parse`) to an
   equal value.
3. **Python side** (`ci.yml` **`backend`** job, `pytest`): the same fixtures must validate against
   the Pydantic model (`Model.model_validate(fixture)`), and `Model.model_json_schema()` is compared
   field-by-field (name, type, required, enum members) against the Zod-derived JSON Schema
   (`zod-to-json-schema`) with a tolerance list for known representational differences (e.g. Pydantic
   `X | None = None` ⇄ Zod `.nullable().optional()`).
4. A drift (field added on one side only, type mismatch, enum divergence, optionality mismatch such
   as `components`) fails CI on both jobs.

### 8.11 Acceptance criteria

- `GET /health` returns `{status:"ok", version, schema_version}` (`version` = `jaaffl.__version__`)
  and header `X-JAAFFL-Schema-Version`.
- `GET /league/{league_id}` returns a `LeagueSettings` that validates against `LeagueSettingsSchema`
  **including** `scoring_tiers` (DST points- **and** yards-allowed) and `scoring_bonuses` (K 50+),
  and reproduces the **immutable constitution verbatim**: `team_count:12`, `draft_type:"snake"`,
  roster **QB=1, RB=1, WR=3, WR/RB=1, TE=1, K=1, DST=1, Bench=8** with the `WR/RB` flex eligible for
  **WR or RB only**, and `draft_order:null` (never inferred from `team_count`); unknown league → 404.
- `GET /recommendation` returns a `Recommendation` validating `RecommendationSchema`; when
  `include_components=true` (default) each `ranked[i]` carries a `components` object validating
  `ScoreComponentsSchema` with `score == mlv + κ·max(0,vona) − risk_penalty + cliff_bonus + Σ
  modifiers` to within float tolerance (κ from `reasoning`); `replacement_baseline` reflects this
  roster's canonical index (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13); honors `league_id`,
  `as_of_overall_pick`, `team_id`, `limit`, `include_components`, `mc`; 404 / 409 / 503 per §8.7.
- `POST /draft/events` and `WS /draft/ws` accept a `DraftEvent` (with `pick_number`/`source`), append
  to the SQLite log **before** engine work, fold state, and (on state-advancing events) broadcast a
  `Recommendation` on `/recs/ws`; duplicate `pick_number` is idempotent.
- `WS /recs/ws` sends `hello`+`snapshot` on connect and one coalesced `rec` per pick; both channels
  implement the §8.6 heartbeat, reconnect-with-resync, and back-pressure (single-slot latest-wins on
  push).
- Error taxonomy (§8.7), close codes (§8.6), versioning headers (§8.8), and loopback/CORS/compliance
  posture (§8.9) are exactly as specified.
- Schema-parity CI (§8.10) passes on all fixtures for `DraftEventSchema`, `LeagueSettingsSchema`,
  `RecommendationSchema`, `ScoreComponentsSchema` (including `components` optionality parity).

### 8.12 Definition of done

- [ ] `packages/shared/src/recommendation.ts` exports `ScoreComponentsSchema` and embeds an optional
      `components` (`.nullable().optional()`) on `RecommendedPickSchema`; `league.ts` exports
      `ScoringTierSchema` + `ScoringBonusSchema` and adds `scoring_tiers`/`scoring_bonuses`;
      `events.ts` adds `pick_number` (required on capture events) + optional `source`.
- [ ] `domain/models.py` mirrors all of the above (identical field names, order, optionality;
      `components: ScoreComponents | None = None`).
- [ ] `api/app.py`: `GET /league/{league_id}` and `WS /recs/ws` (scaffold change #4) added; `GET
      /health` returns `schema_version`; `/draft/ws` upgraded to the typed envelope + heartbeat while
      still accepting a bare `DraftEvent`; `/recommendation` wired to `engine.recommend` (Stage 5)
      with the §8.3.3 query params.
- [ ] `ingest/log.py` append-before-recommend implemented; `handle_event` folds state (`fold_state`)
      and triggers a `/recs/ws` broadcast; `pick_number` de-dup verified.
- [ ] Origin check + close-code handling implemented on both WS channels; back-pressure = single-slot
      latest-wins on `/recs/ws`; reconnect-with-`hello`+`snapshot` verified.
- [ ] `X-JAAFFL-Schema-Version` header emitted; `SCHEMA_VERSION` exported from
      `packages/shared/src/index.ts`.
- [ ] Canonical fixtures added; schema-parity job green in `.github/workflows/ci.yml` (both `backend`
      and `js`).
- [ ] Every JSON example in §8.3–§8.5 validates against its named schema in an automated test, and
      each `components` example satisfies the §8.2 score-reconstruction identity.
- [ ] `ruff check` + `ruff format --check` + `pytest` and `pnpm -r typecheck` + `pnpm -r test` pass.

---

## 9. Calibration, testing & evaluation

This section operationalizes design §7.E (rows E1–E7) and the canonical spec of design §10.3 into an execution-ready calibration + test + evaluation plan. Every item names a concrete script or test path, the exact method, and a binary **pass/fail gate**. The through-line: calibration jobs (E1–E3) *write* the versioned engine parameters into `config/engine.json`; regression/parity/latency gates (E4, E5, E7) run in CI on every PR; the efficacy gate (E6) is the project's own offline proof that the engine beats VBD-only and ADP-only baselines — no such benchmark exists in the literature (design §4.C: "there is no published, peer-reviewed, empirically-validated optimal live snake-draft solver"; §10.6 item 7), so we build it.

**Immutable frame (every gate computes against this — design §2 / `config/league.json`, `immutable:true`).** Draft Type **Snake**; **12** teams; Draft Order **decided in-person, then entered into CBS Sports** (read live from the room, **never inferred from team count**); Scoring **Standard (non-PPR)**; **17** rounds; Roster Slots per Team **QB=1, RB=1, WR=3, WR/RB=1, TE=1, K=1, DST=1, Bench=8** (9 starters + 8 bench); the **WR/RB flex is WR-or-RB only** (no TE/QB). League-wide startable RB+WR pool = 12 RB + 36 WR + 12 flex = **60** (of 108 total starters). No gate paraphrases, re-orders, or "optimizes" these values.

**The object under calibration — the canonical score (design §10.3 / §6.C.7, verbatim).**
```
Score(p) =  MLV_p                        # flex-aware Marginal Lineup Value (Hungarian over the 9 starting slots)
          + κ · max(0, VONA_p)           # scarcity/opportunity-cost urgency from ADP survival
          − λ(phase, slot) · σ̂_p         # risk: floor-tilt (λ>0) for starters, ceiling-tilt (λ<0) for bench
          + α · CliffBonus_p             # tier-cliff urgency (Boris-Chen GMM on ECR)
          + Σ capped modifiers           # bye-stack −, handcuff-synergy +, SOS tiebreak ± (each ≤ ~3–5 pts)
```
Each E-job calibrates one part of this expression: **E1** measures the flex split → sets the RB/WR `replacement_baselines` that feed `MLV_p`; **E2** tunes `κ, α`, the `λ` schedule, and the modifier caps; **E3** calibrates `σ̂_p` (and the floor/ceiling that depend on it) so the risk term is honest; **E6** proves the *assembled* score beats the baselines; **E7** proves it computes inside the **<2 s/pick** budget (analytic path target **<200 ms**). `MLV_p` is the flex-aware marginal gain to the optimal 9-starter lineup via `scipy.optimize.linear_sum_assignment` with a WR/RB flex mask; `VONA_p` uses the analytic Gaussian survival `S_j(N) = 1 − Φ((N − m_j)/s_j)` from FFC ADP mean `m_j` + stdev `s_j` (Monte-Carlo VONA is a stretch refinement).

**Honesty carried forward (design §7.G, §10.6).** The **flex split is measured, not assumed** (likely more RB-heavy than 8/4 in non-PPR — §6.C.2, §6.E, §10.3); the **CBS draft-room transport is UNVERIFIED** (§5.B), so E4 fixtures are synthetic + manual-paste until real frames are captured; the **nflreadpy ID-crosswalk function name is `[VERIFY]`** (`load_ff_playerids`/`load_players` — §10.6 item 4), covered by the fuzzy name+team+pos fallback; any **forward-year (2027) projection is labeled ESTIMATED** (§7.G, §10.4).

**Compliance invariants (design §10.7, ADR 0003, `docs/legal-and-compliance.md`).** The entire harness is **offline/local-first** and **network-free in CI** (frozen fixtures only). It uses the **$0 data tier**: nflverse via `nflreadpy`, FFC ADP (free for personal **and** commercial use; polled no faster than daily), and the user's **own authenticated CBS on-page snapshot** read from the warehouse — never a live CBS scrape. Paid providers (FantasyPros, SportsDataIO, Sportradar) stay disabled stubs. **$0 beyond AI usage; text-only (no voice/Realtime).**

### 9.0 Map, harness layout & the `EngineParams` contract

| ID | What it calibrates / tests | Script / test path | Gate kind | v1 / stretch | Design ref |
|----|-----------------------------|--------------------|-----------|--------------|------------|
| E1 | Flex RB/WR split → baselines | `scripts/calibrate_flex_split.py` · `backend/tests/test_flex_split.py` | Fixture unit + invariant | v1 | §6.C.2, §6.E, §10.3 |
| E2 | κ, λ-table, α, caps, β, vona_horizon, reliability, situation (§3.10) | `scripts/tune_engine_params.py` · `backend/tests/test_engine_params.py` | Offline study + artifact validation | v1 (str: season-wins objective) | §7.E2, §6.C.5–7, §3.10 |
| E3 | Projection blend + σ + reliability-shrinkage + situation caps (§3.10) | `scripts/validate_projections.py` · `backend/tests/test_projections.py` | Fixture metric thresholds; opportunity-μ beats prior-year extrapolation on team/role changes | v1 (str: XGBoost/PWOPR) | §6.C.1, §7.E3, §3.10 |
| E4 | Capture, ingest, replay & `/recs/ws` push | `apps/extension/tests/**` · `backend/tests/test_ingest_replay.py` | Golden-fixture regression + e2e | v1 | §5.B, §7.C, §7.E4, §7.F St.1/6 |
| E5 | Pydantic ⇄ Zod schema parity | `scripts/export_schemas.py` · `backend/tests/test_schema_parity.py` · `packages/shared/tests/parity.test.ts` | Round-trip divergence | v1 | §7.B, §7.E5, §10.5 |
| E6 | Efficacy vs ADP-only + VBD-only | `scripts/run_tournament.py` · `backend/tests/test_tournament.py` | Significance across 12 slots | v1 core (str: MC odds) | §4.C, §7.E6, §10.6 |
| E7 | `recompute()` p95 latency | `scripts/bench_recompute.py` · `backend/tests/test_latency.py` | p95 < 2 s perf gate | v1 | §7.D, §7.E7 |

**Directory conventions (create these).**

```
scripts/                         # runnable calibration/eval entrypoints (argparse; python -m scripts.<name>)
  calibrate_flex_split.py  tune_engine_params.py  validate_projections.py
  run_tournament.py  bench_recompute.py  export_schemas.py
backend/tests/fixtures/          # frozen inputs for CI (FFC ADP sample, realized-pts sample, golden boards)
  ffc_adp_standard_12_2026.json  realized_points_2021_2024.parquet  engine_params_baseline.json
packages/shared/fixtures/        # canonical cross-language payloads (E5): one *.json per contract model
packages/shared/schemas/         # generated JSON Schema from Pydantic (E5 output; checked in)
apps/extension/tests/            # Vitest units + Playwright e2e
  fixtures/                      # captured/synthetic frames + saved draft-room HTML
  parse.test.ts  dedup.test.ts  e2e/mutation-observer.spec.ts  manual-paste.test.ts
```

**Data stores in the harness (design §7 DATA STORES / §7.F St.3).** Backtests (E2/E3/E6) read **nflverse snapshots from Parquet** and run analytics/aggregation in **DuckDB**, both accessed through `jaaffl.data.warehouse.Warehouse` (`init`, `snapshot_league`, `snapshot_draft_state`). Live app/league state and the **append-only draft-event log** live in **SQLite**; E4's replay test folds that log. Frozen fixtures mirror these formats so CI never touches the live stores or the network.

**Determinism.** Every stochastic script accepts `--seed` (default `1729`) and pins `numpy.random.default_rng(seed)`; Optuna uses `TPESampler(seed=...)`. Fixtures are frozen so CI is network-free and reproducible; the live daily jobs (E1 re-measure, E2 pre-draft tune) run offline via `make` targets, and CI only validates their committed artifacts + a tiny smoke study.

**New pytest markers** (add to `backend/pyproject.toml` `[tool.pytest.ini_options]`):

```toml
markers = [
  "perf: latency gate (E7); may be slow",
  "parity: schema round-trip (E5)",
  "slow: full backtests; excluded from default PR run",
  "stretch: MC season-simulator objective (E2/E6 stretch); off by default",
]
```

**Dependency changes (real extras only — no invented `calib` extra).** Scaffold change #2 revises the existing `[data]` extra: **drop `nfl_data_py` + `pandas`, add `nflreadpy>=0.1` + `polars>=1.0`** (Provider return type pandas → polars). The existing `[engine]` extra (`numpy, scipy, ortools, xgboost, optuna`) **gains `scikit-learn>=1.4`** for the Boris-Chen GMM cliff tiers (`sklearn.mixture.GaussianMixture`). `[dev]` **gains `pytest-benchmark>=4.0`** (E7 offline profiling). E4's Playwright job adds `@playwright/test` + `vitest` to `apps/extension` devDependencies. CI installs `.[dev,data,engine]`.

**The `EngineParams` contract (E1/E2 write it, `recompute()` reads it).** New model `jaaffl.config.EngineParams` (+ nested `FlexSplit`, `LambdaBand`) serialized to `config/engine.json` — a NEW, **mutable** file, unlike immutable `config/league.json`. It is the single source of truth every calibration job updates and every hot-path `recompute()` loads.

```jsonc
// config/engine.json — versioned EngineParams (design §10.3 canonical defaults shown)
{
  "version": 1,
  "calibrated_at": "2026-08-24T00:00:00Z",
  "seed": 1729,
  "kappa": 0.65,                         // VONA weight, tunable 0.5–0.8
  "alpha": 0.40,                         // cliff-bonus weight, tunable 0.3–0.5
  "flex_split": { "rb": 8, "wr": 4 },    // DEFAULT; MEASURED by E1 (top-60). rb+wr MUST == 12
  "replacement_baselines": {             // derived from flex_split via the §6.C.2 man-games/VOLS blend
    "RB": 23, "WR": 41, "QB": 13, "TE": 13, "K": 13, "DST": 13 },   // RB≈22–24 / WR≈40–42 / others≈13
  "lambda_schedule": [                   // phase → [lo, hi]; slot override dominates at runtime (§6.C.5)
    { "rounds": [1, 2],   "lo":  0.2, "hi":  0.4 },
    { "rounds": [3, 6],   "lo":  0.1, "hi":  0.3 },
    { "rounds": [7, 9],   "lo":  0.0, "hi":  0.0 },
    { "rounds": [10, 13], "lo": -0.4, "hi": -0.2 },
    { "rounds": [14, 17], "lo": -0.5, "hi": -0.3 } ],
  "modifier_caps": { "bye_stack": 3.0, "handcuff_synergy": 3.0, "sos_tiebreak": 2.0 }, // each ≤ ~3–5 pts
  "projection_blend": { "method": "simple_average", "weights": null, "mu_refinement_cap": 0.15 }, // ±10–15%
  "candidate_cap": 180,
  "mc_rollouts": 2000,
  "provenance": { "study": null, "n_trials": null, "opponent_mix": null, "evaluated_seasons": null,
                  "flex_source": null, "sigma_rescale": null }
}
```

Field-level invariants enforced by `EngineParams` validators (and re-asserted in every gate that writes the file): `flex_split.rb + flex_split.wr == 12` and both `>= 0`; `0.0 < kappa`; `0.0 < modifier_caps.* <= 5.0`; `lambda_schedule` covers rounds 1–17 with no gaps or overlaps; band signs match schedule direction (early bands `lo,hi ≥ 0`; R7–9 `== 0`; late bands `lo,hi ≤ 0`); every `replacement_baselines` value `> 0`.

---

### 9.1 E1 — Flex-split measurement (the top-60 method)

**Script.** `scripts/calibrate_flex_split.py` (run daily pre-draft via `make calibrate-flex`; the measurement is a pure function unit-tested in CI).

**Method (design §10.3 "canonical flex-split measurement", §6.C.2, §6.E).** Pull non-PPR 12-team ADP from `FantasyFootballCalculatorProvider.adp(season)` (new provider module `providers/ffc.py`; endpoint `GET https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year={season}`, cached daily; per-player `adp, stdev, high, low, times_drafted, bye, position`). Restrict to `RB ∪ WR`, rank ascending by `adp`, take the **top-60** (the startable RB/WR pool = 12 RB + 36 WR + 12 flex), and read the flex composition off the surplus over dedicated demand:

```python
# scripts/calibrate_flex_split.py
import polars as pl
from jaaffl.config import FlexSplit

DEDICATED_RB = 12                              # RB=1 dedicated starter × 12 teams
DEDICATED_WR = 36                              # WR=3 dedicated starters × 12 teams
FLEX_SLOTS   = 12                              # WR/RB=1 flex × 12 teams (WR-or-RB only)
POOL         = DEDICATED_RB + DEDICATED_WR + FLEX_SLOTS   # == 60 startable RB/WR (of 108 starters)

def measure_flex_split(adp: pl.DataFrame, *, pool: int = POOL) -> FlexSplit:
    rbwr = adp.filter(pl.col("position").is_in(["RB", "WR"])).sort("adp").head(pool)
    n_rb = rbwr.filter(pl.col("position") == "RB").height
    n_wr = rbwr.filter(pl.col("position") == "WR").height
    flex_rb = n_rb - DEDICATED_RB              # (#RB in top-60) − 12
    flex_wr = n_wr - DEDICATED_WR              # (#WR in top-60) − 36
    assert flex_rb >= 0 and flex_wr >= 0
    assert flex_rb + flex_wr == pool - (DEDICATED_RB + DEDICATED_WR) == FLEX_SLOTS   # 60 − 48 == 12
    return FlexSplit(rb=flex_rb, wr=flex_wr)
```

**Baseline derivation (do NOT equate the VOLS index with the stored baseline).** The measured split first yields the **VOLS startable indices** `RB_vols = 12 + flex_rb`, `WR_vols = 36 + flex_wr` (at the 8/4 default: RB20 / WR40). The **stored `replacement_baselines`** then apply the §6.C.2 **man-games/VOLS 0.5·/0.5· blend** — starters miss bye+injury games covered from the same pool, so effective replacement runs deeper — via `jaaffl.league.replacement.replacement_baselines(settings, split) -> dict[Position, int]`. For this roster that lands the canonical **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13** (12 dedicated per team + a shallow streaming cushion). `write_engine_params()` persists **both** `flex_split` and the derived `replacement_baselines` to `config/engine.json`. **Thin-board fallback** (design §7.G, §10.6 item 5): if `RB ∪ WR < 60` returned (off-season / FFC thins past ~180), complete the top-60 from `NflreadpyProvider.load_ff_rankings` (ECR) deep ranks and record `provenance.flex_source = "ffc+ecr"`.

**Honesty / UNVERIFIED.** Standard-scoring RB scarcity is expected to push this **more RB-heavy than the 8/4 default** (§6.E sensitivity: 6/6→RB18/WR42, 10/2→RB22/WR38) — measuring it is the single highest-value calibration (§10.6 item 1). Never hard-code 8/4 in code paths; always read `EngineParams.flex_split`.

**Pass/fail gate** — `backend/tests/test_flex_split.py` on frozen `fixtures/ffc_adp_standard_12_2026.json`:
- **PASS iff** (a) partition invariant `flex_rb + flex_wr == 12` and both `>= 0`; (b) determinism — same fixture → identical split on repeat; (c) monotonicity — a synthetically more RB-heavy ADP fixture yields a **stored `replacement_baselines["RB"]` no shallower** (numerically ≥) than the neutral fixture; (d) written `config/engine.json` re-validates against `EngineParams`. Any violation fails CI. (The *live* daily re-measure is not a CI gate — network + changes daily — only its pure function and the committed artifact are.)

- [ ] `FantasyFootballCalculatorProvider.adp(season)` returns Polars with `position, adp, stdev`.
- [ ] `measure_flex_split` + `league.replacement.replacement_baselines` + `write_engine_params()` implemented; `--dry-run` prints without writing.
- [ ] Frozen FFC fixture checked in; `test_flex_split.py` asserts (a)–(d).
- [ ] `make calibrate-flex` documented in `CONTRIBUTING.md` as a pre-draft daily step.

---

### 9.2 E2 — Tune κ, λ-table, α, caps (Optuna mock-draft backtest)

**Script.** `scripts/tune_engine_params.py` (offline, `make tune`; writes `config/engine.json`). Uses the `[engine]` extra (`optuna`, `scipy`, `scikit-learn`).

**Method (design §7.E2, §6.C.5–7, §10.6 item 2).** Optuna study, `direction="maximize"`, `TPESampler(seed)`. Each trial samples a parameter vector, runs `D` simulated snake drafts, and scores our final roster by **projected starting-lineup points** — the flex-aware optimal 9 via `engine.optimize.optimal_lineup_value(roster, ctx)` — averaged **across all 12 draft slots** to avoid slot-specific overfit. Sampling stays **inside the canonical tunable ranges** (design §10.3):

```python
# search space (design §10.3 canonical tunable ranges — do NOT widen past these)
kappa = trial.suggest_float("kappa", 0.5, 0.8)                     # VONA weight
alpha = trial.suggest_float("alpha", 0.3, 0.5)                     # cliff-bonus weight
lam   = [trial.suggest_float(f"lam_band{i}", lo, hi)              # one λ per phase, within its canonical band
         for i, (lo, hi) in enumerate(LAMBDA_BANDS)]              # [(0.2,0.4),(0.1,0.3),(0.0,0.0),(-0.4,-0.2),(-0.5,-0.3)]
caps  = trial.suggest_float("modifier_cap", 3.0, 5.0)             # ceiling on dominant modifiers (≤~3–5 pts)
# flex_split is fixed from E1 (with MC variance from FFC stdev), NOT re-tuned blindly; see cross-check below.
```

**Simulated slot sweep ≠ live order.** The per-slot sweep places our agent at each of the 12 slots in turn — a controlled experimental design. It does **not** infer the real draft order; the actual order is read live from the CBS room per the immutable settings.

**Opponent models (anti-self-reference — design §7.E2, §7.G "calibration overfits ADP opponents").** Our `ScoreAgent` (drafting by `Score(p)` under trial params) plays a **mix** of behavioral agents in `engine.simulate` — all implementing the `DraftAgent` protocol: (1) `AdpNoiseAgent` — `argmin adp + N(0, stdev)` from FFC; (2) `VbdOnlyAgent` — pure static VOR baseline (design §6.C.2, no VONA/risk/cliff); (3) `NeedBasedAgent` — fills empty starting slots first. Tuning uses `{AdpNoiseAgent, VbdOnlyAgent}`; **held-out evaluation** uses `{NeedBasedAgent}` + **held-out seasons** so the reported win is never measured on the training opponent.

**Flex-split cross-check (design §6.E "optimizer-implied").** E2 may recompute the optimizer-implied flex composition (tally optimal flex RB-vs-WR over simulated rosters) and **surface disagreement** with E1's ADP-implied `flex_split` in `provenance` — it never silently overrides E1.

**Objective.** `objective(trial) -> mean_starting_lineup_points` over `slots × seeds × opponent_mix`. **Stretch** (`--objective season-wins`, marked `stretch`): replace the static roster score with simulated-season wins / playoff odds from the Monte-Carlo season simulator (design §7.F Stage 5 stretch; CP-SAT end-state via OR-Tools — off the hot path).

**Output.** Best trial → `config/engine.json` with `provenance = {study, n_trials, seed, opponent_mix, evaluated_seasons}`.

**Pass/fail gate.** Two tiers:
- **Offline promotion gate** (`make tune`): the tuned vector must **beat the frozen §10.3 canonical defaults** (`fixtures/engine_params_baseline.json`) on **held-out** opponents *and* seasons — one-sided paired test across the 12 slots (Wilcoxon signed-rank, `p < 0.05`) **and** non-negative effect at every slot. If it does not, **keep the existing config** (`write_engine_params()` refuses to overwrite — no silent regression).
- **CI gate** — `backend/tests/test_engine_params.py`: the committed `config/engine.json` validates against `EngineParams` and satisfies all §9.0 invariants; a **smoke study** (`n_trials=5`, fixture opponents, seeded) runs deterministically to prove the harness wires end-to-end. The full study is offline (too slow for per-PR CI).

- [ ] `engine.simulate` exposes the `DraftAgent` protocol and `ScoreAgent`, `AdpNoiseAgent`, `VbdOnlyAgent`, `NeedBasedAgent`.
- [ ] `engine.simulate.simulate_draft(our_slot, our_agent, opponents, seed)` returns final rosters for all 12 teams.
- [ ] `engine.optimize.optimal_lineup_value(roster, ctx)` scores the flex-aware optimal 9 via `linear_sum_assignment` (design §6.C.3).
- [ ] Held-out opponent + season split enforced; promotion refuses to regress the baseline; flex-split cross-check surfaced in `provenance`.
- [ ] `test_engine_params.py` validates the artifact + runs the 5-trial smoke study.

---

### 9.3 E3 — Validate the projection blend & σ calibration

**Script.** `scripts/validate_projections.py` (`make validate-proj`; `[data]` extra for `nflreadpy`/`polars`). Historical stats via `NflreadpyProvider.load_player_stats` (Polars).

**Method (design §6.C.1, §7.E3, §10.6 item 3).** For seasons **2021–2024**, recompute each player's **realized** season points under the **exact CBS Standard map** (reception = 0 — non-PPR enforced here) using `recompute_realized(stats, scoring)`, a thin per-player-season wrapper over `jaaffl.league.scoring.league_points`. Compute the blended projection `μ_p = mean(sources)` (simple average — design §6.C.1) and each single source (CBS on-page snapshot via `CbsOnPageProvider`; ECR→pts from `load_ff_rankings`; xEP prior from `load_ff_opportunity`). Report per source **and** blend, **split by season**:

| Metric | Definition | Requirement |
|--------|------------|-------------|
| MAE | mean\|μ_p − realized_p\| | `MAE(blend) ≤ min_s MAE(source_s)` — blend ≥ best single source |
| RMSE | √mean(μ_p − realized_p)² | `RMSE(blend) ≤ min_s RMSE(source_s)` |
| Spearman ρ | rank corr(μ, realized) | `ρ(blend) ≥ max_s ρ(source_s) − 0.02` |
| σ coverage | frac(realized ∈ [f_p, c_p]), 80% band, z≈1.28 | coverage ∈ **[0.75, 0.85]** |

`f_p = μ_p − 1.28·σ_p`, `c_p = μ_p + 1.28·σ_p` (design §6.C.1). If coverage falls outside the band, the script rescales `σ_p` (recording the multiplier in `provenance.sigma_rescale`) so the 80% interval is honest — this is what makes the risk term `λ·σ̂_p` and the E7 `ScoreComponents.floor/ceiling` meaningful.

**Honesty / UNVERIFIED / stretch.** Backtest covers **realized 2021–2024 only**; forward-year (2027) outputs remain **ESTIMATED** (§7.G). `load_player_stats` is confirmed, but the ID-crosswalk fn (`load_ff_playerids`/`load_players`) is `[VERIFY]` (§10.6 item 4) — the fuzzy name+team+position fallback covers any miss. XGBoost residual projections are a **stretch** refinement evaluated by this same harness (marked `stretch`); v1 ships the simple-average blend.

**Pass/fail gate** — `backend/tests/test_projections.py` on frozen `fixtures/realized_points_2021_2024.parquet` (small representative sample per season):
- **PASS iff** the four requirements hold **for every season** (no season may regress). CI runs the fixture version; `make validate-proj` runs the full historical sweep offline.

- [ ] `recompute_realized(stats, scoring)` implemented over `league.scoring.league_points`; unit-tested against `test_domain.py::test_league_points_*`.
- [ ] Per-source + blend metrics table emitted (JSON + human summary); split by season.
- [ ] σ-rescale multiplier persisted into `projection_blend` provenance.
- [ ] Frozen parquet fixture checked in; `test_projections.py` asserts all four gates per season.

---

### 9.4 E4 — Capture-layer golden fixtures, Playwright, crash-safe replay & the `/recs/ws` push

**Scripts / tests.** `apps/extension/tests/{parse.test.ts,dedup.test.ts,manual-paste.test.ts}` (Vitest), `apps/extension/tests/e2e/mutation-observer.spec.ts` (Playwright), and `backend/tests/test_ingest_replay.py` (fold/replay + push round-trip).

**Method (design §5.B, §7.C, §7.E4, §7.F Stages 1 & 6).** The CBS transport is **UNVERIFIED**, so the capture layer is validated against **golden fixtures**, not the live site. The capture uses the canonical **three-probe, transport-agnostic** design: (1) a **MAIN-world** content script at `run_at:"document_start"` monkeypatching **WebSocket + fetch + XHR**; (2) a **framework-state read** (React fiber props); (3) a **MutationObserver DOM fallback** in the isolated world. The isolated content script is the trust boundary and owns the localhost WebSocket to `127.0.0.1:8787`.

1. **Frame parsing** — `apps/extension/src/lib/parse.ts` (`parseDraftEvent`, `parseLeagueSettings`) turns each captured probe frame into a normalized `DraftEvent` (`packages/shared/src/events.ts`). Vitest drives `fixtures/*.json` → asserts exact `DraftEvent` output, including the tiered-DST / K-bonus scoring fields (scaffold change #1).
2. **Three-probe de-dup** — `dedup.test.ts` feeds the *same* pick arriving on all three probes and asserts collapse to a **single** event **keyed on the overall pick number** (`DraftPick.overall`; CLAUDE "de-dup by pick_number").
3. **DOM fallback (Playwright)** — `mutation-observer.spec.ts` loads a **saved draft-room HTML fixture** (`fixtures/draft-room.html`), runs the isolated-world `MutationObserver` path, and asserts every board pick is emitted in order.
4. **Manual-paste fallback** — `manual-paste.test.ts` parses pasted board text → identical normalized events (the guaranteed path when transport capture fails).
5. **Crash-safe replay** — `backend/tests/test_ingest_replay.py`: append a sequence of events to the SQLite append-only log via `jaaffl.ingest.log` (append **before** computing a rec), then `fold_state()` after a simulated restart reproduces the **exact** `DraftState` (design §7.F Stage 1: DraftState is a fold over the log); re-ingesting a duplicate overall pick is idempotent (no double-apply).
6. **`/recs/ws` push round-trip (scaffold change #4)** — with a FastAPI `TestClient`: ingest a pick via `POST /draft/events` (or `WS /draft/ws`) → `handle_event` appends to the log → `recompute()` → assert a decomposed `Recommendation` is pushed on the **new `WS /recs/ws`** channel, while `WS /draft/ws` (ingest) and `GET /recommendation` (REST) continue to coexist.

**Pass/fail gate.**
- **PASS iff** (a) **100%** of golden-fixture picks are recovered with **0 duplicates** across the three probes; (b) Playwright extracts all N board picks from the saved HTML; (c) manual-paste yields byte-identical normalized events to the frame path for the same board; (d) replay is deterministic and de-dup idempotent; (e) the ingest → `recompute()` → `/recs/ws` round-trip delivers a `Recommendation` and all three surfaces (`/draft/ws`, `/recs/ws`, REST) work together. Runs in the `js` CI job (Vitest) + a dedicated Playwright job; replay + push run in the `backend` job.
- **UNVERIFIED note in CI:** until real CBS frames are captured, fixtures are **synthetic** and the manual-paste + MutationObserver paths are the load-bearing gates; a `TODO(capture)` marker tracks swapping in real golden frames post-capture (§7.G, §10.6 item 5).

- [ ] `parse.ts` pure + fixture-driven; no live network in tests.
- [ ] Three-probe de-dup keyed on the overall pick number; unit-proven idempotent.
- [ ] Playwright installed in its own CI job; saved `draft-room.html` fixture checked in.
- [ ] `test_ingest_replay.py` proves fold determinism + dup idempotency (append-before-recompute) and the `/recs/ws` push round-trip.
- [ ] Manual-paste path reaches parity with the frame path on the same board.

---

### 9.5 E5 — Schema-parity CI (Pydantic ⇄ Zod)

**Scripts / tests.** `scripts/export_schemas.py` (Pydantic → JSON Schema), `backend/tests/test_schema_parity.py` (Python side), `packages/shared/tests/parity.test.ts` (Zod side).

**Method (design §7.B, §7.E5, scaffold changes #1 & #3, §10.5 "keep Pydantic ⇄ Zod in sync").** Two complementary checks over the canonical contract models — `LeagueSettings` (now with `scoring_tiers` + `scoring_bonuses`, scaffold #1), `RosterSlot`, `ScoringRule`, `Position`, `DraftEvent`, `DraftPick`, `DraftState`, `RecommendedPick` (now embedding **`ScoreComponents`**, scaffold #3), and `Recommendation`.

The new `ScoreComponents` decomposes `Score(p)` term-for-term (identical field names + types on both sides):

```
ScoreComponents = {
  mlv,                 # MLV_p
  vona,                # raw VONA_p; score adds kappa · max(0, vona)
  sigma,               # σ̂_p (season-pts scale)
  risk_penalty,        # λ(phase,slot) · σ̂_p (signed by λ); score SUBTRACTS it
  cliff_bonus,         # alpha · CliffBonus_p (applied)
  floor, ceiling,      # μ_p ∓ 1.28·σ̂_p (diagnostics)
  replacement_baseline,# position replacement value feeding MLV
  modifiers,           # {name: capped_contribution}  (each ≤ ~3–5 pts)
}
# Reconstruction identity (asserted in E7):
#   score ≈ mlv + kappa·max(0, vona) − risk_penalty + cliff_bonus + Σ modifiers.values()
```

1. **Schema diff.** `export_schemas.py` dumps `Model.model_json_schema()` → `packages/shared/schemas/<Model>.json` (checked in). The JS side derives JSON Schema from each Zod schema via `zod-to-json-schema` and structurally compares field names, types, `required`/optional, and enum members. **Any divergence fails.**
2. **Canonical-fixture round-trip.** `packages/shared/fixtures/<Model>.json` holds one canonical payload per model. The **backend** test loads each with the Pydantic model (`Model.model_validate(json)`); the **js** test parses the *same* file with the Zod schema (`Schema.parse(json)`). A payload valid on one side and invalid on the other = divergence = fail.

```python
# backend/tests/test_schema_parity.py (excerpt)
@pytest.mark.parity
@pytest.mark.parametrize("model,fixture", CANONICAL_FIXTURES)
def test_pydantic_accepts_canonical(model, fixture):
    model.model_validate(json.loads(fixture.read_text()))  # must not raise
```

**Pass/fail gate.**
- **PASS iff** (a) generated Pydantic JSON Schema and Zod-derived JSON Schema are structurally equal for every model; (b) every canonical fixture validates under **both** Pydantic and Zod. The NEW fields are explicitly covered: `LeagueSettings.scoring_tiers`/`scoring_bonuses` and `RecommendedPick.score_components` (`ScoreComponents`) must round-trip, or CI fails. Runs in **both** jobs (backend asserts Python side + regenerates schema and `git diff --exit-code`; js asserts Zod side + schema diff).

- [ ] `scoring_tiers` (DST points- AND yards-allowed brackets) + `scoring_bonuses` (K 50+ yd) added to `LeagueSettings` (Pydantic) and `LeagueSettingsSchema` (Zod).
- [ ] `ScoreComponents` added to `RecommendedPick`/`RecommendedPickSchema` on both sides with identical field names/types.
- [ ] `export_schemas.py` output checked in; CI `git diff --exit-code packages/shared/schemas` catches stale schema.
- [ ] Canonical fixtures cover every contract model; both-sides validation enforced.

---

### 9.6 E6 — Offline simulated-league tournament (the efficacy gate)

**Script / test.** `scripts/run_tournament.py` (`make tournament`), `backend/tests/test_tournament.py` (smoke).

**Method (design §4.C, §7.E6, §10.6 item 7).** The project's **own** validation gate — there is **no peer-reviewed, empirically-validated optimal live snake-draft solver** to compare against (design §4.C), so efficacy is proven by an offline simulated-league tournament. Our `ScoreAgent` (drafting by the tuned `Score(p)` from `config/engine.json`) occupies **every one of the 12 draft slots** in turn — a controlled sweep, not the live order — against baseline agents (all implementing `DraftAgent`):
- `AdpOnlyAgent` — draft strictly by FFC ADP.
- `VbdOnlyAgent` — draft strictly by static value-over-replacement (design §6.C.2 baselines; no VONA/risk/cliff).

For each slot × seed, simulate the **17-round snake** to completion, then score each final roster by **projected starting-lineup points** via `engine.optimize.optimal_lineup_value` (the flex-aware optimal 9). Report mean starting-lineup points per agent per slot. **Stretch** (`--mc-season`, `stretch` marker): feed final rosters to the Monte-Carlo season simulator for **playoff / championship odds** (design §7.F Stage 5 stretch; CP-SAT end-state) and report those as the headline metric.

**Anti-self-reference.** Report against **both** baselines and across **all 12 slots** (a strategy that only wins from one slot, or only against one opponent type, does not pass). Opponent tables mix in the E2 `NeedBasedAgent` so the win is not an artifact of ADP opponents.

**Pass/fail gate.**
- **PASS iff** mean starting-lineup points(ours) **≥ max(AdpOnly, VbdOnly)** at **every** one of the 12 slots, **and** the aggregate improvement is significant (one-sided paired test across slot × seed cells, `p < 0.05`), **and** the per-slot effect is **non-negative everywhere** (no slot regresses). Stretch: same relation on MC playoff/championship odds.
- **CI** runs a small deterministic smoke tournament (few seeds, fixture projections) proving the harness + significance test wire up; the **full** tournament is offline (`make tournament`) and its report is the v1 sign-off artifact (`stretch` marker gates the MC-odds path).

- [ ] `AdpOnlyAgent`, `VbdOnlyAgent`, and our `ScoreAgent` share the one `engine.simulate.DraftAgent` protocol.
- [ ] Tournament sweeps all 12 slots × N seeds × opponent tables; results persisted (JSON + summary).
- [ ] Significance test (Wilcoxon/bootstrap) implemented; per-slot non-negativity asserted.
- [ ] `test_tournament.py` smoke run is deterministic and fast; full run documented as the v1 gate.
- [ ] Report explicitly states "no peer-reviewed literature benchmark exists — this is the project's own gate."

---

### 9.7 E7 — Latency perf gate

**Script / test.** `scripts/bench_recompute.py` (`make bench`), `backend/tests/test_latency.py` (`perf` marker, runs in CI).

**Method (design §7.D, §7.E7).** Benchmark the **stateless hot path** `engine.recommend.recompute(ctx: DraftContext, state: DraftState) -> Recommendation` at **worst case**: `candidate_cap = 180` candidates, deepest board (full picked-player mask), all capped modifiers active, both the phase λ band and its runtime **slot-override** branches (design §6.C.5) exercised, and the analytic (non-MC) survival path. The pre-draft `DraftContext` (μ/σ/floor/ceiling, league points, replacement baselines + flex allocation, tiers + cliff bonuses, FFC ADP mean/SD joined by canonical id, crosswalk) is built **once** in a fixture and **warmed** before timing, so we measure the per-pick recompute, not cold import/precompute.

```python
# backend/tests/test_latency.py
@pytest.mark.perf
def test_recompute_p95_under_2s(worst_case_ctx, worst_case_state):
    samples = [time_one(recompute, worst_case_ctx, worst_case_state) for _ in range(200)]
    p95 = statistics.quantiles(samples, n=100)[94]
    assert p95 < 2.0, f"p95 {p95:.3f}s exceeds 2s budget"     # target analytic path < 0.2s
```

Uses `time.perf_counter` over N=200 runs (no new required dep); `scripts/bench_recompute.py` may use `pytest-benchmark` for richer offline profiling. Inside the timed region: drop-picked mask → vectorized survival → bounded top-K candidates → `engine.optimize.marginal_lineup_value` (MLV via `scipy.optimize.linear_sum_assignment` over the 9 slots with the WR/RB flex mask) → analytic VONA/risk/cliff → assemble+sort. **CP-SAT (OR-Tools) is NOT on this path** (reserved for the stretch season simulator — design §7.D). Each returned `RecommendedPick` carries its `ScoreComponents`, and the test asserts the reconstruction identity `abs(score − (mlv + κ·max(0,vona) − risk_penalty + cliff_bonus + Σ modifiers)) < 1e-6`. The full ingest → recompute → `/recs/ws` push round-trip is covered by E4; E7 isolates the recompute core.

**Pass/fail gate.**
- **PASS iff** `p95 < 2000 ms` on the worst-case fixture (soft target: analytic path `< 200 ms`) **and** the `ScoreComponents` reconstruction identity holds for every candidate. Runs as a CI **perf gate** in the `backend` job (`pytest -m perf`); exceeding the budget fails the build. A regression margin is logged so a 1.9 s p95 is flagged as at-risk even though it passes.

- [ ] `recompute()` is stateless and re-entrant; `DraftContext` precompute isolated to a warm fixture.
- [ ] Worst-case fixture (180 candidates, deep mask, all modifiers, slot-override branch) checked in.
- [ ] `test_latency.py` asserts p95 < 2 s over ≥ 200 samples + the decomposition identity; CI runs `pytest -m perf`.
- [ ] `bench_recompute.py` emits a component breakdown (mask, survival, MLV, assemble) for profiling.

---

### 9.8 CI wiring (how each gate runs)

Extend `.github/workflows/ci.yml` (current jobs: `backend` = ruff check + ruff format --check + `pytest -q`; `js` = `pnpm -r typecheck` + `pnpm -r test`).

| Job (existing/new) | Added step | Covers |
|--------------------|------------|--------|
| `backend` | install `.[dev,data,engine]`; `pytest -q` (fixture E1/E3, replay + `/recs/ws` E4, parity E5) | E1, E3, E4-replay/push, E5 (Py side) |
| `backend` | `pytest -m perf` | E7 |
| `backend` | `python -m scripts.export_schemas && git diff --exit-code packages/shared/schemas` | E5 (stale-schema guard) |
| `backend` | `pytest -m parity` | E5 (canonical fixtures, Py side) |
| `backend` | 5-trial smoke study + `EngineParams` validation | E2 (artifact + harness) |
| `js` | `pnpm -r test` (Vitest: `parse`, `dedup`, `manual-paste`, Zod `parity.test.ts`) | E4-unit, E5 (Zod side) |
| **`e2e` (new)** | `pnpm --filter @jaaffl/extension exec playwright install --with-deps && playwright test` | E4 (MutationObserver) |

Offline-only (not per-PR; `make` targets, run pre-draft or at release): **E1 live re-measure** (`make calibrate-flex`), **E2 full study** (`make tune`), **E3 full historical sweep** (`make validate-proj`), **E6 full tournament** (`make tournament`). Their *artifacts* (`config/engine.json`, reports, fixtures) are what CI validates.

New Makefile targets: `calibrate-flex`, `tune`, `validate-proj`, `tournament`, `bench`, `parity`, plus a convenience `calibrate` (E1→E2→E3 in order) and `evaluate` (E6). Backend jobs stay pinned to Python 3.12; the `js`/`e2e` jobs reuse the existing pnpm 10.33.0 / Node 22 setup.

---

### 9.9 Acceptance criteria

- **E1** `scripts/calibrate_flex_split.py` implements the top-60 method; `flex_rb + flex_wr == 12` holds on the frozen fixture; the measured split + the §6.C.2 man-games/VOLS-blended `replacement_baselines` (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13) are written to `config/engine.json`; thin-board ECR fallback works; the likely-RB-heavy result is surfaced, never hard-coded.
- **E2** `scripts/tune_engine_params.py` runs an Optuna study over (κ∈[0.5,0.8], the λ-bands within their canonical ranges, α∈[0.3,0.5], caps∈[3,5]) evaluated across **all 12 slots** and against **AdpNoise, VbdOnly, and NeedBased** agents on **held-out** opponents + seasons; promotes to `config/engine.json` **only** on a significant, per-slot-non-negative win over the frozen defaults; the committed artifact validates against `EngineParams`.
- **E3** `scripts/validate_projections.py` backtests the simple-average blend vs each single source under the exact CBS map (reception = 0) for 2021–2024; `MAE(blend) ≤ min-source MAE` and `Spearman(blend) ≥ max-source − 0.02` every season; σ recalibrated to 80% coverage ∈ [0.75, 0.85].
- **E4** Golden-fixture parse + three-probe de-dup (by overall pick number) + Playwright MutationObserver + manual-paste all green; append-only-log fold replay is deterministic and dup-idempotent; the `/draft/ws` ingest → `recompute()` → `/recs/ws` push round-trip works alongside REST; UNVERIFIED-transport caveat and post-capture fixture-swap TODO recorded.
- **E5** Pydantic and Zod schemas are structurally identical for every contract model — including NEW `LeagueSettings.scoring_tiers`/`scoring_bonuses` and `RecommendedPick.score_components` (`ScoreComponents`) — and every canonical fixture validates under both; stale generated schema fails CI.
- **E6** The offline tournament shows our agent ≥ **both** ADP-only and VBD-only at **every** one of the 12 slots with aggregate significance (`p < 0.05`) and no per-slot regression; the report states plainly that this is the project's own gate (no literature benchmark).
- **E7** `recompute()` worst-case p95 `< 2 s` is asserted in CI (`pytest -m perf`), analytic path targeting `< 200 ms`, and the `ScoreComponents` decomposition reconstructs `score` within 1e-6.
- **Cross-cutting** All stochastic jobs are seed-pinned and reproducible; CI is network-free (fixtures only); heavy calibrations run offline via `make` and only their artifacts gate CI; the harness stays $0 / offline / text-only per §10.7.

### 9.10 Definition of done

- [ ] `config/engine.json` + `jaaffl.config.EngineParams` (with `FlexSplit`, `LambdaBand`) exist with validators enforcing every §9.0 invariant (`flex_rb+flex_wr==12`, `0<caps≤5`, full 1–17 λ coverage, band-sign direction, positive baselines).
- [ ] `scripts/`: `calibrate_flex_split.py`, `tune_engine_params.py`, `validate_projections.py`, `run_tournament.py`, `bench_recompute.py`, `export_schemas.py` — all runnable via `python -m scripts.<name>` with `--seed`/`--dry-run`.
- [ ] `backend/tests/`: `test_flex_split.py`, `test_engine_params.py`, `test_projections.py`, `test_ingest_replay.py`, `test_schema_parity.py`, `test_tournament.py`, `test_latency.py` — all pass; markers `perf/parity/slow/stretch` registered.
- [ ] `apps/extension/tests/`: `parse.test.ts`, `dedup.test.ts`, `manual-paste.test.ts`, `e2e/mutation-observer.spec.ts` — all pass; fixtures checked in; `vitest` + `@playwright/test` added to the extension.
- [ ] `packages/shared/`: `schemas/*.json` generated + checked in; `fixtures/*.json` canonical payloads; `tests/parity.test.ts` green.
- [ ] `backend/pyproject.toml`: `[data]` extra migrated to `nflreadpy`+`polars` (scaffold #2), `scikit-learn` added to `[engine]`, `pytest-benchmark` added to `[dev]`, pytest markers registered.
- [ ] `.github/workflows/ci.yml` extended: backend perf + parity + schema-diff + smoke-study steps; js Vitest parity; new `e2e` Playwright job.
- [ ] Makefile targets `calibrate-flex`, `tune`, `validate-proj`, `tournament`, `bench`, `parity`, `calibrate`, `evaluate` added and documented in `CONTRIBUTING.md`.
- [ ] Honesty flags present in code/reports: flex split **measured** (likely RB-heavy), CBS transport **UNVERIFIED** (synthetic fixtures until capture), nflreadpy crosswalk fn **`[VERIFY]`**, forward-year outputs **ESTIMATED**, E6 is the **project's own** efficacy gate.
- [ ] v1 exit met: with `config/engine.json` calibrated by E1–E3, E4/E5/E7 green in CI, and the E6 tournament report showing ≥-baseline efficacy, live CBS picks yield a decomposed, league-correct, risk-aware, flex-aware recommendation in the overlay within **2 s** on the $0 tier with crash-safe replay.

---

## 10. Phasing — ROADMAP Stages 1–7, v1 vs stretch

This section sequences the settled design (design §7.F, §10.5) into **gated, dependency-ordered stages** that map 1:1 onto `ROADMAP.md` Stages 1–7 plus a **Stage 0** (the four required scaffold changes) and a **cross-cutting calibration track** (E1–E7). It does not re-derive the research — it turns design §4–§10 into buildable work with exact paths, signatures, config keys, exit gates, acceptance criteria, and a Definition-of-done checklist per stage. Read `config/league.json` (immutable) and `docs/draft-system-design.md` before starting any stage.

**Tags:** `[v1]` ships in the first deployable prototype · `[str]` stretch (post-v1). **Status legend** (mirrors `ROADMAP.md`): `[ ]` not started · `[~]` scaffolded (stub/contract in place) · `[x]` done. Every module named below is currently `[~]` in the repo; Stage 0 is the first executable work.

**Governing constants (verbatim — `config/league.json`, `immutable: true`; never paraphrase, re-order, or "optimize"):**

- Draft Type: Snake
- Teams: 12
- Draft Order: Decided in-person, then entered into CBS Sports system
- Scoring Format: Standard
- Draft Rounds: 17
- Roster Slots per Team: QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Derived (arithmetic only, not new constraints): 9 starters + 8 bench = 17 = draft rounds; the **WR/RB flex is WR-or-RB ONLY** (excludes TE, QB, K, DST). Scoring Format **Standard = non-PPR** (0 pts/reception). League-wide starter demand across 12 teams: **QB12, TE12, K12, DST12**, and the RB+WR startable pool = **12 RB + 36 WR + 12 flex = 60** of **108** total starters (9 × 12). **The actual draft order is read live from the CBS room — NEVER inferred from team count.** These values, and only these, drive every baseline computed downstream.

**Cross-cutting guarantees enforced at every stage:** latency budget **< 2 s/pick** (analytic hot path **< 200 ms**; design §7.D); **$0 besides AI usage** (paid providers off by default); **text-only** (no voice/Realtime); **local-first**, user's own authenticated CBS session only; forward-year (2027) outputs labeled **ESTIMATED**. Honesty caveat (ADR 0003): **no peer-reviewed optimal live snake-draft solver exists** — efficacy is proven by the project's OWN offline simulated-league tournament vs VBD-only and ADP-only baselines (E6), never by vendor claims.

### 10.0 Phasing overview & dependency graph

```
Stage 0  Four scaffold changes  ── gate ──►  everything (Pydantic ⇄ Zod parity)
   │
   ▼
Stage 1  CBS sync (extension 3-probe → SQLite append-only log → fold_state)      [v1]
   │           └─ E4 golden fixtures (once real CBS frames observed)             [v1]
   ▼
Stage 2  Normalize league settings (full CBS scoring map: DST dual tiers + K)    [v1]
   ▼
Stage 3  Warehouse (DuckDB + Parquet + SQLite) + crosswalk                        [v1]
   ▼
Stage 4  $0 providers (Nflreadpy + FFC ADP + CBS-on-page; paid stubs off)         [v1]
   │           └─ E1 flex-split measurement (top-60) · E3 projection-blend valid. [v1]
   ▼
Stage 5  Transparent engine (precompute → stateless recompute; ScoreComponents)  [v1 core]
   │           └─ E2 calibrate κ/λ/α (Optuna) · E7 perf gate (<2 s) · E5 parity   [v1]
   │           └─ MC-VONA · season simulator (CP-SAT) · XGBoost · RL audit        [str]
   ▼
Stage 6  Overlay [v1] + WS /recs/ws [v1] + Next.js dashboard [v1-lite/str]
   ▼
Stage 7  Text-only assistant (explain_recommendation over ScoreComponents)       [v1-lite]

Cross-cutting: E6 simulated-league tournament (efficacy proof)                    [str]
               per-manager tendency modeling (wire the log day one)               [str]
```

| Stage | ROADMAP map | Tier | Hard dependency | Exit gate (one line) |
|---|---|---|---|---|
| 0 | — (design §7.B / §10.5) | v1 | none | 4 scaffold changes land; Zod⇄Pydantic parity CI (E5) green |
| 1 | Stage 1 — CBS sync | v1 | 0 | picks stream in **and** replay to exact state after a mid-draft restart |
| 2 | Stage 2 — Normalize | v1 | 0,1 | `LeagueSettings` round-trips the exact CBS scoring map + verbatim roster |
| 3 | Stage 3 — Warehouse | v1 | 0 | snapshots materialized; ids resolve across CBS/FFC/nflverse |
| 4 | Stage 4 — Data tiers | v1 | 3 | projections/ECR/xEP/ADP/CBS-on-page queryable behind the protocol |
| 5 | Stage 5 — Engine | v1 core / str | 2,3,4 | `GET /recommendation` returns a decomposed, tuned rec in **< 2 s** |
| 6 | Stage 6 — UI | v1 / v1-lite | 5 | overlay shows best pick + decomposition + survival %, pushed via `WS /recs/ws` |
| 7 | Stage 7 — Assistant | v1-lite | 5 | `explain_recommendation` narrates `ScoreComponents`; text-only |

### 10.1 Stage 0 — Four required scaffold changes (gate for everything) `[v1]`

The four changes from design §7 / §10.5 must land **before** engine work and must keep the **Pydantic contracts (`backend/src/jaaffl/domain/models.py`) in lockstep with the Zod contracts (`packages/shared/src/*.ts`)** — parity is enforced by E5 in CI.

**Change 1 — `LeagueSettings` gains `scoring_tiers` + `scoring_bonuses`.** CBS **"Standard" DST scores on BOTH a points-allowed AND a yards-allowed tier**; `scoring_bonuses` carries e.g. the **K 50+ yard FG bonus**. The existing flat `scoring: list[ScoringRule]` cannot express brackets.

```python
# backend/src/jaaffl/domain/models.py  (NEW models + 2 new LeagueSettings fields)
class ScoringTier(BaseModel):
    """A bracketed rule, e.g. a DST points-allowed OR yards-allowed band."""
    stat: str                                   # 'dst_points_allowed' | 'dst_yards_allowed'
    min: float | None = None                    # inclusive lower bound (None = -inf)
    max: float | None = None                    # exclusive upper bound (None = +inf)
    points: float
    applies_to: list[Position] | None = None    # e.g. [Position.DST]

class ScoringBonus(BaseModel):
    """A threshold bonus, e.g. K 50+ yard FG."""
    stat: str                                   # e.g. 'fg_made_50_plus'
    threshold: float                            # e.g. 50.0 (yards)
    points: float
    applies_to: list[Position] | None = None    # e.g. [Position.K]

class LeagueSettings(BaseModel):
    ...  # existing fields unchanged
    scoring_tiers: list[ScoringTier] = Field(default_factory=list)     # DST pts- AND yds-allowed brackets
    scoring_bonuses: list[ScoringBonus] = Field(default_factory=list)  # e.g. K 50+ yd bonus
```

```ts
// packages/shared/src/league.ts  (mirror — keep in sync)
export const ScoringTierSchema = z.object({
  stat: z.string(),
  min: z.number().nullable().optional(),
  max: z.number().nullable().optional(),
  points: z.number(),
  applies_to: z.array(PositionSchema).nullable().optional(),
});
export const ScoringBonusSchema = z.object({
  stat: z.string(),
  threshold: z.number(),
  points: z.number(),
  applies_to: z.array(PositionSchema).nullable().optional(),
});
export const LeagueSettingsSchema = z.object({
  /* …existing… */
  scoring_tiers: z.array(ScoringTierSchema).default([]),
  scoring_bonuses: z.array(ScoringBonusSchema).default([]),
});
```

**Change 2 — `nfl_data_py` → `nflreadpy` (Polars).** Provider return type **pandas → polars**. In `backend/src/jaaffl/providers/base.py` the `TYPE_CHECKING` import becomes `import polars as pl` and `historical_stats(...) -> pl.DataFrame`; `players(...)` stays `list[Player]`. `providers/nflverse.py` becomes `NflreadpyProvider` (see Stage 4). Update `pyproject` dep and `providers/registry.py`.

**Change 3 — `RecommendedPick` gains a `ScoreComponents` decomposition** (the canonical `Score(p)` terms — design §10.3):

```python
# backend/src/jaaffl/domain/models.py
class ScoreComponents(BaseModel):
    """Additive decomposition of RecommendedPick.score (canonical Score(p), design §10.3)."""
    mlv: float                 # flex-aware Marginal Lineup Value (Hungarian)
    vona: float                # MLV_p − E[best surviving MLV at pos(p) by your next pick]
    risk_penalty: float        # −λ(phase,slot)·σ̂_p (signed)
    cliff_bonus: float         # α·CliffBonus_p (Boris-Chen GMM tier cliff)
    sigma: float               # σ̂_p used by the risk term
    floor: float               # projection floor (league points)
    ceiling: float             # projection ceiling (league points)
    replacement_baseline: float  # replacement league points at pos(p)
    modifiers: dict[str, float] = Field(default_factory=dict)  # capped bye/handcuff/SOS, each ≤ ~3–5 pts

class RecommendedPick(BaseModel):
    ...  # existing fields unchanged
    components: ScoreComponents | None = None
```

```ts
// packages/shared/src/recommendation.ts  (mirror)
export const ScoreComponentsSchema = z.object({
  mlv: z.number(), vona: z.number(), risk_penalty: z.number(), cliff_bonus: z.number(),
  sigma: z.number(), floor: z.number(), ceiling: z.number(), replacement_baseline: z.number(),
  modifiers: z.record(z.number()).default({}),
});
export const RecommendedPickSchema = z.object({
  /* …existing… */
  components: ScoreComponentsSchema.nullable().optional(),
});
```

**Change 4 — add a `WS /recs/ws` push channel** (backend → overlay/dashboard) in `backend/src/jaaffl/api/app.py`, **keeping** the existing ingest `WS /draft/ws`, `POST /draft/events`, and `GET /recommendation`:

```python
@app.websocket("/recs/ws")
async def recs_ws(ws: WebSocket) -> None:
    """Push channel: backend → overlay/dashboard. Emits a Recommendation (JSON) per new pick."""
    await ws.accept()
    ...  # subscribe to the per-league rec bus; on each fold_state advance, send Recommendation.model_dump()
```

Re-export new symbols from `packages/shared/src/index.ts` and `jaaffl.domain.__init__`.

**Acceptance criteria:** all four changes merged; `LeagueSettings` can represent CBS "Standard" DST dual tiers + K 50+ bonus; providers type-check as polars; `RecommendedPick.components` (de)serializes both ways; `WS /recs/ws` accepts a connection and echoes a `Recommendation` shape; E5 schema-parity check passes.

**Definition of done:**
- [ ] `ScoringTier`, `ScoringBonus`, `ScoreComponents` added to `models.py` **and** mirrored in `league.ts` / `recommendation.ts`; both re-exported.
- [ ] `providers/base.py` returns `pl.DataFrame`; `providers/nflverse.py` renamed to `NflreadpyProvider`; `registry.py` updated; dependency swapped in `pyproject`.
- [ ] `WS /recs/ws` present; `WS /draft/ws` + `POST /draft/events` + `GET /recommendation` untouched.
- [ ] `ruff check` + `ruff format --check` + `pytest` green; `pnpm -r typecheck` + `pnpm -r test` green.
- [ ] E5 parity test (10.9) asserts every Pydantic field ⇄ Zod field 1:1.

### 10.2 Stage 1 — CBS sync layer `[v1]`

MV3 extension with **`@crxjs/vite-plugin`** (WXT fallback), **three-probe, transport-agnostic** capture — **the CBS draft-room transport is `[UNVERIFIED]`**, so we do not commit to a single mechanism:

1. **MAIN-world content script at `run_at: "document_start"`** monkeypatching `WebSocket` + `fetch` + `XHR` (`apps/extension/src/content/cbs-draft.content.ts` + `src/lib/transport.ts`).
2. **Framework-state read** (React fiber props) for the on-the-clock board.
3. **`MutationObserver` DOM fallback** in the **isolated** world.

De-dup captured picks **by `pick_number`**. The **isolated content script is the trust boundary** and owns the localhost WebSocket to `ws://127.0.0.1:8787/draft/ws`; the **service worker stays minimal** (`src/background/service-worker.ts`). **Manifest:** narrow `host_permissions` (CBS + `127.0.0.1:8787`); `permissions`: `scripting`, `storage` (+`activeTab`); **NO `webRequest` / `declarativeNetRequest`**; overlay injected in a **Shadow DOM**. **Manual-paste fallback** for when all three probes miss.

Backend ingest is an **append-only SQLite log with a fold**: `handle_event` (already wired in `api/app.py`) appends the event to SQLite **before** any rec is computed, so a restart replays to the exact `DraftState` (design §7 Step 7). Add `backend/src/jaaffl/ingest/log.py` (NEW):

```python
# backend/src/jaaffl/ingest/log.py  (NEW — append-only log + crash-safe fold)
def append_event(event: DraftEvent) -> int: ...              # persist to SQLite; return monotonic seq
def read_log(league_id: str) -> list[DraftEvent]: ...        # ordered replay source
def fold_state(events: Iterable[DraftEvent]) -> DraftState:  # pure left-fold; de-dup by pick_number
    ...
```

**Tasks:**
- [ ] `transport.ts` three probes + de-dup by `pick_number`; normalize to `DraftEvent` (`packages/shared/src/events.ts`).
- [ ] Isolated CS owns the WS; heartbeat/reconnect; SW minimal.
- [ ] `manifest.json`: narrow hosts, `scripting`+`storage`(+`activeTab`), no `webRequest`/`declarativeNetRequest`, Shadow-DOM overlay.
- [ ] `ingest/log.py` + wire `handle_event` → `append_event` **before** rec compute; `fold_state` rebuild on boot.
- [ ] Manual-paste fallback UI in the overlay.

**Acceptance criteria:** with the extension on a live/mock CBS room, each pick appears as a `pick_made` `DraftEvent` (de-duped) on `WS /draft/ws`; killing and restarting the backend replays the SQLite log to the identical `DraftState` (same `current_overall_pick`, same `picks`).

**Definition of done:**
- [ ] Picks stream end-to-end; `pick_number` de-dup verified against a double-fire fixture.
- [ ] Crash-restart replay reproduces exact state (test drives `append_event` → kill → `fold_state`).
- [ ] Manifest audited: no `webRequest`/`declarativeNetRequest`; host perms limited to CBS + `127.0.0.1:8787`.
- [ ] `[UNVERIFIED]` transport documented; manual-paste fallback exercised.

### 10.3 Stage 2 — Normalize league settings `[v1]`

`apps/extension/src/lib/parse.ts` + `apps/extension/src/content/cbs-league.content.ts` capture the settings page; `backend/src/jaaffl/ingest/cbs.py::normalize_league_settings(raw: dict) -> LeagueSettings` owns the authoritative parse. This stage carries **Change 1 end-to-end**: the **full CBS scoring map** — the **DST points-allowed AND yards-allowed tiers** and the **K 50+ yard bonus** — must round-trip into `scoring_tiers` / `scoring_bonuses`. **Draft order is read from the live board via `normalize_draft_state`; it is NEVER inferred from team count** (`LeagueSettings.draft_order` stays `None` until the room supplies it). Persist every league snapshot for self-owned historical analysis.

The parsed roster MUST reproduce the verbatim slots **QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8**, with the **WR/RB flex eligible for WR or RB only** (`RosterSlot(slot="WR/RB", eligible_positions=[WR, RB], count=1, starting=True)`; TE/QB/K/DST excluded). Cross-check the parse against `config/league.json` and **surface — never silently change — any conflict** (agent_usage_contract).

**Acceptance criteria:** a captured CBS "Standard" settings payload normalizes to a `LeagueSettings` whose `roster_slots` equal the verbatim roster (incl. WR-or-RB-only flex), whose `team_count == 12` and `draft_type == "snake"`, and whose `scoring_tiers` reproduce both DST tiers and `scoring_bonuses` the K 50+ bonus; a settings-vs-`league.json` diff raises a visible conflict rather than mutating either.

**Definition of done:**
- [ ] `normalize_league_settings` implemented; golden fixture round-trips the exact CBS scoring map (both DST tiers + K bonus).
- [ ] Roster slots + WR/RB-only flex assert-tested against the verbatim settings.
- [ ] Draft order sourced only from `normalize_draft_state`; unit test proves it is never derived from `team_count`.
- [ ] League snapshots persisted (Stage 3 store); conflict-surfacing test green.

### 10.4 Stage 3 — Warehouse `[v1]`

`backend/src/jaaffl/data/warehouse.py` + `data/crosswalk.py` provide the three-store local warehouse with **distinct roles** (design §7 Step 7):

- **DuckDB** — analytics / backtest queries (E2/E3/E6 read here).
- **Parquet** — immutable **nflverse snapshots** (season stats, ECR, xEP).
- **SQLite** — **ACID app state + the append-only draft-event log** (Stage 1's `ingest/log.py` writes here); `DraftState` is a **fold over the log**.

`crosswalk.py::Crosswalk` resolves CBS ⇄ FFC ⇄ nflverse ids to the canonical `Player.player_id`, with a **fuzzy name+team+position fallback**. Store lives under `Settings.jaaffl_data_dir` (default `./data`).

**Acceptance criteria:** nflverse pulls land as Parquet and are queryable via DuckDB; the SQLite log + `fold_state` reproduce `DraftState`; `Crosswalk.resolve(...)` maps a known CBS name and a known FFC name to the same canonical id, and an intentionally misspelled name resolves via the fuzzy fallback.

**Definition of done:**
- [ ] `warehouse.py` initializes DuckDB + Parquet dir + SQLite with the documented role split.
- [ ] `crosswalk.py` exact-match + fuzzy fallback, unit-tested on CBS/FFC/nflverse samples.
- [ ] Schema documented and stable enough to graduate to Postgres `jsonb` + Redis Streams later (design §7; ROADMAP Stage 3).

### 10.5 Stage 4 — External data tiers ($0) `[v1]`

Behind the `FantasyDataProvider` protocol (`providers/base.py`, `Capability` enum) and `providers/registry.py`. **$0 is the default; paid providers are opt-in and OFF** (`Settings.jaaffl_enable_fantasypros/…sportsdataio/…sportradar = False`).

- **`NflreadpyProvider`** (`providers/nflverse.py`, polars): history = **`load_player_stats`**; ECR = **`load_ff_rankings`**; expected-pts = **`load_ff_opportunity`**; ids via the nflverse crosswalk (**`load_ff_playerids` / `load_players`** — exact Python name is **`[VERIFY]`, minor**; fuzzy name+team+pos fallback covers CBS/FFC regardless). Declares `HISTORICAL_STATS, RANKINGS, PROJECTIONS`.
- **`FantasyFootballCalculatorProvider`** (NEW, `providers/fantasyfootballcalculator.py`): **ADP mean + stdev** (+ `high`, `low`, `times_drafted`, `bye`) from `https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year={season}`; **cached DAILY**; free for personal + commercial use. FFC mocks are **15-round**, so ADP thins past **~180** → **fall back to ECR for deep-round survival**. Declares `ADP`.
- **`CbsOnPageProvider`** (NEW, `providers/cbs_on_page.py`): live league settings/projections/injuries + **authoritative scoring/roster**, read from the **warehouse CBS snapshot fed by the extension — NOT a network fetch**. Declares `PROJECTIONS, INJURIES, RANKINGS`.
- **FantasyPros / SportsDataIO / Sportradar** = **disabled stubs** (off by default; `fantasypros.py` stays gated by `jaaffl_enable_fantasypros`).

**Acceptance criteria:** with only the $0 tier enabled, the registry yields projections/ECR/xEP (Nflreadpy), ADP mean+stdev (FFC, cached ≤ 24 h, `year={season}`), and CBS on-page settings/projections (from the snapshot), all keyed by canonical `player_id`; requesting a deep player past ~180 returns an ECR-based survival input, not a crash; every paid provider reports `enabled == False`.

**Definition of done:**
- [ ] `NflreadpyProvider` returns polars frames via `load_player_stats` / `load_ff_rankings` / `load_ff_opportunity`; crosswalk fn name confirmed or fuzzy-fallback proven (`[VERIFY]`).
- [ ] `FantasyFootballCalculatorProvider` parses `adp` (mean) + `stdev` (+high/low/times_drafted/bye); **daily cache**; `teams=12`; ECR deep-fallback past ~180.
- [ ] `CbsOnPageProvider` reads the warehouse snapshot only (no HTTP).
- [ ] Paid stubs present but off; provider tests use recorded fixtures (no live network in CI).

### 10.6 Stage 5 — Transparent engine `[v1 core]` / `[str]` refinements

The engine is a **pre-draft PRECOMPUTE → per-pick stateless `recompute()`** design (design §7.D). Precompute an in-memory **`DraftContext`** once; each pick runs a bounded, vectorized recompute that must finish **well under the < 2 s budget** (analytic path target **< 200 ms**, E7).

```python
# backend/src/jaaffl/engine/recommend.py  (Stage 5 target; supersedes the n_sims MC stub)
@dataclass(frozen=True)
class DraftContext:                      # precomputed once, pre-draft (design §7.D)
    players: pl.DataFrame                # id, pos, μ, σ̂, floor, ceiling, league_points (exact CBS map)
    replacement: dict[Position, float]   # canonical baselines (below)
    flex_alloc: tuple[int, int]          # (flex_RB, flex_WR); default (8, 4); MEASURED via top-60 (E1)
    tiers: dict[str, int]                # player_id → Boris-Chen tier (GMM on ECR)
    cliff_bonus: dict[str, float]        # per-player CliffBonus_p
    adp: pl.DataFrame                    # id, m_j (mean), s_j (stdev) from FFC, canonical-id joined
    crosswalk: Crosswalk
    params: EngineParams                 # from config/engine.json

def recompute(ctx: DraftContext, state: DraftState) -> Recommendation:
    """Stateless hot path: mask picked players → vectorized survival → bounded top-K
    candidates → MLV via scipy.optimize.linear_sum_assignment → analytic VONA/risk/cliff/
    modifiers → assemble ScoreComponents, sort, return. CP-SAT is NOT on this path."""
    ...
```

**Canonical replacement baselines for THIS roster** (design §10.3; dedicated demand RB12/WR36/QB12/TE12/K12/DST12 from `league.replacement.starter_demand`, deepened by the measured flex split + VOLS/man-games blend, design §6.C.2):

| Position | Canonical replacement baseline | Draft behavior |
|---|---|---|
| RB | **≈ RB22–24** | scarce top end → **anchor early** |
| WR | **≈ WR40–42** (deep) | breadth → **accumulate mid-rounds** |
| QB | **≈ QB13** (shallow) | **defer** (target ~R7–10) |
| TE | **≈ TE13** (shallow) | **defer unless elite** |
| K | **≈ K13** (flat) | **Round 17**, then stream |
| DST | **≈ DST13** (flat) | **Round 16**, then stream |

**Canonical objective (design §10.3 — use exactly):**
```
Score(p) =  MLV_p                    # flex-aware Marginal Lineup Value (Hungarian over the 9 starting slots)
          + κ · max(0, VONA_p)       # scarcity / opportunity-cost urgency from ADP survival
          − λ(phase, slot) · σ̂_p     # risk: floor-tilt for starters (+λ), ceiling-tilt for bench (−λ)
          + α · CliffBonus_p         # tier-cliff urgency (Boris-Chen GMM on ECR)
          + Σ capped modifiers        # bye-stack −, handcuff-synergy +, SOS tiebreak ± (each ≤ ~3–5 pts)
```
Terms (design §10.3):
- **`MLV_p`** = gain to the optimal **9-starter** lineup from adding `p`, computed by the **Hungarian algorithm (`scipy.optimize.linear_sum_assignment`)** over the 9 slots with a **WR/RB flex mask**, against a **replacement-filled baseline lineup**. Implemented in `engine/optimize.py` as `marginal_lineup_value(...)` (distinct from the CP-SAT `optimize_roster`, which is stretch-only).
- **`VONA_p`** = `MLV_p − E[best surviving MLV at pos(p) by your next pick]`; survival is **analytic Gaussian** `S_j(N) = 1 − Φ((N − m_j)/s_j)` from FFC ADP mean `m_j` + stdev `s_j` (`engine/opponents.py`). **Monte-Carlo VONA is a refinement → `[str]`.**
- **`λ(phase, slot)` risk schedule** (floor-tilt `λ>0`, ceiling-tilt `λ<0`): **R1–2 +0.2…+0.4; R3–6 +0.1…+0.3; R7–9 ≈0; R10–13 −0.2…−0.4; R14–17 −0.3…−0.5.** **Slot override dominates phase:** last open startable slot → **floor**; surplus/stash → **ceiling**.
- **`CliffBonus_p`** via Boris-Chen tiers = **`sklearn.mixture.GaussianMixture` on ECR** (`engine/projections.py` or a `tiers` helper).

**`config/engine.json` (NEW) + `EngineParams` — canonical tunable defaults** (κ **0.5–0.8**, α **0.3–0.5**, flex **8 RB / 4 WR** default but **MEASURE LIVE via the top-60 method**, projection blend = **simple average**, μ-refinement cap **±10–15%**, modifier caps **≤ ~3–5 pts**, `candidate_cap ≈ 180`, `mc_rollouts ≈ 2000`):

```json
{
  "version": 1,
  "kappa": 0.65,                       "kappa_bounds": [0.5, 0.8],
  "alpha": 0.40,                       "alpha_bounds": [0.3, 0.5],
  "flex_split": {"RB": 8, "WR": 4},
  "lambda_schedule": {"R1-2": 0.30, "R3-6": 0.20, "R7-9": 0.00, "R10-13": -0.30, "R14-17": -0.40},
  "lambda_search_bounds": {"R1-2": [0.2, 0.4], "R3-6": [0.1, 0.3], "R7-9": [0.0, 0.0], "R10-13": [-0.4, -0.2], "R14-17": [-0.5, -0.3]},
  "lambda_slot_override": {"last_startable_slot": "floor", "surplus_or_stash": "ceiling"},
  "projection_blend": "mean",
  "mu_refine_cap": 0.125,              "mu_refine_cap_bounds": [0.10, 0.15],
  "modifier_cap": 4.0,                 "modifier_cap_bounds": [3.0, 5.0],
  "candidate_cap": 180,
  "mc_rollouts": 2000
}
```

The strategy this produces (design §10.4): **anchor / Hero-RB (NOT Zero-RB — counter-indicated in Standard)**, accumulate **WR breadth** mid-rounds, **defer QB/TE unless elite**, **DST in R16 + K in R17 (stream)**, bench **RB-skewed high-ceiling stashes**. Every rec carries its `ScoreComponents`. `GET /recommendation` loads the current `DraftState` + `LeagueSettings` and returns `recompute(ctx, state)`.

**`[str]` refinements (design §7.F, §10.5):** Monte-Carlo VONA; the **rest-of-season Monte-Carlo SEASON SIMULATOR** producing **playoff / championship odds** with a **CP-SAT (OR-Tools) end-state** in `engine/simulate.py` + `engine/optimize.py::optimize_roster` (**reserved for the simulator, NOT the hot path**); **XGBoost residual projections**; **per-manager tendency modeling**; **offline RL audit**.

**Acceptance criteria:** `GET /recommendation?league_id=…` returns a `Recommendation` whose top pick has a populated `ScoreComponents` that **sums to `score`** (`mlv + κ·max(0,vona) + risk_penalty + cliff_bonus + Σ modifiers`), computed against the **canonical baselines** and the **measured flex split**, in **< 2 s** on the mid-draft fixture; MLV comes from `linear_sum_assignment` over the 9 flex-aware slots; K/DST are never top-ranked before R16/R17; Zero-RB is not produced in the R1–2 band on the standard-scoring fixture.

**Definition of done:**
- [ ] `DraftContext` precompute + stateless `recompute()`; hot path free of CP-SAT and network I/O.
- [ ] `marginal_lineup_value` (Hungarian, WR/RB flex mask, replacement-filled) in `engine/optimize.py`.
- [ ] Analytic Gaussian survival + VONA in `engine/opponents.py`; GMM cliff tiers wired.
- [ ] `EngineParams` loads `config/engine.json`; all canonical defaults + bounds present.
- [ ] `ScoreComponents` populated and additively consistent with `score` (unit test).
- [ ] E7 perf gate: p95 `recompute` < 2 s (analytic < 200 ms) on a fixed candidate set.
- [ ] Stretch items are stubs/flags only; `optimize_roster` CP-SAT stays off the live path.

### 10.7 Stage 6 — Two-surface UI

- **Overlay `[v1]`** (`apps/extension/src/overlay/overlay.ts`, Shadow DOM): **best pick + `ScoreComponents` decomposition ("why") + next-turn survival %**, driven by **`WS /recs/ws` `[v1]`**.
- **Next.js dashboard `[v1-lite / str for depth]`** (`apps/web/app/page.tsx`, `lib/api.ts`): board analytics, tiers/curves, manager tendencies, scenarios (AG Grid Community + ECharts per ROADMAP Stage 6; the deeper scenario views are `[str]`).

**Acceptance criteria:** on a new pick the overlay updates within the < 2 s budget via `WS /recs/ws`, showing the best pick, the decomposed terms (MLV, κ·VONA, risk, cliff, modifiers), and survival %; the dashboard renders the current board from the same `Recommendation`/warehouse data.

**Definition of done:**
- [ ] Overlay subscribes to `WS /recs/ws`, renders best pick + decomposition + survival %, Shadow-DOM isolated.
- [ ] Dashboard v1-lite reads `lib/api.ts` → backend; deeper scenarios flagged `[str]`.
- [ ] Reconnect/heartbeat on the push socket; no layout leakage into the CBS page.

### 10.8 Stage 7 — AI assistant `[v1-lite]`

Wire the typed function tools early (`backend/src/jaaffl/assistant/tools.py`), integrate last. v1-lite ships **`explain_recommendation`**, which narrates the **`ScoreComponents`** in prose (no new math). **Text-only — voice / Realtime is out of scope (ADR 0003).** Model gated by `Settings.jaaffl_assistant_model`; web search off by default (`jaaffl_assistant_enable_web_search = False`). **`[str]`:** file-search over league rules, web-search for injuries.

**Acceptance criteria:** `explain_recommendation(league_id, player_id)` returns a text rationale whose claims trace to the pick's `ScoreComponents` fields; no audio path exists in the codebase; web search stays disabled unless explicitly flagged.

**Definition of done:**
- [ ] Typed tools registered; `explain_recommendation` reads `ScoreComponents`, emits prose.
- [ ] Text-only asserted (no voice/Realtime deps); assistant defaults keep paid/web features off.
- [ ] `[str]` file-search / web-search behind flags, documented as post-v1.

### 10.9 Cross-cutting calibration & gates (E1–E7)

Feed `config/engine.json` **before the draft**. E1–E5, E7 are **`[v1]`**; E6 is **`[str]`**.

| ID | What | Tier | Where |
|---|---|---|---|
| **E1** | **Flex RB/WR split via the top-60 method** — rank all RB+WR by non-PPR 12-team FFC ADP; the **top-60** are the startable pool (12 RB + 36 WR + 12 flex). `flex_RB = (#RB in top-60) − 12`, `flex_WR = (#WR in top-60) − 36`, so `flex_RB + flex_WR = 60 − 48 = 12`. **Re-measure DAILY;** non-PPR scarcity likely makes it **more RB-heavy than 8/4** — highest-value calibration. `[MEASURE]` | v1 | writes `EngineParams.flex_split` |
| **E2** | Calibrate **κ, the λ schedule, α, modifier caps** via the mock-draft backtest (Optuna), across **all 12 draft slots** and against **non-ADP** opponent models | v1 | design §7.E2 → `config/engine.json` |
| **E3** | Validate the **projection blend (simple average)** against 2021–2024 realized points under the **exact CBS map**; blend must beat the best single source; calibrate σ̂ by interval coverage | v1 | design §7.E3 |
| **E4** | **Capture-layer golden fixtures** once real CBS frames are observed; keep the **manual-paste fallback** for the `[UNVERIFIED]` transport | v1 | design §7.E4 |
| **E5** | **Schema-parity CI** — assert Pydantic (`models.py`) ⇄ Zod (`packages/shared`) field-for-field (new `ScoringTier`/`ScoringBonus`/`ScoreComponents` included) | v1 | `.github/workflows/ci.yml` |
| **E6** | **Simulated-league tournament** vs **VBD-only and ADP-only** baselines — the project's OWN efficacy proof (no solver exists in the literature) | **str** | design §7.E6 |
| **E7** | **Perf gate** — p95 `recompute` **< 2 s** (analytic **< 200 ms**) in CI | v1 | design §7.D |

**Per-manager tendency modeling `[str]`:** wire the append-only log **day one** (Stage 1); model once history accrues.

**Acceptance criteria:** E1 sets a measured `flex_split`; E2 writes calibrated κ/λ/α/caps into `config/engine.json`; E3 shows the blend beats the best single source on held-out seasons; E5 + E7 run in CI and gate merges.

**Definition of done:**
- [ ] E1 top-60 script + daily refresh; `flex_split` populated (documented as measured, not the 8/4 default).
- [ ] E2 Optuna study committed; params versioned in `config/engine.json`.
- [ ] E3 backtest report under the exact CBS scoring map; σ̂ coverage calibrated.
- [ ] E4 golden fixtures + manual-paste fallback test.
- [ ] E5 parity check + E7 perf gate wired into `.github/workflows/ci.yml`.
- [ ] E6 tournament harness stubbed `[str]`; log wired for per-manager modeling `[str]`.

### 10.10 v1 Definition of Done (release gate)

**v1 = live CBS picks → a decomposed, league-correct, risk-aware, flex-aware recommendation in the overlay within 2 s, on the $0 data tier, with calibrated params and crash-safe replay.**

- [ ] Stage 0 scaffold changes merged; E5 parity green.
- [ ] Stage 1 picks stream + crash-restart replay to exact state; no `webRequest`/`declarativeNetRequest`.
- [ ] Stage 2 `LeagueSettings` round-trips the exact CBS scoring map (DST dual tiers + K bonus) and the **verbatim roster** (WR/RB flex = WR-or-RB only); draft order read live, never inferred.
- [ ] Stage 3 warehouse (DuckDB + Parquet + SQLite) + crosswalk operational.
- [ ] Stage 4 $0 providers (Nflreadpy + FFC ADP + CBS-on-page) live; paid providers off.
- [ ] Stage 5 `GET /recommendation` returns a `ScoreComponents`-decomposed, tuned rec in **< 2 s**, against canonical baselines (RB≈22–24, WR≈40–42, QB/TE/K/DST≈13) and the **measured** flex split; strategy is anchor-RB + WR-breadth + late QB/TE + streamed DST(R16)/K(R17), never Zero-RB.
- [ ] Stage 6 overlay shows best pick + decomposition + survival % via `WS /recs/ws`.
- [ ] Stage 7 `explain_recommendation` narrates `ScoreComponents`; text-only.
- [ ] E1–E5, E7 satisfied; `config/engine.json` seeded pre-draft.
- [ ] Compliance recap (10.11) verified; forward-year (2027) outputs labeled ESTIMATED.

**Stretch backlog (post-v1):**

| Item | Home | Note |
|---|---|---|
| Rest-of-season Monte-Carlo **season simulator** → playoff/championship odds (**CP-SAT end-state**) | `engine/simulate.py`, `engine/optimize.py::optimize_roster` | true objective; CP-SAT off the hot path |
| **Monte-Carlo VONA** (`mc_rollouts ≈ 2000`) | `engine/opponents.py` | refinement over analytic Gaussian |
| **XGBoost residual projections** | `engine/projections.py` | over the blended μ |
| **Per-manager tendency modeling** | reads the append-only log | wire the log day one |
| **Offline RL audit** | backtest harness | policy sanity-check |
| Dashboard scenario depth; assistant file-search/web-search | `apps/web`, `assistant/tools.py` | behind flags |
| **E6 simulated-league tournament** | backtest | efficacy proof vs VBD-only / ADP-only |

### 10.11 Scope & compliance recap

Every stage above is scoped to a **personal, non-commercial, local-first** tool (ADR 0003; `docs/legal-and-compliance.md`): CBS data is read **only from the user's own authenticated session**, with **narrow host permissions** and **no `webRequest` / `declarativeNetRequest`**; nothing is redistributed. The whole v1 runs at **$0 besides AI usage** (paid providers stay **off** by default), and the assistant is **text-only (no voice/Realtime)**. The **immutable league settings** (`config/league.json`) govern every baseline and must never be paraphrased or changed — any agent loads that file before work and **surfaces, never silently resolves**, conflicts. Be honest about the ceiling: **no peer-reviewed optimal live snake-draft solver exists**, so efficacy is established only by the project's **own offline simulated-league tournament vs VBD-only and ADP-only baselines (E6)**, and all **forward-year (2027) outputs are ESTIMATED**.

---

## 11. Dev env, CI/CD, deployment & observability + end-to-end runbook

This section is the operator's manual: how to **run**, **ship**, **observe**, and **test the JAAFFL prototype end-to-end** on the `$0` data tier. It builds on the compute/latency plan (design §7.D) and the calibration/testing plan (design §7.E1–E7). Everything is local-first: the backend binds `127.0.0.1:8787`, paid providers stay off, and no CBS data leaves the machine (design §10.7). The league it serves is fixed and immutable (design §2, `config/league.json`): **Snake; 12 teams; draft order decided in-person then entered into CBS; Standard (non-PPR); 17 rounds; roster QB=1, RB=1, WR=3, WR/RB=1, TE=1, K=1, DST=1, Bench=8** (WR/RB flex is **WR-or-RB only**). The actual pick order is read **live from the CBS room — never inferred from team count**.

### 11.1 Local-first development environment

#### 11.1.1 Prerequisites

| Tool | Version | Pinned by | Why |
|---|---|---|---|
| Python | **3.12** | `.github/workflows/ci.yml` (`setup-python: "3.12"`); `requires-python >=3.11` | Backend engine + API |
| Node | **22** | `.nvmrc` (`22`), root `package.json` `engines.node >=22` | Web + extension |
| pnpm | **10.33.0** | root `package.json` `packageManager: pnpm@10.33.0` | JS workspace |
| uv | latest | `Makefile` (`uv … \|\| python -m …` fallback) | Fast Python installs/runs |
| GNU make | any | `Makefile` | Task runner |
| sqlite3 CLI | any | — | Inspect the draft-event / decision log (§11.4) |
| Playwright + Chromium | via `@playwright/test` | E4 capture job (§11.2.3) | MutationObserver fixture test (dev/CI only) |

> `uv` is optional but recommended — every Makefile target degrades to plain `python -m …` / `pip` if `uv` is absent, so a bare Python 3.12 + Node 22 + pnpm box also works.

#### 11.1.2 One-time setup

```bash
git clone <repo> && cd Project_JAAFFL
cp .env.example .env          # paid providers already default OFF
make setup                    # setup-backend (uv pip install -e '.[dev]' ‖ pip) + setup-js (pnpm install)
```

For the engine + warehouse (Stage 4–5) install the optional extras (the base install is intentionally light — `backend/pyproject.toml`):

```bash
cd backend && (uv pip install -e '.[dev,data,engine]' || python -m pip install -e '.[dev,data,engine]')
# add ,assistant for the text-only explainer (needs OPENAI_API_KEY)
```

#### 11.1.3 The `.env` story (paid providers OFF)

`cp .env.example .env`; the defaults are the `$0` tier. Do **not** commit `.env` (git-ignored; only `.env.example` is tracked). Keys below are real `jaaffl.config.Settings` fields (`config.py`) and lines in `.env.example`.

| Key | Default | Meaning |
|---|---|---|
| `JAAFFL_API_HOST` / `JAAFFL_API_PORT` | `127.0.0.1` / `8787` | Local bind; `Settings.jaaffl_api_host` / `.jaaffl_api_port` |
| `JAAFFL_LOG_LEVEL` | `INFO` | Structured-log verbosity (§11.4.1) → `Settings.jaaffl_log_level` |
| `JAAFFL_DATA_DIR` | `./data` | Root for SQLite + DuckDB + Parquet (§11.4) → `Settings.jaaffl_data_dir` |
| `JAAFFL_ENABLE_FANTASYPROS` | `false` | Paid injury/ECR upgrade — **off** |
| `JAAFFL_ENABLE_SPORTSDATAIO` / `_SPORTRADAR` | `false` | Commercial real-time — **off** |
| `JAAFFL_ENABLE_CBS_UNOFFICIAL_API` | `false` | Unofficial CBS adapter — **off** (see `docs/legal-and-compliance.md`) |
| `OPENAI_API_KEY` | *empty* | The one cost the prototype allows (AI usage); text-only, **no voice** |
| `JAAFFL_ASSISTANT_MODEL` | `gpt-4.1-mini` | Assistant model (`Settings.jaaffl_assistant_model`) |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8787` | Dashboard → backend (`apps/web/lib/api.ts`) |

**Rule (CONTRIBUTING.md):** any new data source ships a feature flag in `.env.example` + `jaaffl.config`, defaulted **off**. CI must never depend on a secret (§11.2.5).

#### 11.1.4 Run matrix (Makefile targets → ports)

| Command | Runs | Address | Notes |
|---|---|---|---|
| `make backend-dev` | `uv run jaaffl-api ‖ python -m jaaffl.api` (uvicorn factory `jaaffl.api.app:create_app`) | `http://127.0.0.1:8787` | `/health`, `/draft/events`, `/draft/ws`, `/recommendation`, **[ADD]** `/recs/ws`, **[ADD]** `/playbook` |
| `make web-dev` | `pnpm --filter @jaaffl/web dev` (Next.js) | `http://localhost:3000` | Reads `NEXT_PUBLIC_API_BASE_URL` |
| `make ext-dev` | `pnpm --filter @jaaffl/extension dev` | — | MV3 build in watch; load `apps/extension` unpacked in Chrome |
| `make lint` / `make fmt` | ruff check/format (Python) + `pnpm -r lint` / prettier (JS) | — | ruff mirrors the backend CI gate; CI's `js` job runs typecheck + test, not lint |
| `make test` | `pytest` + `pnpm -r test` | — | The same commands CI runs |

#### 11.1.5 Process topology (who talks to whom)

```mermaid
flowchart LR
  CBS["CBS draft room<br/>(your authenticated session)"] -->|MAIN-world 3-probe capture| ISO["Extension ISOLATED CS<br/>(de-dup by pick_number)"]
  ISO -->|WS /draft/ws (ingest)| BE["FastAPI 127.0.0.1:8787<br/>append→SQLite→recompute()"]
  BE -->|WS /recs/ws (push)| OVL["In-page overlay<br/>(Shadow DOM)"]
  BE -->|WS /recs/ws + REST| WEB["Next.js dashboard :3000"]
  BE <-->|read| WH[("DuckDB + Parquet + SQLite<br/>$JAAFFL_DATA_DIR")]
```

The three-probe capture is transport-agnostic (CBS transport is **UNVERIFIED**, design §7.G): (1) MAIN-world `document_start` monkeypatch of WebSocket/fetch/XHR, (2) framework-state read, (3) MutationObserver DOM fallback — de-duped by `pick_number`. The ISOLATED content script is the trust boundary and owns the localhost WebSocket; the service worker stays minimal (design §5/§7). `/draft/ws` is ingest; **[ADD]** `/recs/ws` is the backend→UI push channel (scaffold change 4) so the overlay updates within the `<2 s` budget without polling.

> **Definition of done — 11.1**
> - [ ] `make setup` succeeds on a clean box (Python 3.12 / Node 22 / pnpm 10.33.0).
> - [ ] `make backend-dev` serves `GET /health` → `{"status":"ok","version":"…"}` on `127.0.0.1:8787`.
> - [ ] `make web-dev` loads `:3000`; `make ext-dev` produces a loadable unpacked MV3 build.
> - [ ] `.env` copied from `.env.example`; every `JAAFFL_ENABLE_*` paid flag is `false`; no secret required to boot.

### 11.2 CI/CD — keep the two jobs green, add E5 / E7 / E4

**Keep unchanged** (`.github/workflows/ci.yml`): the `backend` job (`ruff check .` + `ruff format --check .` + `pytest -q`, `working-directory: backend`, `python -m pip install -e '.[dev]'`) and the `js` job (`pnpm install --frozen-lockfile` + `pnpm -r typecheck` + `pnpm -r test`, pnpm 10.33.0 / node 22). **Add three focused jobs** so the existing two stay fast and green.

New shared assets these jobs need:

| Path | Purpose |
|---|---|
| `tests/contracts/{league_settings,draft_event,recommendation}.json` | Canonical payloads — the **single source** both languages validate (design §7.B: "canonical example JSON fixtures for schema-parity CI") |
| `backend/scripts/export_json_schema.py` | Dumps `model_json_schema()` for `LeagueSettings`, `DraftEvent`, `RecommendedPick` (incl. new `ScoreComponents`), `Recommendation` → `packages/shared/schema/*.json` (committed) |
| `backend/tests/test_schema_parity.py` | `Model.model_validate(fixture)` for each canonical fixture |
| `packages/shared/test/contracts.test.ts` | Zod `.parse(fixture)` on the **same** files (script `test:contracts`) |
| `backend/tests/test_latency.py` | Worst-case `recompute()` benchmark, `@pytest.mark.perf` |
| `apps/extension/tests/` | `parse.ts` unit + three-probe de-dup + Playwright MutationObserver + manual-paste |

Register the perf marker in `backend/pyproject.toml` (extend the existing `[tool.pytest.ini_options]` block — keep `testpaths`/`asyncio_mode`):

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["perf: latency gate (design §7.E7) — excluded from the default backend job"]
```

Package scripts (add `vitest` + `@playwright/test` dev-deps to `apps/extension`, `vitest` to `packages/shared`):

```jsonc
// apps/extension/package.json → "test":       "vitest run"                              // parse + 3-probe de-dup + manual-paste UNIT tests → RIDE the js job's `pnpm -r test`
//                               "test:e2e":   "playwright test"                          // browser MutationObserver path → capture-e2e job
// packages/shared/package.json → "test:contracts": "vitest run test/contracts.test.ts"  // Zod .parse on the canonical fixtures → contracts job
```

> The extension `test` script must be a real unit runner (not the current stub echo) so the E4 unit suite actually executes under the existing `js` job's `pnpm -r test` — no YAML change needed for that portion.

#### 11.2.1 E5 — schema-parity job (Pydantic ⇄ Zod)

Two-sided cross-check (design §7.E5): (a) regenerate JSON Schema from Pydantic and `git diff --exit-code` (fails on drift vs the committed snapshot), and (b) round-trip the **same** canonical fixtures through Pydantic **and** Zod.

```yaml
  contracts:
    name: Schema parity (Pydantic ⇄ Zod)        # design §7.E5
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: pnpm/action-setup@v4
        with: { version: 10.33.0 }
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm }
      - name: Install backend
        working-directory: backend
        run: python -m pip install -e '.[dev]'
      - name: Install JS workspace
        run: pnpm install --frozen-lockfile
      - name: Export JSON Schema from Pydantic + fail on drift
        run: |
          python backend/scripts/export_json_schema.py --out packages/shared/schema
          git diff --exit-code -- packages/shared/schema
      - name: Round-trip canonical fixtures through Pydantic
        working-directory: backend
        run: pytest -q tests/test_schema_parity.py
      - name: Round-trip the SAME fixtures through Zod
        run: pnpm --filter @jaaffl/shared test:contracts
```

This is the mitigation for the "Contract drift (Zod vs Pydantic)" risk (design §7.G) and enforces the CONTRIBUTING rule that `packages/shared` (Zod) and `jaaffl.domain` (Pydantic) change together — including the four scaffold contract additions (`scoring_tiers`/`scoring_bonuses` on `LeagueSettings`, and `ScoreComponents` on `RecommendedPick`). The backend is editable-installed, so `python backend/scripts/export_json_schema.py` imports `jaaffl` from any cwd and writes to the repo-root `packages/shared/schema`.

#### 11.2.2 E7 — latency perf gate (`recompute()` p95)

Benchmarks the stateless hot path at its **worst case** — pick 1, ~300-player pool, horizon ~22, `candidate_cap≈180`, analytic VONA (design §7.D) — and asserts p95 against a budget. The **product SLO is `<200 ms` analytic / `<2 s` with MC** (design §7.D/§7.E7); the CI gate uses headroom (`JAAFFL_PERF_BUDGET_MS`, default 600) so shared-runner noise never false-reds while a real regression (a 3–10× blow-up) still trips it. Needs the `engine` + `data` extras.

```yaml
  latency:
    name: Latency perf gate (recompute p95)      # design §7.E7 / §7.D
    runs-on: ubuntu-latest
    defaults:
      run: { working-directory: backend }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install (engine + data extras)
        run: python -m pip install -e '.[dev,data,engine]'
      - name: Benchmark worst-case recompute() and assert p95
        env:
          JAAFFL_PERF_BUDGET_MS: "600"           # CI headroom; SLO is 200 ms analytic / 2 s MC
        run: pytest -q -m perf tests/test_latency.py
```

`test_latency.py` builds a synthetic worst-case `DraftContext` (≈300 players μ/σ/floor/ceiling; replacement baselines **RB≈22–24 / WR≈40–42 / QB·TE·K·DST≈13**; FFC ADP mean/SD), runs `recompute()` ≥200×, computes p50/p95, prints them, and `assert p95_ms < float(os.environ.get("JAAFFL_PERF_BUDGET_MS", 200))`. The MC path (`mc_rollouts≈2000`) is asserted `< 2000 ms` only when MC is enabled — analytic is the v1 hot path; MC VONA and the season simulator are **stretch** (design §7.F).

#### 11.2.3 E4 — capture-fixture tests (transport UNVERIFIED)

The CBS draft-room transport is **UNVERIFIED** (design §7.G) — these tests lock behavior once real frames are observed. The **unit** portion (`parse.ts`, three-probe de-dup by `pick_number`, manual-paste fallback) rides the existing `js` job via `pnpm -r test` (no YAML change — the extension `test` script now runs vitest over the new files). The **browser** portion (Playwright driving a saved draft-room HTML fixture through the `MutationObserver` path) needs a Chromium install, so it gets its own job:

```yaml
  capture-e2e:
    name: Capture fixtures (MutationObserver)     # design §7.E4
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 10.33.0 }
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm }
      - name: Install
        run: pnpm install --frozen-lockfile
      - name: Install Playwright Chromium
        run: pnpm --filter @jaaffl/extension exec playwright install --with-deps chromium
      - name: Golden-fixture DOM parse + de-dup + manual-paste
        run: pnpm --filter @jaaffl/extension test:e2e
```

Golden fixtures live in `apps/extension/tests/fixtures/` (captured frames JSON + saved room HTML). Until live frames exist, seed with a **synthetic** fixture and mark the real-transport cases `test.fixme` — honest about the UNVERIFIED boundary (design §7.G).

#### 11.2.4 Resulting `jobs:` map

```
backend  (unchanged)  ruff check + ruff format --check + pytest -q
js       (unchanged)  pnpm -r typecheck + pnpm -r test   ← E4 unit tests ride here
contracts   [ADD E5]  Pydantic⇄Zod parity + schema drift gate
latency     [ADD E7]  recompute() p95 vs budget
capture-e2e [ADD E4]  Playwright MutationObserver + manual-paste
```

#### 11.2.5 CI invariants

- **No secrets, ever.** All five jobs run on the `$0` tier with paid flags `false`; nothing reads `OPENAI_API_KEY` or provider keys. Provider tests use recorded/mock responses.
- **Keep it green:** new jobs are additive; a red is a real contract/latency/capture regression, not flake. `latency` uses a budget with headroom; `capture-e2e` `fixme`s unverified-transport cases.
- The workflow-level `concurrency` group (`ci-${{ github.ref }}`, `cancel-in-progress: true`) already cancels superseded runs across **all** jobs — the new jobs inherit it automatically.

> **Acceptance criteria — 11.2**
> - [ ] `backend` and `js` jobs unchanged and green.
> - [ ] `contracts` fails on any Pydantic↔Zod divergence or uncommitted schema drift; passes on the canonical fixtures.
> - [ ] `latency` prints p50/p95 and fails when analytic p95 exceeds the budget.
> - [ ] `capture-e2e` runs `parse.ts` + de-dup + manual-paste + the MutationObserver fixture green; the extension `test` script runs the unit suite under `pnpm -r test`.
> - [ ] No job references a secret; CI is reproducible on a fork.

### 11.3 Optional Vercel preview (dashboard only)

**Optional, personal-use, read-only, no secrets.** The backend is bound to `127.0.0.1` and is **not** reachable from Vercel, and a preview must never touch a real CBS session (compliance, design §10.7). So a preview runs the Next.js dashboard in a **mock mode** that renders canned fixtures — a purely visual preview of the board / tiers / survival panels.

- **Mock mode:** `NEXT_PUBLIC_JAAFFL_MODE=mock` makes `apps/web/lib/api.ts` serve `apps/web/mocks/*.json` (reuse `tests/contracts/recommendation.json`) instead of fetching `NEXT_PUBLIC_API_BASE_URL`. No backend, no network, no auth.
- **Project config** `vercel.json` (root = `apps/web`):

```json
{ "buildCommand": "pnpm --filter @jaaffl/web build",
  "installCommand": "pnpm install --frozen-lockfile",
  "framework": "nextjs",
  "env": { "NEXT_PUBLIC_JAAFFL_MODE": "mock" } }
```

- **No secrets in the preview** — only `NEXT_PUBLIC_*` (public by definition), no provider/AI keys. Disabling the preview changes nothing about v1.

> **Definition of done — 11.3**
> - [ ] Preview builds `@jaaffl/web` in `mock` mode and shows board/tiers/survival from fixtures.
> - [ ] No secret set on the Vercel project; no call to a real CBS session or localhost backend.
> - [ ] Preview is documented as optional and personal-use; disabling it changes nothing about v1.

### 11.4 Observability

Three signals, all local: **structured logs**, **per-pick timing metrics**, and a persistent **engine decision log** — plus a way to read the **SQLite draft-event log** by hand.

#### 11.4.1 Structured logging (levels via `JAAFFL_LOG_LEVEL`)

The backend already uses `structlog` (`api/app.py`, `ingest/__init__.py`). Add one config module in a new `obs/` subpackage and call it from `main()`:

```python
# backend/src/jaaffl/obs/logging.py   (NEW subpackage)
def configure_logging(level: str | None = None) -> None:
    """JSON logs to stdout, ISO timestamps, level from Settings.jaaffl_log_level (default INFO).
    DEBUG surfaces per-candidate MLV; INFO is one line per pick; WARNING for de-dup drops / fallbacks."""
```

Wire `configure_logging(get_settings().jaaffl_log_level)` at the top of `main()` in `jaaffl.api.app` (re-exported as `jaaffl.api.main`). Every line carries `league_id` and (on the hot path) `as_of_pick`.

#### 11.4.2 Per-pick latency + component timing

A tiny timer wraps each hot-path stage (design §7.D: survival → candidates → MLV → VONA/risk/cliff/modifiers → assemble):

```python
# backend/src/jaaffl/obs/metrics.py
class PickTimer:
    def stage(self, name: str) -> ContextManager[None]: ...   # times "survival"|"mlv"|"vona"|"risk"|"cliff"|"assemble"
    def as_dict(self) -> dict[str, float]: ...                 # {survival_ms, mlv_ms, ..., total_ms}
```

`jaaffl.engine.recommend.recompute(ctx: DraftContext, timer: PickTimer)` — the **stateless per-pick hot path** (design §7.D), invoked by the Stage-5 `recommend()` entrypoint in the same module — wraps each stage; on completion it emits one line and persists the timing with the decision (§11.4.3):

```json
{"event":"pick_timing","level":"info","ts":"2026-08-30T19:04:12.812Z","league_id":"cbs-123",
 "as_of_pick":25,"candidates":178,"survival_ms":1.9,"mlv_ms":34.7,"vona_ms":2.1,
 "risk_ms":0.4,"cliff_ms":0.3,"assemble_ms":1.2,"total_ms":40.6}
```

`total_ms` is the live proxy for the `<2 s` SLO (analytic target `<200 ms`); `mlv_ms` is the Hungarian (`scipy.optimize.linear_sum_assignment`) cost — the usual hot spot. The E7 gate (§11.2.2) is the offline enforcement of the same number.

#### 11.4.3 Engine decision log (persist `ScoreComponents` per rec)

Every recommendation persists its full decomposition so a pick is auditable and the assistant's `explain_recommendation` (design §7.F Stage 7) reads real numbers, not a re-derivation. `ScoreComponents` (scaffold change 3) carries `mlv, vona, risk_penalty, cliff_bonus, sigma, floor, ceiling, replacement_baseline, modifiers{}`, and the persisted columns reconstruct the canonical objective exactly (design §10.3):

```
Score(p) = MLV_p + κ·max(0, VONA_p) − λ(phase,slot)·σ̂_p + α·CliffBonus_p + Σ capped modifiers
```

Written to SQLite alongside the event log:

```sql
CREATE TABLE IF NOT EXISTS rec_log (
  seq            INTEGER PRIMARY KEY AUTOINCREMENT,
  league_id      TEXT NOT NULL,
  as_of_pick     INTEGER NOT NULL,
  rank           INTEGER NOT NULL,             -- 0 = recommended pick
  player_id      TEXT NOT NULL,
  score          REAL NOT NULL,
  mlv REAL, vona REAL, risk_penalty REAL, cliff_bonus REAL,
  sigma REAL, floor REAL, ceiling REAL, replacement_baseline REAL,
  modifiers_json TEXT,                         -- capped modifiers {bye_stack, handcuff, sos}, each ≤ ~3–5 pts
  timing_ms_json TEXT,                         -- PickTimer.as_dict()
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Signature (in the same append-only module as the event log):

```python
# backend/src/jaaffl/ingest/log.py
def append_rec(conn: sqlite3.Connection, rec: Recommendation, timing_ms: dict[str, float]) -> None: ...
    # writes one row per rec.ranked candidate (rank 0 = rec.best); each carries its ScoreComponents
```

The decision log mirrors to DuckDB for offline analysis (E2 tuning, E6 tournament; design §7.E). It is **analytics** — not part of crash-safe replay (that is the append-only `draft_event` log below).

#### 11.4.4 Inspecting the SQLite draft-event log (and crash-safe replay)

`DraftState` is a **fold over the append-only event log** (design §7 Step 7): ingest appends the event to SQLite **before** computing a rec, so a restart replays to the exact state. The log and the fold:

```sql
CREATE TABLE IF NOT EXISTS draft_event (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  league_id    TEXT NOT NULL,
  event_type   TEXT NOT NULL,                  -- DraftEventType value, e.g. 'pick_made'
  pick_number  INTEGER,                        -- CBS overall pick index (normalizes to DraftPick.overall); de-dup key for PICK_MADE
  payload_json TEXT NOT NULL,                  -- DraftEvent.data
  received_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(league_id, event_type, pick_number)   -- idempotent append (de-dup by pick_number)
);
```

```python
def append_event(conn: sqlite3.Connection, event: DraftEvent) -> int: ...   # returns seq; idempotent on pick_number
def fold_state(conn: sqlite3.Connection, league_id: str) -> DraftState: ...  # replay ORDER BY seq → exact DraftState
```

Files under `JAAFFL_DATA_DIR` (`./data`, git-ignored — `*.sqlite`, `*.duckdb`, `*.parquet`) map to the design's three stores: `data/jaaffl.sqlite` = **SQLite** (ACID app state + `draft_event` + `rec_log`); `data/warehouse.duckdb` = **DuckDB** (analytics/backtest); `data/parquet/…` = **Parquet** (nflverse snapshots).

Hand inspection:

```bash
# Event log (replay order) and de-dup check
sqlite3 data/jaaffl.sqlite "SELECT seq,event_type,pick_number FROM draft_event ORDER BY seq;"
sqlite3 data/jaaffl.sqlite "SELECT pick_number,COUNT(*) c FROM draft_event WHERE event_type='pick_made' GROUP BY pick_number HAVING c>1;"  -- expect 0 rows

# Recommended pick per round, with decomposition
sqlite3 data/jaaffl.sqlite "SELECT as_of_pick,player_id,score,mlv,vona,risk_penalty,cliff_bonus FROM rec_log WHERE rank=0 ORDER BY as_of_pick;"

# Latency distribution from persisted timings (offline p95)
sqlite3 data/jaaffl.sqlite "SELECT json_extract(timing_ms_json,'$.total_ms') ms FROM rec_log WHERE rank=0 ORDER BY ms;"
```

> **Definition of done — 11.4**
> - [ ] `configure_logging()` wired in `main()`; `JAAFFL_LOG_LEVEL=DEBUG` increases verbosity, `INFO` is one line per pick.
> - [ ] Every rec emits a `pick_timing` line with per-stage + `total_ms`.
> - [ ] Every rec persists a `rec_log` row per candidate with the full `ScoreComponents` + `timing_ms_json`.
> - [ ] `sqlite3` queries above return the event log, de-dup check (0 dup picks), and the decision log.
> - [ ] `backend/src/jaaffl/obs/{logging,metrics}.py` (NEW subpackage) and `backend/src/jaaffl/ingest/log.py` exist with the signatures above.

### 11.5 Round-by-round playbook in-product (design §10.4)

Surface the consolidated **R1–R17** playbook (design §10.4) in **both** UI surfaces from one canonical source, so the human strategy and the engine agree. This is the anchor/Hero-RB strategy for **Standard (non-PPR)** — **not** Zero-RB (counter-indicated in standard).

- **Single source:** the 8-band table lives in the new `config/engine.json` under `playbook` (faithful to design §10.4 — targets condensed, **λ tilts verbatim**), read by the backend and exposed at `GET /playbook`. Every row has the same four keys (`rounds`, `primary_target`, `why`, `risk`), mirroring §10.4's four columns:

```json
{ "playbook": [
  {"rounds":"R1-2","primary_target":"Anchor: 1–2 elite workhorse RBs","why":"RB is the scarce, steep-cliff position in non-PPR; Zero-RB is counter-indicated","risk":"floor (+0.2…+0.4)"},
  {"rounds":"R3-4","primary_target":"Second core RB/WR by MLV/VONA; grab an elite TE if one falls","why":"lock the scarce RB tier before it empties; begin WR accumulation","risk":"floor (+0.1…+0.3)"},
  {"rounds":"R5-6","primary_target":"Fill starting WRs (need 3 + WR/RB flex); heed VONA on runs","why":"WR value here is breadth — weight air-yards/red-zone over raw catch volume","risk":"~neutral"},
  {"rounds":"R7-9","primary_target":"Complete the nine; your QB lands here unless an elite fell","why":"QB baseline is shallow (QB13) so deferring costs little; prize rushing-QB upside","risk":"~neutral"},
  {"rounds":"R10-11","primary_target":"Bench insurance; handcuff your anchor RBs","why":"protect the starting lineup; RB injury churn makes handcuffs high-value","risk":"mild ceiling"},
  {"rounds":"R12-15","primary_target":"Upside swings; skew RB-heavy","why":"championships are won by ceiling; cheap lottery tickets; bench carries more RBs","risk":"ceiling (−0.2…−0.4)"},
  {"rounds":"R16","primary_target":"DST (stream)","why":"our scoring rewards it via BOTH points- and yards-allowed tiers","risk":"punt"},
  {"rounds":"R17","primary_target":"K (stream)","why":"least predictable; never reach; pick on team-total/dome/matchup","risk":"punt"} ] }
```

- **Overlay hint (v1):** a one-line banner above the recommended pick — `R{n} · {primary_target} · {risk}` — read live from `/recs/ws` and rendered in the Shadow-DOM overlay. The **round number** is `round = ((as_of_overall_pick − 1) // 12) + 1` — pure arithmetic (12 picks per round for **12 teams**); it does **not** infer the snake pick *order*, which is read live from the CBS room (design §2, §10.4). The λ tilt is reflected in the sign of `ScoreComponents.risk_penalty`.
- **Dashboard panel (v1-lite):** the full 8-row table rendered in `@jaaffl/web`, with the **current round-band highlighted** and a "standing rules" footer (measure value as **marginal gain to the optimal 9-man starting lineup** — the WR/RB flex filled by whichever of your best remaining **RB/WR** helps most; **VONA** decides take-now-vs-wait; never draft K/DST before R16/R17; treat forward-year (2027) outputs as **ESTIMATED** — design §10.4).

Both surfaces read the same `config/engine.json` payload, so the in-product guidance can never drift from the design.

> **Definition of done — 11.5**
> - [ ] `config/engine.json.playbook` matches design §10.4 (all 8 bands: `rounds`, `primary_target`, `why`, and λ tilts — tilts verbatim); `GET /playbook` returns it.
> - [ ] Overlay shows the correct band + λ tilt for the live round, derived from `as_of_overall_pick` (round number only; pick order read live).
> - [ ] Dashboard renders all 8 bands with the current one highlighted + standing-rules footer.

### 11.6 End-to-end test runbook (how the user tests the prototype)

Numbered path from a saved/mock CBS fixture (or a live personal draft) to a proven crash-safe replay. Uses the same `$0` tier as a real draft.

0. **Prereqs.** `make setup`; `cp .env.example .env` (paid flags `false`); install engine extras (`'.[dev,data,engine]'`). Confirm `config/engine.json` exists with calibrated params — `flex_split` (default **8 RB / 4 WR**, **measured live via the top-60 RB+WR method** and likely more RB-heavy in non-PPR), **κ = 0.5–0.8**, **α = 0.3–0.5**, and the **λ schedule** (R1–2 +0.2…+0.4 → R14–17 −0.3…−0.5) — from E1/E2 (design §7.E / §10.3), plus the `playbook` block (§11.5).
1. **Start the backend.** `make backend-dev` → `GET http://127.0.0.1:8787/health` returns `{"status":"ok","version":"…"}`. Logs are JSON at `JAAFFL_LOG_LEVEL`.
2. **Open the UI.** `make web-dev` (`:3000`); for a live draft, `make ext-dev` and load `apps/extension` unpacked, then open your CBS draft room. For a dry run, use the **saved fixture** in step 4 and the **manual-paste** panel — no CBS session needed.
3. **Pre-draft precompute.** Trigger the `DraftContext` build (projections μ/σ/floor/ceiling; league points under the **exact CBS Standard scoring map** — DST dual points-/yards-allowed tiers + K 50+ bonus; replacement baselines **RB≈22–24 / WR≈40–42 / QB·TE·K·DST≈13** + flex allocation **measured live via the top-60 method, §10.3**; tiers + cliff bonuses; FFC ADP mean/SD joined by canonical id — design §7.D). Confirm one `context_ready` log line.
4. **Stream picks from the fixture.** Replay a saved room: `POST` each frame to `/draft/events` (or push over `/draft/ws`) from `apps/extension/tests/fixtures/`, e.g. `backend/scripts/replay_fixture.py --league cbs-123`. Each pick appends to `draft_event` **before** any rec is computed (§11.4.4). Send a duplicate `pick_number` on purpose → it must be **de-duped** (0 duplicate rows).
5. **Overlay updates `<2 s`.** For each incoming pick the backend runs `recompute()` and pushes the decomposed rec over `/recs/ws`; the overlay shows best pick + its `ScoreComponents` (MLV, **κ·max(0,VONA)**, −λ(phase,slot)·σ̂, α·Cliff, **Σ capped modifiers**, survival %) + the round-band hint (§11.5). Verify the `pick_timing` line's `total_ms` is well under 2000 (analytic target `<200 ms`, design §7.D).
6. **Dashboard shows board / tiers / survival.** `:3000` renders the draft board + pick log, the Boris-Chen tier bands (GMM on ECR), and next-turn survival `S_j(N)=1−Φ((N−m_j)/s_j)` for candidates; the playbook panel highlights the current round.
7. **Assistant explains a rec.** With `OPENAI_API_KEY` set, ask the **text-only** assistant to explain the current pick; `explain_recommendation` reads the persisted `rec_log` `ScoreComponents` (§11.4.3) and returns prose grounded in the actual numbers (no re-derivation), honestly labeling any forward-year figure **ESTIMATED**.
8. **Crash mid-draft.** `kill -9 $(pgrep -f jaaffl.api)` (or Ctrl-\\) partway through the fixture — simulate the unrecoverable-if-wrong failure (design §7 Step 7).
9. **Prove crash-safe replay.** `make backend-dev` again. On boot, `fold_state(conn, "cbs-123")` replays the append-only `draft_event` log to the **exact** pre-crash `DraftState`; the next rec is regenerated. Assert equality:

```bash
# same pick count + same last pick before vs after the kill
sqlite3 data/jaaffl.sqlite "SELECT COUNT(*), MAX(pick_number) FROM draft_event WHERE event_type='pick_made';"
curl -s "http://127.0.0.1:8787/recommendation?league_id=cbs-123" | jq '.as_of_overall_pick, .ranked[0].player_id'
```

The reconstructed `as_of_overall_pick` and board must match the moment before step 8; then finish streaming the remaining picks and confirm the draft completes normally through R17.
10. **Review observability.** Inspect `draft_event` (replay order, no dup picks) and `rec_log` (one decomposed row per candidate + `timing_ms_json`); compute offline p95 (§11.4.4) and confirm it's under the 2 s SLO.

> **Runbook pass =** picks stream in → overlay decomposed rec `<2 s` → dashboard board/tiers/survival correct → assistant explains from persisted components → `kill -9` → identical state after replay.

### 11.7 Section acceptance criteria & Definition of done

**Acceptance criteria**

- [ ] A new engineer runs `make setup && make backend-dev && make web-dev` from this section alone and reaches a live `/health` + dashboard, paid providers off.
- [ ] CI keeps the original `backend` + `js` jobs and adds `contracts` (E5), `latency` (E7), `capture-e2e` (E4); all green; no secrets.
- [ ] E5 trips on any Pydantic↔Zod drift; E7 prints p50/p95 and enforces the budget; E4 covers `parse.ts` + de-dup + manual-paste + MutationObserver.
- [ ] Observability: JSON logs at `JAAFFL_LOG_LEVEL`, a `pick_timing` line + a `rec_log` `ScoreComponents` row per rec, and documented `sqlite3` inspection of the append-only event log.
- [ ] The §10.4 playbook is surfaced from one `config/engine.json` source in both overlay (round-band hint) and dashboard (full panel), with immutable settings (12 teams, 17 rounds, WR/RB-only flex, Standard/non-PPR) intact.
- [ ] The numbered end-to-end runbook (§11.6) passes, including `kill -9` → exact `fold_state` replay.
- [ ] Optional Vercel preview is mock-only, secret-free, and clearly optional.

**Definition of done**

- [ ] `.env.example` fully documents every flag; all `JAAFFL_ENABLE_*` paid providers default `false`.
- [ ] `.github/workflows/ci.yml` contains five jobs matching §11.2; `backend/pyproject.toml` has the `perf` marker; `apps/extension` runs unit tests via `test` (vitest) and `test:e2e` (Playwright); `packages/shared` has `test:contracts`.
- [ ] `tests/contracts/*.json`, `backend/scripts/export_json_schema.py`, `backend/tests/{test_schema_parity,test_latency}.py`, `packages/shared/test/contracts.test.ts`, and `apps/extension/tests/` exist and run in CI.
- [ ] `backend/src/jaaffl/obs/{logging,metrics}.py` (NEW subpackage) and `backend/src/jaaffl/ingest/log.py` (`append_event`, `fold_state`, `append_rec`) exist with the signatures above.
- [ ] `config/engine.json` includes the `playbook` block; `GET /playbook` and the `/recs/ws` push channel serve the overlay/dashboard.
- [ ] **Honesty kept explicit:** no peer-reviewed optimal live snake-draft solver exists — efficacy is proven only by the project's own offline simulated-league tournament vs **VBD-only** and **ADP-only** baselines (design §7.E6), not by vendor claims; forward-year (2027) outputs are **ESTIMATED**.
- [ ] **UNVERIFIED flags kept honest:** CBS transport golden fixtures are `fixme`-gated until real frames are captured (design §7.G); the E7 CI number is a regression budget, not a hardware guarantee; absolute latency depends on the box.

---

## 12. Risks, mitigations & sequenced task backlog

This section is the project's **risk register** and the **master execution backlog**. It turns the settled research (design §4–§10) and the architecture decisions (design §7.B, §7.C, §7.D, §7.E, §7.F, §7.G, §10.2, §10.3, §10.5, §10.6, §10.7) into a single dependency-ordered checklist a solo builder or an agent fleet can run straight through. It does **not** re-derive the research — every non-obvious "why" points back to design §N. Immutable league settings (§2 / `config/league.json`) are fixed inputs to every task and are never altered.

**Immutable inputs (verbatim — `config/league.json`, `immutable:true`; never paraphrase, re-order, or "optimize"):**

- Draft Type: Snake
- Teams: 12
- Draft Order: Decided in-person, then entered into CBS Sports system
- Scoring Format: Standard
- Draft Rounds: 17
- Roster Slots per Team: QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Derived (do not restate as new settings): 9 starters + 8 bench = 17 rounds; the **WR/RB flex is WR-or-RB ONLY (no TE/QB)**; **Standard = non-PPR** (0 pts/reception); the draft order is **read live from the CBS room — never inferred from team count**. League-wide starter demand (12 teams): QB12, TE12, K12, DST12; RB+WR startable pool = 12 RB + 36 WR + 12 flex = 60 of 108 total starters.

### 12.1 Risk register (risks & mitigations)

Extends design §7.G with an explicit **Likelihood** and an **Owner** (the track from §12.2 accountable for the mitigation landing). Scales: Severity/Likelihood ∈ {Low, Low-Med, Med, Med-High, High}. "Residual" = risk left after the mitigation ships. Owner tags each map to a backlog track in §12.2: **CAP** (capture/extension → Track F), **ING** (ingest/API/WS → Track G), **DATA** (warehouse/crosswalk → Track B), **PROV** (providers → Track C), **ENG** (league scoring + engine → Tracks D/E), **CAL** (calibration/DS → Track J), **QA** (testing/CI/parity/perf → Track K), **GATE** (compliance/honesty gate → `docs/legal-and-compliance.md`; enforced via Track L E6 + the §12.4 acceptance gate).

| Risk | Severity | Likelihood | Mitigation | Owner |
|------|----------|-----------|------------|-------|
| **CBS draft-room transport UNVERIFIED** — WS vs SSE vs polling, and the rendering framework, are unconfirmed (design §5, §7.B) | High | High | **Three-probe, transport-agnostic capture**: (1) MAIN-world `WebSocket`/`fetch`/`XHR` monkeypatch at `run_at:"document_start"`; (2) framework-state read (React fiber props); (3) `MutationObserver` DOM fallback in the isolated world. De-dup by `pick_number`. **Manual-paste fallback** always available. Golden-fixture regression tests (E4) the moment real frames are observed. Residual: Med. | CAP |
| **Free live-injury gap** — nflverse injury source lapsed post-2024 (design §5.C, §7.G) | Med | High | Read **CBS on-page injury designations** from the warehouse snapshot + official NFL report; optional **$5.99 FantasyPros** feed behind its off-by-default flag for a guaranteed source. Residual: Low-Med. | PROV |
| **$0 projection quality** — free blend may trail paid projections (design §4, §7.G) | Med | Med | Blend CBS on-page + ECR (`load_ff_rankings`) + xEP (`load_ff_opportunity`) **recomputed under the exact CBS Standard (non-PPR) scoring map**; **validate (E3)** vs 2021–2024 realized, require blend ≥ best single source; label all forward-year (2027) output **ESTIMATED**. Residual: Low-Med. | ENG / CAL |
| **MV3 service-worker lifecycle** — SW eviction kills any SW-owned socket (design §7.B, §7.G) | Med | High | The **isolated content script (not the SW) owns the localhost WS** to `127.0.0.1:8787`; SW stays minimal; heartbeat + auto-reconnect. Residual: Low. | CAP |
| **FFC ADP thin past R15 / off-season empty** — mocks are 15-round; `year=<off-season>` returns "No ADP data" (design §5.C, §7.C, §7.G) | Low-Med | High | Query the **current `season` only**; when ADP thins past ~180, **fall back to ECR** for deep-round survival; cache **daily**. Residual: Low. | PROV |
| **Calibration overfits ADP opponents** — tuning against ADP-driven bots rewards ADP-mimicry (design §7.E, §7.G) | Med | Med-High | Evaluate the tuned params **vs VBD-only and need-based opponent models** and across **all 12 draft slots**; **hold-out seasons**; success requires cross-slot generalization. Residual: Med. | CAL |
| **Flex RB/WR split default wrong** — hard-coded 8 RB / 4 WR is a guess; non-PPR is likely more RB-heavy (design §7.E, §10.3, §10.6 #1) | Med | Med-High | **Measure it live (E1)** from the top-60 non-PPR 12-team FFC ADP before the draft → `EngineParams.flex_split`; ship canonical 8 RB / 4 WR only as a bootstrap default. Residual: Low. | CAL |
| **Draft-order mis-read** — assuming a plain snake from team count corrupts the VONA horizon (immutable settings §2; design §5) | High | Low (High if guardrail skipped) | **Read the actual board/slot order live from the CBS room** (per `config/league.json`: `infer_from_team_count:false`). If the live order can't be read, the fallback is **manual entry of the actual in-person-decided order** via the paste UI — **never synthesize a snake from team count**. Unit-test order parsing against fixtures. Residual: Low. | CAP / ENG |
| **DST dual-tier + K-bonus scoring mis-parse** — CBS "standard" DST scores on **both** points- and yards-allowed brackets; K bonus at 50+ yards (design §5, §7.B) | Med | Med | Model `scoring_tiers` + `scoring_bonuses` in `LeagueSettings`; **read the scoring live (never hardcode)**; `league_points` round-trips the exact CBS map (Stage-2 exit test). Residual: Low. | ENG |
| **Contract drift (Zod ↔ Pydantic)** — two contract definitions diverge silently (design §7.B, §7.G) | Low-Med | Med | **Schema-parity CI (E5)**: emit JSON Schema from Pydantic, round-trip canonical fixtures through Pydantic + Zod, fail on divergence. Residual: Low. | QA |
| **Crash / disconnect mid-draft** — lost state during a live draft is unrecoverable in the moment (design §7 Step 7, §7.C) | High | Low | **Append-only SQLite event log**; ingest appends the event **before** computing a rec; `fold_state` replays to the exact state on restart (crash-safe). Residual: Low. | ING |
| **ToS / personal-use compliance** — automated CBS access could breach terms (design §5, §10.7, `docs/legal-and-compliance.md`) | High-if-ignored | Low | **Local-only**, user's **own authenticated CBS session**, no redistribution, **narrow host permissions** (CBS + `127.0.0.1:8787`), `scripting`+`storage` only, **no `webRequest`/`declarativeNetRequest`**, non-commercial license; **text-only** assistant (no voice/Realtime); compliance doc is the **gate**. Residual: Low. | GATE |
| **Cross-source ID mismatch** — CBS/FFC/nflverse name spellings diverge, breaking joins (design §5.C, §7.C) | Med | Med | Deterministic **nflverse-ID crosswalk** + **fuzzy name+team+pos fallback**; resolutions persisted in SQLite and inspected pre-draft. Residual: Low. | DATA |
| **`nflreadpy` ID-crosswalk fn name [VERIFY]** — `load_ff_playerids` vs `load_players` unconfirmed (design §7.C, §7.G, §10.6 #4) | Low | Med | **Confirm the exact name** from the nflreadpy load-functions reference in Track C; the fuzzy fallback covers CBS/FFC regardless of which resolves. Residual: Low. | PROV / DATA |
| **Latency blowup** — per-pick recompute misses the <2 s budget (design §7.D, §7.G) | Med | Low-Med | **Precompute → in-memory `DraftContext`**; stateless vectorized `recompute()` (mask → survival → top-K → Hungarian MLV → analytic VONA); **CI perf gate (E7)** asserts p95 < 2 s (analytic < 200 ms); MC is opt-in within budget. Residual: Low. | ENG / QA |
| **Overselling efficacy** — no peer-reviewed optimal live snake solver exists; vendor/practitioner claims are UNVERIFIED (design §4, §10.7) | Med | Med | Efficacy is proven **only** by the project's own **offline simulated-league tournament (E6)** vs VBD-only and ADP-only baselines; be explicit in docs/UI that outcomes are **estimated, not guaranteed**. Residual: Med. | CAL / GATE |
| **Engine myopia / noisy-K / stale-situation valuation** — one-step VONA is myopic across the snake turn; K/DST projection *noise* can inflate MLV; prior-year stats mislead after a team/role change (§3.10) | Med | Med | **R1** position-reliability μ-shrinkage (K/DST) + punt guard; **R2** turn-aware (2-pick) VONA (full MC = stretch); **R3** board-conditioned survival; **R4** opportunity/situation μ/σ layer (team change, vacated volume *regressed*, rookie competition, QB env, age/injury) — all **capped** and **Optuna-calibrated (E2/E3)**. PWOPR/XGBoost opportunity model = stretch. Residual: Med. | ENG / CAL |

### 12.2 Sequenced task backlog

Dependency-ordered and grouped into tracks that map onto the ROADMAP stages. Tags: **[v1]** = required for the deployable prototype; **[stretch]** = post-v1. **Rule:** Track A (contracts + `config/engine.json`) lands first because every other track imports those types; Tracks B–E (data → engine) can be built and unit-tested against fixtures **before** the live capture layer (Track F) is wired. Ship `config/engine.json` with the §10.3 canonical **defaults** first; Track J (E1/E2) then overwrites `flex_split` and the risk params with **measured/tuned** values before the real draft.

**Build order / critical path:**

```
A contracts ─┬─► B warehouse ─► C providers ─┬─► D scoring/replacement ─► E engine ─┐
             │                               │                                       ├─► G ingest+API+WS ─► H UI ─► I assistant
             └─► F extension (capture) ──────┴───────────────────────────────────────┘
                                                        J calibration (E1→E2→E3) feeds config/engine.json before E is "done"
                                                        K testing/CI wraps every track ·  L stretch simulator last
```

#### Track A — Contracts & scaffold changes  (foundational; ROADMAP cross-cutting) [v1]

The **four required scaffold changes** (design §7 / §10.5) + the new engine-params config. Keep Pydantic ⇄ Zod in lockstep.

- [ ] **[v1]** `packages/shared/src/league.ts`: add `ScoringTierSchema` (`{stat, brackets:{lower:number, upper:number|null, points:number}[]}`) and `ScoringBonusSchema` (`{stat, threshold:number, points:number}`); add `scoring_tiers` + `scoring_bonuses` to `LeagueSettingsSchema`. *(Scaffold change 1 — CBS "standard" DST scores on BOTH points- and yards-allowed tiers; K bonus at 50+ yards.)*
- [ ] **[v1]** `backend/src/jaaffl/domain/models.py`: add `ScoringTier`, `ScoringBonus` Pydantic models; add `scoring_tiers: list[ScoringTier]` + `scoring_bonuses: list[ScoringBonus]` to `LeagueSettings`. *(Scaffold change 1, mirror)*
- [ ] **[v1]** Migrate `nfl_data_py → nflreadpy` (Polars): rename `providers/nflverse.py` class to `NflreadpyProvider`; add `polars` + `nflreadpy` to the `data` extra; change the provider return type `pd.DataFrame → pl.DataFrame` across the protocol in `providers/base.py` (currently typed `pd.DataFrame`). *(Scaffold change 2)*
- [ ] **[v1]** `packages/shared/src/recommendation.ts`: add `ScoreComponentsSchema` and embed it as `components` on `RecommendedPickSchema`. `backend/src/jaaffl/domain/models.py`: add `ScoreComponents(mlv, vona, risk_penalty, cliff_bonus, sigma, floor, ceiling, replacement_baseline, modifiers: dict[str,float])` and `components: ScoreComponents` on `RecommendedPick`. *(Scaffold change 3)*
- [ ] **[v1]** `packages/shared/src/events.ts`: add required `pick_number` to capture events (cross-probe de-dup) + optional `source: "ws" | "fetch" | "xhr" | "framework" | "dom" | "paste"` (the three probes + manual-paste fallback). Mirror in the Python event model (`DraftEvent`). Re-export new types from `packages/shared/src/index.ts`.
- [ ] **[v1]** `backend/src/jaaffl/domain/models.py` / `providers/base.py`: add `Capability.EXPECTED_POINTS` (+ optional `Capability.DRAFT_PICKS`) to the provider capability enum (currently `{HISTORICAL_STATS, PROJECTIONS, ADP, RANKINGS, INJURIES}`).
- [ ] **[v1]** **NEW** `config/engine.json` + `EngineParams` model (loaded via `jaaffl.config`). Ship the canonical §10.3 defaults:

```json
{
  "version": 1,
  "kappa": 0.65,
  "alpha": 0.4,
  "flex_split": { "RB": 8, "WR": 4 },
  "lambda_schedule": { "R1-2": 0.30, "R3-6": 0.20, "R7-9": 0.0, "R10-13": -0.30, "R14-17": -0.40 },
  "slot_override": { "last_startable": "floor", "surplus": "ceiling" },
  "modifier_caps": { "bye_stack": 5, "handcuff_synergy": 5, "sos": 3 },
  "candidate_cap": 180,
  "mc_rollouts": 2000,
  "mu_refinement_cap_pct": 12,
  "projection_blend": "simple_average"
}
```

  Canonical ranges (design §10.3) the JSON instantiates as within-range point defaults: **κ ∈ 0.5–0.8**, **α ∈ 0.3–0.5**; **λ risk schedule** (floor-tilt λ>0, ceiling-tilt λ<0) **R1–2 +0.2…+0.4; R3–6 +0.1…+0.3; R7–9 ≈0; R10–13 −0.2…−0.4; R14–17 −0.3…−0.5**, slot override dominates phase (last open startable slot → floor; surplus/stash → ceiling); **μ-refinement cap ±10–15%**, **modifier caps ≤~3–5 pts**, **candidate_cap≈180**, **mc_rollouts≈2000**, **projection blend = simple average**; **flex split default 8 RB / 4 WR — MEASURE LIVE via the top-60 method (E1)**.

- [ ] **[v1]** `backend/src/jaaffl/config.py`: add `jaaffl_season`, `jaaffl_enable_ffc=True`, `jaaffl_ffc_scoring="standard"`, `jaaffl_ffc_teams=12`, `jaaffl_engine_params_path`, `jaaffl_candidate_cap=180`, `jaaffl_mc_rollouts=2000`; load `EngineParams` from `config/engine.json`. **Do not touch `config/league.json` (immutable:true).**
- [ ] **[v1]** **NEW** canonical example JSON fixtures under `packages/shared` for schema-parity CI (feeds E5 / Track K).

#### Track B — Data warehouse  (ROADMAP Stage 3 — Data warehouse) [v1]

- [ ] **[v1]** `backend/src/jaaffl/data/warehouse.py`: implement the **DuckDB (analytics/backtest) + Parquet (nflverse snapshots) + SQLite (ACID app state + append-only draft-event log)** layout (design §7 Step 7); materialize nflverse pulls to Parquet, hold hot tables in memory.
- [ ] **[v1]** `backend/src/jaaffl/data/crosswalk.py`: deterministic nflverse-ID join + **fuzzy name+team+pos fallback**; persist resolutions in SQLite.
- [ ] **[stretch]** Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if this ever goes multi-user (ROADMAP Stage 3).

#### Track C — $0 data providers  (ROADMAP Stage 4 — External data tiers) [v1]

- [ ] **[v1]** `providers/nflverse.py` → **`NflreadpyProvider`** with caps `{HISTORICAL_STATS, RANKINGS, EXPECTED_POINTS}`: history→`load_player_stats`, ECR→`load_ff_rankings`, xEP→`load_ff_opportunity`. **Confirm the exact ID-crosswalk fn name (`load_ff_playerids`/`load_players`) [VERIFY]** and map IDs via the crosswalk.
- [ ] **[v1]** **NEW** `providers/ffc.py` (`FantasyFootballCalculatorProvider`), cap `ADP`: `GET https://fantasyfootballcalculator.com/api/v1/adp/{scoring}?teams=12&year={season}` (default `{scoring}=standard` per `jaaffl_ffc_scoring`, i.e. non-PPR; `teams=12`) → `{canonical_id: {adp, stdev, high, low, times_drafted, bye}}`; **cache daily**; current-season only; ECR fallback past ~180.
- [ ] **[v1]** **NEW** `providers/cbs_onpage.py` (`CbsOnPageProvider`), caps `{PROJECTIONS, INJURIES, RANKINGS}` + authoritative `LeagueSettings`: **read the CBS snapshot from the warehouse** (fed by the extension) — **not** a network fetch.
- [ ] **[v1]** `providers/registry.py`: register the three $0 providers; keep `providers/fantasypros.py` and SportsDataIO/Sportradar as **disabled stubs (off by default)**; wire the FantasyPros injury feed behind the **$5.99** opt-in flag (`jaaffl_enable_fantasypros`).

#### Track D — League scoring & replacement  (ROADMAP Stage 2 — Normalize league settings / Stage 5) [v1]

- [ ] **[v1]** `backend/src/jaaffl/league/scoring.py`: extend `league_points` to evaluate **linear rules + tiered brackets (DST points- AND yards-allowed) + threshold bonuses (K 50+ yards)** against the live CBS Standard (non-PPR) map — read live, never hardcode.
- [ ] **[v1]** `backend/src/jaaffl/league/replacement.py`: keep `starter_demand`; implement `replacement_values` = rank by league points within position, valued at **dedicated demand + allocated flex share** (WR-or-RB-only flex; split from `EngineParams`). Target canonical baselines **RB≈22–24, WR≈40–42, QB/TE/K/DST≈13** (design §10.3); add **BEER/man-games blended toward VOLS** at the scarce top end.

#### Track E — Transparent engine pipeline  (ROADMAP Stage 5 — Transparent draft engine) [v1 core]

Pipeline order S0→S4 per design §7.C / §10.2. All read the precomputed `DraftContext`.

- [ ] **[v1]** `engine/projections.py::build_projections` *(S0)*: blend CBS on-page + ECR + xEP [+ optional FP], **all recomputed under the exact CBS Standard (non-PPR) scoring map**; return `{stat_line, mu, sigma, floor, ceiling}` with σ/floor/ceiling from cross-source spread; apply `mu_refinement_cap_pct` (±10–15%).
- [ ] **[v1]** **NEW** `engine/tiers.py` *(S4)*: `sklearn.mixture.GaussianMixture` on ECR → `tier` + `cliff_bonus` (Boris-Chen-style tiers; add `scikit-learn` to the `engine` extra).
- [ ] **[v1]** `engine/optimize.py`: **NEW** `marginal_lineup_value(owned, candidate, replacement, flex_mask, params) -> float` = gain to the optimal 9-starter lineup via `scipy.optimize.linear_sum_assignment` (Hungarian, **WR-or-RB-only flex mask — no TE/QB**, replacement-filled base lineup, base cached + dominance shortcut). Keep `optimize_roster` as CP-SAT (OR-Tools) reserved for **stretch**.
- [ ] **[v1]** `engine/opponents.py::pick_probabilities` *(S2)*: closed-form analytic survival `S_j(N) = 1 − Φ((N − m_j)/s_j)` from FFC ADP mean `m_j` + stdev `s_j` (vectorized NumPy), horizon read from the **live board**; optional per-manager priors hook.
- [ ] **[v1]** `engine/recommend.py::recommend(context: DraftContext, state: DraftState) -> list[RecommendedPick]` *(orchestrator)*: assemble `Score(p) = MLV_p + κ·max(0,VONA_p) − λ(phase,slot)·σ̂_p + α·CliffBonus_p + Σ capped modifiers`; populate `ScoreComponents`; sort; **analytic VONA is the v1 default**.
- [ ] **[v1]** Precompute path: build the in-memory `DraftContext` (projections μ/σ/floor/ceiling, league points, replacement baselines + flex allocation, tiers + cliff bonuses, FFC ADP mean/SD joined by canonical id, crosswalk); stateless per-pick `recompute()` (design §7.D).
- [ ] **[stretch]** `engine/simulate.py::simulate_drafts`: vectorized **Monte-Carlo VONA** for `E[best available]` when analytic is insufficient (mc_rollouts≈2000).

#### Track F — CBS sync extension (capture layer — highest risk)  (ROADMAP Stage 1 — CBS sync layer) [v1]

- [ ] **[v1]** `apps/extension/manifest.json`: add a third `content_scripts` entry → **NEW** `src/inject/cbs-main.inject.ts` with `"world":"MAIN"`, `"run_at":"document_start"`; add the `scripting` permission (currently only `storage`); keep host perms **narrow** (CBS + `127.0.0.1:8787`); **no `webRequest`/`declarativeNetRequest`**; overlay in a **Shadow DOM**.
- [ ] **[v1]** **NEW** `apps/extension/src/inject/cbs-main.inject.ts` (MAIN world): three probes — (1) `WebSocket` monkeypatch (wrap `send` + `message`); (2) `fetch`/`XHR` monkeypatch; (3) framework-state read (React fiber props); relay via `window.postMessage({source:"jaaffl-main", ...})`.
- [ ] **[v1]** `apps/extension/src/content/cbs-draft.content.ts` (ISOLATED — **trust boundary**): receive frames + `MutationObserver` on board/ticker; **de-dup by `pick_number`**; validate via `parse.ts`; own and open the localhost WS (`transport.ts`); mount the overlay.
- [ ] **[v1]** `apps/extension/src/lib/parse.ts`: implement `parseLeagueSettings` (roster slots, **flex eligibility = WR-or-RB only**, **full scoring incl. DST points- AND yards-allowed tiers + K 50+ bonus**, team count, **draft order read from the board**) + `parseDraftEvent`; golden-fixture-driven.
- [ ] **[v1]** `apps/extension/src/content/cbs-league.content.ts`: capture league metadata/settings + snapshot to the warehouse (feeds `CbsOnPageProvider`).
- [ ] **[v1]** `apps/extension/src/lib/transport.ts` + `src/background/service-worker.ts`: content-script-owned WS with heartbeat/reconnect; SW stays minimal. Choose bundler **@crxjs/vite-plugin** (WXT fallback).
- [ ] **[v1]** **Manual-paste fallback** UI in the overlay for the UNVERIFIED transport (also the manual entry point for the actual in-person draft order).

#### Track G — Ingest, API & WS push  (ROADMAP Stage 1 backend + Stage 6 push) [v1]

- [ ] **[v1]** `backend/src/jaaffl/ingest/cbs.py`: implement `normalize_league_settings` / `normalize_draft_state`.
- [ ] **[v1]** **NEW** `backend/src/jaaffl/ingest/log.py`: append every `DraftEvent` to the SQLite log (monotonic `seq`, `pick_number`) **before** engine work; `fold_state(events) -> DraftState` rebuilds state (crash-safe replay).
- [ ] **[v1]** `backend/src/jaaffl/api/app.py`: keep `POST /draft/events` + `WS /draft/ws` (ingest) + `GET /recommendation` (REST); **ADD `WS /recs/ws`** push channel *(Scaffold change 4)* and **NEW** `GET /league/{id}` (returns `LeagueSettings`). Ingest handler flow: **append log → fold state → `recommend` → broadcast on `/recs/ws`**.

#### Track H — Two-surface UI  (ROADMAP Stage 6 — Two-surface UI) [v1 overlay / v1-lite web]

- [ ] **[v1]** `apps/extension/src/overlay/overlay.ts`: subscribe `WS /recs/ws`; render **best pick + top-5 with the `ScoreComponents` decomposition + next-turn survival %** (the "WHY").
- [ ] **[v1-lite]** `apps/web/app/page.tsx` + `apps/web/lib/api.ts`: consume `GET /recommendation` + `WS /recs/ws`; board (AG Grid), distributions/tiers (ECharts), survival curves. Read-only; secondary to the overlay for v1.
- [ ] **[stretch]** Manager-tendency panel as draft history accrues; deeper scenario analytics.

#### Track I — AI assistant (wire early, integrate last)  (ROADMAP Stage 7 — AI assistant) [v1-lite]

- [ ] **[v1-lite]** `backend/src/jaaffl/assistant/tools.py::dispatch`: wire typed tools to warehouse/engine; `explain_recommendation` returns the `ScoreComponents` breakdown **in prose**; **text-only** (Responses API; no voice/Realtime per ADR 0003).
- [ ] **[stretch]** File-search over league rules; web-search for injuries.

#### Track J — Calibration & data science  (design §7.E; ROADMAP cross-cutting) [v1]

Runs **before the live draft** and writes back into `config/engine.json`.

- [ ] **[v1]** **NEW** `scripts/calibrate_flex_split.py` **(E1 — highest-value):** rank RB+WR by non-PPR 12-team FFC ADP; fill 12 dedicated RB + 36 dedicated WR, next 12 by ADP = flex (top-60 total); `flex_RB=(#RB in top-60)−12`, `flex_WR=(#WR in top-60)−36` → overwrite `EngineParams.flex_split`. **Honest caveat: likely more RB-heavy than 8 RB / 4 WR in non-PPR — measuring is the point.**
- [ ] **[v1]** **NEW** `scripts/tune_engine_params.py` **(E2):** Optuna over (κ, λ-table, α, caps, flex_split) maximizing mean starting-lineup value **across all 12 slots**; opponents = ADP+noise **and** non-ADP (VBD-only, need-based) to avoid self-reference → write `config/engine.json`.
- [ ] **[v1]** **NEW** `scripts/validate_projections.py` **(E3):** backtest μ_p vs 2021–2024 realized (recomputed under the CBS Standard map); MAE/RMSE/Spearman of blend vs each single source; **require blend ≥ best single source**; calibrate σ_p by interval coverage (~80% inside the 80% band).

#### Track K — Testing, fixtures, schema-parity, perf & CI  (design §7.E; ROADMAP cross-cutting) [v1]

- [ ] **[v1]** **E4 — capture regression:** save observed frames as **golden fixtures**; unit-test `parse.ts` + three-probe **de-dup by `pick_number`**; **Playwright** drives a saved draft-room HTML fixture for the `MutationObserver` path; test the **manual-paste fallback**.
- [ ] **[v1]** **E5 — schema-parity CI:** emit JSON Schema from Pydantic; round-trip canonical payloads through Pydantic + Zod; fail on divergence.
- [ ] **[v1]** **E7 — latency perf gate:** benchmark `recompute()` worst case (pick 1, ~300-player pool, horizon ~22); assert **p95 < 2 s** (analytic < 200 ms).
- [ ] **[v1]** `.github/workflows/ci.yml`: backend `ruff check` + `ruff format --check` + `pytest`; js `pnpm -r typecheck` + `pnpm -r test`; add the E5 parity job and the E7 perf gate. Wire `make test` / `make lint` / `make fmt`.

#### Track L — Efficacy proof & stretch simulator  (design §7.E, §7.F stretch; ROADMAP Stage 5 tail) [stretch]

- [ ] **[stretch]** **E6 — engine offline evaluation (the only efficacy gate):** simulated-league tournament (our agent at every slot vs ADP opponents); report mean starting-lineup points + (stretch) MC playoff/championship odds **vs VBD-only and ADP-only baselines**; success = ≥ baselines with significance across slots. **No peer-reviewed optimal live snake solver exists — this is the project's own validation, not a vendor claim.**
- [ ] **[stretch]** Rest-of-season **Monte-Carlo season simulator** → playoff/championship odds (CP-SAT end-state in `engine/optimize.py::optimize_roster`); reuse `simulate_drafts`.
- [ ] **[stretch]** XGBoost residual projections; per-manager tendency modeling (wire the append-only log day one, model once history accrues); offline RL **audit/benchmark** only.

### 12.3 Top-priority tunables & open items (critical path to a calibrated draft)

Ordered from design §10.6 — the shortest path to a draft-ready engine. Each maps to a backlog task above.

1. **[v1]** **Measure the flex RB/WR split** (E1 / Track J) → `EngineParams.flex_split`. *Highest-value calibration; likely more RB-heavy than 8 RB / 4 WR in non-PPR.*
2. **[v1]** **Calibrate κ (0.5–0.8), the λ schedule, α (0.3–0.5), and modifier caps** (E2 / Track J) across all 12 slots and vs non-ADP opponents.
3. **[v1]** **Validate the projection blend** (E3 / Track J) vs 2021–2024 under the exact CBS Standard map; blend must beat the best single source; calibrate σ by coverage.
4. **[v1]** **Confirm the `nflreadpy` ID-crosswalk fn name** (`load_ff_playerids`/`load_players`) `[VERIFY]` (Track C); fuzzy fallback covers CBS/FFC regardless.
5. **[v1]** **Capture-layer golden fixtures** once real CBS frames are observed (E4 / Track K); keep the **manual-paste fallback** for the UNVERIFIED transport.
6. **[v1]** **Injury freshness:** wire CBS on-page injury designations (Track C); optionally enable the $5.99 FantasyPros feed behind its flag.
7. **[stretch]** **Prove efficacy offline** (E6 / Track L) vs VBD-only and ADP-only baselines — the project's own validation gate, since none exists in the literature.
8. **[v1]** **Calibrate the round-aware refinements** (§3.10 / E2–E3 / Track J): `reliability_shrinkage` (K/DST noise), `vona_horizon_picks` (turn-aware), `board_survival_weight` (β), and `situation_adjust` caps — co-tuned with κ/λ/α across all 12 slots; validate that K/DST never rank #1 before their stream round and that opportunity-based μ beats prior-year extrapolation for team/role changes.

### 12.4 Acceptance criteria

- [ ] The **risk register** covers every risk enumerated in the deliverable spec and design §7.G, each with **Severity, Likelihood, a concrete mitigation, a named Owner, and a residual level**.
- [ ] The **backlog is dependency-ordered**: no task precedes a task it depends on (Track A contracts before all; B→C→D→E before G wiring; E1/E2 before the engine is "done").
- [ ] Every backlog item is **tagged [v1] or [stretch]**, names an **exact repo path**, and states a **concrete action** (schema field, function signature, config key, or endpoint).
- [ ] The **four required scaffold changes + `config/engine.json`** are the first items and are explicitly Pydantic ⇄ Zod paired.
- [ ] Backlog tracks **map onto the ROADMAP stages** (Stage 1 CBS sync, Stage 2 normalize settings, Stage 3 warehouse, Stage 4 external data tiers, Stage 5 engine, Stage 6 UI, Stage 7 assistant + cross-cutting).
- [ ] The **top-priority tunables/open items** (flex split, κ/λ/α, projection validation, crosswalk fn name, golden fixtures, efficacy proof) each appear and cross-reference a backlog task.
- [ ] **Immutable settings are untouched** — no task alters `config/league.json` or the §2 values; every reference to them is **verbatim** (Snake; 12 teams; in-person→CBS order; Standard/non-PPR; 17 rounds; QB1/RB1/WR3/WR-RB1/TE1/K1/DST1/Bench8; flex WR-or-RB only).

### Definition of done — "the backlog is complete + ordered"

- [ ] A builder or agent can execute the checklist **top-to-bottom** and reach the **v1 definition of done** (design §7.F): live CBS picks → decomposed, league-correct, risk-aware, flex-aware recommendation in the overlay within **2 s**, on the **$0 data tier**, with **calibrated params** and **crash-safe replay**.
- [ ] All **[v1]** tasks are enumerated with paths + actions; all **[stretch]** tasks (season simulator, MC-VONA, XGBoost residuals, per-manager modeling, RL audit) are separated out and clearly deferred.
- [ ] Each risk's **Owner tag resolves to a backlog track** (per the §12.1 legend), so mitigation work is traceable to a task.
- [ ] The section is **self-contained**: no re-reading of the research is required to execute it (all "why" links resolve to design §N), and every path has been verified against the repo (`backend/src/jaaffl/**`, `packages/shared/src/**`, `apps/extension/src/**`, `apps/web/app/**`, `config/**`, `scripts/**` [new], `.github/workflows/ci.yml`).

---

## Appendix A — Consolidated round-by-round playbook

A slot-agnostic round-band guide for this **12-team, Standard (non-PPR), 17-round snake** with roster
QB1/RB1/WR3/(WR-RB)1/TE1/K1/DST1/Bench8. The engine adapts to the **actual** draft order (read live from CBS —
never assumed) and to the board; this table is the human-readable strategy the engine encodes (design §10.4).
Targets are *positions/profiles*, not named players. **This playbook is surfaced in-product** (overlay hint +
dashboard "Playbook" panel — §11).

| Round(s) | Primary target | Why (this league) | Risk (λ) |
|---|---|---|---|
| **R1–2** | **Anchor: 1–2 elite workhorse RBs** (take an elite WR / rare elite TE only if MLV clearly says so) | RB is the scarce, steep-cliff position in non-PPR; top-end RB marginal value is the highest-leverage move; **Zero-RB is counter-indicated** | floor-tilt (+0.2…+0.4) |
| **R3–4** | **Second core piece**: best RB *or* WR by MLV/VONA; aim for ~2 RB + 1–2 WR by end of R4; grab an **elite TE** here if one falls | Lock the scarce RB tier before it empties; begin WR accumulation; elite-TE edge over TE12 can beat WR1-over-WR24 | floor-tilt (+0.1…+0.3) |
| **R5–6** | **Fill starting WRs** (you need 3 + a WR/RB flex): best-value RB/WR; heed **VONA** during position runs | WR value here is *breadth*; weight air-yards/aDOT/deep & red-zone targets over raw catch volume | ~neutral |
| **R7–9** | **Complete the starting nine**: your **QB** lands here (a top-8-ish QB) unless an elite fell; keep adding WR/RB; last shot at a startable TE if you punted | QB baseline is shallow (QB13) → deferring costs little; prioritize rushing-QB upside | ~neutral |
| **R10–11** | **Bench insurance**: safer bye/injury cover for your starters; **handcuff your anchor RBs** | Protect the starting lineup first; RB injury churn (~27% full-season) makes handcuffs high-value | mild ceiling |
| **R12–15** | **Upside swings** (ceiling-tilt): young breakout WRs, high-upside backup RBs with standalone value, optional 2nd QB/TE if streaming-averse; **skew RB-heavy** | Championships are won by ceiling; cheap lottery tickets; bench should carry more RBs than WRs | ceiling (−0.2…−0.4) |
| **R16** | **DST** (stream target) | Draft one DST facing a weak/low-total offense in Wks 1–3; our scoring rewards it via **both** points- and yards-allowed tiers | punt |
| **R17** | **K** (stream target) | Least predictable position; never reach; pick on team-total/dome/matchup | punt |

**Standing rules the engine enforces:** measure value as **marginal gain to your optimal 9-man starting lineup**
(the WR/RB flex is filled by whichever of your best remaining RB/WR helps most); use **VONA** to decide
*take-now-vs-wait* (high urgency on RB, low on WR); never draft K/DST before R16/R17; treat forward-year (2027)
outputs as **ESTIMATED**.

---

## Appendix B — Published luxury UI mockups

Three self-contained, theme-aware (light + dark), WCAG-AA HTML mockups of the "**The Draft Room**" design system
— a quant terminal with the poise of a private club (warm ink + brass, editorial serif + monospaced numerals).
They are immediately viewable/testable and are the visual contract for §6:

| Surface | What it shows | Link |
|---|---|---|
| **Design system / style tile** | Design tokens (theme-aware palette, type scale, spacing, radii, elevation, motion), the component kit (position chips, reserved status pills, buttons, Score-Components bars, the recommended-pick card), and a CVD-validated position palette + value-curve. | https://claude.ai/code/artifact/e85311a6-cc55-4c8b-b3f4-3a34ec50cbe8 |
| **In-draft overlay** (primary surface) | The recommended pick + score, the decomposed **why** (MLV / VONA / risk / tier-cliff), next-turn survival %, the positional-run alert, and the top-5 — glanceable under a live draft clock. | https://claude.ai/code/artifact/93986f24-fe3d-47d5-b93a-d004dd2a57a2 |
| **Analytics dashboard** | Draft board + pick log, positional value curves / tiers, survival curves, manager-tendency panels, and a scenario-comparison strip. | https://claude.ai/code/artifact/b276d135-0d2e-472a-a269-2f6a3a8c17af |

Source files live under [`design/mockups/`](../design/mockups/) (`style-tile.html`, `overlay.html`,
`dashboard.html`). They are static mockups (illustrative data); the production surfaces are the extension overlay
(§5–§6) and the Next.js dashboard (§6).
