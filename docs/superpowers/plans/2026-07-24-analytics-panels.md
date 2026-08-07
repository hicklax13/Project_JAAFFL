# Dashboard Analytics Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two remaining Stage-6 dashboard analytics panels — positional value curves and full survival curves — fed by a new `GET /analytics` endpoint.

**Architecture:** A new pure module `engine/analytics.py` derives series from the already-cached `DraftContext` plus the folded `DraftState`; a new `GET /analytics` endpoint serves them with its own 503 "warming up" gate (the board's `/state` keeps working independently); the dashboard fetches on hydrate and re-fetches on each `/recs/ws` push, rendering two bespoke accessible SVG panels. The frozen engine hot path (`recommend`, `optimize`, `opponents`, `tiers`, `projections`, `context`) is **not modified** — only imported.

**Tech Stack:** Python 3.12 · FastAPI · Pydantic v2 · NumPy/SciPy (already used by `opponents`) · pytest · TypeScript · Next.js 15 · React 19 · Zod · Vitest + Testing Library. **No new dependencies.**

**Design spec:** [`docs/superpowers/specs/2026-07-24-analytics-panels-design.md`](../specs/2026-07-24-analytics-panels-design.md)

---

## Context an engineer needs before starting

**Read first:** [`CLAUDE.md`](../../../CLAUDE.md) and [`config/league.json`](../../../config/league.json). The league config is **IMMUTABLE** — never edit it.

**Four project rules that will bite you:**

1. **Never infer snake draft order from team count.** `config/league.json` sets `"infer_from_team_count": false`. Always get pick numbers from `opponents.next_overall_pick(settings, state, horizon=H)`, which reads the real entered `settings.draft_order`.
2. **Do not edit `design/tokens/draft-room.css`.** It is drift-guarded by `apps/extension/tests/overlay-tokens.test.ts`; editing it requires running `pnpm gen:tokens` and committing the regenerated `apps/extension/src/overlay/draft-room-tokens.ts`. This plan puts all new CSS in `apps/web/app/globals.css` instead, which already imports the canonical tokens and is dashboard-only.
3. **The new schema is deliberately OUTSIDE the E5 Pydantic⇄Zod parity gate.** Do **not** add it to `CONTRACT_SCHEMAS` in `packages/shared/tests/parity.test.ts` or to `scripts/export_schemas.py`. Precedent + rationale: `packages/shared/src/state.ts`.
4. **Python venv has no pip.** It is uv-managed. Use `uv pip install` if you ever need a package (you should not need one).

**Commands (run from the repo root unless noted):**

| Purpose          | Command                                                                          |
| ---------------- | -------------------------------------------------------------------------------- |
| Backend tests    | `cd backend && ../.venv/Scripts/python.exe -m pytest`                            |
| One backend test | `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v` |
| Backend lint     | `cd backend && ../.venv/Scripts/python.exe -m ruff check . ../scripts`           |
| Backend format   | `cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts`          |
| JS typecheck     | `pnpm -r typecheck`                                                              |
| JS tests         | `pnpm -r test`                                                                   |

**Key existing APIs you will call (already implemented — do not rewrite):**

```python
# backend/src/jaaffl/engine/opponents.py
def next_overall_pick(settings: LeagueSettings, state: DraftState, *, horizon: int = 1) -> int
def run_pressure_by_position(state, settings, adp: Mapping[str, float], position) -> dict[Position, float]
def board_adp_shift(run_pressure, position, *, beta: float) -> dict[str, float]
def pick_probabilities(state, settings, adp, adp_sd, *, horizon=None,
                       my_next_overall=None, adp_shift=None) -> dict[str, float]  # P(TAKEN), not survival

# backend/src/jaaffl/engine/service.py
class RecommendationEngine:
    def context_for(self, league_id: str) -> DraftContext | None   # public accessor; returns None while warming
```

`DraftContext` fields you will use: `settings`, `params`, `mu`, `position`, `baselines`, `adp_mean`, `adp_sd`, `players`.

---

## File structure

| File                                                           | Responsibility                                                                |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **Create** `backend/src/jaaffl/engine/analytics.py`            | View models + pure series builders (value curves, survival curves, assembler) |
| **Create** `backend/tests/test_analytics.py`                   | Unit tests for the series math                                                |
| **Modify** `backend/src/jaaffl/api/app.py`                     | Add `GET /analytics`                                                          |
| **Modify** `backend/tests/test_api.py`                         | Endpoint tests (200/404/409/503/Origin)                                       |
| **Create** `packages/shared/src/analytics.ts`                  | Zod mirror (outside the parity gate)                                          |
| **Modify** `packages/shared/src/index.ts`                      | Re-export the new schemas                                                     |
| **Create** `apps/web/lib/curve.ts`                             | Pure SVG scaling math (no React)                                              |
| **Create** `apps/web/lib/curve.test.ts`                        | Tests for the scaling math                                                    |
| **Modify** `apps/web/lib/api.ts`                               | `fetchAnalytics` with the honesty contract                                    |
| **Modify** `apps/web/components/use-recs.ts`                   | Hold analytics in state; `refreshAnalytics()`                                 |
| **Create** `apps/web/components/value-curve-panel.tsx`         | Value-curve chart + position toggle                                           |
| **Create** `apps/web/components/value-curve-panel.test.tsx`    | Panel tests                                                                   |
| **Create** `apps/web/components/survival-curve-panel.tsx`      | Multi-line survival chart                                                     |
| **Create** `apps/web/components/survival-curve-panel.test.tsx` | Panel tests                                                                   |
| **Modify** `apps/web/components/dashboard.tsx`                 | Place both panels                                                             |
| **Modify** `apps/web/app/globals.css`                          | Chart styles (NOT the drift-guarded token file)                               |
| **Modify** `ROADMAP.md`                                        | Mark the panels done                                                          |

---

## Task 1: Backend value curves

**Files:**

- Create: `backend/src/jaaffl/engine/analytics.py`
- Test: `backend/tests/test_analytics.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_analytics.py`:

```python
"""Analytics series for the dashboard panels (GET /analytics) — pure math, no I/O."""

from __future__ import annotations

from jaaffl.domain import DraftPick, Position
from jaaffl.engine.analytics import CURVE_DEPTH, value_curves
from tests.engine_fixtures import draft_state, make_context, teams


def _specs() -> list[dict]:
    """A board with all four charted positions plus a K (which must NOT be charted)."""
    specs: list[dict] = []
    for i in range(40):
        specs.append(
            {"pid": f"rb{i}", "pos": Position.RB, "mu": 300.0 - 5 * i, "adp": float(i + 1), "sd": 6.0}
        )
    for i in range(40):
        specs.append(
            {"pid": f"wr{i}", "pos": Position.WR, "mu": 280.0 - 2 * i, "adp": float(41 + i), "sd": 6.0}
        )
    for i in range(6):
        specs.append(
            {"pid": f"qb{i}", "pos": Position.QB, "mu": 320.0 - 8 * i, "adp": float(20 + i), "sd": 6.0}
        )
    for i in range(6):
        specs.append(
            {"pid": f"te{i}", "pos": Position.TE, "mu": 200.0 - 15 * i, "adp": float(30 + i), "sd": 6.0}
        )
    specs.append({"pid": "k0", "pos": Position.K, "mu": 130.0, "adp": 160.0, "sd": 6.0})
    return specs


def test_value_curves_rank_by_descending_vor() -> None:
    """Each curve is VOR-ranked best-first, and rank is 1-based and contiguous."""
    context = make_context(_specs())
    curves = {c.position: c for c in value_curves(context, draft_state(1))}

    rb = curves["RB"]
    assert [p.rank for p in rb.full] == list(range(1, len(rb.full) + 1))
    assert rb.full == sorted(rb.full, key=lambda p: p.vor, reverse=True)
    assert rb.full[0].player_id == "rb0"


def test_value_curves_exclude_k_and_dst() -> None:
    """K/DST go in the final rounds and their curves are flat — charting them is noise."""
    context = make_context(_specs())
    assert {c.position for c in value_curves(context, draft_state(1))} == {"QB", "RB", "WR", "TE"}


def test_value_curves_cap_depth_per_position() -> None:
    """Payload is bounded at CURVE_DEPTH players per position."""
    context = make_context(_specs())
    curves = {c.position: c for c in value_curves(context, draft_state(1))}
    assert len(curves["RB"].full) == CURVE_DEPTH


def test_remaining_drops_drafted_players_while_full_keeps_them() -> None:
    """The gap between `full` and `remaining` IS the positional run the panel visualises."""
    context = make_context(_specs())
    state = draft_state(
        3,
        picks=[
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t0", player_id="rb0"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t1", player_id="rb1"),
        ],
    )
    rb = {c.position: c for c in value_curves(context, state)}["RB"]

    assert [p.player_id for p in rb.full][:2] == ["rb0", "rb1"]
    assert "rb0" not in {p.player_id for p in rb.remaining}
    assert "rb1" not in {p.player_id for p in rb.remaining}
    assert rb.remaining[0].player_id == "rb2"
    assert rb.remaining[0].rank == 1  # remaining is re-ranked from 1, not a gapped slice


def test_vor_is_mu_minus_positional_baseline() -> None:
    """VOR is value over replacement, using the context's own baselines."""
    context = make_context(_specs())
    rb = {c.position: c for c in value_curves(context, draft_state(1))}["RB"]
    expected = context.mu["rb0"] - context.baselines[Position.RB]
    assert rb.full[0].vor == round(expected, 2)


def test_draft_order_is_never_inferred_from_team_count() -> None:
    """Guard: fixtures pass the REAL entered order; curves must not need one at all."""
    context = make_context(_specs())
    assert context.settings.draft_order == teams(12)
    assert value_curves(context, draft_state(1))  # value curves are order-independent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jaaffl.engine.analytics'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/jaaffl/engine/analytics.py`:

```python
"""Analytics series for the dashboard panels (``GET /analytics``).

Derives the value curves and survival curves the war-room panels render, from the already-cached
:class:`DraftContext` plus the folded :class:`DraftState`. Pure functions, no I/O and no providers —
and NOT on the per-pick hot path: ``recommend`` never calls this module.

Survival reuses ``opponents.pick_probabilities`` (and the R3 board-conditioning helpers) rather than
re-deriving the Gaussian, so the panel and the engine can never disagree about who is scarce.

Backend-internal view models: no place in the E5 Pydantic⇄Zod parity surface, exactly like
:class:`DraftBoardState` (``ingest/board.py``). The dashboard parses these with a local Zod schema
(``packages/shared/src/analytics.ts``); the strict parity set stays the fixed nine.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from jaaffl.domain import DraftState, Position
from jaaffl.engine.context import DraftContext

# Positions worth charting. K and DST are drafted in the final rounds and their curves are flat,
# so plotting them adds noise without informing a decision (config/league.json strategic_notes).
CURVE_POSITIONS: tuple[Position, ...] = (Position.QB, Position.RB, Position.WR, Position.TE)

# Bound the payload: 36 players per position is ~three rounds deep at 12 teams.
CURVE_DEPTH = 36


class CurvePoint(BaseModel):
    """One (rank, VOR) sample on a positional value curve."""

    rank: int = Field(ge=1)
    vor: float
    player_id: str
    name: str | None = None


class PositionCurve(BaseModel):
    """A position's value curve: the original board and what is still undrafted."""

    position: str
    full: list[CurvePoint] = Field(default_factory=list)
    remaining: list[CurvePoint] = Field(default_factory=list)


def _drafted_ids(state: DraftState) -> set[str]:
    return {pick.player_id for pick in state.picks if pick.player_id}


def _curve(pids: Iterable[str], context: DraftContext) -> list[CurvePoint]:
    """VOR-ranked points for one position, best-first, re-ranked from 1 and capped."""
    ranked = sorted(pids, key=lambda pid: context.mu[pid], reverse=True)
    points: list[CurvePoint] = []
    for rank, pid in enumerate(ranked[:CURVE_DEPTH], start=1):
        baseline = context.baselines.get(context.position[pid], 0.0)
        player = context.players.get(pid)
        points.append(
            CurvePoint(
                rank=rank,
                vor=round(context.mu[pid] - baseline, 2),
                player_id=pid,
                name=player.name if player is not None else None,
            )
        )
    return points


def value_curves(context: DraftContext, state: DraftState) -> list[PositionCurve]:
    """Per-position VOR-vs-rank curves: the full preseason board plus what remains.

    The gap between ``full`` and ``remaining`` is what the panel draws as the positional run.
    """
    drafted = _drafted_ids(state)
    curves: list[PositionCurve] = []
    for position in CURVE_POSITIONS:
        at_pos = [pid for pid, pos in context.position.items() if pos == position and pid in context.mu]
        if not at_pos:
            continue
        curves.append(
            PositionCurve(
                position=position.value,
                full=_curve(at_pos, context),
                remaining=_curve([pid for pid in at_pos if pid not in drafted], context),
            )
        )
    return curves
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts && ../.venv/Scripts/python.exe -m ruff check . ../scripts
cd .. && git add backend/src/jaaffl/engine/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): positional value curves (full + remaining) over the cached context"
```

---

## Task 2: Backend survival curves

**Files:**

- Modify: `backend/src/jaaffl/engine/analytics.py`
- Test: `backend/tests/test_analytics.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analytics.py` (and extend the existing import line to
`from jaaffl.engine.analytics import CURVE_DEPTH, SURVIVAL_CANDIDATES, survival_curves, value_curves`):

```python
def test_survival_is_monotonically_decreasing_and_bounded() -> None:
    """A player can only get less available as picks pass; probabilities stay in [0, 1]."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10))

    assert curves, "expected survival curves for the default candidate set"
    for curve in curves:
        values = [p.survival for p in curve.points]
        assert all(0.0 <= v <= 1.0 for v in values)
        assert values == sorted(values, reverse=True)


def test_survival_caps_candidate_count() -> None:
    """One line per candidate, capped so the chart stays readable."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10))
    assert len(curves) <= SURVIVAL_CANDIDATES


def test_explicit_candidates_are_honoured_in_order() -> None:
    """The dashboard passes the ids it already has, so the lines match the ranked picks shown."""
    context = make_context(_specs())
    curves, _ = survival_curves(context, draft_state(10), candidates=["wr3", "rb7"])
    assert [c.player_id for c in curves] == ["wr3", "rb7"]


def test_unknown_and_drafted_candidate_ids_are_ignored_not_fatal() -> None:
    """A stale id from the client must degrade a line, never 500 the endpoint."""
    context = make_context(_specs())
    state = draft_state(
        3, picks=[DraftPick(overall=1, round=1, pick_in_round=1, team_id="t0", player_id="rb0")]
    )
    curves, _ = survival_curves(context, state, candidates=["rb0", "no-such-player", "wr1"])
    assert [c.player_id for c in curves] == ["wr1"]


def test_markers_come_from_the_real_entered_draft_order() -> None:
    """config/league.json forbids inferring snake order; markers must read settings.draft_order."""
    context = make_context(_specs())
    state = draft_state(5, my_team_id="t0")
    _, markers = survival_curves(context, state)

    assert len(markers) == 2
    assert all(m > state.current_overall_pick for m in markers)
    assert markers == sorted(markers)


def test_survival_domain_spans_current_pick_through_second_marker_plus_tail() -> None:
    """The curve must visibly continue past your second turn, not stop on the marker."""
    context = make_context(_specs())
    state = draft_state(5, my_team_id="t0")
    curves, markers = survival_curves(context, state)

    picks = [p.pick for p in curves[0].points]
    assert picks[0] == state.current_overall_pick
    assert picks == list(range(picks[0], picks[-1] + 1))  # every integer pick, no gaps
    assert picks[-1] > markers[-1]


def test_survival_degrades_when_draft_order_is_unknown() -> None:
    """Pre-draft (no order / no team) must return empty markers rather than raising."""
    from tests.engine_fixtures import jaaffl_settings

    context = make_context(_specs(), settings=jaaffl_settings(draft_order=None))
    state = draft_state(1, my_team_id="t0")
    curves, markers = survival_curves(context, state)
    assert markers == []
    assert curves  # curves still render over the fallback span


def test_markers_are_empty_once_my_picks_are_exhausted() -> None:
    """next_overall_pick returns a far-future sentinel when you have no picks left; charting it
    would draw markers and points past the literal end of the draft."""
    context = make_context(_specs())
    state = draft_state(200, my_team_id="t0")  # t0's last pick is overall 193

    curves, markers = survival_curves(context, state)

    assert markers == []
    assert all(point.pick <= 204 for curve in curves for point in curve.points)
```

Note this is a DIFFERENT code path from `test_survival_degrades_when_draft_order_is_unknown`: that
one raises inside `_my_overall_picks` before a sentinel is ever computed. This one has a perfectly
valid draft order and simply has no picks left — which is what the sentinel exists for.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: FAIL — `ImportError: cannot import name 'survival_curves'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/src/jaaffl/engine/analytics.py` — extend the imports at the top:

```python
from jaaffl.engine.opponents import (
    board_adp_shift,
    next_overall_pick,
    pick_probabilities,
    run_pressure_by_position,
)
```

Add these constants beside `CURVE_DEPTH`:

```python
# One survival line per candidate — matches the scalar SurvivalPanel's slice(0, 6) so the two
# survival surfaces always show the same players.
SURVIVAL_CANDIDATES = 6

# Picks charted beyond your second upcoming pick, so the curve continues past the marker.
SURVIVAL_TAIL = 6

# Hard bound on the charted span, so a very deep board cannot balloon the payload.
SURVIVAL_MAX_SPAN = 60

# Mirrors opponents._draft_rounds: rounds = total roster slots, falling back to the JAAFFL
# constitution's 17. Duplicated (not imported) because opponents.py is frozen and exposes no
# public accessor.
_DEFAULT_ROUNDS = 17
```

> **CORRECTED 2026-07-24 (post-review).** An earlier draft of this task guarded the no-picks-left
> sentinel with `pick > current + SURVIVAL_MAX_SPAN`. That is structurally incapable of catching it:
> `next_overall_pick` returns `rounds × teams + 1` (= 205 here, vs a last real pick of 204), and once
> your picks are exhausted the sentinel is only ever `team_count − 1` (≤ 11) picks ahead of the
> current pick — always far below `SURVIVAL_MAX_SPAN` (60), and always greater than it. Neither
> clause could fire, so the final ~11 picks of every real draft charted markers and points past the
> end of the draft. The correct invariant is **end-of-draft**, not span. Fixed in `7f6d6e4`; the code
> below reflects the corrected version.

Append the models and builder:

```python
class SurvivalPoint(BaseModel):
    """P(player still on the board) at one overall pick number."""

    pick: int = Field(ge=1)
    survival: float = Field(ge=0.0, le=1.0)


class SurvivalCurve(BaseModel):
    """One candidate's availability decay across the charted pick span."""

    player_id: str
    name: str | None = None
    position: str | None = None
    points: list[SurvivalPoint] = Field(default_factory=list)


def _total_picks(settings: LeagueSettings) -> int:
    """The last valid overall pick. ``next_overall_pick`` returns this + 1 as its no-picks-left
    sentinel, so any marker beyond it is not a real pick."""
    rounds = sum(slot.count for slot in settings.roster_slots) or _DEFAULT_ROUNDS
    return rounds * len(settings.draft_order or [])


def _marker_picks(context: DraftContext, state: DraftState) -> list[int]:
    """Your next two upcoming picks, read from the REAL entered draft order.

    ``config/league.json`` sets ``infer_from_team_count: false`` — the order is decided in person
    and entered into CBS — so these MUST come from ``next_overall_pick``. Degrades to ``[]`` when
    the order or our team slot is not known yet (pre-draft), rather than raising.
    """
    markers: list[int] = []
    total = _total_picks(context.settings)
    for horizon in (1, 2):
        try:
            pick = next_overall_pick(context.settings, state, horizon=horizon)
        except ValueError:
            return []
        # Beyond the last pick of the draft = the no-picks-left sentinel, not a real upcoming pick.
        if pick <= state.current_overall_pick or (total and pick > total):
            break
        markers.append(pick)
    return markers


def survival_curves(
    context: DraftContext,
    state: DraftState,
    *,
    candidates: Sequence[str] | None = None,
) -> tuple[list[SurvivalCurve], list[int]]:
    """``(curves, marker_picks)`` — availability decay for the candidate set.

    ``candidates`` are the ids the dashboard already holds from the WS push, so the lines match the
    ranked picks rendered above them; unknown or already-drafted ids are skipped rather than
    raising. Omitted, it falls back to the best available by projected points so the endpoint is
    useful (and testable) on its own.
    """
    drafted = _drafted_ids(state)
    available = [pid for pid in context.mu if pid not in drafted]
    if candidates is None:
        chosen = sorted(available, key=lambda pid: context.mu[pid], reverse=True)
    else:
        available_set = set(available)
        chosen = [pid for pid in candidates if pid in available_set]
    chosen = [pid for pid in chosen[:SURVIVAL_CANDIDATES] if pid in context.adp_mean]

    markers = _marker_picks(context, state)
    total = _total_picks(context.settings)
    start = state.current_overall_pick
    end = min((markers[-1] if markers else start) + SURVIVAL_TAIL, start + SURVIVAL_MAX_SPAN)
    if total:
        end = min(end, total)  # never chart a pick past the end of the draft
    picks = list(range(start, end + 1))

    if not chosen or not picks:
        return [], markers

    # Board-conditioned effective ADP (R3), mirroring recommend(): a position going faster than ADP
    # pulls its survival down, so the chart agrees with the advice the engine is giving.
    available_adp = {pid: context.adp_mean[pid] for pid in available if pid in context.adp_mean}
    try:
        pressure = run_pressure_by_position(state, context.settings, available_adp, context.position)
    except ValueError:
        pressure = {}
    shift = board_adp_shift(pressure, context.position, beta=context.params.board_survival_weight)

    subset_adp = {pid: context.adp_mean[pid] for pid in chosen}
    subset_sd = {pid: context.adp_sd[pid] for pid in chosen if pid in context.adp_sd}

    # One vectorized call per charted pick, then fan out — not one call per (player, pick).
    series: dict[str, list[SurvivalPoint]] = {pid: [] for pid in chosen}
    for pick in picks:
        taken = pick_probabilities(
            state,
            context.settings,
            subset_adp,
            subset_sd,
            my_next_overall=pick,
            adp_shift=shift,
        )
        for pid in chosen:
            survival = 1.0 - float(taken.get(pid, 0.0))
            series[pid].append(SurvivalPoint(pick=pick, survival=round(min(1.0, max(0.0, survival)), 4)))

    curves = [
        SurvivalCurve(
            player_id=pid,
            name=context.players[pid].name if pid in context.players else None,
            position=context.position[pid].value if pid in context.position else None,
            points=series[pid],
        )
        for pid in chosen
    ]
    return curves, markers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts && ../.venv/Scripts/python.exe -m ruff check . ../scripts
cd .. && git add backend/src/jaaffl/engine/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): board-conditioned survival curves with real-order pick markers"
```

---

## Task 3: Backend assembler

**Files:**

- Modify: `backend/src/jaaffl/engine/analytics.py`
- Test: `backend/tests/test_analytics.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analytics.py` (extend the analytics import with `build_analytics`):

```python
def test_build_analytics_folds_both_series_and_markers() -> None:
    """One payload the panel layer can render without a second round-trip."""
    context = make_context(_specs())
    state = draft_state(5, league_id="L1", my_team_id="t0")
    analytics = build_analytics(context, state)

    assert analytics.league_id == "L1"
    assert analytics.current_overall_pick == 5
    assert len(analytics.my_next_picks) == 2
    assert {c.position for c in analytics.value_curves} == {"QB", "RB", "WR", "TE"}
    assert analytics.survival_curves


def test_build_analytics_passes_candidates_through() -> None:
    context = make_context(_specs())
    analytics = build_analytics(context, draft_state(5), candidates=["wr2"])
    assert [c.player_id for c in analytics.survival_curves] == ["wr2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_analytics'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/src/jaaffl/engine/analytics.py`:

```python
class DraftAnalytics(BaseModel):
    """The dashboard analytics feed — both series plus the pick markers that anchor them."""

    league_id: str
    current_overall_pick: int = Field(ge=1)
    my_next_picks: list[int] = Field(default_factory=list)
    value_curves: list[PositionCurve] = Field(default_factory=list)
    survival_curves: list[SurvivalCurve] = Field(default_factory=list)


def build_analytics(
    context: DraftContext,
    state: DraftState,
    *,
    candidates: Sequence[str] | None = None,
) -> DraftAnalytics:
    """Assemble the full analytics payload for one league state."""
    curves, markers = survival_curves(context, state, candidates=candidates)
    return DraftAnalytics(
        league_id=state.league_id,
        current_overall_pick=state.current_overall_pick,
        my_next_picks=markers,
        value_curves=value_curves(context, state),
        survival_curves=curves,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_analytics.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts && ../.venv/Scripts/python.exe -m ruff check . ../scripts
cd .. && git add backend/src/jaaffl/engine/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): build_analytics assembler for the dashboard feed"
```

---

## Task 4: `GET /analytics` endpoint

**Files:**

- Modify: `backend/src/jaaffl/api/app.py` (add after the `/state` route, before `return app`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`. Note `_primed_engine()` and `_named_paste_pick(...)` already
exist in that file — reuse them, do not redefine.

```python
def test_analytics_404_for_unknown_league(client: TestClient) -> None:
    res = client.get("/analytics", params={"league_id": "never-seen"})
    assert res.status_code == 404
    assert "unknown" in res.json()["detail"].lower()


def test_analytics_503_while_engine_context_is_warming(client: TestClient) -> None:
    """The board only needs events; analytics needs a precomputed context. Different gates —
    this is exactly why analytics is NOT folded into GET /state."""
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))
    res = client.get("/analytics", params={"league_id": "L1"})
    assert res.status_code == 503

    # ...and the board still renders from the same events.
    assert client.get("/state", params={"league_id": "L1"}).status_code == 200


