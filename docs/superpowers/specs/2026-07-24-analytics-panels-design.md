# Design — Dashboard analytics panels (value curves + survival curves)

**Date:** 2026-07-24 · **Status:** approved (owner) · **Stage:** 6 (two-surface UI)

Completes the last non-owner-gated item in [`ROADMAP.md`](../../../ROADMAP.md) Stage 6: the
remaining dashboard analytics panels. Ships **positional value curves** and **full survival
curves**; **manager-tendency is out of scope** (see §7).

---

## 1. Motivation

The war room renders the decomposed recommendation, the board, and the pick log. Two analytical
views are missing, and one of them is already flagged in code —
[`apps/web/components/charts.tsx`](../../../apps/web/components/charts.tsx) says the shipped
survival panel shows only the scalar `next_turn_availability`, and that *"the full S_j(N)-over-pick
curve needs the ADP mean+SD series, a precompute enrichment."*

Both panels answer live draft questions the current UI cannot:

- **Value curve** — *"how steep is the drop at this position, and how much of it is already gone?"*
- **Survival curve** — *"can I wait a round on him, or is he gone?"*

## 2. Decisions (owner-approved)

| Decision | Choice | Rationale |
|---|---|---|
| Charting | **Bespoke accessible SVG/CSS** | Zero new deps; matches shipped panels; theme + a11y already solved. ECharts (ROADMAP) and AG Grid stay out. |
| Value-curve composition | **Single chart + position toggle** | Larger and more readable than small-multiples; fits the analytics rail. |
| Value-curve data | **Remaining (solid) + full preseason board (ghost)** | The gap between the two lines *is* the positional run. |
| Survival composition | **Multi-line decay curves** | Only the curve *shape* answers "can I wait?"; gets a full-width row. |
| Feed | **New `GET /analytics`** | Independent 503 gate — see §3.1. |

## 3. Architecture

```
DraftContext (cached per league)  ──┐
  mu · baselines · position         ├─► engine/analytics.py ──► GET /analytics ──► fetchAnalytics()
  adp_mean · adp_sd · tiers · players│    (pure, network-free)   (own 503 gate)    + refreshAnalytics()
DraftState (folded from events) ────┘                                                     │
                                                              ┌───────────────────────────┴──────────┐
                                                       ValueCurvePanel (rail)      SurvivalCurvePanel (row)
```

`RecommendationEngine.context_for(league_id)`
([`engine/service.py`](../../../backend/src/jaaffl/engine/service.py)) is already a public
accessor, so the API reaches the cached context with **no engine surgery**. The frozen hot path
(`recommend`, `optimize`, `opponents`, `tiers`, `projections`, `context`) is untouched.

Refresh reuses the shipped convention from
[`use-recs.ts`](../../../apps/web/components/use-recs.ts): *"the board is a pull view (no push
channel of its own): hydrate it once, then re-pull on each `/recs/ws` push."* `refreshAnalytics()`
sits beside the existing `refreshBoard()`.

### 3.1 Why a separate endpoint, not an extension of `GET /state`

`/state` gates only on **draft events** (404 unknown league / 409 not started) and needs no engine
context. The analytics need `context_for()`, which returns `None` while precompute warms → **503**.
Different data, different failure modes.

Merging them forces a bad trade: either the board dies whenever the engine context is not ready, or
per-field nullability quietly muddies the shipped, tested `DraftBoardStateSchema`. Separate
endpoints let the board render from raw events while analytics independently reports "warming up".

Rejected alternative — **pushing over `WS /recs/ws`**: changes a versioned protocol
(`RECS_PROTOCOL_VERSION`), bloats the hot push path, and contradicts the codebase's own pull-view
convention.

## 4. Backend

### 4.1 New module `backend/src/jaaffl/engine/analytics.py`

Pure functions plus their Pydantic view model in one module — bundling model and builder exactly as
[`ingest/board.py`](../../../backend/src/jaaffl/ingest/board.py) does for the board. Network-free,
provider-free, and **not** on the per-pick hot path.

**Value curves.** For **QB / RB / WR / TE only**. K and DST are drafted in the final rounds and
their curves are flat — charting them adds noise without informing a decision
(`config/league.json` `strategic_notes` records the last-rounds convention).

- `VOR = context.mu[pid] − context.baselines[position]`, ranked descending.
- Two series per position: `full` (original board) and `remaining` (undrafted only).
- Capped at **36 players per position** to bound payload (three rounds deep at 12 teams).

**Survival curves.** `S_j(N) = 1 − Φ((N − m_j^eff)/s_j)` sampled across the pick horizon, reusing
[`opponents.pick_probabilities`](../../../backend/src/jaaffl/engine/opponents.py) so the panel and
the engine share one survival definition — including the R3 board-conditioned `adp_shift`
(`m_j^eff = m_j − β·run_pressure`), so the curves reflect what the engine actually recommends on.

- **Candidate count: 6**, matching the existing scalar `SurvivalPanel`'s `slice(0, 6)` so the two
  survival surfaces show the same players.
- **Sampling domain:** every integer pick `N` from `state.current_overall_pick` through
  `next_overall_pick(horizon=2)` **plus a 6-pick tail**, so the curve visibly continues past your
  second turn rather than ending exactly on the marker.

