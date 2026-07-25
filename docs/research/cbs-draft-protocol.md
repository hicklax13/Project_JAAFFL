# CBS fantasy draft protocol — decoded from a real capture

**Date:** 2026-07-24 · **Source:** owner record-mode capture session (12-team snake mock, 14 rounds)
**Status:** verified against 8.4 MB of real frames — supersedes every `TODO(capture)` guess

This is the ground truth that unblocks `apps/extension/src/lib/parse.ts`, whose CBS vocabulary was
entirely synthetic until now. Nothing here is inferred; every field below was observed.

---

## 1. Transport

| | |
|---|---|
| Draft socket | `wss://k8s-draft.prod.fantasy.cbssports.cloud:443/` |
| Chat socket (ignore) | `wss://chat.prod.fantasy.cbssports.cloud:443` |
| Draft room URL | `https://mockdraft-N.football.cbssports.com/mockdraft/<format>` |
| Real league URL | `https://<league>.football.cbssports.com/` |

### ⚠️ Frames are NUL-terminated

**Every** socket frame ends with a literal `\x00`. `JSON.parse` on the raw frame throws
`Extra data` at the final character.

This single detail is why only **8 of 98** captured frames parsed before it was found, and **128**
after. Any parser MUST strip it:

```ts
const json = raw.replace(/\0+$/, "").trim();
```

Some frames are also a bare numeric string (e.g. `"0331701870"`) — a heartbeat, not JSON. Skip
anything that does not start with `{`.

## 2. Message envelope

```jsonc
{ "type": "<domain>", "subtype": "<verb>", "payload": { ... } }
```

Some frames use `"event"` instead of `"subtype"` (notably `auth`). Read either.

Observed `type/subtype` pairs, with counts from one mock draft:

| Count | type/subtype | Meaning |
|---:|---|---|
| 40 | `picks/completed` | **A pick was made** — the primary ingest event |
| 12 | `pick/request` | Outbound: this client asks to draft `playerid` |
| 12 | `pick/response` | Server ack |
| 11 | `queue/add` · `queue/updated` · `queue/response` | Player queue |
| 11 | `autopilot/on` · `autopilot/off` · `autopilot/response` | Bot toggles |
| 4 | `attendance/entered` | Owner joined |
| 3 | `roster/add` · `roster/remove` | Roster deltas |
| 2 | `auth/request` · `auth/reply` | Handshake (`status: 100` = success) |
| 2 | `subscribe/request` · `subscribe/response` | Initial full state (up to 61 KB) |
| 2 | `keepalive` | Heartbeat |

## 3. `picks/completed` — the pick event

```jsonc
{
  "type": "picks", "subtype": "completed",
  "payload": {
    "picks": [
      { "playerid": "3162723", "teamid": "1", "source": "autopick",
        "skipped": 0, "update_team_queue": 0 }
    ],
    "newstate": { ... },          // see §4
    "fullstatedelta": { "opickindex": 1, ... }
  }
}
```

**Picks are ID-only** — no name, position, or NFL team. Resolution therefore REQUIRES a
CBS-id → canonical crosswalk (§5). This is the single biggest divergence from the synthetic
`parse.ts`, which assumed name/team/position rode along with the pick.

`source` distinguishes `"autopick"` from a human pick — keep it; it feeds future manager-tendency
work rather than being discarded.

The overall pick number is **not** on the pick entry. Take it from `newstate.opick`.

## 4. `newstate` — the draft state, attached to most frames

| Field | Example | Maps to |
|---|---|---|
| `opick` | `"24"` | `current_overall_pick` |
| `round` | `2` | round |
| `rounds` | `14` | total rounds |
| `onclockteamid` | `"1"` | `on_the_clock_team_id` |
| `ondeckteamid` | `"2"` | on deck |
| `order_type` | `"snake"` | draft type |
| `upcomingorder` | `"1,1,2,3,…,12,12,11,…,4"` | **the real entered order** |
| `upcomingorder_withroundbreaks` | `"1,…,12,-9,12,…,4"` | same, `-9` marks a round break |
| `onautopilot` | `"10:moderate,11:moderate,…"` | which teams are bots |
| `state` | `"completed"` | terminal marker |
| `teamspresent` / `ownerspresent` | `"1,10,8"` | attendance |
| `deadline`, `currenttime`, `currenthirestime` | epoch | clock |

### ⚠️ `opick` overruns the draft by one at completion

Observed: `rounds: 14`, 12 teams → 168 real picks, but the terminal frame carries `opick: 169`.
`169` is a **draft-over sentinel**, not a 15th-round pick. Treat `opick > rounds × teams` as
"draft complete", exactly as `opponents.next_overall_pick` does with its own sentinel.

### ⚠️ `upcomingorder` is empty once `state == "completed"`

It is populated *during* the draft only. `config/league.json` sets `infer_from_team_count: false`,
so the parser must **read** this field when present and degrade honestly when absent — never
synthesize a snake from team count. Manual paste (`ORDER:` line) remains the draft-day fallback.

### Full roster state

`subscribe` frames carry per-team rosters keyed by CBS player id:

```jsonc
"teams": { "1": { "players": {
  "2181054": { "id": "2181054", "opick": "24", "round": 2, "pick": 12, "team_id": "1",
               "rosterpos": "RB", "elig": "RB" }
}}}
```

This is a complete board snapshot — more valuable than replaying individual pick deltas, and the
right source for a late-join resync.

## 5. CBS player id → name / position / team

Picks are ID-only, so a crosswalk is mandatory. It is derivable **from the capture itself** — three
independent sources, in descending reliability:

1. **Player-list rows** (name + position + NFL team):
   `<tr id="playerListDD_<cbsid>" …><td align="left">WR</td><td align="left">NE</td>`
2. **Player page links** (canonical "First Last"):
   `/players/playerpage/<cbsid>/…<h1 class="name">Jahmyr Gibbs</h1>`
3. **Snippet links** ("Last, First"):
   `/players/playerpage/snippet/<cbsid>" class="playerLink">Gibbs, Jahmyr</a>`

Yield from one mock draft: **241 distinct ids, 241 named (100%), 203 with position + team (84%)**.

Canonical id form stays `cbs:<cbsid>` (matches the existing `playerData()` convention); the
name/position/team triple then feeds the existing crosswalk resolution path.

## 6. What this supersedes

Every `TODO(capture)` marker in `apps/extension/src/lib/parse.ts`, plus the unverified
`CbsPageSnapshot` field shapes in `backend/src/jaaffl/domain/models.py` and
`backend/src/jaaffl/providers/cbs_onpage.py`.

Raw captures live git-ignored under `apps/extension/fixtures/cbs/` (they carry the owner's
`ownerid` and team name). Only redacted golden fixtures are committed.
