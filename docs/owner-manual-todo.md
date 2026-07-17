# Owner-manual TODO (Connor-only tasks)

Tasks only the owner can do (record-mode capture, keys, auth, decisions). Deferred to the end
of each build phase on purpose — nothing here blocks the automated build unless flagged. Do the
`[BLOCKER]` items when you want the feature they gate; the `[WHEN YOU WANT IT]` items are opt-in.

## 1. CBS record-mode capture session  `[PARTIAL BLOCKER — CBS field mapping only]`

The one real-frame session. It unblocks the **real** CBS field shapes that the code currently
mocks behind `TODO(capture)`: the settings-page parse (Stage 2), `CbsOnPageProvider`'s real
projections/injuries/rankings mapping and the `CbsPageSnapshot` schema
(`backend/src/jaaffl/domain/models.py`, `backend/src/jaaffl/providers/cbs_onpage.py`), and — new
in **Phase 4 (Stage 5 engine)** — two more things:

- **The real CBS scoring VALUES.** The engine scores every projection under
  `backend/src/jaaffl/league/defaults.py::cbs_standard_scoring()` — CBS's *published* Standard
  defaults (verified/cited: passing TD = 6, DST dual points+yards brackets, K 50+ = 5). Your live
  room may be commissioner-customized, so those values stay behind `TODO(capture)` until the
  capture confirms them; the real map then arrives via `CbsOnPageProvider.league_settings()`
  (config/league.json stays immutable).
- **Calibration against real drafts (E1/E2/E3).** The tunables in `config/engine.json` (flex split
  8RB/4WR, κ, λ-table, α, reliability shrinkage, situation caps) are literature/first-principles
  priors. E1 measures the flex split from live FFC ADP (top-60); E2/E3 tune the weight vector and
  validate μ/σ against real boards. All optional — the engine ships and runs on the priors.

Steps:
1. Open a CBS mock draft with the extension loaded.
2. Click the extension action button to toggle **record mode**.
3. Run the mock draft to completion (frames land git-ignored under
   `apps/extension/fixtures/cbs/` via `POST /dev/recordings`).
4. Tell Claude "capture done" — Claude finalizes `parse.ts` field mappings, fills the real
   `CbsPageSnapshot` fields, reconciles the scoring map, and promotes redacted golden fixtures.

Not a build blocker: the engine, nflverse + FFC providers, and the `/recommendation` + `/recs/ws`
surfaces are fully built and tested against CBS-Standard defaults + synthetic fixtures. Manual-paste
stays the guaranteed draft-day fallback regardless.

## 2. Paid data providers  `[WHEN YOU WANT IT — off by default]`

The $0 tier (nflverse + FFC + CBS on-page) needs **no keys**. Only if you want fresher injuries
or an extra ADP/projection source:
1. Get an API key (FantasyPros is the cheap, recommended upgrade for live injuries).
2. Set the key + its enable flag in `.env` (e.g. `FANTASYPROS_API_KEY=...` and
   `JAAFFL_ENABLE_FANTASYPROS=true`).
3. The provider then appends after the free tier automatically. (Its adapter is a disabled stub
   today — tell Claude if you enable one so the real API calls get implemented.)

## 3. FFC resolution coverage (informational — no action required)  `[WHEN YOU WANT IT]`

Preseason real-flow check (2026): FFC ADP resolved **144 / 166** players to canonical ids; the
~22 unresolved are team defenses named "<City> Defense" and a few kickers/rookies not yet in the
free DynastyProcess crosswalk. Unresolved rows are logged and skipped (the engine tolerates gaps),
and all skill-position starters resolve. If you later want K/DST ADP fully covered, ask Claude to
add a DST city→team alias map; otherwise it's a safe, low-impact gap (K/DST go in the last rounds).

## 4. Stage 6 (UI) — live data + deferred panels

The dashboard + overlay are built, tested, and render the full decomposed recommendation
live. Three items are opt-in / follow-up, none block the UI:

- **Live $0 recommendations need a player-universe loader**  `[BLOCKER — when you want live recs
  without injecting fixtures]`. `NflreadpyProvider.players()` is not implemented yet, so flipping
  `JAAFFL_PRECOMPUTE_ENABLED=true` on a live server 503s gracefully until a network universe loader
  (nflverse `load_ff_playerids()`) lands. The 503→200 bridge itself is proven end-to-end through the
  injection seam (tests). Tell Claude "wire the live player universe" to implement it (needs the
  nflverse pull; recorded fixtures keep CI offline).
- **Draft board + pick-log panels**  `[WHEN YOU WANT IT]`. Deferred: they need a `GET /state`
  endpoint (folded `DraftState`) plus drafted-player name resolution (picks carry `player_id`; the
  board wants names). The mockups render these as a table + ticker; the deep-research found AG Grid
  is overkill for a 204-cell static board, so the AG Grid deps were removed to avoid shipping unused
  weight. Say the word and Claude adds the board (semantic table or AG Grid — your call).
- **Vercel deploy auth**  `[WHEN YOU WANT IT — otherwise it's localhost]`. The dashboard runs
  local-first at `127.0.0.1`. Hosting it on Vercel is opt-in and needs your Vercel auth; not done.

## Later phases (add here as they surface)

- Stage 7 assistant: an OpenAI key (`OPENAI_API_KEY`).
- Any MCP / connector authorizations a future phase needs.