def test_analytics_returns_both_series_when_primed(tmp_path: Path) -> None:
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))

    res = client.get("/analytics", params={"league_id": "L1"})
    assert res.status_code == 200
    body = res.json()
    assert body["league_id"] == "L1"
    assert {c["position"] for c in body["value_curves"]} <= {"QB", "RB", "WR", "TE"}
    assert body["survival_curves"]
    for curve in body["survival_curves"]:
        assert all(0.0 <= p["survival"] <= 1.0 for p in curve["points"])


def test_analytics_accepts_explicit_candidates(tmp_path: Path) -> None:
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))

    res = client.get("/analytics", params={"league_id": "L1", "candidates": "wr1,wr2"})
    assert res.status_code == 200
    assert [c["player_id"] for c in res.json()["survival_curves"]] == ["wr1", "wr2"]


def test_analytics_honours_origin_allowlist(client: TestClient) -> None:
    res = client.get(
        "/analytics", params={"league_id": "cbs-local"}, headers={"origin": "https://evil.example"}
    )
    assert res.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_api.py -k analytics -v`
Expected: FAIL — 404 Not Found from FastAPI (the route does not exist)

- [ ] **Step 3: Write minimal implementation**

In `backend/src/jaaffl/api/app.py`, add to the imports:

```python
from jaaffl.engine.analytics import DraftAnalytics, build_analytics
```

Add this route immediately after the `/state` route and before `return app`:

```python
    @app.get("/analytics", response_model=DraftAnalytics)
    def draft_analytics(
        request: Request, league_id: str, candidates: str | None = None
    ) -> DraftAnalytics:
        """Value + survival series for the dashboard analytics panels (§6).

        Same event gate and Origin allowlist as /state, PLUS a 503 when the engine context is still
        warming: the board needs only the pick events, while these series need the precomputed
        DraftContext. Keeping them on separate endpoints means a warming engine degrades the charts
        without blanking the board.

        ``candidates`` is an optional comma-separated id list — the dashboard passes the ids it
        already holds from the WS push so the survival lines match the ranked picks on screen.
        """
        require_allowed_origin(request)
        events = app.state.draft_log.events(league_id)
        if not events:
            known = app.state.warehouse.latest_cbs_snapshot(league_id) is not None
            raise HTTPException(
                status_code=409 if known else 404,
                detail=(
                    f"draft not started for league '{league_id}'"
                    if known
                    else f"unknown league '{league_id}'"
                ),
            )
        context = app.state.rec_engine.context_for(league_id)
        if context is None:
            raise HTTPException(
                status_code=503, detail=f"engine warming up for league '{league_id}'"
            )
        state = _resolve_state(fold_state(events), league_id)
        ids = [pid for pid in (candidates or "").split(",") if pid] or None
        return build_analytics(context, state, candidates=ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_api.py -k analytics -v`
Expected: PASS (5 tests)

Then run the whole backend suite to catch regressions:
Run: `cd backend && ../.venv/Scripts/python.exe -m pytest`
Expected: PASS (all tests; stretch tests skip without the `engine-stretch` extra)

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts && ../.venv/Scripts/python.exe -m ruff check . ../scripts
cd .. && git add backend/src/jaaffl/api/app.py backend/tests/test_api.py
git commit -m "feat(api): GET /analytics with its own engine-context 503 gate"
```

---

## Task 5: Shared Zod schema

**Files:**

- Create: `packages/shared/src/analytics.ts`
- Modify: `packages/shared/src/index.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/shared/tests/analytics.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { DraftAnalyticsSchema } from "../src/analytics";

const SAMPLE = {
  league_id: "L1",
  current_overall_pick: 5,
  my_next_picks: [7, 18],
  value_curves: [
    {
      position: "RB",
      full: [{ rank: 1, vor: 92.5, player_id: "rb0", name: "Bijan" }],
      remaining: [{ rank: 1, vor: 80.1, player_id: "rb1", name: "Breece" }],
    },
  ],
  survival_curves: [
    {
      player_id: "wr1",
      name: "Ja'Marr",
      position: "WR",
      points: [
        { pick: 5, survival: 0.98 },
        { pick: 6, survival: 0.91 },
      ],
    },
  ],
};

describe("DraftAnalyticsSchema", () => {
  it("parses a well-formed analytics payload", () => {
    const parsed = DraftAnalyticsSchema.safeParse(SAMPLE);
    expect(parsed.success).toBe(true);
  });

  it("tolerates absent optional display fields", () => {
    const parsed = DraftAnalyticsSchema.safeParse({
      ...SAMPLE,
      survival_curves: [{ player_id: "wr1", points: [] }],
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a payload missing its league id", () => {
    const { league_id: _omitted, ...rest } = SAMPLE;
    expect(DraftAnalyticsSchema.safeParse(rest).success).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @jaaffl/shared test`
Expected: FAIL — cannot resolve `../src/analytics`

- [ ] **Step 3: Write minimal implementation**

Create `packages/shared/src/analytics.ts`:

```ts
/**
 * Dashboard analytics feed (`GET /analytics`) — value curves + survival curves.
 *
 * Mirrors the backend view models in `backend/src/jaaffl/engine/analytics.py`. Like
 * `DraftBoardState` (see `state.ts`) and `CbsPageSnapshot`, it is deliberately OUTSIDE the E5
 * Pydantic⇄Zod parity surface (the strict nine in tests/parity.test.ts) — it is a client-render
 * convenience, not a cross-boundary contract the gate must police. The two sides are simple and
 * kept structurally aligned by hand. Do NOT add these to CONTRACT_SCHEMAS.
 */
import { z } from "zod";

/** One (rank, VOR) sample on a positional value curve. */
export const CurvePointSchema = z.object({
  rank: z.number(),
  vor: z.number(),
  player_id: z.string(),
  name: z.string().nullable().optional(),
});
export type CurvePoint = z.infer<typeof CurvePointSchema>;

/** A position's value curve: the original board (`full`) and what is still undrafted. */
export const PositionCurveSchema = z.object({
  position: z.string(),
  full: z.array(CurvePointSchema),
  remaining: z.array(CurvePointSchema),
});
export type PositionCurve = z.infer<typeof PositionCurveSchema>;

/** P(still on the board) at one overall pick number. */
export const SurvivalPointSchema = z.object({
  pick: z.number(),
  survival: z.number(),
});
export type SurvivalPoint = z.infer<typeof SurvivalPointSchema>;

/** One candidate's availability decay across the charted pick span. */
export const SurvivalCurveSchema = z.object({
  player_id: z.string(),
  name: z.string().nullable().optional(),
  position: z.string().nullable().optional(),
  points: z.array(SurvivalPointSchema),
});
export type SurvivalCurve = z.infer<typeof SurvivalCurveSchema>;

/** The whole analytics payload: both series plus the pick markers that anchor them. */
export const DraftAnalyticsSchema = z.object({
  league_id: z.string(),
  current_overall_pick: z.number(),
  my_next_picks: z.array(z.number()),
  value_curves: z.array(PositionCurveSchema),
  survival_curves: z.array(SurvivalCurveSchema),
});
export type DraftAnalytics = z.infer<typeof DraftAnalyticsSchema>;
```

Add to `packages/shared/src/index.ts`, alongside the existing `export * from "./state";` line:

```ts
export * from "./analytics";
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @jaaffl/shared test`
Expected: PASS (3 new tests; the existing parity test still passes because we did NOT touch `CONTRACT_SCHEMAS`)

Run: `pnpm -r typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/shared/src/analytics.ts packages/shared/src/index.ts packages/shared/tests/analytics.test.ts
git commit -m "feat(shared): Zod mirror for the analytics feed (outside the E5 parity gate)"
```

---

## Task 6: Pure SVG scaling math

**Files:**

- Create: `apps/web/lib/curve.ts`
- Test: `apps/web/lib/curve.test.ts`

Keeping the geometry out of the components makes it directly testable and keeps both panels small.

- [ ] **Step 1: Write the failing test**

Create `apps/web/lib/curve.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { survivalPolyline, valuePolyline } from "./curve";

const BOX = { width: 100, height: 50 };

describe("valuePolyline", () => {
  it("anchors rank 1 at the left edge and the deepest rank at the right", () => {
    const points = valuePolyline(
      [
        { rank: 1, vor: 100 },
        { rank: 3, vor: 0 },
      ],
      { ...BOX, maxRank: 3, minVor: 0, maxVor: 100 },
    );
    expect(points.split(" ")[0]).toBe("0.00,0.00");
    expect(points.split(" ")[1]).toBe("100.00,50.00");
  });

  it("returns an empty string for no points so the SVG renders nothing", () => {
    expect(valuePolyline([], { ...BOX, maxRank: 5, minVor: 0, maxVor: 1 })).toBe("");
  });

  it("does not divide by zero when every VOR is identical", () => {
    const points = valuePolyline(
      [
        { rank: 1, vor: 7 },
        { rank: 2, vor: 7 },
      ],
      { ...BOX, maxRank: 2, minVor: 7, maxVor: 7 },
    );
    expect(points).not.toContain("NaN");
  });
});

describe("survivalPolyline", () => {
  it("maps survival 1 to the top and 0 to the bottom", () => {
    const points = survivalPolyline(
      [
        { pick: 10, survival: 1 },
        { pick: 20, survival: 0 },
      ],
      { ...BOX, minPick: 10, maxPick: 20 },
    );
    expect(points).toBe("0.00,0.00 100.00,50.00");
  });

  it("does not divide by zero for a single-pick span", () => {
    const points = survivalPolyline([{ pick: 10, survival: 0.5 }], {
      ...BOX,
      minPick: 10,
      maxPick: 10,
    });
    expect(points).not.toContain("NaN");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @jaaffl/web test -- curve`
Expected: FAIL — cannot resolve `./curve`

- [ ] **Step 3: Write minimal implementation**

Create `apps/web/lib/curve.ts`:

```ts
/**
 * Pure geometry for the bespoke SVG analytics charts — no React, no DOM, no design tokens.
 *
 * Both panels draw with `<polyline points="x,y x,y ...">` in a fixed viewBox, so all either needs
 * is a domain→viewBox mapping. Keeping it here makes the maths directly unit-testable and keeps the
 * panel components small enough to read at a glance.
 */

export interface Box {
  width: number;
  height: number;
}

/** SVG y grows downward, so a HIGHER value maps to a SMALLER y. */
function project(value: number, min: number, span: number, height: number): number {
  return height - ((value - min) / span) * height;
}

/** Guard every denominator: a degenerate domain must render flat, never NaN. */
function safeSpan(span: number): number {
  return span === 0 ? 1 : span;
}

/** Map (rank, VOR) samples into a polyline. Rank 1 sits at x=0, `maxRank` at x=width. */
export function valuePolyline(
  points: readonly { rank: number; vor: number }[],
  opts: Box & { maxRank: number; minVor: number; maxVor: number },
): string {
  if (points.length === 0) return "";
  const rankSpan = safeSpan(opts.maxRank - 1);
  const vorSpan = safeSpan(opts.maxVor - opts.minVor);
  return points
    .map((p) => {
      const x = ((p.rank - 1) / rankSpan) * opts.width;
      const y = project(p.vor, opts.minVor, vorSpan, opts.height);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

/** Map (pick, survival) samples into a polyline. Survival is already 0..1. */
export function survivalPolyline(
  points: readonly { pick: number; survival: number }[],
  opts: Box & { minPick: number; maxPick: number },
): string {
  if (points.length === 0) return "";
  const pickSpan = safeSpan(opts.maxPick - opts.minPick);
  return points
    .map((p) => {
      const x = ((p.pick - opts.minPick) / pickSpan) * opts.width;
      const y = project(p.survival, 0, 1, opts.height);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

/** Fraction across the x-axis for a pick marker (0..1); clamped so it never escapes the box. */
export function pickOffset(pick: number, minPick: number, maxPick: number): number {
  const span = safeSpan(maxPick - minPick);
  return Math.min(1, Math.max(0, (pick - minPick) / span));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @jaaffl/web test -- curve`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/curve.ts apps/web/lib/curve.test.ts
git commit -m "feat(web): pure SVG scaling helpers for the analytics charts"
```

---

## Task 7: Client fetch + state wiring

**Files:**

- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/use-recs.ts`
- Test: `apps/web/lib/api.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `apps/web/lib/api.test.ts`:

```ts
describe("fetchAnalytics", () => {
  it("returns the parsed payload on 200", async () => {
    const body = {
      league_id: "L1",
      current_overall_pick: 5,
      my_next_picks: [7],
      value_curves: [],
      survival_curves: [],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body }),
    );
    const result = await fetchAnalytics("L1");
    expect(result.status).toBe(200);
    expect(result.analytics?.league_id).toBe("L1");
  });

  it("surfaces a 503 as a status with no analytics rather than throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    const result = await fetchAnalytics("L1");
    expect(result).toEqual({ status: 503, analytics: null });
  });

  it("maps an unreachable backend to status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(await fetchAnalytics("L1")).toEqual({ status: 0, analytics: null });
  });

  it("treats an unparseable 200 body as empty, not an exception", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ nope: true }) }),
    );
    expect(await fetchAnalytics("L1")).toEqual({ status: 200, analytics: null });
  });

  it("forwards candidate ids so the curves match the ranked picks on screen", async () => {
    const spy = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ nope: true }) });
    vi.stubGlobal("fetch", spy);
    await fetchAnalytics("L1", ["a", "b"]);
    expect(spy.mock.calls[0][0]).toContain("candidates=a%2Cb");
  });
});
```

Add `fetchAnalytics` to the existing import from `./api` at the top of that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @jaaffl/web test -- api`
Expected: FAIL — `fetchAnalytics is not a function`

