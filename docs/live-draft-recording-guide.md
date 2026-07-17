# Recording a live CBS fantasy draft — step-by-step owner guide

A do-it-in-order checklist for capturing a **CBS Sports fantasy football draft** with JAAFFL's
record mode. Follow the numbered steps top to bottom. Everything runs **on your own computer**,
inside **your own logged-in CBS browser session** — nothing is sent to a server you don't control.

> This is the owner task described in
> [`owner-manual-todo.md` §1 "CBS record-mode capture session"](owner-manual-todo.md). Doing it
> once (on a **mock** draft) is what unlocks the real CBS field shapes so the assistant's parsers
> can be finalized.

---

## 0. Read this first — what recording does and doesn't do (2 min)

**What a recording IS:** while record mode is ON, the extension quietly copies every draft data
frame CBS sends to your browser (plus periodic snapshots of the draft board) into local files on
your disk. That capture is the deliverable — it's what lets the parsers be finalized so live
recommendations can be wired up.

**What to expect on screen today:** the on-page overlay panel will show **"Watching the board"**.
Live auto-recommendations are **not wired in the free ($0) path yet** (the engine replies
"warming up" until a player-universe loader lands — see
[`owner-manual-todo.md` §4](owner-manual-todo.md)). So the job of *this* session is to **record**,
not to get live pick advice. If you want picks fed in and echoed back during the draft, use the
**Manual paste** box (Step 11).

**Recommended flow:** do a full **mock draft** dry run first (Steps 1–9). Mocks run year-round, so
you rehearse the whole setup and capture the field shapes with zero pressure. Then the exact same
steps record your **real** draft on draft night.

**Time budget:** ~20–30 min one-time install; ~5 min to start recording each session.

---

## 1. Your league settings (confirm these match your CBS league)

These are memorialized in [`config/league.json`](../config/league.json) and are treated as fixed.
Before your real draft, open your league's **Settings** page on CBS and confirm every row matches:

| Setting             | Value                                                                      |
| ------------------- | -------------------------------------------------------------------------- |
| **Platform**        | CBS Sports                                                                 |
| **Draft type**      | Snake                                                                       |
| **Teams**           | 12                                                                         |
| **Draft order**     | Decided in-person, then entered into the CBS system (not a plain snake)    |
| **Scoring**         | Standard (**non-PPR** — 0 points per reception)                            |
| **Rounds**          | 17                                                                         |

**Roster slots per team (9 starters + 8 bench = 17):**

| Slot      | Count | Notes                                             |
| --------- | ----- | ------------------------------------------------- |
| QB        | 1     |                                                   |
| RB        | 1     |                                                   |
| WR        | 3     |                                                   |
| **WR/RB** | 1     | Flex — **WR or RB only** (no TE, QB, K, or DST)   |
| TE        | 1     |                                                   |
| K         | 1     |                                                   |
| DST       | 1     |                                                   |
| Bench     | 8     |                                                   |

> If anything on CBS differs, **stop and tell Claude** — do not edit `config/league.json` yourself.
> These values are the immutable "league constitution" the whole engine calibrates against.

---

## 2. Install the prerequisites (one time)

You need four things. Install any that you don't already have:

| Tool              | Version   | Download                                                            |
| ----------------- | --------- | ------------------------------------------------------------------- |
| **Google Chrome** | current   | https://www.google.com/chrome/                                      |
| **Python**        | ≥ 3.11    | https://www.python.org/downloads/                                   |
| **Node.js**       | 22 (LTS)  | https://nodejs.org/en/download                                      |
| **pnpm**          | ≥ 10      | https://pnpm.io/installation                                        |
| **uv** (optional) | current   | https://docs.astral.sh/uv/getting-started/installation/            |

Quick way to install pnpm once Node is present:

```bash
npm install -g pnpm
```

**Verify everything is on your PATH** (each should print a version, not an error):

```bash
google-chrome --version 2>/dev/null || echo "Chrome installed via the app is fine"
python3 --version      # 3.11 or newer
node --version         # v22.x
pnpm --version         # 10.x or newer
```

