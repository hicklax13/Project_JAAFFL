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
  projectionProvenance,
  type Recommendation,
  type RecommendedPick,
  survivalOutlook,
  type WhyTerm,
  whyTermBar,
  whyTermColorVar,
} from "@jaaffl/shared";

import { subscribeRecs, type RecsSyncState, type WebSocketLike } from "../lib/recs";
import { DRAFT_ROOM_CSS } from "./draft-room-tokens";
import { mountManualPaste } from "./manual-paste";

const RECS_WS_URL = "ws://127.0.0.1:8788/recs/ws";

/** Foot repaint cadence — the sync age has to advance on its own, not only on a push. */
const SYNC_TICK_MS = 500;
/** Matches the recs socket's own stale window, so the badge and the foot never disagree. */
const STALE_AFTER_MS = 3000;
/** Roster-rail order from the league constitution (QB 1 · RB 1 · WR 3 · TE 1 · K 1 · DST 1). */
const ROSTER_POS_ORDER: Position[] = ["QB", "RB", "WR", "TE", "K", "DST"];

/** §6.6 states. Every one carries an icon-free word + colour, never colour alone (§6.7 CVD). */
const STATUS_MAP: Record<OverlaySyncState, { text: string; color: string }> = {
  live: { text: "Live · CBS synced", color: "var(--good)" },
  connecting: { text: "Connecting…", color: "var(--warning)" },
  stale: { text: "Stale · awaiting pick", color: "var(--warning)" },
  disconnected: { text: "Reconnecting…", color: "var(--critical)" },
  waiting: { text: "Watching the board", color: "var(--ink-3)" },
  manual: { text: "Manual paste · not live", color: "var(--warning)" },
};

/** States whose numbers came off a board we cannot vouch for → badge them ESTIMATED (§6.6). */
const ESTIMATED_STATES = new Set<OverlaySyncState>(["manual", "stale"]);

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
  padding: 11px 14px 9px; border-bottom: 1px solid var(--hairline);
  cursor: grab; touch-action: none; user-select: none; }
.ov-head:active { cursor: grabbing; }
/* Collapse to just the header. The panel is fixed at the maximum z-index, so without this it
   sits permanently over the CBS draft board — worst exactly when the board matters most. */
.panel.is-collapsed > *:not(.ov-head) { display: none; }
.panel.is-collapsed { width: 224px; }
.ov-collapse { cursor: pointer; background: transparent; border: 1px solid var(--hairline);
  color: var(--ink-3); border-radius: var(--r-xs); font: inherit; font-size: var(--fs-xxs);
  line-height: 1; padding: 3px 7px; margin-left: 8px; }
.ov-collapse:hover { color: var(--ink); }
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
/* An overdue push is amber in the foot too, so freshness reads the same from the status pill
   and from the sync line. Never colour-alone — the age in seconds carries the same fact. */
.ov-sync.is-stale { color: var(--warning); }
/* Survival ran without knowing my draft slot, so VONA is 0.00 by degradation rather than by
   computation. Amber + a bordered treatment, but the WORDS carry the fact (§6.7 CVD). */
.ov-sync.is-degraded { color: var(--warning); font-weight: 700; }
/* §6.6 — sits directly under the brass score it qualifies, so the caveat travels with the number. */
/* Degraded-projection marker: word + border, never colour alone (§6.7 CVD). */
.prov-chip { display: inline-block; font-size: var(--fs-xxs); font-weight: 700; letter-spacing: .04em;
  color: var(--warning); border: 1px solid var(--warning); border-radius: var(--r-xs);
  padding: 0 4px; }
/* §6.5 Why? drawer — a dense audit table, rendered locally from ScoreComponents (no fetch). */
.why-detail { margin-top: 10px; padding-top: 9px; border-top: 1px dashed var(--hairline-2); }
.why-detail .eyebrow { display: block; margin: 8px 0 5px; }
.why-detail .eyebrow:first-child { margin-top: 0; }
.why-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  padding: 2px 0; }
.why-row .sc-val { font-variant-numeric: tabular-nums; }
.badge-estimated { display: block; margin-top: 4px; font-size: var(--fs-xxs); font-weight: 700;
  letter-spacing: .07em; color: var(--warning); border: 1px solid var(--warning);
  border-radius: var(--r-xs); padding: 1px 5px; }
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


