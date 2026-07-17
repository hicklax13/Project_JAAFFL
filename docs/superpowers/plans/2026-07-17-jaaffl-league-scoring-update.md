# JAAFFL2025 scoring + constitution update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the CBS-Standard-guess scoring map with the owner's authoritative JAAFFL2025 scoring, and fix every dependent test/config/doc — so the engine's projections and draft recommendations use the real league values.

**Architecture:** The scoring *evaluator* (`league_points`) is value-agnostic and unchanged. The change is the scoring **map** (`defaults.jaaffl_scoring`, renamed from `cbs_standard_scoring`), its importers, and the constitution/config framing. Rush/rec/TD/2pt values are already correct, so most callers need only the rename.

**Tech Stack:** Python 3.12, Pydantic v2, pytest.

---

## Environment — run tests in this worktree

```bash
WT=/c/Users/conno/Project_JAAFFL/Project_JAAFFL/.claude/worktrees/league-scoring
PY=/c/Users/conno/Project_JAAFFL/Project_JAAFFL/.venv/Scripts/python.exe
RUFF=/c/Users/conno/Project_JAAFFL/Project_JAAFFL/.venv/Scripts/ruff.exe
# tests: cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest <args>
```
Baseline: 309 backend / 129 JS green. Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Task 1: Rewrite the scoring map + fix all importers (full suite green)

The `cbs_standard_scoring` → `jaaffl_scoring` rename is atomic: renaming the function breaks `constitution.py` + 4 test files at import until they're updated, so this task does the map rewrite AND all rename fixes together, ending with a green full suite.

**Files:**
- Modify: `backend/src/jaaffl/league/defaults.py` (rename + rewrite map + module docstring)
- Modify: `backend/src/jaaffl/league/constitution.py` (import/call rename + docstrings)
- Modify: `backend/tests/test_defaults.py` (rewrite)
- Modify: `backend/tests/test_context.py`, `test_materialize_projections.py`, `test_projections.py` (rename only)
- Modify: `backend/tests/test_api.py` (one tier-set assertion)

- [ ] **Step 1: Rewrite `test_defaults.py` (the failing spec for the new map)**

Replace the entire file `backend/tests/test_defaults.py` with:

```python
"""Owner-provided JAAFFL2025 scoring (league/defaults.py) — custom, non-PPR.

Authoritative owner rules (2026-07-17): passing 0.02/yd (1 per 50); NO offensive turnover penalty;
all TDs 6; non-PPR (rec 0); K FG base 3 + CUMULATIVE distance bonuses (+1 at 50, +1 more at 60); DST
scores a SINGLE points-allowed bracket (0-9 = 6) and NO yards-allowed tier.
"""

from __future__ import annotations

from jaaffl.domain import Position
from jaaffl.league import league_points
from jaaffl.league.defaults import jaaffl_scoring


def test_receptions_score_zero_non_ppr() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"receptions": 10, "receiving_yards": 100, "receiving_td": 1}
    pts = league_points(line, rules, Position.WR, tiers=tiers, bonuses=bonuses)
    assert pts == 100 * 0.1 + 1 * 6  # 16.0 — the 10 catches add nothing (non-PPR)


def test_passing_is_one_point_per_50_and_no_interception_penalty() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"passing_yards": 300, "passing_td": 3, "interception": 1}  # INT must NOT be penalized
    pts = league_points(line, rules, Position.QB, tiers=tiers, bonuses=bonuses)
    assert pts == 300 * 0.02 + 3 * 6  # 6 + 18 = 24.0 (interception scores nothing)


def test_no_offensive_fumble_lost_penalty() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    line = {"rushing_yards": 100, "rushing_td": 1, "fumble_lost": 2}
    pts = league_points(line, rules, Position.RB, tiers=tiers, bonuses=bonuses)
    assert pts == 100 * 0.1 + 1 * 6  # 16.0 — offensive fumbles are not penalized


def test_dst_single_points_allowed_bracket_and_no_yards_tier() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    # Allow 7 pts → +6 (single 0-9 bracket); dst_yards_allowed has NO tier (0); 4 sacks +4; 1 INT +2.
    line = {"dst_points_allowed": 7, "dst_yards_allowed": 280, "sack": 4, "dst_int": 1}
    pts = league_points(line, rules, Position.DST, tiers=tiers, bonuses=bonuses)
    assert pts == 6 + 4 + 2  # 12.0 (yards-allowed is ignored — JAAFFL scores no yards tier)


def test_dst_points_allowed_boundary() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    kw = {"tiers": tiers, "bonuses": bonuses}
    assert league_points({"dst_points_allowed": 9}, rules, Position.DST, **kw) == 6.0  # under 10
    assert league_points({"dst_points_allowed": 10}, rules, Position.DST, **kw) == 0.0  # 10+ → 0


def test_kicker_distance_bonuses_are_cumulative() -> None:
    rules, tiers, bonuses = jaaffl_scoring()
    kw = {"tiers": tiers, "bonuses": bonuses}
    # 55-yd FG: 50plus only → 3 + 1 = 4.  62-yd FG: 50plus AND 60plus → 3 + 1 + 1 = 5.
    assert league_points({"fg_made": 1, "fg_made_50plus": 1}, rules, Position.K, **kw) == 4.0
    assert (
        league_points(
            {"fg_made": 1, "fg_made_50plus": 1, "fg_made_60plus": 1}, rules, Position.K, **kw
        )
        == 5.0
    )
```

