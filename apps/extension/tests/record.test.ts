/**
 * Record-mode capture buffer (src/lib/record.ts).
 *
 * The case that matters here is the ENABLE RACE. `Recorder` resolves its `jaaffl_record` flag
 * asynchronously from `chrome.storage.local`, so at module-execution time `enabled` is still false.
 * The draft content script never notices — it records ongoing network frames and DOM mutations,
 * which all arrive after the flag settles. But a LEAGUE settings page is static: it renders once,
 * so a one-shot snapshot taken at load would be silently dropped and the capture would come back
 * empty while the REC badge sat there looking healthy. That exact class of silent-but-green failure
 * already cost a live draft-capture session, so it gets a test.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Recorder } from "../src/lib/record";

interface Batch {
  session: string;
  frames: { kind: string; payload?: unknown }[];
}

function recorderWithSpy(): { rec: Recorder; batches: Batch[] } {
  const batches: Batch[] = [];
  const rec = new Recorder({
    post: async (payload) => {
      batches.push(payload as Batch);
    },
  });
  return { rec, batches };
}

/** A throwaway detached element to snapshot. Built with DOM methods, not innerHTML. */
function el(text = "settings"): Element {
  const wrapper = document.createElement("div");
  const p = document.createElement("p");
  p.textContent = text;
  wrapper.appendChild(p);
  return wrapper;
}

beforeEach(() => {
  vi.useFakeTimers(); // the constructor installs a flush interval; don't leak it across tests
});

describe("Recorder enable race", () => {
  it("captures a snapshot requested BEFORE recording was enabled", async () => {
    // The static-page case: the page renders (and asks for its snapshot) while the async
    // storage read has not yet flipped `enabled`.
    const { rec, batches } = recorderWithSpy();

    rec.snapshotOnEnable(el());
    await rec.flush();
    expect(batches).toHaveLength(0); // nothing yet — correct, recording is still off

    rec.setEnabled(true); // the storage read resolves
    await rec.flush();

    expect(batches).toHaveLength(1);
    expect(batches[0]!.frames.map((f) => f.kind)).toEqual(["dom-snapshot"]);
  });

  it("captures immediately when recording is ALREADY enabled", async () => {
    const { rec, batches } = recorderWithSpy();
    rec.setEnabled(true);

    rec.snapshotOnEnable(el());
    await rec.flush();

    expect(batches).toHaveLength(1);
    expect(batches[0]!.frames[0]!.kind).toBe("dom-snapshot");
  });

  it("never captures if recording is never enabled", async () => {
    const { rec, batches } = recorderWithSpy();

    rec.snapshotOnEnable(el());
    await rec.flush();

    expect(batches).toHaveLength(0);
  });

  it("does not re-capture the pending element on a later re-enable", async () => {
    // Toggling REC off and on again must not resurrect a stale snapshot from page load.
    const { rec, batches } = recorderWithSpy();

    rec.snapshotOnEnable(el());
    rec.setEnabled(true);
    await rec.flush();
    expect(batches).toHaveLength(1);

    rec.setEnabled(false);
    rec.setEnabled(true);
    await rec.flush();

    expect(batches).toHaveLength(1); // still just the one
  });

  it("tolerates a null element", async () => {
    const { rec, batches } = recorderWithSpy();
    rec.snapshotOnEnable(null);
    rec.setEnabled(true);
    await rec.flush();
    expect(batches).toHaveLength(0);
  });
});

describe("Recorder buffering", () => {
  it("drops frames while disabled and keeps them once enabled", async () => {
    const { rec, batches } = recorderWithSpy();

    rec.record("ws-message", { body: "dropped" });
    await rec.flush();
    expect(batches).toHaveLength(0);

    rec.setEnabled(true);
    rec.record("ws-message", { body: "kept" });
    await rec.flush();

    expect(batches).toHaveLength(1);
    expect(batches[0]!.frames).toHaveLength(1);
  });
});

