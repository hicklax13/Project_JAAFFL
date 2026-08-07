# Architecture

This document describes how the repository is organized and how the components
communicate. The _why_ behind these choices lives in the
[research report](docs/research/cbs-fantasy-football-draft-tool.md) and the
[ADRs](docs/adr/); this is the concrete map of the code.

## Principles

1. **Local-first.** The MVP runs entirely on the user's machine. No required cloud
   services, no server-side credential storage. CBS data comes only from the user's own
   authenticated browser session.
2. **One shared vocabulary.** Normalized draft events, league settings, and
   recommendations are defined once (Zod on the JS side in `packages/shared`, Pydantic on
   the Python side in `jaaffl.domain`) and kept in sync. Every component speaks it.
3. **Transparent before clever.** The draft engine is an auditable pipeline
   (projections → league translation → opponent model → simulation/optimization) before
   any residual ML is layered on. See the roadmap ordering.
4. **Providers behind an interface.** Every external data source implements a single
   provider protocol and is toggled by config. Free/personal feeds (nflverse, FantasyPros)
   and licensed/commercial feeds (SportsDataIO, Sportradar) are interchangeable, and the
   unofficial CBS API adapter can be disabled at runtime.

## Components

### `apps/extension/` — CBS sync layer (Manifest V3)

Runs only on CBS fantasy league and draft pages. Content scripts extract league settings
and live pick events from the authenticated page (DOM + observed network traffic),
normalize them into the shared event schema, and stream them to the localhost backend. A
thin overlay renders the current recommendation, tier breaks, and next-turn risk beside
the live board. See [`apps/extension/README.md`](apps/extension/README.md).

### `backend/` — Python companion service

A FastAPI service bound to `127.0.0.1`. It is the brain of the system, organized into
subpackages that map to roadmap stages:

| Package            | Roadmap stage | Responsibility                                                       |
| ------------------ | ------------- | -------------------------------------------------------------------- |
| `jaaffl.domain`    | —             | Pydantic models: the shared vocabulary (mirror of `packages/shared`) |
| `jaaffl.config`    | —             | Typed settings loaded from environment (`.env`)                      |
| `jaaffl.api`       | 1             | HTTP/WebSocket endpoints; receives draft events, serves recs         |
| `jaaffl.ingest`    | 1–2           | Normalize raw CBS payloads into domain events                        |
| `jaaffl.league`    | 2             | CBS scoring parser, replacement (VORP) values, positional scarcity   |
| `jaaffl.data`      | 3             | DuckDB/SQLite/Parquet warehouse and cross-source ID crosswalks       |
| `jaaffl.providers` | 4             | Provider protocol + nflverse/FantasyPros/... adapters                |
| `jaaffl.engine`    | 5             | Projection ensemble, opponent model, simulation, optimizer           |
| `jaaffl.assistant` | 7             | Typed function tools for the AI assistant                            |

### `apps/web/` — Next.js dashboard

The richer analytics surface: draft board, projection distributions, manager-tendency
panels, and scenario comparison. Reads from the backend over REST/WebSocket. Intended
stack: Next.js App Router + AG Grid Community + ECharts + TanStack Virtual.

### `packages/shared/` — shared contracts

Zod schemas and inferred TypeScript types for the normalized `DraftEvent`, `LeagueSettings`,
and `Recommendation`. Imported by both the extension and the web app so the wire format is
defined in exactly one place on the JS side.

## Data flow

```
extension content script
  → normalize to DraftEvent (packages/shared)
    → POST/ws  →  jaaffl.api
      → jaaffl.ingest (validate, persist raw + normalized)
        → jaaffl.data (warehouse snapshot)
        → jaaffl.engine.recommend(draft_state, league_settings)
          ├─ jaaffl.engine.projections   (uses jaaffl.providers + jaaffl.data)
          ├─ jaaffl.league               (scoring + replacement values)
          ├─ jaaffl.engine.opponents     (pick probabilities)
          └─ jaaffl.engine.simulate/optimize
      → Recommendation
        → overlay (extension)  and  dashboard (apps/web)
```

Every league snapshot is persisted locally from first use, so the system builds its own
long-term manager-tendency dataset instead of depending on CBS history remaining
accessible.

## Boundaries & conventions

- The Python backend is **not** part of the pnpm workspace. `pnpm-workspace.yaml` only
  globs `apps/*` and `packages/*`; `backend/` is a standalone Python package (`src` layout).
- The JS packages share config through the workspace root and depend on `@jaaffl/shared`
  by workspace protocol.
- Provider adapters must never be imported directly by the engine — the engine depends on
  the `jaaffl.providers` protocol only, so sources stay swappable.
