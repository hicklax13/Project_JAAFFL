"""Cross-source ID resolution (plan §2.7). Two stages over SQLite ``players`` +
``id_crosswalk``:

* **Stage A — deterministic** nflverse-id join (``method='deterministic'``, conf 1.0),
  seeded from the ``load_ff_playerids`` crosswalk (the DynastyProcess table that carries
  ``cbs_id``; see crosswalk.py's module docstring).
* **Stage B — fuzzy** name+team+pos fallback (``method='fuzzy'``, conf=score) for ids absent
  from Stage A (CBS custom ids, FFC name-keyed rows, rookies).

Precedence on conflict: ``manual`` > ``deterministic`` > highest-confidence ``fuzzy``; a
manual override survives re-precompute.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jaaffl.data.crosswalk import Crosswalk, name_norm, player_from_playerid_row, team_norm
from jaaffl.data.warehouse import Warehouse
from jaaffl.domain import Player


@pytest.fixture
def cx(tmp_path: Path) -> Crosswalk:
    Warehouse(tmp_path).init()
    return Crosswalk(tmp_path / "app.sqlite", fuzzy_threshold=0.90)


def _crosswalk_row(db: Path, source: str, source_id: str) -> tuple:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT canonical_id, method, confidence, match_features"
            " FROM id_crosswalk WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()
    finally:
        conn.close()


def player(
    pid: str, name: str, pos: str = "WR", team: str | None = "DAL", ext: dict | None = None
) -> Player:
    return Player(player_id=pid, name=name, position=pos, nfl_team=team, external_ids=ext or {})


def playerid_row(**over) -> dict:
    row = {
        "gsis_id": "00-0034796",
        "cbs_id": "2181292",
        "pfr_id": "LambCe00",
        "sleeper_id": "6786",
        "espn_id": "4241389",
        "yahoo_id": "32692",
        "fantasypros_id": "17246",
        "name": "CeeDee Lamb",
        "position": "WR",
        "team": "DAL",
    }
    row.update(over)
    return row


# --- player_from_playerid_row (shared seed/universe mapper) ---------------------------


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


def test_player_from_playerid_row_keeps_idp_positions_in_enum() -> None:
    # LB/DL/DB are IDP extras that ARE in the domain Position enum, so the shared mapper KEEPS them
    # (universe and seed stay aligned by construction). Inert downstream: no ECR/projection join for
    # them in this non-IDP league, so they never become candidates. Pins the deliberate choice.
    p = player_from_playerid_row(playerid_row(gsis_id="00-lb", position="LB", name="A Linebacker"))
    assert p is not None and p.position == "LB"


def test_player_from_playerid_row_aliases_pk_to_canonical_k() -> None:
    """REGRESSION: db_playerids spells kicker ``PK``, the domain spells it ``K``.

    Verified against the live table (nflreadpy 0.1.5, 2026-07-25): position=='PK' has 282 rows
    (151 with a gsis_id) and position=='K' has ZERO — so an un-aliased ``_VALID_POSITIONS``
    check silently dropped EVERY kicker from both the seed and the player universe.
    """
    p = player_from_playerid_row(
        playerid_row(gsis_id="00-0040074", position="PK", name="Tyler Loop", team="BAL")
    )
    assert p is not None, "a PK row must not be skipped — it is this league's kicker"
    assert p.position == "K"
    assert p.player_id == "gsis:00-0040074"


def test_player_from_playerid_row_skips_punters_despite_pk_alias() -> None:
    """``PN`` (punter, 217 live rows) is NOT a kicker and must stay skipped — a sloppy
    'anything kicker-ish -> K' alias would flood the universe with unrosterable punters."""
    assert player_from_playerid_row(playerid_row(gsis_id="00-pn", position="PN")) is None


# --- name_norm -----------------------------------------------------------------------


def test_name_norm_strips_suffix_and_punctuation() -> None:
    assert name_norm("Michael Pittman Jr.") == "michael pittman"
    assert name_norm("D'Andre Swift") == "dandre swift"
    assert name_norm("Patrick Mahomes II") == "patrick mahomes"


# --- team_norm: reconcile divergent source team codes --------------------------------


def test_team_norm_canonicalizes_divergent_source_codes() -> None:
    # load_ff_playerids (DynastyProcess) uses 3-letter codes; FFC/nflverse use standard.
    assert team_norm("SFO") == team_norm("SF") == "SF"
    assert team_norm("GBP") == "GB"
    assert team_norm("JAC") == "JAX"
    assert team_norm("KCC") == "KC"
    assert team_norm("LVR") == team_norm("OAK") == "LV"
    assert team_norm("STL") == team_norm("RAM") == "LAR"
    assert team_norm("SDC") == "LAC"
    assert team_norm("PHI") == "PHI"  # already-standard codes pass through


def test_team_norm_treats_free_agent_and_blank_as_none() -> None:
    assert team_norm(None) is None
    assert team_norm("FA") is None
    assert team_norm("") is None


# --- resolve / upsert (Stage A surface) ----------------------------------------------


def test_resolve_unknown_returns_none(cx: Crosswalk) -> None:
    assert cx.resolve("cbs", "does-not-exist") is None


def test_upsert_registers_external_ids(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:00-1", "CeeDee Lamb", ext={"cbs": "111", "gsis": "00-1"}))
    assert cx.resolve("cbs", "111") == "gsis:00-1"
    assert cx.resolve("gsis", "00-1") == "gsis:00-1"


def test_seed_from_playerids_creates_deterministic_links(cx: Crosswalk) -> None:
    seeded = cx.seed_from_playerids([playerid_row()])
    assert seeded == 1
    assert cx.resolve("cbs", "2181292") == "gsis:00-0034796"
    assert cx.resolve("fantasypros", "17246") == "gsis:00-0034796"
    row = _crosswalk_row(cx.db_path, "cbs", "2181292")
    assert row is not None
    assert row[1] == "deterministic"
    assert row[2] == 1.0


def test_seed_skips_rows_without_gsis(cx: Crosswalk) -> None:
    assert cx.seed_from_playerids([playerid_row(gsis_id=None)]) == 0


def test_seed_skips_non_enum_positions_without_aborting_batch(cx: Crosswalk) -> None:
    """Real db_playerids carries IDP codes (DE/DT/CB/S) outside this league's positions. Such
    a row is skipped, not fatal — the valid rows in the same batch still seed (one bad row must
    not roll the whole batch back to zero)."""
    seeded = cx.seed_from_playerids(
        [
            playerid_row(gsis_id="00-de", cbs_id="c-de", position="DE", name="Some Lineman"),
            playerid_row(gsis_id="00-wr", cbs_id="c-wr", position="WR", name="A Receiver"),
        ]
    )
    assert seeded == 1
    assert cx.resolve("cbs", "c-wr") == "gsis:00-wr"
    assert cx.resolve("cbs", "c-de") is None  # defensive lineman skipped


def test_seed_from_playerids_lands_kickers_in_the_players_table(cx: Crosswalk) -> None:
    """REGRESSION (db-level): a freshly seeded ``players`` table must contain kickers.

    This is the exact query that exposed the bug — it returned 0 against a real seed because
    db_playerids' ``PK`` code never matched the domain's ``K``.
    """
    seeded = cx.seed_from_playerids(
        [
            playerid_row(gsis_id="00-loop", cbs_id="c-k", position="PK", name="Tyler Loop"),
            playerid_row(gsis_id="00-wr", cbs_id="c-wr", position="WR", name="A Receiver"),
        ]
    )
    assert seeded == 2
    conn = sqlite3.connect(cx.db_path)
    try:
        kickers = conn.execute("SELECT COUNT(*) FROM players WHERE position='K'").fetchone()[0]
    finally:
        conn.close()
    assert kickers == 1, "seeded players table has no kickers"
    # The kicker is reachable by its CBS id too, so a live CBS kicker pick can resolve.
    assert cx.resolve("cbs", "c-k") == "gsis:00-loop"


# --- Stage B fuzzy fallback ----------------------------------------------------------


def test_fuzzy_resolves_a_misspelled_name(cx: Crosswalk) -> None:
    """A CBS id absent from Stage A resolves via name+team+pos ≥ τ (intentional misspelling)."""
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    resolved = cx.resolve_or_link(
        "cbs", "cbs-QB-77", name="Patrick Mahommes", position="QB", nfl_team="KC"
    )
    assert resolved == "gsis:mahomes"
    row = _crosswalk_row(cx.db_path, "cbs", "cbs-QB-77")
    assert row[1] == "fuzzy"
    assert 0.90 <= row[2] <= 1.0
    features = json.loads(row[3])
    assert features["pos_match"] is True and features["team_match"] is True
    assert "name_score" in features


def test_fuzzy_below_threshold_stays_unresolved(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    assert (
        cx.resolve_or_link("cbs", "cbs-QB-99", name="Aaron Rodgers", position="QB", nfl_team="KC")
        is None
    )
    assert _crosswalk_row(cx.db_path, "cbs", "cbs-QB-99") is None


def test_fuzzy_requires_exact_position(cx: Crosswalk) -> None:
    """Same name, wrong position must NOT match — positions are hard constraints."""
    cx.upsert(player("gsis:aj", "AJ Brown", pos="WR", team="PHI"))
    assert (
        cx.resolve_or_link("cbs", "cbs-1", name="AJ Brown", position="RB", nfl_team="PHI") is None
    )


def test_fuzzy_is_team_agnostic_for_free_agents(cx: Crosswalk) -> None:
    """A None team (FA / unknown) matches regardless of the candidate's team."""
    cx.upsert(player("gsis:kicker", "Justin Tucker", pos="K", team="BAL"))
    assert (
        cx.resolve_or_link("cbs", "cbs-K-1", name="Justin Tucker", position="K", nfl_team=None)
        == "gsis:kicker"
    )


