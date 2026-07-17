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
