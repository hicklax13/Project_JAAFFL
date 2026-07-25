/**
 * Projection provenance (plan §5 live-data honesty). `PlayerProjection.sources` records which $0
 * sources backed each player's mu; on the live board ~70 players are ECR-ONLY, meaning no modeled
 * projection at all — mu is still the rank-derived fallback curve. One shared rule so the overlay
 * and the dashboard can never disagree about what counts as degraded.
 */
import { describe, expect, it } from "vitest";

import { projectionProvenance } from "../src/provenance";

describe("projectionProvenance", () => {
  it("treats a modeled source as a real projection", () => {
    const p = projectionProvenance(["ecr", "xep"])!;
    expect(p.modeled).toBe(true);
    expect(p.label).toBe("ECR + xEP");
  });

  it("flags ECR-only as a rank-derived fallback, not a projection", () => {
    const p = projectionProvenance(["ecr"])!;
    expect(p.modeled).toBe(false);
    expect(p.label).toBe("ECR only");
    expect(p.detail).toMatch(/rank/i);
  });

  it("treats xEP alone as modeled", () => {
    expect(projectionProvenance(["xep"])!.modeled).toBe(true);
  });

  it("counts CBS on-page projections as modeled once that source exists", () => {
    expect(projectionProvenance(["ecr", "projections"])!.modeled).toBe(true);
  });

  it("returns null when provenance is unknown, so the UI shows nothing rather than guessing", () => {
    expect(projectionProvenance(null)).toBeNull();
    expect(projectionProvenance(undefined)).toBeNull();
    expect(projectionProvenance([])).toBeNull();
  });

  it("renders unknown source keys rather than dropping them silently", () => {
    const p = projectionProvenance(["ecr", "somenewfeed"])!;
    expect(p.label).toContain("somenewfeed");
    expect(p.modeled).toBe(true); // anything beyond bare ECR is more than a rank guess
  });
});
