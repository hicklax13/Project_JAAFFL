# Shared `createRecsSocket` core — design

**Date:** 2026-07-17 · **Status:** approved · **Scope:** refactor, behavior-preserving

Flagged by the Phase-5 `/simplify` pass (reuse + altitude agents) and deferred to avoid churning
tested state machines right before the Stage-6 merge.

## Problem

`apps/web/lib/api.ts` and `apps/extension/src/lib/recs.ts` each carry ~90 near-identical lines of
`/recs/ws` client: the same `WebSocketLike` interface, the same `[250,500,1000,2000,5000]` backoff,
the same connect / `scheduleReconnect` / ping→pong / rec+snapshot→`onRecommendation` /
error→close cleanup. Two copies of one state machine drift.

## Verified divergences

Read line-by-line from both files (not from the `/simplify` summary, which missed the last two):

| Event | Web (`api.ts`) | Overlay (`recs.ts`) |
| --- | --- | --- |
| first arg | `leagueId`; url from `opts.url ?? WS_BASE + /recs/ws` | `url` positional |
| on open | `attempt=0`; status `live`; **sends subscribe frame** | `attempt=0`; status `live`; **arms stale timer** |
| on rec/snapshot | `onRecommendation(rec)` | **status `live`**; **re-arms stale**; `onRecommendation(rec)` |
| on ping | send pong | send pong |
| on close | status `reconnecting` | **clears stale**; status `disconnected` |
| on error | `ws.close()` | `ws.close()` |
| on unsubscribe | clear timer; **status `closed`**; `ws.close()` | clear both timers; **no status**; `ws.close()` |

Two divergences are load-bearing and easy to erase by accident:

1. **The overlay re-emits `live` on every rec; the web never does.** `use-recs.ts` reducer returns
   `{...state, socket}` — a fresh object per dispatch, so an unconditional `live`-on-rec would cost
   the dashboard a second full re-render per push. Both existing tests use `toContain("live")`, so
   the regression would be **silent**.
2. **The web emits a terminal `closed` on unsubscribe; the overlay emits nothing.**

## Design

### Core — `packages/shared/src/socket.ts`

Joins `parseRecsFrame` + `RECS_PROTOCOL_VERSION`, which the module already owns.

```ts
export type RecsSocketPhase = "connecting" | "live" | "stale" | "reconnecting" | "closed";
export interface WebSocketLike { /* hoisted; was declared identically in both surfaces */ }

export function createRecsSocket(url: string, opts: {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (phase: RecsSocketPhase) => void;
  onOpen?: (send: (data: string) => void) => void;  // per (re)connect, once open
  staleAfterMs?: number;   // presence enables stale tracking
  backoffMs?: number[];
  wsFactory?: (url: string) => WebSocketLike;
}): () => void
```

One canonical phase machine:

- `emit("connecting")` → `connect()`
- **open** → `attempt=0`; `emit("live")`; `armStale()`; `onOpen(send)`
- **message** → `parseRecsFrame`; `ping` → pong+return; `rec`/`snapshot` with a rec →
  `markActive()`; `onRecommendation(rec)`. `hello` and null-snapshot fall through.
- **close** → `scheduleReconnect()`: `clearStale()`; `emit("reconnecting")`; backoff; `setTimeout(connect)`
- **error** → `ws.close()` (falls into close)
- **teardown** → `closed=true`; clear both timers; `emit("closed")`; `ws.close()`

`armStale()` and `markActive()` return early when `staleAfterMs` is undefined. `markActive()` is
`emit("live") + armStale()` — **a rec is the activity signal that un-stales the connection**, so
divergence #1 is gated on the one option that owns that feature. The web passes no `staleAfterMs`
and is therefore byte-identical to today.

`onOpen` receives `send`, not the socket: an adapter can write a frame but cannot reach
`close()`/`readyState` and race the core's lifecycle.

The backoff array stays module-private (`export *` in `index.ts` would otherwise make it API).

### Adapters (~15 lines each)

Each keeps its exact current public exports — `RecsSocketState`/`RecsSyncState`,
`RecsHandlers`/`RecsOverlayHandlers`, `SubscribeRecsOptions`, and `WebSocketLike` re-exported from
shared (`export type {...}`, required by `verbatimModuleSyntax`). Consumers `use-recs.ts`,
`league-panels.tsx`, `overlay.ts`, `dashboard.test.tsx` are untouched.

Each owns a **total** phase→label map — `Record<RecsSocketPhase, TLabel | null>`, `null` meaning
deliberate suppression:

- **web**: `stale: null` (no stale concept); `reconnecting → "reconnecting"`; `closed → "closed"`
- **overlay**: `closed: null` (teardown is deliberate — stop reporting, don't paint a final state);
  `reconnecting → "disconnected"`; `stale → "stale"`

Total over `Partial` costs one line per surface and buys the compile-time gate: a phase added to the
core **cannot** be silently dropped by a surface that forgot it. That gate is most of the point of
hoisting the core.

## Testing

- New direct unit tests in `packages/shared/tests/socket.test.ts` (joins the `parseRecsFrame`
  tests) for the phase machine: phase order, `onOpen` send, ping→pong, null-snapshot ignored,
  backoff cap, no-reconnect-after-teardown, and — the regression-prone pair — **`stale` gating**
  (no `live`-on-rec and no stale timer when `staleAfterMs` is absent) and `closed` on teardown.
- Unchanged and must stay green: `apps/web/lib/api.test.ts`, `apps/extension/tests/recs.test.ts`,
  `apps/extension/tests/overlay.test.ts`, `apps/web/components/dashboard.test.tsx`,
  E4 `apps/extension/e2e/overlay.spec.ts`, and `pnpm -r typecheck`.

The existing suites are the safety net: they assert each surface's labels through its adapter, so
they fail if a map is wrong. The new shared tests cover what the adapters can't reach — the gating
semantics that neither surface's tests pin down.

## Non-goals

Changing any surface's labels, the wire protocol, or `parseRecsFrame`. No new deps.
