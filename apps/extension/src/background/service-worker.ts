// MV3 service worker — deliberately minimal (plan §5.5: the content script owns the
// localhost socket to sidestep the SW lifecycle). Responsibilities: the record-mode
// toggle (action click) and, if @crxjs ever mangles the static MAIN-world entry, the
// plan-B dynamic registration (§5.3) — disabled while the static path works.

const RECORD_FLAG = "jaaffl_record";
const ENABLE_PLAN_B_MAIN_REGISTRATION = false;

chrome.runtime.onInstalled.addListener(() => {
  console.debug("[jaaffl] extension installed");
  if (ENABLE_PLAN_B_MAIN_REGISTRATION) {
    void registerMainWorldInjector();
  }
});

// Action click toggles record mode: content scripts watch this flag and stream observed
// frames to the local backend for golden-fixture capture (src/lib/record.ts).
chrome.action.onClicked.addListener(() => {
  void (async () => {
    const stored = await chrome.storage.local.get(RECORD_FLAG);
    const next = !stored[RECORD_FLAG];
    await chrome.storage.local.set({ [RECORD_FLAG]: next });
    await chrome.action.setBadgeText({ text: next ? "REC" : "" });
    if (next) {
      await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
    }
  })();
});

async function registerMainWorldInjector(): Promise<void> {
  try {
    await chrome.scripting.registerContentScripts([
      {
        id: "jaaffl-main",
        js: ["src/inject/cbs-main.inject.js"],
        matches: [
          "https://*.cbssports.com/fantasy/draft/*",
          "https://*.football.cbssports.com/*draft*",
        ],
        world: "MAIN",
        runAt: "document_start",
        persistAcrossSessions: true,
      },
    ]);
  } catch (e) {
    console.warn("[jaaffl] MAIN registration failed", e);
  }
}
