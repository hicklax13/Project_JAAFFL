# Owner-manual TODO (Connor-only tasks)

Tasks only the owner can do (record-mode capture, keys, auth, decisions). Deferred to the end
of each build phase on purpose — nothing here blocks the automated build unless flagged. Do the
`[BLOCKER]` items when you want the feature they gate; the `[WHEN YOU WANT IT]` items are opt-in.

## 1. CBS record-mode capture session  `[PARTIAL BLOCKER — CBS field mapping only]`

The one real-frame session. It unblocks the **real** CBS field shapes that the code currently
mocks behind `TODO(capture)`: the settings-page parse (Stage 2) and — new in Phase 3 —
`CbsOnPageProvider`'s real projections/injuries/rankings mapping and the `CbsPageSnapshot` schema
(`backend/src/jaaffl/domain/models.py`, `backend/src/jaaffl/providers/cbs_onpage.py`).

Steps:
1. Open a CBS mock draft with the extension loaded.
2. Click the extension action button to toggle **record mode**.
3. Run the mock draft to completion (frames land git-ignored under
   `apps/extension/fixtures/cbs/` via `POST /dev/recordings`).
4. Tell Claude "capture done" — Claude finalizes `parse.ts` field mappings, fills the real
   `CbsPageSnapshot` fields, and promotes redacted golden fixtures.

Not a build blocker: nflverse + FFC providers are fully built and tested without it. Manual-paste
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

## Later phases (add here as they surface)

- Stage 6 dashboard: Vercel deploy auth.
- Stage 7 assistant: an OpenAI key (`OPENAI_API_KEY`).
- Any MCP / connector authorizations a future phase needs.
