/**
 * WS /recs/ws (plan §8.5): the frame parser validates the exact frames api/recs.py + app.py emit,
 * and createRecsSocket is the one client state machine both surfaces adapt. WebSocket is injected
 * so the phase machine is tested deterministically (no live backend).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "../src/recommendation";
import {
  createRecsSocket,
  parseRecsFrame,
  type RecsSocketPhase,
  type WebSocketLike,
} from "../src/socket";

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

  // --- stale tracking is opt-in, and it owns the live-on-rec re-emit ---

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
      expect(phases).toEqual([]); // exactly the dashboard's behavior: status on open/close only
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
      expect(phases).toEqual(["connecting", "live", "closed"]); // our own close is not a reconnect
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
