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

> ## 📍 Status — 2026-07-23 (verified against code + merged PRs #1–#17)
>
> **Stages 0–6 core are built, merged, and green** (backend + JS test suites pass). The live
> **$0 recommendation path works end-to-end**: real nflverse player universe → transparent engine
> → decomposed pick pushed to the overlay over `WS /recs/ws`. What remains is the **Stage 7 AI
> assistant** (OpenAI wiring needs an owner key), the **dashboard analytics panels** (`GET /state`
> + board/pick-log/curves), the **calibration scripts** (E1/E2/E3 — the engine ships on priors
> without them), and the clearly-deferred **stretch** items (MC-VONA, CP-SAT season sim, XGBoost,
> per-manager modeling, E6 efficacy tournament). The only hard gate on *real CBS data* is the
> owner's one record-mode capture session — everything today runs on synthetic fixtures + the
> manual-paste fallback. Owner-only tasks: [`docs/owner-manual-todo.md`](docs/owner-manual-todo.md).

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
- [~] **[stretch]** Monte Carlo end-of-draft roster simulation (`jaaffl.engine.simulate`) *(stubbed:
      `NotImplementedError`; analytic VONA is the shipped v1 default)*
- [~] **[stretch]** Constrained roster optimization via OR-Tools CP-SAT
      (`jaaffl.engine.optimize::optimize_roster`) *(stubbed: `NotImplementedError`)*
- [ ] **[stretch]** Only then: XGBoost residual models, injury-risk calibration, 2027 aging curves
- [x] Treat 2027 outputs as **ESTIMATED** unless a forward-year vendor feed is licensed *(policy
      enforced)*

## Stage 6 — Two-surface UI

- [x] Thin in-page overlay: best pick / next-turn risk / why (`apps/extension` overlay)
- [~] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`) *(live
      recommendation feed wired; board / pick-log / value-curve / survival panels pending — this
      backlog)*
- [ ] **AG Grid removed by design** (deep-research: overkill for a 204-cell static board);
      **ECharts** distributions/trends/scenarios still pending

## Stage 7 — AI assistant (wire early, integrate last)

- [~] Typed function tools for DB queries, league-state summaries, news lookups (`jaaffl.assistant`)
      *(tool schemas exist; `dispatch` is a stub — being wired now for the non-OpenAI parts)*
- [ ] OpenAI Responses API: function calling + file search + optional web search *(needs an owner
      `OPENAI_API_KEY`)*
- [ ] **Text-only.** Voice / Realtime is explicitly out of scope for the prototype (see ADR 0003)

## Cross-cutting

- [ ] Playwright kept for testing / emergency draft-room recovery (not the production path)
- [~] Compliance guardrails enforced in code & docs (see `docs/legal-and-compliance.md`)