/** One Score-Components bar bound to a term (§6.5) — geometry + text from the shared whyTermBar. */
function whyRow(term: WhyTerm, position: Position | null): HTMLElement {
  const row = el("div", "sc-row");
  row.appendChild(el("span", "sc-label", term.label));
  const track = el("div", "sc-track");
  const bar = whyTermBar(term);
  if (bar.midlinePct !== null) {
    const mid = el("span", "sc-mid");
    mid.style.left = `${bar.midlinePct}%`;
    track.appendChild(mid);
  }
  const fill = el("span", "sc-fill");
  fill.style[bar.anchorEdge] = `${bar.offsetPct}%`;
  fill.style.width = `${bar.widthPct}%`;
  fill.style.background = whyTermColorVar(term.colorRole, position);
  track.appendChild(fill);
  row.appendChild(track);
  row.appendChild(el("span", "sc-val", bar.displayValue));
  return row;
}

const PANEL_STATE_KEY = "jaaffl_overlay_panel";

interface PanelState {
  collapsed?: boolean;
  left?: number;
  top?: number;
}

/** Persist panel placement so it survives the draft-room popup reloading mid-draft. Best-effort:
 * outside an extension context (tests, plain pages) there is no chrome.storage and we no-op. */
function savePanelState(patch: PanelState): void {
  if (typeof chrome === "undefined" || !chrome.storage?.local) return;
  void chrome.storage.local.get(PANEL_STATE_KEY).then((v) => {
    const prev = (v[PANEL_STATE_KEY] ?? {}) as PanelState;
    void chrome.storage.local.set({ [PANEL_STATE_KEY]: { ...prev, ...patch } });
  });
}

async function restorePanelState(
  applyCollapsed: (on: boolean) => void,
  panel: HTMLElement,
): Promise<void> {
  if (typeof chrome === "undefined" || !chrome.storage?.local) return;
  const v = await chrome.storage.local.get(PANEL_STATE_KEY);
  const state = (v[PANEL_STATE_KEY] ?? {}) as PanelState;
  if (state.collapsed) applyCollapsed(true);
  if (typeof state.left === "number" && typeof state.top === "number") {
    placePanel(panel, state.left, state.top);
  }
}

/** Move the panel onto explicit coordinates, releasing its default top/right anchor. */
function placePanel(panel: HTMLElement, left: number, top: number): void {
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
  panel.style.right = "auto";
}

/**
 * Drag the panel by its header. `ignore` (the collapse button) must not start a drag, or the
 * button becomes unclickable. Listeners live on `window` so a fast drag that outruns the cursor
 * doesn't strand the panel mid-move.
 */
