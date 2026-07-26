/**
 * Manual-paste fallback (plan §5.9) — the guaranteed draft-day path when all three live
 * probes miss. The user pastes CBS's copied results/pick log (and optionally an
 * `ORDER: ...` line carrying the in-person draft order); parsePastedResults normalizes,
 * and the injected sink routes through the SAME validate→de-dup→send tail as live capture.
 *
 * Built with plain DOM methods (no innerHTML): nothing the user pastes ever becomes
 * markup — it flows into parsePastedResults as text only.
 */

import type { DraftEvent } from "@jaaffl/shared";

import { parsePastedReport } from "../lib/parse";

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

export function mountManualPaste(
  shadow: ShadowRoot,
  onPaste: (events: DraftEvent[]) => void,
): void {
  const details = el("details", "paste");
  details.appendChild(el("summary", undefined, "Manual paste (fallback)"));
  details.appendChild(
    el(
      "p",
      "hint",
      "Paste picks — one per line, e.g. `13. Team Name - Player, RB, PHI`. " +
        "Include `ORDER: T1, T2, …` to supply the in-person draft order.",
    ),
  );

  const textarea = el("textarea");
  textarea.rows = 5;
  textarea.placeholder = "ORDER: ...\n1. Team - Player, POS, NFL";
  details.appendChild(textarea);

  const button = el("button", undefined, "Send picks");
  button.type = "button";
  details.appendChild(button);

  const status = el("span", "status");
  details.appendChild(status);

  button.addEventListener("click", () => {
    const { events, skipped } = parsePastedReport(textarea.value);
    onPaste(events);
    if (!events.length) {
      status.textContent = "nothing parseable — check the line format";
    } else if (skipped.length) {
      // A partial parse must NOT read as success. "21 event(s) sent" after 24 pasted picks
      // is indistinguishable from a clean run unless the owner counts — and a pick that
      // never arrives is a player who is never masked.
      status.textContent =
        `${events.length} event(s) sent · ${skipped.length} line(s) SKIPPED: ` +
        skipped.slice(0, 2).join(" | ") +
        (skipped.length > 2 ? " …" : "");
      status.classList.add("is-warning");
    } else {
      status.textContent = `${events.length} event(s) sent`;
      status.classList.remove("is-warning");
    }
  });

  shadow.querySelector(".panel")?.appendChild(details);
}
