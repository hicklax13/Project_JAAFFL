# Setting up a second machine to draft on

One-time setup for the machine you will actually draft on (the owner's ASUS mini PC), so draft
night starts from a verified install rather than a debugging session against a clock.

Do this **days before** the draft, not the morning of. The last step is a full green-suite check;
if anything there fails you want time to say so.

> The rehearsal itself is [`rehearsal-protocol.md`](rehearsal-protocol.md). This document only
> gets the machine ready to run it.

## 1. Prerequisites

| Tool              | Version                   | Download                          |
| ----------------- | ------------------------- | --------------------------------- |
| **Google Chrome** | current                   | https://www.google.com/chrome/    |
| **Python**        | ≥ 3.11 (3.12 recommended) | https://www.python.org/downloads/ |
| **Node.js**       | 22 or 24                  | https://nodejs.org/en/download    |
| **pnpm**          | ≥ 10                      | `npm install -g pnpm`             |

`make` is **not** required and is not installed on the owner's Windows machines — every command
below is the direct equivalent.

## 2. Clone and install

```powershell
cd C:\Users\<you>\Code
git clone https://github.com/hicklax13/project_jaaffl.git
cd project_jaaffl
python -m venv .venv
cd backend
..\.venv\Scripts\python.exe -m pip install -e ".[dev,data,engine]"
cd ..
pnpm install
```

Those are the same three extras the `Makefile`'s `setup` target installs (`dev,data,engine`).
`engine-stretch` (OR-Tools / XGBoost / Optuna) and `assistant` (OpenAI) are **not** needed to
draft — they are calibration and Stage-7 only.

## 3. Bring `.env` across BY HAND

`.env` is git-ignored and never leaves the laptop through git, so nothing above created it.

```powershell
Copy-Item .env.example .env
```

Then open `.env` and set:

- `JAAFFL_MY_TEAM_ID` — leave **empty** for now. You fill it in from the CBS lobby on draft day
  (the rehearsal protocol's §2 does this). Preflight will fail loudly until you do, by design.
- `OPENAI_API_KEY` — only if you want it; nothing in the draft path calls OpenAI yet.

Everything else in `.env.example` is already correct for the $0 draft path.

> ⚠️ Do not commit `.env`, and do not copy it through anything that syncs to a cloud folder.

## 4. Build and load the extension

```powershell
pnpm --filter @jaaffl/extension build
```

Then in Chrome: `chrome://extensions` → **Developer mode** ON (top-right) → **Load unpacked**
(top-left) → select `apps\extension\dist`. Pin the JAAFFL icon via the puzzle-piece menu.

> After any later `git pull`, re-run the build **and click Reload on the extension card**. A
> loaded card serves the old build until reloaded.

## 5. Build the local data

`data/` is git-ignored, so nothing transferred. Rebuild it from the free feeds:

```powershell
.venv\Scripts\python.exe scripts\preflight.py --seed
```

This pulls nflverse + FFC, seeds the id crosswalk (~4,700 players), and prints the board. Expect
it to **exit 1** with `the engine cannot compute a survival model` while `JAAFFL_MY_TEAM_ID` is
empty — that is the Tier-12 guard doing its job, and the rest of its output is still the proof
that the board built. To confirm the whole thing works end to end, run it once with a throwaway
slot:

```powershell
$env:JAAFFL_MY_TEAM_ID = "7"; .venv\Scripts\python.exe scripts\preflight.py; Remove-Item Env:\JAAFFL_MY_TEAM_ID
```

That must print `OK: every startable position ... is fillable` and exit 0.

## 6. Verify the machine before you trust it

```powershell
.venv\Scripts\python.exe -m pytest backend -q
pnpm -r typecheck
pnpm -r test
pnpm lint
```

All four must be green. Then confirm the service really serves:

```powershell
.venv\Scripts\python.exe -m jaaffl.api
```

and in a second terminal:

```powershell
curl http://127.0.0.1:8788/health
```

Expect `{"status":"ok","version":"..."}`. Stop the server with Ctrl+C.

> **If the port is busy:** `netstat -ano | findstr ":8788"` then `taskkill /F /PID <pid>`.
> `pkill` does not exist on Windows.

## 7. You are ready

Go to [`rehearsal-protocol.md`](rehearsal-protocol.md) and run one draft.
