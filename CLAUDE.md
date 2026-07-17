# CLAUDE.md — project memory & required reading

**JAAFFL** is a local-first, personal-use assistant for a **CBS Sports** fantasy football
**live snake draft**. Read this file and the persistent league memory **before any work**.

## ⛳ Persistent league memory (read first — do not paraphrase or change)

The league configuration is fixed and memorialized in **[`config/league.json`](config/league.json)**.
Load it before any draft-system work and compute all baselines against *this* roster.

**League settings (verbatim, authoritative):**

- **Draft Type:** Snake
- **Teams:** 12
- **Draft Order:** Decided in-person, then entered into CBS Sports system
- **Scoring Format:** Standard
- **Draft Rounds:** 17
- **Roster Slots per Team:** QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Derived: 9 starters + 8 bench = 17 roster slots = 17 rounds. Flex (`WR/RB`) is **WR or RB only**
(no TE). Standard = **non-PPR**. Draft order is **not** a plain snake inferred from team count —
read the real order from the CBS room.

> Any agent that touches draft logic MUST honor the `agent_usage_contract` in
> `config/league.json`: treat these values as fixed, baseline VOR against this exact roster,
> and surface (never silently change) conflicts.

## Key documents

- **[`docs/implementation-plan.md`](docs/implementation-plan.md)** — the **execution-ready build
  plan** (phased, testable): system architecture + the four scaffold changes, database / engine /
  providers / extension specs, the luxury UI/UX design system + published mockups, calibration /
  testing / evaluation, deployment, and a sequenced task backlog. **Start here to build.**
- **[`docs/draft-system-design.md`](docs/draft-system-design.md)** — the comprehensive draft
  strategy + system design + build plan (research, reasoning, architecture, recommendations).
- **[`docs/live-draft-recording-guide.md`](docs/live-draft-recording-guide.md)** — owner's
  **step-by-step** guide to recording a live CBS draft (install, launch, the record-mode buttons).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`ROADMAP.md`](ROADMAP.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`docs/legal-and-compliance.md`](docs/legal-and-compliance.md) — CBS/provider guardrails.
- [`docs/owner-manual-todo.md`](docs/owner-manual-todo.md) — owner-only tasks (CBS record-mode
  capture, opt-in keys) deferred to the end of each phase.
- [`docs/research/cbs-fantasy-football-draft-tool.md`](docs/research/cbs-fantasy-football-draft-tool.md)
  — original feasibility research.

## Scope reminders (see ADR 0003)

- Personal-use prototype, **$0 out-of-pocket besides AI usage** (free data: nflverse + CBS
  on-page; paid providers opt-in/off). Text-only assistant — **no voice**.

## Dev quickstart

`make setup` · `make backend-dev` (FastAPI on 127.0.0.1:8787) · `make web-dev` · `make test`
· backend lint/format via `ruff`; JS via `tsc`. See `CONTRIBUTING.md`.
