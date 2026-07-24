/**
 * The dashboard's typed backend client (plan §6.2): the /recs/ws subscription (hello ->
 * snapshot -> rec, reconnect + resync) and fetchLeague. WebSocket + fetch are injected/mocked
 * so the socket state machine is tested deterministically (no live backend).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "@jaaffl/shared";

import {
  fetchAnalytics,
  fetchLeague,
  fetchState,
  getRecommendation,
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
    expect(ws.url).toBe("ws://127.0.0.1:8788/recs/ws");
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

  it("returns null (never rejects) when the backend is unreachable", async () => {
    // The expected "dashboard opened before the backend is up / backend restarting" path:
    // fetch rejects. fetchLeague must resolve to null, not surface an unhandled rejection.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(fetchLeague("cbs-local")).resolves.toBeNull();
  });

  it("returns null when a 200 body is unparseable JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<<not json>>", { status: 200 })));
    await expect(fetchLeague("cbs-local")).resolves.toBeNull();
  });
});

describe("getRecommendation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reports offline (status 0) when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(getRecommendation("cbs-local")).resolves.toEqual({
      status: 0,
      recommendation: null,
    });
  });

  it("returns a null recommendation (never rejects) when a 200 body is unparseable JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<<not json>>", { status: 200 })));
    await expect(getRecommendation("cbs-local")).resolves.toEqual({
      status: 200,
      recommendation: null,
    });
  });
});

describe("fetchState", () => {
  afterEach(() => vi.unstubAllGlobals());

  const BOARD = {
    league_id: "cbs-local",
    current_overall_pick: 3,
    on_the_clock_team_id: "T3",
    my_team_id: "T1",
    complete: false,
    picks: [
      {
        overall: 1,
        round: 1,
        pick_in_round: 1,
        team_id: "T1",
        player_id: "gsis:cmc",
        name: "Christian McCaffrey",
        position: "RB",
        nfl_team: "SF",
      },
      // A name-only paste pick whose canonical id never resolved still carries its display name.
      {
        overall: 2,
        round: 1,
        pick_in_round: 2,
        team_id: "T2",
        player_id: null,
        name: "Tyreek Hill",
        position: "WR",
        nfl_team: "MIA",
      },
    ],
  };

  it("returns the parsed board on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(BOARD), { status: 200 })),
    );
    const result = await fetchState("cbs-local");
    expect(result.status).toBe(200);
    expect(result.state?.picks).toHaveLength(2);
    expect(result.state?.picks[0]?.name).toBe("Christian McCaffrey");
    expect(result.state?.picks[1]?.player_id).toBeNull();
    expect(result.state?.on_the_clock_team_id).toBe("T3");
  });

  it("reports 404 with a null state for an unknown league", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    await expect(fetchState("unknown")).resolves.toEqual({ status: 404, state: null });
  });

  it("reports offline (status 0), never rejects, when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(fetchState("cbs-local")).resolves.toEqual({ status: 0, state: null });
  });
});

describe("fetchAnalytics", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the parsed payload on 200", async () => {
    const body = {
      league_id: "L1",
      current_overall_pick: 5,
      my_next_picks: [7],
      value_curves: [],
      survival_curves: [],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body }),
    );
    const result = await fetchAnalytics("L1");
    expect(result.status).toBe(200);
    expect(result.analytics?.league_id).toBe("L1");
  });

  it("surfaces a 503 as a status with no analytics rather than throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    const result = await fetchAnalytics("L1");
    expect(result).toEqual({ status: 503, analytics: null });
  });

  it("maps an unreachable backend to status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(await fetchAnalytics("L1")).toEqual({ status: 0, analytics: null });
  });

  it("treats an unparseable 200 body as empty, not an exception", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ nope: true }) }),
    );
    expect(await fetchAnalytics("L1")).toEqual({ status: 200, analytics: null });
  });

  it("forwards candidate ids so the curves match the ranked picks on screen", async () => {
    const spy = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ nope: true }) });
    vi.stubGlobal("fetch", spy);
    await fetchAnalytics("L1", ["a", "b"]);
    expect(spy.mock.calls[0]![0]).toContain("candidates=a%2Cb");
  });

  it("omits the candidates param entirely for an empty list", async () => {
    // An empty array must behave like `undefined` — sending `candidates=` would make the backend
    // parse an empty id list instead of falling back to its own top-6 by projection.
    const spy = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ nope: true }) });
    vi.stubGlobal("fetch", spy);
    await fetchAnalytics("L1", []);
    expect(spy.mock.calls[0]![0]).not.toContain("candidates");
  });
});
