# Tier 12: the room is ticking, and the engine never learned the order — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eleven tiers have hardened the engine against a simulator; none has run it against a CBS
room with a clock. **(A)** Before writing a rehearsal at all, driving the live FastAPI surface
showed the headline question is already answered: `survival_basis` is `degraded_no_slot` on
**every** live recommendation, because the entered draft order is decoded from
`fullstatedelta.order` and then dropped twice before it reaches `recommend()`. Fix that seam.
**(B)** Instrument the live path so ONE CBS **mock** rehearsal yields evidence — latency,
`survival_basis`, `vona_method`, masking, crosswalk resolution, what the overlay rendered —
rather than impressions.

**Architecture:** (A) The room's order rides on `DraftState.draft_order` (folded verbatim from the
`league_settings` event the extension already emits), never on `DraftContext.settings` — the
context is built and cached **before** the order is known, and `config/league.json` forbids
inferring one. `recommend()` and `build_analytics` overlay the state's order onto the context's
settings for the duration of one call. (B) A JSONL rehearsal sink at the two recommendation call
sites, off unless `JAAFFL_REHEARSAL_LOG` is set, plus a report script that turns the log into a
pass/fail evidence table. Frame disorder is tested **deterministically** off the Tier-3 capture;
the rehearsal only reports whether it occurred live.

**Tech Stack:** Python 3.12, pytest, FastAPI, pydantic v2; TypeScript, vitest, Zod. No new
dependency. No coefficient. **No edit to `config/engine.json` or `config/league.json`.**

---

## Why this shape (measured 2026-08-10; every number labelled with its pool)

### The control: the live surface still behaves as Tier 11 left it

Server on `127.0.0.1:8788` at `4f7442b`, 25 events posted, then pulled:

| check                | result                                          |
| -------------------- | ----------------------------------------------- |
| `/health`            | `200 {"status":"ok","version":"0.0.0"}`         |
| `/draft/events` × 25 | all `accepted`, `deduped:false`                 |
| `/recommendation`    | `200`, 50 ranked, `vona_method="analytic"`      |
| `recompute_ms`       | **5.36 / 6.00** against the < 200 ms budget     |
| `/recs/ws`           | `hello` (v1, schema 1.0.0) → `snapshot`         |
| `/draft/ws`          | `{"control":"pong"}`, `ack seq=37 pick_number=25` |

Every Tier 12 claim rests on that control.

### 🔴 FINDING — the live path cannot compute a survival model, and no setting fixes it

`survival_basis` came back `degraded_no_slot` **including with `?team_id=1` supplied**. Three links,
each read directly:

1. `apps/extension/src/lib/parse.ts:156` — `parseDraftOrder` decodes `fullstatedelta.order` into a
   `league_settings` event carrying the real entered order, length-guarded at exactly 12. ✅ This
   half works; it is Tier 3's capture-decode work.
2. `backend/src/jaaffl/ingest/log.py:196` — `fold_state`'s `LEAGUE_SETTINGS` branch reads **only**
   `my_team_id`. `draft_order` is discarded.
3. `backend/src/jaaffl/league/constitution.py:71` — `resolve_league_settings` returns
   `draft_order=None` unconditionally, and its docstring states a snapshot never rewrites it.
   `DraftContext.settings` is the only thing `recommend()` reads.

So `opponents._my_overall_picks` always raises → `recommend()` catches it → survival degrades to
"everyone is still available".

Verified directly, not inferred:

```
snapshot present     : False
engine draft_order   : None          <- resolve_league_settings(..., snapshot=snap)
engine team_count    : 12
normalized order     : ['1', ..., '12']   <- normalize_league_settings DOES parse it correctly
```

⚠️ **Tier 3's fix is necessary but not sufficient, and this plan supersedes how it was described.**
`docs/owner-manual-todo.md` §1 tells the owner that setting `JAAFFL_MY_TEAM_ID` restores the real
VONA. It cannot: the second required input has no wiring at all. `JAAFFL_MY_TEAM_ID` is still
EMPTY in `.env` (verified 2026-08-10), and filling it in today changes nothing on the live path.

### Measurability FIRST — and the first attempt was vacuous

The obvious refutation is Tier 8's: `reliability_shrinkage` moved 0 of 60 rosters because the punt
guard dominated it. If supplying the order moved no pick, this would be a cosmetic flag fix.

**The first measurement was thrown away.** It walked 17 rounds with synthetic picks carrying
`player_id=None`, so nothing was masked, the board never depleted, and McCaffrey was the top
recommendation in all 17 rounds under both arms — "0 of 17 moved" was an artifact of a board that
never changed. Rebuilt to draft real canonical ids off the context.

Real board, 581 players, **the same board fed to both arms**, ADP opponents, my slot = 7:

| arm                       | candidates with `vona > 0` | top recommendation      |
| ------------------------- | -------------------------- | ----------------------- |
| shipped (`draft_order` None) | **0 / 50, in all 17 rounds** | —                       |
| order supplied            | 1–13 / 50                  | **differs in 3 of 17 rounds** |

Walking each arm's own draft, **5 of 17 picks differ**. `config/engine.json` sets `kappa: 0.65`,
and it multiplies `max(0, VONA)` — a term that is **identically zero on every live pick today**.

⚠️ Do not quote "5 of 17" as an effect size. Once one pick differs, every later board differs, so
that field says "something changed", not "how much". The clean instrument is the same-board
comparison: **3 of 17**, and the 0/50 → 1–13/50 count.

### The instrument, again — instance EIGHT, and it is the default fixture

`backend/tests/engine_fixtures.py:110` — `make_context()` defaults to
`settings or jaaffl_settings(draft_order=teams(12))`. **Every engine test in the suite hands the
engine a draft order the production wiring drops.** Two consequences:

- `backend/tests/test_my_team_slot.py` — Tier 3's own regression test — asserts
  `survival_basis == "my_slot"` and passes, because `_primed_engine()` calls `make_context()` and
  inherits that default. It has never exercised `resolve_league_settings`.
- `backend/tests/test_cbs_replay.py:202` and `backend/tests/test_e2e_cbs_pipeline.py:121` build
  their context with an explicit `draft_order=[str(i) for i in range(1, 13)]`. The Tier-3 replay
  that "closed the replay gap" replayed real frames through a context whose settings it had
  hand-built — substituting the one component under test.

`backend/tests/test_precompute.py:112` even **pins** `assert ctx.settings.draft_order is None`. The
production behaviour was asserted and the consuming path was fixtured around it, in two different
files, and nothing compared them.

**The new question this tier adds to `test_harness_fidelity.py`:** _does the engine get this input
from the WIRING, or from the fixture?_

### A second, smaller defect found while tracing

`apps/extension/src/lib/parse.ts:503` — `parsePastedReport` accepts an `ORDER:` line of **any**
length and emits it. `opponents._my_overall_picks` uses `len(order)` **as** the team count, so an
11-name paste silently corrupts every "my next pick" calculation for the whole draft.
`parseDraftOrder` (the network path) already guards this at exactly 12 and its comment says why.
The paste path — the guaranteed draft-day fallback — does not.

### Feasibility, checked before committing to the design

- `DraftState` is schema-exported (`packages/shared/schemas/DraftState.json`) and has a Zod twin
  (`packages/shared/src/events.ts:12`) and a canonical fixture
  (`packages/shared/fixtures/DraftState.json`). All three must move together or
  `test_schema_parity.py` and `packages/shared/tests/parity.test.ts` fail. Confirmed by reading all
  three.
- `DraftContext` is a **dataclass**, not a pydantic model (`ctx.model_copy` raises
  `AttributeError`); `LeagueSettings` is pydantic and does have `model_copy`. The override
  therefore happens on the settings object, inside `recommend()`, never on the cached context.
- `engine/analytics.py:59` `_total_picks` returns `rounds * len(settings.draft_order or [])` — i.e.
  **0** on the live path today, so the dashboard's pick markers are already dead for the same
  reason. Same seam, same fix.
- `apps/extension/tests/overlay.test.ts:272-294` already pins the degraded chip's class. The foot
  string itself is a closure (`renderSync`), not exported; the chip predicate is one line and is
  what the report will mirror.

### Design decisions taken deliberately, and surfaced

- **The order rides on `DraftState`, not on the context.** The context is precomputed and cached
  per league before a draft starts; the order is entered in person minutes beforehand. Rebuilding
  or mutating a cached context mid-draft to carry it would fight
  `resolve_league_settings`'s deliberate refusal and would make a shared object time-varying.
- **A wrong-length order is REJECTED and logged, never adopted.** `config/league.json` fixes
  `teams: 12` and is immutable; `agent_usage_contract` says surface conflicts, never silently
  apply them. The fold refuses any order whose length ≠ `team_count`.
- **`survival_basis` gains a third value, `degraded_no_order`.** Today one string covers two
  different owner actions, and the overlay tells the owner to set a draft slot when the actual
  missing input may be the order. Additive on a `str | None` field, so no schema change and old
  payloads still validate.
- **The rehearsal log is OFF unless `JAAFFL_REHEARSAL_LOG` is set** and fails soft, so draft night
  carries zero added hot-path cost or failure mode.
- **Frame disorder is tested deterministically, not hoped for.** A mock may or may not reorder or
  duplicate frames; a shuffled/doubled replay of the Tier-3 capture always can.

### Honest caveats to carry into the docs

- The rehearsal is **n = 1**. One mock, one seat, CBS's bots.
- The `lambda_slot_override` decision stays OPEN and untouched: verified 2026-08-10,
  `config/engine.json` reads `0.4 / −0.4`.
- Fixing the seam changes what `recommend()` computes on the live path. It changes **no**
  calibration number: the harness (`calibrate/tune.py` → `SimContext`) never reads
  `settings.draft_order`, and `simulate.py` derives its own slot schedule. Task 11 asserts this
  rather than assuming it.

---

## File structure

**Backend — create**

- `backend/src/jaaffl/api/rehearsal.py` — the JSONL evidence sink. One responsibility: turn
  `(path, resolved_state, recommendation, context)` into one line, fail-soft.
- `backend/tests/test_draft_order_wiring.py` — the seam, end to end through the live wiring.
- `backend/tests/test_rehearsal_log.py` — the sink's contract and its off-by-default guarantee.
- `backend/tests/test_frame_disorder.py` — out-of-order / duplicated / replayed frames, off the
  Tier-3 capture.

**Backend — modify**

- `backend/src/jaaffl/domain/models.py` — `DraftState.draft_order`.
- `backend/src/jaaffl/ingest/log.py` — fold the order; reject a wrong-length one.
- `backend/src/jaaffl/engine/recommend.py` — effective settings; the `degraded_no_order` basis.
- `backend/src/jaaffl/engine/analytics.py` — same effective settings.
- `backend/src/jaaffl/config.py` — `jaaffl_rehearsal_log`.
- `backend/src/jaaffl/api/app.py` — wire the sink at both recommendation sites.
- `backend/tests/test_harness_fidelity.py` — instance eight.
- `backend/tests/test_engine_latency.py` — the budget on the fixed path.

**Scripts**

- `scripts/rehearsal_report.py` — create. The evidence table.
- `scripts/preflight.py` — modify. The live-room gate.

**JS — modify**

- `packages/shared/src/events.ts` — Zod twin of the new field.
- `packages/shared/fixtures/DraftState.json` — exercise it.
- `packages/shared/schemas/DraftState.json` — regenerated, committed.
- `apps/extension/src/lib/parse.ts` — the paste `ORDER:` length guard.
- `apps/extension/src/overlay/overlay.ts` — render the right degraded reason.
- `apps/extension/tests/manual-paste.test.ts`, `apps/extension/tests/overlay.test.ts` — cover both.

**Docs**

- `docs/rehearsal-protocol.md` — create. The owner's ONE copy-paste block.
- `ROADMAP.md`, `docs/owner-manual-todo.md`, `docs/live-draft-recording-guide.md` — modify.

---

## Task 1: `DraftState.draft_order` — the contract field, on all four sides

**Files:**

- Modify: `backend/src/jaaffl/domain/models.py:158-168`
- Modify: `packages/shared/src/events.ts:12-22`
- Modify: `packages/shared/fixtures/DraftState.json`
- Regenerate: `packages/shared/schemas/DraftState.json`
- Test: `backend/tests/test_domain.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_domain.py`:

```python
def test_draft_state_carries_the_rooms_entered_order() -> None:
    """config/league.json forbids inferring a snake order from team count, so the ONLY place
    the real order can come from is the room. It has to survive the fold, and the fold's
    output is a DraftState — so DraftState is where it lives."""
    state = DraftState(
        league_id="L1",
        current_overall_pick=1,
        draft_order=[str(i) for i in range(1, 13)],
    )
    assert state.draft_order == [str(i) for i in range(1, 13)]


def test_draft_state_order_defaults_to_none_and_is_never_synthesized() -> None:
    assert DraftState(league_id="L1", current_overall_pick=1).draft_order is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_domain.py -k draft_state_carries -q`
Expected: FAIL. Pydantic v2 ignores unknown kwargs by default only when configured to; this model
does not set `extra`, so the field is dropped and the assert reads `AttributeError` or
`assert None == [...]`.

- [ ] **Step 3: Add the field**

In `backend/src/jaaffl/domain/models.py`, inside `class DraftState`, after `my_team_id`:

```python
    # The round-1 team order ACTUALLY ENTERED into CBS, read from the room
    # (parse.ts::parseDraftOrder -> fullstatedelta.order) and folded verbatim. NEVER inferred
    # from team_count (config/league.json -> draft_order.infer_from_team_count = false).
    #
    # It lives on the STATE and not on LeagueSettings because DraftContext is precomputed and
    # cached per league BEFORE a draft starts, while this order is decided in person minutes
    # beforehand. recommend() overlays it onto the context's settings for one call.
    draft_order: list[str] | None = None
```

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_domain.py -k draft_state -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Mirror it in Zod**

In `packages/shared/src/events.ts`, inside `DraftStateSchema`, after `my_team_id`:

```ts
  /** The round-1 team order actually entered into CBS, read from the room — never inferred. */
  draft_order: z.array(z.string()).nullable().optional(),
```

- [ ] **Step 6: Exercise it in the canonical fixture**

In `packages/shared/fixtures/DraftState.json`, add after `"my_team_id": "T07",`:

```json
  "draft_order": ["T01","T02","T03","T04","T05","T06","T07","T08","T09","T10","T11","T12"],
```

- [ ] **Step 7: Regenerate the JSON Schema and confirm parity both ways**

```bash
.venv\Scripts\python.exe scripts\export_schemas.py
git diff --stat packages/shared/schemas
```

Expected: `packages/shared/schemas/DraftState.json` modified, nothing else.

```bash
.venv\Scripts\python.exe -m pytest backend/tests/test_schema_parity.py -q
pnpm --filter @jaaffl/shared test
```

Expected: both PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/jaaffl/domain/models.py backend/tests/test_domain.py packages/shared
git commit -m "feat(contract): carry the room's entered draft order on DraftState

The order is decided in person and entered into CBS minutes before the draft, while
DraftContext is precomputed and cached per league beforehand. LeagueSettings therefore cannot
be where it lives -- resolve_league_settings deliberately returns draft_order=None and a
snapshot never rewrites it. The state is what changes during a draft, so the state carries it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: the fold binds the room's order, and REFUSES a wrong-length one

**Files:**

- Modify: `backend/src/jaaffl/ingest/log.py:196-199`
- Test: `backend/tests/test_ingest_log.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ingest_log.py`:

```python
def test_fold_binds_the_order_the_room_reported() -> None:
    """parse.ts emits league_settings{draft_order} from fullstatedelta.order. The fold read
    only my_team_id off that event, so the order was decoded and then thrown away."""
    order = [str(i) for i in range(1, 13)]
    events = [
        LoggedEvent(
            seq=1,
            league_id="L1",
            event_type=DraftEventType.LEAGUE_SETTINGS,
            data={"league_id": "L1", "team_count": 12, "draft_order": order},
        )
    ]
    assert fold_state(events).draft_order == order


def test_fold_refuses_an_order_that_disagrees_with_team_count() -> None:
    """opponents._my_overall_picks uses len(draft_order) AS the team count, so an 11-entry
    order silently corrupts every 'my next pick'. config/league.json is immutable and fixes
    teams=12: surface the conflict, never adopt it."""
    events = [
        LoggedEvent(
            seq=1,
            league_id="L1",
            event_type=DraftEventType.LEAGUE_SETTINGS,
            data={"league_id": "L1", "team_count": 12, "draft_order": [str(i) for i in range(1, 12)]},
        )
    ]
    assert fold_state(events).draft_order is None


def test_fold_still_never_synthesizes_an_order() -> None:
    """A settings event with a team_count and no order must not mint one."""
    events = [
        LoggedEvent(
            seq=1,
            league_id="L1",
            event_type=DraftEventType.LEAGUE_SETTINGS,
            data={"league_id": "L1", "team_count": 12},
        )
    ]
    assert fold_state(events).draft_order is None


def test_a_later_settings_event_does_not_erase_a_known_order() -> None:
    """CBS attaches fullstatedelta to picks/completed frames, so the settings event repeats
    all draft long -- and the extension's de-dup key for a non-pick event is its whole data
    blob, so a variant without the order does reach the fold."""
    order = [str(i) for i in range(1, 13)]
    events = [
        LoggedEvent(seq=1, league_id="L1", event_type=DraftEventType.LEAGUE_SETTINGS,
                    data={"league_id": "L1", "team_count": 12, "draft_order": order}),
        LoggedEvent(seq=2, league_id="L1", event_type=DraftEventType.LEAGUE_SETTINGS,
                    data={"league_id": "L1", "my_team_id": "7"}),
    ]
    folded = fold_state(events)
    assert folded.draft_order == order
    assert folded.my_team_id == "7"
```

Check the imports already at the top of that file cover `LoggedEvent`, `DraftEventType`,
`fold_state`; `test_fold_never_infers_draft_order` at line 281 already uses them.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_ingest_log.py -k "order" -q`
Expected: `test_fold_binds_the_order_the_room_reported` and
`test_a_later_settings_event_does_not_erase_a_known_order` FAIL with `assert None == ['1', ...]`.
The other two PASS already (they assert today's behaviour, and must keep passing).

- [ ] **Step 3: Implement**

In `backend/src/jaaffl/ingest/log.py`, replace the `LEAGUE_SETTINGS` branch:

```python
        if ev.event_type == DraftEventType.LEAGUE_SETTINGS:
            my_team = ev.data.get("my_team_id")
            if my_team:
                state = state.model_copy(update={"my_team_id": my_team})
            # The REAL entered round-1 order, verbatim from the room
            # (parse.ts::parseDraftOrder <- fullstatedelta.order). Never synthesized, and never
            # ADOPTED when it disagrees with the reported team count: opponents._my_overall_picks
            # uses len(draft_order) AS the team count, so a short order silently corrupts every
            # "my next pick" for the rest of the draft. config/league.json is immutable and its
            # agent_usage_contract says surface a conflict, never apply it.
            order = ev.data.get("draft_order")
            if isinstance(order, list) and order:
                teams = [str(team) for team in order]
                expected = ev.data.get("team_count")
                if expected is not None and int(expected) != len(teams):
                    log.warning(
                        "draft_order_length_conflict",
                        league_id=ev.league_id,
                        reported=len(teams),
                        team_count=int(expected),
                    )
                else:
                    state = state.model_copy(update={"draft_order": teams})
```

- [ ] **Step 4: Run them and watch them pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_ingest_log.py -q`
Expected: PASS, whole file.

- [ ] **Step 5: PROVE THE TESTS CAN FAIL — mutate, component by component**

Copy the file aside first. **Do NOT use `git checkout -- <file>` to undo a mutation** — it
destroys uncommitted work elsewhere.

```bash
cp backend/src/jaaffl/ingest/log.py /tmp/log.py.bak
```

| # | Mutation | The test that MUST fail |
| - | -------- | ----------------------- |
| 1 | delete the whole `order = ...` block | `test_fold_binds_the_order_the_room_reported` |
| 2 | change `int(expected) != len(teams)` to `False` | `test_fold_refuses_an_order_that_disagrees_with_team_count` |
| 3 | move `state.model_copy(update={"draft_order": teams})` outside the `if isinstance(...)` guard so it also runs with `order = None` | `test_a_later_settings_event_does_not_erase_a_known_order` |

Run the file after each; confirm the NAMED test fails and restore with
`cp /tmp/log.py.bak backend/src/jaaffl/ingest/log.py` before the next.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/ingest/log.py backend/tests/test_ingest_log.py
git commit -m "fix(ingest): fold the entered draft order instead of discarding it