- [ ] **Step 2: Run test_defaults — verify it fails (jaaffl_scoring undefined)**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_defaults.py -q
```
Expected: collection ERROR — `ImportError: cannot import name 'jaaffl_scoring'`.

- [ ] **Step 3: Rewrite `defaults.py` — rename + the JAAFFL2025 map**

Replace the module docstring (lines 1-18) and the `cbs_standard_scoring` function body in `backend/src/jaaffl/league/defaults.py`. New docstring:

```python
"""Owner-provided JAAFFL2025 scoring (custom, non-PPR) — the authoritative league map.

Encoded verbatim from the owner's CBS League-Settings + Constitution (2026-07-17). Distinctives:
**passing = 1 pt / 50 yds (0.02/yd)**, **no offensive turnover penalty**, all TDs 6, non-PPR
(receptions score 0). Kicker FG base 3 with cumulative distance bonuses (+1 at 50, +1 more at 60 →
50-59 nets 4, 60+ nets 5). DST scores a SINGLE points-allowed bracket (**allow 0-9 → +6**, else 0)
and NO yards-allowed tier, plus sack 1 / INT 2 / fumble recovery 2 / safety 2 / def+ST TD 6.

Stat keys are JAAFFL-canonical; the ingest/context layer maps provider columns (nflverse
``passing_tds`` → ``passing_td``, etc.) onto them. Only CBS *live-frame parsing* stays capture-blocked
now — the scoring VALUES are owner-confirmed. Do NOT edit config/league.json's roster (immutable); a
captured CBS ``league_settings`` may still override this map (defense-in-depth).

Omitted (no per-player data on the $0 tier; inert): individual fumble-recovery / kick-return TDs.
"""
```

New function (rename + body):

```python
def jaaffl_scoring() -> tuple[list[ScoringRule], list[ScoringTier], list[ScoringBonus]]:
    """Return ``(rules, tiers, bonuses)`` for the owner-provided JAAFFL2025 scoring (non-PPR)."""
    rules = [
        # Offense — non-PPR (no ``reception`` rule); NO offensive turnover penalty; all TDs 6.
        ScoringRule(stat="passing_yards", points_per_unit=0.02),  # 1 pt / 50 yds
        ScoringRule(stat="passing_td", points_per_unit=6.0),
        ScoringRule(stat="rushing_yards", points_per_unit=0.1),  # 1 pt / 10 yds
        ScoringRule(stat="rushing_td", points_per_unit=6.0),
        ScoringRule(stat="receiving_yards", points_per_unit=0.1),
        ScoringRule(stat="receiving_td", points_per_unit=6.0),
        ScoringRule(stat="two_point", points_per_unit=2.0),  # pass/rush/rec conversions
        # Kicker — FG base 3 (linear); PAT 1. Distance bonuses below.
        ScoringRule(stat="fg_made", points_per_unit=3.0, applies_to=_K),
        ScoringRule(stat="xp_made", points_per_unit=1.0, applies_to=_K),
        # DST — event scoring.
        ScoringRule(stat="sack", points_per_unit=1.0, applies_to=_DST),
        ScoringRule(stat="dst_int", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="fumble_recovery", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="safety", points_per_unit=2.0, applies_to=_DST),
        ScoringRule(stat="dst_td", points_per_unit=6.0, applies_to=_DST),
        ScoringRule(stat="return_td", points_per_unit=6.0, applies_to=_DST),
    ]
    tiers = [
        # DST points-allowed: a SINGLE bracket — allow 0-9 → +6, allow 10+ → 0 (no bracket matches).
        # JAAFFL scores NO yards-allowed tier.
        ScoringTier(
            stat="dst_points_allowed",
            applies_to=_DST,
            brackets=[ScoringBracket(lower=0, upper=10, points=6)],
        ),
    ]
    bonuses = [
        # Cumulative FG distance bonuses: ≥50 → +1, ≥60 → +1 more (a 60+ FG earns BOTH → +2).
        ScoringBonus(stat="fg_made_50plus", threshold=50, points=1.0, applies_to=_K),
        ScoringBonus(stat="fg_made_60plus", threshold=60, points=1.0, applies_to=_K),
    ]
    return rules, tiers, bonuses
