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

## Stage 1 — CBS sync layer

- [~] MV3 extension that runs only on CBS fantasy league/draft pages (`apps/extension`)
- [~] Content scripts extract league metadata + live pick events; normalize to shared schema
- [~] Stream normalized events to the localhost backend (`jaaffl.api`, `jaaffl.ingest`)
- [ ] `webRequest` traffic observation; cookies API only if strictly necessary

## Stage 2 — Normalize league settings

- [~] Parse CBS roster slots, flex eligibility, scoring rules, team count, keeper/dynasty
      flags, and draft order from the live room / settings pages (`jaaffl.league`)
- [ ] Never assume snake order from league size — read the actual draft board
- [ ] Persist every league snapshot for self-owned historical analysis

## Stage 3 — Data warehouse

- [~] DuckDB + Parquet + SQLite local warehouse (`jaaffl.data`)
- [~] Stable player/team/league IDs and crosswalks (CBS, NFL, FantasyPros, nflverse)
- [ ] Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if multi-user

## Stage 4 — External data tiers

- [~] Provider protocol + registry (`jaaffl.providers`)
- [~] **$0 prototype tier (default):** nflverse / nflfastR historical stats (free) +
      CBS on-page projections/rankings/ADP read via the extension from the user's session
- [ ] Optional paid tier (opt-in, off by default): FantasyPros rankings/projections/ADP/news/injuries
- [ ] Commercial tier (out of scope for the prototype): SportsDataIO / Sportradar real-time,
      behind the same interface

## Stage 5 — Transparent draft engine

- [~] Exact CBS scoring translation + replacement values + tier breaks (`jaaffl.league`)
- [~] Projection ensemble (`jaaffl.engine.projections`)
- [~] Opponent pick-probability model (`jaaffl.engine.opponents`)
- [~] Monte Carlo end-of-draft roster simulation (`jaaffl.engine.simulate`)
- [~] Constrained roster optimization via OR-Tools CP-SAT (`jaaffl.engine.optimize`)
- [ ] Only then: XGBoost residual models, injury-risk calibration, 2027 aging curves
- [ ] Treat 2027 outputs as **ESTIMATED** unless a forward-year vendor feed is licensed

## Stage 6 — Two-surface UI

- [~] Thin in-page overlay: best pick / next-turn risk / why (`apps/extension` overlay)
- [~] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`)
- [ ] AG Grid Community for tables, ECharts for distributions/trends/scenarios

## Stage 7 — AI assistant (wire early, integrate last)

- [~] Typed function tools for DB queries, league-state summaries, news lookups (`jaaffl.assistant`)
- [ ] OpenAI Responses API: function calling + file search + optional web search
- [ ] **Text-only.** Voice / Realtime is explicitly out of scope for the prototype (see ADR 0003)

## Cross-cutting

- [ ] Playwright kept for testing / emergency draft-room recovery (not the production path)
- [ ] Compliance guardrails enforced in code & docs (see `docs/legal-and-compliance.md`)
