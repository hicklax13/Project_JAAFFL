# Live $0 recs — player universe + drafted-pick name resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip `GET /recommendation` from a graceful 503 to a real 200 on FREE nflverse data by implementing `NflreadpyProvider.players()`, and keep those live recs correct by resolving name-only manual-paste picks to canonical player_ids so the engine masks drafted players.

**Architecture:** `players()` loads the FREE nflverse universe from `load_ff_playerids()` (canonical `gsis:<id>` ids, aligned by construction with the crosswalk seed + `rankings()` so the precompute join can't silently empty out). A new pure `ingest/resolve.resolve_pick_ids` seam — wired into the two API sites that feed the engine — fills `player_id` for name-only picks via the existing `crosswalk.resolve_name`, upstream of the frozen `recommend()` hot path. `recommend()`, `fold_state`, the domain models, and the E5 contract are untouched.

**Tech Stack:** Python 3.12, Pydantic v2, Polars (nflreadpy), rapidfuzz, FastAPI, pytest.

---

## Environment — how to run tests in this worktree

The root `.venv` has an editable install pointing at *main's* `backend/src`. To test **worktree** code, prepend the worktree's `backend/src` to `PYTHONPATH` (this shadows the editable `.pth`). Every test command in this plan is:

```bash
WT=/c/Users/conno/Project_JAAFFL/Project_JAAFFL/.claude/worktrees/live-recs-player-universe
PY=/c/Users/conno/Project_JAAFFL/Project_JAAFFL/.venv/Scripts/python.exe
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest <args>
```

Baseline before starting: **288 backend tests pass**. Do not regress it.

Every commit message ends with:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

## Task 1: Shared `player_from_playerid_row` helper + refactor `seed_from_playerids`

Single source of truth for `load_ff_playerids()` row → canonical `Player`, used by both the crosswalk seed and (Task 2) the universe loader — so the seeded ids and the loaded universe can never diverge.

**Files:**
- Modify: `backend/src/jaaffl/data/crosswalk.py` (add helper; refactor `seed_from_playerids`)
- Test: `backend/tests/test_crosswalk.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_crosswalk.py` (update the crosswalk import line to include `player_from_playerid_row`):

```python
# at top: from jaaffl.data.crosswalk import Crosswalk, name_norm, player_from_playerid_row, team_norm

def test_player_from_playerid_row_maps_canonical() -> None:
    p = player_from_playerid_row(playerid_row())
    assert p is not None
    assert p.player_id == "gsis:00-0034796"
    assert p.name == "CeeDee Lamb"
    assert p.position == "WR"  # Position is a StrEnum
    assert p.nfl_team == "DAL"


def test_player_from_playerid_row_skips_without_gsis() -> None:
    assert player_from_playerid_row(playerid_row(gsis_id=None)) is None


def test_player_from_playerid_row_skips_non_league_position() -> None:
    # db_playerids carries IDP codes (DE/DT/CB/S/...) outside this league's Position set.
    assert player_from_playerid_row(playerid_row(gsis_id="00-idp", position="DE")) is None


def test_player_from_playerid_row_falls_back_to_canonical_name() -> None:
    p = player_from_playerid_row(playerid_row(name=None))
    assert p is not None and p.name == "gsis:00-0034796"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_crosswalk.py -k player_from_playerid_row -v
```
Expected: FAIL — `ImportError: cannot import name 'player_from_playerid_row'`.

- [ ] **Step 3: Add the helper and refactor the seed**

In `backend/src/jaaffl/data/crosswalk.py`, add this module-level function (place it after `name_norm`, before `class Crosswalk`):

```python
def player_from_playerid_row(row: Mapping) -> Player | None:
    """Map one ``load_ff_playerids()`` row to a canonical :class:`Player`, or ``None`` to skip.

    Canonical id = the stable ``gsis:<gsis_id>``. Rows without a gsis id, or whose position is
    outside this league's :data:`_VALID_POSITIONS` (db_playerids carries DE/DT/CB/S/... IDP codes),
    are skipped. This is the ONE mapper shared by :meth:`Crosswalk.seed_from_playerids` and
    ``NflreadpyProvider.players`` so the seeded ids and the loaded universe can never diverge.
    Returns ``None`` on a row that fails :class:`Player` validation, so one bad row can't abort a batch.
    """
    gsis = _clean(row.get("gsis_id"))
    position = str(row.get("position") or "").upper()
    if gsis is None or position not in _VALID_POSITIONS:
        return None
    canonical = f"gsis:{gsis}"
    try:
        return Player(
            player_id=canonical,
            name=str(row.get("name") or canonical),
            position=position,
            nfl_team=_clean(row.get("team")),
        )
    except ValidationError:
        return None
```

Replace the body of `seed_from_playerids` (keep the docstring) with the helper-based version:

```python
    def seed_from_playerids(self, rows: Iterable[Mapping]) -> int:
        """<keep the existing docstring verbatim>"""
        conn = open_app_db(self.db_path)
        seeded = 0
        try:
            for row in rows:
                player = player_from_playerid_row(row)
                if player is None:
                    continue
                self._upsert_player(conn, player)
                for source, column in _SEED_SOURCES.items():
                    source_id = _clean(row.get(column))
                    if source_id is not None:
                        self._link(conn, source, source_id, player.player_id, method="deterministic")
                seeded += 1
            conn.commit()
        finally:
            conn.close()
        return seeded
```

- [ ] **Step 4: Run the new tests + the full crosswalk suite (no regressions)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_crosswalk.py -v
```
Expected: PASS — the 4 new tests plus every existing crosswalk test (the seed refactor is behavior-preserving).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/src/jaaffl/data/crosswalk.py backend/tests/test_crosswalk.py && git commit -m "refactor(crosswalk): shared player_from_playerid_row mapper for seed + universe

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `NflreadpyProvider.players(season)`

**Files:**
- Modify: `backend/src/jaaffl/providers/nflverse.py` (implement `players`)
- Test: `backend/tests/test_provider_nflverse.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_provider_nflverse.py` (add `Position` to the domain import: `from jaaffl.domain import Player, Position`):

```python
def test_players_maps_playerids_to_domain_players(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pl.DataFrame(
        [
            _playerid_row(),  # CeeDee Lamb WR DAL
            _playerid_row(gsis_id="00-0035676", name="Bijan Robinson", position="RB", team="ATL"),
        ]
    )
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    universe = NflreadpyProvider().players(2026)
    assert {p.player_id for p in universe} == {"gsis:00-0034796", "gsis:00-0035676"}
    lamb = next(p for p in universe if p.player_id == "gsis:00-0034796")
    assert (lamb.name, lamb.position, lamb.nfl_team) == ("CeeDee Lamb", Position.WR, "DAL")


def test_players_skips_rows_without_gsis_or_bad_position(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pl.DataFrame(
        [
            _playerid_row(),  # kept
            _playerid_row(gsis_id=None, name="No GSIS"),  # skipped: no gsis
            _playerid_row(gsis_id="00-idp", position="DE", name="Edge"),  # skipped: IDP pos
        ]
    )
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    # One good row survives; the two bad rows are skipped without aborting the batch.
    assert [p.player_id for p in NflreadpyProvider().players(2026)] == ["gsis:00-0034796"]


def test_players_ids_match_seed_canonical(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    """The universe id equals the seeded canonical id equals what rankings() resolves to."""
    df = pl.DataFrame([_playerid_row()])
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    provider = NflreadpyProvider(crosswalk=cx)
    provider.seed_crosswalk()
    universe = provider.players(2026)
    assert universe[0].player_id == cx.resolve("fantasypros", "17246") == "gsis:00-0034796"


def test_players_raises_provider_error_without_data_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "nflreadpy", None)  # force ImportError on `import nflreadpy`
    with pytest.raises(ProviderError):
        NflreadpyProvider().players(2026)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_provider_nflverse.py -k players -v
```
Expected: FAIL — `players()` raises `NotImplementedError` (base class stub).

- [ ] **Step 3: Implement `players`**

In `backend/src/jaaffl/providers/nflverse.py`, add this method to `NflreadpyProvider` (after `rankings`, near `seed_crosswalk`):

```python
    def players(self, season: int) -> list[Player]:
        """The FREE nflverse player universe as domain ``Player``s (canonical ``gsis:<gsis_id>``).

        Loads the DynastyProcess ``ff_playerids`` dimension — the SAME source as
        :meth:`seed_crosswalk`, so the universe ids are exactly the ids the seed + :meth:`rankings`
        resolve to; the precompute join cannot silently empty out. Rows without a gsis id or with a
        non-league position (incl. team DSTs, which have no gsis) are SKIPPED and logged, mirroring
        :meth:`rankings`. ``season`` is accepted for protocol compatibility but does not filter this
        dimension. Raises :class:`ProviderError` when the ``data`` extra is missing.
        """
        from jaaffl.data.crosswalk import player_from_playerid_row

        frame = _import_nflreadpy().load_ff_playerids()
        universe: list[Player] = []
        skipped = 0
        for row in frame.iter_rows(named=True):
            player = player_from_playerid_row(row)
            if player is None:
                skipped += 1
                continue
            universe.append(player)
        if skipped:
            log.info("nflverse_players_unresolved_skipped", skipped=skipped, kept=len(universe))
        return universe
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_provider_nflverse.py -v
```
Expected: PASS — all players tests plus the existing rankings/seed tests.

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/src/jaaffl/providers/nflverse.py backend/tests/test_provider_nflverse.py && git commit -m "feat(nflverse): implement players() — the FREE nflverse universe loader

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Precompute loader flip (503 → real universe)

Proves the keystone: with `players()` implemented, `_registry_player_loader` returns a real universe instead of `{}` (no more `NotImplementedError → {}` swallow). Test-only.

**Files:**
- Test: `backend/tests/test_precompute.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_precompute.py`:

```python
def test_registry_player_loader_uses_real_players_method(monkeypatch, tmp_path) -> None:
    """The 503→universe flip at the loader seam: real NflreadpyProvider.players() (fake nflreadpy)
    yields a real universe dict through _registry_player_loader."""
    import polars as pl

    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import _registry_player_loader
    from jaaffl.providers.nflverse import NflreadpyProvider
    from tests.test_providers import fake_nflreadpy

    Warehouse(tmp_path).init()
    row = {
        "gsis_id": "00-0034796", "cbs_id": "2181292", "pfr_id": "LambCe00", "sleeper_id": "6786",
        "espn_id": "4241389", "yahoo_id": "32692", "fantasypros_id": "17246",
        "name": "CeeDee Lamb", "position": "WR", "team": "DAL",
    }
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: pl.DataFrame([row]))
    provider = NflreadpyProvider(crosswalk=Crosswalk(tmp_path / "app.sqlite"))
    universe = _registry_player_loader([provider])(2026)
    assert set(universe) == {"gsis:00-0034796"}
    assert universe["gsis:00-0034796"].name == "CeeDee Lamb"
```

- [ ] **Step 2: Run to verify it passes (Task 2 already made it green)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_precompute.py::test_registry_player_loader_uses_real_players_method -v
```
Expected: PASS. (This is a regression guard on the keystone flip — it would have FAILED before Task 2, when `players()` raised `NotImplementedError` and the loader swallowed it to `{}`.)

- [ ] **Step 3: Run the full precompute suite (no regressions)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_precompute.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd "$WT" && git add backend/tests/test_precompute.py && git commit -m "test(precompute): guard the 503->universe flip through the real players() loader

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Defer the rapidfuzz import in `_best_fuzzy_match`

The Task-6 resolution runs on every `GET /recommendation`. In a base ($0, no-`data`-extra) install a name-only pick would reach `_best_fuzzy_match`, which imports `rapidfuzz` before checking candidates → `ImportError` → 500. Defer the import so an empty players table returns `None` first.

**Files:**
- Modify: `backend/src/jaaffl/data/crosswalk.py` (`_best_fuzzy_match`)
- Test: `backend/tests/test_crosswalk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_crosswalk.py`:

```python
def test_resolve_name_on_empty_table_returns_none_without_rapidfuzz(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    """A base ($0) install with an unseeded players table must resolve to None without importing
    rapidfuzz (which the data extra provides) — else the API resolution path would 500."""
    import sys

    monkeypatch.setitem(sys.modules, "rapidfuzz", None)  # force ImportError if imported
    assert cx.resolve_name("Nobody Here", "SF", "WR") is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_crosswalk.py::test_resolve_name_on_empty_table_returns_none_without_rapidfuzz -v
```
Expected: FAIL — `ImportError` (rapidfuzz imported before the empty-candidates check).

- [ ] **Step 3: Reorder `_best_fuzzy_match` to defer the import**

In `backend/src/jaaffl/data/crosswalk.py`, replace the top of `_best_fuzzy_match` (currently imports rapidfuzz first) so the DB query and empty-guard run BEFORE the import:

```python
    def _best_fuzzy_match(
        self, name: str, position: str, nfl_team: str | None
    ) -> tuple[str | None, dict]:
        norm = name_norm(name, position)
        target_team = team_norm(nfl_team)  # None => team-agnostic (FA / unknown)
        conn = open_app_db(self.db_path)
        try:
            # Filter by team in Python (via team_norm), not SQL, so divergent source code schemes
            # (DynastyProcess 'SFO' vs FFC 'SF') still match — an exact SQL compare would not.
            candidates = conn.execute(
                "SELECT player_id, name_norm, nfl_team FROM players WHERE position = ?",
                [str(position)],
            ).fetchall()
        finally:
            conn.close()
        if target_team is not None:
            candidates = [c for c in candidates if team_norm(c[2]) == target_team]
        if not candidates:
            return None, {}
        # Deferred so the base ($0) install imports crosswalk (and thus the API) without the
        # `data` extra; only actual fuzzy scoring needs rapidfuzz (mirrors warehouse.py's deferral).
        from rapidfuzz import fuzz

        scored = sorted(
            (
                (fuzz.token_sort_ratio(norm, cand_norm) / 100.0, pid)
                for pid, cand_norm, _ in candidates
            ),
            reverse=True,
        )
        if scored[0][0] < self.threshold:
            return None, {}
        best_score, best_id = scored[0]
        features = {
            "name_score": round(best_score, 4),
            "pos_match": True,
            "team_match": target_team is not None,
            "runners_up": [{"player_id": pid, "score": round(s, 4)} for s, pid in scored[1:4]],
        }
        return best_id, features
```

- [ ] **Step 4: Run the new test + the full crosswalk suite**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_crosswalk.py -v
```
Expected: PASS — the new test plus every existing fuzzy-match test (behavior identical for non-empty candidates).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/src/jaaffl/data/crosswalk.py backend/tests/test_crosswalk.py && git commit -m "fix(crosswalk): defer rapidfuzz import so an empty table resolves to None (base-install safe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `ingest/resolve.resolve_pick_ids`

The pure resolution seam: folded state + league events + an injected resolver → state with name-only picks' `player_id` filled.

**Files:**
- Create: `backend/src/jaaffl/ingest/resolve.py`
- Modify: `backend/src/jaaffl/ingest/__init__.py` (export)
- Test: `backend/tests/test_resolve.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolve.py`:

```python
"""resolve_pick_ids: fill canonical player_ids for name-only (manual-paste) picks."""

from __future__ import annotations

import pytest

from jaaffl.domain import DraftPick, DraftState
from jaaffl.ingest.log import LoggedEvent
from jaaffl.ingest.resolve import resolve_pick_ids


def _pick_event(overall: int, team_id: str, **data) -> LoggedEvent:
    return LoggedEvent(
        seq=overall,
        league_id="L",
        event_type="pick_made",
        pick_number=overall,
        data={"overall": overall, "round": 1, "pick_in_round": overall, "team_id": team_id, **data},
        source="paste",
        captured_at="t",
    )


def _state(picks: list[DraftPick]) -> DraftState:
    return DraftState(league_id="L", current_overall_pick=len(picks) + 1, my_team_id="t0", picks=picks)


def test_resolves_name_only_pick_to_canonical() -> None:
    events = [_pick_event(1, "t1", player_name="Christian McCaffrey", position="RB", player_team="SF")]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])

    def resolver(name, team, pos):
        return "gsis:cmc" if (name, team, pos) == ("Christian McCaffrey", "SF", "RB") else None

    out = resolve_pick_ids(state, events, resolver)
    assert out.picks[0].player_id == "gsis:cmc"


