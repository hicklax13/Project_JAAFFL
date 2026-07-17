# Shared `createRecsSocket` Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the two ~90-line `/recs/ws` client state machines (`apps/web/lib/api.ts`, `apps/extension/src/lib/recs.ts`) into one `createRecsSocket` core in `packages/shared/src/socket.ts`, leaving each surface a ~15-line adapter, with zero behavior change.

**Architecture:** The core owns a canonical 5-phase machine (`connecting`/`live`/`stale`/`reconnecting`/`closed`) plus connect, backoff-with-cap reconnect, ping→pong, and frame→rec dispatch. Each surface translates phases to its own labels through a **total** `Record<RecsSocketPhase, TLabel | null>` map (`null` = deliberate suppression) and passes surface-specific hooks: web sends a `subscribe` frame via `onOpen`; overlay enables stale tracking via `staleAfterMs`. Stale tracking gates both the stale timer *and* the `live`-on-rec re-emit, which is what keeps the web byte-identical.

**Tech Stack:** TypeScript (strict, `noUncheckedIndexedAccess`, `verbatimModuleSyntax`), pnpm workspaces, Vitest, Playwright (E4), Zod (via existing `RecommendationSchema`).

**Design:** `docs/superpowers/specs/2026-07-17-recs-socket-core-design.md`

---

## Critical constraint: do not touch the existing test files

`apps/web/lib/api.test.ts` and `apps/extension/tests/recs.test.ts` must end this task **byte-for-byte unmodified**. They are the safety net that proves the refactor preserves behavior — an edited test that passes proves nothing. Same for `apps/extension/tests/overlay.test.ts`, `apps/web/components/dashboard.test.tsx`, and `apps/extension/e2e/overlay.spec.ts`.

If a change seems to require editing one of those files, **stop** — the adapter is wrong, not the test.

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `packages/shared/src/socket.ts` | Modify (append) | Add `RecsSocketPhase`, `WebSocketLike`, `RecsSocketOptions`, `createRecsSocket`. Keeps existing `parseRecsFrame` + `RECS_PROTOCOL_VERSION` untouched. |
| `packages/shared/tests/socket.test.ts` | Modify (append) | Add a `describe("createRecsSocket")` block. Keeps the existing `parseRecsFrame` block untouched. |
| `apps/web/lib/api.ts` | Modify `:65-153` | Web adapter. `fetchRecommendation`/`getRecommendation`/`fetchLeague` (`:1-63`) untouched. |
| `apps/extension/src/lib/recs.ts` | Modify (rewrite body) | Overlay adapter. |

`packages/shared/src/index.ts` already does `export * from "./socket"` — no change needed, but note it means **every** export from `socket.ts` becomes public API. Keep the backoff constant unexported.

---

### Task 1: Establish the green baseline

**Files:** none (verification only)

- [ ] **Step 1: Run every JS suite and the typecheck, before touching anything**

```bash
pnpm -r typecheck && pnpm -r test
```

Expected: all pass. Record the per-package test counts — Task 5 must match them exactly.
If anything is already red, **stop and report** — do not start a refactor on a red baseline.

---

### Task 2: The shared core (TDD)

**Files:**
- Modify: `packages/shared/src/socket.ts`
- Test: `packages/shared/tests/socket.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `packages/shared/tests/socket.test.ts`. Add `vi` to the existing vitest import
(`import { describe, expect, it, vi } from "vitest";`) and `createRecsSocket`,
`type RecsSocketPhase`, `type WebSocketLike` to the existing `../src/socket` import.

```ts
class FakeWs implements WebSocketLike {
  static instances: FakeWs[] = [];
  readyState = 0;
  sent: string[] = [];
  private listeners: Record<string, ((event: { data?: unknown }) => void)[]> = {};
  constructor(public url: string) {
    FakeWs.instances.push(this);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.readyState = 3;
    this.fire("close", {});
  }
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void {
    (this.listeners[type] ??= []).push(listener);
  }
  fire(type: string, event: { data?: unknown }): void {
    for (const l of this.listeners[type] ?? []) l(event);
  }
  open(): void {
    this.readyState = 1;
    this.fire("open", {});
  }
  message(payload: unknown): void {
    this.fire("message", { data: typeof payload === "string" ? payload : JSON.stringify(payload) });
  }
  static last(): FakeWs {
    return FakeWs.instances[FakeWs.instances.length - 1]!;
  }
}

