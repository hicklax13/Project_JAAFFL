# Live-room rehearsal protocol (Tier 12)

One CBS draft, one sitting, ~45 minutes, on the machine you will actually draft on.

**Which room.** A **free-to-join CBS league** — a real clock, real drafters, no money. That is the
point: a mock's bots do not produce real runs or real pace. Do a 10-minute **mock** first if you
want to shake out the install; §2 works for either. **Do not use your JAAFFL2025 league** — that
draft is the thing this rehearsal exists to protect.

Everything automated runs without you. Your part is the block in §2 plus three nudges in §3. At
the end you run one command and paste me the output.

## 1. What this is testing

The pipeline has replayed a complete captured draft end to end (Tier 3), but it has never faced a
room with a clock. This rehearsal answers, with numbers rather than impressions: was the survival
model live, did every recompute meet the 200 ms budget, was every player anyone drafted removed
from your board, and did every CBS player id resolve.

It also re-tests, in a real room, the defect Tier 12 fixed: the entered draft order was decoded
from CBS's frames and then dropped before it reached the engine, so **every** live recommendation
this project has ever served had a dead scarcity term.

## 2. Your setup — one block, top to bottom

⚠️ **The room must have exactly 12 teams.** The extension parses CBS frames against a fixed
12-team assumption (`parse.ts::IMMUTABLE_TEAM_COUNT`, five call sites) — correct for JAAFFL2025,
and the reason this rehearsal must be run in a 12-team room. In any other size `parseDraftOrder`
returns `null`, so the order never reaches the engine and **every** recommendation degrades; the
round number on every pick is wrong too, because `parse.ts` divides by 12 to get it.
`scripts/rehearsal_report.py` independently asserts `draft_order_len == 12`. **Check the team count
before the clock starts** — in a CBS mock lobby that is the `MEMBERS` column (`0 of 12`), and in a
free league it is the league's team count.

⚠️ **The repo path differs per machine** — this project has been worked on from more than one.
`cd` to wherever your clone actually is, and confirm it before running anything else:

```powershell
cd <your Project_JAAFFL clone>   # verify with: git rev-parse --show-toplevel
git checkout main
git pull
pnpm --filter @jaaffl/extension build
```

Open Chrome → `chrome://extensions` → on the **JAAFFL — CBS Draft Assistant** card click
**Reload**. This matters: a loaded card keeps serving the old build until you reload it, so
skipping this rehearses the old code.

Both entry points below were loaded and read on 2026-08-10 rather than guessed at, in a Chrome
already signed in to CBS:

| what                   | URL                                                                                          |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| **Mock draft lobby**   | `https://mockdraft-1.football.cbssports.com/mockdraft/standard`                              |
| **Free league signup** | `https://freemeeting-0.football.cbssports.com/splash/signup/football/spln/single/free/24406` |

The **mock lobby** lists `START TIME · DETAILS · MEMBERS · ACTION`, refreshed every five minutes,
and is free and unlimited. Pick a row whose MEMBERS column reads **`of 12`** and prefer
**`Flex Roster`** — that is non-PPR with a flex slot, the closest available shape to JAAFFL2025.
Avoid any row labelled **PPR**. Click **JOIN NOW**.

Both room types were opened and read on 2026-08-15 (lobby row → **DETAILS** link →
`/mockdraft/lobby/details/<id>`), so the choice below is measured rather than inferred:

|                   | **JAAFFL2025** | **`Flex Roster` @ 12** | `Standard Roster` |
| ----------------- | -------------- | ---------------------- | ----------------- |
| Teams             | 12             | **12** ✅              | 12 or 14          |
| Scoring           | custom non-PPR | non-PPR ✅             | non-PPR           |
| **Flex slot**     | **WR/RB**      | **1 RB/WR** ✅         | **none** ❌       |
| QB · TE · K · DST | 1 each         | 1 each ✅              | 1 each            |
| RB / WR           | 1 / 3          | 2 / 2 ⚠️               | 2 / 3             |
| Rounds            | 17             | 14 ⚠️                  | 14                |
| Bench             | 8              | 5 `RES` ⚠️             | 5 `RES`           |
| Draft style       | live snake     | `live` ✅              | `live`            |

**`Flex Roster` is the right room, and the flex slot is the whole reason.** `Standard Roster`
happens to match JAAFFL's 3 WR exactly, but it has **no flex at all** — and the flex is precisely
what `engine/optimize.py`'s Hungarian assignment and the `flex_split` calibration exist to handle,
so a flexless room rehearses a different shape of the problem.