```

- [ ] **Step 4: Run test_defaults — verify it passes**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest tests/test_defaults.py -q
```
Expected: 6 passed. (The rest of the suite is now broken at import — fixed next.)

- [ ] **Step 5: Rename importers — `constitution.py` + 3 test files**

In `backend/src/jaaffl/league/constitution.py`:
- line 22: `from jaaffl.league.defaults import cbs_standard_scoring` → `from jaaffl.league.defaults import jaaffl_scoring`
- line 90: `rules, tiers, bonuses = cbs_standard_scoring()` → `rules, tiers, bonuses = jaaffl_scoring()`
- Update the two docstrings (module lines ~9-13, and `resolve_league_settings` ~84): replace "offline ``cbs_standard_scoring()`` map is the validation fallback (TODO(capture): the REAL CBS values are capture-blocked)" with: "the owner-provided ``jaaffl_scoring()`` map is authoritative (only CBS live-frame *parsing* stays capture-blocked); a captured CBS ``league_settings`` scoring still overrides it when present."

In each of `backend/tests/test_context.py`, `backend/tests/test_materialize_projections.py`, `backend/tests/test_projections.py`:
- Change `from jaaffl.league.defaults import cbs_standard_scoring` → `from jaaffl.league.defaults import jaaffl_scoring`
- Change `rules, tiers, bonuses = cbs_standard_scoring()` → `rules, tiers, bonuses = jaaffl_scoring()`
(These feed only rush/rec stat lines — unchanged values — so their assertions are unaffected.)

- [ ] **Step 6: Fix the `test_api.py` tier-set assertion**

In `backend/tests/test_api.py` (~line 358), change:
```python
    assert {t.stat for t in ls.scoring_tiers} == {"dst_points_allowed", "dst_yards_allowed"}
```
to:
```python
    assert {t.stat for t in ls.scoring_tiers} == {"dst_points_allowed"}  # JAAFFL: no yards tier
```
Also update the nearby comment (~line 355) `# Scoring overlay present (offline cbs_standard_scoring default until capture): CBS 6pt pass TD` → `# Scoring overlay present (owner-provided jaaffl_scoring): 6pt pass TD + single DST points-allowed bracket`.

- [ ] **Step 7: Run the FULL backend suite — verify green**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest -q
```
Expected: 309 passed, 1 skipped (no value regressions — the renamed callers use unchanged rush/rec values).

- [ ] **Step 8: Lint + commit**

```bash
cd "$WT/backend" && "$RUFF" check src tests && "$RUFF" format --check src tests
cd "$WT" && git add backend/ && git commit -m "feat(scoring): JAAFFL2025 owner scoring (jaaffl_scoring) replaces the CBS-Standard guess

passing 0.02/yd (1 per 50), no offensive turnover penalty, K cumulative distance bonuses (+1@50,
+1@60), DST single points-allowed bracket (0-9=6) and no yards-allowed tier. Renames
cbs_standard_scoring -> jaaffl_scoring across constitution + tests; evaluator/roster unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Config, docstrings, and docs

**Files:** `config/league.json`; `backend/src/jaaffl/league/scoring.py`, `engine/precompute.py`, `api/app.py` (docstrings); `docs/live-draft-recording-guide.md`, `docs/owner-manual-todo.md`.

- [ ] **Step 1: Update `config/league.json`**

- `"scoring_format": "Standard"` → `"scoring_format": "Custom (non-PPR)"`.
- Replace `"scoring_note"` with: `"Owner-confirmed JAAFFL2025 custom scoring (2026-07-17), non-PPR (0 per reception). Passing = 1 pt / 50 yds (0.02); rush/rec = 0.1/yd; all TDs = 6; 2-pt = 2; NO offensive INT/fumble penalty. K: FG 3, +1 at 50-59, +1 more at 60+, XP 1. DST: sack 1, INT 2, fumble recovery 2, safety 2, def/ST TD 6, points-allowed 0-9 = 6 (no yards-allowed tier). Typed map: backend/src/jaaffl/league/defaults.py::jaaffl_scoring (single source; this note documents, code encodes)."`.
- In the `"league"` object, add after `"platform"`: `"name": "JAAFFL2025", "url": "https://jaaffl2002.football.cbssports.com", "email": "jaaffl2002@football.cbssports.com", "entry_fee_usd": 400,`.
- `"last_confirmed": "2026-07-15"` → `"2026-07-17"`.
- In `"_comment"`, append: ` Scoring values are owner-confirmed as of 2026-07-17 (no longer CBS-inferred).`

