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
