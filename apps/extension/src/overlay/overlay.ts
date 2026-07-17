/**
 * The in-draft overlay (plan §6.3) — the primary surface. Mounted by the ISOLATED content script
 * inside `attachShadow({mode:"open"})` so CBS styles never leak in or out. It renders the
 * recommended pick, the decomposed "why" (bound to ScoreComponents), next-turn survival, and the
 * top-5, and subscribes to WS /recs/ws for live pushes (hello -> snapshot -> rec, resync on drop).
 *
 * ADVISORY & read-only (§6.0): the primary action copies the name / pins intent to the local log;
 * it NEVER submits a pick to CBS. Built with plain DOM methods only (no innerHTML) so nothing the
 * page or a payload contains can ever become markup. Fully self-contained ($0 / no CDN): the design
 * tokens are inlined from the generated single-source module.
 */
import {
  decomposeWhy,
  type DraftEvent,
  formatPct,
  type Position,
  type Recommendation,
  type RecommendedPick,
  survivalOutlook,
  type WhyTerm,
  whyTermColorVar,
} from "@jaaffl/shared";

import { subscribeRecs, type RecsSyncState, type WebSocketLike } from "../lib/recs";
import { DRAFT_ROOM_CSS } from "./draft-room-tokens";
import { mountManualPaste } from "./manual-paste";

const RECS_WS_URL = "ws://127.0.0.1:8787/recs/ws";

// Overlay layout on top of the shared component kit (which already defines .pos/.sc-*/.btn/etc.).
const OVERLAY_CSS = `
:host { all: initial; }
.panel { --sc-label-w: 3.4em; position: fixed; top: 88px; right: 16px; width: 324px;
  z-index: 2147483647; font-family: var(--font-ui); font-size: var(--fs-base);
  background: var(--card-2); color: var(--ink); border: 1px solid var(--hairline-2);
  border-radius: var(--r-lg); box-shadow: var(--e3); overflow: hidden; }
.panel::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--brass-solid), transparent); }
.ov-head { display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px 9px; border-bottom: 1px solid var(--hairline); }
.live { display: inline-flex; align-items: center; gap: .45em; font-size: var(--fs-xxs);
  font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3); }
.beat { width: 7px; height: 7px; border-radius: 50%; background: var(--good); }
.clock { text-align: right; }
.clock .pk { font-family: var(--font-mono); font-size: var(--fs-sm); }
.reco { padding: 14px 14px 4px; }
.reco-who { display: flex; align-items: center; gap: 10px; }
.reco-name { font-family: var(--font-display); font-size: 1.55rem; line-height: 1; }
.reco-sub { color: var(--ink-3); font-size: var(--fs-xxs); margin-top: 3px; }
.reco-score { margin-left: auto; text-align: right; }
.reco-score b { font-family: var(--font-mono); font-size: 2.1rem; font-weight: 600;
  letter-spacing: -.03em; color: var(--brass); line-height: .9; }
.reco-actions { display: flex; gap: 8px; margin-top: 12px; }
.reco-actions .btn { flex: 1; text-align: center; }
.section { padding: 11px 14px; border-top: 1px solid var(--hairline); }
.section .hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; }
.stack { display: flex; flex-direction: column; gap: 8px; }
.mini-note { font-size: var(--fs-xxs); color: var(--ink-3); margin: 8px 0 0; }
.surv-legend { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.surv-legend .lg { display: inline-flex; align-items: center; gap: .4em; font-size: var(--fs-xs); }
.surv-legend .lg b { font-family: var(--font-mono); }
.alt { display: grid; grid-template-columns: 1.3em auto 1fr auto; gap: 9px; align-items: center;
  padding: 7px 2px; border-top: 1px solid var(--hairline); }
.alt:first-child { border-top: 0; }
.alt .rk { font-family: var(--font-mono); font-size: var(--fs-xxs); color: var(--ink-3); text-align: center; }
.alt .nm { font-family: var(--font-display); font-size: var(--fs-md); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.alt .nm small { font-family: var(--font-ui); color: var(--ink-3); font-size: var(--fs-xxs); margin-left: 5px; }
.alt .rt { text-align: right; font-family: var(--font-mono); font-size: var(--fs-xs); }
.ov-foot { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px;
  border-top: 1px solid var(--hairline); background: var(--wash); font-size: var(--fs-xxs); color: var(--ink-3); }
.sc-label { font-size: var(--fs-xxs); color: var(--ink-3); }
.sc-val { font-family: var(--font-mono); font-size: var(--fs-xs); }
`;

export type OverlaySyncState = RecsSyncState | "waiting" | "manual";