def test_leaves_already_resolved_picks_untouched() -> None:
    events = [_pick_event(1, "t1", player_name="X", position="RB", player_team="SF")]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1", player_id="cbs:9")])
    calls: list = []

    def resolver(*a):
        calls.append(a)
        return "gsis:nope"

    out = resolve_pick_ids(state, events, resolver)
    assert out.picks[0].player_id == "cbs:9"
    assert calls == []  # resolver never consulted for a pick that already carries an id
    assert out is state  # nothing changed -> same object


def test_unresolved_name_stays_none() -> None:
    events = [_pick_event(1, "t1", player_name="Ghost", position="RB", player_team="ZZ")]
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])
    out = resolve_pick_ids(state, events, lambda *a: None)
    assert out.picks[0].player_id is None


def test_maps_source_position_codes() -> None:
    events = [
        _pick_event(1, "t1", player_name="San Francisco", position="DEF", player_team="SF"),
        _pick_event(2, "t2", player_name="Some Kicker", position="PK", player_team="SF"),
    ]
    state = _state(
        [
            DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1"),
            DraftPick(overall=2, round=1, pick_in_round=2, team_id="t2"),
        ]
    )
    seen: dict[str, str] = {}

    def resolver(name, team, pos):
        seen[name] = pos
        return None

    resolve_pick_ids(state, events, resolver)
    assert seen == {"San Francisco": "DST", "Some Kicker": "K"}


