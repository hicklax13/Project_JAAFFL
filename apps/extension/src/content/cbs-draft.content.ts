import { parseDraftEvent } from "../lib/parse";
import { sendEvent } from "../lib/transport";
import { mountOverlay } from "../overlay/overlay";

// Runs in the live CBS draft room: mounts the overlay and streams normalized pick events.
mountOverlay();

const observer = new MutationObserver(() => {
  const event = parseDraftEvent(document);
  if (event) void sendEvent(event);
});
observer.observe(document.body, { childList: true, subtree: true });

console.debug("[jaaffl] draft content script active");
