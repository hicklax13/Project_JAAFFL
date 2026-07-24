import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DraftAnalytics } from "@jaaffl/shared";

import { ValueCurvePanel } from "./value-curve-panel";

const ANALYTICS: DraftAnalytics = {
  league_id: "L1",
  current_overall_pick: 3,
  my_next_picks: [7, 18],
  value_curves: [
    {
      position: "RB",
      full: [
        { rank: 1, vor: 90, player_id: "rb0", name: "Bijan" },
        { rank: 2, vor: 40, player_id: "rb1", name: "Breece" },
      ],
      remaining: [{ rank: 1, vor: 40, player_id: "rb1", name: "Breece" }],
    },
    {
      position: "WR",
      full: [
        { rank: 1, vor: 70, player_id: "wr0", name: "Ja'Marr" },
        { rank: 2, vor: 65, player_id: "wr1", name: "Justin" },
      ],
      remaining: [
        { rank: 1, vor: 70, player_id: "wr0", name: "Ja'Marr" },
        { rank: 2, vor: 65, player_id: "wr1", name: "Justin" },
      ],
    },
  ],
  survival_curves: [],
};

describe("ValueCurvePanel", () => {
  it("renders a toggle button per charted position", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByRole("button", { name: /RB/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /WR/ })).toBeInTheDocument();
  });

  it("selects the first position by default and marks it pressed", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByRole("button", { name: /RB/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /WR/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("switches the charted position when a chip is clicked", async () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    await userEvent.click(screen.getByRole("button", { name: /WR/ }));
    expect(screen.getByRole("button", { name: /WR/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /WR value curve/i })).toBeInTheDocument();
  });

  it("describes the curve for screen readers, never colour-alone", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    const chart = screen.getByRole("img", { name: /RB value curve/i });
    expect(chart).toHaveAccessibleName(/1 of 2 taken/i);
  });

  it("shows an honest empty state when the engine is still warming", () => {
    render(<ValueCurvePanel analytics={null} />);
    expect(screen.getByText(/warm up with the engine/i)).toBeInTheDocument();
  });
});
