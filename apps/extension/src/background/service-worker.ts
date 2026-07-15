// MV3 service worker. Coordinates extension lifecycle; the live-draft work happens in the
// content scripts. Kept minimal for the prototype.

chrome.runtime.onInstalled.addListener(() => {
  console.debug("[jaaffl] extension installed");
});
