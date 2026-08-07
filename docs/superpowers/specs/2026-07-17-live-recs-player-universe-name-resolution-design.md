# Design: Live $0 recs — player universe + drafted-pick name resolution

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation
**Scope:** The Stage-5 → live keystone. Flip `GET /recommendation` from a graceful 503 to a
real 200 on FREE nflverse data, and keep those live recs correct as manual-paste picks land.

## Goal

Two coupled increments ship together:

1. **`NflreadpyProvider.players(season) -> list[Player]`** — the FREE nflverse player-universe
   loader. Today `providers/base.players()` raises `NotImplementedError`, so
   `precompute._registry_player_loader` returns `{}` and the precompute source returns `None`
   (503). Implementing it returns a real universe → the join produces projections → 200.
2. **Drafted-pick name resolution** — manual-paste picks arrive name-only (`player_id is None`),
   so `engine/recommend.recommend` (which masks only picks carrying a canonical id) leaves them in
   the candidate pool and can recommend an already-drafted player. Resolve those names to the
   canonical `player_id` via the existing crosswalk so they're masked.

Manual-paste is the live data path. CBS record-mode capture is `TODO(capture)` / out of scope.

## Non-negotiable constraints (verified against `main` @ `2cd3349`)

- **$0 only.** nflverse is free. No paid providers, no API keys/secrets, no OpenAI.
- **Frozen surfaces stay frozen:** `engine/recommend.py` (provider-free hot path),
  `ingest/log.fold_state` (pure, deterministic, no I/O), the `DraftPick`/`DraftState` domain
  models, and the **entire E5 contract** (Zod mirrors, `packages/shared/schemas/*.json`,
  `packages/shared/fixtures/*.json`). No change to `config/league.json` or `config/engine.json`.
- **Seeding stays the existing pre-draft step:** `materialize.refresh_nflverse_history()` already
  calls `seed_crosswalk()`. We do NOT add seeding into the precompute request path.
- **Gates:** project `verify` recipe green (ruff + pytest + tsc); do not regress the
  288 backend / 109 JS baseline.

## Architecture invariants that shape the design

- **The universe is a join key.** In the live $0 tier the only projection source is ECR→points
  (`nflverse.rankings()` via the precompute `ecr_to_points` curve — no free PROJECTIONS provider is
  live; CBS on-page is capture-blocked). Therefore
  `context.mu = {universe ids} ∩ {rankings-resolved ids}`. If `players()` emits ids that don't
  match the `gsis:<id>` ids `rankings()` resolves to, the intersection is empty and
  `/recommendation` still 503s — a silent failure. The universe MUST use the same canonical scheme.
- **Two "no-I/O" contracts** bound where name resolution can live: `recommend()` touches no
  provider/network, and `fold_state()` is a pure replay. The crosswalk does SQLite I/O, so
  resolution goes in a NEW seam in the API orchestration layer — never inside either.
- **Masking already works once `player_id` is filled.** `recommend()` masks by `pick.player_id`.
  Resolution runs upstream and fills `player_id`, so `recommend()` needs zero change.

## Component 1 — `NflreadpyProvider.players(season)`

**Source:** `nflreadpy.load_ff_playerids()` — the DynastyProcess `db_playerids` table, the SAME
source `seed_crosswalk()` uses. Chosen over `load_players()` because it guarantees the universe's
canonical ids are exactly the ids the seed + `rankings()` resolve to (the join cannot silently
empty out), carries the cross-source ids for free, and reuses the already-verified skip rule. It
holds every possible candidate: candidacy requires an ECR, and ECR resolves through this same
table's seeded crosswalk — so a player absent here could never be a candidate anyway.

**Per-row mapping (mirrors `rankings()` resolve+skip and `seed_from_playerids`):**

