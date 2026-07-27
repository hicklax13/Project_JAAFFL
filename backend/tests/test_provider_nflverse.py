"""NflreadpyProvider.rankings() + crosswalk seed (plan §4.3).

Ground-truth [VERIFY], closed 2026-07-16 against nflreadpy 0.1.5:
* load_ff_rankings() has NO season/week columns — it is one live FantasyPros scrape. The
  non-IDP redraft board is ``page_type == 'redraft-overall'`` (491 rows, {QB,RB,WR,TE,K,DST}).
* ``cbs_id`` is ~100% null on that board; the reliable join key is ``id`` (FantasyPros id) ->
  resolve('fantasypros', id) (~80% coverage), with a name+team+pos fuzzy fallback for the
  rest (2026 rookies, team DSTs). Everything unresolved is skipped, never raised.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest

from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import Player, Position
from jaaffl.providers.base import Capability, ProviderError
from jaaffl.providers.nflverse import NflreadpyProvider
from tests.test_providers import fake_nflreadpy


@pytest.fixture
def cx(tmp_path: Path) -> Crosswalk:
    Warehouse(tmp_path).init()
    return Crosswalk(tmp_path / "app.sqlite", fuzzy_threshold=0.90)


def _playerid_row(**over: object) -> dict:
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


def _team_rows(*abbrs: str) -> pl.DataFrame:
    """A load_teams()-shaped frame. Real column names verified against nflreadpy 0.1.5."""
    names = {
        "SF": "San Francisco 49ers",
        "BAL": "Baltimore Ravens",
        "JAX": "Jacksonville Jaguars",
        "OAK": "Oakland Raiders",  # legacy -> LV
        "SD": "San Diego Chargers",  # legacy -> LAC
        "STL": "St. Louis Rams",  # legacy -> LAR
        "LA": "Los Angeles Rams",  # legacy duplicate of LAR
        "LV": "Las Vegas Raiders",
        "LAC": "Los Angeles Chargers",
        "LAR": "Los Angeles Rams",
    }
    return pl.DataFrame(
        [{"team_abbr": a, "team_name": names.get(a, f"{a} Team"), "team_nick": a} for a in abbrs]
    )


def _rank_row(**over: object) -> dict:
    row = {
        "page_type": "redraft-overall",
        "player": "CeeDee Lamb",
        "id": 17246,
        "pos": "WR",
        "team": "DAL",
        "ecr": 8.8,
    }
    row.update(over)
    return row


def test_seed_crosswalk_pulls_playerids_and_links(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    df = pl.DataFrame([_playerid_row()])
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    seeded = NflreadpyProvider(crosswalk=cx).seed_crosswalk()
    assert seeded == 1
    assert cx.resolve("fantasypros", "17246") == "gsis:00-0034796"
    assert cx.resolve("cbs", "2181292") == "gsis:00-0034796"


def test_rankings_resolves_via_fantasypros_id(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    cx.seed_from_playerids(
        [
            _playerid_row(
                fantasypros_id="19788", gsis_id="00-chase", name="Ja'Marr Chase", team="CIN"
            )
        ]
    )
    df = pl.DataFrame([_rank_row(player="Ja'Marr Chase", id=19788, team="CIN", ecr=1.6)])
    fake_nflreadpy(monkeypatch, load_ff_rankings=lambda: df)
    assert NflreadpyProvider(crosswalk=cx).rankings(2026) == {"gsis:00-chase": 1.6}


def test_rankings_excludes_non_redraft_overall_boards(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    cx.seed_from_playerids(
        [
            _playerid_row(
                fantasypros_id="19788", gsis_id="00-chase", name="Ja'Marr Chase", team="CIN"
            )
        ]
    )
    df = pl.DataFrame(
        [
            _rank_row(player="Ja'Marr Chase", id=19788, team="CIN", ecr=1.6),
            _rank_row(
                page_type="dynasty-overall", player="Ja'Marr Chase", id=19788, team="CIN", ecr=1.0
            ),
            _rank_row(
                page_type="redraft-idp",
                player="Some Linebacker",
                id=99999,
                pos="LB",
                team="XX",
                ecr=2.0,
            ),
        ]
    )
    fake_nflreadpy(monkeypatch, load_ff_rankings=lambda: df)
    # Only the redraft-overall Chase row survives (dynasty duplicate + IDP board excluded).
    assert NflreadpyProvider(crosswalk=cx).rankings(2026) == {"gsis:00-chase": 1.6}


def test_rankings_falls_back_to_name_when_id_unmapped(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    # A 2026 rookie absent from playerids: no fantasypros link, resolves by name+team+pos.
    cx.upsert(Player(player_id="gsis:rook", name="Jordyn Tyson", position="WR", nfl_team="NO"))
    df = pl.DataFrame([_rank_row(player="Jordyn Tyson", id=88888, team="NO", ecr=40.0)])
    fake_nflreadpy(monkeypatch, load_ff_rankings=lambda: df)
    assert NflreadpyProvider(crosswalk=cx).rankings(2026) == {"gsis:rook": 40.0}


def test_rankings_skips_unresolved_rows(monkeypatch: pytest.MonkeyPatch, cx: Crosswalk) -> None:
    df = pl.DataFrame([_rank_row(player="Ghost Player", id=77777, team="ZZ", ecr=50.0)])
    fake_nflreadpy(monkeypatch, load_ff_rankings=lambda: df)
    assert NflreadpyProvider(crosswalk=cx).rankings(2026) == {}  # skipped, not raised


def test_rankings_raises_provider_error_without_data_extra(
    monkeypatch: pytest.MonkeyPatch, cx: Crosswalk
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "nflreadpy", None)  # force ImportError on `import nflreadpy`
    with pytest.raises(ProviderError):
        NflreadpyProvider(crosswalk=cx).rankings(2026)


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


def test_players_includes_kickers_from_pk_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION: db_playerids spells kicker ``PK`` (282 live rows) and never ``K`` (0 rows),
    so the un-aliased position gate emptied the live universe of every kicker — the engine
    could not rank or roster one, and the K punt-guard/stream-round logic never fired."""
    df = pl.DataFrame(
        [
            _playerid_row(),  # CeeDee Lamb WR DAL
            _playerid_row(gsis_id="00-0040074", name="Tyler Loop", position="PK", team="BAL"),
        ]
    )
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    universe = NflreadpyProvider().players(2026)
    kickers = [p for p in universe if p.position == Position.K]
    assert len(kickers) == 1, "player universe has no kickers"
    assert (kickers[0].name, kickers[0].player_id) == ("Tyler Loop", "gsis:00-0040074")