---

## 3. Get the project and install its dependencies (one time)

Open a terminal, go to wherever you keep code, and get the repo. If you already have the project
folder, just `cd` into it and skip the clone.

```bash
# from the folder where you keep your projects:
git clone https://github.com/hicklax13/project_jaaffl.git
cd project_jaaffl
```

Create your local env file and install both halves (Python backend + JS workspace):

```bash
cp .env.example .env
make setup
```

`make setup` installs the FastAPI backend (editable) and the pnpm workspace. It can take a few
minutes the first time. **You do not need to edit `.env`** for recording — the defaults are correct
(no API keys required for the $0 recording path).

---

## 4. Build the browser extension (one time, re-run only after code changes)

The extension ships as source; you build a loadable `dist/` folder from it:

```bash
pnpm --filter @jaaffl/extension build
```

This creates **`apps/extension/dist/`** — that's the folder you'll point Chrome at in the next step.

> Prefer live-rebuild while developing? Run `make ext-dev` instead (watch mode). For recording,
> the one-shot `build` above is simpler.

---

## 5. Load the extension into Chrome (one time)

1. Open Chrome.
2. In the address bar, type **`chrome://extensions`** and press **Enter**.
3. Turn **Developer mode** **ON** — the toggle is in the **top-right** corner.
4. Click **"Load unpacked"** — the button is in the **top-left**.
5. In the file picker, select the folder **`apps/extension/dist`** (from Step 4) and confirm.
6. A card titled **"JAAFFL — CBS Draft Assistant"** appears. Make sure its toggle is **ON** (blue).
7. **Pin the icon** so you can click it during the draft: click the **puzzle-piece 🧩 (Extensions)**
   icon at the right of Chrome's toolbar, find **JAAFFL — CBS Draft Assistant**, and click the
   **pin 📌** next to it. The JAAFFL icon now sits in your toolbar.

**Verify the load (optional but recommended):** on the JAAFFL card, when you later open a CBS draft
page, "Inspect views" should list **three** content scripts. If the extension icon never shows a
badge in Step 8, see [Troubleshooting](#12-troubleshooting).

---

## 6. Start the JAAFFL backend (each session)

The extension streams what it records to a small local service. Start it from the project root in
its **own terminal window** and leave it running:

```bash
make backend-dev
```

You should see it come up on **`127.0.0.1:8788`**. Confirm it's healthy in a second terminal (or
your browser):

```bash
curl http://127.0.0.1:8788/health
# → {"status":"ok","version":"..."}
```

Or just open **http://127.0.0.1:8788/health** in Chrome — you should see `{"status":"ok",...}`.

> Keep this terminal open for the whole draft. Closing it stops recording capture.

---

## 7. Open the CBS draft room (each session)

In the **same Chrome profile** where you loaded the extension and are **logged into CBS**:

- **For a rehearsal (do this first):** go to **https://www.cbssports.com/fantasy/football/**,
  and start a **Mock Draft** from the Fantasy Football area.
- **For your real draft (draft night):** open your league and click into the **Draft Room** when
  it opens.

The extension activates **automatically** on draft pages — it only runs on URLs that look like:

```
https://*.cbssports.com/fantasy/draft/*
https://*.football.cbssports.com/*draft*
```

You don't click anything to "attach" it; being on the draft page is enough.

---

## 8. Turn ON record mode (the one button that matters)

With the **CBS draft tab focused**:

1. Click the **JAAFFL toolbar icon** you pinned in Step 5. Its tooltip reads
   **"JAAFFL (click to toggle record mode)"**.
2. A red **`REC`** badge appears on the icon. **Recording is now ON.**

That's the whole toggle — one click. Behind the scenes the extension now streams every observed
draft frame (and periodic board snapshots) to the backend, which writes them to disk.

**Confirm it's actually capturing** (either check works):

- Watch the backend terminal from Step 6 — you'll see `recording_stored` log lines appear (frames
  flush about every 5 seconds).
