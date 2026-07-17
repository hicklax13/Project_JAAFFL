import type { ReactElement } from "react";

import {
  formatPct,
  type Position,
  type RecommendedPick,
  survivalOutlook,
} from "@jaaffl/shared";

import { WhyPanel } from "./why-panel";

/** A position chip — identity is never color-alone; the letter always rides with the hue. */
export function PositionChip({ position }: { position?: Position | null }): ReactElement | null {
  if (!position) return null;
  return <span className={`pos pos-${position}`}>{position}</span>;
}

/** Next-turn survival badge — icon + word + color (never color-alone), per §6.3. */
export function SurvivalBadge({
  probability,
}: {
  probability?: number | null;
}): ReactElement | null {
  if (probability == null) return null;
  const { glyph, word, statusClass } = survivalOutlook(probability);
  return (
    <span
      className={`stat-pill ${statusClass}`}
      aria-label={`${formatPct(probability)} survives to your next pick — ${word}`}
    >
      {glyph} {formatPct(probability)} survives
    </span>
  );
}

export function playerName(pick: RecommendedPick): string {
  return pick.name ?? pick.player_id;
}

function subline(pick: RecommendedPick): string {
  const parts: string[] = [];
  if (pick.nfl_team) parts.push(pick.nfl_team);
  if (pick.bye_week != null) parts.push(`bye ${pick.bye_week}`);
  if (pick.components) parts.push(`replacement baseline ${pick.components.replacement_baseline.toFixed(0)}`);
  return parts.join(" · ");
}

export interface RecommendationBannerProps {
  best: RecommendedPick;
  reasoning?: string | null;
}

/** The single call — best pick + score in brass + the decomposed "why" + advisory actions.
 * The primary action is ADVISORY (copies the name / pins intent locally); it NEVER submits a
 * pick to CBS (§6.0). The human makes the pick in the CBS UI. */
export function RecommendationBanner({ best, reasoning }: RecommendationBannerProps): ReactElement {
  const name = playerName(best);
  return (
    <section className="reco card" aria-labelledby="reco-name">
      <div className="reco-head">
        <span className="eyebrow">Recommended · on the clock</span>
        <SurvivalBadge probability={best.next_turn_availability} />
      </div>
      <div className="reco-who">
        <PositionChip position={best.position} />
        <div className="reco-id">
          <div className="name" id="reco-name">
            {name}
          </div>
          <div className="reco-sub mono">{subline(best)}</div>
        </div>
        <div className="reco-score">
          <span className="eyebrow" style={{ display: "block" }}>
            Score
          </span>
          <b className="mono">{best.score.toFixed(1)}</b>
        </div>
      </div>

      <div className="reco-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void navigator.clipboard?.writeText(name)}
          title="Advisory only — copies the name; the overlay never submits a pick to CBS"
        >
          Copy name
        </button>
        <button type="button" className="btn" aria-label={`Explain why ${name} is recommended`}>
          Why?
        </button>
      </div>

      <hr className="rule-brass" />
      <WhyPanel pick={best} params={reasoning ?? null} position={best.position ?? undefined} />

      {best.rationale && (
        <p className="reco-rationale" style={{ fontSize: "var(--fs-xs)", color: "var(--ink-2)" }}>
          {best.rationale}
        </p>
      )}
    </section>
  );
}

/** The next best — top-5 ranked rows (rank · pos · name · score · survival %). */
export function TopFive({ ranked }: { ranked: RecommendedPick[] }): ReactElement {
  const alts = ranked.slice(1, 6);
  return (
    <section className="alts card" aria-label="Next best — top five by Score">
      <div className="panel-h">
        <h3 className="panel-title">Next best — top 5</h3>
        <span className="chip">by Score</span>
      </div>
      <ol className="alt-list" role="list">
        {alts.map((p, i) => (
          <li className="alt" key={p.player_id}>
            <span className="rk mono">{i + 2}</span>
            <PositionChip position={p.position} />
            <span className="nm">
              {playerName(p)}
              {p.nfl_team && <small> {p.nfl_team}</small>}
            </span>
            <span className="rt">
              <span className="sc mono">{p.score.toFixed(1)}</span>
              {p.next_turn_availability != null && (
                <span className="sv mono"> · {formatPct(p.next_turn_availability)}</span>
              )}
            </span>
          </li>
        ))}
        {alts.length === 0 && <li className="muted">No alternatives yet.</li>}
      </ol>
    </section>
  );
}
