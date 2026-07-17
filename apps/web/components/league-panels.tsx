import type { ReactElement } from "react";

import { type LeagueSettings, parseEngineParams } from "@jaaffl/shared";

import type { RecsSocketState } from "../lib/api";

export type HydrateError = "unknown-league" | "not-started" | "warming-up" | "offline" | null;

/** Verbatim league badges — the immutable constitution rendered read-only (§6.9, never editable). */
export function SettingsBadges({ league }: { league: LeagueSettings | null }): ReactElement {
  const rounds = league?.roster_slots?.reduce((n, s) => n + s.count, 0) ?? 17;
  const teams = league?.team_count ?? 12;
  const type = league?.draft_type ?? "snake";
  return (
    <div className="badges" role="list" aria-label="League format">
      <span className="chip" role="listitem" style={{ textTransform: "capitalize" }}>
        {type} · 17 rd
      </span>
      <span className="chip" role="listitem">
        {teams}-team
      </span>
      <span className="chip" role="listitem">
        Standard · non-PPR
      </span>
      <span className="chip" role="listitem">
        {rounds} rounds
      </span>
      <span className="chip" role="listitem" title="Read live from the CBS room — never inferred from team count">
        Order: in-person → CBS
      </span>
    </div>
  );
}

const SLOT_LABEL: Record<string, string> = {
  QB: "QB",
  RB: "RB",
  WR: "WR",
  "WR/RB": "W/R flex",
  TE: "TE",
  K: "K",
  DST: "DST",
  BENCH: "Bench",
};

/** Roster by slot, verbatim (QB 1 · RB 1 · WR 3 · WR/RB 1 · TE 1 · K 1 · DST 1 · Bench 8). The
 * WR/RB flex is WR-or-RB only (§6.9) — surfaced from eligible_positions, never assumed. */
export function RosterRail({ league }: { league: LeagueSettings | null }): ReactElement {
  const slots = league?.roster_slots ?? [];
  return (
    <section className="panel card" aria-labelledby="roster-h">
      <div className="panel-h">
        <h3 className="panel-title" id="roster-h">
          Roster
        </h3>
        <span className="panel-note mono">9 start · 8 bench</span>
      </div>
      <ul className="roster-list" role="list">
        {slots.map((s) => (
          <li className="roster-slot" key={s.slot}>
            <span className="slot-name">{SLOT_LABEL[s.slot] ?? s.slot}</span>
            <span className="slot-count mono">{s.count}</span>
            {s.slot === "WR/RB" && (
              <span className="slot-note">{s.eligible_positions.join(" or ")} only</span>
            )}
          </li>
        ))}
        {slots.length === 0 && <li className="muted">Awaiting league settings…</li>}
      </ul>
    </section>
  );
}

/** The resolved EngineParams line (§8.3.3) — so any consumer can reconstruct score from the
 * components — plus the honesty note that forward-year figures are ESTIMATED. */
export function ReasoningLine({ reasoning }: { reasoning?: string | null }): ReactElement | null {
  if (!reasoning) return null;
  const p = parseEngineParams(reasoning);
  return (
    <div className="reasoning" role="note" aria-label="Resolved engine parameters">
      <span className="eyebrow">Engine</span>
      <span className="mono reasoning-params">
        {p.kappa != null && `κ=${p.kappa} `}
        {p.alpha != null && `· α=${p.alpha} `}
        {p.lambda != null && `· λ=${p.lambda >= 0 ? "+" : ""}${p.lambda} `}
        {p.flexSplit && `· flex ${p.flexSplit.rb}RB/${p.flexSplit.wr}WR `}
        {p.paramsVersion && `· v${p.paramsVersion}`}
      </span>
      <span className="reasoning-full">{reasoning}</span>
      <span className="chip est-note" title="No proven optimal live-snake-draft solver exists; efficacy is offline-validated">
        Forward-year figures are ESTIMATED
      </span>
    </div>
  );
}

/** The live sync/connection state (§6.6): waiting · live · stale · disconnected · 404/409/503. */
export function StatusBanner({
  socket,
  hydrateError,
  syncedAgoMs,
  hasRec,
}: {
  socket: RecsSocketState;
  hydrateError: HydrateError;
  syncedAgoMs: number | null;
  hasRec: boolean;
}): ReactElement {
  let cls = "is-good";
  let glyph = "●";
  let text: string;

  const ago = syncedAgoMs == null ? null : `${(syncedAgoMs / 1000).toFixed(1)}s ago`;
  const stale = syncedAgoMs != null && syncedAgoMs > 3000;

  if (hydrateError === "unknown-league") {
    cls = "is-critical";
    text = "Unknown league — check the league id (404)";
  } else if (hydrateError === "not-started") {
    cls = "is-warning";
    text = "Draft hasn't started — watching the board (409)";
  } else if (hydrateError === "warming-up") {
    cls = "is-warning";
    text = "Engine warming up — precompute in progress (503)";
  } else if (hydrateError === "offline") {
    cls = "is-critical";
    text = "Companion service unreachable at 127.0.0.1:8788";
  } else if (socket === "closed" || socket === "reconnecting") {
    cls = "is-warning";
    glyph = "◌";
    text = socket === "reconnecting" ? "Reconnecting…" : "Disconnected";
  } else if (!hasRec) {
    cls = "is-warning";
    text = "Watching the board — no picks yet";
  } else if (stale) {
    cls = "is-warning";
    text = `Stale · synced ${ago}`;
  } else {
    text = ago ? `Live · CBS synced · ${ago}` : "Live · CBS synced";
  }

  return (
    <span className={`stat-pill ${cls}`} role="status" aria-live="polite">
      {glyph} {text}
    </span>
  );
}

/** League scoring panel (§6.4): the exact CBS Standard map — DST dual tiers + K 50+ bonus — plus
 * the $0 data-provenance chips so the user sees where each number came from. */
export function ScoringPanel({ league }: { league: LeagueSettings | null }): ReactElement {
  const tiers = league?.scoring_tiers ?? [];
  const bonuses = league?.scoring_bonuses ?? [];
  return (
    <section className="panel card" aria-labelledby="scoring-h">
      <div className="panel-h">
        <h3 className="panel-title" id="scoring-h">
          League scoring — Standard (non-PPR)
        </h3>
      </div>
      {tiers.map((t) => (
        <div className="scoring-tier" key={t.stat}>
          <span className="eyebrow">{t.stat.replaceAll("_", " ")}</span>
          <div className="tier-brackets mono">
            {t.brackets.map((b, i) => (
              <span className="bracket" key={i}>
                {b.lower}
                {b.upper == null ? "+" : `–${b.upper}`}: {b.points > 0 ? `+${b.points}` : b.points}
              </span>
            ))}
          </div>
        </div>
      ))}
      {bonuses.map((b) => (
        <div className="scoring-bonus mono" key={b.stat}>
          {b.stat.replaceAll("_", " ")} ≥ {b.threshold}: +{b.points}
        </div>
      ))}
      {tiers.length === 0 && bonuses.length === 0 && (
        <p className="muted">Scoring map loads with the league (CBS values behind capture).</p>
      )}
      <div className="provenance" aria-label="Data provenance ($0 tier)">
        <span className="chip">nflreadpy</span>
        <span className="chip">FFC ADP</span>
        <span className="chip">CBS on-page</span>
      </div>
    </section>
  );
}