- Or list the capture folder and watch a `rec-*.jsonl` file appear and grow:

  ```bash
  ls -la apps/extension/fixtures/cbs/
  ```

---

## 9. Run the draft to completion

Draft normally in the CBS room — pick your players, let the clock run, let other teams pick. The
recorder captures the whole thing in the background. **Do not close** the CBS tab or the backend
terminal until you're done.

For a mock rehearsal, you can let it auto-draft to the end quickly — you just need a complete run so
every kind of frame (settings, on-the-clock, picks, results) is captured at least once.

---

## 10. Turn OFF record mode and hand off

1. When the draft is finished, click the **JAAFFL toolbar icon again**.
2. The red **`REC`** badge disappears — **recording is OFF** and a final flush is written.
3. Your capture is saved locally under:

   ```
   apps/extension/fixtures/cbs/rec-<timestamp>.jsonl
   ```

   (These files are **git-ignored** — they may contain your league name and are never committed.
   Only redacted "golden" fixtures get committed later, by Claude.)
4. **Tell Claude: "capture done."** Claude then finalizes the CBS field mappings (`parse.ts`),
   fills in the real snapshot fields, reconciles the scoring map, and promotes redacted fixtures —
   the work that unlocks live recommendations.

---

## 11. Manual paste — the guaranteed way to feed picks (fallback)

Because live auto-parsing isn't finalized yet (that's what Step 10 unlocks), the reliable way to
get picks *into* JAAFFL during any draft is the **Manual paste** box built into the overlay:

1. On the CBS draft page, find the JAAFFL overlay panel (top-right of the page).
2. Expand **"Manual paste (fallback)"**.
3. Paste CBS's pick log, **one pick per line**, in this format:

   ```
   ORDER: T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12
   1. Team Name - Player Name, RB, PHI
   2. Team Name - Player Name, WR, MIN
   13. Team Name - Player Name, QB, BUF
   ```

   - The optional **`ORDER:`** line supplies the **in-person draft order** (your league decides the
     order in person, so JAAFFL can't infer it — this is how you tell it).
   - Each pick line is: `<pick #>. <Team> - <Player>, <POS>, <NFL team>`.
4. Click **"Send picks."** The status shows how many events were accepted.

This routes through the exact same validation path as live capture, so it's a safe draft-day
backstop no matter what.

---

## 12. Troubleshooting

| Symptom                                             | Fix                                                                                                                              |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| No `REC` badge after clicking the icon              | Make sure the extension card is **ON** in `chrome://extensions`, then reload the CBS tab and click the icon again.               |
| Overlay panel never appears on the CBS page         | Confirm the URL matches the patterns in Step 7. Reload the page. Check the extension card is enabled.                            |
| `curl http://127.0.0.1:8788/health` fails           | The backend isn't running — start it with `make backend-dev` (Step 6) and leave that terminal open.                              |
| No `rec-*.jsonl` file appears while recording       | Backend must be running **before** you toggle REC. Check the backend terminal for errors; re-toggle REC off/on.                  |
| Extension card shows fewer than 3 content scripts   | Known `@crxjs` build risk with the MAIN-world entry. Re-run `pnpm --filter @jaaffl/extension build`, remove + re-load unpacked.  |
| CBS settings don't match Step 1's table             | **Don't** edit `config/league.json`. Tell Claude what differs so the conflict is handled correctly.                             |

---

## Command cheat-sheet

```bash
# One-time setup
git clone https://github.com/hicklax13/project_jaaffl.git
cd project_jaaffl
cp .env.example .env
make setup
pnpm --filter @jaaffl/extension build      # → apps/extension/dist/  (load unpacked in Chrome)

# Each session
make backend-dev                            # start the local service on 127.0.0.1:8788
curl http://127.0.0.1:8788/health           # verify it's up
ls -la apps/extension/fixtures/cbs/         # watch captures land while REC is on
```

**The one button:** click the pinned **JAAFFL toolbar icon** to start recording (red `REC` badge),
click it again to stop. When done, tell Claude **"capture done."**