- Require a clean `gsis_id` and a league-valid `position` (the domain `Position` set). Otherwise
  **skip-and-log**. (Team DSTs have no gsis → skipped; an honest, documented gap. K/DST are
  streamed late by the punt guard, so this does not hurt live early-round recs. DST-universe
  coverage is a separate future enhancement noted in `docs/owner-manual-todo.md`.)
- Survivor → `Player(player_id=f"gsis:{gsis}", name=<name or canonical>, position=Position(pos),
nfl_team=<clean team>)`. **No `external_ids`** (YAGNI — the engine never reads them; the seed
  links cross-source ids into SQLite separately).
- A per-row construction failure (e.g. `ValidationError`) skips that row, never aborts the batch.
- Emit an aggregate `kept`/`skipped` log line (like `rankings()`).
- `ProviderError` if the `data` extra (nflreadpy) is missing (mirrors `rankings()`/`seed_crosswalk`).

**Single-source-of-truth for alignment (targeted refactor):** extract a module-level helper into
`data/crosswalk.py` (which already owns the `gsis:` scheme, `_VALID_POSITIONS`, and `_clean`):

```python
def player_from_playerid_row(row: Mapping) -> Player | None:
    """Map one load_ff_playerids() row to a canonical Player, or None to skip
    (no gsis_id, or a non-league position)."""
```

Use it in **both** `NflreadpyProvider.players()` and `Crosswalk.seed_from_playerids()` (the latter
refactored to build its upserted `Player` from the helper). This guarantees, by construction, that
the universe and the seed agree on exactly which rows survive and which canonical ids they carry.
`nflverse.py` already depends on the data layer at runtime (it holds a `Crosswalk`), so importing
this helper is not a new dependency. `seed_from_playerids`'s existing behavior/tests are preserved
(identical `Player` output; it still writes the id_crosswalk links itself).

## Component 2 — Drafted-pick name resolution

**New module `ingest/resolve.py`** (imports only `domain` + `ingest.log.LoggedEvent` + typing — no
data layer; the crosswalk is injected as a callable):

```python
NameResolver = Callable[[str, str | None, str], str | None]  # (name, team, canonical_pos) -> id|None

def resolve_pick_ids(
    state: DraftState, events: Iterable[LoggedEvent], resolver: NameResolver
) -> DraftState:
    ...
```

Behavior:

- Build `overall -> (player_name, position, player_team)` from `pick_made` events' `data`
  (manual-paste keys, per `apps/extension/src/lib/parse.ts`: `player_name`, `position`,
  `player_team`).
- For each pick in `state.picks` with **`player_id is None`** AND a resolvable name: normalize the
  source position (`DEF`/`D/ST`/`DEFENSE` → `DST`, `PK` → `K`, upper-case; unknown → skip) and call
  `resolver(name, team, canonical_pos)`. On a hit, replace the pick with `player_id` filled (via
  `model_copy`). Picks that already carry an id are left untouched (keeps the out-of-scope `cbs:`
  capture path out of it; only `None` is filled).
- Unresolved names stay `None` and are **logged with a count**. A drafted-but-unmasked player is a
  real correctness gap, so it is surfaced (info-level summary `resolved=X unresolved=Y`), never
  silently swallowed. Return the same `state` object when nothing changed.

**Wiring (`api/app.py`):** construct one `app.state.crosswalk = Crosswalk(warehouse.app_sqlite)`
in `create_app`, and a small `_resolve_state(state, league_id)` helper that fetches the league's
events and calls `resolve_pick_ids(state, events, app.state.crosswalk.resolve_name)`. Call it at
the two sites that feed the engine, immediately before `rec_engine.recommend(...)`:

- `GET /recommendation` (events already fetched at the top of the handler — reuse them; applies
  after the audit/`team_id` state overrides).
- `publish_recommendation` (the `/recs/ws` push path; fetch events only in the branch that recomputes).

`recommend()` and `fold_state()` are untouched.

