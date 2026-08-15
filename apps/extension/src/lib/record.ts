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

/** `location.href` is unavailable in some test/worker contexts — never let capture throw. */
function pageUrl(): string {
  try {
    return typeof location !== "undefined" ? location.href : "";
  } catch {
    return "";
  }
}

const MAX_SNAPSHOT_CHARS = 500_000;

/** One dom-snapshot payload: the html, WHERE it came from, and whether it was cut. */
function snapshotPayload(el: Element): Record<string, unknown> {
  const full = (el as HTMLElement).outerHTML;
  return {
    html: full.slice(0, MAX_SNAPSHOT_CHARS),
    url: pageUrl(),
    truncated: full.length > MAX_SNAPSHOT_CHARS,
    full_length: full.length,
  };
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
  /** Element awaiting the first enable — see {@link snapshotOnEnable}. Cleared once captured. */
  private pendingSnapshot: Element | null = null;

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
    // A one-shot snapshot requested before the async flag read resolved now gets its chance.
    if (on && this.pendingSnapshot) {
      const el = this.pendingSnapshot;
      this.pendingSnapshot = null; // once only — a later off/on must not resurrect a stale page
      this.recordDomSnapshot(el);
    }
  }

  /**
   * Snapshot ``el`` as soon as recording is on — immediately if it already is, otherwise the
   * moment the flag flips.
   *
   * Why this exists: ``enabled`` is resolved ASYNCHRONOUSLY from ``chrome.storage.local``, so at
   * content-script execution time it is still false. The draft page gets away with a plain
   * ``recordDomSnapshot`` because it records ongoing frames and mutations that all arrive after the
   * flag settles. A league SETTINGS page is static — it renders once — so a load-time snapshot
   * would be silently dropped and the capture would come back empty while the REC badge looked
   * perfectly healthy. Deferring until enabled closes that race.
   */
  snapshotOnEnable(el: Element | null): void {
    if (!el) return;
    if (this.enabled) {
      this.recordDomSnapshot(el);
      return;
    }
    this.pendingSnapshot = el;
  }

  record(kind: string, payload: unknown): void {
    if (!this.enabled) return;
    this.frames.push({ kind, ts: Date.now(), payload });
  }

  /** Board snapshots are throttled — frames matter most; DOM shape lands occasionally.
   *
   * Records the URL and whether the HTML was cut. Both were missing, and both cost real evidence
   * in the 2026-08-15 capture: all 15 snapshots carried `{html}` alone, so nothing said which page
   * they came from, and every one was EXACTLY 500,000 chars — all of them silently truncated. A
   * crosswalk miss then looks like "CBS never rendered it" rather than "we threw it away". The cap
   * stays (a 12-team draft can emit a lot of these); what changes is that it no longer lies. */
  recordDomSnapshot(el: Element | null): void {
    if (!this.enabled || !el) return;
    if (++this.mutationsSinceSnapshot < DOM_SNAPSHOT_EVERY) return;
    this.mutationsSinceSnapshot = 0;
    this.frames.push({ kind: "dom-snapshot", ts: Date.now(), payload: snapshotPayload(el) });
  }

  /** An uncaught extension error, so a content-script crash leaves a trace somewhere.
   *
   * Before this the extension had NO error capture: no `window.onerror`, no `unhandledrejection`,
   * no console forwarding, and the recorder emitted exactly one kind. An uncaught error in the
   * content script was invisible in the backend log, in the capture AND in the rehearsal report —
   * the overlay just stopped updating and read as merely stale. `unhandledrejection` also hands
   * you whatever was rejected, which is frequently not an Error, so this takes `unknown`. */
  recordError(error: unknown, source: string): void {
    if (!this.enabled) return;
    const err = error instanceof Error ? error : undefined;
    this.frames.push({
      kind: "extension-error",
      ts: Date.now(),
      payload: {
        message: err ? `${err.name}: ${err.message}` : String(error),
        stack: err?.stack ?? null,
        source,
        url: pageUrl(),
      },
    });
  }

  async flush(): Promise<void> {
    if (!this.frames.length) return;
    const batch = this.frames.splice(0);
    await this.post({ session: this.session, frames: batch });
  }
}
