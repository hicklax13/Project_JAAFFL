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

  it("warns when VONA was computed without knowing my draft slot", () => {
    // No CBS frame names the VIEWER's own team, so an unconfigured slot degrades survival to
    // "everyone available" and VONA collapses to 0.00 — a number that reads as computed.
    // The overlay must say which basis produced it, or the caveat is invisible.
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update({ ...REC, survival_basis: "degraded_no_slot" });
    const sync = shadow().querySelector(".ov-sync")!;
    expect(sync.textContent).toMatch(/no draft slot/i);
    expect(sync.classList.contains("is-degraded")).toBe(true);
    handle.destroy();
  });

  it("stays quiet when the survival model did have my slot", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update({ ...REC, survival_basis: "my_slot" });
    const sync = shadow().querySelector(".ov-sync")!;
    expect(sync.textContent).not.toMatch(/no draft slot/i);
    expect(sync.classList.contains("is-degraded")).toBe(false);
    handle.destroy();
  });

  it("says nothing about the basis when the backend did not state one", () => {
    // A pre-Tier-3 payload must not be labelled degraded on a guess.
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    const sync = shadow().querySelector(".ov-sync")!;
    expect(sync.textContent).not.toMatch(/no draft slot/i);
    expect(sync.classList.contains("is-degraded")).toBe(false);
    handle.destroy();
  });
});

describe("overlay degraded modes — manual paste + ESTIMATED (§6.6)", () => {
  // If capture fails and the owner falls back to manual paste, the overlay used to still look
  // fully live: nothing ever called setStatus("manual") and no ESTIMATED treatment existed.
  // That is a silent lie at exactly the wrong moment.

  /** Drive the REAL manual-paste control, not setStatus() — the point is that the path is wired. */
  function pasteRealPicks(): void {
    const box = shadow().querySelector<HTMLTextAreaElement>(".paste textarea")!;
    const send = shadow().querySelector<HTMLButtonElement>(".paste button")!;
    box.value = "12. Team Six - Bijan Robinson, RB, ATL";
    send.click();
  }

  function statusText(): string {
    return shadow().querySelector(".live")?.textContent ?? "";
  }

  it("routes pasted picks to the onPaste sink AND flags the board manual", () => {
    const onPaste = vi.fn();
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste });
    handle.setStatus("live");
    expect(statusText()).toMatch(/live/i);

    pasteRealPicks();

    expect(onPaste).toHaveBeenCalledTimes(1);
    expect(onPaste.mock.calls[0]![0]).toHaveLength(1); // the parsed pick still flows through
    expect(statusText()).toMatch(/manual/i);
    handle.destroy();
  });

  it("keeps the manual flag latched when a live push follows", () => {
    // The recs socket can be perfectly healthy while the BOARD came from a human paste.
    // Provenance is a property of the board, so it must not be cleared by a fresh rec.
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste: () => {} });
    pasteRealPicks();
    handle.update(REC); // update() ends by calling setStatus("live")

    expect(statusText()).toMatch(/manual/i);
    expect(statusText()).not.toMatch(/CBS synced/i);
    handle.destroy();
  });

  it("still reports a dropped socket over the manual flag", () => {
    // A dead socket is both more urgent and equally true — it must not be masked by provenance.
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste: () => {} });
    pasteRealPicks();
    handle.setStatus("disconnected");

    expect(statusText()).toMatch(/reconnect/i);
    handle.destroy();
  });

  it("does not flag manual when nothing parsed out of the paste box", () => {
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste: () => {} });
    handle.setStatus("live");
    const box = shadow().querySelector<HTMLTextAreaElement>(".paste textarea")!;
    box.value = "not a pick line at all";
    shadow().querySelector<HTMLButtonElement>(".paste button")!.click();

    expect(statusText()).toMatch(/live/i);
    handle.destroy();
  });

  it("badges the score ESTIMATED once the board is manually pasted", () => {
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste: () => {} });
    handle.update(REC);
    expect(shadow().querySelector(".badge-estimated")).toBeNull();

    pasteRealPicks();
    const badge = shadow().querySelector(".badge-estimated");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toMatch(/estimated/i);
    handle.destroy();
  });

  it("badges the score ESTIMATED while the feed is stale", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    expect(shadow().querySelector(".badge-estimated")).toBeNull();

    handle.setStatus("stale");
    expect(shadow().querySelector(".badge-estimated")).not.toBeNull();

    handle.setStatus("live"); // recovered — the number is trustworthy again
    expect(shadow().querySelector(".badge-estimated")).toBeNull();
    handle.destroy();
  });
});

