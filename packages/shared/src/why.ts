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
 * Rendering guidance (plan §6.5, resolved): BOTH surfaces render these terms as component bars —
 * left-anchored for MLV/VONA/Cliff, diverging around zero for Risk and signed modifiers. The
 * Next.js dashboard (`TermRow`) and the Shadow-DOM overlay (`whyRow`) are pure renderers of the
 * same `terms` array AND the same `whyTermBar` geometry + `whyTermColorVar` colour helpers below,
 * so "one visual system" holds by construction, not convention.
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
    return {
      kappa: null,
      alpha: null,
      lambda: null,
      flexSplit: null,
      paramsVersion: null,
      raw: "",
    };
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
 * Map a term's color role to a design-token CSS variable, shared by both surfaces so the "why"
 * bars colour identically. NOTE: CSS custom-property names are case-sensitive and the tokens are
 * lowercase (`--pos-rb`), while Position values are uppercase (`"RB"`) — so a "pos" role MUST
 * lowercase the position or the fill silently fails to resolve. Identity is never colour-alone;
 * every term also carries its label + signed number.
 */
export function whyTermColorVar(role: WhyColorRole, position: Position | null): string {
  if (role === "pos") {
    return position ? `var(--pos-${position.toLowerCase()})` : "var(--brass-solid)";
  }
  return `var(--${role === "brass" ? "brass-solid" : role})`;
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

export type WhyBarEdge = "left" | "right";

/** Pure render geometry + display text for one WhyTerm — the single source both surfaces consume. */
export interface WhyTermBar {
  /** CSS edge to pin the fill to — NOT the visual side. A diverging penalty pins `right` so it
   *  grows leftward (§6.5 penalty = left/red); naming it a "side" invites an inverted "fix". */
  anchorEdge: WhyBarEdge;
  /** Percent offset of the pinned edge within `.sc-track` (0 for left-anchored, 50 for diverging). */
  offsetPct: number;
  /** Fill width as a percent of the track. */
  widthPct: number;
  /** Percent offset of the `.sc-mid` zero tick, or null when the term has no zero crossing. */
  midlinePct: number | null;
  /** The label-adjacent number: MLV unsigned (a level), every other term signed (a delta). */
  displayValue: string;
}

const DIVERGING_MIDPOINT_PCT = 50;
const FULL_TRACK_PCT = 100;

/** Unsigned, one decimal — for levels (MLV) and the reconstructed total. */
export const formatScore = (n: number): string => n.toFixed(1);

/** Explicitly signed, one decimal — for deltas (every non-MLV term, residual, modifier chips).
 *  The minus is U+2212 MINUS SIGN, not an ASCII hyphen; why.test.ts pins this by codepoint. */
export const formatSignedScore = (n: number): string =>
  `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;

/**
 * Translate a decomposed term into the box geometry + display string both surfaces render, so a
 * rescale is a one-file edit and the geometry is unit-testable. The `.sc-mid` tick, the diverging
 * fill's anchor offset, and its max width are all `DIVERGING_MIDPOINT_PCT` because they encode one
 * fact: zero sits at the track's centre.
 */
export function whyTermBar(term: WhyTerm): WhyTermBar {
  const displayValue =
    term.key === "mlv" ? formatScore(term.contribution) : formatSignedScore(term.contribution);

  if (term.anchor === "diverging") {
    return {
      anchorEdge: term.contribution < 0 ? "right" : "left",
      offsetPct: DIVERGING_MIDPOINT_PCT,
      widthPct: term.barFraction * DIVERGING_MIDPOINT_PCT,
      midlinePct: DIVERGING_MIDPOINT_PCT,
      displayValue,
    };
  }
  return {
    anchorEdge: "left",
    offsetPct: 0,
    widthPct: term.barFraction * FULL_TRACK_PCT,
    midlinePct: null,
    displayValue,
  };
}
