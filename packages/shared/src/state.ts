/**
 * Draft board / pick-log view (dashboard `GET /state`).
 *
 * Mirrors the backend view model `backend/src/jaaffl/ingest/board.py::DraftBoardState`. Like that
 * model (and `CbsPageSnapshot`), it is deliberately OUTSIDE the E5 Pydantic⇄Zod parity surface (the
 * strict nine in tests/parity.test.ts) — it is a client-render convenience, not a cross-boundary
 * contract the gate must police. The two sides are simple and kept structurally aligned by hand.
 */
import { z } from "zod";

/** One drafted pick, enriched with the drafted player's display fields for the board. */
export const BoardPickSchema = z.object({
  overall: z.number(),
  round: z.number(),
  pick_in_round: z.number(),
  team_id: z.string(),
  player_id: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  position: z.string().nullable().optional(),
  nfl_team: z.string().nullable().optional(),
});
export type BoardPick = z.infer<typeof BoardPickSchema>;

/** The folded draft plus name-enriched picks — the dashboard board + pick-log feed. */
export const DraftBoardStateSchema = z.object({
  league_id: z.string(),
  current_overall_pick: z.number(),
  on_the_clock_team_id: z.string().nullable().optional(),
  my_team_id: z.string().nullable().optional(),
  complete: z.boolean(),
  picks: z.array(BoardPickSchema),
});
export type DraftBoardState = z.infer<typeof DraftBoardStateSchema>;
