/**
 * WS /recs/ws frame contract (plan §8.5 / §8.6) — the shared, validated parser both the
 * dashboard and the overlay use so the two surfaces handle push frames identically.
 *
 * The server (backend api/recs.py + app.py) sends text-JSON frames with a `type`
 * discriminator, a protocol version `v`, and a domain payload under a named key. Both
 * consumers run every frame through `parseRecsFrame`, which validates the embedded
 * Recommendation against the shared contract — the UI never trusts an unvalidated payload.
 */
import { type Recommendation, RecommendationSchema } from "./recommendation";

export const RECS_PROTOCOL_VERSION = 1;

export interface HelloFrame {
  type: "hello";
  v: number;
  server_version: string;
  schema_version: string;
}
export interface SnapshotFrame {
  type: "snapshot";
  v: number;
  recommendation: Recommendation | null;
}
export interface RecFrame {
  type: "rec";
  v: number;
  recommendation: Recommendation;
}
export interface PingFrame {
  type: "ping";
  v: number;
  ts?: string;
}

export type RecsServerFrame = HelloFrame | SnapshotFrame | RecFrame | PingFrame;

/**
 * Safely parse a raw /recs/ws message into a typed frame, validating any embedded
 * Recommendation against RecommendationSchema. Returns null for undecodable JSON, an
 * unknown `type`, or a payload that fails contract validation.
 */
export function parseRecsFrame(data: unknown): RecsServerFrame | null {
  let frame: unknown = data;
  if (typeof data === "string") {
    try {
      frame = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (typeof frame !== "object" || frame === null) return null;
  const f = frame as Record<string, unknown>;
  const v = typeof f.v === "number" ? f.v : RECS_PROTOCOL_VERSION;

  switch (f.type) {
    case "hello":
      return {
        type: "hello",
        v,
        server_version: String(f.server_version ?? ""),
        schema_version: String(f.schema_version ?? ""),
      };
    case "ping":
      return { type: "ping", v, ...(typeof f.ts === "string" ? { ts: f.ts } : {}) };
    case "snapshot": {
      if (f.recommendation == null) return { type: "snapshot", v, recommendation: null };
      const parsed = RecommendationSchema.safeParse(f.recommendation);
      return parsed.success ? { type: "snapshot", v, recommendation: parsed.data } : null;
    }
    case "rec": {
      const parsed = RecommendationSchema.safeParse(f.recommendation);
      return parsed.success ? { type: "rec", v, recommendation: parsed.data } : null;
    }
    default:
      return null;
  }
}

/**
 * The canonical connection phases. Each surface maps these to its own labels through a total
 * record, so a phase added here forces both surfaces to decide what to call it.
 */
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
  /**
   * Runs on every (re)connect once open. Receives `send` rather than the socket, so an adapter
   * can write a frame but cannot reach close()/readyState and race the core for the lifecycle.
   */
  onOpen?: (send: (data: string) => void) => void;
  /**
   * Setting this enables stale tracking: "stale" fires when no rec arrives inside the window, and
   * an arriving rec re-emits "live". Surfaces with no stale concept omit it and therefore report
   * status on open/close only.
   */
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

  /** A rec is the activity signal: it un-stales the connection and restarts the window. */
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
      const rec = frame.type === "rec" || frame.type === "snapshot" ? frame.recommendation : null;
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