def test_name_only_pick_without_name_in_events_is_skipped() -> None:
    events = [_pick_event(1, "t1")]  # pick_made with no player_name
    state = _state([DraftPick(overall=1, round=1, pick_in_round=1, team_id="t1")])
    out = resolve_pick_ids(state, events, lambda *a: pytest.fail("resolver must not be called"))
    assert out.picks[0].player_id is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_resolve.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jaaffl.ingest.resolve'`.

- [ ] **Step 3: Create the module**

Create `backend/src/jaaffl/ingest/resolve.py`:

```python
"""Resolve name-only drafted picks to canonical player ids (the live-recs keystone).

Manual-paste picks arrive name-only (``DraftPick.player_id is None``); the ``player_name`` /
``position`` / ``player_team`` live in the raw ``pick_made`` event payload, not the folded
``DraftState`` (``fold_state`` stays pure; ``DraftPick`` stays a frozen contract model). This module
bridges the two: given the folded state, the league's logged events, and an injected name resolver
(the crosswalk), it fills ``player_id`` for name-only picks so ``engine.recommend`` masks them from
the candidate pool. It does NO provider/network I/O (the resolver is injected) and never mutates the
log. Picks already carrying an id are left untouched — the out-of-scope ``cbs:`` capture path stays
out of it. Unresolved names stay ``None`` and are logged (a drafted-but-unmasked player is a real
correctness gap — surfaced, never silently swallowed).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import structlog

from jaaffl.domain import DraftEventType, DraftPick, DraftState
from jaaffl.ingest.log import LoggedEvent

log = structlog.get_logger(__name__)

# (name, nfl_team|None, canonical_position) -> canonical player_id | None
NameResolver = Callable[[str, str | None, str], str | None]

# Source position codes (manual-paste is user-typed) -> canonical domain Position value. resolve_name
# requires a canonical position; anything not aliased is upper-cased and passed through (already-canonical
# codes like RB/WR/QB/TE match as-is; an unknown code simply finds no candidates and stays unresolved).
_POSITION_ALIASES = {"DEF": "DST", "D/ST": "DST", "DEFENSE": "DST", "DST": "DST", "PK": "K", "K": "K"}


def _canonical_position(raw: object) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip().upper()
    if not code:
        return None
    return _POSITION_ALIASES.get(code, code)


def resolve_pick_ids(
    state: DraftState, events: Iterable[LoggedEvent], resolver: NameResolver
) -> DraftState:
    """Return ``state`` with name-only picks' ``player_id`` filled from their event name via
    ``resolver``. Returns the same object when nothing changed."""
    name_index: dict[int, dict] = {}
    for ev in events:
        if ev.event_type == DraftEventType.PICK_MADE:
            overall = ev.data.get("overall")
            if overall is not None:
                name_index[int(overall)] = ev.data

    resolved = 0
    unresolved = 0
    changed = False
    new_picks: list[DraftPick] = []
    for pick in state.picks:
        if pick.player_id is not None:
            new_picks.append(pick)
            continue
        data = name_index.get(pick.overall)
        name = data.get("player_name") if data else None
        pos = _canonical_position(data.get("position")) if data else None
        if not name or pos is None:
            new_picks.append(pick)
            unresolved += 1
            continue
        team = data.get("player_team") or data.get("nfl_team")
        canonical = resolver(str(name), str(team) if team else None, pos)
        if canonical is None:
            new_picks.append(pick)
            unresolved += 1
            continue
        new_picks.append(pick.model_copy(update={"player_id": canonical}))
        resolved += 1
        changed = True

    if resolved or unresolved:
        log.info("drafted_pick_name_resolution", resolved=resolved, unresolved=unresolved)
    return state.model_copy(update={"picks": new_picks}) if changed else state
```

