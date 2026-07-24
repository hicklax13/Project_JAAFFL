"use client";

import { useState, type CSSProperties, type ReactElement } from "react";

import type { DraftAnalytics, PositionCurve } from "@jaaffl/shared";

import { valuePolyline } from "../lib/curve";

const BOX = { width: 320, height: 120 };

/** Describe the curve in words — the chart's accessible name, never colour-alone (WCAG 1.4.1). */
function describe(curve: PositionCurve): string {
  const best = curve.remaining[0];
  // `remaining` is NOT a suffix/subset of `full`: the backend caps both arrays independently at
  // CURVE_DEPTH, so once more than CURVE_DEPTH players exist at a position (RB/WR, always, in the
  // real nflverse universe), drafting players backfills `remaining` from beyond the original
  // top-CURVE_DEPTH board rather than shrinking it. `full.length - remaining.length` is then ~0
  // regardless of how many were actually drafted. Count by id instead: a `full` entry no longer
  // present in `remaining` was drafted, however `remaining` was backfilled.
  const remainingIds = new Set(curve.remaining.map((p) => p.player_id));
  const taken = curve.full.filter((p) => !remainingIds.has(p.player_id)).length;
  if (!best) return `${curve.position} value curve: every charted player is drafted.`;
  const cliff = curve.remaining[1] ? best.vor - curve.remaining[1].vor : 0;
  return (
    `${curve.position} value curve: best remaining ${best.name ?? best.player_id} at ` +
    `${best.vor.toFixed(0)} points over replacement, ` +
    // "of the top N", not "of N": curve.full.length is the CURVE_DEPTH display cap, not the real
    // position pool size (RB/WR pools run well past it) — the payload never carries the true pool
    // size, so this is the most honest phrasing available client-side.
    `${cliff.toFixed(0)} ahead of the next, ${taken} of the top ${curve.full.length} taken.`
  );
}

/**
 * Positional value curve (§6). VOR against positional rank, one position at a time: the SOLID line
 * is what is still available, the GHOST line behind it is the original preseason board — the gap
 * between them is the positional run. The dashed rule is replacement level (VOR = 0).
 */
export function ValueCurvePanel({ analytics }: { analytics: DraftAnalytics | null }): ReactElement {
  const curves = analytics?.value_curves ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const curve = curves.find((c) => c.position === selected) ?? curves[0];

  if (!curve) {
    return (
      <section className="panel card" aria-labelledby="vc-h">
        <div className="panel-h">
          <h3 className="panel-title" id="vc-h">
            Value curves
          </h3>
        </div>
        <p className="muted">Value curves warm up with the engine.</p>
      </section>
    );
  }

  const all = [...curve.full, ...curve.remaining];
  const maxRank = Math.max(1, ...curve.full.map((p) => p.rank));
  const maxVor = Math.max(...all.map((p) => p.vor), 0);
  const minVor = Math.min(...all.map((p) => p.vor), 0);
  const scale = { ...BOX, maxRank, minVor, maxVor };
  // Replacement level (VOR = 0) in viewBox coordinates.
  const zeroY = BOX.height - ((0 - minVor) / (maxVor - minVor || 1)) * BOX.height;

  return (
    <section className="panel card" aria-labelledby="vc-h">
      <div className="panel-h">
        <h3 className="panel-title" id="vc-h">
          Value curves
        </h3>
        <span className="panel-note">points over replacement</span>
      </div>

      <div className="vc-chips" role="group" aria-label="Charted position">
        {curves.map((c) => (
          <button
            key={c.position}
            type="button"
            className="vc-chip"
            aria-pressed={c.position === curve.position}
            onClick={() => setSelected(c.position)}
            style={{ "--chip-hue": `var(--pos-${c.position.toLowerCase()})` } as CSSProperties}
          >
            {c.position}
          </button>
        ))}
      </div>

      <svg
        className="vc-chart"
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-label={describe(curve)}
        preserveAspectRatio="none"
      >
        <line
          className="vc-replacement"
          x1="0"
          y1={zeroY}
          x2={BOX.width}
          y2={zeroY}
          strokeDasharray="4 3"
        />
        <polyline className="vc-ghost" points={valuePolyline(curve.full, scale)} />
        <polyline
          className="vc-line"
          points={valuePolyline(curve.remaining, scale)}
          style={{ stroke: `var(--pos-${curve.position.toLowerCase()})` }}
        />
      </svg>

      <p className="vc-legend muted">
        Solid = still available · faint = preseason board · dashed = replacement
      </p>
    </section>
  );
}
