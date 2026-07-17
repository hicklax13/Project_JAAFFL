/**
 * E4 (plan §9.4), extended: Playwright drives the REAL overlay through Chromium. The overlay is
 * bundled to an IIFE and injected, then mountOverlay() + handle.update(rec) exercises exactly the
 * render path a WS /recs/ws push takes (onRecommendation -> update). Asserts the recommended pick,
 * the ScoreComponents "why" bars, and next-turn survival paint into the isolated Shadow DOM, and
 * that the primary action is advisory (no CBS submit).
 */
import { expect, test } from "@playwright/test";
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

const REC = {
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

let overlayBundle: string;

test.beforeAll(async () => {
  const result = await build({
    entryPoints: [join(HERE, "../src/overlay/overlay.ts")],
    bundle: true,
    write: false,
    format: "iife",
    globalName: "JaafflOverlay",
    platform: "browser",
  });
  overlayBundle = result.outputFiles[0]!.text;
});

test.beforeEach(async ({ page }) => {
  await page.setContent("<!doctype html><html><body></body></html>");
  await page.addScriptTag({ content: overlayBundle });
});

declare global {
  interface Window {
    JaafflOverlay: {
      mountOverlay(opts?: Record<string, unknown>): {
        update(rec: unknown): void;
        destroy(): void;
      };
    };
  }
}

test("renders a pushed recommendation with its decomposition into the Shadow DOM", async ({
  page,
}) => {
  const result = await page.evaluate((rec) => {
    // Prevent a real localhost socket attempt in the sandbox: stub WebSocket to a no-op.
    class NoopWs {
      addEventListener() {}
      send() {}
      close() {}
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = NoopWs;

    const handle = window.JaafflOverlay.mountOverlay();
    handle.update(rec);
    const shadow = document.getElementById("jaaffl-overlay")!.shadowRoot!;
    return {
      text: shadow.textContent ?? "",
      scFills: shadow.querySelectorAll(".sc-fill").length,
      primaryLabel: shadow.querySelector(".btn-primary")?.textContent ?? "",
      hasStyleTokens: (shadow.querySelector("style")?.textContent ?? "").includes("--brass-solid"),
    };
  }, REC);

  expect(result.text).toContain("James Cook"); // recommended pick
  expect(result.text).toContain("41.2"); // brass score
  expect(result.text).toContain("18%"); // survival to next pick
  expect(result.text).toContain("Drake London"); // top-5 alternative
  expect(result.scFills).toBeGreaterThanOrEqual(4); // MLV/VONA/Risk/Cliff bars
  expect(result.primaryLabel).toMatch(/copy name/i); // advisory, not a CBS submit
  expect(result.hasStyleTokens).toBe(true); // self-contained design tokens inlined
});
