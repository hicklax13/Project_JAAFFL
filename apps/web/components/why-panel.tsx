import type { CSSProperties, ReactElement } from "react";

import {
  decomposeWhy,
  type EngineParamsSource,
  formatScore,
  formatSignedScore,
  type Position,
  type RecommendedPick,
  type WhyTerm,
  whyTermBar,
  whyTermColorVar,
} from "@jaaffl/shared";

export interface WhyPanelProps {
  pick: RecommendedPick;
  /** kappa (number) or the resolved-EngineParams reasoning line (string) to reconstruct from. */
  params: EngineParamsSource;
  position?: Position;
}

function TermRow({ term, position }: { term: WhyTerm; position: Position | null }): ReactElement {
  const bar = whyTermBar(term);
  const fill: CSSProperties = {
    width: `${bar.widthPct}%`,
    background: whyTermColorVar(term.colorRole, position),
  };
  fill[bar.anchorEdge] = `${bar.offsetPct}%`;
  return (
    <div className="sc-row">
      <span className="label" style={{ textTransform: "none", letterSpacing: ".02em" }}>
        {term.label}
      </span>
      <div className="sc-track" role="presentation">
        {bar.midlinePct !== null && <span className="sc-mid" style={{ left: `${bar.midlinePct}%` }} />}
        <span className="sc-fill" style={fill} />
      </div>
      <span className="mono" data-testid={`why-term-${term.key}`} style={{ fontSize: "var(--fs-xs)" }}>
        {bar.displayValue}
      </span>
    </div>
  );
}

/**
 * Binds Score(p) to pixels (plan §6.5): renders each contribution as a design-system bar and
 * proves on screen that MLV + kappa*max(0,VONA) - risk + cliff + modifiers reconstructs the
 * total. When a rec carries no components (pre-v1 payload) it degrades to an honest note
 * rather than inventing a decomposition.
 */
export function WhyPanel({ pick, params, position }: WhyPanelProps): ReactElement {
  const why = decomposeWhy(pick, params, { position });
  if (!why) {
    return (
      <div className="why" data-testid="why-panel">
        <p className="muted" style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
          Decomposition unavailable — this recommendation carries no score components.
        </p>
      </div>
    );
  }

  const core = why.terms.filter((t) => !t.key.startsWith("mod:"));
  const mods = why.terms.filter((t) => t.key.startsWith("mod:"));
  const reconcileLabel = why.reconciles
    ? `Reconstructs to ${formatScore(why.score)} from its components`
    : `Warning: does not reconstruct to ${formatScore(why.score)} (residual ${formatSignedScore(why.residual)})`;

  return (
    <div
      className="why"
      role="group"
      aria-label="The why — Score components"
      data-testid="why-panel"
    >
      <div className="stack" style={{ display: "flex", flexDirection: "column", gap: "9px" }}>
        {core.map((term) => (
          <TermRow key={term.key} term={term} position={why.position} />
        ))}
      </div>

      {mods.length > 0 && (
        <div
          className="mods"
          style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "10px" }}
        >
          {mods.map((term) => (
            <span
              key={term.key}
              className={`stat-pill ${term.contribution >= 0 ? "is-good" : "is-critical"}`}
              data-testid={`why-term-${term.key}`}
            >
              {term.label} {formatSignedScore(term.contribution)}
            </span>
          ))}
        </div>
      )}

      <hr className="rule" style={{ margin: "12px 0 10px" }} />

      <div
        className="sc-row why-total-row"
        style={{ alignItems: "baseline" }}
        data-testid="why-total"
      >
        <span className="label" style={{ textTransform: "none", letterSpacing: ".02em" }}>
          Score
        </span>
        <span
          className="mono"
          aria-label={reconcileLabel}
          title={reconcileLabel}
          style={{ color: why.reconciles ? "var(--good)" : "var(--critical)" }}
        >
          {why.reconciles ? "✓ reconstructs" : "⚠ mismatch"}
        </span>
        <b
          className="mono"
          style={{ fontSize: "var(--fs-md)", color: "var(--brass)", justifySelf: "end" }}
        >
          {formatScore(why.score)}
        </b>
      </div>
    </div>
  );
}
