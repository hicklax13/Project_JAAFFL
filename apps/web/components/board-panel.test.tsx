import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DraftBoardState } from "@jaaffl/shared";

import { BoardPanel } from "./board-panel";

const STATE: DraftBoardState = {
  league_id: "cbs-local",
  current_overall_pick: 3,
  on_the_clock_team_id: "T3",
  my_team_id: "T1",
  complete: false,
  picks: [
    {
      overall: 1,
      round: 1,
      pick_in_round: 1,
      team_id: "T1",
      player_id: "gsis:cmc",
      name: "Christian McCaffrey",
      position: "RB",
      nfl_team: "SF",
    },
    {
      overall: 2,
      round: 1,
      pick_in_round: 2,
      team_id: "T2",
      player_id: null, // name-only paste pick that never resolved — still shows on the board
      name: "Tyreek Hill",
      position: "WR",
      nfl_team: "MIA",
    },
  ],
};

describe("BoardPanel", () => {
  it("renders drafted players in the grid and lists them in the pick log", () => {
    render(<BoardPanel state={STATE} />);
    expect(screen.getAllByText("Christian McCaffrey").length).toBeGreaterThan(0);
    const log = screen.getByLabelText("Pick log");
    expect(within(log).getByText("Tyreek Hill")).toBeInTheDocument();
  });

  it("shows an empty state before any pick", () => {
    render(<BoardPanel state={null} />);
    expect(screen.getByText(/Picks appear here/i)).toBeInTheDocument();
  });
});