def test_players_includes_team_defenses(monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION: ff_playerids has NO team-defense rows (verified 2026-07-25: 0 for each of
    DST/DEF/D/ST), so the universe carried no DST at all and the engine could not roster the
    DST=1 starter this league requires. Defenses come from the separate load_teams() table."""
    fake_nflreadpy(
        monkeypatch,
        load_ff_playerids=lambda: pl.DataFrame([_playerid_row()]),
        load_teams=lambda: _team_rows("SF", "BAL"),
    )
    universe = NflreadpyProvider().players(2026)
    defenses = {p.player_id: p for p in universe if p.position == Position.DST}
    assert set(defenses) == {"dst:SF", "dst:BAL"}
    assert defenses["dst:SF"].name == "San Francisco 49ers"
    assert defenses["dst:SF"].nfl_team == "SF"
    # The people universe is unaffected — defenses are additive, never a replacement.
    assert any(p.player_id == "gsis:00-0034796" for p in universe)


def test_players_excludes_relocated_duplicate_team_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_teams() returns 36 rows: 32 current franchises + 4 legacy/relocation duplicates
    (OAK, SD, STL, LA). Keeping those would let ONE defense be drafted twice under two ids."""
    fake_nflreadpy(
        monkeypatch,
        load_ff_playerids=lambda: pl.DataFrame([_playerid_row()]),
        load_teams=lambda: _team_rows("LV", "OAK", "LAC", "SD", "LAR", "STL", "LA"),
    )
    universe = NflreadpyProvider().players(2026)
    assert {p.player_id for p in universe if p.position == Position.DST} == {
        "dst:LV",
        "dst:LAC",
        "dst:LAR",
    }


def test_seed_crosswalk_seeds_team_defenses(monkeypatch: pytest.MonkeyPatch, cx: Crosswalk) -> None:
    """A live CBS defense pick resolves by name+team+pos against ``players``. That fuzzy path
    can only match a row that EXISTS, so the seed must register defenses too — otherwise a
    drafted DST stays unmasked in the candidate pool."""
    fake_nflreadpy(
        monkeypatch,
        load_ff_playerids=lambda: pl.DataFrame([_playerid_row()]),
        load_teams=lambda: _team_rows("SF"),
    )
    NflreadpyProvider(crosswalk=cx).seed_crosswalk()
    # CBS spells a defense many ways; name_norm's DST branch collapses each to the nickname.
    assert cx.resolve_name("San Francisco 49ers", "SF", "DST") == "dst:SF"
    assert cx.resolve_name("49ers", "SF", "DST") == "dst:SF"


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


def test_players_ids_match_seed_canonical(monkeypatch: pytest.MonkeyPatch, cx: Crosswalk) -> None:
    """The universe id equals the seeded canonical id equals what rankings() resolves to."""
    df = pl.DataFrame([_playerid_row()])
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: df)
    provider = NflreadpyProvider(crosswalk=cx)
    provider.seed_crosswalk()
    universe = provider.players(2026)
    assert universe[0].player_id == cx.resolve("fantasypros", "17246") == "gsis:00-0034796"