**Pick markers — a hard constraint.** `config/league.json` sets `"infer_from_team_count": false`;
the draft order is decided in person and entered into CBS. Marker picks **must** come from
[`opponents.next_overall_pick(settings, state, horizon=H)`](../../../backend/src/jaaffl/engine/opponents.py),
which reads `settings.draft_order`. `H=1` is your next pick, `H=2` the turn after. Deriving snake
positions from team count is forbidden and would silently mis-place every marker.

### 4.2 New endpoint `GET /analytics`

`GET /analytics?league_id=<id>&candidates=<id,id,...>` in
[`api/app.py`](../../../backend/src/jaaffl/api/app.py).

- Same `require_allowed_origin` guard as `/state` (read-only, defense in depth).
- 404 unknown league / 409 not started — mirroring `/state`.
- **503** when `context_for()` returns `None` (engine warming).
- `candidates` is **optional**: the dashboard passes the ids it already holds from the WS push, so
  the survival lines always match the ranked picks rendered above them. Omitted → defaults to the
  **top 6 available by projected points**, keeping the endpoint self-contained and independently
  testable. Ids not present in the context are ignored rather than erroring.

### 4.3 Shared schema

`packages/shared/src/analytics.ts` — Zod mirror exported from `index.ts`, explicitly **outside**
`CONTRACT_SCHEMAS` in [`parity.test.ts`](../../../packages/shared/tests/parity.test.ts). This
follows the documented precedent in
[`packages/shared/src/state.ts`](../../../packages/shared/src/state.ts): the board view model is
*"deliberately OUTSIDE the E5 Pydantic⇄Zod parity surface … a client-render convenience, not a
cross-boundary contract the gate must police."* The module docstring must cite that precedent.

## 5. Frontend

Both panels use bespoke SVG over existing design tokens
([`design/tokens/draft-room.css`](../../../design/tokens/draft-room.css)), which already provide
per-position colours (`--pos-qb/rb/wr/te`) with **light and dark variants**, plus
`--good/--warning/--critical`, `--hairline`, `--grid`, `--ink`, `--font-mono`. No hard-coded hex —
colours resolve through `var()`/`currentColor` so both themes work automatically.

### 5.1 `apps/web/components/value-curve-panel.tsx`

- Position toggle as real `<button>` chips with `aria-pressed`, coloured by `--pos-*` to match
  `PositionChip`.
- **Solid** line = remaining; **faint ghost** line = full preseason board.
- Dashed horizontal rule at `VOR = 0`, labelled "replacement".
- `role="img"` plus a descriptive `aria-label` (top VOR, cliff location, count taken), following the
  shipped pattern in `charts.tsx`.

### 5.2 `apps/web/components/survival-curve-panel.tsx`

- One line per candidate; dashed vertical markers at your next picks (`horizon` 1 and 2).
- Legend reuses `survivalOutlook()` from
  [`packages/shared/src/survival.ts`](../../../packages/shared/src/survival.ts), so this panel can
  never disagree with the overlay about what counts as scarce, and identity is never colour-alone
  (WCAG 1.4.1 — every entry carries a glyph **and** a word).
- No animated path drawing under `prefers-reduced-motion`.

### 5.3 Layout

The value curve joins `SurvivalPanel` / `TierLadder` in the `.dr-analytics` rail. The multi-line
survival chart becomes a full-width row below `BoardPanel`, where it has the horizontal room its
shape needs. The existing scalar `SurvivalPanel` **stays** — it is the at-a-glance read; the new
chart is the depth view.

## 6. Degraded states

Mirrors the shipped honesty contract rather than inventing one.

| Condition | Behaviour |
|---|---|
| 503 (context warming) | Panels read "warming up"; **the board keeps rendering** — the point of §3.1 |
| 404 / 409 | Same degraded copy pattern as the board |
| Fetch throws (status 0) | Keep the last series, matching the board's keep-last-on-null reducer |
| Pre-draft (no picks) | Value curve renders the full board (remaining ≡ full); survival shows "appears once the draft starts" |

## 7. Out of scope

- **Manager-tendency panel.** Reads the `manager_tendencies` table, which accrues **across**
  drafts. This is the league's first tracked draft, so there is no data to chart. Shipping an empty
  panel dressed as insight would violate the project's live-data honesty posture. Revisit after ≥1
  recorded draft.
- **ECharts / AG Grid** — superseded by the bespoke-SVG decision (§2).
- **XGBoost residual projections**, higher-fidelity E2 objective — separate stretch tracks.

## 8. Testing (TDD, red → green)

**Backend (pytest).** `analytics.py`: VOR ordering descending; `remaining` diverges from `full`
after picks; K/DST excluded; per-position cap respected; survival **monotonically decreasing in N**
and bounded to [0, 1]; `candidates` honoured and default selection correct; `None` when context is
missing. Endpoint: 200 shape, 404, 409, **503**, and Origin-allowlist rejection — mirroring the
existing `/state` tests.

**Frontend (vitest + testing-library).** Panels: render series, empty states, toggle switches series
(`aria-pressed`), `aria-label`s present. `lib/api.ts`: `fetchAnalytics` status mapping including an
unparseable 200 body. `use-recs`: `refreshAnalytics` fires on hydrate and on each push, and keeps
the last series on a null result.

**Commands.** Backend `cd backend && ../.venv/Scripts/python.exe -m pytest`; lint/format from
`backend` targeting `. ../scripts` (ruff, line-length 100); JS `pnpm -r typecheck` / `pnpm -r test`.

## 9. Delivery

One PR, squash-merged, CI watched green before the work is called done. No new dependencies, so no
CI extra changes are required.
