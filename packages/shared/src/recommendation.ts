import { z } from "zod";

export const RecommendedPickSchema = z.object({
  player_id: z.string(),
  score: z.number(),
  projected_points: z.number().nullable().optional(),
  vorp: z.number().nullable().optional(),
  adp: z.number().nullable().optional(),
  next_turn_availability: z.number().min(0).max(1).nullable().optional(),
  tier: z.number().int().nullable().optional(),
  rationale: z.string().nullable().optional(),
});
export type RecommendedPick = z.infer<typeof RecommendedPickSchema>;

export const RecommendationSchema = z.object({
  league_id: z.string(),
  as_of_overall_pick: z.number().int(),
  ranked: z.array(RecommendedPickSchema).default([]),
  reasoning: z.string().nullable().optional(),
});
export type Recommendation = z.infer<typeof RecommendationSchema>;
