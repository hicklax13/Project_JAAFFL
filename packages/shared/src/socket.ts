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
