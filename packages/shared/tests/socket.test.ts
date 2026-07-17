/** WS /recs/ws frame parser (plan §8.5). Validates the exact frames api/recs.py + app.py emit. */
import { describe, expect, it } from "vitest";

import type { Recommendation } from "../src/recommendation";
import { parseRecsFrame } from "../src/socket";

const REC: Recommendation = {
  league_id: "cbs-local",
  as_of_overall_pick: 5,
  ranked: [{ player_id: "p1", score: 42.1 }],
  reasoning: "R1P5 · κ=0.6",
};

describe("parseRecsFrame", () => {
  it("parses a hello frame", () => {
    const f = parseRecsFrame(
      JSON.stringify({ type: "hello", v: 1, server_version: "0.0.0", schema_version: "1.0.0" }),
    );
    expect(f).toEqual({ type: "hello", v: 1, server_version: "0.0.0", schema_version: "1.0.0" });
  });

  it("parses a rec frame and validates the embedded Recommendation", () => {
    const f = parseRecsFrame(JSON.stringify({ type: "rec", v: 1, recommendation: REC }));
    expect(f?.type).toBe("rec");
    if (f?.type === "rec") expect(f.recommendation.as_of_overall_pick).toBe(5);
  });

  it("parses a snapshot frame carrying a null recommendation (nothing published yet)", () => {
    const f = parseRecsFrame(JSON.stringify({ type: "snapshot", v: 1, recommendation: null }));
    expect(f).toEqual({ type: "snapshot", v: 1, recommendation: null });
  });

  it("parses a ping heartbeat", () => {
    const f = parseRecsFrame(JSON.stringify({ type: "ping", v: 1, ts: "2026-08-30T18:04:20Z" }));
    expect(f?.type).toBe("ping");
  });

  it("accepts an already-parsed object as well as a JSON string", () => {
    const f = parseRecsFrame({ type: "rec", v: 1, recommendation: REC });
    expect(f?.type).toBe("rec");
  });

  it("returns null for undecodable JSON", () => {
    expect(parseRecsFrame("{not json")).toBeNull();
  });

  it("returns null for an unknown frame type", () => {
    expect(parseRecsFrame(JSON.stringify({ type: "bogus", v: 1 }))).toBeNull();
  });

  it("returns null when a rec frame's recommendation fails contract validation", () => {
    const bad = { type: "rec", v: 1, recommendation: { league_id: "x" } }; // missing as_of_overall_pick
    expect(parseRecsFrame(JSON.stringify(bad))).toBeNull();
  });
});
