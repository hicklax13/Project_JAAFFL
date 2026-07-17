/**
 * Drift guard (plan §6.1 / §6.8): the overlay's inlined tokens are GENERATED from the ONE
 * canonical source (design/tokens/draft-room.css) via scripts/gen-overlay-tokens.mjs. This
 * test fails if the committed generated module falls out of sync with the canonical file,
 * so the Shadow-DOM copy can never silently diverge from the web dashboard's tokens. If it
 * fails, run `pnpm gen:tokens`. (Mirrors the repo's E5 schema-parity "export + diff" gate.)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { describe, expect, it } from "vitest";

import { DRAFT_ROOM_CSS } from "../src/overlay/draft-room-tokens";

const lf = (s: string): string => s.replace(/\r\n/g, "\n");

/** Ascend from the vitest cwd (the package dir) to the repo root and read the canonical
 * token file. cwd-relative so it works under happy-dom (where import.meta.url is http:). */
function readCanonicalTokens(): string {
  let dir = process.cwd();
  for (let i = 0; i < 8; i++) {
    try {
      return readFileSync(join(dir, "design", "tokens", "draft-room.css"), "utf8");
    } catch {
      dir = dirname(dir);
    }
  }
  throw new Error(`canonical draft-room.css not found from ${process.cwd()}`);
}

describe("draft-room token single-source", () => {
  it("inlines the canonical token file verbatim (no drift)", () => {
    expect(lf(DRAFT_ROOM_CSS)).toBe(lf(readCanonicalTokens()));
  });

  it("carries the load-bearing tokens and the score-component classes", () => {
    // A regression backstop: the surfaces bind to these names (§6.1 / §6.5).
    for (const token of ["--brass-solid", "--pos-rb", "--critical", "--pine", "--sc-label-w"]) {
      expect(DRAFT_ROOM_CSS).toContain(token);
    }
    for (const cls of [".sc-fill", ".sc-mid", ".pos-DST", ".stat-pill", ".is-critical"]) {
      expect(DRAFT_ROOM_CSS).toContain(cls);
    }
  });
});
