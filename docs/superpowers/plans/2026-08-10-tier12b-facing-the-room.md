# Tier 12b — facing the room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `docs/rehearsal-protocol.md` against a real, ticking, 12-team free-to-join CBS draft
room on the desktop the owner will actually draft on, turn the log into seven verdicts, root-cause
every failure, and record the result honestly as **n = 1**.

**Architecture:** This tier gathers evidence rather than building a feature. Tier 12 built the whole
apparatus — `JAAFFL_REHEARSAL_LOG` writes one JSONL row per recommendation from both the push and
pull paths, and `scripts/rehearsal_report.py` turns that log into pass/fail verdicts — and then did
not use it. The only code this tier is _expected_ to write is whatever the live room proves is
broken. Every such fix is TDD'd and mutation-proved before it lands. The owner is at the keyboard
for the draft; his steps are one paste-able block and three nudges, and everything else runs
without him.

**Tech Stack:** Python 3.12 (`.venv` at repo root, backend editable), FastAPI on `127.0.0.1:8788`,
the MV3 Chrome extension in `apps/extension`, pnpm workspace, pytest + vitest.

---

## Ground state — established before this plan was written

Verified on this desktop on 2026-08-10, not assumed:

| Fact                                                 | Evidence                                                                       |
| ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| Synced to `fb7eb28503ae75fbfa2a00c7a0374943c6611d1b` | `git rev-parse HEAD`; machine was 7 PRs back at `86aed5d` (Tier 7)             |
| `pytest backend -q`                                  | **749 passed, 2 skipped**                                                      |
| `pnpm -r typecheck`                                  | 3/3 packages clean                                                             |
| `pnpm -r test`                                       | **86 + 138 + 61 = 285**                                                        |
| `ruff check` / `format --check` over `. ../scripts`  | clean · 137 files formatted                                                    |
| schema parity · overlay token guard                  | both clean                                                                     |
| extension rebuilt                                    | `vite build`, 535 ms — **owner must Reload the card**                          |
| `data/rehearsal/*.jsonl` and `fixtures/cbs/` ignored | `git check-ignore -v` on real probe paths                                      |
| `config/engine.json` `lambda_slot_override`          | **still `0.4 / -0.4`** — the Tier 8/9/10/11 recommendation is STILL OPEN       |
| preflight with the slot absent                       | exits 1, `basis=degraded_no_slot`, board 581 players, all 6 positions fillable |

**One defect was found and fixed during sync, in the working tree only.** `pnpm lint` failed on 21
files. The flagged set and the CRLF set were byte-for-byte identical, and all 21 were last modified
strictly before commit `9cfc4ca` — the commit that introduced `.gitattributes`. Git applies
`eol=lf` only when it _writes_ a file, so files whose content never changed since kept their
pre-`.gitattributes` CRLF bytes. Forcing git to re-materialize them fixed it with **zero content
change** (`git status` stayed empty; files byte-identical after stripping `\r`). `core.autocrlf=true`
is set locally and is **inert** — all 120 files the pull rewrote came out LF while it was set,
because `.gitattributes` overrides it. Nothing to commit from this.

---

## The constraint that governs the whole tier

`apps/extension/src/lib/parse.ts:20` hardcodes `const IMMUTABLE_TEAM_COUNT = 12`, used in five
places. In a room that is not 12 teams:

- `parseDraftOrder` (`parse.ts:162`) returns `null`, so the order never reaches the backend and
  `survival_basis` is `degraded_no_order` on every row — failing verdicts 2, 3 and 7 for a reason
  that is **not** a pipeline defect;
- `parse.ts:31-32` computes `round` and `pick_in_round` by dividing by 12, silently misattributing
  every pick to the wrong round;
- `scripts/rehearsal_report.py:111` independently asserts `orders == {12}`.

For JAAFFL2025 the constant is **correct** — the league is 12 teams and `config/league.json` is
immutable. It bites only because the rehearsal is deliberately run elsewhere. `docs/rehearsal-protocol.md`
never states this.

**Decision (owner, 2026-08-10): constrain the room to 12 teams. Do not generalize the parser.**
Changing the parse path on the eve of a draft buys nothing for JAAFFL2025 and risks the one code
path that cannot be re-run. The hardcode is recorded as a finding, not fixed.

---

## Three defects already proven in `docs/rehearsal-protocol.md`

The protocol was written blind and has never been executed. Three defects are confirmed **by
execution on this machine**, before the run:

