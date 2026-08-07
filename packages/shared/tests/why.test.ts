/**
 * The "why" reconstruction primitive (plan §6.5 / §8.2). Uses the canonical §8.3.3
 * response examples, whose reconstruction identity the plan states explicitly:
 *   pick 1 (kappa=0.6): 33.7 + 0.6*12.5 - 2.1 + 3.4 + (-0.4) = 42.1
 *   pick 2 (kappa=0.6): 34.9 + 0.6*6.2  - 1.8 + 2.6 + 0      = 39.4
 */
import { describe, expect, it } from "vitest";

import type { RecommendedPick } from "../src/recommendation";
import {
  decomposeWhy,
  formatScore,
  formatSignedScore,
  parseEngineParams,
  whyTermBar,
  whyTermColorVar,
} from "../src/why";
import type { WhyTerm, WhyTermBar } from "../src/why";

const REASONING =
  "R1P5 · floor-tilt λ=+0.3 · κ=0.6 · α=0.4 · flex_split=8RB/4WR " +
  "(EngineParams v1.0.0; flex MEASURED live via top-60, may skew RB-heavy in non-PPR).";

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
    modifiers: { handcuff_synergy: 0.0, bye_stack: -0.4 },
  },
};

describe("parseEngineParams", () => {
  it("extracts kappa/alpha/lambda/flex_split/version from the reasoning line", () => {
    const p = parseEngineParams(REASONING);
    expect(p.kappa).toBeCloseTo(0.6);
    expect(p.alpha).toBeCloseTo(0.4);
    expect(p.lambda).toBeCloseTo(0.3); // "λ=+0.3" -> +0.3
    expect(p.flexSplit).toEqual({ rb: 8, wr: 4 });
    expect(p.paramsVersion).toBe("1.0.0");
  });

  it("returns all-null for empty/missing reasoning", () => {
    const p = parseEngineParams(null);
    expect(p.kappa).toBeNull();
    expect(p.flexSplit).toBeNull();
    expect(p.raw).toBe("");
  });
});

describe("decomposeWhy — score reconstruction (§8.2 identity)", () => {
  it("reconstructs the canonical pick-1 score from its components at kappa=0.6", () => {
    const why = decomposeWhy(PICK1, REASONING, { position: "RB" })!;
    expect(why).not.toBeNull();
    expect(why.reconstructed).toBeCloseTo(42.1, 6);
    expect(why.score).toBe(42.1);
    expect(Math.abs(why.residual)).toBeLessThan(1e-6);
    expect(why.reconciles).toBe(true);
    expect(why.kappa).toBeCloseTo(0.6);
  });

  it("accepts a bare kappa number as well as the reasoning string", () => {
    const why = decomposeWhy(PICK1, 0.6, { position: "RB" })!;
    expect(why.reconstructed).toBeCloseTo(42.1, 6);
  });

  it("term contributions sum to score and match the identity term-for-term", () => {
    const why = decomposeWhy(PICK1, 0.6, { position: "RB" })!;
    const byKey = Object.fromEntries(why.terms.map((t) => [t.key, t]));
    expect(byKey.mlv!.contribution).toBeCloseTo(33.7);
    expect(byKey.vona!.contribution).toBeCloseTo(7.5); // kappa*max(0,12.5)
    expect(byKey.risk!.contribution).toBeCloseTo(-2.1); // -risk_penalty (floor-tilt penalty)
    expect(byKey.cliff!.contribution).toBeCloseTo(3.4);
    expect(byKey["mod:bye_stack"]!.contribution).toBeCloseTo(-0.4);
    const sum = why.terms.reduce((a, t) => a + t.contribution, 0);
    expect(sum).toBeCloseTo(42.1, 6);
  });

  it("clamps VONA at 0 (never a negative contribution)", () => {
    const negVona: RecommendedPick = {
      ...PICK1,
      components: { ...PICK1.components!, vona: -8.0 },
    };
    const why = decomposeWhy(negVona, 0.6, { position: "RB" })!;
    const vona = why.terms.find((t) => t.key === "vona")!;
    expect(vona.contribution).toBe(0);
    expect(vona.anchor).toBe("left");
    expect(vona.rawComponent).toBe(-8.0); // raw is preserved for the detail line
  });

  it("renders the risk term diverging: penalty (lambda>0) is red/critical", () => {
    const why = decomposeWhy(PICK1, 0.6, { position: "RB" })!;
    const risk = why.terms.find((t) => t.key === "risk")!;
    expect(risk.anchor).toBe("diverging");
    expect(risk.contribution).toBeLessThan(0);
    expect(risk.colorRole).toBe("critical");
  });

  it("renders a ceiling-tilt risk bonus (lambda<0) as a positive pine contribution", () => {
    const ceil: RecommendedPick = {
      ...PICK1,
      components: { ...PICK1.components!, risk_penalty: -1.5 },
    };
    const risk = decomposeWhy(ceil, 0.6)!.terms.find((t) => t.key === "risk")!;
    expect(risk.contribution).toBeCloseTo(1.5);
    expect(risk.colorRole).toBe("pine");
  });

  it("colors MLV by position and marks the dominant term", () => {
    const why = decomposeWhy(PICK1, 0.6, { position: "RB" })!;
    const mlv = why.terms.find((t) => t.key === "mlv")!;
    expect(mlv.colorRole).toBe("pos");
    expect(mlv.barFraction).toBeCloseTo(1.0); // largest magnitude -> full bar
    expect(why.dominantKey).toBe("mlv");
  });

  it("drops zero-valued modifiers from the rendered terms", () => {
    const why = decomposeWhy(PICK1, 0.6)!;
    expect(why.terms.some((t) => t.key === "mod:handcuff_synergy")).toBe(false);
    expect(why.terms.some((t) => t.key === "mod:bye_stack")).toBe(true);
  });

  it("flags non-reconciliation when the stored score does not match the components", () => {
    const tampered: RecommendedPick = { ...PICK1, score: 99.9 };
    const why = decomposeWhy(tampered, 0.6)!;
    expect(why.reconciles).toBe(false);
    expect(Math.abs(why.residual)).toBeGreaterThan(1);
  });

  it("returns null when the pick has no components (pre-v1 payload)", () => {
    const bare: RecommendedPick = { player_id: "p1", score: 10 };
    expect(decomposeWhy(bare, 0.6)).toBeNull();
  });
});

