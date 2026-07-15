import type { DraftEvent } from "@jaaffl/shared";

const API_BASE = "http://127.0.0.1:8787";

/**
 * POST a normalized draft event to the local companion service.
 *
 * Fails soft: if the backend isn't running the overlay simply shows no guidance, rather
 * than throwing into the CBS page.
 */
export async function sendEvent(event: DraftEvent): Promise<void> {
  try {
    await fetch(`${API_BASE}/draft/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(event),
    });
  } catch (err) {
    console.warn("[jaaffl] failed to reach companion service", err);
  }
}
