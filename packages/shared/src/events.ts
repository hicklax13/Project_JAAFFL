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
  /** The round-1 team order actually entered into CBS, read from the room — never inferred. */
  draft_order: z.array(z.string()).nullable().optional(),
  picks: z.array(DraftPickSchema).default([]),
  available_player_ids: z.array(z.string()).nullable().optional(),
  // §2.6 reducer: a draft_complete event marks the state terminal.
  complete: z.boolean().default(false),
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

/** Which capture probe won (§5.4): network patch, React-fiber, DOM fallback, manual paste. */
export const DraftEventSourceSchema = z.enum(["ws", "framework", "dom", "paste"]);
export type DraftEventSource = z.infer<typeof DraftEventSourceSchema>;

/** The normalized envelope the extension POSTs to /draft/events (or sends over /draft/ws). */
export const DraftEventSchema = z.object({
  event_type: DraftEventTypeSchema,
  league_id: z.string(),
  // Cross-probe de-dup key (§5.8): overall pick (1..204 for 12x17); required-when-present
  // for pick_made, null for non-pick events.
  pick_number: z.number().int().min(1).nullable().optional(),
  source: DraftEventSourceSchema.nullable().optional(),
  data: z.record(z.unknown()).default({}),
});
export type DraftEvent = z.infer<typeof DraftEventSchema>;
