/**
 * The dashboard's typed backend client (plan §6.2): the /recs/ws subscription (hello ->
 * snapshot -> rec, reconnect + resync) and fetchLeague. WebSocket + fetch are injected/mocked
 * so the socket state machine is tested deterministically (no live backend).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "@jaaffl/shared";

import {
  fetchLeague,
  type RecsSocketState,
  subscribeRecs,
  type WebSocketLike,
} from "./api";

const REC: Recommendation = {
  league_id: "cbs-local",
  as_of_overall_pick: 5,
  ranked: [{ player_id: "p1", score: 42.1 }],
  reasoning: "R1P5 · κ=0.6",
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
  static reset(): void {
    FakeWs.instances = [];
  }
}

const factory = (url: string): WebSocketLike => new FakeWs(url);

beforeEach(() => FakeWs.reset());

describe("subscribeRecs", () => {
  it("connects to /recs/ws, reports live on open, and scopes the subscription to the league", () => {
    const states: RecsSocketState[] = [];
    subscribeRecs(
      "cbs-local",
      { onRecommendation: () => {}, onStatus: (s) => states.push(s) },
      { wsFactory: factory },
    );
    const ws = FakeWs.last();
    expect(ws.url).toBe("ws://127.0.0.1:8787/recs/ws");
    expect(states).toContain("connecting");
    ws.open();
    expect(states).toContain("live");
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: "subscribe", v: 1, league_id: "cbs-local" });
  });

  it("delivers snapshot and rec recommendations, ignoring hello and null snapshots", () => {
    const recs: Recommendation[] = [];
    subscribeRecs("cbs-local", { onRecommendation: (r) => recs.push(r) }, { wsFactory: factory });
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
    subscribeRecs("cbs-local", { onRecommendation: () => {} }, { wsFactory: factory });
    const ws = FakeWs.last();
    ws.open();
    ws.sent.length = 0; // drop the subscribe frame
    ws.message({ type: "ping", v: 1, ts: "2026-08-30T18:04:20Z" });
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: "pong", v: 1 });
  });

  it("reconnects after an unexpected close and resyncs (a new socket is opened)", () => {
    vi.useFakeTimers();
    try {
      const states: RecsSocketState[] = [];
      subscribeRecs(
        "cbs-local",
        { onRecommendation: () => {}, onStatus: (s) => states.push(s) },
        { wsFactory: factory, backoffMs: [10] },
      );
      const first = FakeWs.last();
      first.open();
      first.close(); // server dropped us
      expect(states).toContain("reconnecting");
      vi.advanceTimersByTime(10);
      expect(FakeWs.instances).toHaveLength(2); // a fresh socket resyncs from snapshot
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops reconnecting once unsubscribed", () => {
    vi.useFakeTimers();
    try {
      const unsub = subscribeRecs(
        "cbs-local",
        { onRecommendation: () => {} },
        { wsFactory: factory, backoffMs: [10] },
      );
      const ws = FakeWs.last();
      ws.open();
      unsub();
      expect(ws.readyState).toBe(3); // closed
      vi.advanceTimersByTime(100);
      expect(FakeWs.instances).toHaveLength(1); // no reconnect after unsubscribe
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("fetchLeague", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the parsed LeagueSettings on 200", async () => {
    const settings = {
      league_id: "cbs-local",
      team_count: 12,
      draft_type: "snake",
      roster_slots: [{ slot: "QB", eligible_positions: ["QB"], count: 1, starting: true }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(settings), { status: 200 })),
    );
    const result = await fetchLeague("cbs-local");
    expect(result?.team_count).toBe(12);
    expect(result?.draft_type).toBe("snake");
  });

  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    expect(await fetchLeague("unknown")).toBeNull();
  });
});
