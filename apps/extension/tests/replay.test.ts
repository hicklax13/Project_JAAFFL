/**
 * TIER 3 / TASK 1 — the full replay harness (plan §5.11 A2).
 *
 * Every other parser test feeds `parse.ts` ONE hand-picked frame. This one replays an
 * ENTIRE real draft — every `picks/completed` frame of a complete 12-team, 14-round CBS
 * mock, in capture order, as the literal NUL-terminated bytes the socket delivered — and
 * asserts on the DATA that falls out the far end.
 *
 * It also emits `fixtures/cbs/full-draft.events.json`: the exact `DraftEvent[]` this
 * parser produces, which `backend/tests/test_cbs_replay.py` then drives through
 * fold_state -> resolve_pick_ids -> recommend(). That artifact is COMMITTED and
 * drift-guarded here (same idiom as overlay-tokens.test.ts / the E5 parity gate), so the
 * Python half can never silently replay a stale copy of parse.ts's output.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { DraftEventSchema } from "@jaaffl/shared";
import { describe, expect, it } from "vitest";

import { parseDraftEvents } from "../src/lib/parse";

const HERE = dirname(fileURLToPath(import.meta.url));
const CBS = join(HERE, "fixtures", "cbs");

/** League geometry, from config/league.json (12 teams) and the capture (14 rounds). The
 * capture is a 14-round mock; JAAFFL itself is 17. Rounds are READ from the frames. */
const TEAMS = 12;
const CAPTURE_ROUNDS = 14;
const CAPTURE_PICKS = TEAMS * CAPTURE_ROUNDS; // 168

/** One recorder envelope per line: {kind, payload:{body, seq, ts, url}}. `body` is the
 * literal socket-frame text, NUL terminator and all. */
function replayBodies(name: string): string[] {
  const text = readFileSync(join(CBS, name), "utf-8");
  return text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => (JSON.parse(line) as { payload: { body: string } }).payload.body);
}

describe("full-draft replay — every frame of a real 12x14 CBS mock", () => {
  const bodies = replayBodies("full-draft.deltas.jsonl");
  const events = bodies.flatMap((body) => parseDraftEvents({ via: "ws", body }));
  const picks = events.filter((e) => e.event_type === "pick_made");

  it("replays real NUL-terminated frames that JSON.parse alone cannot read", () => {
    // Not a synthetic corpus: every body still carries the terminator, so this fixture
    // would be unreadable if stripCbsFrame regressed.
    expect(bodies.length).toBeGreaterThan(30);
    expect(bodies.every((b) => b.endsWith("\0"))).toBe(true);
    expect(() => JSON.parse(bodies[0]!)).toThrow();
  });

  it("yields exactly one pick_made per real pick, covering 1..168 with no gaps", () => {
    const overalls = picks.map((p) => p.pick_number);
    expect(overalls).toEqual(Array.from({ length: CAPTURE_PICKS }, (_, i) => i + 1));
  });

  it("emits every pick as a schema-valid ID-only event (the crosswalk is mandatory)", () => {
    for (const pick of picks) {
      expect(DraftEventSchema.safeParse(pick).success).toBe(true);
      expect(String(pick.data["player_id"])).toMatch(/^cbs:\d+$/);
      // Picks are ID-only — no name/pos/team rides along (protocol doc section 3).
      expect(pick.data["player_name"]).toBeUndefined();
      expect(pick.data["position"]).toBeUndefined();
    }
  });

  it("derives round/pick_in_round consistently with the overall it carries", () => {
    for (const pick of picks) {
      const overall = pick.pick_number!;
      expect(pick.data["round"]).toBe(Math.floor((overall - 1) / TEAMS) + 1);
      expect(pick.data["pick_in_round"]).toBe(((overall - 1) % TEAMS) + 1);
    }
  });

  it("reads the real draft order (12 entries) and never the 22-entry rolling window", () => {
    const orders = events.filter((e) => e.event_type === "league_settings");
    expect(orders.length).toBeGreaterThan(0);
    for (const order of orders) {
      // A 22-entry upcomingorder window here would set team_count: 22 and silently
      // corrupt every survival number (opponents.py uses len(draft_order) AS the count).
      expect((order.data["draft_order"] as string[]).length).toBe(TEAMS);
      expect(order.data["team_count"]).toBe(TEAMS);
    }
  });

  it("mints no phantom pick at the draft-over sentinel (opick 169 > 168)", () => {
    expect(Math.max(...picks.map((p) => p.pick_number!))).toBe(CAPTURE_PICKS);
    expect(events.some((e) => e.event_type === "draft_complete")).toBe(true);
  });

  it("keeps the pick source CBS reported (autopick vs userpick), for tendency work", () => {
    const sources = new Set(picks.map((p) => p.data["pick_source"]));
    expect(sources.has("autopick")).toBe(true);
    expect(sources.has("userpick")).toBe(true);
  });

  it("drift guard: the committed events artifact matches this parser's output", () => {
    // The Python replay (backend/tests/test_cbs_replay.py) consumes this file. If parse.ts
    // changes shape, regenerate with JAAFFL_WRITE_REPLAY=1 — otherwise the Python half
    // would keep asserting against an output parse.ts no longer produces.
    const artifact = join(CBS, "full-draft.events.json");
    const serialized = `${JSON.stringify(events, null, 2)}\n`;
    if (process.env["JAAFFL_WRITE_REPLAY"]) writeFileSync(artifact, serialized, "utf-8");
    expect(readFileSync(artifact, "utf-8").replace(/\r\n/g, "\n")).toBe(serialized);
  });
});