def test_resolve_or_link_hits_stage_a_first(cx: Crosswalk) -> None:
    """A known deterministic id resolves by PK without ever running the fuzzy stage."""
    cx.seed_from_playerids([playerid_row()])
    resolved = cx.resolve_or_link(
        "cbs", "2181292", name="literally anything", position="QB", nfl_team="ZZZ"
    )
    assert resolved == "gsis:00-0034796"
    assert _crosswalk_row(cx.db_path, "cbs", "2181292")[1] == "deterministic"


def test_fuzzy_result_persists_for_o1_relookup(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    cx.resolve_or_link("cbs", "cbs-QB-77", name="Patrick Mahommes", position="QB", nfl_team="KC")
    assert cx.resolve("cbs", "cbs-QB-77") == "gsis:mahomes"  # persisted → next lookup is O(1)


# --- precedence: manual > deterministic > fuzzy --------------------------------------


def test_manual_override_wins_over_deterministic(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:A", "Player A"))
    cx.upsert(player("gsis:B", "Player B"))
    cx.link("cbs", "77", "gsis:A", method="deterministic")
    cx.set_manual("cbs", "77", "gsis:B")
    assert cx.resolve("cbs", "77") == "gsis:B"


def test_manual_override_survives_reseed(cx: Crosswalk) -> None:
    """A manual decision is never recomputed away by a later deterministic re-seed."""
    cx.upsert(player("gsis:00-0034796", "CeeDee Lamb"))  # so the manual FK target exists
    cx.upsert(player("gsis:manual", "Manual Target"))
    cx.set_manual("cbs", "2181292", "gsis:manual")
    # a deterministic re-seed would otherwise map cbs 2181292 -> gsis:00-0034796
    cx.seed_from_playerids([playerid_row()])
    assert cx.resolve("cbs", "2181292") == "gsis:manual"


def test_deterministic_overwrites_fuzzy(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:A", "Player A"))
    cx.upsert(player("gsis:B", "Player B"))
    cx.link("cbs", "77", "gsis:A", method="fuzzy", confidence=0.93)
    cx.link("cbs", "77", "gsis:B", method="deterministic")
    assert cx.resolve("cbs", "77") == "gsis:B"


def test_deterministic_reseed_applies_upstream_correction(cx: Crosswalk) -> None:
    """Same-tier latest-wins: a deterministic re-seed that remaps an id (the DynastyProcess
    crosswalk is a live CSV) updates the resolution; it is not frozen at first-seen."""
    cx.upsert(player("gsis:A", "Player A"))
    cx.upsert(player("gsis:B", "Player B"))
    assert cx.link("cbs", "77", "gsis:A", method="deterministic") is True
    assert cx.link("cbs", "77", "gsis:B", method="deterministic") is True
    assert cx.resolve("cbs", "77") == "gsis:B"


def test_fuzzy_never_downgrades_deterministic(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:A", "Player A"))
    cx.upsert(player("gsis:B", "Player B"))
    cx.link("cbs", "77", "gsis:A", method="deterministic")
    linked = cx.link("cbs", "77", "gsis:B", method="fuzzy", confidence=0.99)
    assert linked is False
    assert cx.resolve("cbs", "77") == "gsis:A"


# --- resolve_name: name-keyed fuzzy surface for FFC/CBS (plan §4.4) -------------------


def _name_row(db: Path, name_norm_value: str, team: str, pos: str) -> tuple:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT canonical_id, confidence FROM name_resolutions"
            " WHERE name_norm=? AND nfl_team=? AND position=?",
            (name_norm_value, team, pos),
        ).fetchone()
    finally:
        conn.close()


def test_resolve_name_matches_by_name_team_pos(cx: Crosswalk) -> None:
    """FFC rows carry no stable id, so they resolve by name+team+pos (≥ τ, misspelling ok)."""
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    assert cx.resolve_name("Patrick Mahommes", "KC", "QB") == "gsis:mahomes"


def test_resolve_name_unresolved_returns_none_not_raise(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    assert cx.resolve_name("Totally Different Guy", "KC", "QB") is None


def test_resolve_name_persists_for_o1_relookup(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    assert cx.resolve_name("Patrick Mahommes", "KC", "QB") == "gsis:mahomes"
    row = _name_row(cx.db_path, name_norm("Patrick Mahommes", "QB"), "KC", "QB")
    assert row is not None
    assert row[0] == "gsis:mahomes"
    assert 0.90 <= row[1] <= 1.0


def test_resolve_name_cached_hit_survives_player_deletion(cx: Crosswalk) -> None:
    """A persisted resolution is served O(1) from cache — proven by deleting the underlying
    player row and confirming the cached canonical still returns."""
    cx.upsert(player("gsis:mahomes", "Patrick Mahomes", pos="QB", team="KC"))
    assert cx.resolve_name("Patrick Mahomes", "KC", "QB") == "gsis:mahomes"
    conn = sqlite3.connect(cx.db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")  # keep the cache row; drop only the player
        conn.execute("DELETE FROM players WHERE player_id='gsis:mahomes'")
        conn.commit()
    finally:
        conn.close()
    assert cx.resolve_name("Patrick Mahomes", "KC", "QB") == "gsis:mahomes"


def test_resolve_name_team_agnostic_when_team_none(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:kicker", "Justin Tucker", pos="K", team="BAL"))
    assert cx.resolve_name("Justin Tucker", None, "K") == "gsis:kicker"


def test_resolve_name_requires_exact_position(cx: Crosswalk) -> None:
    cx.upsert(player("gsis:aj", "AJ Brown", pos="WR", team="PHI"))
    assert cx.resolve_name("AJ Brown", "PHI", "RB") is None


def test_resolve_name_matches_across_divergent_team_code_schemes(cx: Crosswalk) -> None:
    """The seed stores DynastyProcess 'SFO'/'TBB'; FFC/CBS send standard 'SF'/'TB'. Exact-string
    team matching would drop top players (CMC, Mike Evans) — team_norm reconciles both sides."""
    cx.upsert(player("gsis:cmc", "Christian McCaffrey", pos="RB", team="SFO"))
    cx.upsert(player("gsis:evans", "Mike Evans", pos="WR", team="TBB"))
    assert cx.resolve_name("Christian McCaffrey", "SF", "RB") == "gsis:cmc"
    assert cx.resolve_name("Mike Evans", "TB", "WR") == "gsis:evans"


def test_resolve_or_link_matches_across_divergent_team_code_schemes(cx: Crosswalk) -> None:
    # The CBS fuzzy fallback (resolve_or_link -> _best_fuzzy_match) benefits from the same fix.
    cx.upsert(player("gsis:jacobs", "Josh Jacobs", pos="RB", team="GBP"))
    assert (
        cx.resolve_or_link("cbs", "c-jj", name="Josh Jacobs", position="RB", nfl_team="GB")
        == "gsis:jacobs"
    )


def test_resolve_name_resolves_dst_by_nickname_token(cx: Crosswalk) -> None:
    """DST names normalize to the nickname token, so '<Nickname> Defense' aligns with the
    canonical '<City> <Nickname>'. (FFC's '<City> Defense' form is a known lower-coverage
    case handled by skip-if-unresolved in the FFC adapter.)"""
    cx.upsert(player("gsis:sea", "Seattle Seahawks", pos="DST", team="SEA"))
    assert cx.resolve_name("Seahawks Defense", "SEA", "DST") == "gsis:sea"


def test_resolve_name_on_empty_table_returns_none_without_rapidfuzz(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    """A base ($0) install with an unseeded players table must resolve to None without importing
    rapidfuzz (which the data extra provides) — else the API resolution path would 500."""
    import sys

    monkeypatch.setitem(sys.modules, "rapidfuzz", None)  # force ImportError if imported
    assert cx.resolve_name("Nobody Here", "SF", "WR") is None
