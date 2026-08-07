# Shared `whyTermBar` geometry — design

**Date:** 2026-07-17 · **Status:** approved · **Scope:** refactor, behavior-preserving

Flagged by the Phase-5 `/simplify` pass (reuse + altitude agents) and deferred from the Stage-6
merge PR. Sibling of [`2026-07-17-recs-socket-core-design.md`](2026-07-17-recs-socket-core-design.md).

## Problem

`decomposeWhy` in `packages/shared/src/why.ts` already returns each term's `anchor`, `barFraction`,
`colorRole`, and signed `contribution`. But the translation of those into **box geometry + display
text** lives in each renderer:

- `apps/web/components/why-panel.tsx` — `TermRow`: the anchor/sign → `{left|right: 50%, width: ×50%}`
  vs left-anchored `×100%` ternary, plus `fmt`/`fmtSigned`.
- `apps/extension/src/overlay/overlay.ts` — `whyRow` + `signed`: the same rule as an if/else.

So a rescale is a two-file edit, while the module's own contract comment already claims
"one visual system". Worse, **no test anywhere asserts the geometry** (see below), so the two-file
edit is one no suite would catch you getting half-right.

## Verified divergences

Read line-by-line from both renderers (not from the `/simplify` summary):

| Case                           | Web (`TermRow`)                        | Overlay (`whyRow`)                     |
| ------------------------------ | -------------------------------------- | -------------------------------------- |
| `anchor: "left"`               | `left: 0`, `width: bf*100%`            | `left="0"`, `width=bf*100%`            |
| diverging, `contribution < 0`  | `right: "50%"`, `width: bf*50%`        | `right="50%"`, `width=bf*50%`          |
| diverging, `contribution >= 0` | `left: "50%"`, `width: bf*50%`         | `left="50%"`, `width=bf*50%`           |
| midline                        | `.sc-mid` at `left: 50%` iff diverging | `.sc-mid` at `left: 50%` iff diverging |
| display text                   | `mlv ? toFixed(1) : signed`            | `mlv ? toFixed(1) : signed`            |
| minus glyph                    | U+2212 (verified by codepoint)         | U+2212 (verified by codepoint)         |

**None.** Unlike the socket refactor, the two copies are currently behavior-equivalent — including
the minus glyph, which is U+2212 MINUS SIGN in both, not an ASCII hyphen. This is a pure dedup with
no divergence to reconcile, so **every existing suite must pass untouched**; that is the proof the
refactor is behavior-preserving.

## Two verified facts that shape the design

### 1. The doc comment is a fossil, and it is load-bearing

`why.ts:17–20` claims the dashboard renders a **horizontal waterfall** and only the overlay renders
diverging bars. This is false about the code (`TermRow` renders the same bars as `whyRow`) and out
of step with the plan. `waterfall` appears in that comment and **nowhere else in the repo** — not in
`docs/implementation-plan.md`, not in `design/mockups/dashboard.html` (which renders
`.sc-row`/`.sc-track`/`.sc-fill`).

Plan **§6.5** is the authority and specifies bars for both surfaces:

| Term      | §6.5 geometry                                                            | Colour                  |
| --------- | ------------------------------------------------------------------------ | ----------------------- |
| MLV       | left-anchored, ≥0                                                        | `--pos-{pos}`           |
| VONA      | left-anchored; clamped at 0                                              | `--brass-solid`         |
| Risk      | **diverging around 0** via `.sc-mid`: penalty left/red, bonus right/pine | `--critical` / `--pine` |
| Cliff     | left-anchored, ≥0                                                        | `--pine`                |
| Modifiers | small chips, capped                                                      | status hues             |

This matters beyond tidiness: had the waterfall been live, sharing geometry would be _wrong_ — it
would hard-code a model the dashboard was scheduled to outgrow. It is not live. The comment is
corrected as part of this work.

### 2. The sign → CSS-edge mapping is inverted, and it is correct

§6.5 says a penalty paints **left/red**. The code gives a negative contribution `right: 50%` —
pinning the fill's _right_ edge at the midline so it grows **leftward**, painting the left half.
So a negative contribution's CSS edge is `right`.

This is why the field is named **`anchorEdge`, not `side`**: `{ side: "right" }` for a bar the user
sees on the left invites a future reader to "fix" the sign and invert every penalty bar on both
surfaces. `anchorEdge` names what it is — the CSS edge to pin.

## Design

### Helper — `packages/shared/src/why.ts`, beside `decomposeWhy`

