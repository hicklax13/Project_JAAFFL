# Roadmap

Dependency-ordered build plan, distilled from the
[research report](docs/research/cbs-fantasy-football-draft-tool.md §"Final implementation
roadmap"). Each stage maps to package boundaries already scaffolded in the repo. Build in
order — later stages assume the earlier contracts exist.

> **Execution-ready detail:** the phased, task-level build plan that fills in each stage below —
> with file paths, interfaces, schemas, acceptance criteria, a v1-vs-stretch split, and a
> sequenced backlog — lives in [`docs/implementation-plan.md`](docs/implementation-plan.md)
> (its §10 Phasing maps to these same stages). This roadmap is the index; the implementation
> plan is the how.

Legend: `[ ]` not started · `[~]` scaffolded (stub/contract in place) · `[x]` done

> ## 📍 Status — 2026-07-25 (verified against code + a live server on a pristine data dir)
>
> **Tier 1 of the spec-vs-code audit is merged** (PRs #29–#31). Three specified inputs existed but
> never reached the engine; all three now do:
>
> - **Projections are real.** μ was `max(0, 300 − ecr)` — linear in expert rank. `build_projections`
>   now consumes `Capability.EXPECTED_POINTS` (nflverse xEP) through `league/xep.py`, scored under
>   the owner-verified `jaaffl_scoring` map, with `xep_season = season − 1` (nflreadpy **raises**
>   for 2026 — xEP is retrospective). σ is per-player from measured weekly residuals; the flat
>   ~50-for-everyone σ floor is replaced by year-over-year drift measured over two season-pairs
>   (`scripts/measure_projection_sigma.py`). Live board: 447 players, 377 with real xEP,
>   267 distinct σ (was 9), adjacent-μ gaps no longer a constant 1.0.
> - **The engine is on by default.** `jaaffl_precompute_enabled` defaulted to `False` and was
>   absent from `.env`, so a fresh clone could never serve a real pick.
> - **The id crosswalk seeds itself** in precompute. This was worse than "drafted players aren't
>   masked": on a fresh clone ADP resolved **0/179** and ECR **0/508**, so `/recommendation`
>   returned 200 with **`vona = 0.00` on every pick** — a dead opponent model behind a healthy
>   status code. Now 147 ADP / 387 ECR / 4,358 CBS links, seeded automatically.
>
> **Stages 0–6 core are built and green** (backend 474 + shared 86 + extension 93 + web 61; the
> backend suite also passes with all non-loopback network hard-blocked — and the blocker itself is
> verified to fire, so that is not a green light over a no-op). The live **$0 recommendation path
> works end-to-end**: real nflverse player universe → transparent engine → decomposed pick pushed
> to the overlay over `WS /recs/ws`.
>
> **Tier 2 of the audit is merged** (PRs #33–#37) — *trust & honesty on the primary surface*. Five
> places where the overlay looked like it was working:
>
> - **The foot renders.** `footRoster`/`footSync` were created, appended, and never assigned, so
>   sync age and recompute ms had never rendered. `recompute_ms` + a roster summary now ride the
>   `Recommendation` contract (the overlay never receives a `DraftState`, and inferring a roster
>   from pick numbers would synthesize draft structure). Sync age is measured **client-side from
>   receipt** and ticks on a timer — a server-stamped age would freeze when the socket died,
>   reading "fresh" forever over rotting data.
> - **Degraded modes are visible.** Nothing ever called `setStatus("manual")`, so a capture failure
>   still looked fully live. Manual provenance is now latched from the real paste path and outranks
>   a *healthy* socket (never a degraded one). The `ESTIMATED` badge is keyed off **trust**
>   (`!manualBoard && socketState === "live"`), not the displayed status word — keying it off the
>   word made the caveat vanish on "Reconnecting…", i.e. exactly as things got worse.
> - **`?mc=true` is real.** `use_mc_vona` appeared only on `recommend()`'s signature. Wired to a new
>   `simulate.mc_expected_best_available`, which estimates the same quantity as the analytic form
>   but with a *coupled* opponent model. Measured (239 players, horizon 2, 2000 rollouts): analytic
>   **p95 9 ms** vs MC **p95 1.14 s** (plan budget <2 s), RB VONA 59.51 → 65.96, and **the two
>   disagree on the #1 pick**. The response now states `vona_method`.
> - **`Why?` works, and pin is its own control.** `whyBtn` had no listener at all; `onPin` rode the
>   Copy handler and the content script never passed it. The panel renders locally from
>   `ScoreComponents` (available even when the backend is not) and shows the score **reconciling to
>   the sum of its terms** — §6.5 made checkable rather than promised — plus σ band, reliability,
>   VONA horizon, `E[best available next]`, and the capped modifiers the bars filter out.
> - **Projection provenance is visible.** `PlayerProjection.sources` never left the backend; ~70
>   ECR-only players (no modeled μ, still the `300 − rank` curve) were indistinguishable from
>   xEP-backed ones. Now on `RecommendedPick.projection_sources`, with one shared rule
>   (`packages/shared/src/provenance.ts`) so overlay and dashboard cannot drift.
>
> **Tier 3 of the audit is merged** (PRs #39–#44) — *draft-night readiness*. Every piece was
> individually tested and none had ever run together on real frames. A complete captured 12×14
> draft now replays end to end — raw NUL-terminated frames → `parse.ts` → `handle_event` →
> `fold_state` → `resolve_pick_ids` → `recommend()` — asserting on the **rendered pick**, not on
> health signals. It found four real defects, none of which any unit test could see:
>
> - **The overlay's VONA was structurally 0.00 on draft night.** No CBS frame names the *viewer's*
>   own team, so `parse.ts` cannot emit `my_team_id`; `opponents._my_overall_picks` then raises and
>   survival degrades to "everyone is available". `GET /recommendation?team_id=` supplies the slot —
>   the `/recs/ws` **push** path that actually feeds the overlay did not. Measured on the real
>   capture at pick 25: with the slot, best pick `mlv 83.00 − E[best avail next] 64.91 = vona 18.09`;
>   without it, `E[best available next]` collapses onto the pick's own MLV and vona is exactly 0.00.
>   Fixed via `JAAFFL_MY_TEAM_ID` **and** a new `Recommendation.survival_basis`, because a degraded
>   0.00 is indistinguishable from a computed one on the wire.
> - **Nothing consumed the `subscribe` snapshot.** Not hypothetical: the owner's 2026-07-25 session
>   began recording mid-draft, so its deltas cover overalls **4–168** and picks 1–3 exist only in
>   that snapshot. Replaying deltas alone left three drafted players unmasked and recommendable.
> - **The manual-paste regex split on hyphenated surnames.** `9. 9 - Jaxon Smith-Njigba, WR, SEA`
>   parsed to `team_id "9 - Jaxon Smith"` / `player_name "Njigba"` — a pick that resolves to nobody
>   and is offered again. The code carried a *reasoned comment* defending the greedy match; real NFL
>   rosters falsify it. The separator is space-surrounded; a surname hyphen is not.
> - **The fixture redactor corrupted its own goldens.** A real one-character team display name in the
>   new capture made `safety_net`'s substring pass rewrite every occurrence of that letter:
>   `"upcomingorder"` → `"upcominTeam 5order"`, `"state":"picking"` → `"pickinTeam 5"` — the two
>   fields the parser reads for draft order and completion.
>
> Also closed from Tier 2's leftovers: projection provenance now marks the **top-5 rows**, not only
> the best pick and the dashboard banner; and MC-VONA is held off the push path by a
> **structural** (mutation-verified) guard rather than a flaky wall-clock gate.
>
> **What Tier 3 did NOT do** (scoped honestly): a **replay is not a live draft.** The pipeline has
> now run end to end on real captured frames, but it has still never run against a LIVE CBS room —
> no draft-night rehearsal against a room that is actually ticking. `ESTIMATED` is still driven by a
> degraded *board*, not the forward-year trigger §6.6 names: `xep_season = season − 1` is
> retrospective, so **no forward-year figure exists to flag** — the trigger would have nothing to
> fire on. `Why?` remains a local decomposition, **not** wired to the Responses API (§6.8); an
> `OPENAI_API_KEY` now exists, but that path adds a network call, a cost, and a latency budget to the
> one surface that must not stall mid-draft, so it wants its own design rather than a Tier-3
> bolt-on. MC-VONA still has **no wall-clock CI gate** at 2000 rollouts — local margin to the 2 s
> budget is ~43%, which a slower runner would eat, so the timing stays a local measurement and CI
> asserts the invariant that actually protects the budget: MC cannot reach the push path at all.
> The **settings-page** parse and `CbsPageSnapshot` remain capture-blocked.
>
> The `feat/post-v1-unblocked` branch adds, all TDD'd + verified: the **`GET /state` board +
> pick-log** endpoint and its **dashboard panels**; the **Stage 7 assistant key-free core**
> (`explain_recommendation` prose over `ScoreComponents` + wired tool `dispatch`); and the **E1
> flex-split** and **E3 projection-validation** calibration tooling (both run live — E1 measured
> RB 12 / WR 0 for 2026, kept as dry-run per owner; E3 persistence 2023→2024 Spearman 0.59).
>
> The stretch **simulation + tuning** subsystem is done too (`engine-stretch` extra): CP-SAT
> `optimize_roster`, the `simulate_draft`/agents/MC-VONA simulator, **E2** tuning (Optuna study +
> no-regression gate, run live on real 2026 data — kept the priors), and the **E6** efficacy
> tournament (our agent beats VBD-only + ADP-only baselines on the fixture pool, p=0.0002).
>
> What remains: the **OpenAI Responses API loop** (needs an owner key), the **manager-tendency
> analytics panel** (value-curve + survival-curve panels are done; manager tendencies await ≥1
> recorded draft to accrue `manager_tendencies` rows), and the deeper **stretch** items (XGBoost
> residual projections, per-manager tendency modeling, a large offline real-data E2 study). The
> record-mode capture session is **DONE** (2026-07-24) and its protocol is decoded. Owner-only
> tasks: [`docs/owner-manual-todo.md`](docs/owner-manual-todo.md).

## Stage 1 — CBS sync layer

- [x] MV3 extension that runs only on CBS fantasy league/draft pages (`apps/extension`)
- [x] Content scripts extract league metadata + live pick events; normalize to shared schema
      *(**capture DONE 2026-07-24** — the network-frame vocabulary is now the REAL decoded CBS
      protocol, see [`docs/research/cbs-draft-protocol.md`](docs/research/cbs-draft-protocol.md):
      NUL-terminated frames, `picks/completed`, `fullstatedelta.order`. DOM-selector and
      settings-page vocabularies remain synthetic — they need a settings/board capture)*
- [x] Stream normalized events to the localhost backend (`jaaffl.api`, `jaaffl.ingest`)
- [x] **Decided against `webRequest`/`declarativeNetRequest`** — replaced by the 3-probe MAIN-world
      capture (WebSocket + `fetch`/XHR monkeypatch, React-fiber framework read, `MutationObserver`
      fallback); cookies API not used

## Stage 2 — Normalize league settings

- [~] Parse CBS roster slots, flex eligibility, scoring rules, team count, keeper/dynasty
      flags, and draft order from the live room / settings pages (`jaaffl.league`)
      *(scoring model + JAAFFL2025 values complete; the live draft-room **order** now reads from
      the real `fullstatedelta.order` — never inferred. The settings-PAGE parse is still
      capture-blocked: the 2026-07-24 session captured draft-room frames, not a settings page)*
- [x] Never assume snake order from league size — read the actual draft board *(enforced in
      `parse.ts` + engine horizon; order comes from the board / manual-paste, never inferred)*
- [x] Persist every league snapshot for self-owned historical analysis *(snapshot-every-settings
      into the warehouse, PR #7)*

## Stage 3 — Data warehouse

- [x] DuckDB + Parquet + SQLite local warehouse (`jaaffl.data`)
- [x] Stable player/team/league IDs and crosswalks (CBS, NFL, FantasyPros, nflverse)
- [ ] **[stretch]** Schema stable enough to graduate to Postgres `jsonb` + Redis Streams if multi-user

## Stage 4 — External data tiers

- [x] Provider protocol + registry (`jaaffl.providers`)
- [x] **$0 prototype tier (default):** nflverse / nflfastR historical stats (free) + **FFC ADP** +
      CBS on-page projections/rankings/ADP read via the extension from the user's session
- [ ] **[opt-in, off by default]** Paid tier: FantasyPros rankings/projections/ADP/news/injuries
      *(disabled stub present; needs an owner key + enable flag)*
- [ ] **[out of scope for the prototype]** Commercial tier: SportsDataIO / Sportradar real-time,
      behind the same interface *(disabled stubs present)*

## Stage 5 — Transparent draft engine

- [x] Exact CBS scoring translation + replacement values + tier breaks (`jaaffl.league`)
- [x] Projection ensemble (`jaaffl.engine.projections`) *(PR #29: **real** nflverse xEP
      (`Capability.EXPECTED_POINTS`) + ECR, both scored under the owner-verified `jaaffl_scoring`
      map. Replaces the `300 − ecr` placeholder. Per-player σ from measured weekly residuals;
      per-position drift σ measured, not chosen (`scripts/measure_projection_sigma.py`). CBS
      on-page projections remain a third source once a settings/board capture exists — that path
      is still unreachable, `cbs_page_snapshots` has 0 rows)*
- [x] Opponent pick-probability model — analytic survival (`jaaffl.engine.opponents`)
- [x] Marginal Lineup Value via Hungarian assignment (`jaaffl.engine.optimize`) — the v1 flex-aware
      optimizer the engine actually uses
- [x] **[stretch]** Draft simulator + agents + MC-VONA (`jaaffl.engine.simulate`) — `simulate_draft`
      (full snake to completion), the behavioral/Score agents, and `simulate_drafts` (E[best
      available]); analytic VONA remains the shipped v1 hot-path default. **`?mc=true` is now
      actually wired** (PR #35): `mc_expected_best_available` replaces the analytic per-position
      `E_π` with a coupled rollout, the response states `vona_method`, no readable draft order
      degrades to analytic *and says so*, and `simulate` imports lazily so the analytic path pays
      nothing. Measured: analytic p95 9 ms · MC p95 1.14 s at 2000 rollouts (budget <2 s)
- [x] **[stretch]** Constrained roster optimization via OR-Tools CP-SAT
      (`jaaffl.engine.optimize::optimize_roster`) — the season-simulator end-state ILP *(needs
      `engine-stretch`)*
- [ ] **[stretch]** Only then: XGBoost residual models, injury-risk calibration, 2027 aging curves
- [x] Treat 2027 outputs as **ESTIMATED** unless a forward-year vendor feed is licensed *(policy
      enforced)*

## Stage 6 — Two-surface UI

- [x] Thin in-page overlay: best pick / next-turn risk / why (`apps/extension` overlay) *(Tier 2,
      PRs #33/#34/#36/#37: the **foot** renders roster + a ticking sync age + recompute ms; the
      **manual-paste** and **ESTIMATED** degraded states are driven from the real paste path;
      **`Why?`** opens a local decomposition that shows the score reconciling to its terms; **pin**
      has its own control writing an advisory `chrome.storage.local` log; ECR-only projections are
      **marked**. Verified in real Chromium via the E4 Playwright spec, not only jsdom)*
- [x] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`) *(live
      recommendation feed, **draft board & pick-log** via `GET /state`, and the **value-curve +
      survival-curve** analytics panels via `GET /analytics` — all done; manager-tendency panel
      deferred until ≥1 recorded draft accrues `manager_tendencies` rows)*
- [x] **AG Grid removed by design** (deep-research: overkill for a 204-cell static board);
      distributions/trends render as **bespoke accessible SVG** (no ECharts dependency)

## Stage 7 — AI assistant (wire early, integrate last)

- [x] Typed function tools for DB queries, league-state summaries, news lookups (`jaaffl.assistant`)
      *(dispatch wired: `explain_recommendation` renders `ScoreComponents` prose via
      `explain_pick`, `league_summary` folds settings+state; `query_warehouse`/`player_news` stay
      NotImplementedError until the LLM loop)*
- [ ] OpenAI Responses API: function calling + file search + optional web search *(the only
      key-gated piece — needs an owner `OPENAI_API_KEY`)*
- [ ] **Text-only.** Voice / Realtime is explicitly out of scope for the prototype (see ADR 0003)

## Cross-cutting

- [~] **Calibration (Track J)** — `jaaffl.calibrate` + `scripts/`: **E1** flex-split
      (`calibrate_flex_split.py`), **E3** projection-validation (`validate_projections.py`), and
      **E2** param tuning (`tune_engine_params.py` — Optuna study + no-regression gate; `--real`
      builds a precompute-backed pool), and the **E6** efficacy tournament (`run_tournament.py` —
      our agent vs VBD-only / ADP-only baselines) all done + run live. **E2 re-run 2026-07-25**
      against the real xEP-backed μ (the prior run had tuned against the `300 − ecr` placeholder,
      fitting its "optimum" to synthetic value) — gate again says **KEEP baseline**
      (`+3.18 pts/slot`, `min_slot −0.41`, `p = 0.41`). Nothing written; `config/engine.json`
      stays owner-adopted. ⚠️ That re-run also exposed **two harness problems** (see
      `docs/owner-manual-todo.md` §1): the held-out opponent `NeedBasedAgent` never consumes its
      `rng`, so `--eval-seeds` is **inert** and the gate has zero simulation variance; and
      **pure-MLV (κ=α=λ=0) PASSES that gate** (`+14.74/slot`, `min_slot +0.00`, `p = 0.0010`)
      while the tuned vector fails it. E2 as configured therefore cannot validate the strategic
      terms — a stochastic held-out mix is the remaining calibration follow-up
- [x] **Projection σ measurement** — `scripts/measure_projection_sigma.py` (read-only) measures the
      per-position year-over-year projection error that anchors the risk band, replacing the flat
      v1 σ placeholder. Also settles season-sum vs rate×17 for μ with two-year-pair evidence
- [ ] Playwright kept for testing / emergency draft-room recovery (not the production path)
- [~] Compliance guardrails enforced in code & docs (see `docs/legal-and-compliance.md`)
