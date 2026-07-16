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

from jaaffl.data.crosswalk import Crosswalk, name_norm
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


# --- name_norm -----------------------------------------------------------------------


def test_name_norm_strips_suffix_and_punctuation() -> None:
    assert name_norm("Michael Pittman Jr.") == "michael pittman"
    assert name_norm("D'Andre Swift") == "dandre swift"
    assert name_norm("Patrick Mahomes II") == "patrick mahomes"


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
