import { z } from "zod";

export const DraftPickSchema = z.object({
  overall: z.number().int().min(1),
  round: z.number().int().min(1),
  pick_in_round: z.number().int().min(1),
  team_id: z.string(),
  player_id: z.string().nullable().optional(),
});
export type DraftPick = z.infer<typeof DraftPickSchema>;

export const DraftStateSchema = z.object({
  league_id: z.string(),
  current_overall_pick: z.number().int().min(1),
  on_the_clock_team_id: z.string().nullable().optional(),
  my_team_id: z.string().nullable().optional(),
  picks: z.array(DraftPickSchema).default([]),
  available_player_ids: z.array(z.string()).nullable().optional(),
});
export type DraftState = z.infer<typeof DraftStateSchema>;

export const DraftEventTypeSchema = z.enum([
  "league_settings",
  "draft_state",
  "on_the_clock",
  "pick_made",
  "draft_complete",
]);
export type DraftEventType = z.infer<typeof DraftEventTypeSchema>;

/** The normalized envelope the extension POSTs to /draft/events (or sends over /draft/ws). */
export const DraftEventSchema = z.object({
  event_type: DraftEventTypeSchema,
  league_id: z.string(),
  data: z.record(z.unknown()).default({}),
});
export type DraftEvent = z.infer<typeof DraftEventSchema>;
