import {
  createRecsSocket,
  type DraftAnalytics,
  DraftAnalyticsSchema,
  type DraftBoardState,
  DraftBoardStateSchema,
  type LeagueSettings,
  LeagueSettingsSchema,
  type Recommendation,
  RecommendationSchema,
  type RecsSocketPhase,
  RECS_PROTOCOL_VERSION,
  type WebSocketLike,
} from "@jaaffl/shared";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8788";
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
  try {
    const parsed = RecommendationSchema.safeParse(await res.json());
    return { status: 200, recommendation: parsed.success ? parsed.data : null };
  } catch {
    return { status: 200, recommendation: null }; // 200 but an unparseable body → no rec, not a throw
  }
}

/**
 * Fetch the normalized, authoritative LeagueSettings for a league (§8.3.2). Null on 404,
 * an unparseable body, OR an unreachable backend — the dashboard opens before `make backend-dev`
 * and survives restarts, so a rejected fetch must degrade to null, never an unhandled rejection.
 */
export async function fetchLeague(leagueId: string): Promise<LeagueSettings | null> {
  try {
    const res = await fetch(`${API_BASE}/league/${encodeURIComponent(leagueId)}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const parsed = LeagueSettingsSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export interface StateResult {
  /** HTTP status so the board can distinguish 404 (unknown) / 409 (not started) from a 200.
   * 0 means the fetch threw (backend down) — the board degrades to empty, never a rejection. */
  status: number;
  state: DraftBoardState | null;
}

/**
 * Status-aware GET /state (§8.3.x): the folded board + pick-log with drafted-player names. Mirrors
 * getRecommendation's honesty contract — 404/409 surface as a status with a null state, an
 * unreachable backend as status 0 — so the board renders the §6.6 degraded states rather than
 * throwing. Re-fetched on each /recs/ws push (a new pick changes the board).
 */
export async function fetchState(leagueId: string): Promise<StateResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/state?league_id=${encodeURIComponent(leagueId)}`, {
      cache: "no-store",
    });
  } catch {
    return { status: 0, state: null };
  }
  if (!res.ok) return { status: res.status, state: null };
  try {
    const parsed = DraftBoardStateSchema.safeParse(await res.json());
    return { status: 200, state: parsed.success ? parsed.data : null };
  } catch {
    return { status: 200, state: null }; // 200 but an unparseable body → empty board, not a throw
  }
}

export interface AnalyticsResult {
  /** HTTP status so panels can distinguish 404 / 409 / 503 (engine warming) from a 200.
   * 0 means the fetch threw (backend down) — panels keep their last series, never throw. */
  status: number;
  analytics: DraftAnalytics | null;
}

/**
 * Status-aware GET /analytics: the value + survival series for the war-room panels. Mirrors
 * fetchState's honesty contract. `candidates` are the ids already on screen from the WS push, so
 * the survival lines always match the ranked picks rendered above them.
 */
export async function fetchAnalytics(
  leagueId: string,
  candidates?: readonly string[],
): Promise<AnalyticsResult> {
  const params = new URLSearchParams({ league_id: leagueId });
  if (candidates && candidates.length > 0) params.set("candidates", candidates.join(","));
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/analytics?${params.toString()}`, { cache: "no-store" });
  } catch {
    return { status: 0, analytics: null };
  }
  if (!res.ok) return { status: res.status, analytics: null };
  try {
    const parsed = DraftAnalyticsSchema.safeParse(await res.json());
    return { status: 200, analytics: parsed.success ? parsed.data : null };
  } catch {
    return { status: 200, analytics: null }; // 200 but an unparseable body → no series, not a throw
  }
}

export type RecsSocketState = "connecting" | "live" | "reconnecting" | "closed";

export interface RecsHandlers {
  onRecommendation: (rec: Recommendation) => void;
  onStatus?: (state: RecsSocketState) => void;
}

/** Minimal WebSocket surface the client uses (the DOM WebSocket satisfies it; tests inject a fake). */
export type { WebSocketLike };

export interface SubscribeRecsOptions {
  url?: string;
  wsFactory?: (url: string) => WebSocketLike;
  /** Reconnect backoff schedule in ms (last value is the cap). */
  backoffMs?: number[];
}

/**
 * The dashboard's phase -> label map (total: every phase answered; `null` = not reported).
 * `stale` is unreachable here — the dashboard passes no staleAfterMs — so it maps to null; the
 * other four are the labels the dashboard has always emitted.
 */
const PHASE_LABELS: Record<RecsSocketPhase, RecsSocketState | null> = {
  connecting: "connecting",
  live: "live",
  stale: null,
  reconnecting: "reconnecting",
  closed: "closed",
};

/**
 * Subscribe to WS /recs/ws (§8.5), scoped to a league — a thin adapter over the shared
 * createRecsSocket. The dashboard re-sends its `subscribe` frame on every (re)connect (the server
 * answers with hello + snapshot, so the UI resynchronizes from current state rather than replaying
 * a dropped stream) and enables no stale tracking. Returns an unsubscribe function.
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
