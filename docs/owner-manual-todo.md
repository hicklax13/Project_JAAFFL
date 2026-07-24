# Owner-manual TODO (Connor-only tasks)

Tasks only the owner can do (record-mode capture, keys, auth, decisions). Deferred to the end
of each build phase on purpose — nothing here blocks the automated build unless flagged. Do the
`[BLOCKER]` items when you want the feature they gate; the `[WHEN YOU WANT IT]` items are opt-in.

## 1. CBS record-mode capture session  `[PARTIAL BLOCKER — CBS field mapping only]`

> 📋 **Full step-by-step walkthrough:** [`docs/live-draft-recording-guide.md`](live-draft-recording-guide.md)
> — exact install commands, Chrome load-unpacked steps, and the record-mode buttons.

The one real-frame session. It unblocks the **real** CBS field shapes that the code currently
mocks behind `TODO(capture)`: the settings-page parse (Stage 2), `CbsOnPageProvider`'s real
projections/injuries/rankings mapping and the `CbsPageSnapshot` schema
(`backend/src/jaaffl/domain/models.py`, `backend/src/jaaffl/providers/cbs_onpage.py`), and — new
in **Phase 4 (Stage 5 engine)** — two more things:

- **The real CBS scoring VALUES — RESOLVED (owner-confirmed 2026-07-17).** The owner provided the
  official JAAFFL2025 scoring (passing 1 pt / 50 yds, no offensive turnover penalty, K distance
  bonuses +1 at 50 / +1 more at 60, DST single points-allowed bracket 0-9 = 6 with no yards-allowed
  tier), now encoded in `backend/src/jaaffl/league/defaults.py::jaaffl_scoring()`. A captured CBS
  scoring page still overrides it via `CbsOnPageProvider.league_settings()` if the room ever differs
  (config/league.json roster stays immutable). Only CBS *frame parsing* (live draft-room shapes)
  remains capture-blocked.
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

- **Live $0 recommendations — ✅ RESOLVED (PR #14, merged `fb338d2`; no owner action needed).**
  `NflreadpyProvider.players()` now loads the FREE nflverse universe via `load_ff_playerids()`
  (real pull verified: **4,571 players**), so with `JAAFFL_PRECOMPUTE_ENABLED=true` a live server
  serves `GET /recommendation` **503→200** on the $0 tier with **no fixture injection**.
  `ingest/resolve.resolve_pick_ids` masks name-only manual-paste picks upstream of the frozen
  `recommend()`; recorded fixtures keep CI offline. *(This was the former `[BLOCKER]`; it is done.)*
- **Draft board + pick-log panels**  `[DONE — branch feat/post-v1-unblocked]`. Shipped: `GET /state`
  (folded `DraftState` + drafted-player name resolution) and the dashboard **board (round × team
  grid, self-ordering to draft slots) + pick-log ticker** (`apps/web` `BoardPanel`), rendered as the
  mockups' table + ticker (semantic table; AG Grid stays removed as overkill). Value-curve / survival
  / manager-tendency panels remain the follow-up analytics.
- **Vercel deploy auth**  `[WHEN YOU WANT IT — otherwise it's localhost]`. The dashboard runs
  local-first at `127.0.0.1`. Hosting it on Vercel is opt-in and needs your Vercel auth; not done.
- **Status-pill text contrast (WCAG AA) — design-palette decision**  `[WHEN YOU WANT IT]`. The
  small status pills (`.is-good/.is-warning/.is-critical` in `design/tokens/draft-room.css`) render
  the accent hue as text on a 15–17% tint of the same hue. In the **light** theme the ~11px pill
  text falls below the 4.5:1 AA contrast minimum (measured roughly: good ≈2.6:1, warning ≈1.5:1,
  critical ≈3.6:1; critical is also ≈3.3:1 in dark). This is **not** a functional a11y blocker —
  identity is never colour-alone (every pill carries a glyph + word, satisfying WCAG 1.4.1), and
  the surrounding body text/ink/focus are AA — but the pill *text legibility* itself is sub-AA.
  It was left for you because a correct fix darkens the pill text in light mode (and would brighten
  it in dark), which touches the Appendix-B brand palette. Concrete proposed fix (no chart/bar
  impact): add theme-aware `--pill-ink-{good,warning,critical}` tokens (dark shades in light theme,
  bright in dark) used only by the three `.is-*` selectors' `color`, leaving the tinted
  backgrounds/borders as-is. Tell Claude "approve the pill-contrast tokens" (or hand over your own
  brand-safe shades) and it lands with a contrast check baked into the token drift-guard.

## Later phases (add here as they surface)

- Stage 7 assistant: an OpenAI key (`OPENAI_API_KEY`).
- Any MCP / connector authorizations a future phase needs.
