# 2. Local-first, extension-based, polyglot-monorepo architecture

Date: 2026-07-15

## Status

Accepted

## Context

The [research report](../research/cbs-fantasy-football-draft-tool.md) concludes that (a)
CBS lacks a dependable modern public API and restricts automated access, (b) a live draft
assistant needs the freshest possible draft-room state, and (c) the tool should be
lowest-cost for personal use while leaving a clean upgrade path to a commercial product.
The system spans a browser extension, a data/analytics/optimization backend, and an
analytics dashboard — naturally polyglot (TypeScript + Python).

## Decision

1. **CBS sync via a Manifest V3 browser extension** running in the user's authenticated
   session, streaming normalized events to a **localhost backend**. Playwright is retained
   for testing/recovery; the unofficial CBS API adapter is behind an interface, disabled by
   default.
2. **Local-first data stack**: DuckDB + Parquet + SQLite. The domain schema is kept stable
   enough to graduate to PostgreSQL `jsonb` + Redis Streams if the project goes multi-user.
3. **Providers behind one interface**, toggled by config. The $0 prototype tier
   (nflverse + CBS on-page data) is the default; FantasyPros and commercial feeds
   (SportsDataIO/Sportradar) are opt-in and off by default. See ADR 0003 for prototype scope.
4. **Transparent engine first**: projections → league translation/VORP → opponent model →
   Monte Carlo + CP-SAT optimization, before any residual ML. No end-to-end RL drafter.
5. **Polyglot monorepo**: Python backend at `backend/` (standalone, `src` layout); a pnpm
   workspace for `apps/extension`, `apps/web`, and `packages/shared`. Normalized contracts
   are defined once per side (Zod + Pydantic) and kept in sync.

## Consequences

- Zero required cloud spend for the personal MVP; CBS exposure is limited to
  user-authorized session data (see `../legal-and-compliance.md`).
- The engine stays auditable and adaptable when league scoring changes.
- Two schema definitions (JS/Python) must be updated together — a documented convention.
- The pnpm workspace deliberately excludes `backend/` so Node tooling doesn't try to manage
  the Python package.

## Alternatives considered

- **Headless Playwright as the production sync path** — heavier, easier for CBS to break,
  worse for user trust. Kept for testing/recovery only.
- **Depending on the deprecated CBS API** — brittle after login changes; best-effort
  fallback only.
- **Streamlit/Dash for the UI** — fastest to prototype but outgrown by a low-latency,
  extension-integrated live-draft product. React/Next.js chosen for the main surface.
