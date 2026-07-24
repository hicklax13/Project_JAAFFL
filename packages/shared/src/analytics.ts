/**
 * Dashboard analytics feed (`GET /analytics`) — value curves + survival curves.
 *
 * Mirrors the backend view models in `backend/src/jaaffl/engine/analytics.py`. Like
 * `DraftBoardState` (see `state.ts`) and `CbsPageSnapshot`, it is deliberately OUTSIDE the E5
 * Pydantic⇄Zod parity surface (the strict nine in tests/parity.test.ts) — it is a client-render
 * convenience, not a cross-boundary contract the gate must police. The two sides are simple and
 * kept structurally aligned by hand. Do NOT add these to CONTRACT_SCHEMAS.
 */
import { z } from "zod";

/** One (rank, VOR) sample on a positional value curve. */
export const CurvePointSchema = z.object({
  rank: z.number(),
  vor: z.number(),
  player_id: z.string(),
  name: z.string().nullable().optional(),
});
export type CurvePoint = z.infer<typeof CurvePointSchema>;

/** A position's value curve: the original board (`full`) and what is still undrafted. */
export const PositionCurveSchema = z.object({
  position: z.string(),
  full: z.array(CurvePointSchema),
  remaining: z.array(CurvePointSchema),
});
export type PositionCurve = z.infer<typeof PositionCurveSchema>;

/** P(still on the board) at one overall pick number. */
export const SurvivalPointSchema = z.object({
  pick: z.number(),
  survival: z.number(),
});
export type SurvivalPoint = z.infer<typeof SurvivalPointSchema>;

/** One candidate's availability decay across the charted pick span. */
export const SurvivalCurveSchema = z.object({
  player_id: z.string(),
  name: z.string().nullable().optional(),
  position: z.string().nullable().optional(),
  points: z.array(SurvivalPointSchema),
});
export type SurvivalCurve = z.infer<typeof SurvivalCurveSchema>;

/** The whole analytics payload: both series plus the pick markers that anchor them. */
export const DraftAnalyticsSchema = z.object({
  league_id: z.string(),
  current_overall_pick: z.number(),
  my_next_picks: z.array(z.number()),
  value_curves: z.array(PositionCurveSchema),
  survival_curves: z.array(SurvivalCurveSchema),
});
export type DraftAnalytics = z.infer<typeof DraftAnalyticsSchema>;
