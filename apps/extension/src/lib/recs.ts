/**
 * Overlay-side WS /recs/ws adapter (plan §6.2 / §8.5). A thin surface over the shared
 * createRecsSocket: it maps the core's phases to the overlay's labels and enables stale marking.
 * The core owns the state machine — resync from the server's hello -> snapshot -> rec on every
 * (re)connect (never a replayed stream), capped-backoff reconnect, and validated frame parsing.
 *
 * Owned by the ISOLATED content script (the trust boundary), read-only to the client; the shared
 * parser means the overlay never renders an unvalidated payload.
 */
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

/**
 * The overlay's phase -> label map (total: every phase answered; `null` = not reported). The
 * overlay renames `reconnecting` to "disconnected" and reports nothing on teardown (`closed` ->
 * null), matching what it has always emitted; the other three pass straight through.
 */
const PHASE_LABELS: Record<RecsSocketPhase, RecsSyncState | null> = {
  connecting: "connecting",
  live: "live",
  stale: "stale",
  reconnecting: "disconnected",
  closed: null,
};

/**
 * Subscribe to WS /recs/ws (§6.2 / §8.5) — a thin adapter over the shared createRecsSocket. The
 * overlay resynchronizes from the server's hello -> snapshot -> rec on every (re)connect, sends no
 * subscribe frame, and marks the last rec stale when a push is overdue. Returns an unsubscribe
 * function.
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
