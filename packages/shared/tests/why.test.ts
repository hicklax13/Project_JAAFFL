/**
 * The "why" reconstruction primitive (plan §6.5 / §8.2). Uses the canonical §8.3.3
 * response examples, whose reconstruction identity the plan states explicitly:
 *   pick 1 (kappa=0.6): 33.7 + 0.6*12.5 - 2.1 + 3.4 + (-0.4) = 42.1
 *   pick 2 (kappa=0.6): 34.9 + 0.6*6.2  - 1.8 + 2.6 + 0      = 39.4
 */
import { describe, expect, it } from "vitest";

import type { RecommendedPick } from "../src/recommendation";
import { decomposeWhy, parseEngineParams } from "../src/why";

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
