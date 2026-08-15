/**
 * ISOLATED draft-room content script = THE TRUST BOUNDARY (plan §5.5).
 *
 * MAIN world is the page's realm — a page script (or hostile ad) could forge a
 * "jaaffl-main" message. This script therefore never trusts a relay blindly: it checks
 * event.source/event.origin, runs every payload through parse.ts + Zod (createForwarder),
 * de-dups by pick_number, and owns the localhost WebSocket. It also runs Probe 3 (the
 * MutationObserver DOM fallback) and mounts the Shadow-DOM overlay + manual-paste UI.
 */

import { createForwarder } from "../lib/dedup";
import { parseDraftEvents, type RawSource } from "../lib/parse";
import { recordPinnedPick } from "../lib/pin-log";
import { Recorder } from "../lib/record";
import { DraftSocket, type MainRelay } from "../lib/transport";
import { mountOverlay } from "../overlay/overlay";

const socket = new DraftSocket(); // owns ws://127.0.0.1:8788/draft/ws (§5.6)
const recorder = new Recorder(); // record mode: action toggle -> fixture capture
const forward = createForwarder((event) => socket.send(event));

// Uncaught errors in THIS script were invisible everywhere — not in the backend log, not in the
// capture, not in the rehearsal report. The overlay would simply stop updating and read as merely
// stale, which is indistinguishable from a quiet draft. Both handlers are passive: they observe
// and never preventDefault, so normal error reporting is unchanged.
window.addEventListener("error", (e: ErrorEvent) => {
  recorder.recordError(e.error ?? e.message, "window.onerror");
});
window.addEventListener("unhandledrejection", (e: PromiseRejectionEvent) => {
  recorder.recordError(e.reason, "unhandledrejection");
});

/** Parse one raw probe payload, then forward each event. Silent on non-draft frames. */
function emit(raw: RawSource): void {
  for (const event of parseDraftEvents(raw)) forward(event);
}

// Receive Probe 1 + Probe 2 relays from the MAIN world.
window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const d = e.data as MainRelay;
  if (d?.source !== "jaaffl-main" || typeof d.body !== "string" || d.body === "\u0000binary") {
    return;
  }
  recorder.record(d.kind, { url: d.url, body: d.body, ts: d.ts, seq: d.seq });
  const via = d.kind === "framework" ? "framework" : "ws"; // network kinds normalize alike
  emit({ via, url: d.url, body: d.body });
});

// Trigger the MAIN-side ring flush; re-post briefly in case the first ack raced the
// injector's listener (§5.2 — cross-world ordering at document_start is not guaranteed).
window.postMessage({ source: "jaaffl-iso", ack: true }, location.origin);
let ackTries = 0;
const ackTimer = setInterval(() => {
  window.postMessage({ source: "jaaffl-iso", ack: true }, location.origin);
  if (++ackTries >= 5) clearInterval(ackTimer);
}, 500);

// Probe 3 (DOM fallback) + overlay: deferred to DOMContentLoaded (body is null at
// document_start). Watches the board AND the always-updating ticker/chat, because CBS
// results panes are known to render only on tab click (§5.4.3).
function onReady(): void {
  mountOverlay({
    onPaste: (events) => events.forEach(forward),
    // Advisory local-log write, NEVER a CBS submit (§6.3). Without this the overlay's pin control
    // called `opts.onPin?.()` on an undefined sink, so pinning did nothing at all.
    onPin: (pick) => void recordPinnedPick(pick, Date.now()),
  });
  const target =
    document.querySelector('[class*="draft-board" i],[data-testid*="draft" i]') ??
    document.querySelector('[class*="ticker" i],[class*="chat" i],[class*="pick-log" i]') ??
    document.body;
  // The ticker/chat mutates continuously during a live draft; coalesce a burst of
  // mutations into one full-document re-parse per frame instead of re-scanning per event.
  let scanQueued = false;
  const observer = new MutationObserver(() => {
    recorder.recordDomSnapshot(target);
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(() => {
      scanQueued = false;
      emit({ via: "dom", root: document });
    });
  });
  observer.observe(target, { childList: true, subtree: true, characterData: true });
  emit({ via: "dom", root: document }); // initial board read (late join / reload)
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", onReady);
} else {
  onReady();
}

console.debug("[jaaffl] draft content script active (trust boundary)");