- [ ] **Step 2: Verify the constitution still loads + serves the new scoring**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -c "
from jaaffl.league.constitution import resolve_league_settings
ls = resolve_league_settings('cbs-local')
print('format-ok', ls.team_count == 12)
print('pass-rule', next(r.points_per_unit for r in ls.scoring if r.stat=='passing_yards'))
print('tiers', {t.stat for t in ls.scoring_tiers})
"
```
Expected: `pass-rule 0.02`, `tiers {'dst_points_allowed'}` (no yards). Also re-run `tests/test_api.py -q` → passed.

- [ ] **Step 3: Update docstrings/comments that describe the scoring as CBS-Standard/capture-blocked**

- `backend/src/jaaffl/league/scoring.py` (module docstring lines ~11, ~22): change "CBS 'Standard' scores DST on BOTH ``dst_points_allowed`` AND ``dst_yards_allowed``, and the two tiers **sum**" → "A league MAY score DST on multiple tiers (they sum); JAAFFL2025 uses a single ``dst_points_allowed`` bracket (``league/defaults.jaaffl_scoring``)." Replace the `TODO(capture): the REAL CBS "Standard" bracket/bonus values are UNVERIFIED` paragraph with "The real JAAFFL scoring values are owner-confirmed in ``league.defaults.jaaffl_scoring``; this evaluator stays value-agnostic."
- `backend/src/jaaffl/engine/precompute.py` (~line 14): change "``cbs_standard_scoring()`` map is the validation fallback until a live CBS scoring-page capture" → "``jaaffl_scoring()`` map is the owner-authoritative scoring (a captured CBS scoring page may still override)".
- `backend/src/jaaffl/api/app.py` (~line 316): change "offline cbs_standard_scoring until a" → "owner-provided jaaffl_scoring (a captured CBS snapshot's scoring still wins when present)".

- [ ] **Step 4: Update docs**

- `docs/live-draft-recording-guide.md` (the league-settings table row): `| **Scoring** | Standard (**non-PPR** — 0 points per reception) |` → `| **Scoring** | Custom (**non-PPR** — 0 per reception); JAAFFL2025 values (1 pt/50 pass yds, no off. turnover penalty, single DST points-allowed bracket) |`.
- `docs/owner-manual-todo.md` (~line 19, the "real CBS scoring VALUES" item): mark **RESOLVED** — "Owner provided the official JAAFFL2025 scoring 2026-07-17; encoded in ``league/defaults.jaaffl_scoring``. The CBS *frame-parsing* capture is still pending (that's for live draft-room shapes, not scoring values)."

- [ ] **Step 5: Lint + commit**

```bash
cd "$WT/backend" && "$RUFF" check src && "$RUFF" format --check src
cd "$WT" && git add -A && git commit -m "docs+config: memorialize JAAFFL2025 custom scoring; retire the CBS-Standard framing

config/league.json scoring_format Custom + real scoring_note + identity block; scoring/precompute/
app docstrings + recording guide + owner-manual-todo updated (scoring values now owner-confirmed,
not capture-blocked).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Full verification

- [ ] **Step 1: Full backend + JS gates**

```bash
cd "$WT/backend" && PYTHONPATH="$WT/backend/src" "$PY" -m pytest -q          # 309 passed, 1 skipped
cd "$WT/backend" && "$RUFF" check src tests && "$RUFF" format --check src tests   # clean
cd "$WT" && pnpm install --frozen-lockfile && pnpm -r typecheck && pnpm -r test   # tsc + 129 vitest (no JS touched → unchanged)
```

- [ ] **Step 2: Code review (silent-failure-hunter is not relevant; use code-reviewer + a scoring-correctness check), then PR.**

---

## Post-merge (NOT in the PR — the memory dir is outside the repo)

Replace the now-wrong `cbs-standard-scoring-verified` memory with a `jaaffl-scoring-verified` reference memory (correct values + owner-confirmed interpretations) and update the `MEMORY.md` index line.

---

## Self-review — spec coverage

| Spec requirement | Task |
|---|---|
| passing 0.02, drop INT/fumble, K double-bonus, DST single PA bracket, drop yards tier | Task 1 Step 3 |
| rename cbs_standard_scoring → jaaffl_scoring (all callers) | Task 1 Steps 3, 5 |
| test_defaults rewrite; test_api tier assertion; test_scoring unchanged | Task 1 Steps 1, 6 |
| config/league.json (format/note/identity) | Task 2 Step 1 |
| constitution/scoring/precompute/app docstrings | Task 1 Step 5, Task 2 Step 3 |
| recording guide + owner-manual-todo | Task 2 Step 4 |
| memory replacement | Post-merge |
| frozen: evaluator, roster, engine, E5 contract | not touched |