- [ ] **Step 3: Write minimal implementation**

In `apps/web/lib/api.ts`, add `DraftAnalytics` + `DraftAnalyticsSchema` to the existing
`@jaaffl/shared` import, then append:

```ts
export interface AnalyticsResult {
  /** HTTP status so panels can distinguish 404 / 409 / 503 (engine warming) from a 200.
   * 0 means the fetch threw (backend down) — panels keep their last series, never throw. */
  status: number;
  analytics: DraftAnalytics | null;
}

/**
 * Status-aware GET /analytics: the value + survival series for the war-room panels. Mirrors
 * fetchState's honesty contract. `candidates` are the ids already on screen from the WS push, so
 * the survival lines always match the ranked picks rendered above them.
 */
export async function fetchAnalytics(
  leagueId: string,
  candidates?: readonly string[],
): Promise<AnalyticsResult> {
  const params = new URLSearchParams({ league_id: leagueId });
  if (candidates && candidates.length > 0) params.set("candidates", candidates.join(","));
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/analytics?${params.toString()}`, { cache: "no-store" });
  } catch {
    return { status: 0, analytics: null };
  }
  if (!res.ok) return { status: res.status, analytics: null };
  try {
    const parsed = DraftAnalyticsSchema.safeParse(await res.json());
    return { status: 200, analytics: parsed.success ? parsed.data : null };
  } catch {
    return { status: 200, analytics: null }; // 200 but an unparseable body → no series, not a throw
  }
}
```

In `apps/web/components/use-recs.ts`, make five edits:

1. Add to the `@jaaffl/shared` type import: `DraftAnalytics`.
2. Add to the `../lib/api` import: `fetchAnalytics as realFetchAnalytics` and `type AnalyticsResult`.
3. Extend the interfaces and initial state:

```ts
export interface DraftRoomApi {
  subscribeRecs: typeof realSubscribeRecs;
  getRecommendation: (leagueId: string) => Promise<RecommendationResult>;
  fetchLeague: (leagueId: string) => Promise<LeagueSettings | null>;
  fetchState: (leagueId: string) => Promise<StateResult>;
  fetchAnalytics: (leagueId: string, candidates?: readonly string[]) => Promise<AnalyticsResult>;
}