describe("whyTermColorVar", () => {
  it("maps a position role to the LOWERCASE --pos-* token (CSS custom props are case-sensitive)", () => {
    // Position values are uppercase ("RB"); the tokens define --pos-rb, not --pos-RB.
    expect(whyTermColorVar("pos", "RB")).toBe("var(--pos-rb)");
    expect(whyTermColorVar("pos", "DST")).toBe("var(--pos-dst)");
  });

  it("maps brass to the solid brass token and passes other roles through", () => {
    expect(whyTermColorVar("brass", null)).toBe("var(--brass-solid)");
    expect(whyTermColorVar("critical", null)).toBe("var(--critical)");
    expect(whyTermColorVar("pine", "RB")).toBe("var(--pine)");
  });

  it("falls back to brass when a position role has no position", () => {
    expect(whyTermColorVar("pos", null)).toBe("var(--brass-solid)");
  });
});

describe("formatScore / formatSignedScore", () => {
  it("formatScore is unsigned, one decimal place", () => {
    expect(formatScore(33.7)).toBe("33.7");
    expect(formatScore(0)).toBe("0.0");
  });

  it("formatSignedScore always carries an explicit sign", () => {
    expect(formatSignedScore(3.4)).toBe("+3.4");
    expect(formatSignedScore(0)).toBe("+0.0");
    expect(formatSignedScore(-2.1)).toBe("−2.1");
  });

  it("signs the minus with U+2212 MINUS SIGN, never an ASCII hyphen", () => {
    const s = formatSignedScore(-2.1);
    expect(s.charCodeAt(0)).toBe(0x2212);
    expect(s).not.toContain("-"); // U+002D ASCII hyphen
  });
});

describe("whyTermBar — box geometry + display text (§6.5)", () => {
  const mkTerm = (over: Partial<WhyTerm>): WhyTerm => ({
    key: "cliff",
    label: "Cliff",
    contribution: 0,
    rawComponent: 0,
    anchor: "left",
    colorRole: "pine",
    barFraction: 0,
    ...over,
  });

  it("left-anchors MLV across the full track, unsigned (MLV is a level, not a delta)", () => {
    const b: WhyTermBar = whyTermBar(mkTerm({ key: "mlv", contribution: 33.7, barFraction: 1 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBeCloseTo(100);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("33.7");
  });

  it("signs a non-MLV left-anchored term and scales width over the full track", () => {
    const b = whyTermBar(mkTerm({ key: "cliff", contribution: 3.4, barFraction: 0.5 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBeCloseTo(50);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("+3.4");
  });

  it("anchors a diverging PENALTY to the RIGHT edge so it paints left of the midline (§6.5)", () => {
    const b = whyTermBar(
      mkTerm({
        key: "risk",
        anchor: "diverging",
        contribution: -2.1,
        barFraction: 0.5,
        colorRole: "critical",
      }),
    );
    expect(b.anchorEdge).toBe("right");
    expect(b.offsetPct).toBe(50);
    expect(b.widthPct).toBeCloseTo(25); // barFraction * 50
    expect(b.midlinePct).toBe(50);
    expect(b.displayValue).toBe("−2.1");
  });

  it("anchors a diverging BONUS to the LEFT edge so it paints right of the midline", () => {
    const b = whyTermBar(
      mkTerm({
        key: "risk",
        anchor: "diverging",
        contribution: 1.5,
        barFraction: 0.3,
        colorRole: "pine",
      }),
    );
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(50);
    expect(b.widthPct).toBeCloseTo(15);
    expect(b.midlinePct).toBe(50);
    expect(b.displayValue).toBe("+1.5");
  });

  it("keeps a zero-magnitude bar left-anchored with zero width", () => {
    const b = whyTermBar(mkTerm({ key: "cliff", contribution: 0, barFraction: 0 }));
    expect(b.anchorEdge).toBe("left");
    expect(b.offsetPct).toBe(0);
    expect(b.widthPct).toBe(0);
    expect(b.midlinePct).toBeNull();
    expect(b.displayValue).toBe("+0.0");
  });
});
