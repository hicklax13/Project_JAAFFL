# whyTermBar Shared Geometry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a pure `whyTermBar(term)` helper beside `decomposeWhy` so the web `TermRow` and the extension `whyRow` become pure renderers of identical bar geometry + display text.

**Architecture:** `decomposeWhy` already yields each term's `anchor`, `barFraction`, `colorRole`, and signed `contribution`. Today each renderer re-derives box geometry (`{left|right, width}`) and display text from those fields — duplicated, and asserted by no test. This plan moves that derivation into one pure function in `packages/shared/src/why.ts`, exports the two score formatters alongside it, and reduces both renderers to: `whyTermBar(term)` + the existing `whyTermColorVar(...)` → apply. Behavior-preserving: the two copies are byte-equivalent today (incl. the U+2212 minus glyph), so every existing suite must pass **untouched**.

**Tech Stack:** TypeScript, pnpm workspaces, Vitest (unit), React 19 / Testing Library (web), jsdom + Shadow DOM (extension), Playwright (E4 e2e). Spec: [`docs/superpowers/specs/2026-07-17-why-term-bar-geometry-design.md`](../specs/2026-07-17-why-term-bar-geometry-design.md).

---

## ⛔ SEQUENCING GATE — read before Task 1

A **concurrent** Claude Desktop session ("Dedup /recs/ws client into shared core", *Session 1*) is
live-editing the SAME repo's `apps/extension/src/overlay/overlay.ts` (and `apps/web/lib/api.ts`,
`apps/extension/src/lib/recs.ts`). Its socket refactor and this one both modify `overlay.ts`.

**Do NOT begin Task 2 or any code change until Session 1 is fully merged to BOTH local `main` and
GitHub `origin/main`.** Implementation happens *after* the rebase, on top of Session 1's merged
`overlay.ts`, so there is no git merge conflict to resolve — instead we integrate one import line
into `overlay.ts`'s then-current shape. Task 1 is the gate; Task 2 is the rebase.

This plan lives on branch `worktree-refactor+why-term-bar` (worktree at
`.claude/worktrees/refactor+why-term-bar`), already carrying two commits: the design spec and a
`.gitignore` hygiene line. Baseline at authoring time: **typecheck green; 109 JS tests green**
(shared 57 / web 19 / extension 33).

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `packages/shared/src/why.ts` | The "why" decomposition + now its render geometry & score formatters | Add `WhyBarEdge`, `WhyTermBar`, `whyTermBar`, `formatScore`, `formatSignedScore`; fix stale render comment |
| `packages/shared/tests/why.test.ts` | Unit tests for the "why" primitives | Add `whyTermBar` + formatter suites |
| `apps/web/components/why-panel.tsx` | React renderer of the decomposition | `TermRow` uses `whyTermBar`; `WhyPanel` uses shared formatters; delete local `fmt`/`fmtSigned` |
| `apps/extension/src/overlay/overlay.ts` | Shadow-DOM overlay renderer | `whyRow` uses `whyTermBar`; delete local `signed` |

`packages/shared/src/index.ts` re-exports via `export * from "./why"` — **no index edit needed.**

---

## Task 1: Sequencing gate — verify Session 1 is fully merged

**No code.** This task only confirms the precondition. Do not proceed past it until every check says MERGED.

- [ ] **Step 1: Fetch and check GitHub `origin/main` carries Session 1's socket core**

Run:
```bash
cd .claude/worktrees/refactor+why-term-bar
git fetch origin
git show origin/main:packages/shared/src/socket.ts 2>/dev/null | grep -q "createRecsSocket" \
  && echo "origin/main: MERGED" || echo "origin/main: NOT YET — STOP AND WAIT"
```
Expected to proceed: `origin/main: MERGED`. `createRecsSocket` is Session 1's new export; its
presence on `origin/main` is the merge signal. If `NOT YET`, stop — the gate is closed.

