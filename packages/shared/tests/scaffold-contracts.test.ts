/**
 * Phase 0 scaffold-change contracts (plan §1.4), Zod side — mirrors
 * backend/tests/test_scaffold_contracts.py. Structure over values: the real CBS
 * bracket numbers are read live in Stage 2.
 */
import { describe, expect, it } from "vitest";

import {
  DraftEventSchema,
  DraftStateSchema,
  LeagueSettingsSchema,
  RecommendedPickSchema,
  ScoreComponentsSchema,
} from "../src/index";

const dstDualTiers = [
  {
    stat: "dst_points_allowed",
    applies_to: ["DST"],
    brackets: [
      { lower: 0, upper: 1, points: 10 },
      { lower: 1, upper: 7, points: 7 },
      { lower: 35, upper: null, points: -4 },
    ],
  },
  {
    stat: "dst_yards_allowed",
    applies_to: ["DST"],
    brackets: [
      { lower: 0, upper: 100, points: 5 },
      { lower: 400, upper: null, points: -3 },
    ],
  },
];

const fullComponents = {
  mlv: 42.5,
  vona: -3.1, // raw VONA may be negative (pre-kappa, pre-max-gate)
  risk_penalty: 1.8,
  cliff_bonus: 0.9,
  sigma: 12.0,
  floor: 110.0,
  ceiling: 180.0,
  replacement_baseline: 95.0,
  modifiers: { bye_stack: -1.5, handcuff_synergy: 2.0, sos: 0.5 },
  reliability: 1.0,
  vona_horizon: 2,
  best_available_next: 38.7,
};

describe("LeagueSettings scoring_tiers + scoring_bonuses (SC1)", () => {
  it("defaults both new fields to empty arrays", () => {
    const parsed = LeagueSettingsSchema.parse({ league_id: "L1", team_count: 12 });
    expect(parsed.scoring_tiers).toEqual([]);
    expect(parsed.scoring_bonuses).toEqual([]);
  });

  it("parses DST dual tiers (points- AND yards-allowed) with an open-ended top bracket", () => {
    const parsed = LeagueSettingsSchema.parse({
      league_id: "L1",
      team_count: 12,
      scoring_tiers: dstDualTiers,
      scoring_bonuses: [
        { stat: "field_goal_distance", threshold: 50, points: 2, applies_to: ["K"] },
      ],
    });
    expect(parsed.scoring_tiers.map((t) => t.stat)).toEqual([
      "dst_points_allowed",
      "dst_yards_allowed",
    ]);
    expect(parsed.scoring_tiers[0]!.brackets[2]!.upper).toBeNull();
    expect(parsed.scoring_bonuses[0]!.threshold).toBe(50);
  });

  it("rejects a bracket missing its points", () => {
    const bad = [{ stat: "dst_points_allowed", brackets: [{ lower: 0, upper: 1 }] }];
    expect(() =>
      LeagueSettingsSchema.parse({ league_id: "L1", team_count: 12, scoring_tiers: bad }),
    ).toThrow();
  });
});

describe("DraftEvent pick_number + source (Stage 1, §5.8)", () => {
  it("parses the de-dup key and winning probe", () => {
    const parsed = DraftEventSchema.parse({
      event_type: "pick_made",
      league_id: "L1",
      pick_number: 25,
      source: "ws",
      data: { overall: 25, round: 3, pick_in_round: 1, team_id: "T1" },
    });
    expect(parsed.pick_number).toBe(25);
    expect(parsed.source).toBe("ws");
  });

  it("keeps both fields additive + optional", () => {
    const parsed = DraftEventSchema.parse({ event_type: "league_settings", league_id: "L1" });
    expect(parsed.pick_number ?? null).toBeNull();
    expect(parsed.source ?? null).toBeNull();
  });

  it("rejects unknown source values and non-positive pick numbers", () => {
    expect(() =>
      DraftEventSchema.parse({ event_type: "pick_made", league_id: "L1", source: "manual" }),
    ).toThrow();
    expect(() =>
      DraftEventSchema.parse({ event_type: "pick_made", league_id: "L1", pick_number: 0 }),
    ).toThrow();
  });

  it("DraftState.complete defaults false (§2.6 terminal marker)", () => {
    const parsed = DraftStateSchema.parse({ league_id: "L1", current_overall_pick: 1 });
    expect(parsed.complete).toBe(false);
  });
});

describe("RecommendedPick.components (SC3)", () => {
  it("parses a fully-populated ScoreComponents", () => {
    const parsed = RecommendedPickSchema.parse({
      player_id: "p1",
      score: 51.2,
      components: fullComponents,
    });
    expect(parsed.components?.modifiers).toEqual(fullComponents.modifiers);
    expect(parsed.components?.vona).toBeLessThan(0);
    expect(parsed.components?.vona_horizon).toBe(2);
    expect(parsed.components?.best_available_next).toBe(38.7);
  });

  it("keeps the §3.10.5 round-aware fields additive + optional (pre-v1.1 payloads validate)", () => {
    const {
      reliability: _r,
      vona_horizon: _h,
      best_available_next: _b,
      ...preV11
    } = fullComponents;
    const parsed = ScoreComponentsSchema.parse(preV11);
    expect(parsed.reliability ?? null).toBeNull();
    expect(parsed.vona_horizon ?? null).toBeNull();
    expect(parsed.best_available_next ?? null).toBeNull();
  });

  it("keeps components optional for pre-engine payloads", () => {
    const parsed = RecommendedPickSchema.parse({ player_id: "p1", score: 1.0 });
    expect(parsed.components ?? null).toBeNull();
  });

  it("rejects a negative sigma", () => {
    expect(() =>
      ScoreComponentsSchema.parse({ ...fullComponents, sigma: -0.1 }),
    ).toThrow();
  });
});
