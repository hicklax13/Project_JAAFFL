/**
 * The advisory pin log (plan §6.3 / §6.8).
 *
 * "Pin my pick" is a LOCAL-LOG WRITE and nothing else — it records the owner's intent so the
 * draft can be reviewed afterwards. It NEVER submits a pick to CBS, and this module is the reason
 * that is checkable: it talks only to `chrome.storage.local`, has no network surface at all, and
 * cannot reach the page.
 */
import type { RecommendedPick } from "@jaaffl/shared";

export const PIN_LOG_KEY = "jaaffl_pin_log";
/** 17 rounds is the whole draft; the slack absorbs re-pins without letting a stuck click grow. */
export const PIN_LOG_MAX = 64;

export interface PinnedPick {
  player_id: string;
  name: string | null;
  position: string | null;
  score: number;
  pinned_at: number;
}

/**
 * Append ``pick`` to the local pin log, oldest-dropped-first past ``PIN_LOG_MAX``.
 *
 * Best-effort by design: outside an extension context (tests, plain pages) there is no
 * `chrome.storage` and this no-ops rather than throwing — an advisory log must never be able to
 * break the surface that writes to it.
 */
export async function recordPinnedPick(pick: RecommendedPick, now: number): Promise<void> {
  if (typeof chrome === "undefined" || !chrome.storage?.local) return;

  const stored = await chrome.storage.local.get(PIN_LOG_KEY);
  const previous = stored[PIN_LOG_KEY];
  // A corrupted value must cost the owner one log, not the pin they just made.
  const log: PinnedPick[] = Array.isArray(previous) ? (previous as PinnedPick[]) : [];

  log.push({
    player_id: pick.player_id,
    name: pick.name ?? null,
    position: pick.position ?? null,
    score: pick.score,
    pinned_at: now,
  });
  await chrome.storage.local.set({ [PIN_LOG_KEY]: log.slice(-PIN_LOG_MAX) });
}