const REAL_API: DraftRoomApi = {
  subscribeRecs: realSubscribeRecs,
  getRecommendation: realGetRecommendation,
  fetchLeague: realFetchLeague,
  fetchState: realFetchState,
  fetchAnalytics: realFetchAnalytics,
};
```

Add `analytics: DraftAnalytics | null;` to `DraftRoomState`, `analytics: null,` to `INITIAL`, and a
new action + reducer case:

```ts
  | { type: "analytics"; analytics: DraftAnalytics | null }
```

```ts
    case "analytics":
      // Keep the last series on a null result (transient offline / warming engine) so the charts
      // do not blank mid-draft — mirrors how "board" preserves the last board.
      return { ...state, analytics: action.analytics ?? state.analytics };
```

4. Inside the effect, add a refresher beside `refreshBoard` and call it in both places:

```ts
const refreshAnalytics = (candidates?: readonly string[]) =>
  void api.fetchAnalytics(leagueId, candidates).then((result) => {
    if (active) dispatch({ type: "analytics", analytics: result.analytics });
  });
```

5. Call `refreshAnalytics();` right after the existing `refreshBoard();` hydrate call, and inside
   `onRecommendation` pass the ids already on screen:

```ts
      onRecommendation: (recommendation) => {
        if (!active) return;
        dispatch({ type: "rec", recommendation, at: Date.now() });
        refreshBoard();
        refreshAnalytics(recommendation.ranked.slice(0, 6).map((p) => p.player_id));
      },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @jaaffl/web test -- api`
Expected: PASS (5 new tests)

Run: `pnpm -r typecheck`
Expected: PASS

Run: `pnpm --filter @jaaffl/web test`
Expected: PASS — existing `dashboard.test.tsx` still passes because `DraftRoomApi` is injected as
`Partial<DraftRoomApi>` and the real `fetchAnalytics` degrades to `{status: 0}` under a stubbed fetch.
If any existing dashboard test now fails on an unstubbed fetch, add
`fetchAnalytics: async () => ({ status: 503, analytics: null })` to that test's `api` override.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/api.ts apps/web/lib/api.test.ts apps/web/components/use-recs.ts
git commit -m "feat(web): fetchAnalytics + refresh-on-push wiring for the analytics panels"
```

