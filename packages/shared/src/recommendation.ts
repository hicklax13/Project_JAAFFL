import { z } from "zod";

import { PositionSchema } from "./league";

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
  // §3.10 v1.1 additive/optional — round-aware explainability (safe for pre-v1.1 payloads):
  // r_pos reliability shrinkage, VONA look-ahead horizon H, and E[best MLV at pos by N_H*].
  reliability: z.number().nullable().optional(),
  vona_horizon: z.number().int().nullable().optional(),
  best_available_next: z.number().nullable().optional(),
});
export type ScoreComponents = z.infer<typeof ScoreComponentsSchema>;

export const RecommendedPickSchema = z.object({
  player_id: z.string(),
  score: z.number(),
  // Display metadata so a pick is self-describing for the UI (name/pos/team/bye); the engine
  // fills these from the DraftContext player universe. All optional/nullable — additive, so
  // pre-enrichment payloads still validate and the UI degrades to the player_id.
  name: z.string().nullable().optional(),
  position: PositionSchema.nullable().optional(),
  nfl_team: z.string().nullable().optional(),
  bye_week: z.number().int().nullable().optional(),
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