Then export it in `backend/src/jaaffl/ingest/__init__.py`: add `from jaaffl.ingest.resolve import resolve_pick_ids` (below the other ingest imports) and add `"resolve_pick_ids"` to `__all__`.

- [ ] **Step 4: Run to verify they pass**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_resolve.py -v
```
Expected: PASS — all 5 tests.

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/src/jaaffl/ingest/resolve.py backend/src/jaaffl/ingest/__init__.py backend/tests/test_resolve.py && git commit -m "feat(ingest): resolve_pick_ids — mask name-only manual-paste picks via the crosswalk

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Wire resolution into the API + end-to-end masking test

**Files:**
- Modify: `backend/src/jaaffl/api/app.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing end-to-end test**

Add to `backend/tests/test_api.py`:

```python
def test_recommendation_masks_name_only_paste_pick(tmp_path: Path) -> None:
    """A manual-paste (name-only) pick is resolved to its canonical id via the crosswalk, then
    masked from the candidate pool — the live-recs correctness guarantee."""
    specs = [{"pid": "gsis:cmc", "pos": Position.RB, "mu": 330.0, "adp": 1.0, "sd": 6.0, "ecr": 1.0}]
    specs += [
        {"pid": f"wr{i}", "pos": Position.WR, "mu": 300.0 - 4 * i, "adp": float(i + 2), "sd": 6.0, "ecr": float(i + 2)}
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=engine,
    )
    # Seed the crosswalk players row so the paste name resolves to the canonical id.
    app.state.crosswalk.upsert(
        Player(player_id="gsis:cmc", name="Christian McCaffrey", position=Position.RB, nfl_team="SF")
    )
    client = TestClient(app)
    paste = {
        "event_type": "pick_made", "league_id": "L1", "pick_number": 1, "source": "paste",
        "data": {
            "overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T1",
            "player_name": "Christian McCaffrey", "position": "RB", "player_team": "SF",
        },
    }
    client.post("/draft/events", json=paste)
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 50})
    assert res.status_code == 200
    ranked_ids = [p["player_id"] for p in res.json()["ranked"]]
    assert ranked_ids  # board still non-empty
    assert "gsis:cmc" not in ranked_ids  # elite RB resolved from the paste name, then masked
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_api.py::test_recommendation_masks_name_only_paste_pick -v
```
Expected: FAIL — `app.state` has no `crosswalk` (AttributeError), and/or `gsis:cmc` still appears in `ranked_ids` (no resolution wired).