- [ ] **Step 2: Confirm local `main` also updated (user required both)**

Run:
```bash
git show main:packages/shared/src/socket.ts 2>/dev/null | grep -q "createRecsSocket" \
  && echo "local main: MERGED" || echo "local main: NOT YET — STOP AND WAIT"
```
Expected to proceed: `local main: MERGED`.

- [ ] **Step 3: Confirm Session 1 left no uncommitted WIP in the main checkout**

Run:
```bash
git -C ../../.. status --porcelain -- apps/web/lib/api.ts apps/extension/src/lib/recs.ts apps/extension/src/overlay/overlay.ts
```
Expected: empty output (Session 1's edits are committed/merged, not dangling). If non-empty,
Session 1 is still working — stop and wait.

---

## Task 2: Rebase onto the merged `origin/main`

**Files:** none edited by hand; this re-bases the branch and re-verifies the baseline.

- [ ] **Step 1: Rebase the branch (spec + gitignore only) onto origin/main**

Run:
```bash
git rebase origin/main
```
Expected: clean replay. This branch's two commits touch only `docs/` and `.gitignore`, so **no
`overlay.ts` conflict occurs here** — the conflict the sequencing gate guards against is avoided by
implementing *after* this rebase, directly on Session 1's merged `overlay.ts`.
If `.gitignore` conflicts (Session 1 added a similar ignore), keep both rules and
`git rebase --continue`.

- [ ] **Step 2: Re-install deps (lockfile may have moved under Session 1)**

Run:
```bash
pnpm install --frozen-lockfile
```
Expected: `Done`. If the lockfile changed and `--frozen-lockfile` fails, run `pnpm install` and note
it in the PR.

- [ ] **Step 3: Re-verify a green baseline on the new base, before any edit**

Run:
```bash
pnpm -r typecheck && pnpm -r test
```
Expected: typecheck green; all suites green. Record the shared/web/extension counts — they are the
"untouched" targets for Tasks 4-5. (Session 1 may have changed the extension count; whatever it is
now is the target.)

- [ ] **Step 4: Read the post-merge overlay.ts import block**

Run:
```bash
sed -n '1,40p' apps/extension/src/overlay/overlay.ts
```
Note the exact current `@jaaffl/shared` import list — Task 5 adds `whyTermBar` into *that* list
(Session 1 may have added/removed names). Do not assume the authoring-time shape.

---

## Task 3: The `whyTermBar` helper + exported formatters (TDD)

**Files:**
- Modify: `packages/shared/src/why.ts` (add types/helper/formatters after `decomposeWhy`; fix comment at lines ~17-20)
- Test: `packages/shared/tests/why.test.ts` (append two `describe` blocks)

- [ ] **Step 1: Write the failing tests**

Append to `packages/shared/tests/why.test.ts`. First extend the import on line 10 to pull the new
symbols:

```ts
import {
  decomposeWhy,
  formatScore,
  formatSignedScore,
  parseEngineParams,
  whyTermBar,
  whyTermColorVar,
} from "../src/why";
import type { WhyTerm, WhyTermBar } from "../src/why";
```

Then append these suites:

```ts
describe("formatScore / formatSignedScore", () => {
  it("formatScore is unsigned, one decimal place", () => {
    expect(formatScore(33.7)).toBe("33.7");
    expect(formatScore(0)).toBe("0.0");
  });

  it("formatSignedScore always carries an explicit sign", () => {
    expect(formatSignedScore(3.4)).toBe("+3.4");
    expect(formatSignedScore(0)).toBe("+0.0");
    expect(formatSignedScore(-2.1)).toBe("−2.1");
  });

  it("signs the minus with U+2212 MINUS SIGN, never an ASCII hyphen", () => {
    const s = formatSignedScore(-2.1);
    expect(s.charCodeAt(0)).toBe(0x2212);
    expect(s).not.toContain("-"); // U+002D ASCII hyphen
  });
});

describe("whyTermBar — box geometry + display text (§6.5)", () => {
  const mkTerm = (over: Partial<WhyTerm>): WhyTerm => ({
    key: "cliff",
    label: "Cliff",
    contribution: 0,
    rawComponent: 0,
    anchor: "left",
    colorRole: "pine",
    barFraction: 0,
    ...over,
  });

  it("left-anchors MLV across the full track, unsigned (MLV is a level, not a delta)", () => {
    const b: WhyTermBar = whyTermBar(mkTerm({ key: "mlv", contribution: 33.7, barFraction: 1 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBeCloseTo(100);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("33.7");
  });

  it("signs a non-MLV left-anchored term and scales width over the full track", () => {
    const b = whyTermBar(mkTerm({ key: "cliff", contribution: 3.4, barFraction: 0.5 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBeCloseTo(50);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("+3.4");
  });

  it("anchors a diverging PENALTY to the RIGHT edge so it paints left of the midline (§6.5)", () => {
    const b = whyTermBar(
      mkTerm({ key: "risk", anchor: "diverging", contribution: -2.1, barFraction: 0.5, colorRole: "critical" }),
    );
    expect(b.anchorEdge).toBe("right");
    expect(b.offsetPct).toBe(50);
    expect(b.widthPct).toBeCloseTo(25); // barFraction * 50
    expect(b.midlinePct).toBe(50);
    expect(b.displayValue).toBe("−2.1");
  });

  it("anchors a diverging BONUS to the LEFT edge so it paints right of the midline", () => {
    const b = whyTermBar(
      mkTerm({ key: "risk", anchor: "diverging", contribution: 1.5, barFraction: 0.3, colorRole: "pine" }),
    );
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(50);
    expect(b.widthPct).toBeCloseTo(15);
    expect(b.midlinePct).toBe(50);
    expect(b.displayValue).toBe("+1.5");
  });

  it("keeps a zero-magnitude bar left-anchored with zero width", () => {
    const b = whyTermBar(mkTerm({ key: "cliff", contribution: 0, barFraction: 0 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBe(0);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("+0.0");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pnpm --filter @jaaffl/shared test
```
Expected: FAIL — `whyTermBar`, `formatScore`, `formatSignedScore`, and type `WhyTermBar` are not
exported yet (compile/import error). The existing `decomposeWhy`/`parseEngineParams`/`whyTermColorVar`
suites still pass.

- [ ] **Step 3: Implement the helper + formatters in `why.ts`**

In `packages/shared/src/why.ts`, add this block immediately **after** `decomposeWhy` (end of file):

```ts
export type WhyBarEdge = "left" | "right";

/** Pure render geometry + display text for one WhyTerm — the single source both surfaces consume. */
export interface WhyTermBar {
  /** CSS edge to pin the fill to — NOT the visual side. A diverging penalty pins `right` so it
   *  grows leftward (§6.5 penalty = left/red); naming it a "side" invites an inverted "fix". */
  anchorEdge: WhyBarEdge;
  /** Percent offset of the pinned edge within `.sc-track` (0 for left-anchored, 50 for diverging). */
  offsetPct: number;
  /** Fill width as a percent of the track. */
  widthPct: number;
  /** Percent offset of the `.sc-mid` zero tick, or null when the term has no zero crossing. */
  midlinePct: number | null;
  /** The label-adjacent number: MLV unsigned (a level), every other term signed (a delta). */
  displayValue: string;
}

const DIVERGING_MIDPOINT_PCT = 50;
const FULL_TRACK_PCT = 100;

/** Unsigned, one decimal — for levels (MLV) and the reconstructed total. */
export const formatScore = (n: number): string => n.toFixed(1);

/** Explicitly signed, one decimal — for deltas (every non-MLV term, residual, modifier chips).
 *  The minus is U+2212 MINUS SIGN, not an ASCII hyphen; why.test.ts pins this by codepoint. */
export const formatSignedScore = (n: number): string =>
  `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;

/**
 * Translate a decomposed term into the box geometry + display string both surfaces render, so a
 * rescale is a one-file edit and the geometry is unit-testable. The `.sc-mid` tick, the diverging
 * fill's anchor offset, and its max width are all `DIVERGING_MIDPOINT_PCT` because they encode one
 * fact: zero sits at the track's centre.
 */
export function whyTermBar(term: WhyTerm): WhyTermBar {
  const displayValue =
    term.key === "mlv" ? formatScore(term.contribution) : formatSignedScore(term.contribution);

  if (term.anchor === "diverging") {
    return {
      anchorEdge: term.contribution < 0 ? "right" : "left",
      offsetPct: DIVERGING_MIDPOINT_PCT,
      widthPct: term.barFraction * DIVERGING_MIDPOINT_PCT,
      midlinePct: DIVERGING_MIDPOINT_PCT,
      displayValue,
    };
  }
  return {
    anchorEdge: "left",
    offsetPct: 0,
    widthPct: term.barFraction * FULL_TRACK_PCT,
    midlinePct: null,
    displayValue,
  };
}
```

- [ ] **Step 4: Fix the stale render comment (lines ~17-20)**

Replace this block near the top of `why.ts`:

```ts
 * Rendering guidance (deep-research, resolved): the dashboard renders these terms as a
 * horizontal WATERFALL (a running additive total with signed steps — the defensible form
 * for an additive decomposition, cf. SHAP's own waterfall view); the compact overlay renders
 * them as diverging component bars. Both consume the same `terms` array below.
```

with:

```ts
 * Rendering guidance (plan §6.5, resolved): BOTH surfaces render these terms as component bars —
 * left-anchored for MLV/VONA/Cliff, diverging around zero for Risk and signed modifiers. The
 * Next.js dashboard (`TermRow`) and the Shadow-DOM overlay (`whyRow`) are pure renderers of the
 * same `terms` array AND the same `whyTermBar` geometry + `whyTermColorVar` colour helpers below,
 * so "one visual system" holds by construction, not convention.
```

(The word "waterfall" appears in this comment and nowhere else in the repo; plan §6.5 specifies bars
for both surfaces. This deletes the fossil.)

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
pnpm --filter @jaaffl/shared test
```
Expected: PASS — all suites green, including the two new blocks and every pre-existing
`decomposeWhy` case (unchanged).

- [ ] **Step 6: Typecheck shared**

Run:
```bash
pnpm --filter @jaaffl/shared typecheck
```
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add packages/shared/src/why.ts packages/shared/tests/why.test.ts
git commit -m "Add whyTermBar geometry helper + exported score formatters

Both 'why' renderers re-derived bar box-geometry and display text from a
WhyTerm; move that into one pure whyTermBar(term) beside decomposeWhy and
export formatScore/formatSignedScore (the U+2212 signing rule). Pins the
geometry — previously asserted by no test — and corrects the stale
'waterfall' render comment to match plan §6.5.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Web renderer becomes a pure consumer

**Files:**
- Modify: `apps/web/components/why-panel.tsx`
- Test: `apps/web/components/why-panel.test.tsx` (**not edited** — it must pass untouched)

- [ ] **Step 1: Replace the imports (lines 1-17 region)**

Replace the top import block:

```tsx
import type { ReactElement } from "react";

import {
  decomposeWhy,
  type EngineParamsSource,
  type Position,
  type RecommendedPick,
  type WhyTerm,
  whyTermColorVar,
} from "@jaaffl/shared";
```

with:

```tsx
import type { CSSProperties, ReactElement } from "react";

import {
  decomposeWhy,
  type EngineParamsSource,
  formatScore,
  formatSignedScore,
  type Position,
  type RecommendedPick,
  type WhyTerm,
  whyTermBar,
  whyTermColorVar,
} from "@jaaffl/shared";
```

- [ ] **Step 2: Delete the local formatters (lines 19-20)**

Delete these two lines:

```tsx
const fmt = (n: number): string => n.toFixed(1);
const fmtSigned = (n: number): string => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
```

- [ ] **Step 3: Rewrite `TermRow` to consume `whyTermBar`**

Replace the whole `TermRow` function:

```tsx
function TermRow({ term, position }: { term: WhyTerm; position: Position | null }): ReactElement {
  const bar = whyTermBar(term);
  const fill: CSSProperties = { width: `${bar.widthPct}%`, background: whyTermColorVar(term.colorRole, position) };
  fill[bar.anchorEdge] = `${bar.offsetPct}%`;
  return (
    <div className="sc-row">
      <span className="label" style={{ textTransform: "none", letterSpacing: ".02em" }}>
        {term.label}
      </span>
      <div className="sc-track" role="presentation">
        {bar.midlinePct !== null && <span className="sc-mid" style={{ left: `${bar.midlinePct}%` }} />}
        <span className="sc-fill" style={fill} />
      </div>
      <span className="mono" data-testid={`why-term-${term.key}`} style={{ fontSize: "var(--fs-xs)" }}>
        {bar.displayValue}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Update `WhyPanel`'s three formatter call sites**

In `WhyPanel`, replace `fmt(` → `formatScore(` and `fmtSigned(` → `formatSignedScore(`:
- `reconcileLabel`: `` `Reconstructs to ${formatScore(why.score)} from its components` `` and
  `` `Warning: does not reconstruct to ${formatScore(why.score)} (residual ${formatSignedScore(why.residual)})` ``
- modifier chip: `{term.label} {formatSignedScore(term.contribution)}`
- total `<b>`: `{formatScore(why.score)}`

- [ ] **Step 5: Run the web suite UNMODIFIED**

Run:
```bash
pnpm --filter @jaaffl/web test
```
Expected: PASS, same count as the Task 2 baseline. Note especially `why-panel.test.tsx`:
`.sc-fill` background still `var(--pos-rb)`; `why-term-mlv` still `33.7`; `why-term-risk` still
contains `2.1` (substring of rendered `−2.1`); total still `42.1`.

- [ ] **Step 6: Typecheck web**

Run:
```bash
pnpm --filter @jaaffl/web typecheck
```
Expected: green. If `fill[bar.anchorEdge] = ...` errors on the computed key, fall back to a
conditional spread (still sourcing every value from `bar`):
```tsx
const edge = bar.anchorEdge === "right"
  ? { right: `${bar.offsetPct}%` }
  : { left: `${bar.offsetPct}%` };
const fill: CSSProperties = { ...edge, width: `${bar.widthPct}%`, background: whyTermColorVar(term.colorRole, position) };
```

- [ ] **Step 7: Commit**

```bash
git add apps/web/components/why-panel.tsx
git commit -m "Render the web why-panel from shared whyTermBar geometry

TermRow's anchor/sign geometry ternary and the panel's local fmt/fmtSigned
are gone; it now consumes whyTermBar + the shared formatters. why-panel
tests pass untouched.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Extension overlay becomes a pure consumer

**Files:**
- Modify: `apps/extension/src/overlay/overlay.ts`
- Test: `apps/extension/tests/overlay.test.ts` + `apps/extension/e2e/overlay.spec.ts` (**not edited**)

- [ ] **Step 1: Add `whyTermBar` to the `@jaaffl/shared` import**

Using the current import block observed in Task 2 Step 4, add `whyTermBar` (alphabetically, before
`whyTermColorVar`). Keep every name Session 1 may have added. `WhyTerm`, `decomposeWhy`, and
`whyTermColorVar` remain. Example (reconcile against the actual post-merge list):

```ts
import {
  decomposeWhy,
  type DraftEvent,
  formatPct,
  type Position,
  type Recommendation,
  type RecommendedPick,
  survivalOutlook,
  type WhyTerm,
  whyTermBar,
  whyTermColorVar,
} from "@jaaffl/shared";
```

- [ ] **Step 2: Rewrite `whyRow` to consume `whyTermBar`**

Replace the whole `whyRow` function:

```ts
/** One Score-Components bar bound to a term (§6.5) — geometry + text from the shared whyTermBar. */
function whyRow(term: WhyTerm, position: Position | null): HTMLElement {
  const row = el("div", "sc-row");
  row.appendChild(el("span", "sc-label", term.label));
  const track = el("div", "sc-track");
  const bar = whyTermBar(term);
  if (bar.midlinePct !== null) {
    const mid = el("span", "sc-mid");
    mid.style.left = `${bar.midlinePct}%`;
    track.appendChild(mid);
  }
  const fill = el("span", "sc-fill");
  fill.style[bar.anchorEdge] = `${bar.offsetPct}%`;
  fill.style.width = `${bar.widthPct}%`;
  fill.style.background = whyTermColorVar(term.colorRole, position);
  track.appendChild(fill);
  row.appendChild(track);
  row.appendChild(el("span", "sc-val", bar.displayValue));
  return row;
}
```

- [ ] **Step 3: Delete the now-unused local `signed`**

Delete this line (was line ~137, just after `whyRow`):

```ts
const signed = (n: number): string => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
```

- [ ] **Step 4: Run the extension suite UNMODIFIED**

Run:
```bash
pnpm --filter @jaaffl/extension test
```
Expected: PASS, same count as the Task 2 baseline. `overlay.test.ts` still finds ≥ 4 `.sc-fill`
nodes (4 core terms → 4 fills, unchanged).

- [ ] **Step 5: Typecheck extension**

Run:
```bash
pnpm --filter @jaaffl/extension typecheck
```
Expected: green. `fill.style[bar.anchorEdge]` indexes `CSSStyleDeclaration` with a `"left"|"right"`
union — both are writable `string` properties, so this type-checks. If it errors, use an explicit
branch:
```ts
if (bar.anchorEdge === "right") fill.style.right = `${bar.offsetPct}%`;
else fill.style.left = `${bar.offsetPct}%`;
```

- [ ] **Step 6: Commit**

```bash
git add apps/extension/src/overlay/overlay.ts
git commit -m "Render the overlay why bars from shared whyTermBar geometry

whyRow's if/else geometry and the local signed() are gone; it now consumes
whyTermBar. Overlay unit + E4 selectors (.sc-fill count) unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Full verification — all gates + E4

**Files:** none. This is the behavior-preserving proof.

- [ ] **Step 1: Prove the three tested files are byte-untouched except the intended files**

Run:
```bash
git diff --stat origin/main...HEAD
```
Expected: only `packages/shared/src/why.ts`, `packages/shared/tests/why.test.ts`,
`apps/web/components/why-panel.tsx`, `apps/extension/src/overlay/overlay.ts`, plus the pre-existing
`docs/…` spec/plan and `.gitignore`. No test file other than `why.test.ts` is modified.

- [ ] **Step 2: Run every gate**

Run:
```bash
pnpm -r typecheck && pnpm -r lint && pnpm -r test
```
Expected: all green. Test counts: shared = baseline + the new `whyTermBar`/formatter cases; web and
extension = **exactly** their Task 2 baselines (untouched).

- [ ] **Step 3: Run E4 (Playwright) — the real overlay in Chromium**

Run:
```bash
pnpm --filter @jaaffl/extension exec playwright install --with-deps chromium
pnpm --filter @jaaffl/extension exec playwright test e2e/overlay.spec.ts
```
Expected: PASS. E4 bundles the overlay to an IIFE, injects it, calls `mountOverlay()` +
`handle.update(rec)`, and asserts the `.sc-fill` "why" bars paint into the Shadow DOM. If the
`playwright test` invocation differs in this repo, discover it first:
`grep -n '"test:e2e"\|playwright' apps/extension/package.json`.

- [ ] **Step 4: Confirm the duplication is actually gone**

Run:
```bash
grep -n "barFraction \* 50\|barFraction \* 100\|right: \"50%\"\|\* 50}%\|\* 100}%" \
  apps/web/components/why-panel.tsx apps/extension/src/overlay/overlay.ts || echo "NO geometry literals remain in either renderer ✓"
grep -rn "n >= 0 ? \"+\"" apps/web apps/extension || echo "NO local signed-formatter remains ✓"
```
Expected: both print the ✓ line — geometry math and the signing rule now live only in `why.ts`.

---

## Task 7: Rebase check, push, and open the PR

**Files:** none.

- [ ] **Step 1: Final fetch + rebase (in case main moved during implementation)**

Run:
```bash
git fetch origin
git rebase origin/main
```
Expected: clean. If `overlay.ts` now conflicts (main moved again), resolve by keeping Session 1's
surrounding code and this task's `whyRow`/import edits, then re-run Task 6 Steps 2-3 before pushing.

- [ ] **Step 2: Push the branch**

Run:
```bash
git push -u origin HEAD
```

- [ ] **Step 3: Open the PR**

Run (via `gh`; body via heredoc):
```bash
gh pr create --base main --title "Refactor: shared whyTermBar geometry for the two 'why' renderers" --body "$(cat <<'EOF'
Extracts a pure `whyTermBar(term)` beside `decomposeWhy` so `TermRow` (web) and `whyRow`
(extension) become pure renderers of identical bar geometry + display text — the geometry a
rescale used to require editing in two files, and that no test asserted.

## What changed
- `packages/shared/src/why.ts`: `whyTermBar`, `WhyTermBar`, `WhyBarEdge`, `formatScore`,
  `formatSignedScore`; corrected the stale "waterfall" render comment to match plan §6.5.
- `apps/web/components/why-panel.tsx`, `apps/extension/src/overlay/overlay.ts`: pure consumers.
- Also carries a one-line `.gitignore` rule for `.claude/worktrees/` (worktree hygiene).

## Why it's safe
The two renderers were byte-equivalent before this change (incl. the U+2212 minus). The web and
extension suites pass **untouched**; only `why.test.ts` gains cases (they pin the geometry for the
first time). All gates + E4 green. Rebased on top of Session 1's merged `/recs/ws` refactor.

Spec: `docs/superpowers/specs/2026-07-17-why-term-bar-geometry-design.md`
Plan: `docs/superpowers/plans/2026-07-17-why-term-bar-geometry.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Report the PR URL and stop**

Print the PR URL from Step 3's output. Do not merge — leave the PR for review.

---

## Self-Review (author checklist — completed at authoring time)

- **Spec coverage:** helper signature + `midlinePct` + `anchorEdge` naming (Task 3) ✓; exported
  formatters (Task 3) ✓; both renderers pure (Tasks 4-5) ✓; stale comment fix (Task 3 Step 4) ✓;
  TDD geometry incl. U+2212-by-codepoint (Task 3 Step 1) ✓; existing suites untouched + E4 (Task 6) ✓.
- **Placeholder scan:** none — every code step shows exact code; every command shows expected output.
- **Type consistency:** `whyTermBar`/`WhyTermBar`/`WhyBarEdge`/`formatScore`/`formatSignedScore`
  named identically across Tasks 3-5; `anchorEdge`/`offsetPct`/`widthPct`/`midlinePct`/`displayValue`
  field names consistent between the interface (Task 3) and both consumers (Tasks 4-5).
- **Sequencing:** Task 1 gate + Task 2 rebase precede every edit; Task 7 re-rebases before push.
