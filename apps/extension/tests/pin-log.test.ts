/**
 * The advisory pin log (plan §6.3): "Pin my pick" is a LOCAL-LOG WRITE and never a CBS submit.
 * `onPin` was invoked from inside the copy handler and the content script passed no `onPin` at
 * all, so nothing was ever recorded anywhere.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RecommendedPick } from "@jaaffl/shared";

import { PIN_LOG_KEY, PIN_LOG_MAX, recordPinnedPick } from "../src/lib/pin-log";

const PICK: RecommendedPick = {
  player_id: "gsis:00-0036223",
  name: "James Cook",
  position: "RB",
  nfl_team: "BUF",
  score: 41.2,
};

function fakeStorage(initial: Record<string, unknown> = {}) {
  const store: Record<string, unknown> = { ...initial };
  return {
    store,
    get: vi.fn(async (key: string) => ({ [key]: store[key] })),
    set: vi.fn(async (patch: Record<string, unknown>) => {
      Object.assign(store, patch);
    }),
  };
}

function installChrome(storage: ReturnType<typeof fakeStorage>): void {
  vi.stubGlobal("chrome", { storage: { local: { get: storage.get, set: storage.set } } });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("recordPinnedPick", () => {
  it("appends the pinned pick to chrome.storage.local", async () => {
    const storage = fakeStorage();
    installChrome(storage);

    await recordPinnedPick(PICK, 1_700_000_000_000);

    const log = storage.store[PIN_LOG_KEY] as Array<Record<string, unknown>>;
    expect(log).toHaveLength(1);
    expect(log[0]).toMatchObject({
      player_id: "gsis:00-0036223",
      name: "James Cook",
      position: "RB",
      score: 41.2,
      pinned_at: 1_700_000_000_000,
    });
  });

  it("keeps earlier pins so the log reads as a draft history", async () => {
    const storage = fakeStorage();
    installChrome(storage);

    await recordPinnedPick(PICK, 1);
    await recordPinnedPick({ ...PICK, player_id: "p2", name: "Drake London" }, 2);

    const log = storage.store[PIN_LOG_KEY] as Array<Record<string, unknown>>;
    expect(log.map((e) => e.name)).toEqual(["James Cook", "Drake London"]);
  });

  it("caps the log so a stuck click cannot grow storage without bound", async () => {
    const storage = fakeStorage({
      [PIN_LOG_KEY]: Array.from({ length: PIN_LOG_MAX }, (_, i) => ({ player_id: `old${i}` })),
    });
    installChrome(storage);

    await recordPinnedPick(PICK, 9);

    const log = storage.store[PIN_LOG_KEY] as Array<Record<string, unknown>>;
    expect(log).toHaveLength(PIN_LOG_MAX);
    expect(log[log.length - 1]).toMatchObject({ player_id: "gsis:00-0036223" });
    expect(log[0]).toMatchObject({ player_id: "old1" }); // oldest dropped
  });

  it("no-ops outside an extension context instead of throwing", async () => {
    // The overlay also mounts in tests and on plain pages, where there is no chrome.storage.
    await expect(recordPinnedPick(PICK, 1)).resolves.toBeUndefined();
  });

  it("survives a corrupted log rather than losing the pin", async () => {
    const storage = fakeStorage({ [PIN_LOG_KEY]: "not an array" });
    installChrome(storage);

    await recordPinnedPick(PICK, 3);

    const log = storage.store[PIN_LOG_KEY] as Array<Record<string, unknown>>;
    expect(Array.isArray(log)).toBe(true);
    expect(log).toHaveLength(1);
  });
});