- [ ] **Step 3: Wire resolution into `api/app.py`**

Add imports near the top of `backend/src/jaaffl/api/app.py`:
```python
from jaaffl.data import Crosswalk
```
Extend the ingest import line to include the new symbol:
```python
from jaaffl.ingest import DraftLog, IngestResult, handle_event, resolve_pick_ids
```

In `create_app`, right after `app.state.warehouse = Warehouse(settings.jaaffl_data_dir)`, add:
```python
    app.state.crosswalk = Crosswalk(app.state.warehouse.app_sqlite)
```

Add the resolution helper (place it just before `def publish_recommendation`):
```python
    def _resolve_state(state, league_id):
        """Fill canonical player_ids for name-only (manual-paste) picks — resolving the raw event
        names via the crosswalk — so the engine masks drafted players from the candidate pool."""
        return resolve_pick_ids(
            state, app.state.draft_log.events(league_id), app.state.crosswalk.resolve_name
        )
```

In `publish_recommendation`, resolve before recommending:
```python
        recommendation = app.state.rec_engine.recommend(
            _resolve_state(result.state, event.league_id)
        )
```

In the `recommendation` route, insert the resolve call immediately before `rec = app.state.rec_engine.recommend(...)` (after the `as_of_overall_pick` / `team_id` overrides):
```python
        state = _resolve_state(state, league_id)
        rec = app.state.rec_engine.recommend(state, limit=limit, use_mc=mc)
```

