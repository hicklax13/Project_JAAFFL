import type { DraftEvent, LeagueSettings } from "@jaaffl/shared";

/**
 * Parse CBS league settings from the current page.
 *
 * TODO(stage 2): read roster slots, flex eligibility, scoring rules, team count, and
 * explicit draft order from the DOM or the page's embedded state.
 */
export function parseLeagueSettings(_doc: Document): LeagueSettings | null {
  return null;
}

/**
 * Parse a pick / on-the-clock event from the live draft room.
 *
 * TODO(stage 1): observe the draft-board DOM (or intercepted network payloads) and emit a
 * normalized event. Draft order is read from the room, never inferred from league size.
 */
export function parseDraftEvent(_root: ParentNode): DraftEvent | null {
  return null;
}
