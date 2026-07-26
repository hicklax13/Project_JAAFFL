/**
 * Golden-fixture-driven normalizers (plan §5.7). Every probe funnels through ONE
 * normalizer via the discriminated RawSource union; the isolated content script is the
 * sole caller (trust boundary).
 *
 * The network-frame vocabulary below is the REAL decoded CBS draft-socket protocol
 * (docs/research/cbs-draft-protocol.md, verified against a live capture) — no longer
 * synthetic. The DOM-selector vocabulary and the settings-page mapping remain SYNTHETIC
 * placeholders pinned by tests/fixtures (TODO(capture): still pending a real capture).
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
 * Real CBS network-frame vocabulary (docs/research/cbs-draft-protocol.md, decoded from a
 * live capture). Frames are NUL-terminated JSON, or a bare numeral heartbeat. Envelope is
 * {type, subtype|event, payload}. The DOM-selector vocabulary below this section is
 * unrelated and stays synthetic (TODO(capture) — still pending a real capture).
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

/** Strip the trailing NUL(s) every CBS draft-socket frame carries. `JSON.parse` throws
 * "Extra data" on the raw frame — this is the single most load-bearing line in this file. */
function stripCbsFrame(raw: string): string {
  return raw.replace(/\0+$/, "").trim();
}

/** payload.picks[] entry (picks/completed) — ID-ONLY, no name/position/team. */
interface CbsPickEntry {
  playerid?: string | number;
  teamid?: string | number;
  source?: string; // "autopick" | "userpick" | ... — preserved for manager-tendency work
  skipped?: number;
}

/** payload.newstate — attached to most frames; describes the CURRENT/next (forward-
 * looking) pick, not whatever pick(s) this same frame's payload.picks[] just reported. */
interface CbsNewState {
  opick?: string | number;
  round?: string | number;
  rounds?: string | number;
  onclockteamid?: string | number;
  ondeckteamid?: string | number;
  state?: string;
}

/** payload.fullstatedelta — the delta CBS attaches to picks/completed frames. `order` is
 * the STABLE, real entered round-1 order (see parseDraftOrder). */
interface CbsFullStateDelta {
  order?: string;
}

function cbsPlayerData(playerid: string | number | undefined): Record<string, unknown> {
  if (playerid == null) return {};
  return { player_id: `cbs:${playerid}`, cbs_player_id: String(playerid) };
}

/** CBS represents "nobody" as the NUMBER 0 (not the string "0") on onclockteamid /
 * ondeckteamid once the draft is over; a real team id rides as a numeric string. */
function cbsTeamId(value: string | number | undefined): string | null {
  if (value == null || value === 0 || value === "0") return null;
  return String(value);
}

/**
 * payload.fullstatedelta.order → the REAL entered round-1 order, verbatim.
 *
 * NOT payload.newstate.upcomingorder: that field is a ROLLING multi-round lookahead
 * window (observed entry counts across one full draft: 22, 17, 8, 1, 0 — never a stable
 * one-per-team order) and must never feed draft_order — opponents.py's snake math
 * (_my_overall_picks) uses len(draft_order) AS the team count, so a wrong-length order
 * silently corrupts every "my next pick" calculation. fullstatedelta.order, by contrast,
 * is confirmed STABLE: exactly one distinct value ("1,2,...,12") across all
 * fullstatedelta-bearing frames of a full draft.
 *
 * Length guard: only accept a parsed order of EXACTLY IMMUTABLE_TEAM_COUNT entries — that
 * is the whole point (any other length, empty or otherwise, risks the same corruption the
 * rolling window would have caused) — never synthesize a snake from team count either (A5).
 */
function parseDraftOrder(order: string | undefined): string[] | null {
  if (!order) return null;
  const teams = order
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return teams.length === IMMUTABLE_TEAM_COUNT ? teams : null;
}

/**
 * payload.picks[] → one pick_made per entry. GROUND-TRUTH CORRECTION vs. the doc's
 * original prose ("take the overall from newstate.opick", corrected in commit 43b386b):
 * newstate.opick is the pick now on the clock (paired with onclockteamid), i.e. ONE AHEAD
 * of the pick(s) this same frame just reported. overall = newstate.opick - picks.length +
 * index is CONFIRMED against every pick of a full draft (168/168 matches, batch sizes
 * 1/2/5/7/9 all included) via fullstatedelta.opickindex and fullstatedelta.results/teams.
 * Walking backward from opick by the batch size also naturally avoids ever minting a
 * phantom pick at the completion sentinel.
 */
