/**
 * Golden-fixture parser tests (plan §5.7 / E4). Fixtures are SYNTHETIC until the
 * record-mode mock-draft session captures real CBS frames (TODO(capture)); the shapes
 * asserted here are the contract the real-frame field mapping must land on.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { DraftEventSchema, LeagueSettingsSchema } from "@jaaffl/shared";

import {
  parseDraftEvent,
  parseDraftEvents,
  parseLeagueSettings,
  parsePastedResults,
} from "../src/lib/parse";

const HERE = dirname(fileURLToPath(import.meta.url));

function fixture(name: string): string {
  return readFileSync(join(HERE, "fixtures", name), "utf-8");
}

function dom(html: string): Document {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  return parsed;
}

describe("parseDraftEvents — network/fiber frames", () => {
  it("normalizes a synthetic ws pick frame to the expected DraftEvent", () => {
    const events = parseDraftEvents({ via: "ws", body: fixture("pick-made.ws.json") });
    expect(events).toEqual([JSON.parse(fixture("pick-made.expected.json"))]);
    for (const ev of events) DraftEventSchema.parse(ev); // schema-parity armor
  });

  it("parseDraftEvent returns the first event (stub-compatible signature)", () => {
    const one = parseDraftEvent({ via: "ws", body: fixture("pick-made.ws.json") });
    expect(one?.event_type).toBe("pick_made");
  });

  it("normalizes a draft_state frame to a resync event plus a board-read order event", () => {
    const events = parseDraftEvents({ via: "fetch", body: fixture("draft-state.fetch.json") });
    expect(events).toEqual(JSON.parse(fixture("draft-state.expected.json")));
    for (const ev of events) DraftEventSchema.parse(ev);
  });

  it("stamps framework-probe events with source=framework", () => {
    const events = parseDraftEvents({
      via: "framework",
      body: fixture("draft-state.fetch.json"),
    });
    expect(events.every((e) => e.source === "framework")).toBe(true);
  });

  it("returns [] for non-draft frames (noisy relay, silent parser)", () => {
    expect(parseDraftEvents({ via: "ws", body: '{"type":"chat","msg":"hi"}' })).toEqual([]);
    expect(parseDraftEvents({ via: "ws", body: "not json at all" })).toEqual([]);
  });

  it("drops non-positive-overall rows from a draft_state so one bad row can't reject the resync", () => {
    const body = JSON.stringify({
      type: "draft_state",
      leagueId: "L1",
      currentPick: 3,
      picks: [
        { overall: 0, teamId: "T?" }, // corrupt row — must be dropped, not kept as {overall:0}
        { overall: -1, teamId: "T?" },
        { overall: "", teamId: "T?" },
        { overall: 2, round: 1, pickInRound: 2, teamId: "T3" },
      ],
    });
    const [state] = parseDraftEvents({ via: "fetch", body });
    const picks = (state!.data["picks"] as Array<{ overall: number }>).map((p) => p.overall);
    expect(picks).toEqual([2]);
    DraftEventSchema.parse(state); // and the survivor still validates
  });
});

describe("parseLeagueSettings — full scoring map", () => {
  it("normalizes synthetic CBS settings incl. DST dual tiers + K 50+ bonus", () => {
    const settings = parseLeagueSettings({
      via: "ws",
      body: fixture("league-settings.cbs.json"),
    });
    expect(settings).toEqual(JSON.parse(fixture("league-settings.expected.json")));
    LeagueSettingsSchema.parse(settings);
  });

  it("asserts the flex is WR-or-RB only", () => {
    const settings = parseLeagueSettings({
      via: "ws",
      body: fixture("league-settings.cbs.json"),
    });
    const flex = settings?.roster_slots.find((s) => s.slot === "WR/RB");
    expect(flex?.eligible_positions).toEqual(["WR", "RB"]);
  });
});

describe("parseDraftEvents — DOM probe (board fixture)", () => {
  it("reads picks AND the draft order from the board — never inferred", () => {
    const doc = dom(fixture("draft-board.html"));
    const events = parseDraftEvents({ via: "dom", root: doc });
    const expected = JSON.parse(fixture("draft-order.expected.json"));

    const picks = events.filter((e) => e.event_type === "pick_made");
    expect(picks.map((p) => p.pick_number)).toEqual(expected.picks_overall);
    expect(picks.every((p) => p.source === "dom")).toBe(true);

    const settings = events.find((e) => e.event_type === "league_settings");
    expect(settings?.data["draft_order"]).toEqual(expected.draft_order);
    expect(settings?.data["team_count"]).toBe(expected.team_count);
    for (const ev of events) DraftEventSchema.parse(ev);
  });

  it("emits NO order event when the board order is unreadable (A5: no synthesized snake)", () => {
    const doc = dom(fixture("draft-board.html"));
    doc.querySelector(".draft-order")?.remove();
    const events = parseDraftEvents({ via: "dom", root: doc });
    const settings = events.find((e) => e.event_type === "league_settings");
    expect(settings).toBeUndefined();
    // picks still parse — order simply stays unknown (backend keeps draft_order null)
    expect(events.filter((e) => e.event_type === "pick_made").length).toBeGreaterThan(0);
  });
});

describe("parsePastedResults — manual fallback", () => {
  it("parses a pasted results block (order line + numbered picks) to golden events", () => {
    const events = parsePastedResults(fixture("results-paste.txt"));
    expect(events).toEqual(JSON.parse(fixture("results-paste.expected.json")));
    for (const ev of events) DraftEventSchema.parse(ev);
  });

  it("computes round/pick_in_round arithmetically from the immutable 12-team size", () => {
    const [pick] = parsePastedResults("25) Team Twelve — Saquon Barkley, RB, PHI");
    expect(pick?.data).toMatchObject({ overall: 25, round: 3, pick_in_round: 1 });
  });

  it("ignores garbage lines instead of throwing", () => {
    expect(parsePastedResults("hello\nworld\n")).toEqual([]);
  });

  it("splits on the LAST dash so a hyphenated team name survives", () => {
    const [pick] = parsePastedResults("3. Steel-Curtain Squad - Justin Jefferson, WR, MIN");
    expect(pick?.data).toMatchObject({
      team_id: "Steel-Curtain Squad",
      player_name: "Justin Jefferson",
      position: "WR",
      player_team: "MIN",
    });
  });
});
