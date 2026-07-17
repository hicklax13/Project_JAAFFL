#!/usr/bin/env node
/**
 * Generate the overlay's inlined design tokens FROM the single canonical source
 * (design/tokens/draft-room.css) into a committed TS string module the overlay imports.
 *
 * Why generate instead of importing the .css directly: the overlay lives in a Shadow DOM
 * and must inline its CSS as a string, but Vitest stubs `.css` imports (even `?raw`) to
 * empty, and a cross-package `?raw` is fragile. A committed generated module is bulletproof
 * across build + vitest + tsc, and mirrors the repo's existing E5 "export + git diff" gate:
 * the drift guard (apps/extension/tests/overlay-tokens.test.ts) fails if this file is stale.
 *
 * Usage:  node scripts/gen-overlay-tokens.mjs         (write)
 *         node scripts/gen-overlay-tokens.mjs --check (exit 1 if stale; used ad hoc)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const CANONICAL = join(ROOT, "design", "tokens", "draft-room.css");
const OUT = join(ROOT, "apps", "extension", "src", "overlay", "draft-room-tokens.ts");

// Normalize to LF so the artifact is identical on Windows (dev) and Linux (CI).
const css = readFileSync(CANONICAL, "utf8").replace(/\r\n/g, "\n");

const banner =
  "// GENERATED FROM design/tokens/draft-room.css — DO NOT EDIT BY HAND.\n" +
  "// Regenerate after editing the canonical token file:  pnpm gen:tokens\n" +
  "//\n" +
  "// The overlay inlines this string into its Shadow-DOM <style> so it stays fully\n" +
  "// self-contained ($0 / local-first / no external CSS or CDN). The drift guard in\n" +
  "// apps/extension/tests/overlay-tokens.test.ts fails if this file falls out of sync.\n\n";
const contents = `${banner}export const DRAFT_ROOM_CSS = ${JSON.stringify(css)};\n`;

if (process.argv.includes("--check")) {
  const current = readFileSync(OUT, "utf8").replace(/\r\n/g, "\n");
  if (current !== contents) {
    console.error("draft-room-tokens.ts is STALE — run `pnpm gen:tokens`.");
    process.exit(1);
  }
  console.log("draft-room-tokens.ts is up to date.");
} else {
  writeFileSync(OUT, contents, "utf8");
  console.log(`wrote ${OUT} (${css.length} chars of CSS)`);
}