export interface OverlayHandle {
  update(rec: Recommendation): void;
  setStatus(state: OverlaySyncState): void;
  setClock(secondsLeft: number, pick: string): void;
  destroy(): void;
}

export interface MountOverlayOptions {
  recsUrl?: string;
  wsFactory?: (url: string) => WebSocketLike;
  onPaste?: (events: DraftEvent[]) => void;
  /** Advisory local-log write of the intended pick (never a CBS submit). */
  onPin?: (pick: RecommendedPick) => void;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}


/** One Score-Components bar bound to a term (§6.5) — left-anchored or diverging around 0. */
function whyRow(term: WhyTerm, position: Position | null): HTMLElement {
  const row = el("div", "sc-row");
  row.appendChild(el("span", "sc-label", term.label));
  const track = el("div", "sc-track");
  const color = whyTermColorVar(term.colorRole, position);
  if (term.anchor === "diverging") {
    const mid = el("span", "sc-mid");
    mid.style.left = "50%";
    track.appendChild(mid);
    const fill = el("span", "sc-fill");
    if (term.contribution < 0) {
      fill.style.right = "50%";
    } else {
      fill.style.left = "50%";
    }
    fill.style.width = `${term.barFraction * 50}%`;
    fill.style.background = color;
    track.appendChild(fill);
  } else {
    const fill = el("span", "sc-fill");
    fill.style.left = "0";
    fill.style.width = `${term.barFraction * 100}%`;
    fill.style.background = color;
    track.appendChild(fill);
  }
  row.appendChild(track);
  const value = term.key === "mlv" ? term.contribution.toFixed(1) : signed(term.contribution);
  row.appendChild(el("span", "sc-val", value));
  return row;
}

const signed = (n: number): string => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;

