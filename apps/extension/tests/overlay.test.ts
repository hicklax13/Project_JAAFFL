/**
 * The in-draft overlay (plan §6.3) — the primary surface. It renders the recommended pick, its
 * decomposed "why", next-turn survival, and the top-5 into an isolated Shadow DOM, and it is
 * ADVISORY: the primary action copies the name / pins intent locally and NEVER submits to CBS.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "@jaaffl/shared";

import { mountOverlay } from "../src/overlay/overlay";
import type { WebSocketLike } from "../src/lib/recs";

// A WebSocket that never connects, so mounting the overlay opens no real socket in tests.
class NoopWs implements WebSocketLike {
  readyState = 0;
  send(): void {}
  close(): void {}
  addEventListener(): void {}
}
const noopFactory = (): WebSocketLike => new NoopWs();

const REC: Recommendation = {
  league_id: "cbs-local",
  as_of_overall_pick: 27,
  reasoning: "R3P3 · floor-tilt λ=+0.2 · κ=0.6 · α=0.4 · flex_split=8RB/4WR (EngineParams v1.0.0)",
  ranked: [
    {
      player_id: "p1",
      name: "James Cook",
      position: "RB",
      nfl_team: "BUF",
      bye_week: 7,
      score: 41.2,
      next_turn_availability: 0.18,
      tier: 3,
      rationale: "Last elite anchor-RB before the cliff.",
      components: {
        mlv: 32.4,
        vona: 15.0,
        risk_penalty: 2.1,
        cliff_bonus: 2.0,
        sigma: 40,
        floor: 200,
        ceiling: 300,
        replacement_baseline: 118,
        modifiers: {},
      },
    },
    { player_id: "p2", name: "Drake London", position: "WR", nfl_team: "ATL", score: 37.8, next_turn_availability: 0.41 },
  ],
};

function shadow(): ShadowRoot {
  return document.getElementById("jaaffl-overlay")!.shadowRoot!;
}

beforeEach(() => {
  document.getElementById("jaaffl-overlay")?.remove();
});

describe("mountOverlay", () => {
  it("renders the recommended pick, the decomposed why, survival, and the top-5", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    const text = shadow().textContent ?? "";
    expect(text).toContain("James Cook");
    expect(text).toContain("41.2"); // brass score
    expect(text).toContain("18%"); // survival to next pick
    expect(text).toContain("Drake London"); // top-5 alternative
    // the "why" bars bind to ScoreComponents — MLV/VONA/Risk/Cliff each a bar
    expect(shadow().querySelectorAll(".sc-fill").length).toBeGreaterThanOrEqual(4);
    handle.destroy();
  });

  it("inlines the self-contained design tokens into the Shadow DOM (no external CSS)", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    expect(shadow().querySelector("style")?.textContent).toContain("--brass-solid");
    handle.destroy();
  });

  it("is ADVISORY: the primary action copies the name and never submits a pick to CBS", () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    const text = shadow().textContent ?? "";
    expect(text).not.toMatch(/draft james cook/i); // the illustrative auto-submit label is gone
    const primary = shadow().querySelector<HTMLButtonElement>(".btn-primary")!;
    expect(primary.textContent).toMatch(/copy name|pin/i);
    primary.click();
    expect(writeText).toHaveBeenCalledWith("James Cook");
    handle.destroy();
    vi.unstubAllGlobals();
  });

  it("reflects sync status and offers a Why? affordance", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.setStatus("disconnected");
    expect(shadow().textContent ?? "").toMatch(/reconnect|disconnect/i);
    expect(shadow().querySelector('[aria-label*="Explain" i]')).not.toBeNull();
    handle.destroy();
  });

  it("destroy() removes the overlay host from the page", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    expect(document.getElementById("jaaffl-overlay")).not.toBeNull();
    handle.destroy();
    expect(document.getElementById("jaaffl-overlay")).toBeNull();
  });
});

describe("overlay panel controls", () => {
  // The panel is position:fixed at z-index 2147483647 with hard-coded top/right. During a live
  // mock draft that meant it sat permanently over the CBS draft board with no way to move or
  // dismiss it — exactly when the board matters most. These pin the escape hatches.

  function mount() {
    const handle = mountOverlay({ wsFactory: noopFactory });
    const shadow = document.getElementById("jaaffl-overlay")!.shadowRoot!;
    return { handle, shadow };
  }

  it("renders a collapse toggle that is expanded by default", () => {
    const { shadow } = mount();
    const btn = shadow.querySelector<HTMLButtonElement>(".ov-collapse")!;

    expect(btn).toBeTruthy();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(shadow.querySelector(".panel")!.classList.contains("is-collapsed")).toBe(false);
  });

  it("collapses to just the header when toggled, and restores", () => {
    const { shadow } = mount();
    const btn = shadow.querySelector<HTMLButtonElement>(".ov-collapse")!;
    const panel = shadow.querySelector(".panel")!;

    btn.click();
    expect(panel.classList.contains("is-collapsed")).toBe(true);
    expect(btn.getAttribute("aria-expanded")).toBe("false");

    btn.click();
    expect(panel.classList.contains("is-collapsed")).toBe(false);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("gives the collapse button an accessible name in both states", () => {
    const { shadow } = mount();
    const btn = shadow.querySelector<HTMLButtonElement>(".ov-collapse")!;

    expect(btn.getAttribute("aria-label")).toMatch(/collapse/i);
    btn.click();
    expect(btn.getAttribute("aria-label")).toMatch(/expand/i);
  });

  it("drags by the header to a new position", () => {
    const { shadow } = mount();
    const head = shadow.querySelector<HTMLElement>(".ov-head")!;
    const panel = shadow.querySelector<HTMLElement>(".panel")!;

    head.dispatchEvent(new MouseEvent("pointerdown", { clientX: 500, clientY: 100, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 460, clientY: 160, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));

    // Dragging switches the panel off its hard-coded `right` anchor onto explicit coords.
    expect(panel.style.left).not.toBe("");
    expect(panel.style.top).not.toBe("");
    expect(panel.style.right).toBe("auto");
  });

  it("does not start a drag from the collapse button", () => {
    const { shadow } = mount();
    const btn = shadow.querySelector<HTMLButtonElement>(".ov-collapse")!;
    const panel = shadow.querySelector<HTMLElement>(".panel")!;

    btn.dispatchEvent(new MouseEvent("pointerdown", { clientX: 500, clientY: 100, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 300, clientY: 300, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));

    expect(panel.style.left).toBe(""); // never moved
  });
});

describe("overlay foot — roster + freshness (§6.3 anatomy #6, §6.7 auditability)", () => {
  // These two fields are the whole difference between trusting a pick and not: they let the
  // owner tell a 200ms-old recommendation from a 90-second-old one. Both elements existed and
  // were appended to the DOM, but neither was ever assigned — permanently blank on draft night.

  const FRESH: Recommendation = {
    ...REC,
    recompute_ms: 12.4,
    roster_filled: 2,
    roster_size: 17,
    roster_by_position: { RB: 1, WR: 1 },
  };

  function foot(): HTMLElement {
    return shadow().querySelector<HTMLElement>(".ov-foot")!;
  }

  it("renders the roster summary the engine published", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(FRESH);
    expect(foot().textContent).toContain("Roster 2/17");
    expect(foot().textContent).toContain("RB 1");
    expect(foot().textContent).toContain("WR 1");
    handle.destroy();
  });

  it("renders the backend recompute cost, making the <200ms budget auditable", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(FRESH);
    expect(foot().textContent).toContain("recompute 12ms");
    handle.destroy();
  });

  it("ages the sync clock so a stale recommendation cannot look fresh", () => {
    vi.useFakeTimers();
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(FRESH);
    const first = foot().textContent ?? "";
    expect(first).toContain("synced 0.0s ago");

    vi.advanceTimersByTime(45_000);
    const later = foot().textContent ?? "";
    expect(later).toContain("synced 45.0s ago");
    expect(later).not.toBe(first); // the whole point: the number MOVED without a new push

    handle.destroy();
    vi.useRealTimers();
  });

  it("flags the sync line stale once the push is overdue", () => {
    vi.useFakeTimers();
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(FRESH);
    const sync = shadow().querySelector<HTMLElement>(".ov-sync")!;
    expect(sync.classList.contains("is-stale")).toBe(false);

    vi.advanceTimersByTime(10_000);
    expect(sync.classList.contains("is-stale")).toBe(true);

    handle.destroy();
    vi.useRealTimers();
  });

  it("degrades honestly when the engine published no roster summary", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC); // pre-Tier-2 payload: no roster/recompute fields at all
    expect(foot().textContent).toContain("Roster —");
    expect(foot().textContent).not.toContain("recompute");
    handle.destroy();
  });
});
