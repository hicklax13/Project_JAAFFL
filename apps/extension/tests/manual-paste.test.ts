/**
 * TIER 3 / TASK 3 — the manual-paste fallback, checked against the REAL protocol.
 *
 * Plan §5.11 A7 says manual-paste must produce events "byte-identical to live capture".
 * That acceptance criterion was written against the SYNTHETIC parse.ts vocabulary, in which
 * a pick carried its own name/position/team. The real decoded protocol does not:
 *
 *   live  -> { player_id: "cbs:3162723", cbs_player_id: "3162723" }   (ID-only)
 *   paste -> { player_name: "...", position: "...", player_team: "..." }  (NAME-only)
 *
 * The two carry DISJOINT identity fields, so byte-identity is not achievable — and chasing
 * it would mean inventing a CBS id for a pasted name, which is exactly the kind of guess
 * resolve_pick_ids refuses to make. Surfaced here rather than quietly reconciled, per
 * config/league.json's agent_usage_contract.
 *
 * What A7 was actually protecting — that the draft-day fallback yields the same ADVICE — is
 * real and is proved where the two paths genuinely converge: after id resolution, at the
 * folded board and the recommendation (backend/tests/test_manual_paste_parity.py).
 *
 * ⚠️ The paste TEXT FORMAT remains synthetic. The 2026-07-25 session captured draft-room
 * socket frames, not a "copy results" clipboard payload, so no golden exists for CBS's own
 * export layout. The fixture below uses the real players, teams and pick numbers of a real
 * captured draft in the format parse.ts documents.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { DraftEventSchema } from "@jaaffl/shared";
import { describe, expect, it } from "vitest";

import { parseDraftEvents, parsePastedResults, parsePastedReport } from "../src/lib/parse";

const HERE = dirname(fileURLToPath(import.meta.url));
const CBS = join(HERE, "fixtures", "cbs");

const TEAMS = 12;

function livePicks() {
  const events = JSON.parse(readFileSync(join(CBS, "full-draft.events.json"), "utf-8")) as Array<{
    event_type: string;
    pick_number: number | null;
    data: Record<string, unknown>;
  }>;
  return events.filter((e) => e.event_type === "pick_made");
}

describe("manual paste vs the real live-capture vocabulary", () => {
  const pasteText = readFileSync(join(CBS, "manual-paste.txt"), "utf-8");
  const pasted = parsePastedResults(pasteText);
  const pastedPicks = pasted.filter((e) => e.event_type === "pick_made");

  it("parses every pick line of a real draft's results block", () => {
    expect(pastedPicks.length).toBeGreaterThanOrEqual(24);
    expect(pastedPicks.map((p) => p.pick_number)).toEqual(
      Array.from({ length: pastedPicks.length }, (_, i) => i + 1),
    );
    for (const pick of pastedPicks) {
      expect(DraftEventSchema.safeParse(pick).success).toBe(true);
      expect(pick.source).toBe("paste");
    }
  });

  it("reads the ORDER line rather than synthesizing a snake from team count (A5)", () => {
    const order = pasted.find((e) => e.event_type === "league_settings");
    expect(order).toBeDefined();
    expect((order!.data["draft_order"] as string[]).length).toBe(TEAMS);
  });

  it("carries name/position/team where the live path carries a CBS id — A7 restated", () => {
    // Not a defect: it is what each source actually knows. Asserted so the divergence is
    // pinned rather than rediscovered on draft night.
    const live = livePicks()[0]!;
    const paste = pastedPicks[0]!;

    expect(live.data["player_id"]).toMatch(/^cbs:\d+$/);
    expect(live.data["player_name"]).toBeUndefined();

    expect(paste.data["player_name"]).toBeTruthy();
    expect(paste.data["player_id"]).toBeUndefined();

    // Byte-identity is therefore impossible; the fields they DO share must still agree.
    for (const field of ["overall", "round", "pick_in_round", "team_id"]) {
      expect(paste.data[field]).toEqual(live.data[field]);
    }
  });

  it("agrees with the live path on every shared field, for every pick", () => {
    const live = new Map(livePicks().map((p) => [p.pick_number, p.data]));
    for (const paste of pastedPicks) {
      const liveData = live.get(paste.pick_number ?? null)!;
      expect(liveData).toBeDefined();
      expect({
        overall: paste.data["overall"],
        round: paste.data["round"],
        pick_in_round: paste.data["pick_in_round"],
        team_id: paste.data["team_id"],
      }).toEqual({
        overall: liveData["overall"],
        round: liveData["round"],
        pick_in_round: liveData["pick_in_round"],
        team_id: liveData["team_id"],
      });
    }
  });

  it("converges on the same validate -> de-dup -> send tail as a live frame (§5.5)", () => {
    // Both reach `forward()` as a DraftEvent with the same de-dup key (pick:<pick_number>).
    const liveEvent = parseDraftEvents({
      via: "ws",
      body: (
        JSON.parse(readFileSync(join(CBS, "picks-completed.autopick.json"), "utf-8")) as {
          payload: { body: string };
        }
      ).payload.body,
    }).find((e) => e.event_type === "pick_made")!;
    expect(liveEvent.pick_number).toBe(pastedPicks[0]!.pick_number);
    expect(liveEvent.event_type).toBe(pastedPicks[0]!.event_type);
  });

  it("splits on the separator dash, not on a hyphen inside a player's surname", () => {
    // Found by real data: parse.ts anchored on the LAST dash, reasoning that a team name
    // may contain a hyphen while "the trailing player segment almost never does". Real NFL
    // rosters falsify that — Jaxon Smith-Njigba, Amon-Ra St. Brown, Ray-Ray McCloud. The
    // separator is distinguishable because it is SPACE-SURROUNDED; a surname hyphen is not.
    const [pick] = parsePastedResults("9. 9 - Jaxon Smith-Njigba, WR, SEA");
    expect(pick!.data["team_id"]).toBe("9");
    expect(pick!.data["player_name"]).toBe("Jaxon Smith-Njigba");
    expect(pick!.data["position"]).toBe("WR");
    expect(pick!.data["player_team"]).toBe("SEA");
  });

  it("still anchors on the LAST separator when the team name itself is hyphenated", () => {
    // The original motivating case must keep working.
    const [tight] = parsePastedResults("4. Steel-Curtain Squad - Bijan Robinson, RB, ATL");
    expect(tight!.data["team_id"]).toBe("Steel-Curtain Squad");
    expect(tight!.data["player_name"]).toBe("Bijan Robinson");

    const [spaced] = parsePastedResults("5. Steel - Curtain Squad - Puka Nacua, WR, LAR");
    expect(spaced!.data["team_id"]).toBe("Steel - Curtain Squad");
    expect(spaced!.data["player_name"]).toBe("Puka Nacua");
  });

  it("handles a hyphenated surname AND a hyphenated team name together", () => {
    const [pick] = parsePastedResults("6. Steel-Curtain Squad - Amon-Ra St. Brown, WR, DET");
    expect(pick!.data["team_id"]).toBe("Steel-Curtain Squad");
    expect(pick!.data["player_name"]).toBe("Amon-Ra St. Brown");
  });

  it("reports the lines it could not parse instead of dropping them silently", () => {
    // A stricter separator makes silent drops MORE likely, and a paste panel that says
    // "21 event(s) sent" after being handed 24 picks reads as success. The owner has to be
    // told which lines were skipped, or a missing pick is invisible until it costs a player.
    const report = parsePastedReport(
      ["ORDER: 1, 2, 3", "1. 1 - Puka Nacua, WR, LAR", "2. 2 -- broken", "", "   "].join("\n"),
    );
    expect(report.events).toHaveLength(2); // the ORDER line + the one good pick
    expect(report.skipped).toEqual(["2. 2 -- broken"]);
  });

  it("counts blank lines as nothing at all, not as skipped", () => {
    expect(parsePastedReport("\n\n   \n").skipped).toEqual([]);
    expect(parsePastedReport("\n\n   \n").events).toEqual([]);
  });

  it("parses the real fixture with zero skipped lines", () => {
    // The whole point: a real draft's results block must go through cleanly.
    expect(parsePastedReport(pasteText).skipped).toEqual([]);
  });

  it("keeps parsePastedResults as the events-only view of the same parse", () => {
    expect(parsePastedResults(pasteText)).toEqual(parsePastedReport(pasteText).events);
  });

  it("drift guard: the committed paste artifact matches this parser's output", () => {
    const artifact = join(CBS, "manual-paste.events.json");
    const serialized = `${JSON.stringify(pasted, null, 2)}\n`;
    if (process.env["JAAFFL_WRITE_REPLAY"]) writeFileSync(artifact, serialized, "utf-8");
    expect(readFileSync(artifact, "utf-8").replace(/\r\n/g, "\n")).toBe(serialized);
  });
});
