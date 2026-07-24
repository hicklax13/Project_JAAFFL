import type { ReactElement } from "react";

import {
  type DraftAnalytics,
  formatPct,
  type SurvivalCurve,
  survivalOutlook,
} from "@jaaffl/shared";

import { pickOffset, survivalPolyline } from "../lib/curve";

const BOX = { width: 640, height: 180 };

/**
 * Survival at your next pick — the number the legend reports and the tier it maps to. Falls back
 * to the LAST charted point when `pick` is unknown (no next pick yet, i.e. draft order not read),
 * which silently changes what the number means (survival "at your next pick" vs "at the end of the
 * charted span"). Every caller that surfaces this value MUST also surface which meaning applies —
 * see `hasNextPick` / `chartLabel` in `SurvivalCurvePanel` below.
 */
function atPick(curve: SurvivalCurve, pick: number | undefined): number {
  if (pick == null) return curve.points[curve.points.length - 1]?.survival ?? 0;
  const exact = curve.points.find((p) => p.pick === pick);
  return exact?.survival ?? curve.points[curve.points.length - 1]?.survival ?? 0;
}

/**
 * Survival curves (§6.3 / §3.4): P(each candidate is still on the board) across upcoming picks,
 * with dashed markers at YOUR next picks — read from the real entered draft order, never inferred.
 * The curve SHAPE is the point: flat to your marker means you can wait; a cliff before it means
 * take him now. Tier words come from the shared survivalOutlook, so this panel and the overlay can
 * never disagree about who is scarce.
 */
export function SurvivalCurvePanel({
  analytics,
}: {
  analytics: DraftAnalytics | null;
}): ReactElement {
  const curves = analytics?.survival_curves ?? [];
  const markers = analytics?.my_next_picks ?? [];

  if (curves.length === 0) {
    return (
      <section className="panel card sc-panel" aria-labelledby="sc-h">
        <div className="panel-h">
          <h3 className="panel-title" id="sc-h">
            Survival curves
          </h3>
        </div>
        <p className="muted">Survival curves appear once the draft starts.</p>
      </section>
    );
  }

  // Derive the pick domain from every charted point across ALL curves, not just curves[0]: a
  // candidate curve can legitimately have zero points (Math.min(...[]) is Infinity, not a usable
  // domain), and curves are not guaranteed to be perfectly aligned even though the backend builds
  // them over one shared pick range in practice. Unioning satisfies curve.ts's stated invariant
  // (derive the domain from the SAME points being plotted) for every polyline drawn below.
  const allPicks = curves.flatMap((c) => c.points.map((p) => p.pick));
  const minPick = allPicks.length > 0 ? Math.min(...allPicks) : 0;
  const maxPick = allPicks.length > 0 ? Math.max(...allPicks) : 1;
  const nextPick = markers[0];
  // Whether every percentage below genuinely means "at your next pick" (true) or has fallen back
  // to "at the end of the charted span" (false) — see the `atPick` docstring. Both the visible
  // panel note and the chart's accessible name must say so; a bare percentage must never silently
  // change meaning (this project's honesty bar, not just a WCAG nicety).
  const hasNextPick = nextPick != null;
  const perCandidate = curves
    .map((c) => `${c.name ?? c.player_id} ${formatPct(atPick(c, nextPick))}`)
    .join(", ");
  const chartLabel = hasNextPick
    ? `Survival to each upcoming pick for ${perCandidate}`
    : `Survival across the charted picks (draft order not yet known) for ${perCandidate}`;

  return (
    <section className="panel card sc-panel" aria-labelledby="sc-h">
      <div className="panel-h">
        <h3 className="panel-title" id="sc-h">
          Survival curves
        </h3>
        <span className="panel-note">
          {hasNextPick
            ? `your picks: ${markers.join(", ")}`
            : "draft order unknown — showing survival across the charted picks"}
        </span>
      </div>

      <svg
        className="sc-chart"
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-label={chartLabel}
        preserveAspectRatio="none"
      >
        {markers.map((pick) => {
          const x = pickOffset(pick, minPick, maxPick) * BOX.width;
          return (
            <line
              className="sc-marker"
              key={pick}
              x1={x}
              y1={0}
              x2={x}
              y2={BOX.height}
              strokeDasharray="4 3"
            />
          );
        })}
        {curves.map((curve) => (
          <polyline
            className="sc-line"
            key={curve.player_id}
            points={survivalPolyline(curve.points, { ...BOX, minPick, maxPick })}
            style={{ stroke: `var(--pos-${(curve.position ?? "wr").toLowerCase()})` }}
          />
        ))}
      </svg>

      <ul className="sc-legend" role="list">
        {curves.map((curve) => {
          const probability = atPick(curve, nextPick);
          const outlook = survivalOutlook(probability);
          return (
            <li className="sc-legend-row" key={curve.player_id}>
              <span
                className="sc-swatch"
                aria-hidden="true"
                style={{ background: `var(--pos-${(curve.position ?? "wr").toLowerCase()})` }}
              />
              <span className="sc-name">{curve.name ?? curve.player_id}</span>
              <span className="mono">{formatPct(probability)}</span>
              <span className={`stat-pill ${outlook.statusClass}`}>
                {outlook.glyph} {outlook.word}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
