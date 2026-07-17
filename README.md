# JAAFFL — CBS Fantasy Football Live Draft Assistant

A local-first assistant that connects to a live **CBS** fantasy football draft, reads
league settings and pick-by-pick draft state in real time, and produces transparent,
league-specific pick recommendations backed by projections, opponent modeling, and
draft simulation.

> **Status:** repository scaffold. This is the foundational structure for the build
> described in [`docs/research/cbs-fantasy-football-draft-tool.md`](docs/research/cbs-fantasy-football-draft-tool.md).
> Most modules are typed stubs that map 1:1 to the [roadmap](ROADMAP.md); they define
> the contracts and package boundaries, not final implementations.

## What it does

During a CBS draft, JAAFFL answers one question on every pick: **which available player
maximizes the expected quality of your final roster under _your league's exact settings_?**
It does this with a transparent, auditable pipeline rather than a black-box model:

1. **Projection ensemble** — blends historical NFL production (nflverse, free) with
   CBS's own on-page projections/rankings (read from your authenticated session) and
   optional paid fantasy projections (FantasyPros) plus injury/context features.
2. **League translation** — parses your CBS scoring + roster rules and converts projected
   statlines into league points, replacement (VORP) baselines, and positional scarcity.
3. **Opponent model** — estimates who gets picked before your next turn from ADP,
   expert-consensus dispersion, and prior-draft manager tendencies.
4. **Simulation + optimization** — Monte Carlo draft rollouts scored by a constrained
   roster optimizer, optionally extended to season/playoff-odds simulation.

## Architecture at a glance

```
        CBS draft room (user's authenticated browser session)
                          │  live pick + settings events
                          ▼
   ┌─────────────────────────────────────┐
   │  apps/extension  (MV3 browser ext)   │  reads DOM/network, normalizes events,
   │  content scripts · overlay · sw      │  renders a thin in-draft overlay
   └───────────────┬─────────────────────┘
                   │  normalized events (packages/shared contracts)
                   ▼  http/ws → localhost
   ┌─────────────────────────────────────┐        ┌───────────────────────────┐
   │  backend  (Python · FastAPI)         │◀──────▶│  data warehouse           │
   │  ingest · league · engine · assistant│        │  DuckDB · SQLite · Parquet│
   └───────────────┬─────────────────────┘        └───────────────────────────┘
                   │  recommendations + analytics (REST/ws)      ▲
                   ▼                                             │ pluggable providers
   ┌─────────────────────────────────────┐        ┌───────────────────────────┐
   │  apps/web  (Next.js dashboard)       │        │ nflverse · FantasyPros ·  │
   │  board · projections · scenarios     │        │ SportsDataIO · Sportradar │
   └─────────────────────────────────────┘        └───────────────────────────┘
```

The extension, backend, and web app all speak the same normalized vocabulary defined
once in [`packages/shared`](packages/shared). Data providers sit behind a single
interface so free/personal and licensed/commercial feeds are swappable at runtime.

## Repository layout

| Path                | Language   | Responsibility                                                             |
| ------------------- | ---------- | -------------------------------------------------------------------------- |
| `backend/`          | Python     | FastAPI companion service, data warehouse, draft engine, AI assistant      |
| `apps/extension/`   | TypeScript | Manifest V3 CBS sync layer + in-draft overlay                              |
| `apps/web/`         | TypeScript | Next.js analytics dashboard                                                |
| `packages/shared/`  | TypeScript | Shared event/league/recommendation schemas (Zod) used across the JS side  |
| `data/`             | —          | Local warehouse artifacts (git-ignored)                                     |
| `docs/`             | —          | Research report, ADRs, legal & compliance notes                            |

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit together and
[`ROADMAP.md`](ROADMAP.md) for the dependency-ordered build plan.

## Quickstart

Prerequisites: **Python ≥ 3.11**, **Node ≥ 22**, **pnpm ≥ 10**. `uv` is recommended for
the Python side but not required.

```bash
cp .env.example .env          # fill in provider keys as you enable them
make setup                    # install backend + JS workspace deps
make backend-dev              # run the FastAPI companion on 127.0.0.1:8788
make web-dev                  # run the Next.js dashboard
make ext-dev                  # build the extension in watch mode, then load unpacked
```

Run `make help` for the full task list.

## Scope & design posture

This is a **personal-use prototype**. Explicit scope for the current phase:

- **Personal use only.** Not a commercial or shared product (see the compliance note below).
- **$0 out-of-pocket besides AI usage.** The prototype runs entirely on free data: the
  **nflverse** open historical stack plus **CBS's own on-page** projections/rankings/ADP,
  read from your authenticated session. The only spend is your AI credits for the assistant.
  Paid feeds (FantasyPros Premium, SportsDataIO, Sportradar) are **opt-in and off by
  default** — the provider interface lets you enable them later without touching domain code.
- **No voice.** The AI assistant is **text-only**; the Realtime/voice feature is out of scope.

Everything is **local-first**: it runs on your machine with zero required cloud spend, using
CBS data only from your own authenticated session.

⚠️ **Before using CBS data, read [`docs/legal-and-compliance.md`](docs/legal-and-compliance.md).**
CBS's terms restrict automated access and commercial exploitation. This project is
structured for personal, user-authorized use; a commercial track requires licensed data
feeds and must not depend on CBS scraping.

## License

**Personal, non-commercial.** See [`LICENSE.md`](LICENSE.md) — the license mirrors the
personal, non-commercial posture required by CBS and the data providers this project uses
(see the compliance note above). Commercial use requires deliberate relicensing and licensed
data feeds.
