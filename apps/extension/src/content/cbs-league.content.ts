import { parseLeagueSettings } from "../lib/parse";
import { sendEvent } from "../lib/transport";

// Runs on CBS fantasy league pages. Emits a league_settings event once it can read them.
// (Full settings-page DOM parsing is stage 2 — parseLeagueSettings returns null until the
// TODO(capture) selectors land, and this stays a quiet no-op.)
const settings = parseLeagueSettings(document);
if (settings) {
  void sendEvent({
    event_type: "league_settings",
    league_id: settings.league_id,
    source: "dom",
    data: settings as unknown as Record<string, unknown>,
  });
} else {
  console.debug("[jaaffl] league settings not parsed yet (stage 2 TODO)");
}
