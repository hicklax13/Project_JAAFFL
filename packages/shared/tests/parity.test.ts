/**
 * E5 schema-parity gate, Zod side (plan §9.5).
 *
 * (1) Every canonical fixture under fixtures/ parses with its Zod schema — the SAME files
 * the backend validates with Pydantic (backend/tests/test_schema_parity.py).
 * (2) Each checked-in Pydantic JSON Schema under schemas/ is structurally equal to the
 * schema derived from the Zod mirror: field names, types, required/optional, enum members.
 * Pydantic is the source of truth; regenerate with scripts/export_schemas.py.
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { ZodTypeAny } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";

import {
  DraftEventSchema,
  DraftPickSchema,
  DraftStateSchema,
  LeagueSettingsSchema,
  PositionSchema,
  RecommendationSchema,
  RecommendedPickSchema,
  RosterSlotSchema,
  ScoringRuleSchema,
} from "../src/index";
import { normalizeSchema } from "./normalize";

/** The contract surface (§9.5) — must match CONTRACT_MODELS in scripts/export_schemas.py. */
const CONTRACT_SCHEMAS: Record<string, ZodTypeAny> = {
  Position: PositionSchema,
  RosterSlot: RosterSlotSchema,
  ScoringRule: ScoringRuleSchema,
  LeagueSettings: LeagueSettingsSchema,
  DraftPick: DraftPickSchema,
  DraftState: DraftStateSchema,
  DraftEvent: DraftEventSchema,
  RecommendedPick: RecommendedPickSchema,
  Recommendation: RecommendationSchema,
};

const names = Object.keys(CONTRACT_SCHEMAS);

function load(relative: string): unknown {
  return JSON.parse(readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf-8"));
}

function jsonStems(relativeDir: string): string[] {
  const dir = fileURLToPath(new URL(relativeDir, import.meta.url));
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(/\.json$/, ""))
    .sort();
}

describe("canonical fixtures parse under Zod (same files Pydantic validates)", () => {
  it.each(names)("%s fixture parses", (name) => {
    const fixture = load(`../fixtures/${name}.json`);
    expect(() => CONTRACT_SCHEMAS[name]!.parse(fixture)).not.toThrow();
  });

  it("fixture set covers exactly the contract surface", () => {
    expect(jsonStems("../fixtures")).toEqual([...names].sort());
  });
});

describe("Pydantic JSON Schema ≡ Zod-derived schema (structural)", () => {
  it.each(names)("%s schemas are structurally equal", (name) => {
    const pydantic = load(`../schemas/${name}.json`) as Record<string, unknown>;
    const zod = zodToJsonSchema(CONTRACT_SCHEMAS[name]!, {
      target: "jsonSchema7",
      $refStrategy: "none",
    }) as Record<string, unknown>;
    expect(normalizeSchema(zod)).toEqual(normalizeSchema(pydantic));
  });

  it("checked-in schema set covers exactly the contract surface", () => {
    expect(jsonStems("../schemas")).toEqual([...names].sort());
  });
});
