/**
 * TIER 3 / TASK 2 — late-join resync from a `subscribe` snapshot, and the draft-over sentinel.
 *
 * `subscribe/response` carries a COMPLETE per-team board keyed by CBS player id
 * (`fullstate.teams.<team>.players.<playerid>` with `opick`/`round`/`pick`/`rosterpos`).
 * The protocol doc calls it "more valuable than replaying individual pick deltas, and the
 * right source for a late-join resync" — and nothing consumed it.
 *
 * That is not hypothetical. The owner's own 2026-07-25 capture began recording MID-DRAFT:
 * its delta stream covers overalls 4..168 and picks 1, 2 and 3 exist ONLY in its subscribe
 * snapshot. Replaying deltas alone leaves three drafted players unmasked and recommendable.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { DraftEventSchema } from "@jaaffl/shared";
import { describe, expect, it } from "vitest";

import { parseDraftEvents } from "../src/lib/parse";

const HERE = dirname(fileURLToPath(import.meta.url));
const CBS = join(HERE, "fixtures", "cbs");

const TEAMS = 12;
const CAPTURE_ROUNDS = 14;
const CAPTURE_PICKS = TEAMS * CAPTURE_ROUNDS; // 168

function frameBody(name: string): string {
  return (JSON.parse(readFileSync(join(CBS, name), "utf-8")) as { payload: { body: string } })
    .payload.body;
}

function replayBodies(name: string): string[] {
  return readFileSync(join(CBS, name), "utf-8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => (JSON.parse(line) as { payload: { body: string } }).payload.body);
}

/** The resync event a snapshot should produce: a draft_state carrying an explicit `picks`
 * board (which fold_state treats as an authoritative full re-sync, unlike a ticker tick). */
function resyncOf(body: string) {
  return parseDraftEvents({ via: "ws", body }).find(
    (e) => e.event_type === "draft_state" && Array.isArray(e.data["picks"]),
  );
}

describe("subscribe snapshot — the late-join resync source", () => {
  it("turns a full-board snapshot into one authoritative draft_state with every pick", () => {
    const resync = resyncOf(frameBody("subscribe-complete.json"));
    expect(resync).toBeDefined();
    const picks = resync!.data["picks"] as Array<Record<string, unknown>>;
    expect(picks).toHaveLength(CAPTURE_PICKS);
    const overalls = picks.map((p) => p["overall"]).sort((a, b) => Number(a) - Number(b));
    expect(overalls).toEqual(Array.from({ length: CAPTURE_PICKS }, (_, i) => i + 1));
  });

  it("reads CBS's own round/pick/team for each roster entry rather than deriving them", () => {
    const picks = resyncOf(frameBody("subscribe-complete.json"))!.data["picks"] as Array<
      Record<string, unknown>
    >;
    for (const pick of picks) {
      const overall = Number(pick["overall"]);
      // CBS records round/pick per roster entry; they must agree with the snake arithmetic.
      expect(pick["round"]).toBe(Math.floor((overall - 1) / TEAMS) + 1);
      expect(pick["pick_in_round"]).toBe(((overall - 1) % TEAMS) + 1);
      expect(String(pick["player_id"])).toMatch(/^cbs:\d+$/);
      expect(String(pick["team_id"])).toMatch(/^\d+$/);
    }
  });

  it("emits a schema-valid event", () => {
    const resync = resyncOf(frameBody("subscribe-complete.json"))!;
    expect(DraftEventSchema.safeParse(resync).success).toBe(true);
  });

  it("recovers exactly the picks a mid-draft join never saw as deltas", () => {
    // The real late-join capture: deltas start at overall 4.
    const deltaOveralls = new Set(
      replayBodies("late-join.deltas.jsonl")
        .flatMap((body) => parseDraftEvents({ via: "ws", body }))
        .filter((e) => e.event_type === "pick_made")
        .map((e) => e.pick_number),
    );
    expect(deltaOveralls.has(1)).toBe(false);
    expect(deltaOveralls.has(4)).toBe(true);
    expect(deltaOveralls.size).toBe(165);

    const snapshotPicks = resyncOf(frameBody("late-join.snapshot.json"))!.data["picks"] as Array<
      Record<string, unknown>
    >;
    expect(snapshotPicks.map((p) => p["overall"]).sort()).toEqual([1, 2, 3]);

    // Together they are the whole draft; neither alone is.
    const union = new Set([...deltaOveralls, ...snapshotPicks.map((p) => Number(p["overall"]))]);
    expect(union.size).toBe(CAPTURE_PICKS);
  });
});

