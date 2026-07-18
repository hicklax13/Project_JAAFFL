# Design: JAAFFL2025 official scoring + constitution update

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation
**Scope:** Correct the repo's scoring map + league constitution to the owner's **official JAAFFL2025
rules** (provided verbatim). The current map is a CBS-Standard *guess*; several values are wrong and
would make the engine's projections — and therefore its draft recommendations — incorrect.

## Goal

Replace the placeholder `cbs_standard_scoring()` with the authoritative owner-provided **JAAFFL2025**
scoring, update the constitution/config framing, and fix every test/memory/doc that encodes the old
values. The scoring *evaluator* (`league.scoring.league_points`), the roster/starter model, and the
engine are already correct and stay untouched.

## Authoritative source

The owner pasted the CBS **League Settings** (scoring system, roster limits, policies) and the
**Constitution** rule book. These are the immutable truth for this league. Owner-confirmed
interpretations (2026-07-17):
- **DST points-allowed: single bracket** — allow 0–9 pts → **+6**, allow 10+ → **0**. (No other PA
  brackets; matches the settings table + Constitution 6e "6 points for under 10".)
- **No offensive turnover penalties** — QBs/skill players are NOT docked for INT/fumble; turnovers
  only reward the opposing DST.
- **Roster:** keep the current 9-starter + 8-bench (17-round) model — it already captures the active
  min/max (QB1, RB1–2, WR3–4, TE1, K1, DST1, 8–9 starters). Position roster-total caps / IR / flexible
  bench are in-season admin and are NOT modeled (they don't affect draft value).

## What changes (the deltas)

| # | Stat | Current (wrong) | JAAFFL2025 (correct) |
|---|------|-----------------|----------------------|
| 1 | `passing_yards` | 0.04/yd | **0.02/yd** (1 pt / 50) |
| 2 | `interception` (thrown), `fumble_lost` | −2 each | **removed** (no offensive turnover penalty) |
| 3 | K FG 50+ bonus | single `fg_made_50plus` +2 | **`fg_made_50plus` +1 AND `fg_made_60plus` +1** (cumulative: 50–59 → +1 net 4, 60+ → +2 net 5) |
| 4 | `dst_points_allowed` tier | 6 brackets (12/8/6/4/2/0) | **single bracket `[0,10) → 6`** |
| 5 | `dst_yards_allowed` tier | 7 brackets | **removed entirely** |
| 6 | function name / framing | `cbs_standard_scoring()`, "capture-blocked fallback" | **`jaaffl_scoring()`, owner-authoritative** |

**Unchanged (already correct):** `passing_td` 6; `rushing_yards`/`receiving_yards` 0.1; all TDs 6;
`two_point` 2; non-PPR (no `reception` rule); `xp_made` 1; `fg_made` base 3; DST `sack` 1 / `dst_int`
2 / `fumble_recovery` 2 / `safety` 2 / `dst_td` 6 / `return_td` 6.

## Components

### 1. `backend/src/jaaffl/league/defaults.py`
Rename `cbs_standard_scoring()` → **`jaaffl_scoring()`**; rewrite the docstring (owner-provided
JAAFFL2025 map, authoritative — only CBS live-frame *parsing* stays capture-blocked, not the scoring
values). Apply deltas 1–5. The tuple return shape `(rules, tiers, bonuses)` is unchanged, so the
evaluator and callers need only the rename.

### 2. `backend/src/jaaffl/league/constitution.py`
Import/call `jaaffl_scoring()`; update the module + `resolve_league_settings` docstrings so they no
longer describe the scoring as a "CBS Standard fallback (capture-blocked)". A captured CBS snapshot's
scoring may still override (defense-in-depth), but the default is now authoritative.

### 3. `config/league.json`
- `scoring_format`: `"Standard"` → `"Custom (non-PPR)"`.
- `scoring_note`: rewrite to state the real JAAFFL2025 values (0.02 passing / 1-per-50, no offensive
  turnover penalty, K distance bonuses, DST single-bracket PA + no yards) and that the typed map lives
  in `league/defaults.jaaffl_scoring` (single source; the constitution documents, code encodes).
- Add an `identity` block: `name` "JAAFFL2025", `url`, `email`, `entry_fee` 400 (memorialization; no
  engine impact).
- Roster slots, 12 teams, snake, 17 rounds, `draft_order` null — **unchanged**.
- Bump `last_confirmed` and clarify the `_comment`: values are owner-confirmed (not CBS-inferred).
- Values stay single-sourced in code; league.json does not duplicate the typed rules.

### 4. Tests
- `test_defaults.py`: assert the JAAFFL2025 map (0.02 passing; NO `interception`/`fumble_lost` rules;
  two K bonuses at 50 & 60 each +1; `dst_points_allowed` single `[0,10)→6`; NO `dst_yards_allowed`).
- `test_scoring.py`: update any case built on the old values; add scenario tests — a QB stat line
  scores passing at 0.02 and is NOT docked for an INT; a K's 55-yd FG = 4 and 62-yd FG = 5; a DST
  allowing 7 = +6 and allowing 10 = +0; a DST yards-allowed value contributes nothing.
- `test_api.py`: the `scoring_tiers` assertion `{dst_points_allowed, dst_yards_allowed}` →
  `{dst_points_allowed}`; keep the `passing_td == 6` assertion.
- Any test importing `cbs_standard_scoring` → `jaaffl_scoring`.

### 5. Memory
Replace the now-wrong `cbs-standard-scoring-verified` (says 0.04 passing + dual-bracket DST) with a
`jaaffl-scoring-verified` reference memory carrying the correct values + the owner-confirmed
interpretations; update the `MEMORY.md` index line.

### 6. Docs
- `docs/live-draft-recording-guide.md`: the league-settings table "Standard (non-PPR)" →
  "Custom (non-PPR) — JAAFFL2025".
- `docs/owner-manual-todo.md`: mark the "real CBS **scoring values** stay capture-gated" item
  **RESOLVED** (owner provided them 2026-07-17); the CBS **frame-parsing** capture is still pending.
- Archival design docs (`implementation-plan.md`, `draft-system-design.md`) that say "Standard":
  leave as historical (a scoping note in the PR), to keep the diff focused.

## Out of scope
IFRTD/IKRTD individual return/fumble-return TDs (6 pts) — omitted (no per-player data on the $0 tier;
inert, mirrors the current map's omission of blocked-kicks). Roster position caps / IR / flexible
bench. The scoring evaluator, VOR/engine, E5 contract, extension, and the CBS live-frame capture.

## Testing / gates
Network-free unit tests (`test_defaults`, `test_scoring`, `test_api`); full `verify` recipe green
(ruff + pytest + tsc); do not regress the 309 backend / 129 JS baseline. The engine's downstream
projection/VORP numbers shift (that's the point — they were wrong before); reconstruction invariants
and roster math are unaffected.
