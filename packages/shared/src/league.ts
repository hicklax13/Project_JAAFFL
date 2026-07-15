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

export const LeagueSettingsSchema = z.object({
  league_id: z.string(),
  platform: z.string().default("cbs"),
  name: z.string().nullable().optional(),
  team_count: z.number().int().min(2),
  roster_slots: z.array(RosterSlotSchema).default([]),
  scoring: z.array(ScoringRuleSchema).default([]),
  draft_type: z.string().default("snake"),
  // Never inferred from team_count alone — read from the live room when available.
  draft_order: z.array(z.string()).nullable().optional(),
  keeper: z.boolean().default(false),
  dynasty: z.boolean().default(false),
  raw: z.record(z.unknown()).default({}),
});
export type LeagueSettings = z.infer<typeof LeagueSettingsSchema>;
