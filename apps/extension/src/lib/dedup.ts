/**
 * Cross-probe de-dup (plan §5.5): the validate → de-dup → send tail every probe AND
 * manual paste converge on. First probe to report a given pick_number wins — picks are
 * immutable once made. The backend's SQLite unique index is the durable de-dup of
 * record; this Set is the cheap first line.
 */

import { DraftEventSchema, type DraftEvent } from "@jaaffl/shared";

export function dedupKey(ev: DraftEvent): string {
  if (ev.event_type === "pick_made" && ev.pick_number != null) {
    return `pick:${ev.pick_number}`;
  }
  if (ev.event_type === "on_the_clock") {
    return `otc:${(ev.data as Record<string, unknown>)["current_overall_pick"]}`;
  }
  if (ev.event_type === "draft_state") {
    return `state:${(ev.data as Record<string, unknown>)["current_overall_pick"]}`;
  }
  return `${ev.event_type}:${JSON.stringify(ev.data ?? {})}`;
}

/** Validate (Zod = the trust-boundary gate) → de-dup → send. */
export function createForwarder(send: (event: DraftEvent) => void): (candidate: unknown) => void {
  const seen = new Set<string>();
  return (candidate: unknown) => {
    const result = DraftEventSchema.safeParse(candidate);
    if (!result.success) {
      console.debug("[jaaffl] dropped invalid event", result.error.issues);
      return;
    }
    const key = dedupKey(result.data);
    if (seen.has(key)) return;
    seen.add(key);
    send(result.data);
  };
}