function cbsPickEvents(
  leagueId: string,
  source: DraftEvent["source"],
  payload: Record<string, unknown>,
): DraftEvent[] {
  const picks = payload["picks"];
  const newstate = payload["newstate"] as CbsNewState | undefined;
  const hasAnchor = !!newstate && isValidOverall(newstate.opick);
  if (!Array.isArray(picks) || picks.length === 0 || !hasAnchor) return [];

  const nextOverall = Number(newstate!.opick);
  const rounds = Number(newstate!.rounds);
  const maxOverall =
    Number.isInteger(rounds) && rounds > 0 ? rounds * IMMUTABLE_TEAM_COUNT : Infinity;

  const events: DraftEvent[] = [];
  picks.forEach((raw: unknown, i: number) => {
    const p = raw as CbsPickEntry;
    const overall = nextOverall - picks.length + i;
    if (!isValidOverall(overall) || overall > maxOverall) return; // completion-sentinel guard
    const arithmetic = roundFromOverall(overall);
    events.push(
      pickEnvelope(leagueId, source, overall, {
        round: arithmetic.round,
        pick_in_round: arithmetic.pick_in_round,
        team_id: String(p.teamid ?? ""),
        pick_source: p.source ?? null,
        ...cbsPlayerData(p.playerid),
      }),
    );
  });
  return events;
}

/** One entry of subscribe's per-team board: fullstate.teams.<team>.players.<playerid>. CBS
 * records its OWN opick/round/pick per roster entry — read them, never re-derive. */
interface CbsRosterEntry {
  id?: string | number;
  opick?: string | number;
  round?: string | number;
  pick?: string | number;
  team_id?: string | number;
  rosterpos?: string;
  elig?: string;
}

/**
 * payload.fullstate.teams → the complete board, as a single authoritative resync.
 *
 * This is the late-join / reconnect source (protocol doc §4 "Full roster state"): every team's
 * roster keyed by CBS player id. It is emitted as a `draft_state` carrying an explicit `picks`
 * list, which `ingest/log.py::fold_state` treats as a full re-sync — as opposed to the ticker
 * `draft_state` most frames carry, which deliberately leaves previously folded picks alone.
 *
 * ⚠️ Read `fullstate`, NOT `fullstatedelta`. Both have a `teams` map of the same shape, but
 * `fullstatedelta.teams` holds only the picks THAT FRAME reported (measured: 1-9 entries on a
 * 168-pick draft). Treating a delta as a full resync would replace the whole board with a
 * handful of picks on every frame.
 */
function cbsSnapshotPicks(payload: Record<string, unknown>): Record<string, unknown>[] {
  const fullstate = payload["fullstate"];
  if (!fullstate || typeof fullstate !== "object") return [];
  const teams = (fullstate as Record<string, unknown>)["teams"];
  if (!teams || typeof teams !== "object") return [];

  const picks: Record<string, unknown>[] = [];
  for (const [teamId, team] of Object.entries(teams as Record<string, unknown>)) {
    const players = (team as Record<string, unknown> | null)?.["players"];
    if (!players || typeof players !== "object") continue;
    for (const [playerId, raw] of Object.entries(players as Record<string, unknown>)) {
      const entry = raw as CbsRosterEntry;
      const overall = Number(entry.opick);
      if (!isValidOverall(overall)) continue;
      const arithmetic = roundFromOverall(overall);
      picks.push({
        overall,
        round: Number(entry.round ?? arithmetic.round),
        pick_in_round: Number(entry.pick ?? arithmetic.pick_in_round),
        team_id: String(entry.team_id ?? teamId),
        ...cbsPlayerData(entry.id ?? playerId),
      });
    }
  }
  return picks.sort((a, b) => Number(a["overall"]) - Number(b["overall"]));
}

/** payload.newstate → draft_state (current pick / round / on-the-clock / on-deck). Unlike
 * pick_made, NO adjustment is needed here — newstate IS "the current state," by design. */
function cbsDraftStateEvent(
  leagueId: string,
  source: DraftEvent["source"],
  newstate: CbsNewState,
  picks?: Record<string, unknown>[],
): DraftEvent | null {
  if (!isValidOverall(newstate.opick)) return null;
  return {
    event_type: "draft_state",
    league_id: leagueId,
    source,
    data: {
      // Verbatim, INCLUDING the draft-over overrun (opick 169 on a 168-pick draft). That is
      // the same "no picks left" sentinel opponents.next_overall_pick returns; clamping it to
      // 168 would claim the final pick is still on the clock after it was made.
      current_overall_pick: Number(newstate.opick),
      round: newstate.round != null ? Number(newstate.round) : null,
      on_the_clock_team_id: cbsTeamId(newstate.onclockteamid),
      on_deck_team_id: cbsTeamId(newstate.ondeckteamid),
      // Present ONLY for a real full-board snapshot — its presence is what tells fold_state
      // this is an authoritative resync rather than a ticker tick.
      ...(picks && picks.length > 0 ? { picks } : {}),
    },
  };
}

/** True when the clock has run past the last real pick (rounds x teams). CBS's terminal frame
 * carries opick 169 on a 14-round, 12-team draft — a draft-over sentinel, not a 15th round.
 * Structural, so completion is detected even if the `state` word is absent or changes. */
function isDraftOver(newstate: CbsNewState, teamCount: number): boolean {
  const rounds = Number(newstate.rounds);
  const opick = Number(newstate.opick);
  if (!Number.isInteger(rounds) || rounds <= 0 || !Number.isInteger(opick)) return false;
  return opick > rounds * teamCount;
}