const factory = (url: string): WebSocketLike => new FakeWs(url);

describe("createRecsSocket", () => {
  beforeEach(() => {
    FakeWs.instances = [];
  });

  it("emits connecting then live on open, against the given url", () => {
    const phases: RecsSocketPhase[] = [];
    createRecsSocket("ws://x/recs/ws", {
      onRecommendation: () => {},
      onStatus: (p) => phases.push(p),
      wsFactory: factory,
    });
    expect(FakeWs.last().url).toBe("ws://x/recs/ws");
    expect(phases).toEqual(["connecting"]);
    FakeWs.last().open();
    expect(phases).toEqual(["connecting", "live"]);
  });

  it("delivers rec and snapshot recommendations, ignoring hello and null snapshots", () => {
    const recs: Recommendation[] = [];
    createRecsSocket("ws://x/recs/ws", {
      onRecommendation: (r) => recs.push(r),
      wsFactory: factory,
    });
    const ws = FakeWs.last();
    ws.open();
    ws.message({ type: "hello", v: 1, server_version: "0.0.0", schema_version: "1.0.0" });
    ws.message({ type: "snapshot", v: 1, recommendation: null });
    expect(recs).toHaveLength(0);
    ws.message({ type: "snapshot", v: 1, recommendation: REC });
    ws.message({ type: "rec", v: 1, recommendation: { ...REC, as_of_overall_pick: 6 } });
    expect(recs.map((r) => r.as_of_overall_pick)).toEqual([5, 6]);
  });

  it("answers ping heartbeats with a pong", () => {
    createRecsSocket("ws://x/recs/ws", { onRecommendation: () => {}, wsFactory: factory });
    const ws = FakeWs.last();
    ws.open();
    ws.message({ type: "ping", v: 1, ts: "2026-08-30T18:04:20Z" });
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: "pong", v: 1 });
  });

  it("invokes onOpen with a send fn on every (re)connect, so a resync re-subscribes", () => {
    vi.useFakeTimers();
    try {
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onOpen: (send) => send(JSON.stringify({ type: "subscribe", v: 1 })),
        wsFactory: factory,
        backoffMs: [10],
      });
      FakeWs.last().open();
      expect(JSON.parse(FakeWs.last().sent[0]!)).toEqual({ type: "subscribe", v: 1 });
      FakeWs.last().close();
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2);
      FakeWs.last().open();
      expect(JSON.parse(FakeWs.last().sent[0]!)).toEqual({ type: "subscribe", v: 1 });
    } finally {
      vi.useRealTimers();
    }
  });

  // --- the regression-prone pair: stale gating (design divergence #1) ---

  it("never emits live-on-rec and never goes stale when staleAfterMs is absent", () => {
    vi.useFakeTimers();
    try {
      const phases: RecsSocketPhase[] = [];
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onStatus: (p) => phases.push(p),
        wsFactory: factory,
      });
      FakeWs.last().open();
      phases.length = 0; // drop connecting + live-on-open
      FakeWs.last().message({ type: "rec", v: 1, recommendation: REC });
      vi.advanceTimersByTime(60_000);
      expect(phases).toEqual([]); // exactly the dashboard's behavior: status only on open/close
    } finally {
      vi.useRealTimers();
    }
  });

  it("emits stale after the window, and a rec re-emits live AND re-arms the timer", () => {
    vi.useFakeTimers();
    try {
      const phases: RecsSocketPhase[] = [];
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onStatus: (p) => phases.push(p),
        wsFactory: factory,
        staleAfterMs: 3000,
      });
      FakeWs.last().open();
      vi.advanceTimersByTime(2000);
      phases.length = 0;
      FakeWs.last().message({ type: "rec", v: 1, recommendation: REC });
      expect(phases).toEqual(["live"]); // un-staled
      vi.advanceTimersByTime(2000);
      expect(phases).toEqual(["live"]); // re-armed from the rec, not still counting from open
      vi.advanceTimersByTime(1000);
      expect(phases).toEqual(["live", "stale"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears the stale timer while reconnecting", () => {
    vi.useFakeTimers();
    try {
      const phases: RecsSocketPhase[] = [];
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onStatus: (p) => phases.push(p),
        wsFactory: factory,
        staleAfterMs: 3000,
        backoffMs: [100_000],
      });
      FakeWs.last().open();
      FakeWs.last().close();
      phases.length = 0;
      vi.advanceTimersByTime(10_000); // well past staleAfterMs
      expect(phases).toEqual([]); // "reconnecting" already reported; no stale on a dead socket
    } finally {
      vi.useRealTimers();
    }
  });

  // --- reconnect ---

  it("emits reconnecting and opens a fresh socket after an unexpected close", () => {
    vi.useFakeTimers();
    try {
      const phases: RecsSocketPhase[] = [];
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onStatus: (p) => phases.push(p),
        wsFactory: factory,
        backoffMs: [10],
      });
      FakeWs.last().open();
      FakeWs.last().close();
      expect(phases).toEqual(["connecting", "live", "reconnecting"]);
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the socket on error, which drives the reconnect", () => {
    vi.useFakeTimers();
    try {
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        wsFactory: factory,
        backoffMs: [10],
      });
      FakeWs.last().open();
      FakeWs.last().fire("error", {});
      expect(FakeWs.last().readyState).toBe(3);
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("caps the backoff at the last entry in the schedule", () => {
    vi.useFakeTimers();
    try {
      createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        wsFactory: factory,
        backoffMs: [10, 20],
      });
      FakeWs.last().open();
      FakeWs.last().close(); // attempt 0 -> 10ms
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2);
      FakeWs.last().close(); // attempt 1 -> 20ms (no open() — attempt must not reset)
      vi.advanceTimersByTime(20);
      expect(FakeWs.instances).toHaveLength(3);
      FakeWs.last().close(); // attempt 2 -> capped at 20ms, not grown
      vi.advanceTimersByTime(19);
      expect(FakeWs.instances).toHaveLength(3);
      vi.advanceTimersByTime(1);
      expect(FakeWs.instances).toHaveLength(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it("emits closed, closes the socket, and stops reconnecting on teardown", () => {
    vi.useFakeTimers();
    try {
      const phases: RecsSocketPhase[] = [];
      const stop = createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        onStatus: (p) => phases.push(p),
        wsFactory: factory,
        backoffMs: [10],
      });
      FakeWs.last().open();
      stop();
      expect(FakeWs.last().readyState).toBe(3);
      expect(phases).toEqual(["connecting", "live", "closed"]); // no "reconnecting" from our own close
      vi.advanceTimersByTime(1000);
      expect(FakeWs.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels a pending reconnect on teardown", () => {
    vi.useFakeTimers();
    try {
      const stop = createRecsSocket("ws://x/recs/ws", {
        onRecommendation: () => {},
        wsFactory: factory,
        backoffMs: [50],
      });
      FakeWs.last().open();
      FakeWs.last().close(); // reconnect armed for 50ms
      stop();
      vi.advanceTimersByTime(1000);
      expect(FakeWs.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
```

Also add `beforeEach` to the vitest import if not already present.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pnpm --filter @jaaffl/shared test
```

Expected: FAIL — `createRecsSocket is not a function` / TS resolution errors. The existing
`parseRecsFrame` block must still pass.

- [ ] **Step 3: Implement the core**

Append to `packages/shared/src/socket.ts` (below `parseRecsFrame`):

```ts
/** The canonical connection phases. Each surface maps these to its own labels (§ design). */
export type RecsSocketPhase = "connecting" | "live" | "stale" | "reconnecting" | "closed";

/** Minimal WebSocket surface the client uses (the DOM WebSocket satisfies it; tests inject a fake). */
export interface WebSocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void;
}

export interface RecsSocketOptions {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (phase: RecsSocketPhase) => void;
  /** Runs on every (re)connect once open. `send` writes one raw frame — deliberately not the
   *  socket, so an adapter cannot race the core for the connection's lifecycle. */
  onOpen?: (send: (data: string) => void) => void;
  /** Setting this enables stale tracking: "stale" fires when no rec arrives inside the window,
   *  and an arriving rec re-emits "live". Surfaces with no stale concept omit it. */
  staleAfterMs?: number;
  /** Reconnect backoff schedule in ms (last value is the cap). */
  backoffMs?: number[];
  wsFactory?: (url: string) => WebSocketLike;
}

const DEFAULT_BACKOFF_MS = [250, 500, 1000, 2000, 5000];

/**
 * The one /recs/ws client (§8.5): hello -> snapshot -> rec, with reconnect + resync from the
 * server's snapshot (never a replayed stream). Returns a teardown function.
 *
 * On reconnect the server re-sends hello + snapshot, so a surface resynchronizes from current
 * state rather than replaying a dropped stream; back-pressure is the server's single-slot
 * latest-wins, so only the newest Recommendation is ever seen.
 */
export function createRecsSocket(url: string, opts: RecsSocketOptions): () => void {
  const wsFactory = opts.wsFactory ?? ((u) => new WebSocket(u) as unknown as WebSocketLike);
  const backoff = opts.backoffMs ?? DEFAULT_BACKOFF_MS;
  const { staleAfterMs } = opts;

  let closed = false;
  let attempt = 0;
  let ws: WebSocketLike | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;

  const emit = (phase: RecsSocketPhase): void => opts.onStatus?.(phase);

  function clearStale(): void {
    if (staleTimer) clearTimeout(staleTimer);
    staleTimer = null;
  }

  function armStale(): void {
    if (staleAfterMs === undefined) return;
    clearStale();
    staleTimer = setTimeout(() => emit("stale"), staleAfterMs);
  }

  /** A rec is the activity signal: it un-stales the connection and restarts the window. No-op
   *  for surfaces without stale tracking, which therefore report status only on open/close. */
  function markActive(): void {
    if (staleAfterMs === undefined) return;
    emit("live");
    armStale();
  }

  function connect(): void {
    if (closed) return;
    ws = wsFactory(url);
    ws.addEventListener("open", () => {
      attempt = 0;
      emit("live");
      armStale();
      opts.onOpen?.((data) => ws?.send(data));
    });
    ws.addEventListener("message", (event) => {
      const frame = parseRecsFrame(event.data);
      if (!frame) return;
      if (frame.type === "ping") {
        ws?.send(JSON.stringify({ type: "pong", v: RECS_PROTOCOL_VERSION }));
        return;
      }
      const rec =
        frame.type === "rec" || frame.type === "snapshot" ? frame.recommendation : null;
      if (!rec) return; // hello, and a snapshot with nothing published yet
      markActive();
      opts.onRecommendation(rec);
    });
    ws.addEventListener("close", scheduleReconnect);
    ws.addEventListener("error", () => ws?.close());
  }

  function scheduleReconnect(): void {
    if (closed) return;
    clearStale(); // a dead socket is "reconnecting", not "stale"
    emit("reconnecting");
    const delay = backoff[Math.min(attempt, backoff.length - 1)] ?? 0;
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  }

  emit("connecting");
  connect();

  return () => {
    closed = true; // set first: our own ws.close() below must not schedule a reconnect
    if (reconnectTimer) clearTimeout(reconnectTimer);
    clearStale();
    emit("closed");
    ws?.close();
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm --filter @jaaffl/shared test && pnpm --filter @jaaffl/shared typecheck
```

Expected: PASS — the existing `parseRecsFrame` tests plus all 11 new `createRecsSocket` tests.

- [ ] **Step 5: Commit**

```bash
git add packages/shared/src/socket.ts packages/shared/tests/socket.test.ts
git commit -m "Add shared createRecsSocket core with a canonical phase machine"
```

---

### Task 3: Web adapter

**Files:**
- Modify: `apps/web/lib/api.ts:65-153` (replace from `export type RecsSocketState` to end of file)
- Test: `apps/web/lib/api.test.ts` — **DO NOT EDIT.** It must pass unmodified.

- [ ] **Step 1: Replace the imports**

`apps/web/lib/api.ts:1-8` becomes:

```ts
import {
  createRecsSocket,
  type LeagueSettings,
  LeagueSettingsSchema,
  type Recommendation,
  type RecsSocketPhase,
  RecommendationSchema,
  RECS_PROTOCOL_VERSION,
} from "@jaaffl/shared";
```

`parseRecsFrame` is no longer imported here — the core owns frame handling now.

- [ ] **Step 2: Replace `:65-153` with the adapter**

```ts
export type RecsSocketState = "connecting" | "live" | "reconnecting" | "closed";

export interface RecsHandlers {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (state: RecsSocketState) => void;
}

/** Minimal WebSocket surface the client uses (the DOM WebSocket satisfies it; tests inject a fake). */
export type { WebSocketLike } from "@jaaffl/shared";

export interface SubscribeRecsOptions {
  url?: string;
  wsFactory?: (url: string) => WebSocketLike;
  /** Reconnect backoff schedule in ms (last value is the cap). */
  backoffMs?: number[];
}

// TODO(user): the dashboard's phase -> label map. Total Record: every phase must be answered,
// `null` = deliberately not reported. See the design doc's "Adapters" section.

/**
 * Subscribe to WS /recs/ws (§8.5), scoped to a league. Thin adapter over the shared
 * createRecsSocket: the dashboard sends a `subscribe` frame on every (re)connect and has no
 * stale concept, so it reports status on open/close only. Returns an unsubscribe function.
 */
export function subscribeRecs(
  leagueId: string,
  handlers: RecsHandlers,
  opts: SubscribeRecsOptions = {},
): () => void {
  return createRecsSocket(opts.url ?? `${WS_BASE}/recs/ws`, {
    onRecommendation: handlers.onRecommendation,
    onStatus: (phase) => {
      const label = PHASE_LABELS[phase];
      if (label) handlers.onStatus?.(label);
    },
    onOpen: (send) =>
      send(JSON.stringify({ type: "subscribe", v: RECS_PROTOCOL_VERSION, league_id: leagueId })),
    backoffMs: opts.backoffMs,
    wsFactory: opts.wsFactory,
  });
}
```

Note `WebSocketLike` is re-exported with `export type { ... } from`, required by
`verbatimModuleSyntax`. It is referenced in `SubscribeRecsOptions` above, so it must also be
imported as a type in the import block from Step 1 — add `type WebSocketLike` there.

- [ ] **Step 3: The user writes `PHASE_LABELS`**

Stop and hand off. The map is the crux of the divergence, and the user asked to write it.
Expected shape (~6 lines), replacing the TODO:

```ts
const PHASE_LABELS: Record<RecsSocketPhase, RecsSocketState | null> = { /* user */ };
```

- [ ] **Step 4: Run the web suite unmodified**

```bash
pnpm --filter @jaaffl/web test && pnpm --filter @jaaffl/web typecheck
```

Expected: PASS, same count as the Task 1 baseline. `git diff --stat apps/web/lib/api.test.ts`
must be empty.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/api.ts
git commit -m "Make the dashboard /recs/ws client a thin createRecsSocket adapter"
```

---

### Task 4: Overlay adapter

**Files:**
- Modify: `apps/extension/src/lib/recs.ts` (rewrite below the header comment)
- Test: `apps/extension/tests/recs.test.ts` — **DO NOT EDIT.** It must pass unmodified.

- [ ] **Step 1: Rewrite the module**

Keep the existing file header comment. Body becomes:

```ts
import {
  createRecsSocket,
  type Recommendation,
  type RecsSocketPhase,
  type WebSocketLike,
} from "@jaaffl/shared";

export type RecsSyncState = "connecting" | "live" | "stale" | "disconnected";

export interface RecsOverlayHandlers {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (state: RecsSyncState) => void;
}

/** Minimal WebSocket surface (the DOM WebSocket satisfies it; tests inject a fake). */
export type { WebSocketLike };

export interface SubscribeRecsOptions {
  wsFactory?: (url: string) => WebSocketLike;
  backoffMs?: number[];
  /** Mark the last rec stale if no push arrives within this window (default 3s). */
  staleAfterMs?: number;
}

// TODO(user): the overlay's phase -> label map. Total Record: every phase must be answered,
// `null` = deliberately not reported. See the design doc's "Adapters" section.

/**
 * Subscribe to WS /recs/ws (§6.2 / §8.5). Thin adapter over the shared createRecsSocket: the
 * overlay tracks staleness (a push overdue by `staleAfterMs` marks the last rec stale) and
 * sends no subscribe frame. Returns an unsubscribe function.
 */
export function subscribeRecs(
  url: string,
  handlers: RecsOverlayHandlers,
  opts: SubscribeRecsOptions = {},
): () => void {
  return createRecsSocket(url, {
    onRecommendation: handlers.onRecommendation,
    onStatus: (phase) => {
      const label = PHASE_LABELS[phase];
      if (label) handlers.onStatus?.(label);
    },
    staleAfterMs: opts.staleAfterMs ?? 3000,
    backoffMs: opts.backoffMs,
    wsFactory: opts.wsFactory,
  });
}
```

- [ ] **Step 2: The user writes `PHASE_LABELS`**

Stop and hand off. Expected shape (~6 lines), replacing the TODO:

```ts
const PHASE_LABELS: Record<RecsSocketPhase, RecsSyncState | null> = { /* user */ };
```

- [ ] **Step 3: Run the extension suite unmodified**

```bash
pnpm --filter @jaaffl/extension test && pnpm --filter @jaaffl/extension typecheck
```

Expected: PASS, same count as the Task 1 baseline. `git diff --stat apps/extension/tests/`
must be empty.

- [ ] **Step 4: Commit**

```bash
git add apps/extension/src/lib/recs.ts
git commit -m "Make the overlay /recs/ws client a thin createRecsSocket adapter"
```

---

### Task 5: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Prove the existing tests are untouched**

```bash
git diff --stat main -- apps/web/lib/api.test.ts apps/extension/tests/ apps/web/components/ apps/extension/e2e/
```

Expected: **empty output.** Any diff here invalidates the safety net — investigate before continuing.

- [ ] **Step 2: Run everything**

```bash
pnpm -r typecheck && pnpm -r test
```

Expected: PASS, per-package counts equal to Task 1's baseline plus the new shared tests.

- [ ] **Step 3: Run E4 (Playwright)**

```bash
pnpm --filter @jaaffl/extension test:e2e
```

Expected: PASS. This is the real-Chromium overlay render path; it stubs `WebSocket` with a
no-op class, which exercises the core's default `wsFactory` branch.

- [ ] **Step 4: Confirm the duplication is actually gone**

```bash
grep -rn "DEFAULT_BACKOFF\|scheduleReconnect\|addEventListener(\"open\"" apps/web/lib/api.ts apps/extension/src/lib/recs.ts
```

Expected: **no matches.** Both adapters should be free of state-machine mechanics.

- [ ] **Step 5: Commit any remaining changes**

```bash
git status --short
```

Expected: clean.

---

## Self-Review

**Spec coverage:** core signature + phase machine → Task 2; `onOpen`-takes-`send` → Task 2 Step 3;
stale gating (divergence #1) → Task 2 Steps 1/3, tested twice; `closed`-on-teardown (divergence #2)
→ Task 2 teardown test + the maps in Tasks 3/4; total-Record maps → Tasks 3/4; backoff private →
Task 2 Step 3 (`DEFAULT_BACKOFF_MS`, unexported); public exports preserved → Tasks 3/4 Step 1;
tests unchanged → the critical-constraint section + Task 5 Step 1; E4 → Task 5 Step 3.

**Placeholder scan:** the two `TODO(user)` markers are deliberate hand-off points the user
requested, each with its exact type signature and a pointer to the design section — not vague
"implement later". No other placeholders.

**Type consistency:** `RecsSocketPhase`, `WebSocketLike`, `RecsSocketOptions`, `createRecsSocket`,
`PHASE_LABELS`, `DEFAULT_BACKOFF_MS`, `markActive`, `armStale`, `clearStale`, `emit` are spelled
identically across Tasks 2–4. Adapter option names (`backoffMs`, `wsFactory`, `staleAfterMs`,
`onOpen`, `onStatus`, `onRecommendation`) match `RecsSocketOptions` exactly. `RecsSocketState`
(web) and `RecsSyncState` (overlay) keep their current spellings and members.
