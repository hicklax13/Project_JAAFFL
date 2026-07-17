"""Cross-source player identity (plan §2.7).

Every provider names players differently (CBS ids, nflverse GSIS ids, FantasyPros ids). The
crosswalk maps them all to one JAAFFL canonical ``player_id`` so projections and draft events
line up. Without it the engine cannot join a CBS pick to nflverse history.

Two stages over SQLite ``players`` + ``id_crosswalk`` (created by :func:`Warehouse.init`):

* **Stage A — deterministic** (``method='deterministic'``, confidence 1.0): seed from the
  nflverse ff_playerids crosswalk. The correct loader is **``nflreadpy.load_ff_playerids()``**
  — verified against nflreadpy 0.1.5, it returns the DynastyProcess ``db_playerids`` table
  whose 35 columns include ``cbs_id`` (plus ``gsis_id, pfr_id, sleeper_id, espn_id, yahoo_id,
  fantasypros_id``). ``load_players()`` is the nflverse player *dimension* and carries only
  ``gsis/esb/nfl/pfr/pff/otc/espn/smart`` ids — **no CBS id** — so it is NOT the seed.
  (Sources: nflreadpy 0.1.5 ``load_ffverse.py`` → ``dynastyprocess/data@master/files/
  db_playerids.csv``; https://nflreadr.nflverse.com/reference/load_ff_playerids.html.)
  Caveat: in 0.1.5 that table is a live CSV (not a pinned release) and ``cbs_id`` is nullable,
  so Stage A is a high-confidence seed, not a guaranteed hit for every CBS player — which is
  exactly why Stage B must cover CBS/FFC regardless.

* **Stage B — fuzzy** (``method='fuzzy'``, confidence=score): for ids absent from Stage A
  (CBS custom ids, FFC name-keyed rows, rookies). Normalize the name, require an exact
  position match and (team-agnostic for FAs) team match, then rank ``players`` candidates by
  ``rapidfuzz`` similarity; accept the best at/above τ (default 0.90, ``Settings``-tunable) and
  persist the audit trail (``name_score``, team/pos match, runners-up).

Precedence on conflict: ``manual`` > ``deterministic`` > highest-confidence ``fuzzy``. A manual
override (confidence 1.0) always wins and survives re-precompute (persisted, never recomputed
away).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ValidationError

from jaaffl.config import get_settings
from jaaffl.data.warehouse import open_app_db
from jaaffl.domain import Player, Position

# Positions this league can roster (domain.Position). Stage-A seed rows outside this set
# (e.g. db_playerids' DE/DT/CB/S defensive codes) are skipped — a standard 12-team snake with
# no IDP slots never drafts them, and both the enum and the SQLite CHECK reject them.
_VALID_POSITIONS = frozenset(p.value for p in Position)

# Method precedence: a lower-ranked method never overwrites a higher-ranked resolution.
_RANK = {"fuzzy": 1, "deterministic": 2, "manual": 3}

# Name suffixes stripped before fuzzy comparison (generational + numeric).
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Source team-code reconciliation. load_ff_playerids (DynastyProcess) uses 3-letter codes
# (SFO/NEP/GBP/…) while FFC and nflverse use standard 2–3 letter codes (SF/NE/GB/…). Without
# this, name+team fuzzy resolution exact-matches the raw strings and silently drops every player
# on a divergently-coded team (verified: CMC 'SFO'≠'SF', Mike Evans 'TBB'≠'TB'). Legacy
# relocations (OAK→LV, STL/RAM→LAR, SDC→LAC) fold to the current code.
_TEAM_ALIASES = {
    "GBP": "GB",
    "JAC": "JAX",
    "KCC": "KC",
    "LVR": "LV",
    "OAK": "LV",
    "NEP": "NE",
    "NOS": "NO",
    "SFO": "SF",
    "TBB": "TB",
    "SDC": "LAC",
    "STL": "LAR",
    "RAM": "LAR",
}
_FREE_AGENT_CODES = {"FA", "FA*", "NA", "NONE"}


def team_norm(team: str | None) -> str | None:
    """Canonicalize an NFL team code so divergent source schemes compare equal (DynastyProcess
    ``SFO`` vs FFC ``SF``). Free-agent / blank codes normalize to ``None`` (team-agnostic)."""
    if not team:
        return None
    code = team.strip().upper()
    if not code or code in _FREE_AGENT_CODES:
        return None
    return _TEAM_ALIASES.get(code, code)


# id_crosswalk.source ← ff_playerids column, for Stage-A deterministic seeding. Keys are the
# CHECK-constrained sources; values are the verified load_ff_playerids column names.
_SEED_SOURCES = {
    "gsis": "gsis_id",
    "pfr": "pfr_id",
    "cbs": "cbs_id",
    "sleeper": "sleeper_id",
    "espn": "espn_id",
    "yahoo": "yahoo_id",
    "fantasypros": "fantasypros_id",
}


def name_norm(name: str, position: str | None = None) -> str:
    """Fuzzy key: lowercase, strip punctuation and generational suffixes, collapse spaces.

    For DST, drop defense words and keep the team nickname token (stable across 'San
    Francisco 49ers' / '49ers'); exact team match is the real DST discriminator upstream.
    """
    text = re.sub(r"[^0-9a-z\s]", "", name.lower())
    tokens = [t for t in text.split() if t and t not in _SUFFIXES]
    if position and str(position).upper() == "DST":
        tokens = [t for t in tokens if t not in {"defense", "dst", "dest", "special", "teams"}]
        if tokens:
            tokens = [tokens[-1]]  # nickname
    return " ".join(tokens)


def player_from_playerid_row(row: Mapping) -> Player | None:
    """Map one ``load_ff_playerids()`` row to a canonical :class:`Player`, or ``None`` to skip.

    Canonical id = the stable ``gsis:<gsis_id>``. Rows without a gsis id, or whose position is
    outside this league's :data:`_VALID_POSITIONS` (db_playerids carries DE/DT/CB/S/... IDP codes),
    are skipped. This is the ONE mapper shared by :meth:`Crosswalk.seed_from_playerids` and
    ``NflreadpyProvider.players`` so the seeded ids and the loaded universe can never diverge.
    Returns ``None`` on a row that fails :class:`Player` validation, so one bad row can't abort
    a batch.
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


class Crosswalk:
    """Resolve source-specific ids to canonical JAAFFL player ids over SQLite."""

    def __init__(
        self, db_path: str | Path | None = None, *, fuzzy_threshold: float | None = None
    ) -> None:
        settings = get_settings()
        self.db_path = (
            Path(db_path) if db_path is not None else settings.jaaffl_data_dir / "app.sqlite"
        )
        self.threshold = (
            fuzzy_threshold
            if fuzzy_threshold is not None
            else settings.jaaffl_crosswalk_fuzzy_threshold
        )

    # --- resolution ------------------------------------------------------------------
    def resolve(self, source: str, source_id: str) -> str | None:
        """Return the canonical ``player_id`` for a ``(source, source_id)`` pair, if known
        (a single indexed PK lookup)."""
        conn = open_app_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT canonical_id FROM id_crosswalk WHERE source = ? AND source_id = ?",
                (source, source_id),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def resolve_or_link(
        self,
        source: str,
        source_id: str,
        *,
        name: str,
        position: str,
        nfl_team: str | None = None,
    ) -> str | None:
        """Stage A then Stage B: return an existing resolution, else fuzzy-match ``name`` (with
        exact ``position`` and, unless ``nfl_team`` is None, exact team) against ``players`` and
        persist the winner at/above τ. Returns the canonical id, or None if unresolved."""
        hit = self.resolve(source, source_id)
        if hit is not None:
            return hit
        canonical, features = self._best_fuzzy_match(name, position, nfl_team)
        if canonical is None:
            return None
        self.link(
            source,
            source_id,
            canonical,
            method="fuzzy",
            confidence=features["name_score"],
            match_features=features,
        )
        return canonical

    def resolve_name(self, name: str, team: str | None, pos: str) -> str | None:
        """Resolve a NAME-keyed source row (FFC ADP; CBS fuzzy fallback) to a canonical
        ``player_id`` via name+team+pos, persisting the hit so re-lookups are O(1).

        ``pos`` must already be a *canonical* position — callers map source codes first (the
        FFC adapter maps ``DEF``→``DST`` and ``PK``→``K``, else kickers/defenses would never
        match). ``team`` is the NFL team abbrev (upper-cased here) or ``None`` for team-agnostic
        (FA / unknown). Returns ``None`` when nothing matches at/above τ — the row is logged and
        SKIPPED by the caller, never raised. Only Stage-B *fuzzy* results land in the
        ``name_resolutions`` cache; a manual correction goes through the source-id path
        (:meth:`set_manual`), preserving manual > deterministic > fuzzy precedence overall."""
        key_norm = name_norm(name, pos)
        team_key = (team or "").upper()
        cached = self._resolve_name_cached(key_norm, team_key, pos)
        if cached is not None:
            return cached
        canonical, features = self._best_fuzzy_match(name, pos, team_key or None)
        if canonical is None:
            return None
        self._cache_name_resolution(key_norm, team_key, pos, canonical, features)
        return canonical

    def _resolve_name_cached(self, name_norm_value: str, team_key: str, pos: str) -> str | None:
        conn = open_app_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT canonical_id FROM name_resolutions"
                " WHERE name_norm = ? AND nfl_team = ? AND position = ?",
                (name_norm_value, team_key, pos),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def _cache_name_resolution(
        self, name_norm_value: str, team_key: str, pos: str, canonical_id: str, features: dict
    ) -> None:
        conn = open_app_db(self.db_path)
        try:
            conn.execute(
                "INSERT INTO name_resolutions"
                " (name_norm, nfl_team, position, canonical_id, confidence, match_features)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name_norm, nfl_team, position) DO UPDATE SET"
                "   canonical_id=excluded.canonical_id, confidence=excluded.confidence,"
                "   match_features=excluded.match_features,"
                "   resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (
                    name_norm_value,
                    team_key,
                    pos,
                    canonical_id,
                    features["name_score"],
                    json.dumps(features, sort_keys=True),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _best_fuzzy_match(
        self, name: str, position: str, nfl_team: str | None
    ) -> tuple[str | None, dict]:
        # Deferred so the base ($0) install imports crosswalk (and thus the API) without the
        # `data` extra; only actual fuzzy matching needs rapidfuzz (mirrors warehouse.py's
        # duckdb/polars deferral).
        from rapidfuzz import fuzz

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
        scored = sorted(
            (
                (fuzz.token_sort_ratio(norm, cand_norm) / 100.0, pid)
                for pid, cand_norm, _ in candidates
            ),
            reverse=True,
        )
        if not scored or scored[0][0] < self.threshold:
            return None, {}
        best_score, best_id = scored[0]
        features = {
            "name_score": round(best_score, 4),
            "pos_match": True,
            "team_match": target_team is not None,
            "runners_up": [{"player_id": pid, "score": round(s, 4)} for s, pid in scored[1:4]],
        }
        return best_id, features

    # --- writes ----------------------------------------------------------------------
    def upsert(self, player: Player) -> None:
        """Register/merge a player and its ``external_ids`` (as deterministic links)."""
        conn = open_app_db(self.db_path)
        try:
            self._upsert_player(conn, player)
            for source, source_id in player.external_ids.items():
                if source in _SEED_SOURCES:  # only CHECK-valid sources are linkable
                    self._link(conn, source, source_id, player.player_id, method="deterministic")
            conn.commit()
        finally:
            conn.close()

    def seed_from_playerids(self, rows: Iterable[Mapping]) -> int:
        """Stage A: seed ``players`` + deterministic ``id_crosswalk`` from ff_playerids rows
        (``load_ff_playerids().iter_rows(named=True)`` in Stage 4). Canonical id = the stable
        ``gsis:<gsis_id>``. Rows without a gsis id, or whose position is outside this league's
        :data:`_VALID_POSITIONS` (db_playerids carries DE/DT/CB/S/… IDP codes), are skipped —
        as is any row that fails validation, so one bad row can't abort the batch. Returns
        players seeded."""
        conn = open_app_db(self.db_path)
        seeded = 0
        try:
            for row in rows:
                player = player_from_playerid_row(row)  # shared mapper: skip rule + canonical id
                if player is None:  # no gsis / non-league position / invalid → skip this row
                    continue
                self._upsert_player(conn, player)
                for source, column in _SEED_SOURCES.items():
                    source_id = _clean(row.get(column))
                    if source_id is not None:
                        self._link(
                            conn, source, source_id, player.player_id, method="deterministic"
                        )
                seeded += 1
            conn.commit()
        finally:
            conn.close()
        return seeded

    def set_manual(self, source: str, source_id: str, canonical_id: str) -> None:
        """Persist a manual override (confidence 1.0). Wins over any automatic resolution and
        survives re-precompute (deterministic re-seeds never overwrite it)."""
        self.link(source, source_id, canonical_id, method="manual", confidence=1.0)

    def link(
        self,
        source: str,
        source_id: str,
        canonical_id: str,
        *,
        method: str,
        confidence: float = 1.0,
        match_features: dict | None = None,
    ) -> bool:
        """Write an ``id_crosswalk`` resolution honoring precedence (manual > deterministic >
        fuzzy; ties broken by confidence). Returns True if written, False if an equal/higher
        precedence row was preserved."""
        conn = open_app_db(self.db_path)
        try:
            written = self._link(
                conn,
                source,
                source_id,
                canonical_id,
                method=method,
                confidence=confidence,
                match_features=match_features,
            )
            conn.commit()
            return written
        finally:
            conn.close()

    # --- internals (share one connection/transaction) --------------------------------
    @staticmethod
    def _upsert_player(conn: sqlite3.Connection, player: Player) -> None:
        conn.execute(
            "INSERT INTO players (player_id, name, position, nfl_team, name_norm)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(player_id) DO UPDATE SET"
            "   name=excluded.name, position=excluded.position, nfl_team=excluded.nfl_team,"
            "   name_norm=excluded.name_norm,"
            "   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (
                player.player_id,
                player.name,
                str(player.position),
                player.nfl_team,
                name_norm(player.name, player.position),
            ),
        )

    @staticmethod
    def _link(
        conn: sqlite3.Connection,
        source: str,
        source_id: str,
        canonical_id: str,
        *,
        method: str,
        confidence: float = 1.0,
        match_features: dict | None = None,
    ) -> bool:
        existing = conn.execute(
            "SELECT method, confidence FROM id_crosswalk WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        if existing is not None:
            old_method, old_confidence = existing
            if _RANK[method] < _RANK[old_method]:
                return False  # never downgrade a higher-precedence resolution
            if _RANK[method] == _RANK[old_method] and confidence < old_confidence:
                return False  # same tier, strictly worse -> keep the incumbent
            # same tier, equal-or-better confidence -> latest wins (deterministic upstream
            # corrections apply; the DynastyProcess crosswalk is a live, unversioned CSV)
        conn.execute(
            "INSERT INTO id_crosswalk"
            " (source, source_id, canonical_id, method, confidence, match_features)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(source, source_id) DO UPDATE SET"
            "   canonical_id=excluded.canonical_id, method=excluded.method,"
            "   confidence=excluded.confidence, match_features=excluded.match_features,"
            "   resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (
                source,
                source_id,
                canonical_id,
                method,
                confidence,
                json.dumps(match_features, sort_keys=True) if match_features else None,
            ),
        )
        return True


def _clean(value: object) -> str | None:
    """Normalize a possibly-null/NaN/float id cell to a trimmed string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "na"}:
        return None
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text
