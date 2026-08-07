# CBS fantasy draft protocol — decoded from a real capture

**Date:** 2026-07-24 · **Source:** owner record-mode capture session (12-team snake mock, 14 rounds)
**Status:** verified against 8.4 MB of real frames — supersedes every `TODO(capture)` guess

This is the ground truth that unblocks `apps/extension/src/lib/parse.ts`, whose CBS vocabulary was
entirely synthetic until now. Nothing here is inferred; every field below was observed.

---

## 1. Transport

|                      |                                                                 |
| -------------------- | --------------------------------------------------------------- |
| Draft socket         | `wss://k8s-draft.prod.fantasy.cbssports.cloud:443/`             |
| Chat socket (ignore) | `wss://chat.prod.fantasy.cbssports.cloud:443`                   |
| Draft room URL       | `https://mockdraft-N.football.cbssports.com/mockdraft/<format>` |
| Real league URL      | `https://<league>.football.cbssports.com/`                      |

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

| Count | type/subtype                                            | Meaning                                        |
| ----: | ------------------------------------------------------- | ---------------------------------------------- |
|    40 | `picks/completed`                                       | **A pick was made** — the primary ingest event |
|    12 | `pick/request`                                          | Outbound: this client asks to draft `playerid` |
|    12 | `pick/response`                                         | Server ack                                     |
|    11 | `queue/add` · `queue/updated` · `queue/response`        | Player queue                                   |
|    11 | `autopilot/on` · `autopilot/off` · `autopilot/response` | Bot toggles                                    |
|     4 | `attendance/entered`                                    | Owner joined                                   |
|     3 | `roster/add` · `roster/remove`                          | Roster deltas                                  |
|     2 | `auth/request` · `auth/reply`                           | Handshake (`status: 100` = success)            |
|     2 | `subscribe/request` · `subscribe/response`              | Initial full state (up to 61 KB)               |
|     2 | `keepalive`                                             | Heartbeat                                      |

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

`source` distinguishes `"autopick"` from a human (`"userpick"`) pick — keep it; it feeds future
manager-tendency work rather than being discarded.

### ⚠️ The overall pick number: `newstate.opick` is FORWARD-LOOKING

The overall pick is **not** on the pick entry, and `newstate.opick` is **not** the pick that just
completed — it is the pick now **on the clock** (it pairs with `onclockteamid`). Reading it
literally mis-numbers every pick by +1 and, at the terminal frame, drops the real final pick.

`payload.picks[]` is also **batched** — observed batch sizes 1, 2, 5, 7 and 9 (one frame can report
nine completed picks at once, e.g. after a run of autopicks). So walk backward from `opick`:

```ts
overall = newstate.opick - picks.length + index; // index within payload.picks[]
```

**Verified exhaustively:** this matches CBS's own record
(`fullstatedelta.teams[<team>].players[<playerid>].opick`) for **all 168 picks of a complete draft,
zero mismatches**, across every observed batch size.

`fullstatedelta.opickindex` is consistently `opick - 1` (a 0-based index of the on-the-clock pick).

Note `draft_state.current_overall_pick` should use `opick` **unadjusted** — there, "the pick now on
the clock" is exactly the right meaning.

## 4. `newstate` — the draft state, attached to most frames

| Field                                         | Example                       | Maps to                                             |
| --------------------------------------------- | ----------------------------- | --------------------------------------------------- |
| `opick`                                       | `"24"`                        | `current_overall_pick`                              |
| `round`                                       | `2`                           | round                                               |
| `rounds`                                      | `14`                          | total rounds                                        |
| `onclockteamid`                               | `"1"`                         | `on_the_clock_team_id`                              |
| `ondeckteamid`                                | `"2"`                         | on deck                                             |
| `order_type`                                  | `"snake"`                     | draft type                                          |
| `upcomingorder`                               | `"1,1,2,3,…,12,12,11,…,4"`    | **the real entered order**                          |
| `upcomingorder_withroundbreaks`               | `"1,…,12,-9,12,…,4"`          | same, `-9` marks a round break                      |
| `onautopilot`                                 | `"10:moderate,11:moderate,…"` | which teams are bots                                |
| `state`                                       | `"completed"`                 | terminal marker                                     |
| `teamspresent`                                | `"1,10,8"`                    | attendance — team SLOT numbers                      |
| `ownerspresent`                               | `"d5k…,pwc…"`                 | attendance — alphanumeric owner-id tokens (**PII**) |
| `deadline`, `currenttime`, `currenthirestime` | epoch                         | clock                                               |