def test_players_raises_provider_error_without_data_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "nflreadpy", None)  # force ImportError on `import nflreadpy`
    with pytest.raises(ProviderError):
        NflreadpyProvider().players(2026)


@pytest.mark.skipif(
    not os.environ.get("JAAFFL_RUN_NETWORK_TESTS"),
    reason="opt-in: real nflverse network pull; set JAAFFL_RUN_NETWORK_TESTS=1 to run",
)
def test_players_real_nflverse_pull_returns_universe() -> None:
    pytest.importorskip("nflreadpy")
    universe = NflreadpyProvider().players(2026)
    assert len(universe) > 100  # a real universe is thousands of players
    # Two canonical namespaces: people are gsis:<gsis_id>, team defenses are dst:<team_abbr>
    # (a team has no gsis id, so reusing that prefix would falsely imply one).
    assert all(p.player_id.startswith(("gsis:", "dst:")) for p in universe)
    assert all(p.player_id.startswith("dst:") == (p.position == Position.DST) for p in universe), (
        "the dst: namespace and the DST position must agree exactly"
    )
    positions = {p.position for p in universe}
    # Every position this league STARTS is asserted against the REAL feed on purpose. K and DST
    # are the two that broke: K because db_playerids spells it PK (alias drift), DST because
    # db_playerids has no team rows at all (source gap, filled from load_teams). An earlier
    # version of this assertion covered only QB/RB/WR/TE, which is why both went unnoticed.
    assert {
        Position.QB,
        Position.RB,
        Position.WR,
        Position.TE,
        Position.K,
        Position.DST,
    }.issubset(positions)
    # Exactly the 32 current franchises — no legacy OAK/SD/STL/LA duplicate defenses.
    assert len([p for p in universe if p.position == Position.DST]) == 32


def test_schedule_returns_regular_season_rows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Playoff rows would extend the week span and make almost every team look multi-bye, which
    `league.schedule.bye_weeks` then reports as NO bye at all — a silently empty chip."""
    import polars as pl

    df = pl.DataFrame(
        {
            "season": [2026, 2026, 2026],
            "game_type": ["REG", "REG", "WC"],
            "week": [1, 2, 19],
            "home_team": ["SEA", "BUF", "SEA"],
            "away_team": ["BUF", "KC", "KC"],
        }
    )
    fake_nflreadpy(monkeypatch, load_schedules=lambda seasons: df)

    games = NflreadpyProvider().schedule(2026)

    assert games == [(1, "SEA", "BUF"), (2, "BUF", "KC")]  # the WC row is dropped
    assert Capability.SCHEDULE in NflreadpyProvider().capabilities
