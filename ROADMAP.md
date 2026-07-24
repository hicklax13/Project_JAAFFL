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

> ## 📍 Status — 2026-07-23 (verified against code; branch `feat/post-v1-unblocked`)
>
> **Stages 0–6 core are built and green** (backend + JS suites pass). The live **$0 recommendation
> path works end-to-end**: real nflverse player universe → transparent engine → decomposed pick
> pushed to the overlay over `WS /recs/ws`.
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
> only hard gate on *real CBS data* is the owner's one record-mode capture session. Owner-only
> tasks: [`docs/owner-manual-todo.md`](docs/owner-manual-todo.md).

## Stage 1 — CBS sync layer

- [x] MV3 extension that runs only on CBS fantasy league/draft pages (`apps/extension`)
- [x] Content scripts extract league metadata + live pick events; normalize to shared schema
      *(code + de-dup complete; real CBS field/selector vocabulary is synthetic until the owner
      capture session — tracked in owner-manual-todo)*
- [x] Stream normalized events to the localhost backend (`jaaffl.api`, `jaaffl.ingest`)
- [x] **Decided against `webRequest`/`declarativeNetRequest`** — replaced by the 3-probe MAIN-world
      capture (WebSocket + `fetch`/XHR monkeypatch, React-fiber framework read, `MutationObserver`
      fallback); cookies API not used

## Stage 2 — Normalize league settings

- [~] Parse CBS roster slots, flex eligibility, scoring rules, team count, keeper/dynasty
      flags, and draft order from the live room / settings pages (`jaaffl.league`)
      *(scoring model + JAAFFL2025 values complete; live CBS settings-page parse is capture-blocked)*
- [x] Never assume snake order from league size — read the actual draft board *(enforced in
      `parse.ts` + engine horizon; order comes from the board / manual-paste, never inferred)*
- [x] Persist every league snapshot for self-owned historical analysis *(snapshot-every-settings
      into the warehouse, PR #7)*

## Stage 3 — Data warehouse

- [x] DuckDB + Parquet + SQLite local warehouse (`jaaffl.data`)
- [x] Stable player/team/league IDs and crosswalks (CBS, NFL, FantasyPros, nflverse)
- [ ] **[stretch]** Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if multi-user

## Stage 4 — External data tiers

- [x] Provider protocol + registry (`jaaffl.providers`)
- [x] **$0 prototype tier (default):** nflverse / nflfastR historical stats (free) + **FFC ADP** +
      CBS on-page projections/rankings/ADP read via the extension from the user's session
- [ ] **[opt-in, off by default]** Paid tier: FantasyPros rankings/projections/ADP/news/injuries
      *(disabled stub present; needs an owner key + enable flag)*
- [ ] **[out of scope for the prototype]** Commercial tier: SportsDataIO / Sportradar real-time,
      behind the same interface *(disabled stubs present)*

## Stage 5 — Transparent draft engine

- [x] Exact CBS scoring translation + replacement values + tier breaks (`jaaffl.league`)
- [x] Projection ensemble (`jaaffl.engine.projections`)
- [x] Opponent pick-probability model — analytic survival (`jaaffl.engine.opponents`)
- [x] Marginal Lineup Value via Hungarian assignment (`jaaffl.engine.optimize`) — the v1 flex-aware
      optimizer the engine actually uses
- [x] **[stretch]** Draft simulator + agents + MC-VONA (`jaaffl.engine.simulate`) — `simulate_draft`
      (full snake to completion), the behavioral/Score agents, and `simulate_drafts` (E[best
      available]); analytic VONA remains the shipped v1 hot-path default *(needs `engine-stretch`)*
- [x] **[stretch]** Constrained roster optimization via OR-Tools CP-SAT
      (`jaaffl.engine.optimize::optimize_roster`) — the season-simulator end-state ILP *(needs
      `engine-stretch`)*
- [ ] **[stretch]** Only then: XGBoost residual models, injury-risk calibration, 2027 aging curves
- [x] Treat 2027 outputs as **ESTIMATED** unless a forward-year vendor feed is licensed *(policy
      enforced)*

## Stage 6 — Two-surface UI

- [x] Thin in-page overlay: best pick / next-turn risk / why (`apps/extension` overlay)
- [x] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`) *(live
      recommendation feed, **draft board & pick-log** via `GET /state`, and the **value-curve +
      survival-curve** analytics panels via `GET /analytics` — all done; manager-tendency panel
      deferred until ≥1 recorded draft accrues `manager_tendencies` rows)*
- [x] **AG Grid removed by design** (deep-research: overkill for a 204-cell static board);
      distributions/trends render as **bespoke accessible SVG** (no ECharts dependency)

## Stage 7 — AI assistant (wire early, integrate last)

- [x] Typed function tools for DB queries, league-state summaries, news lookups (`jaaffl.assistant`)
      *(dispatch wired: `explain_recommendation` renders `ScoreComponents` prose via
      `explain_pick`, `league_summary` folds settings+state; `query_warehouse`/`player_news` stay
      NotImplementedError until the LLM loop)*
- [ ] OpenAI Responses API: function calling + file search + optional web search *(the only
      key-gated piece — needs an owner `OPENAI_API_KEY`)*
- [ ] **Text-only.** Voice / Realtime is explicitly out of scope for the prototype (see ADR 0003)

## Cross-cutting

- [~] **Calibration (Track J)** — `jaaffl.calibrate` + `scripts/`: **E1** flex-split
      (`calibrate_flex_split.py`), **E3** projection-validation (`validate_projections.py`), and
      **E2** param tuning (`tune_engine_params.py` — Optuna study + no-regression gate; `--real`
      builds a precompute-backed pool), and the **E6** efficacy tournament (`run_tournament.py` —
      our agent vs VBD-only / ADP-only baselines) all done + run live. A large offline real-data E2
      study (many trials/seeds) is the remaining calibration follow-up
- [ ] Playwright kept for testing / emergency draft-room recovery (not the production path)
- [~] Compliance guardrails enforced in code & docs (see `docs/legal-and-compliance.md`)