The round/bench gaps do **not** matter here: this run rehearses the PIPELINE, not roster fit.
`config/league.json` is immutable, so the engine keeps optimising for JAAFFL's 17-round,
3-WR roster no matter what room it is pointed at — expect its advice to skew WR relative to what
the mock room wants, and do not file that as a defect. A 14-round room simply means rounds 15-17
never happen.

⚠️ **In a mock you CHOOSE your seat** — the details page lists every position as either a taken
team name or `Join at this Position`. So unlike draft day, you know `<N>` before the clock starts.
That value is disposable; overwrite it on 2026-08-22.

The **free league** page asks for a single `Team Name` and an **OK** button. CBS's own comparison
table puts the free tier at **$0 · 12 teams · Standard (non-PPR) · Snake** — which matches
JAAFFL2025 on team count, scoring family and draft type. Its draft time is scheduled by the
league and is not visible before joining.

Wait in the lobby and **read your team number off the board** — that is your draft slot.

Back in the terminal, with `<N>` = your team number:

```powershell
(Get-Content .env) -notmatch '^JAAFFL_MY_TEAM_ID=' | Set-Content .env
Add-Content .env 'JAAFFL_MY_TEAM_ID=<N>'
.venv\Scripts\python.exe scripts\preflight.py
$env:JAAFFL_REHEARSAL_LOG = "data\rehearsal\draft-1.jsonl"
.venv\Scripts\python.exe -m jaaffl.api
```

> ⚠️ **Why `-notmatch` + `Add-Content` and not a plain `-replace`.** This file previously said
> `(Get-Content .env) -replace '^JAAFFL_MY_TEAM_ID=.*', ...`, which only works if the key is
> already in `.env`. On the desktop it was **absent**, not empty — so the replace matched nothing,
> wrote the file back unchanged, and **silently did not set the slot**. Verified 2026-08-10 by
> applying it to a copy of the real `.env`: zero matching lines afterwards. The form above works
> whether the key is absent or present, leaves exactly one line when re-run with a different
> number, and preserves every other key. `JAAFFL_REHEARSAL_LOG` must be set in the **same
> terminal** that starts the API — it is read at process start.

**Preflight must print `OK` and exit 0.** It now checks the wiring as well as the board — its last
line reads `survival probe ... basis=my_slot`. If it fails it names the reason; stop and tell me.
Leave the last command running: that terminal is the backend.

In Chrome, on the draft tab, click the pinned **JAAFFL** icon. A red **REC** badge appears.

> ⚠️ **Chrome will ask to "access other apps and services on this device" — click Allow.** It asks
> **again** when the draft-room popup opens, because the lobby and the popup are different
> origins. Allow both. This is Chrome's Local Network Access prompt, attributed to the CBS page.
>
> ⚠️ **OPEN QUESTION — whether Allow is actually REQUIRED is not established, and the two things
> we know point opposite ways.** Settle it on a throwaway mock, never on draft night.
>
> - **This file used to assert** that without Allow "nothing is recorded and everything still looks
>   healthy". That sentence was written **blind** — the protocol had never been executed when it was
>   written, which is the same provenance as the three §2 defects this document already records.
>   It is an assumption formatted as a fact.
> - **The source says a page-level grant should be irrelevant.** The backend link is owned by
>   `apps/extension/src/content/cbs-draft.content.ts`, which the built manifest runs in the
>   **ISOLATED** world — so its `ws://127.0.0.1:8788/draft/ws` connection uses the EXTENSION's
>   origin and the `http://127.0.0.1:8788/*` entry already present in `host_permissions`. The only
>   MAIN-world script, `inject/cbs-main.inject.ts`, imports `MainRelay` as `import type` (erased at
>   compile time) and reaches the isolated world **only** through `window.postMessage`. It never
>   touches localhost. Verified by reading the built `dist/manifest.json` and the source on
>   2026-08-15 — but **not** by observing a blocked run, which is the evidence that would settle it.
>
> **Until it is settled, click Allow**, because the two outcomes are not symmetric: if Allow is
> unnecessary you have granted one throwaway mock session local-network access, whereas if Block is
> wrong you record NOTHING while every surface still looks healthy — the single failure mode this
> whole protocol exists to prevent.
>
> **How to settle it (one spare mock, ~10 min, free and unlimited):** run the mock again, click
> **Block** on both prompts, and watch the backend terminal for ingest. If picks still arrive,
> Block is correct and this instruction should be inverted on privacy grounds — CBS pages carry
> third-party ad and tracker scripts, and the grant is to the PAGE, not to us. Record the result
> here with the date either way.