export function mountOverlay(opts: MountOverlayOptions = {}): OverlayHandle {
  document.getElementById("jaaffl-overlay")?.remove();

  const host = el("div");
  host.id = "jaaffl-overlay";
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = DRAFT_ROOM_CSS + OVERLAY_CSS;
  shadow.appendChild(style);

  const panel = el("div", "panel");

  // 1 — head: live/status + clock
  const head = el("div", "ov-head");
  const live = el("div", "live");
  const beat = el("span", "beat");
  const liveText = el("span", undefined, "Waiting");
  live.append(beat, liveText);
  const clock = el("div", "clock");
  const clockPk = el("span", "pk", "— · —");
  clock.appendChild(clockPk);
  head.append(live, clock);

  // 2 — recommended block
  const reco = el("div", "reco");
  const who = el("div", "reco-who");
  const posChip = el("span", "pos");
  const idBox = el("div");
  const nameEl = el("div", "reco-name", "Watching the board…");
  const subEl = el("div", "reco-sub mono");
  idBox.append(nameEl, subEl);
  const scoreBox = el("div", "reco-score");
  scoreBox.appendChild(el("span", "eyebrow", "Score"));
  const scoreEl = el("b", "mono", "—");
  scoreBox.appendChild(scoreEl);
  who.append(posChip, idBox, scoreBox);
  const actions = el("div", "reco-actions");
  const copyBtn = el("button", "btn btn-primary", "Copy name");
  copyBtn.type = "button";
  copyBtn.title = "Advisory only — copies the name; the overlay never submits a pick to CBS";
  const whyBtn = el("button", "btn", "Why?");
  whyBtn.type = "button";
  whyBtn.setAttribute("aria-label", "Explain this recommendation");
  actions.append(copyBtn, whyBtn);
  reco.append(who, actions);

  // 3 — the why (score components)
  const whySection = el("div", "section");
  const whyHd = el("div", "hd");
  whyHd.appendChild(el("span", "eyebrow", "The why · score components"));
  const whyStack = el("div", "stack");
  const whyNote = el("p", "mini-note");
  whySection.append(whyHd, whyStack, whyNote);

  // 4 — next-turn survival
  const survSection = el("div", "section");
  const survHd = el("div", "hd");
  survHd.appendChild(el("span", "eyebrow", "Next-turn survival"));
  const survLegend = el("div", "surv-legend");
  survSection.append(survHd, survLegend);

  // 5 — next best (top 5)
  const altSection = el("div", "section");
  const altHd = el("div", "hd");
  altHd.appendChild(el("span", "eyebrow", "Next best — top 5"));
  const altList = el("div", "alts");
  altSection.append(altHd, altList);

  // 6 — foot
  const foot = el("div", "ov-foot");
  const footRoster = el("span", undefined, "Roster —");
  const footSync = el("span", "mono", "");
  foot.append(footRoster, footSync);

  panel.append(head, reco, whySection, survSection, altSection, foot);
  shadow.appendChild(panel);
  document.body.appendChild(host);

  mountManualPaste(shadow, opts.onPaste ?? (() => {}));

  let currentBest: RecommendedPick | null = null;

  function update(rec: Recommendation): void {
    const best = rec.ranked[0];
    if (!best) return;
    currentBest = best;
    const name = best.name ?? best.player_id;
    const pos = best.position ?? null;

    posChip.className = pos ? `pos pos-${pos}` : "pos";
    posChip.textContent = pos ?? "";
    nameEl.textContent = name;
    const subParts: string[] = [];
    if (best.nfl_team) subParts.push(best.nfl_team);
    if (best.bye_week != null) subParts.push(`bye ${best.bye_week}`);
    if (best.components) subParts.push(`replacement ${best.components.replacement_baseline.toFixed(0)}`);
    subEl.textContent = subParts.join(" · ");
    scoreEl.textContent = best.score.toFixed(1);

    // 3 — why bars from the shared decomposition
    const why = decomposeWhy(best, rec.reasoning ?? null, { position: pos ?? undefined });
    whyStack.replaceChildren();
    if (why) {
      for (const term of why.terms.filter((t) => !t.key.startsWith("mod:"))) {
        whyStack.appendChild(whyRow(term, why.position));
      }
      whyNote.textContent = best.rationale ?? "";
    } else {
      whyNote.textContent = "Decomposition unavailable for this pick.";
    }

    // 4 — survival
    survLegend.replaceChildren();
    if (best.next_turn_availability != null) {
      const p = best.next_turn_availability;
      const lg = el("div", "lg");
      lg.appendChild(el("span", "sc-label", `${name} survives`));
      lg.appendChild(el("b", undefined, ` ${formatPct(p)}`));
      survLegend.appendChild(lg);
      const outlook = survivalOutlook(p);
      const pill = el("span", `stat-pill ${outlook.statusClass}`);
      pill.textContent = `${outlook.glyph} ${outlook.word}`;
      survLegend.appendChild(pill);
    }

    // 5 — top 5
    altList.replaceChildren();
    rec.ranked.slice(1, 6).forEach((p, i) => {
      const row = el("div", "alt");
      row.appendChild(el("span", "rk", String(i + 2)));
      const chip = el("span", p.position ? `pos pos-${p.position}` : "pos", p.position ?? "");
      row.appendChild(chip);
      const nm = el("span", "nm", p.name ?? p.player_id);
      if (p.nfl_team) nm.appendChild(el("small", undefined, ` ${p.nfl_team}`));
      row.appendChild(nm);
      const rt = p.next_turn_availability != null
        ? `${p.score.toFixed(1)} · ${formatPct(p.next_turn_availability)}`
        : p.score.toFixed(1);
      row.appendChild(el("span", "rt", rt));
      altList.appendChild(row);
    });

    setStatus("live");
  }

  function setStatus(state: OverlaySyncState): void {
    const map: Record<OverlaySyncState, { text: string; color: string }> = {
      live: { text: "Live · CBS synced", color: "var(--good)" },
      connecting: { text: "Connecting…", color: "var(--warning)" },
      stale: { text: "Stale · awaiting pick", color: "var(--warning)" },
      disconnected: { text: "Reconnecting…", color: "var(--critical)" },
      waiting: { text: "Watching the board", color: "var(--ink-3)" },
      manual: { text: "Manual paste", color: "var(--warning)" },
    };
    const s = map[state];
    liveText.textContent = s.text;
    beat.style.background = s.color;
  }

  function setClock(secondsLeft: number, pick: string): void {
    const m = Math.floor(secondsLeft / 60);
    const sec = Math.max(0, secondsLeft % 60);
    clockPk.textContent = `${pick} · ${m}:${sec < 10 ? "0" : ""}${sec}`;
    clockPk.style.color = secondsLeft <= 10 ? "var(--critical)" : "var(--ink)";
  }

  copyBtn.addEventListener("click", () => {
    if (!currentBest) return;
    const name = currentBest.name ?? currentBest.player_id;
    void navigator.clipboard?.writeText(name); // advisory — copies the name, never submits to CBS
    opts.onPin?.(currentBest);
  });

  const unsubscribe = subscribeRecs(
    opts.recsUrl ?? RECS_WS_URL,
    { onRecommendation: update, onStatus: (s) => setStatus(s) },
    { wsFactory: opts.wsFactory },
  );

  return {
    update,
    setStatus,
    setClock,
    destroy: () => {
      unsubscribe();
      host.remove();
    },
  };
}