describe("the late-join event stream, as the backend will receive it", () => {
  it("drift guard: the committed late-join artifact matches this parser's output", () => {
    // The real chronological order a client joining mid-draft sees: the subscribe snapshot
    // first, then every subsequent delta. backend/tests/test_cbs_resync.py folds this.
    // Regenerate with JAAFFL_WRITE_REPLAY=1.
    const events = [
      ...parseDraftEvents({ via: "ws", body: frameBody("late-join.snapshot.json") }),
      ...replayBodies("late-join.deltas.jsonl").flatMap((body) =>
        parseDraftEvents({ via: "ws", body }),
      ),
    ];
    const artifact = join(CBS, "late-join.events.json");
    const serialized = `${JSON.stringify(events, null, 2)}\n`;
    if (process.env["JAAFFL_WRITE_REPLAY"]) writeFileSync(artifact, serialized, "utf-8");
    expect(readFileSync(artifact, "utf-8").replace(/\r\n/g, "\n")).toBe(serialized);
  });

  it("drift guard: the committed full-board resync artifact matches this parser's output", () => {
    // A join arriving with the whole draft already on the board — one event, 168 picks.
    const events = parseDraftEvents({ via: "ws", body: frameBody("subscribe-complete.json") });
    const artifact = join(CBS, "subscribe-complete.events.json");
    const serialized = `${JSON.stringify(events, null, 2)}\n`;
    if (process.env["JAAFFL_WRITE_REPLAY"]) writeFileSync(artifact, serialized, "utf-8");
    expect(readFileSync(artifact, "utf-8").replace(/\r\n/g, "\n")).toBe(serialized);
  });
});

describe("the draft-over sentinel", () => {
  it("marks a completed draft complete without inventing a 169th pick", () => {
    const events = parseDraftEvents({ via: "ws", body: frameBody("subscribe-complete.json") });
    expect(events.some((e) => e.event_type === "draft_complete")).toBe(true);
    expect(events.some((e) => e.event_type === "pick_made")).toBe(false);
    const resync = resyncOf(frameBody("subscribe-complete.json"))!;
    const picks = resync.data["picks"] as Array<Record<string, unknown>>;
    expect(Math.max(...picks.map((p) => Number(p["overall"])))).toBe(CAPTURE_PICKS);
  });

  it("treats the overrun itself as completion, not only CBS's state word", () => {
    // rounds 14 x 12 = 168 real picks, but the terminal frame carries opick 169. The overrun
    // is the structural signal; `state: "completed"` is a second, independent one. Keying
    // completion off the state word ALONE means a frame that overruns without it is read as
    // a live draft sitting on a pick that cannot exist.
    const body = frameBody("subscribe-complete.json");
    const withoutStateWord = body.replace(/"state":"completed"/g, '"state":"picking"');
    expect(withoutStateWord).not.toBe(body); // the substitution really applied
    const events = parseDraftEvents({ via: "ws", body: withoutStateWord });
    expect(events.some((e) => e.event_type === "draft_complete")).toBe(true);
    expect(events.some((e) => e.event_type === "pick_made")).toBe(false);
  });

  it("keeps the overrun opick verbatim — it is the engine's own no-picks-left sentinel", () => {
    // Deliberately NOT clamped to 168: `opponents.next_overall_pick` already returns
    // rounds*teams + 1 to mean "you have no picks left", so 169 is the same convention.
    // Clamping to 168 would assert that pick 168 is on the clock when it has been made.
    const events = parseDraftEvents({ via: "ws", body: frameBody("subscribe-complete.json") });
    const ticker = events.find((e) => e.event_type === "draft_state");
    expect(ticker!.data["current_overall_pick"]).toBe(CAPTURE_PICKS + 1);
  });

  it("still reports a mid-draft opick verbatim (the sentinel rule must not clamp live play)", () => {
    const events = parseDraftEvents({ via: "ws", body: frameBody("late-join.snapshot.json") });
    const state = events.find((e) => e.event_type === "draft_state");
    expect(state!.data["current_overall_pick"]).toBe(4);
    expect(events.some((e) => e.event_type === "draft_complete")).toBe(false);
  });
});
