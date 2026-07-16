/**
 * Golden-fixture-driven normalizers (plan §5.7). Every probe funnels through ONE
 * normalizer via the discriminated RawSource union; the isolated content script is the
 * sole caller (trust boundary).
 *
 * TODO(capture): every CBS-specific message shape and DOM selector below is a SYNTHETIC
 * placeholder pinned by tests/fixtures. After the record-mode mock-draft session, swap
 * the field mappings/selectors for the real captured shapes — the capture mechanism
 * (probes/relay/de-dup/transport) must not change.
 */

import type { DraftEvent, LeagueSettings } from "@jaaffl/shared";

export type RawSource =
  | { via: "ws" | "framework" | "fetch" | "xhr"; url?: string; body: string }
  | { via: "dom"; root: ParentNode }
  | { via: "paste"; text: string };

// Arithmetic ONLY (round math from overall). The draft ORDER is never derived from this.
const IMMUTABLE_TEAM_COUNT = 12;

type NetworkVia = "ws" | "framework" | "fetch" | "xhr";

function probeSource(via: NetworkVia): "ws" | "framework" {
  // All network kinds normalize the same way; fiber snapshots keep their own provenance.
  return via === "framework" ? "framework" : "ws";
}

function roundFromOverall(overall: number): { round: number; pick_in_round: number } {
  return {
    round: Math.floor((overall - 1) / IMMUTABLE_TEAM_COUNT) + 1,
    pick_in_round: ((overall - 1) % IMMUTABLE_TEAM_COUNT) + 1,
  };
}

/** A valid overall pick is a positive integer (1..204 for 12x17). Guards every
 * overall-derivation site so one corrupt row/frame can't poison a whole event. */
function isValidOverall(value: unknown): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1;
}

/* ------------------------------------------------------------------------------------ *
 * Synthetic network-frame vocabulary — TODO(capture): map real CBS frames here.
 * ------------------------------------------------------------------------------------ */

interface SyntheticPlayer {
  id?: string | number;
  name?: string;
  team?: string;
  position?: string;
}

function playerData(player: SyntheticPlayer | undefined): Record<string, unknown> {
  if (!player) return {};
  const out: Record<string, unknown> = {};
  if (player.id != null) {
    out["player_id"] = `cbs:${player.id}`;
    out["cbs_player_id"] = String(player.id);
  }
  if (player.name) out["player_name"] = player.name;
  if (player.team) out["player_team"] = player.team;
  if (player.position) out["position"] = player.position;
  return out;
}

/** Wrap already-assembled pick `data` in the canonical pick_made envelope — the one place
 * every probe/paste path agrees on event_type + de-dup key + source. */
function pickEnvelope(
  leagueId: string,
  source: DraftEvent["source"],
  overall: number,
  data: Record<string, unknown>,
): DraftEvent {
  return {
    event_type: "pick_made",
    league_id: leagueId,
    pick_number: overall,
    source,
    data: { overall, ...data },
  };
}

function pickEvent(
  leagueId: string,
  source: DraftEvent["source"],
  pick: {
    overall: number;
    round?: number;
    pickInRound?: number;
    teamId: string;
    player?: SyntheticPlayer;
  },
): DraftEvent {
  const arithmetic = roundFromOverall(pick.overall);
  return pickEnvelope(leagueId, source, pick.overall, {
    round: pick.round ?? arithmetic.round,
    pick_in_round: pick.pickInRound ?? arithmetic.pick_in_round,
    team_id: pick.teamId,
    ...playerData(pick.player),
  });
}

function orderEvent(
  leagueId: string,
  source: DraftEvent["source"],
  order: string[],
): DraftEvent {
  // team_count is READ (counting actual teams on the board) — the order itself is the
  // in-person order entered into CBS; a snake pattern is never synthesized from it.
  return {
    event_type: "league_settings",
    league_id: leagueId,
    source,
    data: { league_id: leagueId, team_count: order.length, draft_order: order },
  };
}

