import { describe, expect, it } from "vitest";

import { DraftAnalyticsSchema } from "../src/analytics";

const SAMPLE = {
  league_id: "L1",
  current_overall_pick: 5,
  my_next_picks: [7, 18],
  value_curves: [
    {
      position: "RB",
      full: [{ rank: 1, vor: 92.5, player_id: "rb0", name: "Bijan" }],
      remaining: [{ rank: 1, vor: 80.1, player_id: "rb1", name: "Breece" }],
    },
  ],
  survival_curves: [
    {
      player_id: "wr1",
      name: "Ja'Marr",
      position: "WR",
      points: [
        { pick: 5, survival: 0.98 },
        { pick: 6, survival: 0.91 },
      ],
    },
  ],
};

describe("DraftAnalyticsSchema", () => {
  it("parses a well-formed analytics payload", () => {
    const parsed = DraftAnalyticsSchema.safeParse(SAMPLE);
    expect(parsed.success).toBe(true);
  });

  it("tolerates absent optional display fields", () => {
    const parsed = DraftAnalyticsSchema.safeParse({
      ...SAMPLE,
      survival_curves: [{ player_id: "wr1", points: [] }],
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a payload missing its league id", () => {
    const { league_id: _omitted, ...rest } = SAMPLE;
    expect(DraftAnalyticsSchema.safeParse(rest).success).toBe(false);
  });
});
