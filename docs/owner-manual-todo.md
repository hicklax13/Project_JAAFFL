# Owner-manual TODO (Connor-only tasks)

Tasks only the owner can do (record-mode capture, keys, auth, decisions). Deferred to the end
of each build phase on purpose — nothing here blocks the automated build unless flagged. Do the
`[BLOCKER]` items when you want the feature they gate; the `[WHEN YOU WANT IT]` items are opt-in.

## 1. CBS record-mode capture session  `[✅ DONE — 2026-07-24]`

> **The owner ran this.** One 12-team snake mock (14 rounds, bots) produced **8.4 MB** of real
> frames. The decoded result is [`docs/research/cbs-draft-protocol.md`](research/cbs-draft-protocol.md)
> — ground truth that replaced every `TODO(capture)` guess in the **network-frame** vocabulary of
> `apps/extension/src/lib/parse.ts`.
>
> Headline findings: CBS socket frames are **NUL-terminated** (this alone took parsed frames from
> 8/98 to 128); `picks/completed` is the pick event and picks are **ID-only**; `newstate.opick` is
> **forward-looking** (the pick on the clock, not the one just made); the real draft order lives in
> `fullstatedelta.order`, **not** the rolling `upcomingorder` window.
>
> Three live bugs were found and fixed in the process (PRs #24, #25): CWD-relative paths writing
> captures to a NON-git-ignored directory, CORS globs never matching (which recorded zero frames
> while looking healthy), and `env_file` being CWD-relative.
>
> ⚠️ **The raw captures under `apps/extension/fixtures/cbs/` contain the owner's email and other
> real drafters' ids/team names.** Git-ignored; keep them local. Committed fixtures are redacted via
> `scripts/redact_cbs_fixtures.py`.
>
> **Still open from this session:** live end-to-end resolution has **not** been exercised against a
> real draft — the pieces are individually tested but have never run together on live frames. Tier 2
> did not change this: it made the overlay tell the truth about the data it is given, which is a
> different thing from proving the pipeline works on real CBS frames. That is **Tier 3**. Also still
> `TODO(capture)`: the **settings-page** parse and `CbsPageSnapshot` projections/injuries/rankings
> (§4 below), which need a *settings/board* page capture rather than draft-room frames.
>
> ✅ **`scripts/seed_cbs_crosswalk.py` is no longer a prerequisite (PR #31).** The crosswalk now
> seeds itself on the first `/recommendation` (~4,400 players / ~4,360 CBS links from the free
> DynastyProcess table). Running the script after a capture is still worthwhile — it mines CBS ids
> that table lacks — but forgetting it no longer breaks draft night. Verified on a pristine data
> dir: an ID-only CBS pick now masks its player from the board with zero manual setup.

> 📋 **Full step-by-step walkthrough:** [`docs/live-draft-recording-guide.md`](live-draft-recording-guide.md)
> — exact install commands, Chrome load-unpacked steps, and the record-mode buttons.

The one real-frame session. It unblocked the **real** CBS field shapes that the code previously
mocked behind `TODO(capture)`: `CbsOnPageProvider`'s real projections/injuries/rankings mapping and
the `CbsPageSnapshot` schema (`backend/src/jaaffl/domain/models.py`,
`backend/src/jaaffl/providers/cbs_onpage.py`) remain outstanding, and — new
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
  **E2 was re-run on 2026-07-25** against the new *real* xEP-backed μ/σ (the earlier run had tuned
  against the `300 − ecr` placeholder, so its "optimum" was fitted to synthetic value). It again
  **kept the baseline**: the tuned vector was directionally better but not significantly so
  (`mean_diff +3.18 pts/slot`, `min_slot_diff −0.41`, `p = 0.41`), failing the no-regression gate.
  Nothing was written — the CLI is dry-run unless you pass `--write`, and `config/engine.json`
  stays owner-adopted.

  ⚠️ **Two things that re-run exposed about the E2 harness itself — READ BEFORE TRUSTING E2.**
  Neither is fixed; both are decisions for you.

  1. **`--eval-seeds` is inert.** The held-out opponent set is `[NeedBasedAgent()]`, and
     `NeedBasedAgent.pick` accepts `rng` and never uses it — it is fully deterministic. So the
     held-out evaluation has **zero simulation variance**: 1 eval seed and 6 eval seeds produce
     bit-identical numbers (measured twice; two studies with different trial counts and different
     tuned vectors reported the same `+3.18 / −0.41 / p=0.4062`). The gate's Wilcoxon is therefore
     a 12-slot paired test on ONE deterministic scenario, not a seed-varied estimate. Fix would be
     a stochastic held-out mix (e.g. include `AdpNoiseAgent`, which does consume `rng`).
  2. **Pure-MLV passes the gate that the tuned vector fails.** Turning every strategic term OFF
     (κ=0, α=0, λ≡0, no K/DST shrinkage — i.e. rank purely on Marginal Lineup Value) scores
     `+14.74 pts/slot` over the baseline with `min_slot_diff +0.00` and `p = 0.0010` —
     `would_promote = True`. Read it narrowly: that is against ONE deterministic, exploitable
     opponent archetype, and E6 separately shows the agent beating VBD-only/ADP-only baselines. It
     does **not** mean VONA/cliff/risk are worthless. It does mean **E2 as currently configured
     cannot validate them**, so "KEEP baseline" is a weak endorsement rather than a clean one.

Steps (kept for the next capture — e.g. a settings-page capture, or re-verifying on draft night):
1. Open a CBS mock draft with the extension loaded.
2. Click the extension action button to toggle **record mode**.
3. Run the mock draft to completion (frames land git-ignored under
   `apps/extension/fixtures/cbs/` via `POST /dev/recordings`).
4. Tell Claude "capture done."

Two things learned the hard way, worth knowing before the next one:

- **`make` is not installed** on the owner's Windows setup, so the guide's `make backend-dev` fails.
  Use `cd backend && ../.venv/Scripts/python.exe -m jaaffl.api` (now documented in the guide).
- **Chrome will prompt for "access other apps and services on this device."** That is Chrome's Local
  Network Access gate on the CBS page reaching `127.0.0.1:8788` — i.e. our own backend. It must be
  allowed or recording silently stalls. Revoke it afterwards via the icon left of the URL if desired.

Not a build blocker: the engine, nflverse + FFC providers, and the `/recommendation` + `/recs/ws`
surfaces are fully built and tested. Manual-paste stays the guaranteed draft-day fallback regardless.

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

## 3b. Two Tier-2 decisions left for you  `[WHEN YOU WANT IT]`

Neither blocks anything; both are judgement calls rather than bugs.

- **Monte-Carlo VONA is opt-in and slow on purpose.** `?mc=true` now genuinely runs (it used to be
  a silent no-op). Measured on the pick-1 worst case: **analytic p95 9 ms · MC p95 1.14 s** at the
  shipped `mc_rollouts = 2000`, against the plan's `<2 s` MC budget. It is NOT on the `/recs/ws`
  push path — the overlay always gets the analytic number — so you only pay this when you ask for
  it by hand. If you ever want MC on the live path, drop `mc_rollouts` (it is a real, tested
  budget knob) rather than raising the budget. MC and analytic **disagree on the #1 pick** on the
  synthetic board, so this is a genuine second opinion, not a rounding difference.
- **`ESTIMATED` currently means "degraded board", not "forward-year".** §6.6 names forward-year
  (2027) figures as the trigger. Nothing on the contract flags a forward-year projection today, so
  the badge is driven by the trigger we can actually detect: a manually-pasted or non-live board.
  Same badge, same treatment — say the word if you want a forward-year flag plumbed through too.

## 4. Stage 6 (UI) — live data + deferred panels

The dashboard + overlay are built, tested, and render the full decomposed recommendation
live. Three items are opt-in / follow-up, none block the UI:

- **Live $0 recommendations — ✅ RESOLVED (PR #14, merged `fb338d2`; no owner action needed).**
  `NflreadpyProvider.players()` now loads the FREE nflverse universe via `load_ff_playerids()`
  (real pull verified: **4,571 players**), so a live server serves `GET /recommendation`
  **503→200** on the $0 tier with **no fixture injection**. `JAAFFL_PRECOMPUTE_ENABLED` now
  **defaults to true** (PR #30) — it used to default to false and was absent from `.env`, so a
  fresh clone followed the documented setup and still got a permanent 503.
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
