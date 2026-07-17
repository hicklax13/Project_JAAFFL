/**
 * Next-turn survival semantics (plan §6.3) — the SINGLE source both surfaces render, so the
 * dashboard and the overlay can never disagree on "what counts as scarce." Given
 * `next_turn_availability` (the analytic Gaussian probability the engine already computed that a
 * player is still on the board at your next pick), it returns the tier's glyph + word + colours.
 *
 * Identity is NEVER colour-alone: every tier carries a distinct glyph AND word (WCAG 1.4.1), so
 * `colorVar` (bar/text surfaces) and `statusClass` (pill surfaces) are always paired with copy.
 */

export type SurvivalLevel = "safe" | "contested" | "scarce";

export interface SurvivalOutlook {
  level: SurvivalLevel;
  /** Filled-circle glyph conveying the tier without colour. */
  glyph: string;
  /** The one canonical advisory word for this tier (can wait → watch → take now). */
  word: string;
  /** Status-pill class (the overlay pill + dashboard badge). */
  statusClass: "is-good" | "is-warning" | "is-critical";
  /** Design-token colour var for bar fills / mono text (the survival panel). */
  colorVar: string;
}

const SAFE: SurvivalOutlook = {
  level: "safe",
  glyph: "◗",
  word: "can wait",
  statusClass: "is-good",
  colorVar: "var(--good)",
};
const CONTESTED: SurvivalOutlook = {
  level: "contested",
  glyph: "◐",
  word: "watch",
  statusClass: "is-warning",
  colorVar: "var(--warning)",
};
const SCARCE: SurvivalOutlook = {
  level: "scarce",
  glyph: "●",
  word: "take now",
  statusClass: "is-critical",
  colorVar: "var(--critical)",
};

/** Classify a next-turn survival probability into its renderable tier (thresholds inclusive). */
export function survivalOutlook(probability: number): SurvivalOutlook {
  if (probability >= 0.55) return SAFE;
  if (probability >= 0.4) return CONTESTED;
  return SCARCE;
}

/** Format a 0..1 probability as a whole-percent string (`0.18` → `"18%"`). */
export function formatPct(probability: number): string {
  return `${Math.round(probability * 100)}%`;
}