---

## Task 8: Value-curve panel

**Files:**

- Create: `apps/web/components/value-curve-panel.tsx`
- Test: `apps/web/components/value-curve-panel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/components/value-curve-panel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DraftAnalytics } from "@jaaffl/shared";

import { ValueCurvePanel } from "./value-curve-panel";

const ANALYTICS: DraftAnalytics = {
  league_id: "L1",
  current_overall_pick: 3,
  my_next_picks: [7, 18],
  value_curves: [
    {
      position: "RB",
      full: [
        { rank: 1, vor: 90, player_id: "rb0", name: "Bijan" },
        { rank: 2, vor: 40, player_id: "rb1", name: "Breece" },
      ],
      remaining: [{ rank: 1, vor: 40, player_id: "rb1", name: "Breece" }],
    },
    {
      position: "WR",
      full: [
        { rank: 1, vor: 70, player_id: "wr0", name: "Ja'Marr" },
        { rank: 2, vor: 65, player_id: "wr1", name: "Justin" },
      ],
      remaining: [
        { rank: 1, vor: 70, player_id: "wr0", name: "Ja'Marr" },
        { rank: 2, vor: 65, player_id: "wr1", name: "Justin" },
      ],
    },
  ],
  survival_curves: [],
};

describe("ValueCurvePanel", () => {
  it("renders a toggle button per charted position", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByRole("button", { name: /RB/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /WR/ })).toBeInTheDocument();
  });

  it("selects the first position by default and marks it pressed", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByRole("button", { name: /RB/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /WR/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("switches the charted position when a chip is clicked", async () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    await userEvent.click(screen.getByRole("button", { name: /WR/ }));
    expect(screen.getByRole("button", { name: /WR/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /WR value curve/i })).toBeInTheDocument();
  });

  it("describes the curve for screen readers, never colour-alone", () => {
    render(<ValueCurvePanel analytics={ANALYTICS} />);
    const chart = screen.getByRole("img", { name: /RB value curve/i });
    expect(chart).toHaveAccessibleName(/1 of 2 taken/i);
  });

  it("shows an honest empty state when the engine is still warming", () => {
    render(<ValueCurvePanel analytics={null} />);
    expect(screen.getByText(/warm up with the engine/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @jaaffl/web test -- value-curve`
