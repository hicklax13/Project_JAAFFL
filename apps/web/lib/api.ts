import {
  type LeagueSettings,
  LeagueSettingsSchema,
  parseRecsFrame,
  type Recommendation,
  RecommendationSchema,
  RECS_PROTOCOL_VERSION,
} from "@jaaffl/shared";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8787";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

/** The primary/demo league the local UI targets (matches backend Settings.jaaffl_league_id). */
export const DEFAULT_LEAGUE_ID = process.env.NEXT_PUBLIC_LEAGUE_ID ?? "cbs-local";

/** Fetch the current recommendation from the companion service (§8.3.3). */
export async function fetchRecommendation(leagueId: string): Promise<Recommendation | null> {
  return (await getRecommendation(leagueId)).recommendation;
}

export interface RecommendationResult {
  /** HTTP status so callers can distinguish 404 (unknown league) / 409 (not started) /
   * 503 (engine warming up) — the §6.6 degraded states — from a 200. 0 means the fetch threw. */
  status: number;
  recommendation: Recommendation | null;
}

/** Status-aware GET /recommendation so the dashboard can render 404/409/503 honestly (§6.6). */
export async function getRecommendation(leagueId: string): Promise<RecommendationResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/recommendation?league_id=${encodeURIComponent(leagueId)}`, {
      cache: "no-store",
    });
  } catch {
    return { status: 0, recommendation: null };
  }
  if (!res.ok) return { status: res.status, recommendation: null };
  const parsed = RecommendationSchema.safeParse(await res.json());
  return { status: 200, recommendation: parsed.success ? parsed.data : null };
}

/** Fetch the normalized, authoritative LeagueSettings for a league (§8.3.2). Null on 404. */
export async function fetchLeague(leagueId: string): Promise<LeagueSettings | null> {
  const res = await fetch(`${API_BASE}/league/${encodeURIComponent(leagueId)}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  const parsed = LeagueSettingsSchema.safeParse(await res.json());
  return parsed.success ? parsed.data : null;
}

export type RecsSocketState = "connecting" | "live" | "reconnecting" | "closed";

export interface RecsHandlers {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (state: RecsSocketState) => void;
}

/** Minimal WebSocket surface the client uses (the DOM WebSocket satisfies it; tests inject a fake). */
export interface WebSocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void;
}

export interface SubscribeRecsOptions {
  url?: string;
  wsFactory?: (url: string) => WebSocketLike;
  /** Reconnect backoff schedule in ms (last value is the cap). */
  backoffMs?: number[];
}

const DEFAULT_BACKOFF = [250, 500, 1000, 2000, 5000];

/**
 * Subscribe to WS /recs/ws (§8.5): hello -> snapshot -> rec, with reconnect + resync from the
 * server's snapshot (never a replayed stream). Returns an unsubscribe function.
 *
 * On reconnect the server re-sends hello + snapshot, so the UI resynchronizes from the current
 * state rather than replaying a dropped stream; back-pressure is the server's single-slot
 * latest-wins, so we only ever see the newest Recommendation.
 */
export function subscribeRecs(
  leagueId: string,
  handlers: RecsHandlers,
  opts: SubscribeRecsOptions = {},
): () => void {
  const url = opts.url ?? `${WS_BASE}/recs/ws`;
  const wsFactory = opts.wsFactory ?? ((u) => new WebSocket(u) as unknown as WebSocketLike);
  const backoff = opts.backoffMs ?? DEFAULT_BACKOFF;

  let closed = false;
  let attempt = 0;
  let ws: WebSocketLike | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const setStatus = (state: RecsSocketState) => handlers.onStatus?.(state);

  function connect(): void {
    if (closed) return;
    ws = wsFactory(url);
    ws.addEventListener("open", () => {
      attempt = 0;
      setStatus("live");
      ws?.send(JSON.stringify({ type: "subscribe", v: RECS_PROTOCOL_VERSION, league_id: leagueId }));
    });
    ws.addEventListener("message", (event) => {
      const frame = parseRecsFrame(event.data);
      if (!frame) return;
      if (frame.type === "ping") {
        ws?.send(JSON.stringify({ type: "pong", v: RECS_PROTOCOL_VERSION }));
      } else if (frame.type === "rec") {
        handlers.onRecommendation(frame.recommendation);
      } else if (frame.type === "snapshot" && frame.recommendation) {
        handlers.onRecommendation(frame.recommendation);
      }
    });
    ws.addEventListener("close", scheduleReconnect);
    ws.addEventListener("error", () => ws?.close());
  }

  function scheduleReconnect(): void {
    if (closed) return;
    setStatus("reconnecting");
    const delay = backoff[Math.min(attempt, backoff.length - 1)] ?? 0;
    attempt += 1;
    timer = setTimeout(connect, delay);
  }

  setStatus("connecting");
  connect();

  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    setStatus("closed");
    ws?.close();
  };
}
