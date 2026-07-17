/**
 * Record mode (Phase-1 capture tooling): when enabled (extension action toggles the
 * chrome.storage.local `jaaffl_record` flag), every observed frame + occasional DOM
 * snapshots are batched to the local backend, which writes them under
 * apps/extension/fixtures/cbs/<session>.jsonl for the one real-frame mock-draft session.
 * Raw recordings may contain league names — they are git-ignored; only redacted goldens
 * are committed (plan §5.10).
 */

const ENDPOINT = "http://127.0.0.1:8788/dev/recordings";
const FLUSH_MS = 5_000;
const DOM_SNAPSHOT_EVERY = 100; // mutations between board snapshots
const RECORD_FLAG = "jaaffl_record";

interface RecorderDeps {
  post?: (payload: unknown) => Promise<void>;
}

async function defaultPost(payload: unknown): Promise<void> {
  try {
    await fetch(ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    /* recording is best-effort; never break capture */
  }
}

export class Recorder {
  private enabled = false;
  private session = "";
  private frames: unknown[] = [];
  private mutationsSinceSnapshot = DOM_SNAPSHOT_EVERY; // snapshot on first mutation

  private readonly post: (payload: unknown) => Promise<void>;

  constructor(deps: RecorderDeps = {}) {
    this.post = deps.post ?? defaultPost;
    if (typeof chrome !== "undefined" && chrome.storage?.local) {
      void chrome.storage.local
        .get(RECORD_FLAG)
        .then((v) => this.setEnabled(Boolean(v[RECORD_FLAG])));
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area === "local" && RECORD_FLAG in changes) {
          this.setEnabled(Boolean(changes[RECORD_FLAG]?.newValue));
        }
      });
    }
    setInterval(() => void this.flush(), FLUSH_MS);
  }

  setEnabled(on: boolean): void {
    if (on && !this.enabled) {
      this.session = `rec-${new Date().toISOString().replace(/[:.]/g, "-")}`;
      console.info(`[jaaffl] record mode ON -> ${this.session}`);
    }
    if (!on && this.enabled) void this.flush();
    this.enabled = on;
  }

  record(kind: string, payload: unknown): void {
    if (!this.enabled) return;
    this.frames.push({ kind, ts: Date.now(), payload });
  }

  /** Board snapshots are throttled — frames matter most; DOM shape lands occasionally. */
  recordDomSnapshot(el: Element | null): void {
    if (!this.enabled || !el) return;
    if (++this.mutationsSinceSnapshot < DOM_SNAPSHOT_EVERY) return;
    this.mutationsSinceSnapshot = 0;
    this.frames.push({
      kind: "dom-snapshot",
      ts: Date.now(),
      payload: { html: (el as HTMLElement).outerHTML.slice(0, 500_000) },
    });
  }

  async flush(): Promise<void> {
    if (!this.frames.length) return;
    const batch = this.frames.splice(0);
    await this.post({ session: this.session, frames: batch });
  }
}