describe("overlay ESTIMATED — the badge tracks trust, not just the status word", () => {
  function pasteRealPicks(): void {
    const box = shadow().querySelector<HTMLTextAreaElement>(".paste textarea")!;
    box.value = "12. Team Six - Bijan Robinson, RB, ATL";
    shadow().querySelector<HTMLButtonElement>(".paste button")!.click();
  }

  it("keeps the badge when a manual board's socket ALSO drops", () => {
    // Caught by looking at the rendered output: keying the badge off the displayed status word
    // made it vanish on "Reconnecting…", i.e. the caveat disappeared exactly as things got worse.
    const handle = mountOverlay({ wsFactory: noopFactory, onPaste: () => {} });
    handle.update(REC);
    pasteRealPicks();
    expect(shadow().querySelector(".badge-estimated")).not.toBeNull();

    handle.setStatus("disconnected");
    expect(shadow().querySelector(".live")!.textContent).toMatch(/reconnect/i);
    expect(shadow().querySelector(".badge-estimated")).not.toBeNull();
    handle.destroy();
  });

  it("badges a rec left on screen while the socket is only connecting", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    handle.setStatus("connecting");
    expect(shadow().querySelector(".badge-estimated")).not.toBeNull();
    handle.destroy();
  });
});

describe("overlay Why? and Pin (§6.5 anti-black-box, §6.3 advisory actions)", () => {
  // `Why?` was created, given an aria-label, appended — and never given a click handler. `onPin`
  // was invoked, but from INSIDE the copyBtn handler, and the content script passed no onPin at
  // all. Both halves of the primary action were inert.

  const WITH_MODS: Recommendation = {
    ...REC,
    ranked: [
      {
        ...REC.ranked[0]!,
        components: {
          ...REC.ranked[0]!.components!,
          modifiers: { bye_stack: -1.5, handcuff_synergy: 2 },
          reliability: 0.82,
          vona_horizon: 2,
          best_available_next: 17.4,
        },
      },
      ...REC.ranked.slice(1),
    ],
  };

  function whyBtn(): HTMLButtonElement {
    return shadow().querySelector<HTMLButtonElement>('[aria-label*="Explain" i]')!;
  }

  it("opens and closes the explanation, tracking aria-expanded", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    expect(shadow().querySelector(".why-detail")).toBeNull();
    expect(whyBtn().getAttribute("aria-expanded")).toBe("false");

    whyBtn().click();
    expect(shadow().querySelector(".why-detail")).not.toBeNull();
    expect(whyBtn().getAttribute("aria-expanded")).toBe("true");

    whyBtn().click();
    expect(shadow().querySelector(".why-detail")).toBeNull();
    handle.destroy();
  });

  it("shows the score reconciling to its terms — the anti-black-box guarantee, checkable", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    whyBtn().click();
    const text = shadow().querySelector(".why-detail")!.textContent ?? "";
    expect(text).toMatch(/reconcile/i);
    expect(text).toContain("41.2"); // the score the terms must add up to
    handle.destroy();
  });

  it("surfaces the ScoreComponents fields the bars never render", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(WITH_MODS);
    whyBtn().click();
    const text = shadow().querySelector(".why-detail")!.textContent ?? "";

    expect(text).toContain("200.0"); // floor  — risk band, invisible until now
    expect(text).toContain("300.0"); // ceiling
    expect(text).toContain("0.82"); // reliability shrinkage r_pos
    expect(text).toContain("17.4"); // E[best available next] — the VONA baseline
    expect(text).toMatch(/horizon/i);
    handle.destroy();
  });

  it("renders capped modifiers, which the why bars deliberately filter out", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(WITH_MODS);
    whyBtn().click();
    const text = shadow().querySelector(".why-detail")!.textContent ?? "";
    expect(text).toMatch(/bye stack/i);
    expect(text).toMatch(/handcuff/i);
    handle.destroy();
  });

  it("repaints the open explanation when a new recommendation arrives", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(REC);
    whyBtn().click();
    expect(shadow().querySelector(".why-detail")!.textContent).not.toContain("0.82");

    handle.update(WITH_MODS);
    expect(shadow().querySelector(".why-detail")!.textContent).toContain("0.82");
    handle.destroy();
  });

  it("pins from its OWN control, not by riding the Copy handler", () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const onPin = vi.fn();
    const handle = mountOverlay({ wsFactory: noopFactory, onPin });
    handle.update(REC);

    const pin = shadow().querySelector<HTMLButtonElement>(".ov-pin")!;
    expect(pin.textContent).toMatch(/pin/i);
    pin.click();
    expect(onPin).toHaveBeenCalledTimes(1);
    expect(onPin.mock.calls[0]![0].player_id).toBe("p1");
    expect(writeText).not.toHaveBeenCalled(); // pinning is not copying

    handle.destroy();
    vi.unstubAllGlobals();
  });

  it("copies without pinning, so the two intents stay separable", () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const onPin = vi.fn();
    const handle = mountOverlay({ wsFactory: noopFactory, onPin });
    handle.update(REC);

    shadow().querySelector<HTMLButtonElement>(".btn-primary")!.click();
    expect(writeText).toHaveBeenCalledWith("James Cook");
    expect(onPin).not.toHaveBeenCalled();

    handle.destroy();
    vi.unstubAllGlobals();
  });

  it("does not pin when there is no recommendation yet", () => {
    const onPin = vi.fn();
    const handle = mountOverlay({ wsFactory: noopFactory, onPin });
    shadow().querySelector<HTMLButtonElement>(".ov-pin")!.click();
    expect(onPin).not.toHaveBeenCalled();
    handle.destroy();
  });
});