function makeDraggable(panel: HTMLElement, handle: HTMLElement, ignore: HTMLElement): void {
  let startX = 0;
  let startY = 0;
  let originLeft = 0;
  let originTop = 0;
  let dragging = false;

  const onMove = (e: MouseEvent): void => {
    if (!dragging) return;
    placePanel(panel, originLeft + (e.clientX - startX), originTop + (e.clientY - startY));
  };
  const onUp = (): void => {
    if (!dragging) return;
    dragging = false;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    savePanelState({
      left: Number.parseFloat(panel.style.left) || 0,
      top: Number.parseFloat(panel.style.top) || 0,
    });
  };

  handle.addEventListener("pointerdown", (e) => {
    const target = e.target as Node | null;
    if (target && (target === ignore || ignore.contains(target))) return;
    const rect = panel.getBoundingClientRect();
    startX = (e as MouseEvent).clientX;
    startY = (e as MouseEvent).clientY;
    originLeft = rect.left;
    originTop = rect.top;
    dragging = true;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

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

  // Collapse toggle. The panel is fixed at the maximum z-index, so on a live draft it otherwise
  // covers the CBS board with no way out short of disabling the extension (which stops recording).
  const collapseBtn = el("button", "ov-collapse", "▾") as HTMLButtonElement;
  collapseBtn.type = "button";
  const applyCollapsed = (on: boolean): void => {
    panel.classList.toggle("is-collapsed", on);
    collapseBtn.textContent = on ? "▸" : "▾";
    collapseBtn.setAttribute("aria-expanded", String(!on));
    collapseBtn.setAttribute("aria-label", on ? "Expand JAAFFL panel" : "Collapse JAAFFL panel");
  };
  applyCollapsed(false);
  collapseBtn.addEventListener("click", () => {
    const next = !panel.classList.contains("is-collapsed");
    applyCollapsed(next);
    savePanelState({ collapsed: next });
  });

  const headRight = el("div", "ov-head-right");
  headRight.append(clock, collapseBtn);
  head.append(live, headRight);
  makeDraggable(panel, head, collapseBtn);
  void restorePanelState(applyCollapsed, panel);

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
  // §6.6 ESTIMATED — a badge ON THE NUMBER, added/removed from the DOM rather than hidden, so
  // "is this figure trustworthy?" is answerable from the tree and not just from a CSS property.
  const estimatedBadge = el("span", "badge-estimated", "ESTIMATED");
  estimatedBadge.title = "Computed from a board that is not live — treat this number as estimated";
  who.append(posChip, idBox, scoreBox);
  const actions = el("div", "reco-actions");
  const copyBtn = el("button", "btn btn-primary", "Copy name");
  copyBtn.type = "button";
  copyBtn.title = "Advisory only — copies the name; the overlay never submits a pick to CBS";
  // Pin gets its OWN control. It used to ride the copyBtn handler, which meant the owner could
  // not copy a name without also writing a pick to the advisory log — two intents, one button.
  const pinBtn = el("button", "btn ov-pin", "Pin my pick");
  pinBtn.type = "button";
  pinBtn.title = "Advisory only — logs your intent locally; the overlay never submits to CBS";
  const whyBtn = el("button", "btn", "Why?");
  whyBtn.type = "button";
  whyBtn.setAttribute("aria-label", "Explain this recommendation");
  whyBtn.setAttribute("aria-expanded", "false");
  actions.append(copyBtn, pinBtn, whyBtn);
  reco.append(who, actions);

  // 3 — the why (score components)
  const whySection = el("div", "section");
  const whyHd = el("div", "hd");
  whyHd.appendChild(el("span", "eyebrow", "The why · score components"));
  const whyStack = el("div", "stack");
  const whyNote = el("p", "mini-note");
  const whyDetailHost = el("div"); // holds the Why? panel; empty while collapsed
  whySection.append(whyHd, whyStack, whyNote, whyDetailHost);

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

  // 6 — foot: roster state + freshness. Both were created and appended but never assigned, so
  // sync age and recompute ms never rendered — the two numbers that let the owner tell a 200ms-old
  // recommendation from a 90-second-old one (§6.7 auditability).
  const foot = el("div", "ov-foot");
  const footRoster = el("span", undefined, "Roster —");
  const footSync = el("span", "mono ov-sync", "");
  foot.append(footRoster, footSync);

  panel.append(head, reco, whySection, survSection, altSection, foot);
  shadow.appendChild(panel);
  document.body.appendChild(host);

  // Manual-paste fallback. parse.ts already tags these events "manual"; that signal used to be
  // thrown away, so a capture failure left the overlay looking fully live. Latch it instead:
  // provenance is a property of the BOARD, so it holds until the page reloads.
  mountManualPaste(shadow, (events) => {
    if (events.length > 0) {
      manualBoard = true;
      renderStatus();
    }
    opts.onPaste?.(events);
  });

  let currentBest: RecommendedPick | null = null;
  let receivedAt: number | null = null; // CLIENT-side receipt clock — see renderSync()
  let recomputeMs: number | null = null;
  /** Which survival model produced this rec's VONA (Recommendation.survival_basis).
   * null = the backend said nothing, which is NOT the same as saying it was degraded. */
  let survivalBasis: string | null = null;
  let socketState: OverlaySyncState = "waiting";
  let whyOpen = false;
  let lastReasoning: string | null = null;
  /** Latched once the owner falls back to manual paste — the board's provenance, not the socket's. */
  let manualBoard = false;

  /**
   * Foot, right half: `synced 0.4s ago · recompute 380ms` (§6.3 anatomy #6).
   *
   * The two numbers come from deliberately different places. `recompute` is server-side truth —
   * only the backend can time its own engine, so it rides the Recommendation contract. Sync age
   * is measured CLIENT-side from receipt, because that is the question the owner is actually
   * asking ("how long since my overlay heard from the engine?"). A server-stamped age would
   * freeze at its last value the moment the socket died, reading "fresh" forever over rotting
   * data; a receipt clock keeps ticking, so a dead feed visibly ages.
   */
  function renderSync(): void {
    if (receivedAt === null) {
      footSync.textContent = "";
      return;
    }
    const ageMs = Date.now() - receivedAt;
    const parts = [`synced ${(ageMs / 1000).toFixed(1)}s ago`];
    if (recomputeMs !== null) parts.push(`recompute ${Math.round(recomputeMs)}ms`);
    // No CBS frame names the viewer's own team, so without a configured slot the engine
    // cannot work out when my next pick is: survival degrades to "everyone available" and
    // VONA collapses to 0.00. That zero is indistinguishable from a computed zero unless it
    // is labelled here. Only ever shown when the backend actually SAID so — an older payload
    // that omits survival_basis is not accused of being degraded.
    const degraded = survivalBasis === "degraded_no_slot";
    if (degraded) parts.push("VONA degraded · no draft slot set");
    footSync.textContent = parts.join(" · ");
    footSync.classList.toggle("is-stale", ageMs >= STALE_AFTER_MS);
    footSync.classList.toggle("is-degraded", degraded);
  }

  // Repaint on a timer, not only on push: without this the age would freeze at "0.0s ago" the
  // instant the feed stopped — precisely the silent lie the footer exists to prevent.
  const syncTimer = setInterval(renderSync, SYNC_TICK_MS);

  /** Foot, left half: `Roster 2/17 · RB 1 · WR 3` — published by the engine, never inferred. */
  function renderRoster(rec: Recommendation): void {
    if (rec.roster_filled == null || !rec.roster_size) {
      footRoster.textContent = "Roster —";
      return;
    }
    const byPos = rec.roster_by_position ?? {};
    const known = ROSTER_POS_ORDER.filter((p) => byPos[p]);
    const extra = Object.keys(byPos)
      .filter((p) => byPos[p] && !ROSTER_POS_ORDER.includes(p as Position))
      .sort();
    const counts = [...known, ...extra].map((p) => `${p} ${byPos[p]}`);
    footRoster.textContent = [`Roster ${rec.roster_filled}/${rec.roster_size}`, ...counts].join(
      " · ",
    );
  }

  /** One `label · value` line inside the Why? panel. */
  function whyLine(label: string, value: string): HTMLElement {
    const row = el("div", "why-row");
    row.append(el("span", "sc-label", label), el("span", "sc-val", value));
    return row;
  }

  /**
   * The `Why?` panel (§6.5, the anti-black-box guarantee). Rendered LOCALLY from the
   * `ScoreComponents` the overlay already holds — no fetch. That keeps the click within the
   * one-frame repaint budget (§6.7) and, more importantly, keeps the explanation available
   * exactly when the backend is not: a dropped socket is when you most want to interrogate the
   * last pick you were given.
   *
   * It shows what the four bars CANNOT: the score reconciling to the sum of its terms (proof that
   * no term is hidden, rather than a promise), the capped modifiers the bars deliberately filter
   * out, and the descriptive fields — σ band, reliability shrinkage, VONA horizon, and E[best
   * available next] — that ride the contract and were never rendered anywhere.
   */
  function renderWhyDetail(): void {
    whyDetailHost.replaceChildren();
    if (!whyOpen || !currentBest) return;

    const box = el("div", "why-detail");
    const why = decomposeWhy(currentBest, lastReasoning, {
      position: currentBest.position ?? undefined,
    });
    const c = currentBest.components;
    if (!why || !c) {
      box.appendChild(el("p", "mini-note", "No decomposition rode along with this pick."));
      whyDetailHost.appendChild(box);
      return;
    }

    box.appendChild(el("div", "eyebrow", "Score reconciliation"));
    for (const term of why.terms) {
      box.appendChild(whyLine(term.label, whyTermBar(term).displayValue));
    }
    box.appendChild(whyLine("Sum of terms", why.reconstructed.toFixed(1)));
    box.appendChild(whyLine("Reported score", why.score.toFixed(1)));
    box.appendChild(
      whyLine(
        why.reconciles ? "Reconciles ✓" : "Reconciles ✗",
        `residual ${why.residual.toFixed(2)}`,
      ),
    );

    box.appendChild(el("div", "eyebrow", "Projection & horizon"));
    const prov = projectionProvenance(currentBest.projection_sources);
    if (prov) {
      box.appendChild(whyLine("Sources", prov.label));
      box.appendChild(el("p", "mini-note", prov.detail));
    }
    box.appendChild(whyLine("Floor (p10)", c.floor.toFixed(1)));
    box.appendChild(whyLine("Ceiling (p90)", c.ceiling.toFixed(1)));
    box.appendChild(whyLine("σ", c.sigma.toFixed(1)));
    box.appendChild(whyLine("Replacement baseline", c.replacement_baseline.toFixed(1)));
    if (c.reliability != null) box.appendChild(whyLine("Reliability r_pos", c.reliability.toFixed(2)));
    if (c.vona_horizon != null) box.appendChild(whyLine("VONA horizon", `${c.vona_horizon} turns`));
    if (c.best_available_next != null) {
      box.appendChild(whyLine("E[best available next]", c.best_available_next.toFixed(1)));
    }
    whyDetailHost.appendChild(box);
  }

  function update(rec: Recommendation): void {
    const best = rec.ranked[0];
    if (!best) return;
    currentBest = best;
    lastReasoning = rec.reasoning ?? null;
    receivedAt = Date.now();
    recomputeMs = rec.recompute_ms ?? null;
    survivalBasis = rec.survival_basis ?? null;
    renderRoster(rec);
    renderSync();
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

    // Projection provenance (§5). Marked ONLY when degraded, so the chip's presence carries the
    // information — an ECR-only player has no modeled projection at all, just a rank mapped onto
    // the fallback curve. Unknown provenance renders nothing: "we don't know" and "we checked and
    // it's degraded" are different claims.
    const prov = projectionProvenance(best.projection_sources);
    if (prov && !prov.modeled) {
      const chip = el("span", "prov-chip", prov.label);
      chip.title = prov.detail;
      subEl.append(" ", chip);
    }
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
      // The alternates are exactly where the owner pivots when they disagree with #1, so an
      // unbacked projection has to be marked here too — not only on the best pick.
      // Same rule as the best pick: unknown provenance renders nothing, because "we don't
      // know" and "we checked and it's degraded" are different claims.
      const altProv = projectionProvenance(p.projection_sources);
      if (altProv && !altProv.modeled) {
        const altChip = el("span", "prov-chip", altProv.label);
        altChip.title = altProv.detail;
        nm.append(" ", altChip);
      }
      row.appendChild(nm);
      const rt = p.next_turn_availability != null
        ? `${p.score.toFixed(1)} · ${formatPct(p.next_turn_availability)}`
        : p.score.toFixed(1);
      row.appendChild(el("span", "rt", rt));
      altList.appendChild(row);
    });

    renderWhyDetail(); // keep an OPEN explanation in step with the pick it explains
    setStatus("live");
  }

  function setStatus(state: OverlaySyncState): void {
    socketState = state;
    renderStatus();
  }

  /**
   * Resolve socket health + board provenance into one honest status (§6.6).
   *
   * Manual provenance outranks a HEALTHY socket, because the two describe different things: the
   * recs feed can be perfectly live while the board it computed from came out of a human paste.
   * It never outranks a DEGRADED socket — "reconnecting" is both more urgent and equally true,
   * and hiding it behind a provenance badge would trade one silent lie for another.
   */
  function renderStatus(): void {
    const healthy = socketState === "live" || socketState === "waiting";
    const effective: OverlaySyncState = manualBoard && healthy ? "manual" : socketState;
    const s = STATUS_MAP[effective];
    liveText.textContent = s.text;
    beat.style.background = s.color;

    // §6.6's ESTIMATED row names forward-year figures as the trigger; the same badge is what a
    // degraded board warrants, and a degraded board is the trigger we can actually detect today.
    // A forward-year flag on the contract would light the identical treatment.
    //
    // Keyed off TRUST, not off the displayed word. Keying it off `effective` made the badge
    // vanish on "Reconnecting…" — the caveat disappearing exactly as things got worse, because a
    // manual board plus a dead socket rendered as merely disconnected. A score is un-caveated
    // only when a live feed is reporting a live-captured board; anything less is estimated.
    const trustworthy = !manualBoard && socketState === "live";
    const estimated = currentBest !== null && !trustworthy;
    if (estimated && !estimatedBadge.isConnected) scoreBox.appendChild(estimatedBadge);
    else if (!estimated && estimatedBadge.isConnected) estimatedBadge.remove();
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
  });

  pinBtn.addEventListener("click", () => {
    if (!currentBest) return;
    opts.onPin?.(currentBest); // advisory local-log write — never a CBS submit (§6.3)
  });

  whyBtn.addEventListener("click", () => {
    whyOpen = !whyOpen;
    whyBtn.setAttribute("aria-expanded", String(whyOpen));
    renderWhyDetail();
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
      clearInterval(syncTimer);
      unsubscribe();
      host.remove();
    },
  };
}