- [ ] **Step 4: Run the new test + the full API suite (no regressions)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_api.py -v
```
Expected: PASS — the new masking test plus every existing API test (existing picks carry no `player_name`, so resolution is a no-op for them).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/src/jaaffl/api/app.py backend/tests/test_api.py && git commit -m "feat(api): resolve name-only picks before recommend so drafted players are masked

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Opt-in slow integration test (real nflverse pull)

Proves `players()` against the real FREE nflverse feed. Opt-in (skipped by default) so the suite stays network-free.

**Files:**
- Test: `backend/tests/test_provider_nflverse.py`

- [ ] **Step 1: Add the gated test**

Add to `backend/tests/test_provider_nflverse.py` (add `import os` at the top of the file):

```python
@pytest.mark.skipif(
    not os.environ.get("JAAFFL_RUN_NETWORK_TESTS"),
    reason="opt-in: real nflverse network pull; set JAAFFL_RUN_NETWORK_TESTS=1 to run",
)
def test_players_real_nflverse_pull_returns_universe() -> None:
    pytest.importorskip("nflreadpy")
    universe = NflreadpyProvider().players(2026)
    assert len(universe) > 100  # a real universe is thousands of players
    assert all(p.player_id.startswith("gsis:") for p in universe)
    positions = {p.position for p in universe}
    assert {Position.QB, Position.RB, Position.WR, Position.TE}.issubset(positions)
