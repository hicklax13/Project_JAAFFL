/**
 * Overlay /recs/ws client (plan §8.5): resync from hello->snapshot->rec, reconnect with backoff,
 * and mark the last rec stale when a push is overdue. WebSocket is injected so the state machine
 * is tested deterministically (no live backend).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "@jaaffl/shared";

import { type RecsSyncState, subscribeRecs, type WebSocketLike } from "../src/lib/recs";

const REC: Recommendation = {
  league_id: "cbs-local",
  as_of_overall_pick: 5,
  ranked: [{ player_id: "p1", score: 42.1 }],
};

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

beforeEach(() => {
  FakeWs.instances = [];
});

describe("overlay subscribeRecs", () => {
  it("reports connecting then live and resyncs a snapshot + rec (ignoring null + hello)", () => {
    const states: RecsSyncState[] = [];
    const recs: Recommendation[] = [];
    subscribeRecs(
      "ws://127.0.0.1:8788/recs/ws",
      { onRecommendation: (r) => recs.push(r), onStatus: (s) => states.push(s) },
      { wsFactory: factory, staleAfterMs: 100000 },
    );
    const ws = FakeWs.last();
    expect(states[0]).toBe("connecting");
    ws.open();
    expect(states).toContain("live");
    ws.message({ type: "hello", v: 1, server_version: "0.0.0", schema_version: "1.0.0" });
    ws.message({ type: "snapshot", v: 1, recommendation: null });
    expect(recs).toHaveLength(0);
    ws.message({ type: "snapshot", v: 1, recommendation: REC });
    ws.message({ type: "rec", v: 1, recommendation: { ...REC, as_of_overall_pick: 6 } });
    expect(recs.map((r) => r.as_of_overall_pick)).toEqual([5, 6]);
  });

  it("answers ping with pong", () => {
    subscribeRecs(
      "ws://x/recs/ws",
      { onRecommendation: () => {} },
      { wsFactory: factory, staleAfterMs: 100000 },
    );
    const ws = FakeWs.last();
    ws.open();
    ws.sent.length = 0;
    ws.message({ type: "ping", v: 1 });
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: "pong", v: 1 });
  });

  it("marks the last rec stale when a push is overdue", () => {
    vi.useFakeTimers();
    try {
      const states: RecsSyncState[] = [];
      subscribeRecs(
        "ws://x/recs/ws",
        { onRecommendation: () => {}, onStatus: (s) => states.push(s) },
        { wsFactory: factory, staleAfterMs: 3000 },
      );
      FakeWs.last().open();
      vi.advanceTimersByTime(3000);
      expect(states).toContain("stale");
    } finally {
      vi.useRealTimers();
    }
  });

  it("reconnects after a drop (disconnected -> new socket) and stops once unsubscribed", () => {
    vi.useFakeTimers();
    try {
      const states: RecsSyncState[] = [];
      const unsub = subscribeRecs(
        "ws://x/recs/ws",
        { onRecommendation: () => {}, onStatus: (s) => states.push(s) },
        { wsFactory: factory, backoffMs: [10], staleAfterMs: 100000 },
      );
      FakeWs.last().open();
      FakeWs.last().close();
      expect(states).toContain("disconnected");
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2);
      unsub();
      vi.advanceTimersByTime(1000);
      expect(FakeWs.instances).toHaveLength(2); // no reconnect after unsubscribe
    } finally {
      vi.useRealTimers();
    }
  });
});
