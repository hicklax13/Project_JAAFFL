/**
 * The "why" — binding Score(p) to pixels (plan §6.5, the anti-black-box guarantee).
 *
 * Framework-agnostic reconstruction shared by BOTH surfaces (the Next.js dashboard and
 * the Shadow-DOM overlay) so they render the identical decomposition. Given a
 * RecommendedPick's ScoreComponents and kappa (from EngineParams, echoed in
 * Recommendation.reasoning), it rebuilds the canonical score term-for-term:
 *
 *   score = mlv + kappa*max(0, vona) - risk_penalty + cliff_bonus + sum(modifiers)
 *
 * `risk_penalty` and `cliff_bonus` are stored ALREADY-SCALED and SIGNED (lambda*sigma_hat,
 * alpha*Cliff); `vona` is stored RAW (kappa and the max(0,.) gate are applied here). So a
 * consumer rebuilds `score` from the stored components plus kappa alone — never from lambda
 * or sigma (plan §8.2). Every number the UI shows is one of these contributions; nothing is
 * hidden.
 *
 * Rendering guidance (deep-research, resolved): the dashboard renders these terms as a
 * horizontal WATERFALL (a running additive total with signed steps — the defensible form
 * for an additive decomposition, cf. SHAP's own waterfall view); the compact overlay renders
 * them as diverging component bars. Both consume the same `terms` array below.
 */
import type { Position } from "./league";
import type { RecommendedPick, ScoreComponents } from "./recommendation";

/** Resolved EngineParams echoed once per response in Recommendation.reasoning (§8.3.3). */
export interface EngineParamsView {
  kappa: number | null;
  alpha: number | null;
  lambda: number | null;
  flexSplit: { rb: number; wr: number } | null;
  paramsVersion: string | null;
  raw: string;
}

export type WhyTermKey = "mlv" | "vona" | "risk" | "cliff" | `mod:${string}`;
export type BarAnchor = "left" | "diverging";
export type WhyColorRole = "pos" | "brass" | "critical" | "pine" | "good" | "warning";

export interface WhyTerm {
  key: WhyTermKey;
  label: string;
  /** Signed contribution to `score` (this IS the number the bar/step shows). */
  contribution: number;
  /** The underlying ScoreComponents value (mlv, raw vona, risk_penalty, cliff_bonus, or modifier). */
  rawComponent: number;
  anchor: BarAnchor;
  colorRole: WhyColorRole;
  /** Magnitude 0..1 relative to the largest-magnitude term (drives bar width, one visual system). */
  barFraction: number;
}

export interface WhyDecomposition {
  terms: WhyTerm[];
  /** Sum of every term's contribution — should equal `score`. */
  reconstructed: number;
  score: number;
  residual: number;
  reconciles: boolean;
  /** Key of the largest-magnitude contribution (the term the rationale should foreground). */
  dominantKey: WhyTermKey;
  kappa: number | null;
  /** Position of the pick, so a "pos"-role term maps to `var(--pos-{position})`. */
  position: Position | null;
}

export type EngineParamsSource = number | string | EngineParamsView | null | undefined;

/** Default float tolerance for the score-reconstruction identity (§9.5 / §8.2). */
export const RECONSTRUCTION_TOLERANCE = 0.05;

const NUM = "([+-]?\\d*\\.?\\d+)";

function firstNumber(text: string, ...patterns: RegExp[]): number | null {
  for (const re of patterns) {
    const m = text.match(re);
    if (m && m[1] !== undefined) {
      const n = Number(m[1]);
      if (!Number.isNaN(n)) return n;
    }
  }
  return null;
}

