/**
 * Normalize a JSON Schema (Pydantic `model_json_schema()` output OR zod-to-json-schema
 * output) into a canonical type descriptor so the two can be compared structurally.
 *
 * Per plan §9.5 the comparison covers field names, types, required/optional, and enum
 * members — NOT titles, descriptions, defaults, or numeric bounds. Both encodings of
 * nullability (`anyOf: [X, {type:"null"}]` and `type: ["string","null"]`) collapse to the
 * same descriptor, and `$ref`s are resolved inline.
 */

type Desc =
  | { kind: "any" }
  | { kind: "null" }
  | { kind: "number" | "integer" | "string" | "boolean" }
  | { kind: "enum"; values: string[] }
  | { kind: "nullable"; inner: Desc }
  | { kind: "array"; items: Desc }
  | { kind: "record"; values: Desc }
  | { kind: "object"; properties: Record<string, Desc>; required: string[] }
  | { kind: "union"; options: Desc[] };

export function normalizeSchema(root: Record<string, unknown>): Desc {
  const defs = collectDefs(root);

  function resolve(node: unknown): Record<string, unknown> {
    let current = node as Record<string, unknown>;
    const seen = new Set<string>();
    while (typeof current?.["$ref"] === "string") {
      const ref = current["$ref"] as string;
      if (seen.has(ref)) throw new Error(`circular $ref: ${ref}`);
      seen.add(ref);
      const name = ref.split("/").pop()!;
      const target = defs[name];
      if (!target) throw new Error(`unresolvable $ref: ${ref}`);
      current = target;
    }
    return current;
  }

  function normalize(rawNode: unknown): Desc {
    const node = resolve(rawNode);

    // Pydantic wraps referenced sub-models in a single-element allOf when the field
    // carries metadata; unwrap it. Anything wider is an encoding this normalizer does
    // not understand — throw rather than degrade to "any" and pass vacuously.
    const allOf = node["allOf"] as unknown[] | undefined;
    if (Array.isArray(allOf)) {
      if (allOf.length === 1 && !node["properties"]) return normalize(allOf[0]);
      throw new Error(`unhandled allOf shape: ${JSON.stringify(node)}`);
    }

    const anyOf = (node["anyOf"] ?? node["oneOf"]) as unknown[] | undefined;
    if (Array.isArray(anyOf)) {
      const options = anyOf.map(normalize);
      const nonNull = options.filter((o) => o.kind !== "null");
      const hasNull = nonNull.length !== options.length;
      const inner: Desc =
        nonNull.length === 1 ? nonNull[0]! : { kind: "union", options: sortDescs(nonNull) };
      return hasNull ? { kind: "nullable", inner } : inner;
    }

    if (Array.isArray(node["enum"])) {
      return { kind: "enum", values: [...(node["enum"] as string[])].sort() };
    }
    if (node["const"] !== undefined) {
      return { kind: "enum", values: [String(node["const"])] };
    }

    let type = node["type"];
    // JSON Schema allows omitting "type" when object keywords make it unambiguous.
    if (type === undefined && (node["properties"] || node["additionalProperties"])) {
      type = "object";
    }
    // type: ["number","null"] — the array encoding of nullability.
    if (Array.isArray(type)) {
      const nonNull = type.filter((t) => t !== "null");
      const hasNull = nonNull.length !== type.length;
      const inner = normalize({ ...node, type: nonNull.length === 1 ? nonNull[0] : nonNull });
      return hasNull ? { kind: "nullable", inner } : inner;
    }

    switch (type) {
      case "null":
        return { kind: "null" };
      case "number":
      case "integer":
      case "string":
      case "boolean":
        return { kind: type };
      case "array":
        return { kind: "array", items: node["items"] ? normalize(node["items"]) : { kind: "any" } };
      case "object": {
        const props = node["properties"] as Record<string, unknown> | undefined;
        if (props && Object.keys(props).length > 0) {
          const properties: Record<string, Desc> = {};
          for (const key of Object.keys(props).sort()) {
            properties[key] = normalize(props[key]);
          }
          const required = [...((node["required"] as string[] | undefined) ?? [])].sort();
          return { kind: "object", properties, required };
        }
        const ap = node["additionalProperties"];
        if (ap && typeof ap === "object" && Object.keys(ap).length > 0) {
          return { kind: "record", values: normalize(ap) };
        }
        return { kind: "record", values: { kind: "any" } };
      }
      case undefined: {
        // Bare {} means "any" (e.g. record values of z.unknown()). A typeless node that
        // still carries structural keywords is an unhandled encoding — throw, don't pass.
        const unhandled = ["items", "prefixItems", "patternProperties", "not", "contains"]
          .filter((key) => node[key] !== undefined);
        if (unhandled.length > 0) {
          throw new Error(`typeless node with unhandled keywords: ${unhandled.join(", ")}`);
        }
        return { kind: "any" };
      }
      default:
        throw new Error(`unhandled schema node type: ${JSON.stringify(type)}`);
    }
  }

  return normalize(root);
}

function collectDefs(root: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const defs: Record<string, Record<string, unknown>> = {};
  for (const key of ["$defs", "definitions"]) {
    const bucket = root[key] as Record<string, Record<string, unknown>> | undefined;
    if (bucket) Object.assign(defs, bucket);
  }
  return defs;
}

function sortDescs(descs: Desc[]): Desc[] {
  return [...descs].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}
