import { describe, expect, it } from "vitest";

import type { BoardPick } from "@jaaffl/shared";

import { toDraftBoard } from "./board";

function pick(
  overall: number,
  round: number,
  pickInRound: number,
  teamId: string,
  name: string,
): BoardPick {
  return {
    overall,
    round,
    pick_in_round: pickInRound,
    team_id: teamId,
    name,
    position: "RB",
    nfl_team: "SF",
    player_id: null,
  };
}

describe("toDraftBoard", () => {
  it("orders team columns by draft slot (first-pick order), not lexicographically", () => {
    // Round 1 of a snake drafts in overall order, so T2 (pick 1) precedes T10 (pick 2) —
    // a naive string sort would wrongly put T10 before T2.
    const board = toDraftBoard([pick(1, 1, 1, "T2", "A"), pick(2, 1, 2, "T10", "B")]);
    expect(board.teams).toEqual(["T2", "T10"]);
  });

  it("places each pick in its (round, team) cell and leaves undrafted cells empty", () => {
    const board = toDraftBoard([
      pick(1, 1, 1, "T1", "CMC"),
      pick(24, 2, 12, "T1", "Handcuff"), // T1's round-2 pick (snake wrap)
    ]);
    expect(board.cell(1, "T1")?.name).toBe("CMC");
    expect(board.cell(2, "T1")?.name).toBe("Handcuff");
    expect(board.cell(3, "T1")).toBeUndefined();
  });

  it("builds a contiguous round list from 1 to the max round drafted", () => {
    expect(toDraftBoard([pick(1, 1, 1, "T1", "A"), pick(13, 2, 1, "T1", "B")]).rounds).toEqual([
      1, 2,
    ]);
  });

  it("lists the pick-log newest first", () => {
    const board = toDraftBoard([
      pick(1, 1, 1, "T1", "first"),
      pick(2, 1, 2, "T2", "second"),
      pick(3, 1, 3, "T3", "third"),
    ]);
    expect(board.log.map((p) => p.name)).toEqual(["third", "second", "first"]);
  });

  it("handles an empty board", () => {
    const board = toDraftBoard([]);
    expect(board.teams).toEqual([]);
    expect(board.rounds).toEqual([]);
    expect(board.log).toEqual([]);
  });
});