> ⚠️ **Extension card: the master toggle is the grant.** On `chrome://extensions` → JAAFFL →
> **Site access**, what matters is **"Automatically allow access on the following sites"** being
> ON. The per-site rows listed beneath it (`http://127.0.0.1:8788/*`, `https://*.cbssports.com/*`)
> can read as grey/unset and that is **normal** — it does not mean access was denied. Confirmed on
> the owner's machine 2026-08-15, where the overlay rendered on a CBS page with those rows grey.
> Do not "fix" them and do not treat them as a fault to chase.

> ⚠️ **Start the backend BEFORE opening the draft room — or reload the tab afterwards.** The
> overlay shows a red **RECONNECTING…** whenever the backend is not up. That is the correct display
> for a stopped server, not a defect. If you started the room first, reload the draft tab once the
> API is running and confirm the red clears.

## 3. During the draft — three nudges, everything else is normal drafting

Draft normally, against the clock.

| When                      | Do this                                                                        | Why                                                                 |
| ------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| one of your first 3 picks | **let the clock run out** so CBS auto-picks for you                            | a pick made _for_ you takes a different path than one you make      |
| around round 4            | **close the CBS draft tab and reopen the draft room**                          | the late-join resync — the board must not be lost                   |
| around round 6            | in the backend terminal press **Ctrl+C**, then re-run the last two lines of §2 | a mid-draft restart: the durable log must replay, the board rebuild |

> ⚠️ **In a real league these three cost you something.** The auto-pick spends a real pick, and
> each restart costs ~20 seconds of a clock. Do all three **early, in rounds where several players
> would suit you**, and skip any of them if the clock is tight. A defect found at round 4 is worth
> exactly as much as one found at round 12. **If you skip one, say which.**

Then draft to the end (or to round 8+ if the league lets you leave). Click the **JAAFFL** icon
again — the REC badge goes away and a final flush is written.

## 4. Hand back — one command plus two things

```powershell
.venv\Scripts\python.exe scripts\rehearsal_report.py data\rehearsal\draft-1.jsonl
```

Paste me its whole output, plus:

1. **one screenshot of the JAAFFL overlay** taken mid-draft (the foot line matters most)
2. **your team number**

That is everything. The recording under `apps/extension/fixtures/cbs/rec-*.jsonl` stays on your
disk (git-ignored) and lets a future tier replay this exact draft.

## 5. What each step passes on

| #   | Step                     | Pass                                                                  |
| --- | ------------------------ | --------------------------------------------------------------------- |
| 1   | preflight                | exit 0, including `survival probe ... basis=my_slot`                  |
| 2   | backend up               | `/health` returns `{"status":"ok"}`                                   |
| 3   | REC on                   | `recording_stored` lines in the backend terminal; `rec-*.jsonl` grows |
| 4   | order read from the room | report: **the order was read from the room** PASS                     |
| 5   | survival live            | report: **survival is live** PASS — every row `my_slot`               |
| 6   | latency                  | report: **recompute under 200ms** PASS — including the very first row |
| 7   | masking                  | report: **every drafted player masked** PASS — `unresolved_ids` empty |
| 8   | scarcity live            | report: **the scarcity term is live** PASS — `vona>0` never 0         |
| 9   | reconnect                | `masked` never decreases across the §3 tab reopen                     |
| 10  | restart                  | recommendations resume after the §3 restart, same board               |
| 11  | overlay                  | your screenshot's foot line matches the report's derived line         |

## 6. What this does NOT establish

- **n = 1.** One draft, one seat, one evening.
- **A free league is not JAAFFL2025.** Different people, different pace, different runs, and a
  roster/scoring setup that is probably not yours — so nothing here validates the engine against
  _your_ league's board.
- **Nothing about pick QUALITY.** This proves the pipeline is live and honest under a clock; it
  says nothing about whether the recommendations are good. That is what the tournament measures,
  and `lambda_slot_override` is still the open decision there (`docs/owner-manual-todo.md` §1).
- **Not the settings page.** `CbsPageSnapshot` projections/injuries/rankings stay `TODO(capture)`
  — that needs a settings-page capture, not draft-room frames.
- **Whatever you skipped in §3** did not get tested. Say which.
