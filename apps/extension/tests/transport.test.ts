/**
 * DraftSocket (plan §5.6): content-script-owned localhost WS with heartbeat/reconnect;
 * REST mirror while the socket is down (backend pick_number de-dup absorbs overlap).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftEvent } from "@jaaffl/shared";

import { DraftSocket } from "../src/lib/transport";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

function event(overall: number): DraftEvent {
  return {
    event_type: "pick_made",
    league_id: "L1",
    pick_number: overall,
    source: "ws",
    data: { overall, round: 1, pick_in_round: overall, team_id: "T1" },
  };
}

describe("DraftSocket", () => {
  let rest: DraftEvent[];

  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    rest = [];
  });
  afterEach(() => vi.useRealTimers());

  function makeSocket(): DraftSocket {
    return new DraftSocket({
      makeSocket: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      rest: async (e) => {
        rest.push(e);
      },
    });
  }

  it("queues while closed, mirrors over REST, and flushes on open", () => {
    const socket = makeSocket();
    socket.send(event(1));
    expect(rest).toHaveLength(1); // fail-soft mirror
    const ws = FakeWebSocket.instances[0]!;
    expect(ws.sent).toHaveLength(0);
    ws.open();
    expect(ws.sent).toHaveLength(1); // queued event flushed over WS
    expect(JSON.parse(ws.sent[0]!).pick_number).toBe(1);
  });

  it("sends directly once open (no REST mirror)", () => {
    const socket = makeSocket();
    FakeWebSocket.instances[0]!.open();
    socket.send(event(2));
    expect(rest).toHaveLength(0);
    expect(FakeWebSocket.instances[0]!.sent).toHaveLength(1);
  });

  it("emits {control:'ping'} heartbeats and reconnects after missed liveness", () => {
    makeSocket();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();
    vi.advanceTimersByTime(15_000);
    expect(ws.sent.some((s) => JSON.parse(s).control === "ping")).toBe(true);
    // liveness reply arrives -> stays connected
    ws.onmessage?.({ data: '{"control":"pong"}' });
    vi.advanceTimersByTime(15_000);
    expect(ws.readyState).toBe(FakeWebSocket.OPEN);
    // no reply this cycle -> socket force-closed -> reconnect scheduled
    vi.advanceTimersByTime(15_000);
    expect(ws.readyState).toBe(3);
    vi.advanceTimersByTime(5_000);
    expect(FakeWebSocket.instances.length).toBeGreaterThan(1);
  });

  it("reconnects with capped backoff after close", () => {
    makeSocket();
    const first = FakeWebSocket.instances[0]!;
    first.open();
    first.close();
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