function parseNetworkFrame(via: NetworkVia, body: string): DraftEvent[] {
  let frame: Record<string, unknown>;
  try {
    frame = JSON.parse(body) as Record<string, unknown>;
  } catch {
    return []; // noisy relay, silent parser — not a draft frame
  }
  if (typeof frame !== "object" || frame === null) return [];
  const source = probeSource(via);
  const leagueId = String(frame["leagueId"] ?? frame["league_id"] ?? "cbs-live");

  if (frame["type"] === "pick" && typeof frame["pick"] === "object" && frame["pick"]) {
    return [pickEvent(leagueId, source, frame["pick"] as Parameters<typeof pickEvent>[2])];
  }
  if (frame["type"] === "on_the_clock") {
    const overall = Number(frame["overall"]);
    if (!isValidOverall(overall)) return [];
    return [
      {
        event_type: "on_the_clock",
        league_id: leagueId,
        pick_number: overall,
        source,
        data: { current_overall_pick: overall, team_id: String(frame["teamId"] ?? "") },
      },
    ];
  }
  if (frame["type"] === "draft_state" || Array.isArray(frame["picks"])) {
    const rawPicks = (frame["picks"] ?? []) as Array<Record<string, unknown>>;
    const picks = rawPicks
      .filter((p) => isValidOverall(p["overall"]))
      .map((p) => {
        const overall = Number(p["overall"]);
        const arithmetic = roundFromOverall(overall);
        const player = p["player"] as SyntheticPlayer | undefined;
        return {
          overall,
          round: Number(p["round"] ?? arithmetic.round),
          pick_in_round: Number(
            p["pickInRound"] ?? p["pick_in_round"] ?? arithmetic.pick_in_round,
          ),
          team_id: String(p["teamId"] ?? p["team_id"] ?? ""),
          ...(player?.id != null ? { player_id: `cbs:${player.id}` } : {}),
        };
      });
    const events: DraftEvent[] = [
      {
        event_type: "draft_state",
        league_id: leagueId,
        source,
        data: {
          current_overall_pick: Number(
            frame["currentPick"] ?? frame["current_overall_pick"] ?? 1,
          ),
          on_the_clock_team_id: (frame["onTheClock"] ?? null) as string | null,
          picks,
        },
      },
    ];
    const order = frame["order"] ?? frame["draftOrder"];
    if (Array.isArray(order) && order.length > 0) {
      events.push(orderEvent(leagueId, source, order.map(String)));
    }
    return events;
  }
  if (frame["type"] === "league_settings") {
    const settings = mapSyntheticSettings(frame);
    if (!settings) return [];
    return [
      {
        event_type: "league_settings",
        league_id: settings.league_id,
        source,
        data: settings as unknown as Record<string, unknown>,
      },
    ];
  }
  if (frame["type"] === "draft_complete") {
    return [{ event_type: "draft_complete", league_id: leagueId, source, data: {} }];
  }
  return [];
}

/* ------------------------------------------------------------------------------------ *
 * League settings mapping — full CBS scoring map incl. DST dual tiers + K 50+ bonus.
 * ------------------------------------------------------------------------------------ */

interface SyntheticBracket {
  from: number;
  to: number | null;
  points: number;
}

function brackets(raw: SyntheticBracket[] | undefined) {
  return (raw ?? []).map((b) => ({ lower: b.from, upper: b.to, points: b.points }));
}

