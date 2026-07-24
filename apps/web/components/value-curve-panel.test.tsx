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

const CURVE_DEPTH = 36; // backend/src/jaaffl/engine/analytics.py CURVE_DEPTH
const DRAFTED_COUNT = 10;

/** `count` distinct synthetic players numbered from `startingAt`, ranked 1..count, VOR descending. */
function makeCurvePoints(count: number, startingAt: number) {
  return Array.from({ length: count }, (_, i) => {
    const n = startingAt + i;
    return { rank: i + 1, vor: 500 - n, player_id: `rb${n}`, name: `Runner ${n}` };
  });
}

// A position with MORE than CURVE_DEPTH draftable players (RB/WR always, in the real nflverse
// universe): the backend caps `full` AND `remaining` at CURVE_DEPTH independently, so drafting the
// top 10 backfills `remaining` from players ranked 37-46 instead of shrinking it. Both arrays stay
// at length 36, overlapping only on players 11-36 — `full.length - remaining.length` reads this as
// "0 taken" when the true count is 10 (see describe() in value-curve-panel.tsx).
const OVERFLOW_ANALYTICS: DraftAnalytics = {
  league_id: "L1",
  current_overall_pick: DRAFTED_COUNT + 1,
  my_next_picks: [],
  value_curves: [
    {
      position: "RB",
      full: makeCurvePoints(CURVE_DEPTH, 1), // players 1-36 (the original top-36 board)
      remaining: makeCurvePoints(CURVE_DEPTH, DRAFTED_COUNT + 1), // players 11-46 (backfilled)
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
    expect(chart).toHaveAccessibleName(/1 of the top 2 taken/i);
  });

  it("counts drafted players correctly when a position exceeds the curve cap and remaining backfills past it", () => {
    render(<ValueCurvePanel analytics={OVERFLOW_ANALYTICS} />);
    const chart = screen.getByRole("img", { name: /RB value curve/i });
    // full.length (36) - remaining.length (36) would say "0 of the top 36 taken" — but 10 real
    // players (rb1..rb10) are gone from `remaining`, backfilled by rb37..rb46. This is the count
    // of full-entries no longer present in remaining, i.e. the true number drafted.
    expect(chart).toHaveAccessibleName(/10 of the top 36 taken/i);
  });

  it("shows an honest empty state when the engine is still warming", () => {
    render(<ValueCurvePanel analytics={null} />);
    expect(screen.getByText(/warm up with the engine/i)).toBeInTheDocument();
  });
});