```

- [ ] **Step 2: Verify it is SKIPPED by default (network-free)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_provider_nflverse.py::test_players_real_nflverse_pull_returns_universe -v
```
Expected: `1 skipped` (no `JAAFFL_RUN_NETWORK_TESTS` set).

- [ ] **Step 3: (Optional, manual) Run it once against the live feed**

```bash
cd "$WT/backend" && JAAFFL_RUN_NETWORK_TESTS=1 PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_provider_nflverse.py::test_players_real_nflverse_pull_returns_universe -v
```
Expected: PASS (pulls the free DynastyProcess CSV; needs network). Record the observed universe size in the PR description.

- [ ] **Step 4: Commit**

```bash
cd "$WT" && git add backend/tests/test_provider_nflverse.py && git commit -m "test(nflverse): opt-in integration test for the real players() pull (network-gated)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Full backend suite (network-free) stays green + grew by the new tests**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest -q
```
Expected: PASS, `>= 288` passing + `1 skipped` (the opt-in integration test), 0 failures.

- [ ] **Run the project `verify` recipe (ruff + pytest + tsc)** via the verify skill — all green; JS baseline (109) unchanged (no JS touched, E5 contract untouched).

---

## Self-review — spec coverage

| Spec requirement | Task |
|---|---|
| `players()` from `load_ff_playerids()`, skip-and-log, `gsis:` ids, `ProviderError` | Task 2 |
| Alignment: universe ids == seed/rankings canonical ids | Task 1 (shared helper) + Task 2 assertion |
| 503→universe flip through `_registry_player_loader` | Task 3 |
| `resolve_pick_ids` seam, position mapping, only-fill-`None`, log unresolved | Task 5 |
| Wire into `GET /recommendation` + `publish_recommendation` | Task 6 |
| rapidfuzz micro-fix (base-install 500 guard) | Task 4 |
| End-to-end paste → resolved → masked | Task 6 test |
| Opt-in slow real-nflverse integration test | Task 7 |
| Frozen: `recommend.py`, `fold_state`, domain models, E5 contract | not touched (verified in Final: JS/parity untouched) |
