import type { ReactElement } from "react";

import { formatPct, type RecommendedPick, survivalOutlook } from "@jaaffl/shared";

import { PositionChip, playerName } from "./recommendation-banner";

/**
 * Next-turn survival — the probability each top candidate is still on the board at your next
 * pick (§6.3). Rendered as accessible probability bars from next_turn_availability (the analytic
 * Gaussian value the engine already computed); the full S_j(N)-over-pick curve needs the ADP
 * mean+SD series, a precompute enrichment. Never color-alone: every bar carries its % and word.
 */
export function SurvivalPanel({ ranked }: { ranked: RecommendedPick[] }): ReactElement {
  const rows = ranked.filter((p) => p.next_turn_availability != null).slice(0, 6);
  return (
    <section className="panel card" aria-labelledby="surv-h">
      <div className="panel-h">
        <h3 className="panel-title" id="surv-h">
          Next-turn survival
        </h3>
        <span className="panel-note">to your next pick</span>
      </div>
      <ul
        className="surv-list"
        role="img"
        aria-label={`Survival to your next pick: ${rows
          .map((p) => `${playerName(p)} ${formatPct(p.next_turn_availability!)}`)
          .join(", ")}`}
      >
        {rows.map((p) => {
          const prob = p.next_turn_availability!;
          const color = survivalOutlook(prob).colorVar;
          return (
            <li className="surv-row" key={p.player_id}>
              <PositionChip position={p.position} />
              <span className="surv-name">{playerName(p)}</span>
              <div className="surv-track" aria-hidden="true">
                <span className="surv-fill" style={{ width: `${prob * 100}%`, background: color }} />
              </div>
              <span className="surv-pct mono" style={{ color }}>
                {formatPct(prob)}
              </span>
            </li>
          );
        })}
        {rows.length === 0 && <li className="muted">Survival appears once the board fills in.</li>}
      </ul>
    </section>
  );
}

/**
 * Tier board — groups the visible candidates by their Boris-Chen GMM tier and shows the score
 * cliff between tiers (the α·CliffBonus intuition). Derived from the ranked picks' `tier`.
 */
export function TierLadder({ ranked }: { ranked: RecommendedPick[] }): ReactElement {
  const withTier = ranked.filter((p) => p.tier != null);
  const tiers = [...new Set(withTier.map((p) => p.tier!))].sort((a, b) => a - b);
  return (
    <section className="panel card" aria-labelledby="tier-h">
      <div className="panel-h">
        <h3 className="panel-title" id="tier-h">
          Tiers &amp; cliffs
        </h3>
      </div>
      <div className="tier-ladder">
        {tiers.map((tier, idx) => {
          const group = withTier.filter((p) => p.tier === tier);
          const nextGroup = withTier.filter((p) => p.tier === tiers[idx + 1]);
          const cliff =
            group.length && nextGroup.length
              ? group[group.length - 1]!.score - nextGroup[0]!.score
              : null;
          return (
            <div className="tier-group" key={tier}>
              <div className="tier-head">
                <span className="eyebrow">Tier {tier}</span>
              </div>
              <ul role="list" className="tier-players">
                {group.map((p) => (
                  <li className="tier-player" key={p.player_id}>
                    <PositionChip position={p.position} />
                    <span className="tier-name">{playerName(p)}</span>
                    <span className="mono">{p.score.toFixed(1)}</span>
                  </li>
                ))}
              </ul>
              {cliff != null && cliff > 0 && (
                <div className="tier-cliff">
                  <span className="stat-pill is-critical" aria-label={`Tier cliff of ${cliff.toFixed(1)} points to Tier ${tiers[idx + 1]}`}>
                    ▾ {cliff.toFixed(1)} cliff
                  </span>
                </div>
              )}
            </div>
          );
        })}
        {tiers.length === 0 && <li className="muted">Tiers appear with the candidate pool.</li>}
      </div>
    </section>
  );
}