**Cost:** `resolve_name` checks an indexed `name_resolutions` cache first and only fuzzy-matches on
a miss (then caches), so a repeated board is O(1) after first sighting; ingest is low-rate. Picks
with an id (or no name) never invoke the resolver.

## Component 3 — Micro-fix: defer the rapidfuzz import in `_best_fuzzy_match`

The new resolution runs on every `GET /recommendation`. In a base ($0, no-`data`-extra) install a
name-only pick would reach `resolve_name → _best_fuzzy_match`, which currently imports `rapidfuzz`
**before** querying candidates → `ImportError` → **500** (today that path 503s). Fix: query the
`players` candidates first and `return None` early when there are none, importing `rapidfuzz` only
when there is something to score. Behavior-identical for the seeded path; removes the reachable 500.
An unseeded/empty players table (base install) legitimately means "no match" → `None`.

## Files touched

| File                                       | Change                                                                                                                          |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `backend/src/jaaffl/data/crosswalk.py`     | add `player_from_playerid_row` helper; `seed_from_playerids` uses it; reorder `_best_fuzzy_match` to defer the rapidfuzz import |
| `backend/src/jaaffl/providers/nflverse.py` | implement `players(season)` via the helper + `load_ff_playerids()`                                                              |
| `backend/src/jaaffl/ingest/resolve.py`     | NEW — `resolve_pick_ids` + source-position normalization                                                                        |
| `backend/src/jaaffl/ingest/__init__.py`    | export `resolve_pick_ids`                                                                                                       |
| `backend/src/jaaffl/api/app.py`            | construct `app.state.crosswalk`; wire `_resolve_state` into the two engine-feeding sites                                        |

**Not touched:** `engine/recommend.py`, `ingest/log.fold_state`, domain models, the E5 contract
(Zod/schemas/fixtures), `config/league.json`, `config/engine.json`, the provider registry.

## Testing plan (TDD, network-free by default)

**`test_provider_nflverse.py` (extend):**

- `players()` maps `load_ff_playerids` rows → `Player(gsis:…, name, position, nfl_team)`.
- skips rows without gsis; skips non-league positions (e.g. IDP `DE`); skips a malformed row
  without aborting the batch.
- the ids `players()` returns equal the canonical ids `seed_from_playerids` links (alignment).
- `ProviderError` when the `data` extra is absent (force `ImportError`, mirror `rankings()` test).

**`test_precompute.py` (extend):** a real `NflreadpyProvider.players()` (via `fake_nflreadpy`)
through `_registry_player_loader` returns a non-empty universe — the 503→universe flip at the
loader seam (no more `NotImplementedError → {}`).

**new `test_resolve.py`:**

- name-only pick + matching event → `player_id` filled by a fake resolver.
- already-resolved pick → untouched (resolver not consulted for it).
- unresolved name → stays `None` (and is logged; no crash).
- source position codes map (`DEF`→`DST`, `PK`→`K`).
- name-only pick with no name in events → skipped.

**`test_crosswalk.py` (extend):** `resolve_name` against an empty/unseeded `players` table returns
`None` without importing rapidfuzz (guards the base-install path).

**`test_api.py` (extend):** end-to-end — prime an engine whose universe includes a player, seed the
crosswalk `players` row, ingest a manual-paste pick (`"1. T1 - Christian McCaffrey, RB, SF"` shape)
→ `GET /recommendation` excludes that player (resolved-then-masked). Plus the 503 (unprimed) → 200
(primed) gate.

**one opt-in/slow integration test** (gated behind a marker; `pytest.importorskip("nflreadpy")`):
real `NflreadpyProvider(cx).players(2026)` pull asserts a non-empty list of well-formed `Player`s
whose ids start with `gsis:`. Excluded from the default `verify` run so the suite stays
network-free.

## Out of scope (later phases)

Web analytics panels + `GET /state`; calibration E1/E2/E3; Stage 7 assistant; the inert "Why?"
buttons; DST-universe coverage / alias map; README refresh; anything needing a key or the CBS
capture.