function mapSyntheticSettings(frame: Record<string, unknown>): LeagueSettings | null {
  // TODO(capture): real CBS settings-page payload mapping lands post-capture (stage 2
  // deepens it); the synthetic shape mirrors CBS "Standard" semantics.
  const scoring = (frame["scoring"] ?? {}) as Record<string, unknown>;
  const slots = frame["rosterSlots"] as Array<Record<string, unknown>> | undefined;
  if (!slots) return null;
  const dstPoints = brackets(scoring["dstPointsAllowed"] as SyntheticBracket[] | undefined);
  const dstYards = brackets(scoring["dstYardsAllowed"] as SyntheticBracket[] | undefined);
  const settings = {
    league_id: String(frame["leagueId"] ?? "cbs-live"),
    platform: "cbs",
    name: (frame["name"] as string) ?? null,
    team_count: Number(frame["teams"] ?? 0),
    roster_slots: slots.map((s) => ({
      slot: String(s["label"]),
      eligible_positions: (s["eligible"] as string[]) ?? [],
      count: Number(s["count"] ?? 0),
      starting: Boolean(s["starting"]),
    })),
    scoring: ((scoring["rules"] ?? []) as Array<Record<string, unknown>>).map((r) => ({
      stat: String(r["abbr"]),
      points_per_unit: Number(r["points"]),
    })),
    scoring_tiers: [
      ...(dstPoints.length
        ? [{ stat: "dst_points_allowed", applies_to: ["DST"], brackets: dstPoints }]
        : []),
      ...(dstYards.length
        ? [{ stat: "dst_yards_allowed", applies_to: ["DST"], brackets: dstYards }]
        : []),
    ],
    scoring_bonuses: ((scoring["bonuses"] ?? []) as Array<Record<string, unknown>>).map(
      (b) => ({
        stat: String(b["stat"]),
        threshold: Number(b["threshold"]),
        points: Number(b["points"]),
        applies_to: ["K"], // TODO(capture): CBS bonus->position mapping from the real page
      }),
    ),
    draft_type: String(frame["draftType"] ?? "snake"),
    // READ from the payload/board; null when unreadable — NEVER a synthesized snake.
    draft_order: Array.isArray(frame["draftOrder"])
      ? (frame["draftOrder"] as unknown[]).map(String)
      : null,
  };
  return settings as unknown as LeagueSettings;
}

/* ------------------------------------------------------------------------------------ *
 * DOM probe — board/ticker extraction (MutationObserver path).
 * ------------------------------------------------------------------------------------ */

function parseBoard(root: ParentNode): DraftEvent[] {
  // TODO(capture): selector vocabulary is synthetic ([data-overall] rows + .draft-order);
  // refine against the real room DOM once recorded.
  const board = root.querySelector(
    '#draftBoard, [class*="draft-board" i], [data-testid*="draft" i]',
  );
  const leagueId = board?.getAttribute("data-league-id") ?? "cbs-live";
  const events: DraftEvent[] = [];

  for (const row of Array.from(root.querySelectorAll("[data-overall]"))) {
    const overall = Number(row.getAttribute("data-overall"));
    if (!isValidOverall(overall)) continue;
    const arithmetic = roundFromOverall(overall);
    const attr = (name: string) => row.getAttribute(name);
    const player: SyntheticPlayer = {
      ...(attr("data-player-id") ? { id: attr("data-player-id")! } : {}),
      ...(attr("data-player-name") ? { name: attr("data-player-name")! } : {}),
      ...(attr("data-player-team") ? { team: attr("data-player-team")! } : {}),
      ...(attr("data-position") ? { position: attr("data-position")! } : {}),
    };
    events.push(
      pickEnvelope(leagueId, "dom", overall, {
        round: Number(attr("data-round") ?? arithmetic.round),
        pick_in_round: Number(attr("data-pick") ?? arithmetic.pick_in_round),
        team_id: String(attr("data-team-id") ?? ""),
        ...playerData(player),
      }),
    );
  }

  const order = Array.from(root.querySelectorAll(".draft-order [data-team-id]"))
    .map((el) => el.getAttribute("data-team-id"))
    .filter((id): id is string => !!id);
  if (order.length > 0) {
    events.push(orderEvent(leagueId, "dom", order));
  }
  return events;
}

