/**
 * Overlay-side WS /recs/ws client (plan §6.2 / §8.5): subscribe to the backend push channel and
 * resynchronize from the server's hello -> snapshot -> rec on every (re)connect — never a replayed
 * stream. Reconnect with jittered backoff; mark the last rec "stale" if a push is overdue.
 *
 * Owned by the ISOLATED content script (the trust boundary), read-only to the client. Frames run
 * through the shared, validated parseRecsFrame so the overlay never renders an unvalidated payload.
 */
import { parseRecsFrame, type Recommendation, RECS_PROTOCOL_VERSION } from "@jaaffl/shared";

export type RecsSyncState = "connecting" | "live" | "stale" | "disconnected";

export interface RecsOverlayHandlers {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (state: RecsSyncState) => void;
}

/** Minimal WebSocket surface (the DOM WebSocket satisfies it; tests inject a fake). */
export interface WebSocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void;
}

export interface SubscribeRecsOptions {
  wsFactory?: (url: string) => WebSocketLike;
  backoffMs?: number[];
  /** Mark the last rec stale if no push arrives within this window (default 3s). */
  staleAfterMs?: number;
}

const DEFAULT_BACKOFF = [250, 500, 1000, 2000, 5000];

export function subscribeRecs(
  url: string,
  handlers: RecsOverlayHandlers,
  opts: SubscribeRecsOptions = {},
): () => void {
  const wsFactory = opts.wsFactory ?? ((u) => new WebSocket(u) as unknown as WebSocketLike);
  const backoff = opts.backoffMs ?? DEFAULT_BACKOFF;
  const staleAfterMs = opts.staleAfterMs ?? 3000;

  let closed = false;
  let attempt = 0;
  let ws: WebSocketLike | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;

  const setStatus = (state: RecsSyncState) => handlers.onStatus?.(state);

  function armStaleTimer(): void {
    if (staleTimer) clearTimeout(staleTimer);
    staleTimer = setTimeout(() => setStatus("stale"), staleAfterMs);
  }

  function connect(): void {
    if (closed) return;
    ws = wsFactory(url);
    ws.addEventListener("open", () => {
      attempt = 0;
      setStatus("live");
      armStaleTimer();
    });
    ws.addEventListener("message", (event) => {
      const frame = parseRecsFrame(event.data);
      if (!frame) return;
      if (frame.type === "ping") {
        ws?.send(JSON.stringify({ type: "pong", v: RECS_PROTOCOL_VERSION }));
        return;
      }
      const rec =
        frame.type === "rec"
          ? frame.recommendation
          : frame.type === "snapshot"
            ? frame.recommendation
            : null;
      if (rec) {
        setStatus("live");
        armStaleTimer();
        handlers.onRecommendation(rec);
      }
    });
    ws.addEventListener("close", scheduleReconnect);
    ws.addEventListener("error", () => ws?.close());
  }

  function scheduleReconnect(): void {
    if (closed) return;
    if (staleTimer) clearTimeout(staleTimer);
    setStatus("disconnected");
    const delay = backoff[Math.min(attempt, backoff.length - 1)] ?? 0;
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  }

  setStatus("connecting");
  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (staleTimer) clearTimeout(staleTimer);
    ws?.close();
  };
}
