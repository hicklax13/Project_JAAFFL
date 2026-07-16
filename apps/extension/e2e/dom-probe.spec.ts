/**
 * E4 (plan §9.4): Playwright drives the saved draft-room HTML fixture through a REAL
 * Chromium — the MutationObserver DOM-probe path. parse.ts is bundled to an IIFE and
 * injected, then exercised exactly as the isolated content script uses it.
 */
import { expect, test } from "@playwright/test";
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BOARD = pathToFileURL(join(HERE, "../tests/fixtures/draft-board.html")).href;

let parseBundle: string;

test.beforeAll(async () => {
  const result = await build({
    entryPoints: [join(HERE, "../src/lib/parse.ts")],
    bundle: true,
    write: false,
    format: "iife",
    globalName: "JaafflParse",
    platform: "browser",
  });
  parseBundle = result.outputFiles[0]!.text;
});

test.beforeEach(async ({ page }) => {
  await page.goto(BOARD);
  await page.addScriptTag({ content: parseBundle });
});

declare global {
  interface Window {
    JaafflParse: {
      parseDraftEvents(src: { via: "dom"; root: ParentNode }): Array<{
        event_type: string;
        pick_number?: number | null;
        source?: string | null;
        data: Record<string, unknown>;
      }>;
    };
  }
}

test("extracts every board pick AND the draft order from the saved room", async ({ page }) => {
  const events = await page.evaluate(() =>
    window.JaafflParse.parseDraftEvents({ via: "dom", root: document }),
  );
  const picks = events.filter((e) => e.event_type === "pick_made");
  expect(picks.map((p) => p.pick_number)).toEqual([1, 2, 3]);
  expect(picks.every((p) => p.source === "dom")).toBe(true);

  const order = events.find((e) => e.event_type === "league_settings");
  expect(order?.data["draft_order"]).toEqual([
    "T7", "T3", "T12", "T5", "T9", "T1", "T11", "T4", "T8", "T2", "T10", "T6",
  ]);
});

test("a MutationObserver fires on a new pick row and the parser sees it (probe 3)", async ({
  page,
}) => {
  const events = await page.evaluate(
    () =>
      new Promise<ReturnType<typeof window.JaafflParse.parseDraftEvents>>((resolve) => {
        const target = document.querySelector("#draftBoard")!;
        const observer = new MutationObserver(() => {
          observer.disconnect();
          resolve(window.JaafflParse.parseDraftEvents({ via: "dom", root: document }));
        });
        observer.observe(target, { childList: true, subtree: true, characterData: true });

        // Simulate CBS appending the next pick to the live board.
        const row = document.createElement("tr");
        row.className = "pick-row";
        row.setAttribute("data-overall", "4");
        row.setAttribute("data-round", "1");
        row.setAttribute("data-pick", "4");
        row.setAttribute("data-team-id", "T5");
        row.setAttribute("data-player-id", "3117251");
        row.setAttribute("data-player-name", "Christian McCaffrey");
        row.setAttribute("data-player-team", "SF");
        row.setAttribute("data-position", "RB");
        document.querySelector(".picks tbody")!.appendChild(row);
      }),
  );
  const picks = events.filter((e) => e.event_type === "pick_made");
  expect(picks.map((p) => p.pick_number)).toEqual([1, 2, 3, 4]);
  expect(picks[3]!.data["player_name"]).toBe("Christian McCaffrey");
});

test("an unreadable order yields NO order event — a snake is never synthesized (A5)", async ({
  page,
}) => {
  const events = await page.evaluate(() => {
    document.querySelector(".draft-order")?.remove();
    return window.JaafflParse.parseDraftEvents({ via: "dom", root: document });
  });
  expect(events.find((e) => e.event_type === "league_settings")).toBeUndefined();
  expect(events.filter((e) => e.event_type === "pick_made").length).toBeGreaterThan(0);
});
