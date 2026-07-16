// Thin in-page overlay: Shadow-DOM host (styles can't leak either way), a /recs/ws
// subscription hook, and the manual-paste fallback panel. The full recommendation panel
// (ScoreComponents decomposition, survival %) is Stage 6 — here we only guarantee the
// socket + render hook + paste fallback exist (plan §5.9). Built with plain DOM methods
// (no innerHTML) so no observed content can ever become markup.

import type { DraftEvent, Recommendation } from "@jaaffl/shared";

import { mountManualPaste } from "./manual-paste";

const RECS_WS_URL = "ws://127.0.0.1:8787/recs/ws";

const PANEL_CSS = `
  :host { all: initial; }
  .panel {
    position: fixed; top: 88px; right: 16px; width: 300px; z-index: 2147483647;
    font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
    border-radius: 12px; padding: 14px 16px; box-shadow: 0 8px 30px rgba(0,0,0,.35);
  }
  h1 { font-size: 13px; margin: 0 0 6px; letter-spacing: .04em;
    text-transform: uppercase; color: #94a3b8; }
  .rec { font-size: 18px; font-weight: 700; }
  .muted { font-size: 12px; color: #94a3b8; margin-top: 8px; }
  .paste { margin-top: 10px; font-size: 12px; }
  .paste textarea { width: 100%; box-sizing: border-box; margin: 6px 0;
    background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; }
  .paste button { background: #38bdf8; color: #0f172a; border: 0; border-radius: 6px;
    padding: 4px 10px; font-weight: 600; cursor: pointer; }
  .paste .status { margin-left: 8px; color: #94a3b8; }
  .paste .hint { color: #64748b; margin: 4px 0; }
`;

export interface OverlayOptions {
  onPaste?: (events: DraftEvent[]) => void;
}

export function mountOverlay(opts: OverlayOptions = {}): void {
  if (document.getElementById("jaaffl-overlay")) return;

  const host = document.createElement("div");
  host.id = "jaaffl-overlay";
  const shadow = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = PANEL_CSS;
  shadow.appendChild(style);

  const panel = document.createElement("div");
  panel.className = "panel";
  const title = document.createElement("h1");
  title.textContent = "JAAFFL";
  const rec = document.createElement("div");
  rec.className = "rec";
  rec.textContent = "Waiting for draft…";
  const muted = document.createElement("div");
  muted.className = "muted";
  muted.textContent = "Recommendations appear here once the engine is wired (stage 5).";
  panel.append(title, rec, muted);
  shadow.appendChild(panel);

  document.body.appendChild(host);
  mountManualPaste(shadow, opts.onPaste ?? (() => {}));
  subscribeRecs(shadow);
}

/** Subscribe to the backend push channel (scaffold change #4). Renders minimally until
 * the Stage-6 overlay design lands; fails soft when the backend is down. */
function subscribeRecs(shadow: ShadowRoot): void {
  try {
    const ws = new WebSocket(RECS_WS_URL);
    ws.onmessage = (e) => {
      try {
        const frame = JSON.parse(String(e.data)) as {
          type?: string;
          recommendation?: Recommendation | null;
        };
        if ((frame.type === "rec" || frame.type === "snapshot") && frame.recommendation) {
          renderRecs(shadow, frame.recommendation);
        }
      } catch {
        /* ignore undecodable frames */
      }
    };
    ws.onerror = () => ws.close();
  } catch {
    /* backend down — overlay simply shows no guidance */
  }
}

function renderRecs(shadow: ShadowRoot, recommendation: Recommendation): void {
  const best = recommendation.ranked[0];
  const target = shadow.querySelector(".rec");
  if (target && best) {
    target.textContent =
      `#${recommendation.as_of_overall_pick}: ${best.player_id} (${best.score.toFixed(1)})`;
  }
}