/** Parse the resolved-EngineParams reasoning line (κ, α, λ, flex split, params version). */
export function parseEngineParams(reasoning: string | null | undefined): EngineParamsView {
  const raw = reasoning ?? "";
  if (!raw) {
    return { kappa: null, alpha: null, lambda: null, flexSplit: null, paramsVersion: null, raw: "" };
  }
  const flex = raw.match(/flex_split\s*=\s*(\d+)\s*RB\s*\/\s*(\d+)\s*WR/i);
  const version = raw.match(/EngineParams\s+v([\d.]+)/i);
  return {
    kappa: firstNumber(raw, new RegExp(`(?:κ|kappa)\\s*=\\s*${NUM}`, "i")),
    alpha: firstNumber(raw, new RegExp(`(?:α|alpha)\\s*=\\s*${NUM}`, "i")),
    lambda: firstNumber(raw, new RegExp(`(?:λ|lambda)\\s*=\\s*${NUM}`, "i")),
    flexSplit: flex ? { rb: Number(flex[1]), wr: Number(flex[2]) } : null,
    paramsVersion: version ? version[1]! : null,
    raw,
  };
}

function resolveKappa(source: EngineParamsSource): number | null {
  if (source == null) return null;
  if (typeof source === "number") return source;
  if (typeof source === "string") return parseEngineParams(source).kappa;
  return source.kappa;
}

function humanize(name: string): string {
  const spaced = name.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Decompose a pick's score into its renderable, sign-preserving contributions, and check
 * the reconstruction identity. Returns null when the pick carries no components.
 */
export function decomposeWhy(
  pick: RecommendedPick,
  params: EngineParamsSource,
  opts: { position?: Position; tolerance?: number } = {},
): WhyDecomposition | null {
  const c: ScoreComponents | null | undefined = pick.components;
  if (!c) return null;

  const kappa = resolveKappa(params);
  const k = kappa ?? 1; // best-effort display when kappa is unknown; residual flags it
  const position = opts.position ?? null;

  const riskContribution = -c.risk_penalty; // score SUBTRACTS the stored signed penalty
  const terms: WhyTerm[] = [
    {
      key: "mlv",
      label: "MLV",
      contribution: c.mlv,
      rawComponent: c.mlv,
      anchor: "left",
      colorRole: "pos",
      barFraction: 0,
    },
    {
      key: "vona",
      label: "VONA",
      contribution: k * Math.max(0, c.vona),
      rawComponent: c.vona,
      anchor: "left",
      colorRole: "brass",
      barFraction: 0,
    },
    {
      key: "risk",
      label: "Risk",
      contribution: riskContribution,
      rawComponent: c.risk_penalty,
      anchor: "diverging",
      colorRole: riskContribution < 0 ? "critical" : "pine",
      barFraction: 0,
    },
    {
      key: "cliff",
      label: "Cliff",
      contribution: c.cliff_bonus,
      rawComponent: c.cliff_bonus,
      anchor: "left",
      colorRole: "pine",
      barFraction: 0,
    },
  ];

  for (const [name, value] of Object.entries(c.modifiers ?? {})) {
    if (value === 0) continue; // a zero modifier is not a reason for the pick — don't render it
    terms.push({
      key: `mod:${name}`,
      label: humanize(name),
      contribution: value,
      rawComponent: value,
      anchor: "diverging",
      colorRole: value >= 0 ? "good" : "critical",
      barFraction: 0,
    });
  }

  const maxMag = terms.reduce((m, t) => Math.max(m, Math.abs(t.contribution)), 0);
  for (const t of terms) t.barFraction = maxMag > 0 ? Math.abs(t.contribution) / maxMag : 0;

  const reconstructed = terms.reduce((a, t) => a + t.contribution, 0);
  const residual = pick.score - reconstructed;
  const tolerance = opts.tolerance ?? RECONSTRUCTION_TOLERANCE;
  const dominant = terms.reduce((best, t) =>
    Math.abs(t.contribution) > Math.abs(best.contribution) ? t : best,
  );

  return {
    terms,
    reconstructed,
    score: pick.score,
    residual,
    reconciles: Math.abs(residual) <= tolerance,
    dominantKey: dominant.key,
    kappa,
    position,
  };
}
