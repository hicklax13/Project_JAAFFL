/**
 * Pure geometry for the bespoke SVG analytics charts — no React, no DOM, no design tokens.
 *
 * Both panels draw with `<polyline points="x,y x,y ...">` in a fixed viewBox, so all either needs
 * is a domain→viewBox mapping. Keeping it here makes the maths directly unit-testable and keeps the
 * panel components small enough to read at a glance.
 */

export interface Box {
  width: number;
  height: number;
}

/** SVG y grows downward, so a HIGHER value maps to a SMALLER y. */
function project(value: number, min: number, span: number, height: number): number {
  return height - ((value - min) / span) * height;
}

/** Guard every denominator: a degenerate domain must render flat, never NaN. */
function safeSpan(span: number): number {
  return span === 0 ? 1 : span;
}

/** Map (rank, VOR) samples into a polyline. Rank 1 sits at x=0, `maxRank` at x=width. */
export function valuePolyline(
  points: readonly { rank: number; vor: number }[],
  opts: Box & { maxRank: number; minVor: number; maxVor: number },
): string {
  if (points.length === 0) return "";
  const rankSpan = safeSpan(opts.maxRank - 1);
  const vorSpan = safeSpan(opts.maxVor - opts.minVor);
  return points
    .map((p) => {
      const x = ((p.rank - 1) / rankSpan) * opts.width;
      const y = project(p.vor, opts.minVor, vorSpan, opts.height);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

/** Map (pick, survival) samples into a polyline. Survival is already 0..1. */
export function survivalPolyline(
  points: readonly { pick: number; survival: number }[],
  opts: Box & { minPick: number; maxPick: number },
): string {
  if (points.length === 0) return "";
  const pickSpan = safeSpan(opts.maxPick - opts.minPick);
  return points
    .map((p) => {
      const x = ((p.pick - opts.minPick) / pickSpan) * opts.width;
      const y = project(p.survival, 0, 1, opts.height);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

/** Fraction across the x-axis for a pick marker (0..1); clamped so it never escapes the box. */
export function pickOffset(pick: number, minPick: number, maxPick: number): number {
  const span = safeSpan(maxPick - minPick);
  return Math.min(1, Math.max(0, (pick - minPick) / span));
}