/**
 * Capture QUALITY — three gaps the 2026-08-15 live rehearsal exposed while auditing the 8 MB
 * recording it produced.
 *
 * The capture is not a nice-to-have: `scripts/seed_cbs_crosswalk.py` mines it for the CBS id ->
 * player identities that let a drafted player be masked off the board. Every defense drafted that
 * night went unmasked, and recovering them depends entirely on what this file writes down.
 */
/** First batch's frames, narrowed — `batches[0]` is optional under noUncheckedIndexedAccess. */
function framesOf(batches: Batch[]): Batch["frames"] {
  const first = batches[0];
  expect(first).toBeDefined();
  return first!.frames;
}

describe("Recorder capture quality", () => {
  it("records WHICH PAGE a snapshot came from", async () => {
    // All 15 snapshots in the live capture carried `{html}` and nothing else. With no URL you
    // cannot tell a draft-room snapshot from a settings page — which is exactly what blocks the
    // still-open settings-page TODO(capture): you could not even confirm you had taken one.
    const { rec, batches } = recorderWithSpy();
    await rec.setEnabled(true);
    rec.snapshotOnEnable(el());
    await rec.flush();
    const snap = framesOf(batches).find((f) => f.kind === "dom-snapshot");
    expect(snap?.payload).toHaveProperty("url");
    expect(typeof (snap?.payload as { url: unknown }).url).toBe("string");
  });

  it("says so when it truncates, instead of cutting silently", async () => {
    // EVERY snapshot in the live capture was exactly 500,000 chars — all 15 hit the cap. Content
    // past it is discarded, and nothing recorded that it had happened, so a crosswalk miss looks
    // like "CBS never rendered it" rather than "we threw it away".
    const { rec, batches } = recorderWithSpy();
    await rec.setEnabled(true);
    const big = document.createElement("div");
    big.textContent = "x".repeat(600_000);
    rec.snapshotOnEnable(big);
    await rec.flush();
    const p = framesOf(batches).find((f) => f.kind === "dom-snapshot")?.payload as {
      truncated?: boolean;
      full_length?: number;
      html: string;
    };
    expect(p.truncated).toBe(true);
    expect(p.full_length).toBeGreaterThan(500_000);
    expect(p.html.length).toBe(500_000);
  });

  it("marks a snapshot that was NOT truncated", async () => {
    const { rec, batches } = recorderWithSpy();
    await rec.setEnabled(true);
    rec.snapshotOnEnable(el());
    await rec.flush();
    const p = framesOf(batches).find((f) => f.kind === "dom-snapshot")?.payload as {
      truncated?: boolean;
    };
    expect(p.truncated).toBe(false);
  });

  it("can record an extension error, so a content-script crash leaves a trace", async () => {
    // The extension had NO error capture at all: no window.onerror, no unhandledrejection, no
    // console forwarding, and the recorder emitted exactly one kind (`dom-snapshot`). An uncaught
    // error in the content script is therefore invisible in the backend log, in the capture and in
    // the report — the overlay simply stops updating and reads as merely stale.
    const { rec, batches } = recorderWithSpy();
    await rec.setEnabled(true);
    rec.recordError(new Error("boom"), "window.onerror");
    await rec.flush();
    const err = framesOf(batches).find((f) => f.kind === "extension-error");
    expect(err).toBeDefined();
    const p = err?.payload as { message: string; source: string; stack?: string };
    expect(p.message).toContain("boom");
    expect(p.source).toBe("window.onerror");
  });

  it("records a non-Error rejection value without throwing", async () => {
    // `unhandledrejection` hands you whatever was rejected — often not an Error.
    const { rec, batches } = recorderWithSpy();
    await rec.setEnabled(true);
    rec.recordError("plain string failure", "unhandledrejection");
    await rec.flush();
    const p = framesOf(batches).find((f) => f.kind === "extension-error")?.payload as {
      message: string;
    };
    expect(p.message).toContain("plain string failure");
  });
});
