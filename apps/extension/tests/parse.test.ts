/**
 * Golden-fixture parser tests (plan §5.7 / E4). The network-frame vocabulary is now the
 * REAL decoded CBS protocol (docs/research/cbs-draft-protocol.md), driven by the 7
 * redacted golden captures under fixtures/cbs/. The DOM-probe, manual-paste, and
 * settings-page shapes below remain SYNTHETIC placeholders (still TODO(capture)).
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

/** A golden CBS capture is a recorder envelope `{kind, payload: {body, seq, ts, url}}`;
 * `body` is the literal (possibly NUL-terminated) socket-frame text — the real RawSource
 * input under test. */
function cbsFrame(name: string): string {
  const outer = JSON.parse(fixture(`cbs/${name}`)) as { payload: { body: string } };
  return outer.payload.body;
}

describe("parseDraftEvents — real CBS network protocol (docs/research/cbs-draft-protocol.md)", () => {
  it("strips the NUL terminator before parsing — the raw (unstripped) frame throws", () => {
    const raw = cbsFrame("picks-completed.autopick.json");
    expect(raw.charCodeAt(raw.length - 1)).toBe(0); // sanity: fixture really is NUL-terminated
    expect(() => JSON.parse(raw)).toThrow(); // proves stripping is load-bearing, not a no-op
    const events = parseDraftEvents({ via: "ws", body: raw });
    expect(events.length).toBeGreaterThan(0);
  });

  it("skips a bare-numeral heartbeat frame without throwing", () => {
    const raw = cbsFrame("heartbeat.json");
    expect(raw.startsWith("{")).toBe(false); // sanity: really a bare numeral, not JSON
    expect(() => parseDraftEvents({ via: "ws", body: raw })).not.toThrow();
    expect(parseDraftEvents({ via: "ws", body: raw })).toEqual([]);
  });

  it("ignores an outbound pick/request frame (this client asking to draft)", () => {
    expect(parseDraftEvents({ via: "ws", body: cbsFrame("pick-request.json") })).toEqual([]);
  });

  it("ignores a keepalive frame", () => {
    expect(parseDraftEvents({ via: "ws", body: cbsFrame("keepalive.json") })).toEqual([]);
  });

  it("ignores a chat-socket auth/reply frame, whose envelope uses `event` instead of `subtype`", () => {
    expect(parseDraftEvents({ via: "ws", body: cbsFrame("auth-reply.json") })).toEqual([]);
  });

  it("reads the envelope's `event` field as a fallback for `subtype` (doc §2)", () => {
    // No golden fixture pairs `event` (vs `subtype`) with a picks/completed payload — hand-built
    // to prove the fallback is load-bearing, not just exercised on frames we already ignore.
    const body = JSON.stringify({
      type: "picks",
      event: "completed", // NOT "subtype"
      payload: {
        picks: [{ playerid: "999", teamid: "5", source: "userpick", skipped: 0 }],
        newstate: { opick: "10", round: 1, rounds: 14, onclockteamid: "6" },
      },
    });
    const pick = parseDraftEvents({ via: "ws", body }).find((e) => e.event_type === "pick_made");
    expect(pick?.data).toMatchObject({ overall: 9, team_id: "5" });
  });

  describe("picks/completed → pick_made", () => {
    // GROUND-TRUTH NOTE: the doc originally said "take the overall from newstate.opick" —
    // but newstate.opick is the FORWARD-LOOKING current/next pick (paired with
    // onclockteamid), not the pick just reported in payload.picks[]. The doc has since been
    // corrected (commit 43b386b). overall = newstate.opick - picks.length + index is
    // CONFIRMED against every pick of a full draft from the raw capture, including batched
    // frames (batch sizes 1/2/5/7/9 observed) — 168/168 matches, 0 mismatches.
    it("numbers an autopick 1 (not 2 — newstate.opick's literal, un-adjusted value)", () => {
      const events = parseDraftEvents({
        via: "ws",
        body: cbsFrame("picks-completed.autopick.json"),
      });
      const picks = events.filter((e) => e.event_type === "pick_made");
      expect(picks).toHaveLength(1);
      expect(picks[0]).toMatchObject({
        event_type: "pick_made",
        league_id: "cbs-live",
        pick_number: 1,
        source: "ws",
        data: {
          overall: 1,
          round: 1,
          pick_in_round: 1,
          team_id: "1",
          pick_source: "autopick",
          player_id: "cbs:3162723",
          cbs_player_id: "3162723",
        },
      });
      expect(picks[0]?.data["overall"]).not.toBe(2);
      DraftEventSchema.parse(picks[0]);
    });

    it("maps the terminal frame's real pick (168) — no phantom 169th pick from the opick sentinel", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("picks-completed.final.json") });
      const picks = events.filter((e) => e.event_type === "pick_made");
      expect(picks).toHaveLength(1);
      expect(picks[0]?.data).toMatchObject({
        overall: 168,
        round: 14,
        pick_in_round: 12,
        team_id: "1",
        pick_source: "userpick",
        cbs_player_id: "2741207",
      });
      expect(picks.some((p) => p.data["overall"] === 169)).toBe(false);
      DraftEventSchema.parse(picks[0]);
    });

    it("parseDraftEvent returns the first event (stub-compatible signature)", () => {
      const one = parseDraftEvent({ via: "ws", body: cbsFrame("picks-completed.autopick.json") });
      expect(one?.event_type).toBe("pick_made");
    });
  });

  describe("newstate → draft_state", () => {
    it("carries current pick / round / on-the-clock (+ on-deck) from an in-progress frame", () => {
      const events = parseDraftEvents({
        via: "ws",
        body: cbsFrame("picks-completed.autopick.json"),
      });
      const state = events.find((e) => e.event_type === "draft_state");
      expect(state?.data).toMatchObject({
        current_overall_pick: 2,
        round: 1,
        on_the_clock_team_id: "2",
        on_deck_team_id: "3",
      });
      DraftEventSchema.parse(state);
    });

    it("derives draft_state from a subscribe/response frame that carries newstate but no picks[]", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("subscribe-response.json") });
      const state = events.find((e) => e.event_type === "draft_state");
      expect(state?.data).toMatchObject({ current_overall_pick: 169, round: 15 });
      expect(events.some((e) => e.event_type === "pick_made")).toBe(false);
    });

    it("nulls on_the_clock/on_deck team ids at CBS's numeric 0 sentinel (not the string \"0\")", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("picks-completed.final.json") });
      const state = events.find((e) => e.event_type === "draft_state");
      expect(state?.data["on_the_clock_team_id"]).toBeNull();
      expect(state?.data["on_deck_team_id"]).toBeNull();
    });

    it("stamps framework-probe reads with source=framework", () => {
      const events = parseDraftEvents({
        via: "framework",
        body: cbsFrame("picks-completed.autopick.json"),
      });
      expect(events.length).toBeGreaterThan(0);
      expect(events.every((e) => e.source === "framework")).toBe(true);
    });
  });

  describe("fullstatedelta.order → draft-order event (NOT newstate.upcomingorder)", () => {
    // SUPERSEDES an earlier (wrong) spec: "a populated upcomingorder maps to the order
    // event". Confirmed against the full raw capture: newstate.upcomingorder is a ROLLING
    // multi-round lookahead window (observed entry counts across one draft: 22, 17, 8, 1,
    // 0 — never a stable one-per-team order) and MUST NOT drive draft_order, because
    // opponents.py's snake math (_my_overall_picks) uses len(draft_order) AS the team
    // count — a wrong-length order silently corrupts every "my next pick" calculation.
    // payload.fullstatedelta.order is the correct, verified source: exactly ONE distinct
    // value ("1,2,...,12") across all 40 fullstatedelta-bearing frames of a full draft.
    it("maps fullstatedelta.order to a league_settings/order event with the real (stable) order", () => {
      const events = parseDraftEvents({
        via: "ws",
        body: cbsFrame("picks-completed.autopick.json"),
      });
      const order = events.find((e) => e.event_type === "league_settings");
      expect(order?.data["draft_order"]).toEqual([
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
      ]);
      expect(order?.data["team_count"]).toBe(12);
      DraftEventSchema.parse(order);
    });

    it("is stable — the same order on the terminal frame too", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("picks-completed.final.json") });
      const order = events.find((e) => e.event_type === "league_settings");
      expect(order?.data["draft_order"]).toEqual([
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
      ]);
    });

    it("REGRESSION: a populated newstate.upcomingorder never becomes draft_order", () => {
      // Hand-built: upcomingorder present (rolling-window shape) but no fullstatedelta at
      // all. If someone re-wires the order event back onto upcomingorder, this must fail.
      const body = JSON.stringify({
        type: "picks",
        subtype: "completed",
        payload: {
          picks: [{ playerid: "1", teamid: "1", source: "userpick" }],
          newstate: { opick: "5", round: 1, rounds: 14, upcomingorder: "5,6,7" },
        },
      });
      const events = parseDraftEvents({ via: "ws", body });
      expect(events.some((e) => e.event_type === "league_settings")).toBe(false);
    });

    it("emits NO order event when fullstatedelta is absent (e.g. a subscribe/response resync)", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("subscribe-response.json") });
      expect(events.some((e) => e.event_type === "league_settings")).toBe(false);
    });

    it("length guard: a wrong-length fullstatedelta.order emits NO event (never corrupts team_count)", () => {
      const body = JSON.stringify({
        type: "picks",
        subtype: "completed",
        payload: {
          picks: [{ playerid: "1", teamid: "1", source: "userpick" }],
          newstate: { opick: "5", round: 1, rounds: 14 },
          fullstatedelta: { order: "1,2,3,4,5,6,7,8,9,10,11" }, // 11 entries, not 12
        },
      });
      const events = parseDraftEvents({ via: "ws", body });
      expect(events.some((e) => e.event_type === "league_settings")).toBe(false);
    });

    it("empty fullstatedelta.order emits NO event (A5: never a synthesized snake)", () => {
      const body = JSON.stringify({
        type: "picks",
        subtype: "completed",
        payload: {
          picks: [{ playerid: "1", teamid: "1", source: "userpick" }],
          newstate: { opick: "5", round: 1, rounds: 14 },
          fullstatedelta: { order: "" },
        },
      });
      const events = parseDraftEvents({ via: "ws", body });
      expect(events.some((e) => e.event_type === "league_settings")).toBe(false);
    });
  });

  describe("completion sentinel → draft_complete", () => {
    it("emits draft_complete when newstate.state is completed (terminal picks/completed frame)", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("picks-completed.final.json") });
      expect(events.some((e) => e.event_type === "draft_complete")).toBe(true);
    });

    it("emits draft_complete from a completed subscribe/response resync too", () => {
      const events = parseDraftEvents({ via: "ws", body: cbsFrame("subscribe-response.json") });
      expect(events.some((e) => e.event_type === "draft_complete")).toBe(true);
    });

    it("does NOT emit draft_complete for an in-progress frame", () => {
      const events = parseDraftEvents({
        via: "ws",
        body: cbsFrame("picks-completed.autopick.json"),
      });
      expect(events.some((e) => e.event_type === "draft_complete")).toBe(false);
    });
  });

  it("returns [] for non-draft/garbage frames (noisy relay, silent parser)", () => {
    expect(parseDraftEvents({ via: "ws", body: '{"type":"chat","msg":"hi"}' })).toEqual([]);
    expect(parseDraftEvents({ via: "ws", body: "not json at all" })).toEqual([]);
  });

  it("a corrupt/non-numeric newstate.opick can't crash the parser or produce a draft_state/pick", () => {
    const body = JSON.stringify({
      type: "picks",
      subtype: "completed",
      payload: {
        picks: [{ playerid: "1", teamid: "1", source: "userpick" }],
        newstate: { opick: "not-a-number", round: 1 },
      },
    });
    expect(() => parseDraftEvents({ via: "ws", body })).not.toThrow();
    const events = parseDraftEvents({ via: "ws", body });
    expect(events.some((e) => e.event_type === "draft_state")).toBe(false);
    expect(events.some((e) => e.event_type === "pick_made")).toBe(false); // no anchor for overall
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