Expected: FAIL — cannot resolve `./value-curve-panel`

- [ ] **Step 3: Write minimal implementation**

Create `apps/web/components/value-curve-panel.tsx`:

```tsx
"use client";

import { useState, type ReactElement } from "react";

import type { DraftAnalytics, PositionCurve } from "@jaaffl/shared";

import { valuePolyline } from "../lib/curve";

const BOX = { width: 320, height: 120 };

/** Describe the curve in words — the chart's accessible name, never colour-alone (WCAG 1.4.1). */
function describe(curve: PositionCurve): string {
  const best = curve.remaining[0];
  // CORRECTED post-review: `remaining` is NOT a subset of `full` — the backend caps BOTH
  // independently at CURVE_DEPTH (36), so once a position pool exceeds 36 (RB/WR always do),
  // drafting the top players just backfills `remaining` from rank 37+. Subtracting lengths then
  // reports ~0 taken no matter how many are gone. Count by identity instead.
  const remainingIds = new Set(curve.remaining.map((p) => p.player_id));
  const taken = curve.full.filter((p) => !remainingIds.has(p.player_id)).length;
  if (!best) return `${curve.position} value curve: every charted player is drafted.`;
  const cliff = curve.remaining[1] ? best.vor - curve.remaining[1].vor : 0;
  return (
    `${curve.position} value curve: best remaining ${best.name ?? best.player_id} at ` +
    `${best.vor.toFixed(0)} points over replacement, ` +
    `${cliff.toFixed(0)} ahead of the next, ${taken} of ${curve.full.length} taken.`
  );
}

/**
 * Positional value curve (§6). VOR against positional rank, one position at a time: the SOLID line
 * is what is still available, the GHOST line behind it is the original preseason board — the gap
 * between them is the positional run. The dashed rule is replacement level (VOR = 0).
 */
export function ValueCurvePanel({ analytics }: { analytics: DraftAnalytics | null }): ReactElement {
  const curves = analytics?.value_curves ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const curve = curves.find((c) => c.position === selected) ?? curves[0];

  if (!curve) {
    return (
      <section className="panel card" aria-labelledby="vc-h">
        <div className="panel-h">
          <h3 className="panel-title" id="vc-h">
            Value curves
          </h3>
        </div>
        <p className="muted">Value curves warm up with the engine.</p>
      </section>
    );
  }

  const all = [...curve.full, ...curve.remaining];
  const maxRank = Math.max(1, ...curve.full.map((p) => p.rank));
  const maxVor = Math.max(...all.map((p) => p.vor), 0);
  const minVor = Math.min(...all.map((p) => p.vor), 0);
  const scale = { ...BOX, maxRank, minVor, maxVor };
  // Replacement level (VOR = 0) in viewBox coordinates.
  const zeroY = BOX.height - ((0 - minVor) / (maxVor - minVor || 1)) * BOX.height;

  return (
    <section className="panel card" aria-labelledby="vc-h">
      <div className="panel-h">
        <h3 className="panel-title" id="vc-h">
          Value curves
        </h3>
        <span className="panel-note">points over replacement</span>
      </div>

      <div className="vc-chips" role="group" aria-label="Charted position">
        {curves.map((c) => (
          <button
            key={c.position}
            type="button"
            className="vc-chip"
            aria-pressed={c.position === curve.position}
            onClick={() => setSelected(c.position)}
            style={
              { "--chip-hue": `var(--pos-${c.position.toLowerCase()})` } as React.CSSProperties
            }
          >
            {c.position}
          </button>
        ))}
      </div>

      <svg
        className="vc-chart"
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-label={describe(curve)}
        preserveAspectRatio="none"
      >
        <line
          className="vc-replacement"
          x1="0"
          y1={zeroY}
          x2={BOX.width}
          y2={zeroY}
          strokeDasharray="4 3"
        />
        <polyline className="vc-ghost" points={valuePolyline(curve.full, scale)} />
        <polyline
          className="vc-line"
          points={valuePolyline(curve.remaining, scale)}
          style={{ stroke: `var(--pos-${curve.position.toLowerCase()})` }}
        />
      </svg>

      <p className="vc-legend muted">
        Solid = still available · faint = preseason board · dashed = replacement
      </p>
    </section>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @jaaffl/web test -- value-curve`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/value-curve-panel.tsx apps/web/components/value-curve-panel.test.tsx
