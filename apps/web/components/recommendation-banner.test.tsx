/**
 * Projection provenance on Surface B (plan §5 live-data honesty). The dashboard reuses the SAME
 * shared rule as the overlay (`projectionProvenance`), so the two surfaces cannot disagree about
 * which players have a modeled projection and which carry only a rank-derived fallback.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecommendedPick } from "@jaaffl/shared";

import { RecommendationBanner } from "./recommendation-banner";

const PICK: RecommendedPick = {
  player_id: "p1",
  name: "James Cook",
  position: "RB",
  nfl_team: "BUF",
  bye_week: 7,
  score: 41.2,
  components: {
    mlv: 32.4,
    vona: 15,
    risk_penalty: 2.1,
    cliff_bonus: 2,
    sigma: 40,
    floor: 200,
    ceiling: 300,
    replacement_baseline: 118,
    modifiers: {},
  },
};

describe("RecommendationBanner projection provenance", () => {
  it("marks an ECR-only pick as having no modeled projection", () => {
    render(<RecommendationBanner best={{ ...PICK, projection_sources: ["ecr"] }} />);
    expect(screen.getByText(/ECR only/i)).toBeTruthy();
  });

  it("leaves an xEP-backed pick unmarked, so the flag carries the information", () => {
    render(<RecommendationBanner best={{ ...PICK, projection_sources: ["ecr", "xep"] }} />);
    expect(screen.queryByText(/ECR only/i)).toBeNull();
  });

  it("shows nothing when provenance is unknown rather than guessing", () => {
    render(<RecommendationBanner best={PICK} />);
    expect(screen.queryByText(/ECR only/i)).toBeNull();
  });
});
