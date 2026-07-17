/**
 * The "why" panel (plan §6.5) — the anti-black-box guarantee rendered. It MUST show every
 * Score(p) term and prove on screen that they reconstruct the total (§8.2 identity).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecommendedPick } from "@jaaffl/shared";

import { WhyPanel } from "./why-panel";

const REASONING = "R1P5 · floor-tilt λ=+0.3 · κ=0.6 · α=0.4 · flex_split=8RB/4WR (EngineParams v1.0.0)";

const PICK1: RecommendedPick = {
  player_id: "jaaffl:00-0036223",
  score: 42.1,
  next_turn_availability: 0.18,
  tier: 1,
  components: {
    mlv: 33.7,
    vona: 12.5,
    risk_penalty: 2.1,
    cliff_bonus: 3.4,
    sigma: 41.0,
    floor: 214.0,
    ceiling: 322.0,
    replacement_baseline: 118.6,
    modifiers: { bye_stack: -0.4 },
  },
};

describe("WhyPanel", () => {
  it("renders every Score(p) term with its signed contribution", () => {
    render(<WhyPanel pick={PICK1} params={REASONING} position="RB" />);
    for (const label of ["MLV", "VONA", "Risk", "Cliff"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByTestId("why-term-mlv")).toHaveTextContent("33.7");
    expect(screen.getByTestId("why-term-vona")).toHaveTextContent("7.5"); // kappa*max(0,12.5)
    expect(screen.getByTestId("why-term-risk")).toHaveTextContent("2.1");
    expect(screen.getByTestId("why-term-cliff")).toHaveTextContent("3.4");
  });

  it("proves the reconstruction: the displayed total equals score and reconciles", () => {
    render(<WhyPanel pick={PICK1} params={REASONING} position="RB" />);
    const total = screen.getByTestId("why-total");
    expect(total).toHaveTextContent("42.1");
    // an explicit, accessible reconciliation affordance (the anti-black-box guarantee)
    expect(screen.getByLabelText(/reconstructs/i)).toBeInTheDocument();
  });

  it("renders capped modifiers as their own labeled contributions", () => {
    render(<WhyPanel pick={PICK1} params={0.6} position="RB" />);
    expect(screen.getByText(/bye stack/i)).toBeInTheDocument();
  });

  it("degrades gracefully when a pick carries no components (pre-v1 payload)", () => {
    const bare: RecommendedPick = { player_id: "p1", score: 10 };
    render(<WhyPanel pick={bare} params={0.6} />);
    expect(screen.getByText(/decomposition unavailable/i)).toBeInTheDocument();
  });
});