git commit -m "feat(web): value-curve panel with position toggle and remaining-vs-board ghost"
```

---

## Task 9: Survival-curve panel

**Files:**

- Create: `apps/web/components/survival-curve-panel.tsx`
- Test: `apps/web/components/survival-curve-panel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/components/survival-curve-panel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DraftAnalytics } from "@jaaffl/shared";

import { SurvivalCurvePanel } from "./survival-curve-panel";

const ANALYTICS: DraftAnalytics = {
  league_id: "L1",
  current_overall_pick: 10,
  my_next_picks: [14, 26],
  value_curves: [],
  survival_curves: [
    {
      player_id: "wr0",
      name: "Ja'Marr",
      position: "WR",
      points: [
        { pick: 10, survival: 1 },
        { pick: 14, survival: 0.82 },
        { pick: 26, survival: 0.2 },
      ],
    },
    {
      player_id: "rb0",
      name: "Bijan",
      position: "RB",
      points: [
        { pick: 10, survival: 1 },
        { pick: 14, survival: 0.3 },
        { pick: 26, survival: 0.02 },
      ],
    },
  ],
};

describe("SurvivalCurvePanel", () => {
  it("lists every candidate with its survival at your next pick", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByText("Ja'Marr")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
  });

  it("pairs every survival tier with a WORD, never colour alone", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByText(/can wait/i)).toBeInTheDocument();
    expect(screen.getByText(/take now/i)).toBeInTheDocument();
  });

  it("renders one marker per upcoming pick", () => {
    const { container } = render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(container.querySelectorAll(".sc-marker")).toHaveLength(2);
  });

  it("gives the chart an accessible description", () => {
    render(<SurvivalCurvePanel analytics={ANALYTICS} />);
    expect(screen.getByRole("img", { name: /survival/i })).toBeInTheDocument();
  });

  it("shows an honest empty state before the draft starts", () => {
    render(<SurvivalCurvePanel analytics={null} />);
    expect(screen.getByText(/once the draft starts/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @jaaffl/web test -- survival-curve`
Expected: FAIL — cannot resolve `./survival-curve-panel`

- [ ] **Step 3: Write minimal implementation**

Create `apps/web/components/survival-curve-panel.tsx`:

```tsx
"use client";

import type { ReactElement } from "react";

import {
  type DraftAnalytics,
  formatPct,
  type SurvivalCurve,
  survivalOutlook,
} from "@jaaffl/shared";

import { pickOffset, survivalPolyline } from "../lib/curve";

const BOX = { width: 640, height: 180 };

/** Survival at your next pick — the number the legend reports and the tier it maps to. */
function atPick(curve: SurvivalCurve, pick: number | undefined): number {
  if (pick == null) return curve.points[curve.points.length - 1]?.survival ?? 0;
  const exact = curve.points.find((p) => p.pick === pick);
  return exact?.survival ?? curve.points[curve.points.length - 1]?.survival ?? 0;
}

/**
 * Survival curves (§6.3 / §3.4): P(each candidate is still on the board) across upcoming picks,
 * with dashed markers at YOUR next picks — read from the real entered draft order, never inferred.
 * The curve SHAPE is the point: flat to your marker means you can wait; a cliff before it means
 * take him now. Tier words come from the shared survivalOutlook, so this panel and the overlay can
 * never disagree about who is scarce.
 */
export function SurvivalCurvePanel({
  analytics,
}: {
  analytics: DraftAnalytics | null;
}): ReactElement {
  const curves = analytics?.survival_curves ?? [];
  const markers = analytics?.my_next_picks ?? [];

  if (curves.length === 0) {
    return (
      <section className="panel card sc-panel" aria-labelledby="sc-h">
        <div className="panel-h">
          <h3 className="panel-title" id="sc-h">
            Survival curves
          </h3>
        </div>
        <p className="muted">Survival curves appear once the draft starts.</p>
      </section>
    );
  }

  const picks = curves[0]!.points.map((p) => p.pick);
  const minPick = Math.min(...picks);
  const maxPick = Math.max(...picks);
  const nextPick = markers[0];

  return (
    <section className="panel card sc-panel" aria-labelledby="sc-h">
      <div className="panel-h">
        <h3 className="panel-title" id="sc-h">
          Survival curves
        </h3>
        <span className="panel-note">
          {markers.length > 0 ? `your picks: ${markers.join(", ")}` : "draft order unknown"}
        </span>
      </div>

      <svg
        className="sc-chart"
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-label={`Survival to each upcoming pick for ${curves
          .map((c) => `${c.name ?? c.player_id} ${formatPct(atPick(c, nextPick))}`)
          .join(", ")}`}
        preserveAspectRatio="none"
      >
        {markers.map((pick) => {
          const x = pickOffset(pick, minPick, maxPick) * BOX.width;
          return (
            <line
              className="sc-marker"
              key={pick}
              x1={x}
              y1={0}
              x2={x}
              y2={BOX.height}
              strokeDasharray="4 3"
            />
          );
        })}
        {curves.map((curve) => (
          <polyline
            className="sc-line"
            key={curve.player_id}
            points={survivalPolyline(curve.points, { ...BOX, minPick, maxPick })}
            style={{ stroke: `var(--pos-${(curve.position ?? "wr").toLowerCase()})` }}
          />
        ))}
      </svg>

      <ul className="sc-legend" role="list">
        {curves.map((curve) => {
          const probability = atPick(curve, nextPick);
          const outlook = survivalOutlook(probability);
          return (
            <li className="sc-legend-row" key={curve.player_id}>
              <span
                className="sc-swatch"
                aria-hidden="true"
                style={{ background: `var(--pos-${(curve.position ?? "wr").toLowerCase()})` }}
              />
              <span className="sc-name">{curve.name ?? curve.player_id}</span>
              <span className="mono">{formatPct(probability)}</span>
              <span className={`stat-pill ${outlook.statusClass}`}>
                {outlook.glyph} {outlook.word}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @jaaffl/web test -- survival-curve`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/survival-curve-panel.tsx apps/web/components/survival-curve-panel.test.tsx
git commit -m "feat(web): multi-line survival-curve panel with real-order pick markers"
```

---

## Task 10: Layout, styles, docs, and final verification

**Files:**

- Modify: `apps/web/components/dashboard.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `ROADMAP.md`

Reminder: do **not** edit `design/tokens/draft-room.css` (drift-guarded — see the context section).

- [ ] **Step 1: Wire both panels into the dashboard**

In `apps/web/components/dashboard.tsx`, add the imports:

```tsx
import { SurvivalCurvePanel } from "./survival-curve-panel";
import { ValueCurvePanel } from "./value-curve-panel";
```

Add the value curve to the analytics rail, after `<TierLadder .../>`:

```tsx
<ValueCurvePanel analytics={state.analytics} />
```

Add the survival chart as a full-width row, immediately after `<BoardPanel state={state.boardState} />`:

```tsx
<SurvivalCurvePanel analytics={state.analytics} />
```

- [ ] **Step 2: Add the chart styles**

Append to `apps/web/app/globals.css`:

```css
/* ---- Analytics charts (dashboard-only; the canonical tokens live in design/tokens/
   draft-room.css and are drift-guarded, so these consumers live here instead). ---- */

.vc-chips {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.vc-chip {
  font: inherit;
  font-size: var(--fs-xxs);
  letter-spacing: 0.04em;
  padding: 2px 10px;
  border-radius: var(--r-xs);
  border: 1px solid var(--hairline);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}

.vc-chip[aria-pressed="true"] {
  border-color: var(--chip-hue);
  box-shadow: inset 0 -2px 0 var(--chip-hue);
}

.vc-chart,
.sc-chart {
  width: 100%;
  height: auto;
  overflow: visible;
}

.vc-line,
.sc-line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
}

.vc-ghost {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.5;
  opacity: 0.22;
}

.vc-replacement,
.sc-marker {
  stroke: var(--ink);
  opacity: 0.45;
}

.vc-legend {
  margin-top: 6px;
  font-size: var(--fs-xxs);
}

.sc-panel {
  margin-top: 16px;
}

.sc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
  padding: 0;
  list-style: none;
}

.sc-legend-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sc-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}

/* The charts are static; nothing animates. Kept explicit so future transitions inherit it. */
@media (prefers-reduced-motion: reduce) {
  .vc-line,
  .sc-line,
  .vc-ghost {
    transition: none;
  }
}
```

- [ ] **Step 3: Run the full verification suite**

```bash
cd backend && ../.venv/Scripts/python.exe -m ruff format . ../scripts && ../.venv/Scripts/python.exe -m ruff check . ../scripts && ../.venv/Scripts/python.exe -m pytest
```

Expected: ruff clean; pytest all PASS

```bash
pnpm -r typecheck && pnpm -r test
```

Expected: typecheck clean; all suites PASS (including the untouched `overlay-tokens` drift guard and the E5 `parity` gate)

- [ ] **Step 4: Update the roadmap**

In `ROADMAP.md`, replace the Stage 6 dashboard line:

```markdown
- [x] Next.js dashboard: board analytics, manager tendencies, scenarios (`apps/web`) _(live
      recommendation feed, **draft board & pick-log** via `GET /state`, and the **value-curve +
      survival-curve** analytics panels via `GET /analytics` — all done; manager-tendency panel
      deferred until ≥1 recorded draft accrues `manager_tendencies` rows)_
```

And the AG Grid line:

```markdown
- [x] **AG Grid removed by design** (deep-research: overkill for a 204-cell static board);
      distributions/trends render as **bespoke accessible SVG** (no ECharts dependency)
```

- [ ] **Step 5: Commit and open the PR**

```bash
git add apps/web/components/dashboard.tsx apps/web/app/globals.css ROADMAP.md
git commit -m "feat(web): place analytics panels in the war room + chart styles"
git push -u origin HEAD
gh pr create --title "Dashboard analytics panels: value curves + survival curves" --body "$(cat <<'EOF'
Completes the last non-owner-gated Stage 6 item.

## What
- `engine/analytics.py` — pure series builders over the cached `DraftContext`
- `GET /analytics` — its own engine-context 503 gate, so a warming engine degrades the charts without blanking the board
- Value-curve panel (position toggle; remaining solid over preseason-board ghost)
- Survival-curve panel (multi-line decay; dashed markers at your real upcoming picks)

## Notes
- No new dependencies; bespoke accessible SVG over the existing design tokens
- Survival reuses `opponents.pick_probabilities` incl. R3 board conditioning, so the chart and the engine never disagree
- Pick markers come from `next_overall_pick` (real entered order) — `config/league.json` forbids inferring snake order
- New Zod schema is deliberately outside the E5 parity gate, per the `state.ts` precedent
- Manager-tendency panel deferred: `manager_tendencies` accrues across drafts and this is the first tracked one

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Watch CI to green**

```bash
gh pr checks --watch
```

Expected: all checks pass. Do not call the work done until CI is green.

---

## Self-review

**Spec coverage:** §2 decisions → Tasks 8/9 (bespoke SVG, toggle, ghost, multi-line) and Task 4 (endpoint). §3.1 separate-endpoint rationale → tested in Task 4 (`test_analytics_503_while_engine_context_is_warming` asserts the board still 200s). §4.1 value curves → Task 1; survival + R3 conditioning + real-order markers → Task 2; assembler → Task 3. §4.2 endpoint incl. optional `candidates` → Task 4. §4.3 shared schema outside the parity gate → Task 5. §5.1/§5.2 panels → Tasks 8/9; §5.3 layout → Task 10. §6 degraded states → Task 7 (status mapping, keep-last-on-null) and Tasks 8/9 (empty states). §7 out-of-scope recorded in the ROADMAP edit. §8 testing → every task is test-first.

**Placeholder scan:** No TBD/TODO. Every code step carries complete, runnable code. No "similar to Task N" references.

**Type consistency:** `DraftAnalytics.value_curves`/`survival_curves`/`my_next_picks` are used with identical names in the Pydantic model (Task 3), the Zod mirror (Task 5), and both panels (Tasks 8/9). `survival_curves` returns `tuple[list[SurvivalCurve], list[int]]` in Task 2 and is destructured that way in Task 3. `fetchAnalytics` returns `AnalyticsResult {status, analytics}` in Task 7 and is consumed with those field names in the reducer. `valuePolyline`/`survivalPolyline`/`pickOffset` are defined in Task 6 and called with matching signatures in Tasks 8/9.