```ts
export type WhyBarEdge = "left" | "right";

export interface WhyTermBar {
  /** CSS edge to pin the fill to — NOT the visual side. See whyTermBar. */
  anchorEdge: WhyBarEdge;
  offsetPct: number;
  widthPct: number;
  /** Percent offset of the `.sc-mid` zero tick, or null when the term has no zero crossing. */
  midlinePct: number | null;
  displayValue: string;
}

const DIVERGING_MIDPOINT_PCT = 50;
const FULL_TRACK_PCT = 100;

export const formatScore = (n: number): string => n.toFixed(1);
export const formatSignedScore = (n: number): string =>
  `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;

export function whyTermBar(term: WhyTerm): WhyTermBar;
```

Pure: same term in, same box out. `export * from "./why"` in `index.ts` re-exports it — no index
change needed.

**`midlinePct: number | null`, not `showMidline: boolean`.** A boolean would leave the renderer
hardcoding `left: "50%"`, so the midline's 50% would stay in two files while the fill's 50% moved to
one — half-delivering the goal. Carrying the offset means **no renderer writes a percentage literal
at all**. The `.sc-mid` tick, the fill's anchor offset, and a diverging fill's max width are all the
same constant, because they encode one fact: zero sits at the track's centre.

**Formatters exported, not module-private.** `fmt`/`fmtSigned` are used beyond `TermRow` — for
`why.score` (total + reconcile label), `why.residual`, and the modifier chips. Kept private, the
U+2212 rule would still live in two files: the exact drift this refactor removes. They format
`WhyDecomposition` fields, so `why.ts` is their home — matching the local convention that formatters
live beside the concept they format (`formatPct` lives in `survival.ts:55`; there is no generic
format module). The chips then render the identical string to the bar rows by construction.

Colour stays in the existing, already-tested `whyTermColorVar(role, position)` — folding it in would
create a second callable path to the same value.

### Renderers — both become pure

Each collapses to: `whyTermBar(term)` → `whyTermColorVar(term.colorRole, position)` → apply.
`TermRow`'s ternary and `whyRow`'s if/else both disappear. Web keeps its `data-testid`; the overlay
keeps `.sc-val`. The extension's `signed` is used _only_ by `whyRow` and is deleted outright.

Out of scope: the overlay's `best.score.toFixed(1)` and alt-row formatting are untouched.

### Typing note

`fill.style[bar.anchorEdge] = ...` is fine on `CSSStyleDeclaration` (imperative, extension). React's
`CSSProperties` with a _computed_ union key may widen to a string index signature and fail to
satisfy the type. The cast-free escape is mutation, since both `left` and `right` accept `string`:

```tsx
const fill: CSSProperties = { width: `${bar.widthPct}%`, background: color };
fill[bar.anchorEdge] = `${bar.offsetPct}%`;
```

To be **confirmed by `tsc`, not assumed**. Fallback if it fights: a conditional spread, which costs a
branch but keeps every _value_ sourced from `bar`.

## Tests

TDD: the `whyTermBar` suite is written and failing before the helper exists. New
`describe("whyTermBar")` in `packages/shared/tests/why.test.ts` pins what nothing currently asserts:

- MLV → `anchorEdge: "left"`, `offsetPct: 0`, `widthPct: 100` (dominant ⇒ full track),
  `midlinePct: null`, `displayValue: "33.7"` — **unsigned, because MLV is a level, not a delta**.
- Diverging penalty → `anchorEdge: "right"` (paints left of the midline, §6.5 penalty left/red),
  `offsetPct: 50`, `midlinePct: 50`, `widthPct: (2.1/33.7)*50`.
- Ceiling-tilt bonus (`risk_penalty: -1.5`) → `anchorEdge: "left"` (paints right, §6.5 bonus
  right/pine).
- U+2212 asserted **by codepoint**, not by eyeballing a glyph indistinguishable from a hyphen.
- Midline present iff diverging; a diverging fill capped at half the track, left-anchored at full.
- Edge cases: `contribution === 0` (→ `anchorEdge: "left"`, width 0) and `barFraction === 0`
  (all-zero components ⇒ `maxMag === 0`).

## Verification

`make test` + `tsc`, plus the E4 Playwright spec. The three existing suites pass **untouched** —
that is the behavior-preserving check, not an afterthought:

- `packages/shared/tests/why.test.ts` — existing `decomposeWhy` cases unchanged.
- `apps/web/components/why-panel.test.tsx` — asserts the MLV fill's `background`, and
  `toHaveTextContent("2.1")` against rendered `"−2.1"` (substring match ⇒ still green).
- `apps/extension/tests/overlay.test.ts` — counts `.sc-fill` ≥ 4.
- `apps/extension/e2e/overlay.spec.ts` (E4) — counts `.sc-fill`. Every term still yields exactly one
  `.sc-fill`, so the count is unchanged.