describe("overlay projection provenance (§5 live-data honesty)", () => {
  // After Tier 1 the live board has 314 players backed by {ecr,xep}, 63 by {xep} — and 70 by
  // {ecr} ONLY, i.e. no modeled projection at all. `sources` never left the backend, so all three
  // groups rendered identically and the owner could not tell a projection from a rank guess.

  function withSources(name: string, sources: string[] | null): Recommendation {
    return {
      ...REC,
      ranked: [{ ...REC.ranked[0]!, name, projection_sources: sources }, ...REC.ranked.slice(1)],
    };
  }

  it("marks an ECR-only pick as having no modeled projection", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(withSources("Fallback Guy", ["ecr"]));
    const chip = shadow().querySelector(".prov-chip");
    expect(chip).not.toBeNull();
    expect(chip!.textContent).toMatch(/ECR only/i);
    handle.destroy();
  });

  it("leaves an xEP-backed pick unmarked, so the flag means something", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(withSources("Real Projection Guy", ["ecr", "xep"]));
    expect(shadow().querySelector(".prov-chip")).toBeNull();
    handle.destroy();
  });

  it("clears the mark when the next pick IS backed", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(withSources("Fallback Guy", ["ecr"]));
    expect(shadow().querySelector(".prov-chip")).not.toBeNull();

    handle.update(withSources("Real Projection Guy", ["ecr", "xep"]));
    expect(shadow().querySelector(".prov-chip")).toBeNull();
    handle.destroy();
  });

  it("shows nothing at all when provenance is unknown, rather than guessing", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(withSources("Unknown Guy", null));
    expect(shadow().querySelector(".prov-chip")).toBeNull();
    handle.destroy();
  });

  it("names the actual sources in the Why? panel either way", () => {
    const handle = mountOverlay({ wsFactory: noopFactory });
    handle.update(withSources("Real Projection Guy", ["ecr", "xep"]));
    shadow().querySelector<HTMLButtonElement>('[aria-label*="Explain" i]')!.click();
    expect(shadow().querySelector(".why-detail")!.textContent).toContain("ECR + xEP");

    handle.update(withSources("Fallback Guy", ["ecr"]));
    const text = shadow().querySelector(".why-detail")!.textContent ?? "";
    expect(text).toContain("ECR only");
    expect(text).toMatch(/rank/i); // the reason it matters, not just the label
    handle.destroy();
  });
});
