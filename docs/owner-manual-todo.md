# Owner-manual TODO (Connor-only tasks)

Tasks only the owner can do (record-mode capture, keys, auth, decisions). Deferred to the end
of each build phase on purpose — nothing here blocks the automated build unless flagged. Do the
`[BLOCKER]` items when you want the feature they gate; the `[WHEN YOU WANT IT]` items are opt-in.

## 1. CBS record-mode capture session `[✅ DONE — 2026-07-24]`

> **The owner ran this.** One 12-team snake mock (14 rounds, bots) produced **8.4 MB** of real
> frames. The decoded result is [`docs/research/cbs-draft-protocol.md`](research/cbs-draft-protocol.md)
> — ground truth that replaced every `TODO(capture)` guess in the **network-frame** vocabulary of
> `apps/extension/src/lib/parse.ts`.
>
> Headline findings: CBS socket frames are **NUL-terminated** (this alone took parsed frames from
> 8/98 to 128); `picks/completed` is the pick event and picks are **ID-only**; `newstate.opick` is
> **forward-looking** (the pick on the clock, not the one just made); the real draft order lives in
> `fullstatedelta.order`, **not** the rolling `upcomingorder` window.
>
> Three live bugs were found and fixed in the process (PRs #24, #25): CWD-relative paths writing
> captures to a NON-git-ignored directory, CORS globs never matching (which recorded zero frames
> while looking healthy), and `env_file` being CWD-relative.
>
> ⚠️ **The raw captures under `apps/extension/fixtures/cbs/` contain the owner's email and other
> real drafters' ids/team names.** Git-ignored; keep them local. Committed fixtures are redacted via
> `scripts/redact_cbs_fixtures.py`.
>
> **Tier 3 closed the replay gap (2026-07-25).** A complete captured 12×14 draft now runs the whole
> pipeline end to end — raw frames → `parse.ts` → fold → resolve → `recommend()` — and asserts on
> the rendered pick. It found four real defects (see `ROADMAP.md`), including one that mattered on
> draft night: the overlay's VONA was structurally **0.00** because nothing supplied your draft slot
> to the push path.
>
> ### ⚠️ TWO THINGS TO DO BEFORE DRAFT NIGHT
>
> **1. Set `JAAFFL_MY_TEAM_ID`.** Put your CBS team slot (`"1"`–`"12"`, as CBS numbers the teams in
> the room) in `.env`. No CBS frame names _your own_ team, so the app cannot work it out from the
> live feed. Without it the engine cannot tell when your next pick is, survival degrades to
> "everyone is still available", and every recommendation reads `vona 0.00` — the scarcity half of
> the model is off. It still ranks on Marginal Lineup Value and it now says so (the overlay foot
> shows `VONA degraded · no draft slot set`), but you want the real number. One line:
>
> ```
> JAAFFL_MY_TEAM_ID=7
> ```
>
> **2. Run the preflight — the morning of the draft, not the night before.** It pulls the live
> feeds, so run it close enough to draft day that you are checking the data you will actually draft
> against:
>
> ```
> .venv/Scripts/python.exe scripts/preflight.py --seed
> ```
>
> It builds the REAL draft context through the same wiring the live service uses, then prints how
> many draftable players exist at each position and **exits non-zero** if any position you must
> start has none. Healthy output looks like:
>
> ```
> [preflight] draftable players on the board: 513
> [preflight]   DST     31  (start)
> [preflight]   K       32  (start)
> [preflight]   QB      56  (start)
> [preflight]   RB     128  (start)
> [preflight]   TE      90  (start)
> [preflight]   WR     176  (start)
> [preflight] OK: every startable position (DST, K, QB, RB, TE, WR) is fillable.
> ```
>
> If it fails, it names the position — treat that as a hard stop and fix it before drafting, because
> the engine cannot recommend or roster what is not on the board, and any pick an opponent makes at
> that position will not be masked from your candidate pool.
>
> **Why this exists (PR #45).** The board silently carried **zero kickers and zero defenses** — 2 of
> your 9 starting slots — and nothing surfaced it. nflverse's crosswalk spells kicker `PK` while the
> domain spells it `K`, so all 151 were dropped by a position gate; and that table carries no team
> rows at all, so there were no defenses to drop in the first place. The whole suite was green
> throughout, because every test fixture spelled the positions the way the code expected. The loader
> did log `skipped=8040`, but ~8,000 of those are normal IDP rows, so the missing ones hid in the
> noise. `engine/precompute.py` now also logs a non-fatal `precompute_position_coverage_gap` warning
> if it ever recurs mid-draft — but the preflight is the one that catches it while you can still act.
>
> **Still open:** a **replay is not a live draft.** The pipeline has run end to end on real captured
> frames; it has still never run against a LIVE CBS room that is actually ticking. Also still
> `TODO(capture)`: the **settings-page** parse and `CbsPageSnapshot` projections/injuries/rankings
> (§4 below), which need a _settings/board_ page capture rather than draft-room frames.
>
> ✅ **`scripts/seed_cbs_crosswalk.py` is no longer a prerequisite (PR #31).** The crosswalk now
> seeds itself on the first `/recommendation` (~4,400 players / ~4,360 CBS links from the free
> DynastyProcess table). Running the script after a capture is still worthwhile — it mines CBS ids
> that table lacks — but forgetting it no longer breaks draft night. Verified on a pristine data
> dir: an ID-only CBS pick now masks its player from the board with zero manual setup.

> 📋 **Full step-by-step walkthrough:** [`docs/live-draft-recording-guide.md`](live-draft-recording-guide.md)
> — exact install commands, Chrome load-unpacked steps, and the record-mode buttons.

The one real-frame session. It unblocked the **real** CBS field shapes that the code previously
mocked behind `TODO(capture)`: `CbsOnPageProvider`'s real projections/injuries/rankings mapping and
the `CbsPageSnapshot` schema (`backend/src/jaaffl/domain/models.py`,
`backend/src/jaaffl/providers/cbs_onpage.py`) remain outstanding, and — new
in **Phase 4 (Stage 5 engine)** — two more things:

- **The real CBS scoring VALUES — RESOLVED (owner-confirmed 2026-07-17).** The owner provided the
  official JAAFFL2025 scoring (passing 1 pt / 50 yds, no offensive turnover penalty, K distance
  bonuses +1 at 50 / +1 more at 60, DST single points-allowed bracket 0-9 = 6 with no yards-allowed
  tier), now encoded in `backend/src/jaaffl/league/defaults.py::jaaffl_scoring()`. A captured CBS
  scoring page still overrides it via `CbsOnPageProvider.league_settings()` if the room ever differs
  (config/league.json roster stays immutable). Only CBS _frame parsing_ (live draft-room shapes)
  remains capture-blocked.
- **Calibration against real drafts (E1/E2/E3).** The tunables in `config/engine.json` (flex split
  8RB/4WR, κ, λ-table, α, reliability shrinkage, situation caps) are literature/first-principles
  priors. E1 measures the flex split from live FFC ADP (top-60); E2/E3 tune the weight vector and
  validate μ/σ against real boards. All optional — the engine ships and runs on the priors.
  **E2 was re-run on 2026-07-25** against the new _real_ xEP-backed μ/σ (the earlier run had tuned
  against the `300 − ecr` placeholder, so its "optimum" was fitted to synthetic value). It again
  **kept the baseline**: the tuned vector was directionally better but not significantly so
  (`mean_diff +3.18 pts/slot`, `min_slot_diff −0.41`, `p = 0.41`), failing the no-regression gate.
  Nothing was written — the CLI is dry-run unless you pass `--write`, and `config/engine.json`
  stays owner-adopted.

  ✅ **Both warnings that re-run raised are now RESOLVED — Tier 4 rebuilt the harness (2026-07-26,
  PRs #47–#49).** They were symptoms of five deeper problems, all measured:

  1. The scorer read only μ and **never σ**, so `λ·σ` could be penalised and never rewarded.
  2. The baseline was bare `EngineParams()`, whose `lambda_schedule` defaults to `[]` — so **every
     previous E2 baseline, and E6's "ours" contender, was a risk-FREE agent**, not the vector in
     `config/engine.json`.
  3. Both fixture pools were **params-blind**: κ, α and λ all switched off left a bit-identical
     roster in 96/96 cells.
  4. The simulated agent capped candidates by raw value at 50, where the live engine caps by MLV at
     180 — it **could not draft a DST at all**.
  5. `--eval-seeds` was inert (every held-out opponent deterministic).

  Drafts are now scored by **win probability** — `P(your roster posts the highest realized season
total of the 12)` over seasons sampled from `N(μ, σ)` — against a disjoint stochastic held-out
  field, with the committed config as the baseline.

  **The pure-MLV finding reverses.** On the real 2026 board (8 seeds, 800 sampled seasons/draft),
  pure-MLV still gains `+21.65 pts/slot` (p=0.0002) — but it sheds **42% of its championship
  probability** (0.1077 → 0.0624, p=0.9998). The old harness could only see the points half of that
  trade. **λ is the load-bearing term**: switching it off costs _both_ win probability and points,
  and doubling it also hurts, so the shipped schedule sits near a local optimum.

  **The re-run still says KEEP baseline**, but informatively: the tuned vector is _significantly_
  better on win probability (`+0.0130/slot, p = 0.0029`) and fails only the
  non-negative-at-every-slot leg by `−0.0014` — a margin inside Monte-Carlo noise. Nothing was
  written; the CLI is dry-run unless you pass `--write`, and `config/engine.json` stays
  owner-adopted. **No action needed from you** unless you want to revisit that gate leg.

  ✅ **The old "α does nothing" warning is RESOLVED — Tier 5 fixed the tiering (2026-07-27,
  PRs #50–#52).** The tier-cliff term now works on the board you will actually draft against:
  **16 priced drops** where there were **0**, at all six positions. Three things were wrong at once:
  the tiering algorithm chose the number of tiers by a criterion that answers "one tier" for a
  smooth value curve; tiers were cut on expert rank while the cliff was priced in projected points
  (the same ordering when μ was `300 − ecr`, no longer with real xEP); and tiering the whole board
  put every boundary below replacement, where a drop is worth nothing. Biggest real cliffs on the
  2026 board: **TE1 is 43.88 points clear of TE2**, **RB1 is 40.13 clear of RB2**. Kickers top out
  at 2.97 — the honest answer for a streaming position, not a manufactured number.

  ### ⚠️ A DECISION FOR YOU — the tier-cliff term now works, and it makes things WORSE

  With the term finally live, the calibration harness could measure it for the first time. It says
  **turn it off.** Setting `alpha` to 0 gains **+0.0133 championship probability per slot**
  (`p = 0.0002`) _and_ **+5.28 points per slot** (`p = 0.0002`), and is non-negative at **every one
  of the 12 draft slots** — the first vector in this project's history to pass **both** legs of the
  no-regression gate. The response is monotone, so this is not one lucky point estimate:

  | `alpha`                    | championship probability |
  | -------------------------- | ------------------------ |
  | **0.0**                    | **0.1059**               |
  | 0.3                        | 0.0940                   |
  | **0.4 (what ships today)** | **0.0926**               |
  | 0.5                        | 0.0870                   |
  | 0.8                        | 0.0871                   |

  The likely reason: `κ·VONA` already prices scarcity, and prices it _better_ — it knows whether the
  player will still be there at your next pick. The cliff bonus adds a second, blunter scarcity
  bonus on top that ignores that. It hurts most at **draft slot 1** (0.0958 → 0.1650 with α off),
  the seat best able to spend the first overall pick on the huge-cliff tight end.

  **Nothing has been changed.** `config/engine.json` is yours; the calibration CLI is dry-run unless
  you pass `--write`, and a simulator result is not a fact about drafting — the opponents are bots,
  not the eleven people in your room. **If you want it, the whole change is one line** in
  `config/engine.json`:

  ```
  "alpha": 0.0,
  ```

  Note this is outside the plan's specified `alpha` range of 0.3–0.5, i.e. the measurement says the
  spec's own bounds exclude the best value. Leaving it at 0.4 is a defensible call too — you would
  be trading a measured simulator edge for the tier-cliff explanation showing up in `Why?`.

  ⚠️ **Tier 6 update — one leg of that claim does not replicate.** Re-running the same comparison
  over **five independent seed blocks** instead of one:

  | α = 0 vs the shipped α = 0.4       | across the 5 blocks                                                  |
  | ---------------------------------- | -------------------------------------------------------------------- |
  | average gain                       | **positive in 5 of 5** (+0.0133, +0.0063, +0.0033, +0.0133, +0.0086) |
  | "non-negative at every draft slot" | **held in only 1 of 5**                                              |

  So **the headline still stands — α = 0 is better on average, every time we measured it** — but the
  "first vector to pass both legs" part was a property of the one seed block Tier 5 happened to use.
  The gate's second leg turned out to be measuring its own noise (it decides at ~0.001 while the
  noise is 0.001–0.009), which is now fixed. **This does not change the recommendation, only how
  strongly it was stated.** Still your call, still one line, still nothing changed for you.

  ℹ️ **Tier 6 also found a signal on two OTHER knobs — but it is NOT yet a recommendation.** A
  one-factor sweep says the scarcity weight `kappa` wants to be roughly **double** what the plan
  allows (still improving at 1.50 vs the 0.80 ceiling), and the risk schedule `lambda` wants to be
  about **half** its current magnitude. Both replicate across two independent seed blocks.

  **Do not change either yet.** Those numbers measure championship probability only; nobody has
  measured what they do to expected POINTS, and the one time we checked such a trade (Tier 5, for
  `kappa`) it turned out to buy championship odds _by giving up points_. Asking you to adopt a knob
  on half the evidence is exactly the mistake this audit keeps finding. Details in `ROADMAP.md` §6;
  the missing measurement is the next tier's job. **Nothing has been changed.**

  ⛔ **Tier 7 update — those numbers are now OUT OF DATE, including the `alpha = 0` recommendation
  above.** Tier 7 fixed the measuring stick itself (see §1b): a roster that cannot field a legal
  lineup used to score almost as well as one that can, and _every_ calibration number in this
  section was produced with that broken stick. They are not wrong so much as **no longer
  comparable** — the whole scale moved. Re-measuring is the next tier's first job.

  **What this means for you: there is currently NO knob recommendation on the table.** The
  `alpha = 0` suggestion above is suspended until it is re-measured, not withdrawn. Leaving
  `config/engine.json` exactly as it is remains the right call, and is what the code ships with.

  ### 🔴 A DECISION FOR YOU — one setting is costing you most of your title odds `[NEW — Tier 8]`

  Tier 8 repaired the calibration harness (it had been unable to see this setting at all — see §1b)
  and then measured it properly for the first time: **real board, five independent seed blocks, 40
  drafts per seat, 800 simulated seasons each.** The result is the largest effect this project has
  ever measured, by a wide margin.

  The setting is `lambda_slot_override`. It has two halves: a **bonus** for drafting an unpredictable
  player you do _not_ need, and a **penalty** for drafting a steady player you _do_ need. Turning
  both off:

  | measure                      | shipped today | with the setting off | change      |
  | ---------------------------- | ------------- | -------------------- | ----------- |
  | **championship probability** | **0.0121**    | **0.0866**           | **+0.0745** |
  | **projected points**         | **1462**      | **1705**             | **+243**    |

  For scale: in a 12-team league an average team wins **0.0833** of the time. The engine as shipped
  wins **0.0121** — about one seventh of its fair share. With this one setting off it is back to
  roughly average. It gains on **both** measures, at `p = 0.0002` on each, and it is better at **every
  one of the 12 draft seats** — the first change in this project's history to clear that bar on both
  measures with replicates.

  **Why it goes so wrong.** The bonus is multiplied by how unpredictable a player is, and that varies
  enormously _by position_ — typical spread is 20 for a kicker, 25 for a defense, but **106 for a
  quarterback**. Since the bonus and the penalty apply to opposite candidates, the engine can swing a
  comparison by ~85 points on unpredictability alone, which is more than the entire value signal in
  the late rounds. A real example from round 15 on your board: it took a running back its own value
  model scored at **−45** over a kicker it scored at **0**, purely on this bonus. (Kickers and
  defenses are worse still: every kicker has the identical unpredictability number, so for them this
  term carries no information at all — it is a pure positional thumb on the scale.)

  **If you want it, the whole change is two lines** in `config/engine.json`:

  ```
  "lambda_slot_override": {
    "last_startable_slot_floor": 0.0,
    "surplus_stash_ceiling": 0.0
  },
  ```

  **Nothing has been changed.** `config/engine.json` is yours, the calibration CLI is dry-run unless
  you pass `--write`, and a simulator result is not a fact about drafting — the opponents are bots,
  not the eleven people in your room. But this is a much stronger result than the `alpha` one above,
  measured on five seed blocks rather than one, and it points the same way on both measures rather
  than trading one for the other. **If you change one thing before draft night, change this.**

  ### 🔴 STILL OPEN — Tier 9 tested the same setting a second way, and it is worse than we thought

  **This decision is still waiting on you.** As of 2026-08-09 `config/engine.json` still reads
  `0.4 / -0.4`; nothing has been changed, and nothing will be without you saying so.

  Tier 9 re-tested it on a completely different measurement — the **efficacy tournament**, which
  races the engine against a "just take the best available player" baseline at all twelve draft
  seats — and ran that tournament **on your real player board for the first time**. Every number
  below is the real board, not a practice fixture:

  | measure                      | engine as shipped | with the setting off | plain best-available |
  | ---------------------------- | ----------------- | -------------------- | -------------------- |
  | **championship probability** | **0.0072**        | **0.0683**           | **0.1066**           |
  | **projected points**         | **1460**          | **1714**             | **1662**             |

  Read that table twice, because it says two things and they pull in opposite directions.

  **The bad news first: as shipped, your engine is beaten by a plain best-available draft on _both_
  measures.** Not a trade — worse at winning the title _and_ worse on points, by 202. In a 12-team
  league an average team wins 0.0833 of the time; your engine as shipped wins **0.0072**, about one
  twelfth of its fair share.

  **The good news: turning this one setting off recovers most of it.** Championship odds go from
  0.0072 to 0.0683 and points from 1460 to 1714 — better on both, at p = 0.0002 on each. It becomes
  the **best points-scorer in the field**, ahead of best-available by 52.

  ⚠️ **But be clear about what it does not do.** Even with the setting off, the engine still wins
  the title _less often_ than a plain best-available draft (0.0683 vs 0.1066). So this change is a
  large, well-measured improvement and it is **not** a clean win over the naive baseline. Something
  else is costing you roughly half a fair share and nobody has found it yet — that is the next
  tier's job. An earlier draft of this note said the setting-off engine beat the baseline outright;
  that was measured on the practice fixture and **the real board disagrees.** The real board wins.

  **And the reason is worse than Tier 8 described.** Tier 8 called this a late-round problem. It is
  not — it starts in **round 3**. Walking a draft with your real settings, the engine spent picks
  **three and four** on the 15th- and 20th-best tight ends, both of them worse than a freely
  available replacement, both scored by its own value model at exactly **zero**. It took them
  because this setting pays a bonus for unpredictability that has nothing to do with whether the
  player can ever enter your lineup. It ends up holding **three tight ends** — the maximum your
  roster can hold — when it can only ever start one.

  The mechanism, in one line: the setting keys off _how many starting slots a position has left
  open_, and any position with a **single** starting slot (QB, TE, K, DST — four of your six) is
  therefore permanently in one of the two override states and never in the normal one. Your
  round-by-round risk schedule only ever applies to running backs and receivers.

  **The change is still the same two lines**, and it is still entirely your call:

  ```
  "lambda_slot_override": {
    "last_startable_slot_floor": 0.0,
    "surplus_stash_ceiling": 0.0
  },
  ```

  Tier 9 also tested the obvious code alternative — leaving the setting in place but making it
  behave like the normal round-by-round schedule — and it is **worse** than simply turning it off.
  So there is no cleverer fix waiting; this is the decision.

  ### ✅ TIER 10 UPDATE — the missing half has been found and fixed, and it makes this decision matter more

  Tier 9 ended with "even with the setting off, something else is costing you roughly half a fair
  share and nobody has found it yet." **Tier 10 found it, and it was not a setting at all.**

  From the moment your nine starting slots are full, every remaining player the engine could take
  scored **exactly the same** — zero. Not "close to zero": bit-for-bit identical. So the engine had
  no opinion at all about **8 of your 17 picks**, and the tie was being settled by the order players
  happened to sit in an internal list. In one measured case its top recommendation was a player
  projected for **122.9** points while a player projected for **204.2** sat in the same tie.

  That has been fixed in code (nothing for you to do): when the engine genuinely cannot tell two
  players apart, it now prefers the one worth more relative to a freely available replacement.

  **Why this changes the decision above rather than replacing it.** The fix and the setting are
  **coupled** — measured on your real board:

  | what you run                       | championship probability | projected points |
  | ---------------------------------- | ------------------------ | ---------------- |
  | today's settings, before the fix   | 0.0072                   | 1460             |
  | today's settings, **with the fix** | 0.0071                   | 1450             |
  | **setting off**, before the fix    | 0.0683                   | 1714             |
  | **setting off, with the fix**      | **0.1161**               | **1717**         |
  | plain best-available (the bar)     | 0.1066                   | 1662             |

  Read the second row carefully: **while this setting is on, the fix does not help you — it costs
  you about 10 projected points.** That is small but it is a real, measured loss, not noise. With
  the setting live the engine was already breaking those ties — badly, on unpredictability — so
  there was nothing left for the fix to improve, and it slightly reshuffles which players the engine
  considers at all. Turn the setting off and the same fix is worth **+0.0478** championship
  probability instead.

  So the honest summary is: **the code that just shipped makes your engine marginally worse until
  you change these two lines, and substantially better once you do.**

  So: **the two lines below are now worth more than they were yesterday**, and they are still the
  only thing on your desk.

  ```
  "lambda_slot_override": {
    "last_startable_slot_floor": 0.0,
    "surplus_stash_ceiling": 0.0
  },
  ```

  ⚠️ **Be precise about what the combination buys.** With both, the engine **beats** a plain
  best-available draft on points (+55, a solid result) and is **level with it** on championship
  odds — 0.1161 against 0.1066, ahead by an amount too small to call a win (the measurement's own
  noise is about twice that gap). It is the first time the engine has not been _behind_ the naive
  baseline, and the first time it sits above a 12-team average (0.0833). It is not yet a win.

  **Nothing has been changed.** `config/engine.json` is yours; verified 2026-08-09 it still reads
  `0.4 / −0.4`.

  **Nothing has been changed, again.** `config/engine.json` is yours. A simulator is still not a
  fact about drafting — the other eleven teams are bots, not the people in your room. What is now
  measured, on your real board and on a practice board, under three different opponent line-ups, is
  that this setting costs the engine on **both** measures every time it is tested.

  ### ⚠️ TIER 11 UPDATE — the measuring stick itself was skewed, and the numbers above move

  **The decision does not change. The scoreboard does.** Tier 11 found that the practice harness —
  the thing that produces every number on this page — was applying your kicker/defense reliability
  discount **twice**, so it rated a kicker 2.5× closer to "freely available" than your real engine
  does. That affected the practice **opponents** and the **scorekeeper**, not really your engine's
  own picks. Corrected, and re-measured on your real board with the same five independent seed
  blocks:

  | measure                      | engine as shipped | with the setting off | plain best-available |
  | ---------------------------- | ----------------- | -------------------- | -------------------- |
  | **championship probability** | 0.0063            | **0.1109**           | **0.1206**           |
  | **projected points**         | 1453              | **1739**             | 1703                 |

  **What still holds, unchanged.** Turning the setting off is worth going from **0.0063 to 0.1109**
  championship probability and **+286 points** — the largest effect in this project, and it is if
  anything larger than yesterday's version of the same table. **If you change one thing before draft
  night, this is still it.**

  ⚠️ **What moved, and you should hear it plainly.** Yesterday this page said the setting-off engine
  was _level with_ best-available on championship odds and slightly ahead (0.1161 vs 0.1066). On the
  corrected scoreboard it is **level and slightly behind** (0.1109 vs 0.1206). It is still a tie —
  the gap is smaller than the measurement's own noise, both yesterday and today — but the point
  estimate has crossed to the other side of zero, and this project has a habit of quoting the
  friendly half of a tie. It still **beats** best-available on points (+36, solidly measured), and
  it still sits above a 12-team average (0.0833). It is **not** a win over the naive baseline.

  **And a second scorekeeper now disagrees with the first.** Tier 11 also built a week-by-week
  scorekeeper — real bye weeks, real injury/no-show rates, and the fact that a quarterback and his
  own receivers have good weeks together — because the old one had no concept of a week at all and
  therefore valued your entire bench at exactly **zero**. On that scorekeeper the setting-off engine
  comes out **ahead** of best-available on championship odds (0.1192 vs 0.1086), and by enough to
  clear the significance bar.

  ⚠️ **That would be the first time this engine has ever beaten the naive baseline on championship
  odds, and it is deliberately NOT being claimed.** The scorekeeper that says so is one day old and
  was built in the same tier that is reporting the result. Every tier of this audit has found the
  previous tier's headline wrong, and "we built a new ruler and the new ruler says we win" is exactly
  the shape of the findings that had to be withdrawn. It needs an independent re-run before it means
  anything.

  What both scorekeepers **do** agree on: the setting-off engine beats best-available on **points**
  (+36 and +35, both solidly measured), and turning the setting off is worth an enormous amount
  against your current config on every measure tried. That is the decision on your desk, and it is
  unaffected by which scorekeeper is right.

  **Nothing has been changed.** `config/engine.json` is yours; verified again 2026-08-09, it still
  reads `0.4 / −0.4`.

## 1b. ⛔ READ BEFORE DRAFT NIGHT — the engine goes blind in the late rounds `[NEW — Tier 6]`

**You must fill QB, K and DST yourself. The engine will not tell you to.**

Tier 6 walked a full 12×17 draft on the real board using the engine's own recommendations. It
produced this roster:

```
R1:TE R2:WR R3:WR R4:WR R5:TE R6:TE R7:TE R8:TE R9:TE R10:RB R11:TE R12:TE R13:TE R14:TE R15:TE R16:TE R17:TE
-> 13 tight ends, 3 WR, 1 RB.  ZERO QB, ZERO K, ZERO DST.
```

That roster **cannot field a legal starting lineup** — **four** of your nine starting slots would be
empty. (Tier 6 said three. It counted the missing _positions_ — QB, K, DST — and forgot the
**WR/RB flex**: your 1 RB and 3 WR fill the RB slot and the three WR slots exactly, leaving the
flex with nobody. Corrected in Tier 7.) It happens identically whether the other eleven teams draft
greedily or realistically, so it is not an artifact of the simulation. And the players were there
for the taking: at your round-17 pick there were **21 kickers available** and the best one was
ranked **53rd**; at round 16, **20 defenses** available, best ranked **55th**; **38 quarterbacks**
available at round 10, best ranked **150th**.

**Why.** From about round 5, every remaining player at every position you still need is projected
below "replacement level", and the engine measures a player by how much he adds to your _starting_
lineup. A below-replacement player adds nothing — so the engine scores a quarterback you desperately
need exactly the same as a thirteenth tight end you cannot start: **zero**. With every value signal
at zero, the only thing left moving the ranking is the uncertainty term, which late in the draft is
tuned to prefer _high-variance_ players — and that number is nearly identical for everyone at a
position. The result is close to arbitrary. In round 13 it recommended a player projected for **16
points** over one projected for **83**.

**What to do on the night — a 30-second rule:**

1. Trust the engine for **rounds 1–9**. Its value signal is real and live there.
2. From **round 10**, before you look at the list: _do I still need a QB, K or DST?_
3. If yes, take the best one **yourself** — do not wait for the engine to surface it.
4. Use the engine's late-round list only to choose **among players at a position you actually want**.

The overlay is honest about this if you look: those picks show `MLV 0.00` and the rationale reads
`risk tilt` rather than `value`. That is the engine telling you it has no value opinion.

✅ **MOSTLY FIXED IN TIER 7 (2026-07-27) — but read the one remaining case below.**

The engine now understands that a replacement-level player is only worth counting **while you still
have a pick left to draft him**. Two things were wrong, and neither was what Tier 6 guessed:

1. Once a position was fully spoken for league-wide, the engine measured the best available
   quarterback **against himself**, so his value came out at exactly zero every single round.
2. The measuring stick used to test the whole engine could not tell a roster with no quarterback
   from one with a replacement quarterback. On your real board it reported a **+15.34**-point gap
   where the true gap was **+260.77** — it could see 5.9% of the problem. That is why six rounds of
   calibration never caught this: the test could not fail.

Walking the same draft again on your real board, from the same seat:

|                                | roster                                 | legal?                      |
| ------------------------------ | -------------------------------------- | --------------------------- |
| before                         | `{RB:1, TE:13, WR:3}`                  | ✗ four empty starting slots |
| after                          | `{DST:1, K:1, QB:1, RB:2, TE:8, WR:4}` | ✅ **all nine**             |
| after, vs. realistic opponents | `{DST:1, QB:2, RB:1, TE:9, WR:4}`      | ✗ **no kicker**             |

⚠️ **The one case still broken: it can take a second QB instead of a kicker.** In the last rounds
the engine gets a bonus for drafting _high-uncertainty_ players (sensible for a bench flier). That
bonus is currently paid even for a player you could never start — a **second** quarterback, when
you can only ever play one. At round 16 that bonus was worth **+68** points to a backup QB, against
a kicker worth **+2.6**, so the kicker lost. Fixing it means changing a dial in
`config/engine.json`, which is **yours**, and it needs the calibration harness to sign off first —
so it is the next tier's job and nothing was changed for you.

**So the 30-second rule above still applies, with one change:** you can now trust the engine to
take a QB, K and DST on its own in the last few rounds — but **at round 16 and 17, if you still
have no kicker, take one yourself.**

### ✅ CORRECTED IN TIER 8 (2026-08-07) — the reason above is wrong, but keep the habit

**The engine does draft your kicker.** Everything above this line diagnosed a real symptom and
blamed the wrong thing. Tier 8 walked the draft from **all twelve seats against two different
opponent styles — 24 full drafts** — and the engine as shipped filled **all nine starting slots in
24 of 24**, taking its kicker in **round 16** on average.

What was actually broken was the **practice-opponents**, not the engine. In the simulation the other
eleven teams were drafting kickers and defenses they could never use — up to **five kickers each**,
consuming **all 33** on the board. No engine can draft a kicker from an empty board. Real managers
cannot do that (your league gives them one kicker slot and a bench that does not accept kickers), so
this never described your actual draft. Once the practice opponents were made to obey the roster
rules, the problem vanished — for every version of the engine we tried.

**This is the third tier in a row to blame the engine for it, and the first to test the assumption.**

⚠️ **TIER 9 CORRECTION (2026-08-09) — the same setting is also spending your EARLY picks.**
Everything above treats the uncertainty bonus as a late-round quirk. It is not. Measured on
2026-08-09, with your committed settings, the engine spends **round 3 and round 4** on tight ends it
can never start — its own value model scores them at exactly zero — because that bonus outbids the
running backs and receivers it should be taking. So the fix is not a late-round tidy-up; it is worth
about **five times your championship odds**, and it is the decision sitting in §1 above.

This does **not** change the rule below. Rounds 1–9 are still where the engine's value signal is
strongest, and glancing at your empty slots from round 14 is still free.

**Your 30-second rule, updated:**

1. Trust the engine for **rounds 1–9**. Unchanged.
2. From **round 14**, take five seconds to glance at your empty starting slots. Not because the
   engine is expected to fail — it did not fail once in 24 tests — but because a simulator is not
   your draft room, this exact question has been answered wrong three times, and checking is free.
3. If a slot is empty with only a pick or two left, take that position yourself.

You no longer need the old "at 16 and 17 take a kicker yourself" rule.

⚠️ **A question for you, because the answer changes the code.** Your league file says `Bench: 8` and
does **not** say which positions a bench spot accepts. The code assumes **quarterbacks, running
backs, receivers and tight ends only — no kickers or defenses** (`league/constitution.py`, whose own
comment calls this "a JAAFFL modeling choice"). That assumption is what makes "one kicker per team"
the rule the practice opponents now follow. **Does CBS let you put a kicker or a defense on your
bench?** If it does, say so and it is a one-line change. Nothing was altered in `config/league.json`,
which stays immutable.

> 📊 **Tier 10 gave that question a price.** It used to be abstract; now it is measured. The Tier 10
> tie-break prefers the player worth more relative to a freely available replacement — and by that
> yardstick a spare kicker looks better than a deep receiver, because the kicker sits a few points
> under his replacement while the receiver is 120 under his. The **practice draft** never notices,
> because there the engine is forbidden from drafting a player it cannot roster. **Your live overlay
> has no such rule** — deliberately, because adding one would bake in the guess above about what your
> bench accepts.
>
> Walking three full 17-round drafts through the real recommendation code, 51 of your picks:
>
> ```
> before Tier 10:  0 of 51 picks were at a position your roster was already full at
> after  Tier 10:  1 of 51   (a second kicker, round 12, at one seat of three)
> ```
>
> So the cost of leaving this open is roughly **one wasted late-round suggestion per draft**, and the
> 30-second rule above already catches it. **Tell us whether CBS lets a kicker or defense sit on your
> bench** and that goes to zero; until you do, nothing will be assumed on your behalf.

✅ **Also new in Tier 6 (no action needed):** the overlay's **bye-week chip now actually works**. It
was declared, styled and rendered all along, but nothing ever filled it in, so it could never
appear. It now reads the free NFL schedule: **485 of the 510 draftable players carry a real bye
week** (the other 25 are free agents, who have no team and so no bye).

Steps (kept for the next capture — e.g. a settings-page capture, or re-verifying on draft night):

1. Open a CBS mock draft with the extension loaded.
2. Click the extension action button to toggle **record mode**.
3. Run the mock draft to completion (frames land git-ignored under
   `apps/extension/fixtures/cbs/` via `POST /dev/recordings`).
4. Tell Claude "capture done."

Two things learned the hard way, worth knowing before the next one:

- **`make` is not installed** on the owner's Windows setup, so the guide's `make backend-dev` fails.
  Use `cd backend && ../.venv/Scripts/python.exe -m jaaffl.api` (now documented in the guide).
- **Chrome will prompt for "access other apps and services on this device."** That is Chrome's Local
  Network Access gate on the CBS page reaching `127.0.0.1:8788` — i.e. our own backend. It must be
  allowed or recording silently stalls. Revoke it afterwards via the icon left of the URL if desired.

Not a build blocker: the engine, nflverse + FFC providers, and the `/recommendation` + `/recs/ws`
surfaces are fully built and tested. Manual-paste stays the guaranteed draft-day fallback regardless.

## 2. Paid data providers `[WHEN YOU WANT IT — off by default]`

The $0 tier (nflverse + FFC + CBS on-page) needs **no keys**. Only if you want fresher injuries
or an extra ADP/projection source:

1. Get an API key (FantasyPros is the cheap, recommended upgrade for live injuries).
2. Set the key + its enable flag in `.env` (e.g. `FANTASYPROS_API_KEY=...` and
   `JAAFFL_ENABLE_FANTASYPROS=true`).
3. The provider then appends after the free tier automatically. (Its adapter is a disabled stub
   today — tell Claude if you enable one so the real API calls get implemented.)

## 3. FFC resolution coverage (informational — no action required) `[WHEN YOU WANT IT]`

Preseason real-flow check (2026): FFC ADP resolved **144 / 166** players to canonical ids; the
~22 unresolved are team defenses named "<City> Defense" and a few kickers/rookies not yet in the
free DynastyProcess crosswalk. Unresolved rows are logged and skipped (the engine tolerates gaps),
and all skill-position starters resolve. If you later want K/DST ADP fully covered, ask Claude to
add a DST city→team alias map; otherwise it's a safe, low-impact gap (K/DST go in the last rounds).

## 3b. Two Tier-2 decisions left for you `[WHEN YOU WANT IT]`

Neither blocks anything; both are judgement calls rather than bugs.

- **Monte-Carlo VONA is opt-in and slow on purpose.** `?mc=true` now genuinely runs (it used to be
  a silent no-op). Measured on the pick-1 worst case: **analytic p95 9 ms · MC p95 1.14 s** at the
  shipped `mc_rollouts = 2000`, against the plan's `<2 s` MC budget. It is NOT on the `/recs/ws`
  push path — the overlay always gets the analytic number — so you only pay this when you ask for
  it by hand. If you ever want MC on the live path, drop `mc_rollouts` (it is a real, tested
  budget knob) rather than raising the budget. MC and analytic **disagree on the #1 pick** on the
  synthetic board, so this is a genuine second opinion, not a rounding difference.
- **`ESTIMATED` currently means "degraded board", not "forward-year".** §6.6 names forward-year
  (2027) figures as the trigger. Nothing on the contract flags a forward-year projection today, so
  the badge is driven by the trigger we can actually detect: a manually-pasted or non-live board.
  Same badge, same treatment — say the word if you want a forward-year flag plumbed through too.
  **Tier 3 re-checked this and left it deliberately:** projections are built with
  `xep_season = season − 1` (nflreadpy _raises_ for the current season — xEP is retrospective), so
  there is **no forward-year figure anywhere in the system** for the trigger to fire on. Plumbing
  the flag now would add a contract field that is always false. It becomes real work the day a
  forward-year vendor feed is licensed.

- **`Why?` is still local, not the Responses API.** §6.8 wants the explanation rendered through
  `assistant/tools.py::explain_recommendation` over OpenAI. Your `OPENAI_API_KEY` now exists, so
  this is unblocked — but Tier 3 did not take it, on purpose. `Why?` sits on the one surface that
  must not stall mid-draft, and routing it through a network call adds a latency budget, a failure
  mode, and a per-click cost to a panel that currently renders instantly and works with the backend
  down. It deserves its own design (streaming? cached? pre-warmed at the pick?), not a bolt-on.
  Say the word and it gets one. This remains the last key-gated piece in Stage 7.

- **MC-VONA has no wall-clock CI gate, on purpose.** At the shipped `mc_rollouts = 2000` the local
  p95 is 1.14 s against a 2 s budget — ~43% headroom, which a slower CI runner would eat. A gate
  there would either flake or be loosened until it meant nothing. CI instead asserts the invariant
  that actually protects draft night: **MC cannot reach the `/recs/ws` push path at all**
  (`test_mc_off_hot_path.py`, verified by mutation — the guard was confirmed to fail when the push
  path is made to request MC). The timing number stays a local measurement.

## 4. Stage 6 (UI) — live data + deferred panels

The dashboard + overlay are built, tested, and render the full decomposed recommendation
live. Three items are opt-in / follow-up, none block the UI:

- **Live $0 recommendations — ✅ RESOLVED (PR #14, merged `fb338d2`; no owner action needed).**
  `NflreadpyProvider.players()` now loads the FREE nflverse universe via `load_ff_playerids()`
  (real pull verified: **4,571 players**), so a live server serves `GET /recommendation`
  **503→200** on the $0 tier with **no fixture injection**. `JAAFFL_PRECOMPUTE_ENABLED` now
  **defaults to true** (PR #30) — it used to default to false and was absent from `.env`, so a
  fresh clone followed the documented setup and still got a permanent 503.
  `ingest/resolve.resolve_pick_ids` masks name-only manual-paste picks upstream of the frozen
  `recommend()`; recorded fixtures keep CI offline. _(This was the former `[BLOCKER]`; it is done.)_
- **Draft board + pick-log panels** `[DONE — branch feat/post-v1-unblocked]`. Shipped: `GET /state`
  (folded `DraftState` + drafted-player name resolution) and the dashboard **board (round × team
  grid, self-ordering to draft slots) + pick-log ticker** (`apps/web` `BoardPanel`), rendered as the
  mockups' table + ticker (semantic table; AG Grid stays removed as overkill). Value-curve / survival
  / manager-tendency panels remain the follow-up analytics.
- **Vercel deploy auth** `[WHEN YOU WANT IT — otherwise it's localhost]`. The dashboard runs
  local-first at `127.0.0.1`. Hosting it on Vercel is opt-in and needs your Vercel auth; not done.
- **Status-pill text contrast (WCAG AA) — design-palette decision** `[WHEN YOU WANT IT]`. The
  small status pills (`.is-good/.is-warning/.is-critical` in `design/tokens/draft-room.css`) render
  the accent hue as text on a 15–17% tint of the same hue. In the **light** theme the ~11px pill
  text falls below the 4.5:1 AA contrast minimum (measured roughly: good ≈2.6:1, warning ≈1.5:1,
  critical ≈3.6:1; critical is also ≈3.3:1 in dark). This is **not** a functional a11y blocker —
  identity is never colour-alone (every pill carries a glyph + word, satisfying WCAG 1.4.1), and
  the surrounding body text/ink/focus are AA — but the pill _text legibility_ itself is sub-AA.
  It was left for you because a correct fix darkens the pill text in light mode (and would brighten
  it in dark), which touches the Appendix-B brand palette. Concrete proposed fix (no chart/bar
  impact): add theme-aware `--pill-ink-{good,warning,critical}` tokens (dark shades in light theme,
  bright in dark) used only by the three `.is-*` selectors' `color`, leaving the tinted
  backgrounds/borders as-is. Tell Claude "approve the pill-contrast tokens" (or hand over your own
  brand-safe shades) and it lands with a contrast check baked into the token drift-guard.

## Later phases (add here as they surface)

- Stage 7 assistant: an OpenAI key (`OPENAI_API_KEY`).
- Any MCP / connector authorizations a future phase needs.
