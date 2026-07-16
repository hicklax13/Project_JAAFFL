import { z } from "zod";

export const PositionSchema = z.enum(["QB", "RB", "WR", "TE", "K", "DST", "DL", "LB", "DB"]);
export type Position = z.infer<typeof PositionSchema>;

export const RosterSlotSchema = z.object({
  slot: z.string(),
  eligible_positions: z.array(PositionSchema),
  count: z.number().int().nonnegative(),
  starting: z.boolean().default(true),
});
export type RosterSlot = z.infer<typeof RosterSlotSchema>;

export const ScoringRuleSchema = z.object({
  stat: z.string(),
  points_per_unit: z.number(),
  applies_to: z.array(PositionSchema).nullable().optional(),
});
export type ScoringRule = z.infer<typeof ScoringRuleSchema>;

/**
 * One inclusive-lower bracket of a tiered stat. Points awarded when
 * lower <= stat < upper (upper=null => open-ended top bracket).
 */
export const ScoringBracketSchema = z.object({
  lower: z.number(),
  upper: z.number().nullable().optional(),
  points: z.number(),
});
export type ScoringBracket = z.infer<typeof ScoringBracketSchema>;

/** A bracketed (non-linear) scoring stat, e.g. CBS DST points-allowed / yards-allowed. */
export const ScoringTierSchema = z.object({
  stat: z.string(),
  applies_to: z.array(PositionSchema).nullable().optional(),
  brackets: z.array(ScoringBracketSchema).default([]),
});
export type ScoringTier = z.infer<typeof ScoringTierSchema>;

/** A threshold bonus, e.g. K field goal of 50+ yards => +N points. */
export const ScoringBonusSchema = z.object({
  stat: z.string(),
  threshold: z.number(),
  points: z.number(),
  applies_to: z.array(PositionSchema).nullable().optional(),
});
export type ScoringBonus = z.infer<typeof ScoringBonusSchema>;

export const LeagueSettingsSchema = z.object({
  league_id: z.string(),
  platform: z.string().default("cbs"),
  name: z.string().nullable().optional(),
  team_count: z.number().int().min(2),
  roster_slots: z.array(RosterSlotSchema).default([]),
  scoring: z.array(ScoringRuleSchema).default([]),
  // CBS "Standard" scores DST on BOTH points-allowed AND yards-allowed brackets, and
  // awards threshold bonuses (e.g. K 50+ yd FG) that flat linear rules cannot express.
  scoring_tiers: z.array(ScoringTierSchema).default([]),
  scoring_bonuses: z.array(ScoringBonusSchema).default([]),
  draft_type: z.string().default("snake"),
  // Never inferred from team_count alone — read from the live room when available.
  draft_order: z.array(z.string()).nullable().optional(),
  keeper: z.boolean().default(false),
  dynasty: z.boolean().default(false),
  raw: z.record(z.unknown()).default({}),
});
export type LeagueSettings = z.infer<typeof LeagueSettingsSchema>;
