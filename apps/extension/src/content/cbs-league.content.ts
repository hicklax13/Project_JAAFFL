/**
 * Runs on CBS fantasy LEAGUE pages (not the draft room) — e.g. the league home and `/rules`,
 * which is where CBS renders the real scoring + roster settings.
 *
 * Two jobs:
 *  1. Emit a `league_settings` event once the settings DOM can actually be read. Still a quiet
 *     no-op: `parseLeagueSettings` returns null until the TODO(capture) settings-page selectors
 *     land (stage 2).
 *  2. Capture the page under record mode, which is what UNBLOCKS (1). Those selectors can't be
 *     written until we've seen a real settings page, and the 2026-07-24 draft-room capture did not
 *     include one — it only covered `wss://k8s-draft…` frames.
 *
 * The snapshot goes through `snapshotOnEnable`, NOT `recordDomSnapshot`: a settings page is static
 * and renders once, while the record flag resolves asynchronously from chrome.storage. A plain
 * load-time snapshot would be dropped before `enabled` ever flipped — capturing nothing while the
 * REC badge looked perfectly healthy. See record.ts for the full rationale.
 */
import { parseLeagueSettings } from "../lib/parse";
import { Recorder } from "../lib/record";
import { sendEvent } from "../lib/transport";

const recorder = new Recorder(); // record mode: action toggle -> fixture capture

// `documentElement`, not `body`, so the settings tables keep their surrounding markup.
recorder.snapshotOnEnable(document.documentElement);

const settings = parseLeagueSettings(document);
if (settings) {
  void sendEvent({
    event_type: "league_settings",
    league_id: settings.league_id,
    source: "dom",
    data: settings as unknown as Record<string, unknown>,
  });
} else {
  console.debug("[jaaffl] league settings not parsed yet (stage 2 TODO) — page captured for it");
}
