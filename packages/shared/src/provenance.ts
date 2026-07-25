/**
 * Projection provenance (plan §5 live-data honesty) — the single rule both surfaces share.
 *
 * `PlayerProjection.sources` records which $0 sources actually backed a player's μ, and it rides
 * every `RecommendedPick` as `projection_sources`. The distinction that matters to the owner:
 * **ECR alone is not a projection.** It is an expert *rank* mapped onto the fallback points curve,
 * so an ECR-only player carries no modeled estimate of anything. On the live board that is ~70
 * players sitting next to 377 with real nflverse xEP, indistinguishable until now.
 *
 * Defined once here so the overlay and the dashboard can never disagree about what "degraded"
 * means.
 */

/** Sources that constitute a real, modeled projection — anything beyond a bare expert rank. */
const RANK_ONLY_SOURCE = "ecr";

const SOURCE_LABELS: Record<string, string> = {
  ecr: "ECR",
  xep: "xEP",
  projections: "CBS on-page",
};

export interface ProjectionProvenance {
  /** True when at least one source is more than an expert rank. */
  modeled: boolean;
  /** Short chip text, e.g. `"ECR + xEP"` or `"ECR only"`. */
  label: string;
  /** One sentence for a tooltip / the Why? panel. */
  detail: string;
  /** The raw source keys, sorted as the engine sent them. */
  sources: string[];
}

function labelFor(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * Classify a pick's `projection_sources`.
 *
 * Returns `null` when provenance is unknown (absent or empty) — the UI must then render nothing
 * rather than guess, because "we don't know" and "we checked and it's degraded" are different
 * claims and only one of them is true.
 */
export function projectionProvenance(
  sources: string[] | null | undefined,
): ProjectionProvenance | null {
  if (!sources || sources.length === 0) return null;

  const modeled = sources.some((s) => s !== RANK_ONLY_SOURCE);
  if (!modeled) {
    return {
      modeled: false,
      label: "ECR only",
      detail:
        "No modeled projection — this player's points are derived from expert rank alone, " +
        "not from measured opportunity.",
      sources: [...sources],
    };
  }
  return {
    modeled: true,
    label: sources.map(labelFor).join(" + "),
    detail: `Projection backed by ${sources.map(labelFor).join(" and ")}.`,
    sources: [...sources],
  };
}
