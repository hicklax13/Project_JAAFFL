import { describe, expect, it } from "vitest";

import { formatPct, survivalOutlook } from "../src/survival";

describe("survivalOutlook", () => {
  it("classifies safe / contested / scarce at the 0.55 and 0.40 thresholds (inclusive)", () => {
    expect(survivalOutlook(0.9).level).toBe("safe");
    expect(survivalOutlook(0.55).level).toBe("safe");
    expect(survivalOutlook(0.5).level).toBe("contested");
    expect(survivalOutlook(0.4).level).toBe("contested");
    expect(survivalOutlook(0.39).level).toBe("scarce");
    expect(survivalOutlook(0).level).toBe("scarce");
  });

  it("gives each tier a distinct glyph, word, status class, and color var (never color-alone)", () => {
    const safe = survivalOutlook(0.8);
    const contested = survivalOutlook(0.45);
    const scarce = survivalOutlook(0.1);
    // The single canonical vocabulary both surfaces render — no per-surface drift.
    expect([safe.word, contested.word, scarce.word]).toEqual(["can wait", "watch", "take now"]);
    expect([safe.statusClass, contested.statusClass, scarce.statusClass]).toEqual([
      "is-good",
      "is-warning",
      "is-critical",
    ]);
    expect(safe.colorVar).toBe("var(--good)");
    expect(contested.colorVar).toBe("var(--warning)");
    expect(scarce.colorVar).toBe("var(--critical)");
    // Identity is never colour-alone: every tier also carries a glyph and a word.
    for (const o of [safe, contested, scarce]) {
      expect(o.glyph).toBeTruthy();
      expect(o.word).toBeTruthy();
    }
  });
});

describe("formatPct", () => {
  it("rounds a probability to a whole-percent string", () => {
    expect(formatPct(0.18)).toBe("18%");
    expect(formatPct(0.555)).toBe("56%");
    expect(formatPct(1)).toBe("100%");
    expect(formatPct(0)).toBe("0%");
  });
});