/* ------------------------------------------------------------------------------------ *
 * Manual-paste fallback — the guaranteed draft-day path.
 * ------------------------------------------------------------------------------------ */

const ORDER_LINE = /^ORDER\s*:\s*(.+)$/i;
// Team capture is GREEDY so matching anchors on the LAST dash — a user-chosen team name
// may contain a hyphen ("Steel-Curtain Squad"), the trailing "player, POS, NFL" segment
// almost never does.
const PICK_LINE = /^\s*(\d+)[.)]\s*(.+)\s*[-–—]\s*(.+?)\s*$/;

/** Manual-paste path: many events from a copied results table / pick log; each stamped
 * source:"paste". Supported lines: `ORDER: T1, T2, ...` (the in-person draft order) and
 * `<overall>. <team> - <player>, <POS>, <NFL>`. Garbage lines are ignored. */
export function parsePastedResults(text: string): DraftEvent[] {
  const events: DraftEvent[] = [];
  for (const line of text.split(/\r?\n/)) {
    const order = line.match(ORDER_LINE);
    if (order?.[1]) {
      const teams = order[1].split(/[,\s]+/).filter(Boolean);
      if (teams.length > 0) {
        events.push(orderEvent("manual", "paste", teams));
      }
      continue;
    }
    const pick = line.match(PICK_LINE);
    if (!pick) continue;
    const overall = Number(pick[1]);
    const teamId = pick[2]!.trim();
    const playerPart = pick[3]!.trim();
    const segments = playerPart.split(",").map((s) => s.trim());
    let playerName = playerPart;
    let position: string | undefined;
    let playerTeam: string | undefined;
    if (segments.length >= 3) {
      [playerName, position, playerTeam] = [segments[0]!, segments[1], segments[2]];
    } else {
      const tokens = playerPart.split(/\s+/);
      if (tokens.length >= 3 && /^[A-Z]{1,3}$/.test(tokens[tokens.length - 1]!)) {
        playerTeam = tokens.pop();
        position = tokens.pop();
        playerName = tokens.join(" ");
      }
    }
    events.push(
      pickEnvelope("manual", "paste", overall, {
        ...roundFromOverall(overall),
        team_id: teamId,
        player_name: playerName,
        ...(position ? { position } : {}),
        ...(playerTeam ? { player_team: playerTeam } : {}),
      }),
    );
  }
  return events;
}

/* ------------------------------------------------------------------------------------ *
 * Public parser surface (§5.7).
 * ------------------------------------------------------------------------------------ */

/** Normalize one raw probe payload into zero-or-more DraftEvents. */
export function parseDraftEvents(src: RawSource): DraftEvent[] {
  if (src.via === "dom") return parseBoard(src.root);
  if (src.via === "paste") return parsePastedResults(src.text);
  return parseNetworkFrame(src.via, src.body);
}

/** Emit a normalized DraftEvent or null (stub-compatible single-event signature). */
export function parseDraftEvent(src: RawSource): DraftEvent | null {
  return parseDraftEvents(src)[0] ?? null;
}

/** Emit full LeagueSettings — roster slots, flex eligibility, FULL scoring (DST dual
 * tiers + K bonus), team count, draft order (from the payload/board or null). */
export function parseLeagueSettings(src: RawSource | Document): LeagueSettings | null {
  if (src instanceof Document) {
    // TODO(capture)/stage 2: real settings-page DOM parse. Synthetic hook: an embedded
    // JSON island our fixtures (and record-mode replays) provide.
    const island = src.querySelector("#jaaffl-league-settings");
    if (!island?.textContent) return null;
    return parseLeagueSettings({ via: "ws", body: island.textContent });
  }
  if (src.via === "dom" || src.via === "paste") return null;
  try {
    const frame = JSON.parse(src.body) as Record<string, unknown>;
    if (frame["type"] !== "league_settings" && !frame["rosterSlots"]) return null;
    return mapSyntheticSettings(frame);
  } catch {
    return null;
  }
}