### ⚠️ `opick` overruns the draft by one at completion

Observed: `rounds: 14`, 12 teams → 168 real picks, but the terminal frame carries `opick: 169`.
`169` is a **draft-over sentinel**, not a 15th-round pick. Treat `opick > rounds × teams` as
"draft complete", exactly as `opponents.next_overall_pick` does with its own sentinel.

Since Tier 3, `parse.ts` reads completion from **two independent signals**: CBS's own
`state: "completed"` word _and_ the structural overrun (`isDraftOver`). Either is sufficient, so a
frame that overruns without the state word is not read as a live draft parked on a pick that
cannot exist.

The overrun value itself is passed through **verbatim**, deliberately not clamped to 168:
`opponents.next_overall_pick` already returns `rounds × teams + 1` to mean "you have no picks
left", so 169 is the same convention. Clamping to 168 would assert that the final pick is still on
the clock after it was made.

### ⚠️ `upcomingorder` is a ROLLING WINDOW — do NOT use it as `draft_order`

`upcomingorder` is the upcoming pick sequence from _right now_, spanning a partial round into the
next — **not** one entry per team. Observed entry counts across one draft:

| Frames |                         Entries |
| -----: | ------------------------------: |
|     55 |                              22 |
|      1 |                              17 |
|      2 |                               8 |
|      2 |                               1 |
|      4 | 0 (once `state == "completed"`) |

This matters because `engine/opponents.py::_my_overall_picks` does `n = len(settings.draft_order)`
and uses `n` as the **team count** for snake math. Feeding it a 22-entry window would set
`team_count: 22` and silently corrupt every "my next pick" and survival calculation.

**Use `payload.fullstatedelta.order` instead.** It is exactly one entry per team and stable for the
whole draft — a single distinct value `"1,2,3,4,5,6,7,8,9,10,11,12"` across all 40 frames that
carry it, i.e. 12 entries for a 12-team league.

`config/league.json` sets `infer_from_team_count: false`, so the parser must **read** the order and
degrade honestly when it is absent — never synthesize a snake from team count. Manual paste
(`ORDER:` line) remains the draft-day fallback.

`upcomingorder_withroundbreaks` (the `-9`-delimited variant) is still useful for _reading_ the snake
shape, but it is the same rolling window and is likewise not a `draft_order`.

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

**Consumed since Tier 3.** `parse.ts::cbsSnapshotPicks` turns `fullstate.teams` into a single
`draft_state` event carrying an explicit `picks` list, which `fold_state` treats as an
authoritative full re-sync (a plain ticker `draft_state` deliberately leaves the board alone).

### ⚠️ `fullstate` is the board; `fullstatedelta` is NOT

Both carry a `teams` map of the same shape, so they are easy to confuse — and the mistake is
expensive. `fullstatedelta.teams` holds **only the picks that frame reported** (measured across a
168-pick draft: 1–9 entries per frame, never the full board). Treating it as a resync would
replace the entire board with a handful of picks on every frame.

### ⚠️ Recording can begin mid-draft — and then the deltas are NOT enough

Observed in the owner's 2026-07-25 session: the client connected at `opick: 4`, so the delta
stream covers overalls **4–168** and picks **1, 2, 3 exist only in the `subscribe` snapshot**.
A resync that ignores the snapshot leaves three genuinely drafted players unmasked and
recommendable. This is not a hypothetical reconnect — it is what the real capture did.

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

Raw captures live git-ignored under `apps/extension/fixtures/cbs/`. Only redacted golden fixtures
are committed, under `apps/extension/tests/fixtures/cbs/`, generated reproducibly by
`scripts/redact_cbs_fixtures.py`.

### ⚠️ What the RAW captures contain

More personal data than first assumed — verified while building the fixtures:

- the owner's `ownerid`, team display name, **and email address**
- **other real drafters' `ownerid`s and team names** (a public mock draft has other humans in it)

They are git-ignored and must stay local. Do not paste them into an issue, share them, or upload
them anywhere. The redaction script exists precisely so that testing never requires the raw files.
