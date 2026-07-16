import { z } from "zod";

/**
 * Auditable decomposition of Score(p) (design §10.3) — never a black box.
 *
 * Reconstruction (kappa/alpha and caps from EngineParams):
 *   score ~= mlv + kappa*max(0, vona) - risk_penalty + cliff_bonus + sum(modifiers)
 * `vona` is RAW (pre-kappa, may be negative); `risk_penalty`/`cliff_bonus` are the APPLIED
 * signed contributions; `sigma`/`floor`/`ceiling`/`replacement_baseline` are descriptive.
 */
export const ScoreComponentsSchema = z.object({
  mlv: z.number(),
  vona: z.number(),
  risk_penalty: z.number(),
  cliff_bonus: z.number(),
  sigma: z.number().nonnegative(),
  floor: z.number(),
  ceiling: z.number(),
  replacement_baseline: z.number(),
  modifiers: z.record(z.number()).default({}),
});
export type ScoreComponents = z.infer<typeof ScoreComponentsSchema>;

export const RecommendedPickSchema = z.object({
  player_id: z.string(),
  score: z.number(),
  projected_points: z.number().nullable().optional(),
  vorp: z.number().nullable().optional(),
  adp: z.number().nullable().optional(),
  next_turn_availability: z.number().min(0).max(1).nullable().optional(),
  tier: z.number().int().nullable().optional(),
  rationale: z.string().nullable().optional(),
  // Populated by engine.recommend for every v1 rec (Stage 5); optional so that
  // pre-engine (Stage 1-4) payloads still validate.
  components: ScoreComponentsSchema.nullable().optional(),
});
export type RecommendedPick = z.infer<typeof RecommendedPickSchema>;

export const RecommendationSchema = z.object({
  league_id: z.string(),
  as_of_overall_pick: z.number().int(),
  ranked: z.array(RecommendedPickSchema).default([]),
  reasoning: z.string().nullable().optional(),
});
export type Recommendation = z.infer<typeof RecommendationSchema>;
