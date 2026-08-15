# CLAUDE.md — project memory & required reading

**JAAFFL** is a local-first, personal-use assistant for a **CBS Sports** fantasy football
**live snake draft**. Read this file and the persistent league memory **before any work**.

## 🚨 DRAFT DAY — Saturday, 2026-08-22 at 5:00 PM Eastern

**This is the deadline every remaining task is measured against.** The JAAFFL2025 live draft is
**Saturday 22 August 2026, 17:00 America/New_York** (= `2026-08-22T21:00:00Z`). The owner stated
it as "5:00pm EST"; on that date Eastern is **EDT (UTC−04:00)**, not EST — the authoritative value
is the **wall clock, 5:00 PM Eastern**. Do not re-derive it from the literal string "EST" or you
will be an hour early. Machine-readable copy: `config/league.json` → `league.draft_day`.

### ⛔ `JAAFFL_MY_TEAM_ID` is a DRAFT-DAY action — do not "fix" it before then

The draft order is **decided in person on draft day** and only then entered into CBS. The owner's
slot and team number are therefore **unknowable in advance**. `JAAFFL_MY_TEAM_ID` in `.env` is
**empty on purpose** until 2026-08-22 and is set on the day, once the owner reads his team number
off the CBS board.

- An empty `JAAFFL_MY_TEAM_ID` before draft day is **EXPECTED**, not a defect. Do not fill it with
  a guess, a placeholder, or a value inferred from anything.
- `scripts/preflight.py` **exiting 1** with `basis=degraded_no_slot` before draft day is therefore
  the **correct** behaviour, not a bug to chase.
- A **mock/rehearsal** draft is the exception: there you set it to whatever slot the mock lobby
  gives you, purely to exercise the pipeline. That value is disposable and must be cleared or
  overwritten on draft day.

## ⛳ Persistent league memory (read first — do not paraphrase or change)

The league configuration is fixed and memorialized in **[`config/league.json`](config/league.json)**.
Load it before any draft-system work and compute all baselines against _this_ roster.

**League settings (verbatim, authoritative):**

- **Draft Type:** Snake
- **Teams:** 12
- **Draft Order:** Decided in-person, then entered into CBS Sports system
- **Scoring Format:** Custom (non-PPR) — JAAFFL2025 owner-confirmed values (typed map: `backend/src/jaaffl/league/defaults.py::jaaffl_scoring`)
- **Draft Rounds:** 17
- **Roster Slots per Team:** QB = 1, RB = 1, WR = 3, WR/RB = 1, TE = 1, K = 1, DST = 1, Bench = 8

Derived: 9 starters + 8 bench = 17 roster slots = 17 rounds. Flex (`WR/RB`) is **WR or RB only**
(no TE). Scoring is **custom non-PPR** (JAAFFL2025 — 1 pt/50 pass yds, no offensive turnover
penalty, single DST points-allowed bracket). Draft order is **not** a plain snake inferred from team count —
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

`make setup` · `make backend-dev` (FastAPI on 127.0.0.1:8788) · `make web-dev` · `make test`
· backend lint/format via `ruff`; JS via `tsc`. See `CONTRIBUTING.md`.
