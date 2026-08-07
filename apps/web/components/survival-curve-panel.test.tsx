import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DraftAnalytics } from "@jaaffl/shared";

import { SurvivalCurvePanel } from "./survival-curve-panel";

const ANALYTICS: DraftAnalytics = {
  league_id: "L1",
  current_overall_pick: 10,
  my_next_picks: [14, 26],
  value_curves: [],
  survival_curves: [
    {
      player_id: "wr0",
      name: "Ja'Marr",
      position: "WR",
      points: [
        { pick: 10, survival: 1 },
        { pick: 14, survival: 0.82 },
        { pick: 26, survival: 0.2 },
      ],
    },
    {
      player_id: "rb0",
      name: "Bijan",
      position: "RB",
      points: [
        { pick: 10, survival: 1 },
        { pick: 14, survival: 0.3 },
        { pick: 26, survival: 0.02 },
      ],
    },
  ],
};

describe("SurvivalCurvePanel", () => {
  it("lists every candidate with its survival at your next pick", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByText("Ja'Marr")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
  });

  it("pairs every survival tier with a WORD, never colour alone", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByText(/can wait/i)).toBeInTheDocument();
    expect(screen.getByText(/take now/i)).toBeInTheDocument();
  });

  it("renders one marker per upcoming pick", () => {
    const { container } = render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(container.querySelectorAll(".sc-marker")).toHaveLength(2);
  });

  it("gives the chart an accessible description that embeds real candidate data", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    // my_next_picks[0] is 14, so this pins the actual computed per-candidate text, not just the
    // static "survival" label prefix (which a chart with no data would also satisfy).
    expect(screen.getByRole("img", { name: /survival/i })).toHaveAccessibleName(/Ja'Marr 82%/i);
  });

  it("shows an honest empty state before the draft starts", () => {
    render(<SurvivalCurvePanel analytics={null} />);
    expect(screen.getByText(/once the draft starts/i)).toBeInTheDocument();
  });

  it("flags survival percentages as spanning the whole chart, never silently, when the draft order is unknown", () => {
    render(<SurvivalCurvePanel analytics={{ ...ANALYTICS, my_next_picks: [] }} />);
    // The percentages fall back to the last charted point (not "at your next pick") once there is
    // no next pick to anchor them — the accessible name must say so, not just the panel note.
    expect(screen.getByRole("img", { name: /draft order not yet known/i })).toBeInTheDocument();
    expect(screen.getByText(/draft order unknown/i)).toBeInTheDocument();
  });
});
