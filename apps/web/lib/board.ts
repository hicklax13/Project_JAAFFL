import type { BoardPick } from "@jaaffl/shared";

/** A draft board pivoted for rendering: team columns (in slot order), round rows, cell lookup,
 * and the chronological pick-log. Pure — derived entirely from the pick stream. */
export interface DraftBoard {
  /** Column order: teams sorted by the overall of their FIRST pick. In a snake draft round 1
   * drafts in slot order, so first-pick order reconstructs the draft columns without draft_order
   * (which is null until read live). */
  teams: string[];
  /** Row order: a contiguous 1..maxRound so partly-filled later rounds still render a full grid. */
  rounds: number[];
  /** The pick at a (round, team) cell, or undefined for a not-yet-drafted cell. */
  cell: (round: number, teamId: string) => BoardPick | undefined;
  /** The pick-log / ticker, newest pick first. */
  log: BoardPick[];
}

export function toDraftBoard(picks: BoardPick[]): DraftBoard {
  const firstSeen = new Map<string, number>();
  const byCell = new Map<string, BoardPick>();
  let maxRound = 0;
  for (const p of picks) {
    const seen = firstSeen.get(p.team_id);
    if (seen === undefined || p.overall < seen) firstSeen.set(p.team_id, p.overall);
    byCell.set(`${p.round}:${p.team_id}`, p);
    if (p.round > maxRound) maxRound = p.round;
  }
  return {
    teams: [...firstSeen.keys()].sort((a, b) => firstSeen.get(a)! - firstSeen.get(b)!),
    rounds: Array.from({ length: maxRound }, (_, i) => i + 1),
    cell: (round, teamId) => byCell.get(`${round}:${teamId}`),
    log: [...picks].sort((a, b) => b.overall - a.overall),
  };
}
