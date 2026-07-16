/**
 * Cross-probe de-dup (plan §5.5): first probe to report a pick_number wins; redundant
 * on_the_clock re-renders collapse; league snapshots pass through. The backend's
 * SQLite unique index is the durable de-dup of record — this is the cheap first line.
 */
import { describe, expect, it } from "vitest";
import type { DraftEvent } from "@jaaffl/shared";

import { createForwarder, dedupKey } from "../src/lib/dedup";

function pick(overall: number, source: DraftEvent["source"]): DraftEvent {
  return {
    event_type: "pick_made",
    league_id: "L1",
    pick_number: overall,
    source,
    data: { overall, round: 1, pick_in_round: overall, team_id: `T${overall}` },
  };
}

describe("dedupKey", () => {
  it("keys picks by pick_number and on_the_clock/draft_state by current pick", () => {
    expect(dedupKey(pick(5, "ws"))).toBe("pick:5");
    expect(
      dedupKey({
        event_type: "on_the_clock",
        league_id: "L1",
        data: { current_overall_pick: 6, team_id: "T6" },
      }),
    ).toBe("otc:6");
    expect(
      dedupKey({
        event_type: "draft_state",
        league_id: "L1",
        data: { current_overall_pick: 6 },
      }),
    ).toBe("state:6");
  });
});

describe("createForwarder", () => {
  it("sends a pick once when three probes double-fire it (A3)", () => {
    const sent: DraftEvent[] = [];
    const forward = createForwarder((e) => sent.push(e));
    forward(pick(5, "ws"));
    forward(pick(5, "framework"));
    forward(pick(5, "dom"));
    expect(sent).toHaveLength(1);
    expect(sent[0]!.source).toBe("ws"); // first probe wins
  });

  it("drops invalid candidates at the Zod gate (trust boundary)", () => {
    const sent: DraftEvent[] = [];
    const forward = createForwarder((e) => sent.push(e));
    forward({ event_type: "nonsense", league_id: "L1" } as unknown as DraftEvent);
    forward({ event_type: "pick_made", league_id: "L1", pick_number: 0 } as DraftEvent);
    expect(sent).toHaveLength(0);
  });

  it("lets distinct picks and repeated league snapshots through", () => {
    const sent: DraftEvent[] = [];
    const forward = createForwarder((e) => sent.push(e));
    forward(pick(1, "ws"));
    forward(pick(2, "ws"));
    const settings: DraftEvent = {
      event_type: "league_settings",
      league_id: "L1",
      data: { league_id: "L1", team_count: 12 },
    };
    forward(settings);
    forward({ ...settings, data: { ...settings.data, name: "renamed" } });
    expect(sent).toHaveLength(4);
  });
});