function parseNetworkFrame(via: NetworkVia, body: string): DraftEvent[] {
  const stripped = stripCbsFrame(body);
  if (!stripped.startsWith("{")) return []; // bare-numeral heartbeat / non-JSON — silent skip
  let frame: Record<string, unknown>;
  try {
    frame = JSON.parse(stripped) as Record<string, unknown>;
  } catch {
    return []; // noisy relay, silent parser — not a draft frame
  }
  if (typeof frame !== "object" || frame === null) return [];
  const source = probeSource(via);
  const leagueId = String(frame["leagueId"] ?? frame["league_id"] ?? "cbs-live");

  // Settings-page mapping — a DIFFERENT (still-synthetic) source than the draft socket;
  // real CBS draft frames never carry type "league_settings" (see doc's observed table).
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

  const payload = (frame["payload"] ?? {}) as Record<string, unknown>;
  const verb = (frame["subtype"] ?? frame["event"]) as string | undefined; // doc §2: read either
  const events: DraftEvent[] = [];

  if (frame["type"] === "picks" && verb === "completed") {
    events.push(...cbsPickEvents(leagueId, source, payload));
  }

  const newstate = payload["newstate"];
  const ns = newstate && typeof newstate === "object" ? (newstate as CbsNewState) : null;
  // A subscribe/response's full board — the late-join resync source (§4). Never fullstatedelta.
  const snapshot = cbsSnapshotPicks(payload);
  if (ns) {
    const stateEvent = cbsDraftStateEvent(leagueId, source, ns, snapshot);
    if (stateEvent) events.push(stateEvent);
  }

  const fullstatedelta = payload["fullstatedelta"];
  if (fullstatedelta && typeof fullstatedelta === "object") {
    const order = parseDraftOrder((fullstatedelta as CbsFullStateDelta).order);
    if (order) events.push(orderEvent(leagueId, source, order));
  }

  // Two independent completion signals: CBS's own state word, and the structural overrun of
  // the clock past the last real pick. Either one is enough.
  if (ns && (ns.state === "completed" || isDraftOver(ns, IMMUTABLE_TEAM_COUNT))) {
    events.push({ event_type: "draft_complete", league_id: leagueId, source, data: {} });
  }

  return events;
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
/**
 * `<overall>. <team> - <player>, <POS>, <NFL>`
 *
 * The separator dash MUST be surrounded by whitespace. An earlier form matched any dash and
 * relied on greediness plus the assumption that "the trailing player segment almost never"
 * contains one — which real NFL rosters falsify. Replaying a real captured draft through the
 * paste path split `9. 9 - Jaxon Smith-Njigba, WR, SEA` on the SURNAME, yielding
 * team_id "9 - Jaxon Smith" and player_name "Njigba": a pick that then resolves to nobody,
 * is never masked, and is recommended again. Amon-Ra St. Brown and Ray-Ray McCloud break it
 * the same way.
 *
 * Requiring whitespace keeps the case that motivated greediness — a hyphenated TEAM name
 * ("Steel-Curtain Squad") writes its hyphen without spaces — while the team capture stays
 * greedy so a team name containing a spaced dash still anchors on the last separator.
 */
const PICK_LINE = /^\s*(\d+)[.)]\s*(.+)\s+[-–—]\s+(.+?)\s*$/;

/** What a paste actually yielded — including what it could NOT read. */
export interface PastedReport {
  events: DraftEvent[];
  /** Non-blank lines that matched neither an ORDER nor a pick line. Surfaced because a
   * partial parse reported as "N event(s) sent" reads as success: the owner would have to
   * count picks to notice one went missing, and by then it has cost them a player. */
  skipped: string[];
}

/** Manual-paste path: many events from a copied results table / pick log; each stamped
 * source:"paste". Supported lines: `ORDER: T1, T2, ...` (the in-person draft order) and
 * `<overall>. <team> - <player>, <POS>, <NFL>`. Unreadable lines are REPORTED, not dropped
 * silently — see PastedReport.skipped. */
export function parsePastedReport(text: string): PastedReport {
  const events: DraftEvent[] = [];
  const skipped: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue; // blank: nothing was there to lose
    const order = line.match(ORDER_LINE);
    if (order?.[1]) {
      const teams = order[1].split(/[,\s]+/).filter(Boolean);
      if (teams.length > 0) {
        events.push(orderEvent("manual", "paste", teams));
      } else {
        skipped.push(line);
      }
      continue;
    }
    const pick = line.match(PICK_LINE);
    if (!pick) {
      skipped.push(line);
      continue;
    }
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
  return { events, skipped };
}

/** Events-only view of {@link parsePastedReport}, for callers that route straight into the
 * shared forward() tail. Prefer the report where the user can be told what was skipped. */
export function parsePastedResults(text: string): DraftEvent[] {
  return parsePastedReport(text).events;
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
