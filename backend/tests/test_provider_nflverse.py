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
from jaaffl.providers.base import ProviderError
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
    assert all(p.player_id.startswith("gsis:") for p in universe)
    positions = {p.position for p in universe}
    assert {Position.QB, Position.RB, Position.WR, Position.TE}.issubset(positions)