1. **§2 `cd C:\Users\conno\Code\Project_JAAFFL` does not exist.** The repo is
   `C:\Users\conno\Project_JAAFFL\Project_JAAFFL`.
2. **§2's `.env` edit silently does nothing.** `JAAFFL_MY_TEAM_ID` is **absent** from this
   desktop's `.env` (not empty — absent), so `(Get-Content .env) -replace '^JAAFFL_MY_TEAM_ID=.*'`
   matches nothing and writes the file back unchanged. Proven: applying it to a copy left **0**
   matching lines. The owner would believe his slot was set; preflight would then exit 1 and the
   reason would look unrelated.
3. **§2 never states the 12-team constraint**, without which the run cannot produce evidence.

A fourth is expected but not yet proven: §0 of `docs/live-draft-recording-guide.md` claims live
auto-recommendations are **not wired** and the overlay shows "Watching the board". That predates
PR #14. Task 8 corrects it **from the live overlay actually observed**, not from code reading.

---

## File Structure

| File                                                           | Responsibility in this tier                                                       |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `docs/rehearsal-protocol.md`                                   | Corrected against reality: repo path, `.env` incantation, 12-team gate, run order |
| `docs/live-draft-recording-guide.md`                           | §0 corrected from the observed live overlay                                       |
| `docs/owner-manual-todo.md`                                    | §1 "a replay is not a live draft" resolved or re-scoped; bench question re-stated |
| `ROADMAP.md`                                                   | New Tier 12b status block, labelled n=1, with an explicit NOT-established list    |
| `scripts/rehearsal_report.py`                                  | Touched **only** if a verdict is proven wrong by the live log                     |
| `backend/src/jaaffl/**`                                        | Touched **only** to fix a defect the room exposed, TDD'd + mutation-proved        |
| `apps/extension/src/**`                                        | Same rule. The 12-team hardcode is explicitly out of scope                        |
| `docs/superpowers/plans/2026-08-10-tier12b-facing-the-room.md` | This plan                                                                         |
| `data/rehearsal/*.jsonl`                                       | Evidence. **git-ignored — never committed** (real drafters' ids and names)        |

---

## Task 1: Correct the protocol's two fatal §2 defects BEFORE the run

Handing the owner a protocol with a wrong path and a silent no-op wastes the room. These two are
proven; fix them now, and leave everything else in the doc alone until reality corrects it.

**Files:**

- Modify: `docs/rehearsal-protocol.md` §2

- [ ] **Step 0: Branch from main — never commit to main**

```bash
git checkout main && git pull && git checkout -b tier12b/facing-the-room
```

- [ ] **Step 1: Fix the repo path**

Replace `cd C:\Users\conno\Code\Project_JAAFFL` with `cd C:\Users\conno\Project_JAAFFL\Project_JAAFFL`.

- [ ] **Step 2: Replace the silent `.env` edit with the tested incantation**

```powershell
(Get-Content .env) -notmatch '^JAAFFL_MY_TEAM_ID=' | Set-Content .env
Add-Content .env 'JAAFFL_MY_TEAM_ID=<N>'
```

Verified on a copy of the real `.env`: works when the key is **absent**, works when **present**,
leaves exactly **one** line on a re-run with a different value, and preserves every other key.

- [ ] **Step 3: Add the 12-team gate to §2**

Add, immediately before joining a league:

> ⚠️ **The room must have exactly 12 teams.** The extension parses CBS frames against a fixed
> 12-team assumption (`parse.ts::IMMUTABLE_TEAM_COUNT`) — correct for JAAFFL2025, and the reason
> this rehearsal must be run in a 12-team room. In any other size the draft order is rejected, every
> recommendation degrades, and the round number on every pick is wrong. **Check the team count in
> the lobby before the clock starts.**

- [ ] **Step 4: Verify the doc still lints**

Run: `pnpm exec prettier --check docs/rehearsal-protocol.md`
Expected: `All matched files use Prettier code style!`

- [ ] **Step 5: Commit**

```bash
git add docs/rehearsal-protocol.md
git commit -m "docs(rehearsal): the protocol's own setup block could not have worked"
```

---

## Task 2: The shake-out mock (owner, ~10 minutes)

Purpose: catch the install problems with no clock pressure. Tier 12 documented that a missed Chrome
Local Network Access prompt makes recording stall **silently** while everything looks healthy — the
single most likely way to lose this session's evidence.

- [ ] **Step 1: Owner reloads the extension card**

`chrome://extensions` → **JAAFFL — CBS Draft Assistant** → **Reload**. The card serves the old
`dist` until reloaded; skipping this rehearses the previous build.

- [ ] **Step 2: Owner runs the mock with `JAAFFL_REHEARSAL_LOG=data\rehearsal\mock-0.jsonl`**

A CBS **Mock Draft** (12 teams). Any slot. Draft ~4 rounds, then stop.

- [ ] **Step 3: Confirm the log is non-empty before the real room**

```bash
.venv/Scripts/python.exe scripts/rehearsal_report.py data/rehearsal/mock-0.jsonl
```

Expected: a table with rows. **If it reports `no rows: the rehearsal log is empty`, the install is
broken and the free league must not be started yet** — that is exactly the outcome this mock exists
to catch. Diagnose against Task 5's table.

The mock's verdicts are **not** evidence for the ROADMAP block — bots, no real pace. Its only job
is to prove frames are flowing.

---

## Task 3: The live run (owner, one sitting)

- [ ] **Step 1: Owner joins a 12-team free-to-join CBS league and confirms the count in the lobby**

Not a mock. Not JAAFFL2025. Real clock, real drafters, no money.

- [ ] **Step 2: Owner runs the one setup block** — `<N>` = his team number, read off the lobby board

```powershell
cd C:\Users\conno\Project_JAAFFL\Project_JAAFFL
(Get-Content .env) -notmatch '^JAAFFL_MY_TEAM_ID=' | Set-Content .env
Add-Content .env 'JAAFFL_MY_TEAM_ID=<N>'
.venv\Scripts\python.exe scripts\preflight.py
$env:JAAFFL_REHEARSAL_LOG = "data\rehearsal\free-1.jsonl"
.venv\Scripts\python.exe -m jaaffl.api
```

`JAAFFL_REHEARSAL_LOG` must be set in the **same terminal** that starts the API — it is read at
process start. Leave the last command running; that terminal is the backend.

- [ ] **Step 3: Preflight must print `OK` and exit 0**

Its last line must read `survival probe ... basis=my_slot`. If it fails it names the reason — stop
and report it rather than drafting into a known-degraded run.

- [ ] **Step 4: Owner drafts, with the three §3 nudges**

Auto-pick once in the first three rounds; close and reopen the draft tab around round 4; Ctrl+C and
restart the backend around round 6. Skip any of them if the clock is tight, and **say which**.

- [ ] **Step 5: Owner hands back the report output, his team number, and one mid-draft overlay screenshot**

The screenshot is the ground-truth cross-check on the overlay foot line, which the report can only
_derive_.

---

## Task 4: Run the report and record the seven verdicts

**Files:**

- Read: `data/rehearsal/free-1.jsonl` (git-ignored)

- [ ] **Step 1: Run the report**

```bash
.venv/Scripts/python.exe scripts/rehearsal_report.py data/rehearsal/free-1.jsonl
```

- [ ] **Step 2: Record all seven verdicts verbatim, labelled n = 1**

The seven, from `scripts/rehearsal_report.py::CRITERIA`: `recommendations served`, `survival is
live`, `the order was read from the room`, `recompute under 200ms`, `every drafted player masked`,
`vona_method stated`, `the scarcity term is live`.

- [ ] **Step 3: Check measurability BEFORE interpreting anything**

An empty log fails all seven **by design**, and a vacuous pass is this project's documented failure
mode (Tier 12's own first measurement was an artifact: synthetic picks with `player_id=None` meant
nothing was masked and the board never depleted). Before treating any verdict as evidence, confirm:

- row count > 0, and both `push` and `pull` paths appear;
- `picks_total` **increases** across the draft — a board that never depletes measures nothing;
- at least one row has `picks_masked > 0`.

If those fail, the run measured nothing and the block must say so instead of reporting verdicts.

---

## Task 5: Root-cause every failing verdict — no fixes before Phase 1 is complete

**REQUIRED SUB-SKILL:** `superpowers:systematic-debugging` for each failure, independently. This
project has three tiers on record of fixing the wrong thing, and Tier 12 introduced a critical
defect that only code review caught.

Predicted failure modes and the **first** diagnostic for each — real content, not a placeholder.
None of these is expected; each is where to look if it happens.

| Failing verdict                    | First thing to read                                                                                                                                                                                                                                            |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recommendations served`           | Empty log ⇒ frames never arrived. Chrome Local Network Access prompt (asked twice — lobby and popup are different origins); then `JAAFFL_REHEARSAL_LOG` set in the same terminal that started the API.                                                         |
| `the order was read from the room` | `draft_order_len` in the log. `0` ⇒ `parseDraftOrder` rejected it (team count ≠ 12, or `fullstatedelta.order` absent from this room's frames). Non-zero but ≠ 12 ⇒ `fold_state`'s `draft_order_length_conflict` warning in the backend terminal.               |
| `survival is live`                 | Downstream of the order. If order is 12 and this still fails, read `survival_basis`: `degraded_no_slot` ⇒ the slot did not reach `recommend()`; `degraded_no_order` ⇒ the overlay in `engine/context.py::effective_settings`.                                  |
| `recompute under 200ms`            | Which row is slow. **The first row** ⇒ Finding B regressed — the `create_app` warm-up is not paying the numpy/scipy import. A **later** row ⇒ a genuine live cost Tier 12 never saw.                                                                           |
| `every drafted player masked`      | `unresolved_ids`. Non-empty is a real draft-night defect: `ingest/resolve.py` keeps `cbs:<id>`, never guesses, and the player **stays on the board and can be recommended again**. Count them; a free league's roster may include players the crosswalk lacks. |
| `vona_method stated`               | Anything but `analytic` on the push path means MC reached the hot path — `test_mc_off_hot_path.py` should have prevented it.                                                                                                                                   |
| `the scarcity term is live`        | `positive_vona_n == 0` on rows that are `my_slot` ⇒ `kappa · max(0, VONA)` is still identically zero with survival live. That is Finding A surviving its own fix.                                                                                              |

- [ ] **Step 1: For each failure, complete root-cause investigation before proposing any fix**

Read the log rows, the backend terminal output, and the code path. State the hypothesis explicitly
before testing it.

- [ ] **Step 2: For each confirmed root cause, write the failing test FIRST**

**REQUIRED SUB-SKILL:** `superpowers:test-driven-development`. Prefer a deterministic assertion over
a wall-clock one — Tier 12a rewrote a timing test to assert the _lever_ instead, which was both
steadier and strictly stronger.

- [ ] **Step 3: Run the new test and confirm it fails on an ASSERTION, not an ImportError**

- [ ] **Step 4: Implement the minimal fix**

- [ ] **Step 5: Run the test and confirm it passes**

- [ ] **Step 6: Mutate the implementation and confirm the SPECIFIC named test fails**

Copy the file aside first — `git checkout -- <file>` silently destroys uncommitted work. Confirm the
mutation actually landed before trusting a red test.

- [ ] **Step 7: Commit per defect, with the root cause in the message**

---

## Task 6: The ROADMAP Tier 12b block

**Files:**

- Modify: `ROADMAP.md` (new block above the Tier 12 block at line 16)

- [ ] **Step 1: Write the block in the established voice**

Required content: what the room actually showed; the seven verdicts with numbers; every defect
root-caused and fixed; **an explicit "what one draft does NOT establish" list**; what is superseded.

- [ ] **Step 2: State the n = 1 limits explicitly**

At minimum, and without softening:

- **n = 1.** One draft, one seat, one evening, one machine.
- **A free league is not JAAFFL2025.** Roster and scoring differ while `config/league.json` is
  immutable, so the engine baselined against the owner's roster while he drafted in theirs. The
  **pipeline** result (survival, latency, masking, reconnect, resync) is valid; **no
  recommendation from this draft is advice**, and **nothing about pick quality is reported**.
- **Nothing about ranking quality.** The live engine's picks have still never been scored with
  survival live — that needs the tournament, not a rehearsal.
- **The 12-team hardcode was not fixed**, only worked around by room selection.
- **Whatever the owner skipped in §3** was not tested; name it.
- Every Tier 11 caveat still stands.

- [ ] **Step 3: Prettier the markdown and commit**

```bash
pnpm exec prettier --write ROADMAP.md
git add ROADMAP.md && git commit -m "docs(roadmap): Tier 12b — the room, at last (n=1)"
```

---

## Task 7: Correct `docs/rehearsal-protocol.md` against what actually happened

- [ ] **Step 1: Fold in every step that was wrong, missing, or in the wrong order**

Beyond Task 1's three: anything the owner hit that the doc did not predict — prompt order, timing,
what the overlay actually showed, what the backend printed, whether the §3 nudges were feasible
against a live clock.

- [ ] **Step 2: Mark the protocol as EXECUTED, with the date and the room type**

It currently reads as a guess. It should read as a thing that has been done once.

- [ ] **Step 3: Prettier and commit**

---

## Task 8: Correct `docs/live-draft-recording-guide.md` §0 from the observed overlay

**Files:**

- Modify: `docs/live-draft-recording-guide.md` §0

- [ ] **Step 1: Replace the "Watching the board" / "not wired" claim with what was observed**

§0 currently says live auto-recommendations are **not wired in the free ($0) path** and the engine
replies "warming up". That predates PR #14. Tier 12 deliberately left it because it never observed a
live overlay. Correct it from the screenshot and the run — **not** from reading the code.

- [ ] **Step 2: Prettier and commit**

---

## Task 9: Update `docs/owner-manual-todo.md`

- [ ] **Step 1: Resolve or re-scope §1's "Still open: a replay is not a live draft"**

If the run succeeded, say what it retired **and what it did not** — n = 1, and a free league is not
his league.

- [ ] **Step 2: Re-state the still-open `lambda_slot_override` decision with Tier 11's numbers**

Verified 2026-08-10: `config/engine.json` still reads `0.4 / -0.4`.

| measure                  | engine as shipped | with the setting off | plain best-available |
| ------------------------ | ----------------- | -------------------- | -------------------- |
| championship probability | 0.0063            | **0.1109**           | **0.1206**           |
| projected points         | 1453              | **1739**             | 1703                 |

Still the largest effect in the project; still **not** a win over the naive baseline on championship
odds; still the owner's call.

- [ ] **Step 3: Re-state the open bench-eligibility question (§1b)** — does CBS let a kicker or
      defense sit on the bench? Unanswered; priced at roughly one wasted late-round suggestion per draft.

- [ ] **Step 4: Prettier and commit**

---

## Task 10: Propose the `config/engine.json` change as a diff — do NOT apply it

`config/engine.json` is owner-adopted. **Nothing is written without explicit approval in chat.**

- [ ] **Step 1: Present the diff in the PR body and in chat**

```diff
   "lambda_slot_override": {
-    "last_startable_slot_floor": 0.4,
-    "surplus_stash_ceiling": -0.4
+    "last_startable_slot_floor": 0.0,
+    "surplus_stash_ceiling": 0.0
   },
```

- [ ] **Step 2: Confirm the file is unchanged before the PR**

```bash
git diff --exit-code config/engine.json config/league.json
```

Expected: exit 0, no output.

---

## Task 11: Full verification, PR, CI, merge

**REQUIRED SUB-SKILL:** `superpowers:verification-before-completion`, then
`superpowers:requesting-code-review` — it has caught a serious defect in each of the last three
tiers, including one Tier 12 introduced itself.

- [ ] **Step 1: Confirm no evidence file is staged**

```bash
git status --porcelain | grep -E 'data/rehearsal|fixtures/cbs' && echo "STOP" || echo "clean"
```

Expected: `clean`. A real league's log carries other drafters' ids and names.

- [ ] **Step 2: Run every gate**

```bash
.venv/Scripts/python.exe -m pytest backend -q
pnpm -r typecheck && pnpm -r test && pnpm lint
```

Then from `backend/`: `ruff check . ../scripts` and `ruff format --check . ../scripts`.
Then schema parity (`python scripts/export_schemas.py` then `git diff --exit-code packages/shared/schemas`)
and `node scripts/gen-overlay-tokens.mjs --check`.

- [ ] **Step 3: Request code review, act on what it finds**

- [ ] **Step 4: Push, open the PR with the rehearsal evidence in the body, wait for all 4 checks**

Backend · Node 22 · Node 24 · Playwright. `jq` is not installed — read `gh pr checks N`'s table.

- [ ] **Step 5: Squash-merge, delete the branch, `git checkout main && git pull`, report PR URL + SHA**

---

## Risks

- **The likeliest outcome is an empty log**, and it fails all seven verdicts by design. The mock in
  Task 2 exists to catch it before the room. Chrome asks for Local Network Access **twice**.
- **A free league's board may not resolve cleanly.** Unresolved CBS ids leave players unmasked and
  recommendable. That is a real defect class, but a free league's roster settings are not the
  owner's, so the _count_ may not transfer to draft night. Say so.
- **The three §3 nudges cost real picks and real clock.** Skipping is allowed; unreported skipping
  is not.
- **This tier may find nothing.** Seven PASSes is a legitimate outcome and must not be inflated into
  more than one draft's worth of evidence.