parse.ts decoded fullstatedelta.order into a league_settings event (Tier 3's capture work) and
fold_state read only my_team_id off it, so the order the room reported never left the ingest
layer. A wrong-length order is refused rather than adopted: _my_overall_picks uses
len(draft_order) as the team count, so an 11-entry order would corrupt every 'my next pick'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `recommend()` uses the room's order — and says WHICH input was missing

**Files:**

- Modify: `backend/src/jaaffl/engine/recommend.py:172-226`
- Modify: `backend/src/jaaffl/domain/models.py` (the `survival_basis` description only)
- Test: create `backend/tests/test_draft_order_wiring.py`

- [ ] **Step 1: Write the failing test — through the LIVE wiring, not the fixture**

Create `backend/tests/test_draft_order_wiring.py`:

```python
"""TIER 12 — the room's entered order reaches the engine, or the survival model is dead.

Measured 2026-08-10 on the real board: with settings.draft_order None, ZERO of 50 ranked
candidates carry a positive VONA in ANY of the 17 rounds, so `kappa * max(0, VONA)` -- kappa
0.65 in config/engine.json -- contributes exactly nothing to every live pick. Supplying the
order moves the top recommendation in 3 of 17 rounds on an identical board.

Why no test saw it: engine_fixtures.make_context() defaults to
`jaaffl_settings(draft_order=teams(12))`, so every engine test in the suite -- including
Tier 3's own test_my_team_slot.py, via test_api._primed_engine() -- hands the engine an order
the production wiring drops. These tests take their settings from
league.constitution.resolve_league_settings, the function the live service actually calls.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import DraftPick, DraftState, Position
from jaaffl.engine.recommend import recommend
from jaaffl.league.constitution import resolve_league_settings
from tests.engine_fixtures import engine_params, make_context

ORDER = [str(i) for i in range(1, 13)]


def _live_settings():
    """EXACTLY what the live service gives the engine: precompute.py calls this, with no
    snapshot on a fresh room. Its draft_order is None by construction (constitution.py:71)."""
    return resolve_league_settings("cbs-live")


def _board():
    return [
        {"pid": f"rb{i}", "pos": Position.RB, "mu": 300.0 - 5 * i, "adp": float(i + 1),
         "sd": 6.0, "ecr": float(i + 1)}
        for i in range(24)
    ] + [
        {"pid": f"wr{i}", "pos": Position.WR, "mu": 280.0 - 4 * i, "adp": float(25 + i),
         "sd": 6.0, "ecr": float(25 + i)}
        for i in range(24)
    ]


def _state(**over) -> DraftState:
    base = dict(
        league_id="cbs-live",
        current_overall_pick=13,
        my_team_id="7",
        picks=[
            DraftPick(overall=o, round=1, pick_in_round=o, team_id=ORDER[o - 1],
                      player_id=f"rb{o - 1}")
            for o in range(1, 13)
        ],
    )
    base.update(over)
    return DraftState(**base)


class TestTheLiveWiringCanReachMySlot:
    def test_the_constitution_alone_cannot_produce_a_survival_model(self) -> None:
        """Pins the production fact this tier is routing around, so a future change to
        constitution.py cannot make the test below vacuous without failing here first."""
        assert _live_settings().draft_order is None

    def test_the_state_order_gives_the_engine_my_slot(self) -> None:
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        rec = recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50)
        assert rec.survival_basis == "my_slot"

    def test_without_it_the_engine_says_the_ORDER_is_what_is_missing(self) -> None:
        """One string used to cover two different owner actions. The overlay told the owner to
        set a draft slot when the missing input can be the order -- which no setting supplies."""
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        rec = recommend(_state(), ctx, ctx.params, limit=50)
        assert rec.survival_basis == "degraded_no_order"

    def test_a_missing_slot_is_still_reported_as_a_missing_slot(self) -> None:
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        rec = recommend(_state(draft_order=ORDER, my_team_id=None), ctx, ctx.params, limit=50)
        assert rec.survival_basis == "degraded_no_slot"


class TestTheTermItActuallyTurnsOn:
    """survival_basis is a label; VONA is the thing. Tie them together so they cannot drift."""

    @staticmethod
    def _positive_vona(rec) -> int:
        return sum(1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0)

    def test_a_degraded_model_prices_scarcity_at_zero_for_every_candidate(self) -> None:
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        rec = recommend(_state(), ctx, ctx.params, limit=50)
        assert self._positive_vona(rec) == 0

    def test_the_rooms_order_makes_the_scarcity_term_live(self) -> None:
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        rec = recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50)
        assert self._positive_vona(rec) > 0

    def test_the_context_settings_are_not_mutated_by_the_call(self) -> None:
        """DraftContext is cached per league and shared across every pick and every client.
        The override must live for one call only."""
        ctx = make_context(_board(), params=engine_params(), settings=_live_settings())
        recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=5)
        assert ctx.settings.draft_order is None


class TestAContextThatAlreadyKnowsTheOrderStillWorks:
    """A captured-settings future, and every existing test, passes the order on the settings."""

    def test_context_settings_are_used_when_the_state_has_none(self) -> None:
        settings = _live_settings().model_copy(update={"draft_order": ORDER})
        ctx = make_context(_board(), params=engine_params(), settings=settings)
        assert recommend(_state(), ctx, ctx.params, limit=5).survival_basis == "my_slot"

    def test_the_state_wins_when_both_are_present(self) -> None:
        """The room is the authority; a stale precomputed order must not override it."""
        stale = [str(i) for i in range(12, 0, -1)]
        settings = _live_settings().model_copy(update={"draft_order": stale})
        ctx = make_context(_board(), params=engine_params(), settings=settings)
        rec_state = recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50)
        rec_ctx = recommend(_state(), ctx, ctx.params, limit=50)
        assert rec_state.survival_basis == rec_ctx.survival_basis == "my_slot"
        # slot 7 of "1..12" and slot 7 of "12..1" are different seats, so the survival model --
        # and therefore the ranking -- must differ. Equal rankings would mean the state's order
        # was silently ignored.
        assert [p.player_id for p in rec_state.ranked] != [p.player_id for p in rec_ctx.ranked]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_draft_order_wiring.py -q`
Expected: FAIL. `test_the_state_order_gives_the_engine_my_slot` reports
`assert 'degraded_no_slot' == 'my_slot'`; `test_without_it_..._ORDER_...` reports
`assert 'degraded_no_slot' == 'degraded_no_order'`;
`test_the_rooms_order_makes_the_scarcity_term_live` reports `assert 0 > 0`.
`test_the_constitution_alone_cannot_produce_a_survival_model` PASSES (it pins today's fact).

- [ ] **Step 3: Implement — the effective settings, and the two reasons**

In `backend/src/jaaffl/engine/recommend.py`, replace line 173 (`settings = context.settings`) with:

```python
    # The entered round-1 order is decided in person minutes before the draft, while
    # DraftContext is precomputed and cached per league beforehand -- so the ROOM's order
    # arrives on the state, and the state wins. Overlaid for THIS CALL ONLY: the context is a
    # cached object shared across every pick and every connected client.
    settings = context.settings
    if state.draft_order:
        settings = settings.model_copy(update={"draft_order": state.draft_order})
```

Then replace the `survival_basis` initialisation and `_survival` (lines 209-223) with:

```python
    # Whether survival could condition on MY slot at all, and if not, WHICH input was missing.
    # One string used to cover both, and the overlay rendered it as "no draft slot set" -- which
    # told the owner to set JAAFFL_MY_TEAM_ID even when the missing input was the ORDER, which
    # no setting supplies. A degraded model still ranks (on MLV), but every VONA is 0.00 and
    # that is indistinguishable on the wire from a computed 0.00. See Recommendation.survival_basis.
    if not settings.draft_order:
        survival_basis = "degraded_no_order"
    elif state.my_team_id is None or state.my_team_id not in settings.draft_order:
        survival_basis = "degraded_no_slot"
    else:
        survival_basis = "my_slot"

    def _survival(h: int) -> dict[str, float]:
        nonlocal survival_basis
        try:
            taken = pick_probabilities(
                state, settings, available_adp, context.adp_sd, horizon=h, adp_shift=shift
            )
        except ValueError:
            # Belt and braces: the branch above should already have classified this, but
            # _my_overall_picks is the authority on what it can compute.
            taken = {}
            if survival_basis == "my_slot":
                survival_basis = "degraded_no_slot"
        return {pid: 1.0 - taken.get(pid, 0.0) for pid in available}
```

In `backend/src/jaaffl/domain/models.py`, update the `survival_basis` description:

```python
        description="What the survival/VONA model could actually condition on: 'my_slot' when "
        "the entered draft order AND my team are both known; 'degraded_no_order' when the room's "
        "round-1 order has not been read yet (no setting supplies it — it is folded from the "
        "league_settings event, or pasted as an ORDER: line); 'degraded_no_slot' when the order "
        "is known but my own team is not (set JAAFFL_MY_TEAM_ID). In both degraded cases every "
        "player is treated as surviving and VONA collapses toward 0. Stated because a degraded "
        "0.00 is indistinguishable from a computed 0.00 on the wire.",
```

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_draft_order_wiring.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Run every test that touches `survival_basis`, and fix the one that must change**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_my_team_slot.py backend/tests/test_recommend.py backend/tests/test_analytics.py -q`

`test_my_team_slot.py::test_a_recommendation_without_one_admits_the_model_is_degraded` and
`::test_without_the_setting_the_push_says_it_is_degraded` assert the literal
`"degraded_no_slot"`. `_primed_engine()`'s context DOES carry an order (via `make_context`'s
default), so those two are genuinely still `degraded_no_slot` and must keep passing unchanged.
If any test now fails, read it before editing — a real regression and a stale literal look the
same at the assert.

Add to `backend/tests/test_my_team_slot.py`, inside `TestTheSurvivalBasisIsStated`:

```python
    def test_the_degraded_reason_distinguishes_a_missing_order_from_a_missing_slot(
        self, tmp_path: Path
    ) -> None:
        """This class's other tests run against _primed_engine(), whose context carries an
        order from engine_fixtures.make_context's default -- which is exactly why Tier 3's
        regression test passed while the LIVE path could never reach 'my_slot'. The wiring
        version of this assertion lives in test_draft_order_wiring.py."""
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        # order known (fixture), slot unknown -> the slot is the missing input
        assert body["survival_basis"] == "degraded_no_slot"
```

- [ ] **Step 6: PROVE THE TESTS CAN FAIL — mutate**

```bash
cp backend/src/jaaffl/engine/recommend.py /tmp/recommend.py.bak
```

| # | Mutation | The test that MUST fail |
| - | -------- | ----------------------- |
| 1 | delete the `if state.draft_order:` override | `test_the_state_order_gives_the_engine_my_slot`, `test_the_rooms_order_makes_the_scarcity_term_live` |
| 2 | change `settings.model_copy(update=...)` to an in-place `settings.draft_order = state.draft_order` (pydantic allows it on a non-frozen model) | `test_the_context_settings_are_not_mutated_by_the_call` |
| 3 | swap the precedence: prefer `context.settings.draft_order` when both are set | `test_the_state_wins_when_both_are_present` |
| 4 | collapse `degraded_no_order` back to `degraded_no_slot` | `test_without_it_the_engine_says_the_ORDER_is_what_is_missing` |

⚠️ For mutation 1, confirm the failure message is about `survival_basis`/VONA — **not** an
`AttributeError` or `NameError`. A test that fails because the module stopped importing has not
demonstrated it can detect this defect. Restore with `cp /tmp/recommend.py.bak ...` between each.

- [ ] **Step 7: Commit**

```bash
git add backend/src/jaaffl/engine/recommend.py backend/src/jaaffl/domain/models.py backend/tests/test_draft_order_wiring.py backend/tests/test_my_team_slot.py
git commit -m "fix(engine): the room's entered order reaches recommend(), and the degraded reason names the missing input

survival_basis was 'degraded_no_slot' on 100% of live recommendations -- including with
?team_id= supplied -- because resolve_league_settings returns draft_order=None by construction
and nothing else ever set it. Measured on the real board: 0 of 50 ranked candidates carried a
positive VONA in any of the 17 rounds, so kappa*max(0,VONA) contributed exactly nothing to
every live pick; with the order supplied the top recommendation moves in 3 of 17 rounds on an
identical board.

The overlay told the owner to set a draft slot, which could not fix it. survival_basis now
distinguishes degraded_no_order from degraded_no_slot.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: the dashboard's analytics reads the same order

**Files:**

- Modify: `backend/src/jaaffl/engine/analytics.py` (inside `build_analytics`)
- Test: `backend/tests/test_analytics.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analytics.py`:

```python
def test_markers_read_the_order_the_room_reported_not_just_the_settings() -> None:
    """analytics._total_picks is `rounds * len(settings.draft_order or [])`, i.e. ZERO on the
    live path, so the dashboard's pick markers were dead for the same reason the overlay's
    VONA was. Same seam, same fix."""
    context = make_context(_specs(), settings=jaaffl_settings(draft_order=None))
    state = DraftState(
        league_id="cbs-test",
        current_overall_pick=13,
        my_team_id="t0",
        draft_order=teams(12),
    )
    analytics = build_analytics(context, state)
    assert analytics.survival_curves.markers, "no markers: the state's order was ignored"
```

Match the existing imports and helper names in that file (`_specs`, `jaaffl_settings`, `teams`,
`build_analytics`) — `test_markers_come_from_the_real_entered_draft_order` at line 168 shows the
shape, including the exact attribute path for the markers. Use that same attribute path here.

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_analytics.py -k markers_read_the_order -q`
Expected: FAIL — `no markers: the state's order was ignored`.

- [ ] **Step 3: Implement**

At the top of `build_analytics` in `backend/src/jaaffl/engine/analytics.py`, before any use of
`context.settings`, add:

```python
    # Same seam as recommend(): the entered order arrives on the STATE (the cached context was
    # built before the draft). Overlaid for this call only -- never written back to the context.
    settings = context.settings
    if state.draft_order:
        settings = settings.model_copy(update={"draft_order": state.draft_order})
```

Then replace every `context.settings` reference **inside `build_analytics` and the helpers it
calls with a settings argument** with this local `settings`. Read the function body before
editing: if a helper takes `context` rather than `settings`, pass `settings` explicitly rather
than reaching through `context` again.

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_analytics.py -q`
Expected: PASS, whole file — including
`test_value_curves_do_not_require_a_draft_order` and
`test_survival_degrades_when_draft_order_is_unknown`, which must be unaffected.

- [ ] **Step 5: PROVE IT CAN FAIL**

```bash
cp backend/src/jaaffl/engine/analytics.py /tmp/analytics.py.bak
```

Delete the `if state.draft_order:` override. Run the file.
Expected: `test_markers_read_the_order_the_room_reported_not_just_the_settings` FAILS and
`test_survival_degrades_when_draft_order_is_unknown` still PASSES.
Restore: `cp /tmp/analytics.py.bak backend/src/jaaffl/engine/analytics.py`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/jaaffl/engine/analytics.py backend/tests/test_analytics.py
git commit -m "fix(analytics): pick markers read the room's order too

_total_picks is rounds * len(settings.draft_order or []), which is 0 on the live path, so the
dashboard's survival markers were as dead as the overlay's VONA and for the same reason.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: the manual-paste `ORDER:` line gets the length guard the network path already has

**Files:**

- Modify: `apps/extension/src/lib/parse.ts:497-511`
- Test: `apps/extension/tests/manual-paste.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `apps/extension/tests/manual-paste.test.ts`:

```ts
describe("the ORDER: line is length-guarded like the network path", () => {
  it("accepts exactly twelve teams", () => {
    const { events, skipped } = parsePastedReport("ORDER: 1,2,3,4,5,6,7,8,9,10,11,12");
    expect(skipped).toEqual([]);
    const order = events.find((e) => e.event_type === "league_settings");
    expect((order?.data as Record<string, unknown>)["draft_order"]).toHaveLength(12);
  });

  it("REPORTS a short order instead of emitting it", () => {
    // opponents._my_overall_picks uses len(draft_order) AS the team count, so an 11-name
    // paste would silently give every "my next pick" the wrong number for the whole draft.
    // parseDraftOrder guards the network path at exactly 12; this is the same guard.
    const line = "ORDER: 1,2,3,4,5,6,7,8,9,10,11";
    const { events, skipped } = parsePastedReport(line);
    expect(events.filter((e) => e.event_type === "league_settings")).toEqual([]);
    expect(skipped).toEqual([line]);
  });

  it("REPORTS a long order instead of emitting it", () => {
    const line = "ORDER: 1,2,3,4,5,6,7,8,9,10,11,12,13";
    const { events, skipped } = parsePastedReport(line);
    expect(events.filter((e) => e.event_type === "league_settings")).toEqual([]);
    expect(skipped).toEqual([line]);
  });
});
```

- [ ] **Step 2: Run them and watch two fail**

Run: `pnpm --filter @jaaffl/extension test -- -t "length-guarded"`
Expected: the "accepts exactly twelve" case PASSES; both REPORTS cases FAIL — today a short or
long order is emitted and `skipped` is empty.

- [ ] **Step 3: Implement**

In `apps/extension/src/lib/parse.ts`, inside `parsePastedReport`, replace the ORDER branch:

```ts
    const order = line.match(ORDER_LINE);
    if (order?.[1]) {
      const teams = order[1].split(/[,\s]+/).filter(Boolean);
      // Same guard, same reason, as parseDraftOrder on the network path: opponents.py's snake
      // math uses len(draft_order) AS the team count, so ANY other length silently corrupts
      // every "my next pick" for the rest of the draft. Reported, never dropped silently --
      // a partial parse announced as success is how the owner loses a player.
      if (teams.length === IMMUTABLE_TEAM_COUNT) {
        events.push(orderEvent("manual", "paste", teams));
      } else {
        skipped.push(line);
      }
      continue;
    }
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pnpm --filter @jaaffl/extension test`
Expected: PASS, whole package.

- [ ] **Step 5: PROVE IT CAN FAIL**

```bash
cp apps/extension/src/lib/parse.ts /tmp/parse.ts.bak
```

Change `teams.length === IMMUTABLE_TEAM_COUNT` to `teams.length > 0`. Run.
Expected: both REPORTS tests FAIL; the accepts-twelve test still PASSES.
Restore: `cp /tmp/parse.ts.bak apps/extension/src/lib/parse.ts`.

- [ ] **Step 6: Commit**

```bash
git add apps/extension/src/lib/parse.ts apps/extension/tests/manual-paste.test.ts
git commit -m "fix(extension): length-guard the manual-paste ORDER: line

parseDraftOrder guards the network path at exactly 12 and its comment explains why --
_my_overall_picks uses len(draft_order) as the team count. parsePastedReport accepted any
length, so an 11-name paste on the guaranteed draft-day fallback would have silently given
every 'my next pick' the wrong number.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: the overlay tells the owner which input is missing

**Files:**

- Modify: `apps/extension/src/overlay/overlay.ts:400-418`
- Test: `apps/extension/tests/overlay.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to the degraded-mode `describe` block in `apps/extension/tests/overlay.test.ts` (the one
containing the existing `is-degraded` assertions around line 272):

```ts
  it("names the ORDER when that is the missing input", () => {
    const { handle, foot, sync } = mountForTest();
    handle.update({ ...REC, survival_basis: "degraded_no_order" });
    expect(foot().textContent).toContain("VONA degraded · draft order not read yet");
    expect(sync.classList.contains("is-degraded")).toBe(true);
  });

  it("still names the SLOT when that is the missing input", () => {
    const { handle, foot, sync } = mountForTest();
    handle.update({ ...REC, survival_basis: "degraded_no_slot" });
    expect(foot().textContent).toContain("VONA degraded · no draft slot set");
    expect(sync.classList.contains("is-degraded")).toBe(true);
  });

  it("does not accuse an unknown basis of being degraded", () => {
    const { handle, sync } = mountForTest();
    handle.update({ ...REC, survival_basis: "my_slot" });
    expect(sync.classList.contains("is-degraded")).toBe(false);
  });
```

Reuse the exact mount/query helpers that file already uses for the existing degraded tests
(`foot()`, `sync`) rather than inventing new ones — read lines 260-300 and match them.

- [ ] **Step 2: Run them and watch one fail**

Run: `pnpm --filter @jaaffl/extension test -- -t "missing input"`
Expected: `names the ORDER` FAILS — today `degraded_no_order` matches neither branch, so no chip
renders and `is-degraded` is false.

- [ ] **Step 3: Implement**

In `apps/extension/src/overlay/overlay.ts`, replace the degraded block in `renderSync`:

```ts
    // No CBS frame names the viewer's own team, and the entered round-1 order is only known
    // once the room reports it — so a degraded VONA has TWO possible causes with two different
    // owner actions, and saying "no draft slot set" for both told the owner to set
    // JAAFFL_MY_TEAM_ID when what was missing was the order. Only ever shown when the backend
    // actually SAID so — an older payload that omits survival_basis is not accused.
    const degradedReason =
      survivalBasis === "degraded_no_order"
        ? "VONA degraded · draft order not read yet"
        : survivalBasis === "degraded_no_slot"
          ? "VONA degraded · no draft slot set"
          : null;
    if (degradedReason) parts.push(degradedReason);
    footSync.textContent = parts.join(" · ");
    footSync.classList.toggle("is-stale", ageMs >= STALE_AFTER_MS);
    footSync.classList.toggle("is-degraded", degradedReason !== null);
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pnpm --filter @jaaffl/extension test`
Expected: PASS, whole package (the pre-existing degraded tests included).

- [ ] **Step 5: PROVE IT CAN FAIL**

```bash
cp apps/extension/src/overlay/overlay.ts /tmp/overlay.ts.bak
```

Change the ternary so `degraded_no_order` also yields `"VONA degraded · no draft slot set"`.
Expected: `names the ORDER` FAILS; `still names the SLOT` PASSES.
Restore: `cp /tmp/overlay.ts.bak apps/extension/src/overlay/overlay.ts`.

- [ ] **Step 6: Commit**

```bash
git add apps/extension/src/overlay/overlay.ts apps/extension/tests/overlay.test.ts
git commit -m "fix(overlay): say which input the degraded VONA is missing

'no draft slot set' was shown for both causes, so it told the owner to set JAAFFL_MY_TEAM_ID
even when the missing input was the room's entered order -- which no setting supplies.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: the rehearsal log — evidence, off by default

**Files:**

- Create: `backend/src/jaaffl/api/rehearsal.py`
- Modify: `backend/src/jaaffl/config.py`
- Modify: `backend/src/jaaffl/api/app.py`
- Test: create `backend/tests/test_rehearsal_log.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_rehearsal_log.py`:

```python
"""TIER 12 — the rehearsal must produce EVIDENCE, not impressions.

One JSONL line per recommendation actually served, from BOTH the push and pull paths, so a
single CBS mock answers: was survival live, how long did each recompute take against the
<200ms budget, was every drafted player masked, did every cbs: id resolve.

OFF unless JAAFFL_REHEARSAL_LOG is set, and fail-soft when on: draft night must not acquire a
new failure mode in exchange for a log.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from jaaffl.api import create_app
from jaaffl.config import Settings
from tests.test_api import _primed_engine, pick_payload


def _app(tmp_path: Path, **over):
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            **over,
        ),
        rec_engine=_primed_engine(),
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestItIsOffByDefault:
    def test_no_file_is_written_when_the_setting_is_unset(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert list((tmp_path).rglob("*.jsonl")) == []


class TestItRecordsWhatTheRehearsalNeeds:
    def test_the_push_path_writes_a_line_per_recommendation(self, tmp_path: Path) -> None:
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        rows = _lines(out)
        assert len(rows) == 1
        assert rows[0]["path"] == "push"

    def test_the_pull_path_writes_one_too_and_says_so(self, tmp_path: Path) -> None:
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert [r["path"] for r in _lines(out)] == ["push", "pull"]

    def test_every_field_the_report_reads_is_present(self, tmp_path: Path) -> None:
        """Pins the contract between the sink and scripts/rehearsal_report.py, so a field
        rename cannot silently blank a column of the evidence table."""
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1))
        row = _lines(out)[0]
        assert set(row) >= {
            "ts", "path", "league_id", "overall", "survival_basis", "vona_method",
            "recompute_ms", "draft_order_len", "my_team_id", "ranked_n", "positive_vona_n",
            "picks_total", "picks_masked", "picks_unresolved", "unresolved_ids", "top",
        }
        assert set(row["top"]) >= {"player_id", "name", "vona", "mlv", "projected_points"}

    def test_it_counts_the_picks_the_engine_actually_masked(self, tmp_path: Path) -> None:
        """The question a rehearsal has to answer: did a drafted player stay on my board?
        picks_masked counts resolved picks whose id is a real candidate; unresolved_ids names
        the ones that are NOT masked and therefore can be recommended again."""
        out = tmp_path / "rehearsal.jsonl"
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=out))
        client.post("/draft/events", json=pick_payload(1, player_id="rb0"))
        client.post("/draft/events", json=pick_payload(2, player_id="cbs:9999999"))
        row = _lines(out)[-1]
        assert row["picks_total"] == 2
        assert row["picks_masked"] == 1
        assert row["picks_unresolved"] == 1
        assert row["unresolved_ids"] == ["cbs:9999999"]


class TestItNeverBreaksTheHotPath:
    def test_an_unwritable_path_does_not_fail_the_recommendation(self, tmp_path: Path) -> None:
        """A directory where a file should be: open() raises. Draft night must not acquire a
        new failure mode in exchange for a log."""
        bad = tmp_path / "not-a-file.jsonl"
        bad.mkdir(parents=True)
        client = TestClient(_app(tmp_path, jaaffl_rehearsal_log=bad))
        client.post("/draft/events", json=pick_payload(1))
        res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"})
        assert res.status_code == 200
```

Read `backend/tests/test_api.py`'s `pick_payload` before writing these — if it does not already
accept a `player_id` keyword, add one there with a `None` default so the existing callers are
unaffected, and note that edit in this task's commit.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_rehearsal_log.py -q`
Expected: FAIL — `Settings` has no `jaaffl_rehearsal_log` (pydantic-settings raises on the
unknown kwarg). `TestItIsOffByDefault` PASSES.

- [ ] **Step 3: Add the setting**

In `backend/src/jaaffl/config.py`, after `jaaffl_recordings_dir`:

```python
    # TIER 12 rehearsal evidence sink. UNSET = off, and off is the draft-night default: a
    # rehearsal is worth a log line per pick, a real draft is not worth a new failure mode.
    # When set, one JSONL line per recommendation actually served (push AND pull), fail-soft.
    # Read by scripts/rehearsal_report.py.
    jaaffl_rehearsal_log: Path | None = None
```

- [ ] **Step 4: Write the sink**

Create `backend/src/jaaffl/api/rehearsal.py`:

```python
"""TIER 12 rehearsal evidence sink.

A CBS mock draft is a one-shot, unrepeatable event on someone else's clock. Watching the
overlay during one yields impressions; this yields a file. One JSONL line per recommendation
actually served, from both the push (/recs/ws) and pull (GET /recommendation) paths, carrying
exactly the fields scripts/rehearsal_report.py turns into a pass/fail table.

OFF unless ``jaaffl_rehearsal_log`` is set, and fail-soft when on — a recommendation must never
fail because a log line could not be written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from jaaffl.domain import DraftState, Recommendation
from jaaffl.engine.context import DraftContext

log = structlog.get_logger(__name__)


class RehearsalLog:
    """Append-only evidence sink. ``path=None`` makes every call a no-op."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def record(
        self,
        path_label: str,
        state: DraftState,
        rec: Recommendation,
        context: DraftContext | None,
    ) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(self._row(path_label, state, rec, context)) + "\n")
        except Exception:  # noqa: BLE001 - fail-soft is the whole point; see the module docstring
            log.warning("rehearsal_log_write_failed", path=str(self._path), exc_info=True)

    @staticmethod
    def _row(
        path_label: str,
        state: DraftState,
        rec: Recommendation,
        context: DraftContext | None,
    ) -> dict:
        board = context.mu if context is not None else {}
        # A pick is MASKED only when its id is a real candidate id -- an unresolved name-only
        # pick (player_id None) or an unresolved "cbs:<id>" one is still on the owner's board
        # and can be recommended again. That is the correctness question a rehearsal must answer.
        masked = [p for p in state.picks if p.player_id and p.player_id in board]
        unresolved = [
            p.player_id or f"<name-only overall {p.overall}>"
            for p in state.picks
            if not p.player_id or p.player_id not in board
        ]
        top = rec.ranked[0] if rec.ranked else None
        return {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "path": path_label,
            "league_id": rec.league_id,
            "overall": rec.as_of_overall_pick,
            "survival_basis": rec.survival_basis,
            "vona_method": rec.vona_method,
            "recompute_ms": rec.recompute_ms,
            "draft_order_len": len(state.draft_order) if state.draft_order else 0,
            "my_team_id": state.my_team_id,
            "ranked_n": len(rec.ranked),
            "positive_vona_n": sum(
                1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0
            ),
            "picks_total": len(state.picks),
            "picks_masked": len(masked),
            "picks_unresolved": len(unresolved),
            "unresolved_ids": unresolved,
            "roster_filled": rec.roster_filled,
            "top": {
                "player_id": top.player_id if top else None,
                "name": top.name if top else None,
                "vona": (top.components.vona if top and top.components else None),
                "mlv": (top.components.mlv if top and top.components else None),
                "projected_points": top.projected_points if top else None,
            },
        }
```

Before writing `_row`, open `backend/src/jaaffl/domain/models.py` and confirm the exact attribute
names on `RecommendedPick` and `ScoreComponents` (`projected_points`, `components.mlv`,
`components.vona`) — the live pull in the Why section above shows all three, but read them.

- [ ] **Step 5: Wire both call sites**

In `backend/src/jaaffl/api/app.py`, add the import and build the sink beside the other app state:

```python
from jaaffl.api.rehearsal import RehearsalLog
```

```python
    app.state.rehearsal = RehearsalLog(settings.jaaffl_rehearsal_log)
```

In `publish_recommendation`, after `app.state.rec_history.setdefault(...).append(recommendation)`:

```python
            app.state.rehearsal.record(
                "push", state, recommendation, app.state.rec_engine.context_for(event.league_id)
            )
```

In the `/recommendation` handler, after the `include_components` block and before `return rec`:

```python
        app.state.rehearsal.record(
            "pull", state, rec, app.state.rec_engine.context_for(league_id)
        )
```

⚠️ Record the recommendation the engine produced, not the `include_components=False` copy — the
`positive_vona_n` column reads `components`, and a stripped payload would silently report 0.
Place the `pull` call **before** the `include_components` re-copy, or record the pre-copy object.

- [ ] **Step 6: Run them and watch them pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_rehearsal_log.py -q`
Expected: PASS (7 passed).

- [ ] **Step 7: PROVE THE TESTS CAN FAIL**

```bash
cp backend/src/jaaffl/api/rehearsal.py /tmp/rehearsal.py.bak
```

| # | Mutation | The test that MUST fail |
| - | -------- | ----------------------- |
| 1 | make `record` return immediately, always | `test_the_push_path_writes_a_line_per_recommendation` |
| 2 | count `masked` as `len(state.picks)` | `test_it_counts_the_picks_the_engine_actually_masked` |
| 3 | replace the `except Exception` with `except OSError` and raise a `TypeError` in `_row` | `test_an_unwritable_path_does_not_fail_the_recommendation` |
| 4 | drop `"top"` from the row | `test_every_field_the_report_reads_is_present` |

⚠️ Mutation 3 exists because "fail-soft" is exactly the kind of claim that passes against a
narrower `except` than the code needs — verify the test fails with a `TypeError` escaping, not
with a write error. Restore between each.

- [ ] **Step 8: Commit**

```bash
git add backend/src/jaaffl/api/rehearsal.py backend/src/jaaffl/api/app.py backend/src/jaaffl/config.py backend/tests/test_rehearsal_log.py backend/tests/test_api.py
git commit -m "feat(api): rehearsal evidence sink, off unless JAAFFL_REHEARSAL_LOG is set

A CBS mock is one-shot and on someone else's clock, so watching the overlay yields impressions.
One JSONL line per recommendation served -- push and pull -- carrying survival_basis,
vona_method, recompute_ms, masking counts and the unresolved ids. Fail-soft: draft night does
not acquire a new failure mode in exchange for a log.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: `scripts/rehearsal_report.py` — the evidence table

**Files:**

- Create: `scripts/rehearsal_report.py`
- Test: create `backend/tests/test_rehearsal_report.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rehearsal_report.py`:

```python
"""The report is the deliverable of the rehearsal, so its verdicts are tested like code."""

from __future__ import annotations

import json
from pathlib import Path

from rehearsal_report import Verdict, evaluate


def _row(**over) -> dict:
    row = {
        "ts": "2026-08-10T12:00:00.000+00:00", "path": "push", "league_id": "cbs-live",
        "overall": 7, "survival_basis": "my_slot", "vona_method": "analytic",
        "recompute_ms": 8.0, "draft_order_len": 12, "my_team_id": "7", "ranked_n": 50,
        "positive_vona_n": 11, "picks_total": 6, "picks_masked": 6, "picks_unresolved": 0,
        "unresolved_ids": [], "roster_filled": 0,
        "top": {"player_id": "gsis:x", "name": "X", "vona": 3.0, "mlv": 40.0,
                "projected_points": 250.0},
    }
    row.update(over)
    return row


def test_a_clean_rehearsal_passes_every_check() -> None:
    report = evaluate([_row(), _row(overall=19)])
    assert all(v.passed for v in report), [v.name for v in report if not v.passed]


def test_a_degraded_survival_basis_fails_loudly() -> None:
    report = evaluate([_row(), _row(survival_basis="degraded_no_order", positive_vona_n=0)])
    failed = {v.name for v in report if not v.passed}
    assert "survival is live" in failed


def test_a_recompute_over_the_budget_fails() -> None:
    report = evaluate([_row(), _row(recompute_ms=250.0)])
    assert "recompute under 200ms" in {v.name for v in report if not v.passed}


def test_an_unmasked_drafted_player_fails_and_is_named() -> None:
    report = evaluate([_row(picks_masked=5, picks_unresolved=1, unresolved_ids=["cbs:404"])])
    bad = next(v for v in report if v.name == "every drafted player masked")
    assert not bad.passed
    assert "cbs:404" in bad.detail


def test_an_empty_log_is_a_failure_not_a_pass() -> None:
    """A rehearsal that recorded nothing must never read as a clean run."""
    report = evaluate([])
    assert not any(v.passed for v in report)
```

The `from rehearsal_report import ...` line requires `scripts/` on `sys.path`. Check
`backend/pyproject.toml` / `backend/tests/conftest.py` for how existing script tests do it
(`test_redact_fixtures.py` imports `scripts/redact_cbs_fixtures.py` — copy that mechanism
exactly rather than inventing one).

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_rehearsal_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rehearsal_report'`.

- [ ] **Step 3: Write the script**

Create `scripts/rehearsal_report.py`:

```python
#!/usr/bin/env python
"""Turn a Tier-12 rehearsal log into an evidence table with a verdict per criterion.

Reads the JSONL that backend/src/jaaffl/api/rehearsal.py wrote during ONE CBS mock draft and
answers, with numbers rather than impressions: was the survival model live, did every recompute
meet the <200ms budget, was every drafted player masked off the board, did every cbs: id
resolve, and what did the overlay's foot say.

n = 1. One mock, one seat, CBS's bots. Every verdict below is about that one run.

Usage (from the repo root, via the backend venv)::

    .venv/Scripts/python.exe scripts/rehearsal_report.py data/rehearsal/mock-1.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

LATENCY_BUDGET_MS = 200.0


@dataclass(frozen=True)
class Verdict:
    name: str
    passed: bool
    detail: str


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def evaluate(rows: list[dict]) -> list[Verdict]:
    """Every criterion the rehearsal protocol claims to test, as a pass/fail with its numbers.

    An EMPTY log fails every check rather than passing them vacuously -- a rehearsal that
    recorded nothing is the one outcome that must never read as clean.
    """
    if not rows:
        return [
            Verdict(name, False, "no rows: the rehearsal log is empty")
            for name in (
                "recommendations served", "survival is live", "the order was read from the room",
                "recompute under 200ms", "every drafted player masked", "vona_method stated",
                "the scarcity term is live",
            )
        ]

    bases = {r.get("survival_basis") for r in rows}
    orders = {r.get("draft_order_len", 0) for r in rows}
    latencies = [float(r["recompute_ms"]) for r in rows if r.get("recompute_ms") is not None]
    unresolved = sorted({i for r in rows for i in r.get("unresolved_ids", [])})
    methods = {r.get("vona_method") for r in rows}
    live_rows = [r for r in rows if r.get("survival_basis") == "my_slot"]
    positive = [r.get("positive_vona_n", 0) for r in live_rows]

    return [
        Verdict("recommendations served", True, f"{len(rows)} rows "
                f"({sum(1 for r in rows if r['path'] == 'push')} push / "
                f"{sum(1 for r in rows if r['path'] == 'pull')} pull)"),
        Verdict("survival is live", bases == {"my_slot"},
                f"survival_basis values seen: {sorted(b or 'null' for b in bases)}"),
        Verdict("the order was read from the room", orders == {12},
                f"draft_order_len values seen: {sorted(orders)}"),
        Verdict("recompute under 200ms", bool(latencies) and max(latencies) < LATENCY_BUDGET_MS,
                f"n={len(latencies)} median={statistics.median(latencies):.1f}ms "
                f"p95={_pct(latencies, 0.95):.1f}ms max={max(latencies):.1f}ms "
                f"budget={LATENCY_BUDGET_MS:.0f}ms" if latencies else "no timings recorded"),
        Verdict("every drafted player masked", not unresolved,
                f"unresolved (still on the board, can be recommended again): {unresolved}"
                if unresolved else
                f"{max(r['picks_masked'] for r in rows)} of "
                f"{max(r['picks_total'] for r in rows)} picks masked"),
        Verdict("vona_method stated", methods == {"analytic"},
                f"vona_method values seen: {sorted(m or 'null' for m in methods)}"),
        Verdict("the scarcity term is live", bool(positive) and min(positive) > 0,
                f"candidates with vona>0 across {len(live_rows)} live recomputes: "
                f"min={min(positive)} max={max(positive)}" if positive else
                "no recompute ever had a live survival model"),
    ]


def _overlay_foot(row: dict) -> str:
    """What the overlay's foot rendered for this row.

    DERIVED, not observed -- the backend cannot see the DOM. The chip is a pure function of
    survival_basis (apps/extension/src/overlay/overlay.ts::renderSync, pinned by
    apps/extension/tests/overlay.test.ts), so this reproduces that one rule and nothing else.
    The owner's screenshot is the ground-truth cross-check.
    """
    chip = {
        "degraded_no_order": " · VONA degraded · draft order not read yet",
        "degraded_no_slot": " · VONA degraded · no draft slot set",
    }.get(row.get("survival_basis") or "", "")
    return f"recompute {round(row.get('recompute_ms') or 0)}ms{chip}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("log", type=Path, help="The JSONL written by JAAFFL_REHEARSAL_LOG.")
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"[rehearsal] no log at {args.log}", file=sys.stderr)
        return 1
    rows = [json.loads(line) for line in args.log.read_text(encoding="utf-8").splitlines() if line]

    print(f"[rehearsal] {args.log}  ({len(rows)} recommendations)   n = 1 — ONE mock draft\n")
    print(f"{'rnd':>4} {'ovr':>4} {'path':>5} {'basis':>18} {'ms':>7} {'vona>0':>7} "
          f"{'masked':>10}  top")
    for row in rows:
        overall = row.get("overall") or 0
        print(f"{(overall - 1) // 12 + 1:>4} {overall:>4} {row['path']:>5} "
              f"{str(row.get('survival_basis')):>18} {row.get('recompute_ms') or 0:>7.1f} "
              f"{row.get('positive_vona_n', 0):>7} "
              f"{row.get('picks_masked', 0):>4}/{row.get('picks_total', 0):<5} "
              f"{(row.get('top') or {}).get('name')}")

    print("\n[rehearsal] verdicts")
    report = evaluate(rows)
    for verdict in report:
        print(f"  {'PASS' if verdict.passed else 'FAIL'}  {verdict.name:<32} {verdict.detail}")

    if rows:
        print(f"\n[rehearsal] overlay foot, derived from the last row: {_overlay_foot(rows[-1])}")
    failures = [v.name for v in report if not v.passed]
    print(f"\n[rehearsal] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_rehearsal_report.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: PROVE IT CAN FAIL**

```bash
cp scripts/rehearsal_report.py /tmp/rehearsal_report.py.bak
```

| # | Mutation | The test that MUST fail |
| - | -------- | ----------------------- |
| 1 | change the empty-log branch to `return []` | `test_an_empty_log_is_a_failure_not_a_pass` |
| 2 | change `bases == {"my_slot"}` to `"my_slot" in bases` | `test_a_degraded_survival_basis_fails_loudly` |
| 3 | change `max(latencies)` to `statistics.median(latencies)` | `test_a_recompute_over_the_budget_fails` |

⚠️ Mutation 1's failure must be an assertion about verdicts, not an `IndexError` from
`next(...)` finding nothing. Restore between each.

- [ ] **Step 6: Commit**

```bash
git add scripts/rehearsal_report.py backend/tests/test_rehearsal_report.py
git commit -m "feat(scripts): rehearsal_report turns the evidence log into pass/fail verdicts

An empty log fails every check rather than passing them vacuously -- a rehearsal that recorded
nothing is the one outcome that must never read as a clean run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: preflight becomes the gate that would have caught this

**Files:**

- Modify: `scripts/preflight.py`
- Test: `backend/tests/test_coverage.py` (or a new `backend/tests/test_preflight_gate.py` if that
  file has no script-import mechanism — check first)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_preflight_gate.py`:

```python
"""TIER 12 — preflight now answers the question that decided this tier.

scripts/preflight.py checked that every startable position was fillable and that the tier-cliff
term was alive. It never asked whether the engine could compute a survival model AT ALL, which
is why 'survival_basis is degraded on 100% of live recommendations' survived eleven tiers.

The probe order is a PROBE, labelled as one. config/league.json forbids inferring the real
order from team count and preflight runs hours before that order exists.
"""

from __future__ import annotations

from preflight import survival_probe
from tests.engine_fixtures import engine_params, make_context, jaaffl_settings
from jaaffl.domain import Position


def _ctx(order):
    specs = [
        {"pid": f"rb{i}", "pos": Position.RB, "mu": 300.0 - 5 * i, "adp": float(i + 1),
         "sd": 6.0, "ecr": float(i + 1)}
        for i in range(24)
    ]
    return make_context(specs, params=engine_params(),
                        settings=jaaffl_settings(draft_order=order))


def test_the_probe_reports_a_live_survival_model() -> None:
    basis, positive = survival_probe(_ctx(None), my_team_id="7")
    assert basis == "my_slot"
    assert positive > 0


def test_the_probe_fails_when_the_slot_is_unset() -> None:
    basis, positive = survival_probe(_ctx(None), my_team_id=None)
    assert basis != "my_slot"
    assert positive == 0


def test_the_probe_fails_when_the_slot_is_not_a_team_in_the_room() -> None:
    basis, positive = survival_probe(_ctx(None), my_team_id="99")
    assert basis == "degraded_no_slot"
    assert positive == 0
```

Use the same script-import mechanism `test_redact_fixtures.py` uses.

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_preflight_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'survival_probe'`.

- [ ] **Step 3: Implement**

In `scripts/preflight.py`, add the imports and the function above `main`:

```python
from jaaffl.domain import DraftPick, DraftState
from jaaffl.engine.recommend import recommend

# A PROBE order, never an inference of the real one. config/league.json fixes teams=12 and
# records that the real order is decided in person and entered into CBS; preflight runs hours
# before that exists. Its only job is to prove the WIRING can produce a survival model, which
# is what nothing checked until Tier 12.
_PROBE_ORDER = [str(i) for i in range(1, 13)]


def survival_probe(context, *, my_team_id: str | None) -> tuple[str | None, int]:
    """Ask the real recommend() whether a survival model is reachable at all.

    Returns ``(survival_basis, candidates_with_positive_vona)``. `kappa * max(0, VONA)` is the
    engine's whole scarcity term; measured 2026-08-10, with no order reaching the engine it was
    exactly 0.00 for every candidate in every one of 17 rounds while the response looked healthy.
    """
    state = DraftState(
        league_id="preflight",
        current_overall_pick=13,
        my_team_id=my_team_id,
        draft_order=_PROBE_ORDER,
        picks=[
            DraftPick(overall=o, round=1, pick_in_round=o, team_id=_PROBE_ORDER[o - 1])
            for o in range(1, 13)
        ],
    )
    rec = recommend(state, context, context.params, limit=50)
    positive = sum(1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0)
    return rec.survival_basis, positive
```

Then add the fourth guard in `main`, after the bye-week block and before the final OK line:

```python
    # Fourth guard (TIER 12): can the engine compute a survival model at all? Everything above
    # checks the BOARD; this checks the WIRING, on the real recommend(). It fails hard because
    # -- like the missing kickers -- a dead scarcity term is invisible in a healthy-looking
    # response, and the morning of the draft is when there is still time to fix it.
    my_team_id = get_settings().jaaffl_my_team_id
    basis, positive = survival_probe(context, my_team_id=my_team_id)
    print(
        f"[preflight] survival probe (PROBE order, not the real one): basis={basis} "
        f"candidates with vona>0: {positive}"
    )
    if basis != "my_slot" or positive == 0:
        print(
            f"[preflight] FAIL: the engine cannot compute a survival model "
            f"(JAAFFL_MY_TEAM_ID={my_team_id!r}).",
            file=sys.stderr,
        )
        print(
            "[preflight] set JAAFFL_MY_TEAM_ID in .env to your CBS team number ('1'..'12')."
            " Without a survival model every VONA is 0.00 and the engine ranks on MLV alone —"
            " a healthy-looking response carrying a dead scarcity term.",
            file=sys.stderr,
        )
        return 1
```

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_preflight_gate.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the real preflight and record BOTH outcomes**

```bash
.venv\Scripts\python.exe scripts\preflight.py
```

Expected **exit 1** today: `.env` has `JAAFFL_MY_TEAM_ID=` (empty, verified 2026-08-10), so the
new guard trips. **That is the correct result and it is the point of the guard.** Record the
exact output for the ROADMAP block.

Then confirm it passes once the slot is set (temporary, do NOT commit `.env`):

```bash
JAAFFL_MY_TEAM_ID=7 .venv/Scripts/python.exe scripts/preflight.py; echo "exit=$?"
```

Expected: `exit=0`, with the survival-probe line reporting `basis=my_slot` and a positive count.

- [ ] **Step 6: PROVE IT CAN FAIL**

```bash
cp scripts/preflight.py /tmp/preflight.py.bak
```

Change `if basis != "my_slot" or positive == 0:` to `if False:`. Re-run
`.venv\Scripts\python.exe -m pytest backend/tests/test_preflight_gate.py -q` — the unit tests
still pass (they test `survival_probe`, not the gate), so **also** re-run the real script with an
empty slot and confirm it now wrongly exits 0. Restore.

⚠️ Note this asymmetry in the plan record: the unit tests cover the probe, the manual run covers
the gate. If that gap matters, add an `evaluate`-style seam; this plan does not, and says so.

- [ ] **Step 7: Commit**

```bash
git add scripts/preflight.py backend/tests/test_preflight_gate.py
git commit -m "feat(preflight): fail if the engine cannot compute a survival model

Preflight checked the BOARD (every startable position fillable, the tier-cliff term alive) and
never the WIRING. A survival model that degrades to 'everyone is available' produces a
completely healthy-looking recommendation whose scarcity term is exactly 0.00 -- which is how
it survived eleven tiers. The probe order is a probe, labelled as one; config/league.json
forbids inferring the real one and preflight runs before it exists.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: frame disorder, tested deterministically instead of hoped for

**Files:**

- Create: `backend/tests/test_frame_disorder.py`
- Test data: the existing Tier-3 capture fixtures under `backend/tests/fixtures/` — read
  `backend/tests/test_cbs_resync.py`'s fixtures (`late_join_events`, `folded_with_snapshot`) and
  reuse them rather than adding new data.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_frame_disorder.py`:

```python
"""TIER 12 — a live room is not an ordered stream, and a mock may not misbehave on cue.

Three things a ticking CBS room does that a clean replay does not: deliver frames out of
order (two content scripts plus a REST mirror all race), deliver the same pick twice, and
resend the whole board after a reconnect. Testing these against a mock means hoping the mock
misbehaves while the owner watches; testing them against the Tier-3 capture means they are
always covered. The rehearsal REPORTS whether they occurred, it does not establish they are
handled.
"""

from __future__ import annotations

import random

from jaaffl.ingest.log import fold_state


def test_the_board_is_identical_when_pick_frames_arrive_out_of_order(late_join_events) -> None:
    """fold_state appends a pick idempotently per `overall`, so order must not matter to the
    SET of picks. current_overall_pick is a max() and must not matter either."""
    ordered = fold_state(late_join_events)
    shuffled = list(late_join_events)
    random.Random(20260810).shuffle(shuffled)
    scrambled = fold_state(shuffled)
    assert {p.overall for p in scrambled.picks} == {p.overall for p in ordered.picks}
    assert scrambled.current_overall_pick == ordered.current_overall_pick


def test_a_duplicated_pick_frame_does_not_duplicate_the_pick(late_join_events) -> None:
    """The extension de-dups by pick_number and SQLite has a unique index, but a fold that
    accepted a repeat would put the same player on the board twice and shift every round."""
    doubled = [ev for ev in late_join_events for _ in (0, 1)]
    once, twice = fold_state(late_join_events), fold_state(doubled)
    assert len(twice.picks) == len(once.picks)
    assert [p.overall for p in twice.picks] == [p.overall for p in once.picks]


def test_the_order_survives_a_reconnect_resync(late_join_events) -> None:
    """A reconnect replays the whole stream. The order must still be there afterwards -- the
    reason a mid-draft backend restart is a scripted step of the rehearsal."""
    order = [str(i) for i in range(1, 13)]
    events = list(late_join_events)
    folded = fold_state(events)
    if folded.draft_order is None:
        # The Tier-3 capture's own fullstatedelta.order rides on league_settings events; if this
        # fixture stream carries none, this test would be vacuous. Assert that explicitly rather
        # than skipping silently, and build the case the live room produces.
        raise AssertionError(
            "fixture carries no league_settings order — replace this fixture with one that does, "
            "or this test proves nothing"
        )
    assert folded.draft_order == order
```

⚠️ **Before running:** confirm the Tier-3 capture fixture actually contains a
`league_settings` event with a `draft_order` (grep the fixture, or fold it and print). If it does
not, the third test is vacuous — rewrite it to build the event stream explicitly from
`parse.ts`'s documented shape rather than deleting it, and note in the ROADMAP block that the
committed capture does not carry one. **The failure mode this whole tier is about is a test that
cannot fail.**

- [ ] **Step 2: Run them**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_frame_disorder.py -q`
Expected: the first two PASS immediately (`fold_state` is already idempotent per `overall` —
they are regression pins, and the plan says so rather than pretending they were red first). The
third PASSES only after Task 2 and only if the fixture carries an order.

- [ ] **Step 3: PROVE THEY CAN FAIL**

```bash
cp backend/src/jaaffl/ingest/log.py /tmp/log.py.bak2
```

| # | Mutation in `fold_state`'s `PICK_MADE` branch | The test that MUST fail |
| - | --------------------------------------------- | ----------------------- |
| 1 | drop the `if all(p.overall != pick.overall ...)` idempotence guard | `test_a_duplicated_pick_frame_does_not_duplicate_the_pick` |
| 2 | change `max(state.current_overall_pick, pick.overall + 1)` to `pick.overall + 1` | `test_the_board_is_identical_when_pick_frames_arrive_out_of_order` |
| 3 | delete the Task-2 order block | `test_the_order_survives_a_reconnect_resync` |

Restore between each.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_frame_disorder.py
git commit -m "test: pin out-of-order, duplicated and reconnected frames deterministically

A mock draft may not misbehave on cue, and the rehearsal is n=1. These run off the Tier-3
capture every CI run; the rehearsal only reports whether disorder occurred live.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: the harness-fidelity question, and the two things the fix must NOT move

**Files:**

- Modify: `backend/tests/test_harness_fidelity.py`
- Modify: `backend/tests/test_engine_latency.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_harness_fidelity.py`:

```python
class TestInstanceEight_TheFixtureSuppliedWhatTheWiringDropped:
    """Five tiers asked 'change the knob, does a pick move?'. Tier 10 asked 'change the pool
    ORDER, does a pick move?'. Tier 11 asked 'change the roster, does the objective move?'.

    Tier 12 asks the question none of those can: does the engine get this input from the
    WIRING, or from the fixture? engine_fixtures.make_context() defaults to
    jaaffl_settings(draft_order=teams(12)), so every engine test -- including Tier 3's own
    test_my_team_slot.py -- handed the engine an order that resolve_league_settings has never
    produced and, by its own docstring, never will.
    """

    def test_the_default_test_fixture_supplies_an_order_the_live_wiring_cannot(self) -> None:
        from jaaffl.league.constitution import resolve_league_settings
        from tests.engine_fixtures import make_context

        fixture = make_context([{"pid": "rb0", "pos": Position.RB, "mu": 300.0}])
        assert fixture.settings.draft_order is not None, "fixture no longer supplies an order"
        assert resolve_league_settings("cbs-live").draft_order is None
        # The gap itself, asserted. If a future change makes the constitution carry an order,
        # this fails and the ROADMAP note about instance eight has to be rewritten -- which is
        # the correct outcome, not a nuisance.

    def test_the_survival_model_is_reachable_from_the_state_alone(self) -> None:
        """The routing this tier added: with a live-wiring context (no order) the engine still
        reaches 'my_slot', because the ROOM's order arrives on the DraftState."""
        from jaaffl.domain import DraftState
        from jaaffl.engine.recommend import recommend
        from jaaffl.league.constitution import resolve_league_settings
        from tests.engine_fixtures import make_context

        specs = [
            {"pid": f"rb{i}", "pos": Position.RB, "mu": 300.0 - 5 * i, "adp": float(i + 1),
             "sd": 6.0, "ecr": float(i + 1)}
            for i in range(24)
        ]
        ctx = make_context(specs, settings=resolve_league_settings("cbs-live"))
        state = DraftState(
            league_id="cbs-live",
            current_overall_pick=13,
            my_team_id="7",
            draft_order=[str(i) for i in range(1, 13)],
        )
        assert recommend(state, ctx, ctx.params, limit=10).survival_basis == "my_slot"
```

Check the imports already at the top of `test_harness_fidelity.py` — add `Position` if absent.

- [ ] **Step 2: Run it**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_fidelity.py -q`
Expected: PASS after Task 3. Run it **before** Task 3 as a cross-check if convenient:
`test_the_survival_model_is_reachable_from_the_state_alone` fails there.

- [ ] **Step 3: Assert the two things the fix must NOT move**

Append to `backend/tests/test_engine_latency.py`:

```python
def test_the_state_order_does_not_cost_the_latency_budget() -> None:
    """The override is one model_copy per recompute. Pin it against the same <200ms analytic
    budget this file already enforces, on the same pick-1 worst case."""
    context = make_context(_latency_board())  # reuse this file's existing worst-case builder
    state = draft_state(
        league_id=context.settings.league_id,
        current_overall_pick=1,
        my_team_id="t0",
        draft_order=[f"t{i}" for i in range(12)],
    )
    started = time.perf_counter()
    rec = recommend(state, context, context.params)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert rec.survival_basis == "my_slot"
    assert elapsed_ms < 200.0, f"analytic recompute {elapsed_ms:.1f}ms exceeds the 200ms budget"
```

Read the existing budget test in that file first and reuse its board builder and its
`draft_state` helper signature verbatim — do not introduce a second worst-case board. If
`draft_state` does not accept `draft_order`/`my_team_id`, construct the `DraftState` directly.

- [ ] **Step 4: Assert the calibration harness is untouched**

Append to `backend/tests/test_harness_fidelity.py`:

```python
    def test_the_calibration_harness_never_reads_a_draft_order(self) -> None:
        """Tier 11 superseded every real-board number when the harness changed. This fix must
        not: calibrate/tune.py builds a SimContext and simulate.py derives its own slot
        schedule, so neither reads settings.draft_order. Asserted structurally rather than
        assumed, because 'this cannot possibly move the numbers' is how Tier 10's coupling
        was missed."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "jaaffl" / "calibrate"
        offenders = [
            path.name
            for path in root.rglob("*.py")
            if "draft_order" in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"calibrate reads draft_order in {offenders}"
```

Run it. **If it fails, stop and read the offending file** — a calibration module that reads
`draft_order` means this tier does move the tournament numbers and the ROADMAP block must say
so and re-measure, rather than the assertion being relaxed.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_harness_fidelity.py backend/tests/test_engine_latency.py
git commit -m "test: harness fidelity instance eight — the fixture supplied what the wiring dropped

make_context() defaults to jaaffl_settings(draft_order=teams(12)), so every engine test --
including Tier 3's own regression test for this exact symptom -- handed the engine an order
resolve_league_settings has never produced. Plus the two things this fix must NOT move: the
<200ms analytic budget, and every calibration number.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: the rehearsal protocol — the owner's ONE copy-paste block

**Files:**

- Create: `docs/rehearsal-protocol.md`

- [ ] **Step 1: Write it**

Create `docs/rehearsal-protocol.md` with exactly this structure. Every command must be one the
plan has already run — do not invent an invocation.

````markdown
# Live-room rehearsal protocol (Tier 12)

One CBS draft, one sitting, ~45 minutes, on the machine you will actually draft on.

**Which room.** A **free-to-join CBS league** — a real clock, real drafters, no money. That is
the point: a mock's bots do not produce real runs or real pace. Do a 10-minute **mock** first if
you want to shake out the install (§2 works for either). **Do not use your JAAFFL2025 league** —
that draft is the thing this rehearsal exists to protect.

Everything automated runs without you. Your part is the block in §2 plus three timed nudges
in §3. At the end you run one command and paste me the output.

## 1. What this is testing

The pipeline has replayed a complete captured draft end to end (Tier 3) but has never faced a
room with a clock. This rehearsal answers, with numbers: was the survival model live, did every
recompute meet the 200 ms budget, was every player you or anyone else drafted removed from your
board, and did every CBS player id resolve.

## 2. Your setup — one block, top to bottom

```powershell
cd C:\Users\conno\Code\Project_JAAFFL
git checkout tier12/live-room-rehearsal
git pull
pnpm --filter @jaaffl/extension build
```

Open Chrome → `chrome://extensions` → on the **JAAFFL — CBS Draft Assistant** card click
**Reload** (it must pick up the new build).

Open **https://www.cbssports.com/fantasy/football/**, join a **free** league and open its
**Draft Room** when it opens (or start a **Mock Draft** if you are shaking out the install).
Wait in the lobby. **Read your team number off the board** — that is your draft slot.

Back in the terminal, with `<N>` = your team number:

```powershell
(Get-Content .env) -replace '^JAAFFL_MY_TEAM_ID=.*', 'JAAFFL_MY_TEAM_ID=<N>' | Set-Content .env
.venv\Scripts\python.exe scripts\preflight.py
$env:JAAFFL_REHEARSAL_LOG = "data\rehearsal\mock-1.jsonl"
.venv\Scripts\python.exe -m jaaffl.api
```

**Preflight must print `OK` and exit 0.** If it fails it names the reason — stop and tell me.
Leave the last command running; that terminal is the backend.

In Chrome, on the draft tab: click the pinned **JAAFFL** icon. A red **REC** badge appears.
**Chrome will ask to "access other apps and services on this device" — click Allow.** It asks
again when the draft-room popup opens (different origin). Allow both, or nothing is recorded.

## 3. During the draft — three nudges, everything else is normal drafting

Draft normally against the clock for at least 6 rounds.

| When | Do this | Why |
| --- | --- | --- |
| one of your first 3 picks | **let the clock run out** so CBS auto-picks for you | a pick made *for* you takes a different path than one you make |
| around round 4 | **close the CBS draft tab and reopen the draft room** | the late-join resync — the board must not be lost |
| around round 6 | in the backend terminal press **Ctrl+C**, then re-run the last two lines of §2 | a mid-draft restart: the durable log must replay and the board must rebuild |

⚠️ **In a real league these three cost you something.** The auto-pick spends a real pick, and the
tab/backend restarts each take ~20 seconds off a clock. Do all three **early, in rounds where you
are happy with any of several players**, and skip any of them if the clock is tight — the
rehearsal is worth more than a perfect roster, but a defect found at round 4 is worth exactly as
much as one found at round 12. If you skip one, say which.

Then draft to the end (or to round 8+ if the league lets you leave). Click the **JAAFFL** icon
again — the REC badge goes away.

## 4. Hand back — one command plus two things

```powershell
.venv\Scripts\python.exe scripts\rehearsal_report.py data\rehearsal\mock-1.jsonl
```

Paste me its whole output, plus:

1. **one screenshot of the JAAFFL overlay** taken mid-draft (the foot line matters most)
2. **your team number**

That is everything. The recording under `apps/extension/fixtures/cbs/rec-*.jsonl` stays on your
disk (git-ignored) and lets a future tier replay this exact draft.

## 5. What each step passes on

| # | Step | Pass |
| - | ---- | ---- |
| 1 | preflight | exit 0, including `survival probe: basis=my_slot` |
| 2 | backend up | `/health` returns `{"status":"ok"}` |
| 3 | REC on | `recording_stored` lines in the backend terminal; `rec-*.jsonl` grows |
| 4 | order read from the room | report: **the order was read from the room** PASS |
| 5 | survival live | report: **survival is live** PASS — every row `my_slot` |
| 6 | latency | report: **recompute under 200ms** PASS — max under budget |
| 7 | masking | report: **every drafted player masked** PASS — `unresolved_ids` empty |
| 8 | scarcity live | report: **the scarcity term is live** PASS — `vona>0` never 0 |
| 9 | reconnect | `picks_masked` never decreases across the §3 tab reopen |
| 10 | restart | recommendations resume after the §3 restart, same board |
| 11 | overlay | your screenshot's foot line matches the report's derived line |

## 6. What this does NOT establish

- **n = 1.** One draft, one seat, one evening.
- **A free league is not JAAFFL2025.** Different people, different pace, different runs, and a
  roster/scoring setup that is probably not yours — so nothing here validates the engine against
  *your* league's board.
- **Nothing about pick QUALITY.** This proves the pipeline is live and honest under a clock; it
  says nothing about whether the recommendations are good. That is what the tournament measures,
  and `lambda_slot_override` is still the open decision there.
- **Not the settings page.** `CbsPageSnapshot` projections/injuries/rankings stay
  `TODO(capture)` — that needs a settings-page capture, not draft-room frames.
- **Whatever you skipped in §3** did not get tested. Say which.
````

- [ ] **Step 2: Format and commit**

```bash
pnpm exec prettier --write docs/rehearsal-protocol.md
git add docs/rehearsal-protocol.md
git commit -m "docs: the Tier 12 live-room rehearsal protocol

One CBS mock, one sitting, the owner's steps in one block. Three scripted perturbations -- an
auto-pick, a tab reopen, a mid-draft backend restart -- because those are the paths a clean
replay never takes. n=1, and it says so.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: run the rehearsal — DEFERRED to the desktop session

⚠️ **Scope change, decided 2026-08-10 mid-tier.** The owner will run the rehearsal on a
different machine (an ASUS mini PC, not the laptop this tier was built on) and in a **real
free-to-join CBS league** rather than a mock — a real clock and real drafters, with none of the
$400 league's stakes. Rehearsing where the draft will actually happen is the right call, and it
means **Tier 12 merges with the instrumentation and NO rehearsal results.**

That is a genuine reduction in what this tier establishes and the ROADMAP block must say so
without softening it: the seam is fixed and measured on the real board, the evidence pipeline is
built and unit-tested, and **the live room has still never been faced.** The claim "a replay is
not a live draft" is NOT retired by this tier.

The steps below move to the desktop session, which owns Tier 12's evidence half.

- [ ] **Step 1 (desktop session): hand the owner `docs/rehearsal-protocol.md`** and wait. Do not
      proceed on a guess about what the rehearsal will show.

- [ ] **Step 2: Run the report on the log the owner produced**

```bash
.venv\Scripts\python.exe scripts\rehearsal_report.py data\rehearsal\mock-1.jsonl
```

- [ ] **Step 3: For EVERY failing verdict, root-cause before fixing**

Use superpowers:systematic-debugging. Write the mechanism down before touching code — this
project has three tiers on record of fixing the wrong thing. Each defect gets a failing test
first, then the fix, then a mutation proving the test can fail.

- [ ] **Step 4: Cross-check the owner's screenshot against the report's derived foot line.**
      If they disagree, the screenshot wins — the derivation is a claim about the overlay, and
      the DOM is the ground truth.

- [ ] **Step 5 (desktop session): commit the evidence**

Copy the report output and the log's row count into a **Tier 12b** ROADMAP block. Do **not**
commit `data/rehearsal/*.jsonl` — a free-to-join league's log carries other real drafters' team
ids, exactly like the raw captures under `apps/extension/fixtures/cbs/`. Confirm `.gitignore`
covers `data/` before committing anything else in this task.

---

## Task 14: the corrected record

**Files:**

- Modify: `ROADMAP.md` (new Tier 12 block at the top, above Tier 11)
- Modify: `docs/owner-manual-todo.md`
- Modify: `docs/live-draft-recording-guide.md`

- [ ] **Step 1: Write the ROADMAP Tier 12 block**

Match the established voice: a `> **Tier 12 of the audit is merged** (PR #NN).` lead, then the
control, the finding with its measurements, the instrument section, **What Tier 12 did NOT do**,
and **⚠️ What is superseded**. Every number carries its pool. It must state:

- the control (the live surface at `4f7442b`, table in this plan's Why section);
- the finding, with the three links and the 0/50 → 3-of-17 measurement;
- **harness-fidelity instance eight** — `make_context`'s default order, and that Tier 3's own
  `test_my_team_slot.py` passed against it;
- 🔴 **that the rehearsal was NOT run in this tier** — the instrumentation, the protocol and the
  preflight gate shipped; the room did not. State it in the lead, not buried in the NOT-done
  list, because a tier titled "the room is ticking" that never faced a room is exactly the kind
  of thing a reader will assume happened. `ROADMAP`'s standing "a replay is not a live draft" is
  **not** retired;
- **What Tier 12 did NOT do**, including at minimum: **no rehearsal** (deferred to the desktop
  session, in a free-to-join league); no coefficient, no config key,
  `config/engine.json` untouched and the `lambda_slot_override` recommendation still OPEN
  (verified 2026-08-10, still `0.4 / −0.4`); no calibration number re-measured (asserted in
  Task 11, not assumed); a mock is not a league; the settings-page capture is still
  `TODO(capture)`; every Tier 11 caveat still standing (σ excludes missed-game variance, weekly
  scores unclipped, championship probability still "highest season total of the 12");
- **⚠️ What is superseded**: Tier 3's account of the VONA-zero defect (its fix was necessary and
  not sufficient), and `docs/owner-manual-todo.md` §1's instruction that setting
  `JAAFFL_MY_TEAM_ID` restores the real VONA.

- [ ] **Step 2: Correct `docs/owner-manual-todo.md` §1**

The "TWO THINGS TO DO BEFORE DRAFT NIGHT" block says setting `JAAFFL_MY_TEAM_ID` makes the
engine compute real survival. Until this tier that was **false**, and the correction is the more
useful fact — record it rather than quietly editing. State: the slot was one of two required
inputs; the other (the room's entered order) had no wiring at all; both are now wired; preflight
fails if the slot is unset; and the overlay now names which input is missing.

Re-state the still-open `lambda_slot_override` recommendation with Tier 11's corrected numbers:
`0.0063 → 0.1109` championship probability and `1453 → 1739` points against `vbd_only`'s
`0.1206 / 1703`, on the corrected harness, five seed blocks. **Nothing changed;
`config/engine.json` is the owner's, verified 2026-08-10 still `0.4 / −0.4`.**

Add a Tier 12 note under §1b if and only if the rehearsal produced a bench-eligibility
observation; that question (§1b, "Does CBS let you put a kicker or a defense on your bench?")
stays OPEN either way.

- [ ] **Step 3: Update `docs/live-draft-recording-guide.md`**

Three edits, only where this tier actually changed something:

1. **§6** documents `make backend-dev` with a Windows fallback. Add the `JAAFFL_REHEARSAL_LOG`
   line as an optional extra, and note the extension must be **reloaded** in
   `chrome://extensions` after any rebuild (Step 4 builds `dist/`, but a loaded card keeps
   serving the old build until reloaded — a rehearsal that skips this tests the old code).
2. **§7** gains a pointer to `docs/rehearsal-protocol.md` and to
   `docs/desktop-draft-setup.md`.
3. **§12 Troubleshooting** gains one row: `VONA degraded · draft order not read yet` in the
   overlay foot → the room's `league_settings` frame has not arrived; paste an
   `ORDER: 1,2,…,12` line (exactly 12 entries) into the Manual-paste box.

⚠️ Do **not** rewrite §0's "what to expect on screen" — it describes what the overlay shows
during a live draft, and this tier did not observe one. That correction belongs to the desktop
session, which will have seen it.

- [ ] **Step 4: Write `docs/desktop-draft-setup.md`**

A one-time setup for the ASUS mini PC, so the desktop session starts from a known-good machine
rather than debugging an install against a clock. It must cover: clone from GitHub; install
Python ≥ 3.11 / Node 22 / pnpm; create the venv and install the backend editable with the same
extras this repo uses (read `CONTRIBUTING.md` and `backend/pyproject.toml` for the exact extra
names — do not guess them); `pnpm install`; **copy `.env` across by hand** (it is git-ignored and
holds `OPENAI_API_KEY`); build and load the extension; run `scripts/preflight.py --seed` to
rebuild `data/` from the free feeds (also git-ignored — nothing in `data/` transfers); then the
full green-suite check so the desktop is verified before draft night, not during it.

- [ ] **Step 5: Format and commit**

```bash
pnpm exec prettier --write ROADMAP.md docs/owner-manual-todo.md docs/live-draft-recording-guide.md docs/desktop-draft-setup.md
git add ROADMAP.md docs/owner-manual-todo.md docs/live-draft-recording-guide.md docs/desktop-draft-setup.md
git commit -m "docs: Tier 12 record — the live path could never compute a survival model

The rehearsal itself is NOT in this tier: it moves to the owner's desktop, in a free-to-join
league. The instrumentation, the protocol and the preflight gate shipped; the room did not.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 15: the config change this tier RE-STATES — proposed, NOT applied

- [ ] **Step 1: Verify the file again, in this session, and quote it**

```bash
.venv\Scripts\python.exe -c "import json;print(json.load(open('config/engine.json'))['lambda_slot_override'])"
```

Expected: `{'last_startable_slot_floor': 0.4, 'surplus_stash_ceiling': -0.4}`.

- [ ] **Step 2: Put the proposed diff in the PR body, and nowhere else**

```diff
   "lambda_slot_override": {
-    "last_startable_slot_floor": 0.4,
-    "surplus_stash_ceiling": -0.4
+    "last_startable_slot_floor": 0.0,
+    "surplus_stash_ceiling": 0.0
   },
```

With Tier 11's corrected numbers, real board, five disjoint seed blocks × 8 seeds × 12 slots,
800 sampled seasons, field `[SoftmaxVbd, NeedBased]`:

| measure                  | as shipped | setting off | plain best-available |
| ------------------------ | ---------- | ----------- | -------------------- |
| championship probability | 0.0063     | **0.1109**  | 0.1206               |
| projected points         | 1453       | **1739**    | 1703                 |

Still a statistical tie against best-available on championship probability (and the point
estimate is now on the **unfriendly** side of zero); a solid win on points. Tier 12 measured
none of this and changes none of it.

- [ ] **Step 3: Do NOT edit `config/engine.json`.** It is owner-adopted. This tier writes no
      config file.

---

## Task 16: verification, review, PR

- [ ] **Step 1: Use superpowers:verification-before-completion.** No success claim without the
      command output in front of you.

- [ ] **Step 2: Run every gate, from the repo root**

```bash
.venv\Scripts\python.exe -m pytest backend -q
pnpm -r typecheck
pnpm -r test
pnpm lint
cd backend && ..\.venv\Scripts\python.exe -m ruff check . ../scripts && ..\.venv\Scripts\python.exe -m ruff format --check . ../scripts && cd ..
.venv\Scripts\python.exe scripts\export_schemas.py
git diff --exit-code packages\shared\schemas
node scripts\gen-overlay-tokens.mjs --check
```

⚠️ `ruff check . ../scripts` from `backend/` — a bare `ruff check .` there does **not** cover
`scripts/`, and this tier adds two files there. Expected: `679 + new` passed, everything green,
`git diff --exit-code` clean (Task 1 already committed the regenerated schema).

- [ ] **Step 3: Drive the real FastAPI surface** with the project's `verify` skill. Confirm
      `survival_basis` and `recompute_ms` on both the pull and push paths, and both WS
      handshakes. Record the numbers for the PR body.

- [ ] **Step 4: Prettier every touched markdown file and commit the result**

```bash
pnpm exec prettier --write docs/rehearsal-protocol.md ROADMAP.md docs/owner-manual-todo.md docs/live-draft-recording-guide.md docs/superpowers/plans/2026-08-10-tier12-the-room-is-ticking.md
git add -A && git commit -m "chore: prettier the Tier 12 docs

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Use superpowers:requesting-code-review.** It has caught a serious defect in each
      of the last two tiers, including one that invalidated a headline. Act on what it finds; if
      it invalidates a claim in the ROADMAP block, retract it in the block rather than editing it
      away — the retraction is the more useful fact.

- [ ] **Step 6: Push, PR, wait for all four checks, squash-merge**

```bash
git push -u origin tier12/live-room-rehearsal
gh pr create --title "Tier 12: the room is ticking, and the engine never learned the order" --body-file <path>
gh pr checks <N>            # no jq on this machine — read the table
```

Wait for **Backend, Node 22, Node 24, Playwright**. Then squash-merge, delete the branch, and:

```bash
git checkout main && git pull
```

- [ ] **Step 7: Report the PR URL and the final commit SHA.**

---

## Self-review

**Spec coverage.** Every element of the approved design maps to a task: the contract field
(1), the fold (2), `recommend()` + the degraded reason (3), analytics (4), the paste guard (5),
the overlay message (6), the sink (7), the report (8), the preflight gate (9), deterministic
disorder (10), harness fidelity + the two non-regressions (11), the protocol (12), the rehearsal
itself (13), the record (14), the config re-statement (15), verification and PR (16).

**Three places this plan tells the implementer to stop rather than guess**, because each is a
way this tier could produce a vacuous result:

1. Task 10, the reconnect test — if the committed Tier-3 fixture carries no `league_settings`
   order, the test proves nothing and must be rebuilt, not skipped.
2. Task 11 step 4 — if any `calibrate/` module reads `draft_order`, this tier **does** move the
   tournament numbers and must say so, rather than relaxing the assertion.
3. Task 13 — the rehearsal's outcome is not predicted anywhere in this plan.

**Known gap, stated rather than papered over.** Task 9's unit tests cover `survival_probe`; the
`return 1` gate around it is covered only by the manual run in step 5. A test that shells out to
`preflight.main()` would close it; this plan does not add one, and the mutation step says so
explicitly.

**Type consistency.** `survival_basis` takes exactly three values — `my_slot`,
`degraded_no_slot`, `degraded_no_order` — spelled identically in `recommend.py`, the model
description, `overlay.ts`, `rehearsal_report.py` and every test. `RehearsalLog.record` has one
signature, `(path_label, state, rec, context)`, at both call sites, and `evaluate(rows)` returns
`list[Verdict]` with `.name` / `.passed` / `.detail` used consistently by the report and its
tests.
