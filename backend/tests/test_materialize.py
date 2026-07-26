"""Stage-4 ADP materialization (plan §2.4/§2.8/§4): FFC ADP -> canonical Parquet -> DuckDB adp.

Split respects the store roles: ``refresh_adp`` does the network pull + canonical resolution and
writes a Parquet snapshot; ``Warehouse.materialize()`` (what ``make warehouse`` runs) loads that
Parquet into the DISPOSABLE DuckDB ``adp`` table with NO network and NO wall-clock in its output,
so a rebuild reproduces it byte-for-byte for fixed inputs. ``projections`` stays empty (Stage 5).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from jaaffl.config import Settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.data.warehouse import rebuild_warehouse
from jaaffl.domain import Player
from jaaffl.materialize import refresh_adp
from jaaffl.providers.ffc import FantasyFootballCalculatorProvider

FIXTURES = Path(__file__).parent / "fixtures" / "ffc"
CAPTURED = date(2026, 7, 16)
SEEDED = {"gsis:gibbs", "gsis:nacua", "gsis:allen", "gsis:mcbride", "gsis:sea-dst", "gsis:aubrey"}


def _ffc(settings: Settings, cx: Crosswalk) -> FantasyFootballCalculatorProvider:
    payload = json.loads((FIXTURES / "adp_standard_12_2026.json").read_text(encoding="utf-8"))
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    )
    return FantasyFootballCalculatorProvider(settings, cx, client=client)


@pytest.fixture
def env(tmp_path: Path) -> tuple[Settings, Warehouse, Crosswalk]:
    settings = Settings(jaaffl_data_dir=tmp_path, jaaffl_season=2026)
    wh = Warehouse(tmp_path)
    wh.init()
    cx = Crosswalk(tmp_path / "app.sqlite")
    for pid, name, pos, team in [
        ("gsis:gibbs", "Jahmyr Gibbs", "RB", "DET"),
        ("gsis:nacua", "Puka Nacua", "WR", "LAR"),
        ("gsis:allen", "Josh Allen", "QB", "BUF"),
        ("gsis:mcbride", "Trey McBride", "TE", "ARI"),
        ("gsis:sea-dst", "Seattle Defense", "DST", "SEA"),
        ("gsis:aubrey", "Brandon Aubrey", "K", "DAL"),
    ]:
        cx.upsert(Player(player_id=pid, name=name, position=pos, nfl_team=team))
    return settings, wh, cx


def _adp_rows(wh: Warehouse) -> list[tuple]:
    con = wh._duckdb_connect()
    try:
        return con.execute(
            "SELECT player_id, adp, stdev, season, scoring, teams, bye, captured_at"
            " FROM adp ORDER BY player_id"
        ).fetchall()
    finally:
        con.close()


def _count(wh: Warehouse, table: str) -> int:
    con = wh._duckdb_connect()
    try:
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_refresh_adp_writes_canonical_dated_parquet(env: tuple) -> None:
    settings, wh, cx = env
    path = refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=CAPTURED,
    )
    assert path is not None and path.exists()
    df = wh.scan_parquet("ffc/adp_standard_12_2026_20260716")  # dated: ADP drifts, keep the series
    assert set(df["player_id"].to_list()) == SEEDED  # canonical ids, not raw FFC names/ids
    assert set(df["captured_at"].to_list()) == {CAPTURED}


def test_refresh_adp_dated_snapshots_accumulate_a_series(env: tuple) -> None:
    """ADP drifts through preseason, so each day's pull is its own dated Parquet — a re-run must
    NOT overwrite the prior day (the DuckDB adp PK includes captured_at to hold the series)."""
    settings, wh, cx = env
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=date(2026, 7, 16),
    )
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=date(2026, 7, 17),
    )
    files = sorted((wh.parquet_dir / "ffc").glob("adp_*.parquet"))
    assert len(files) == 2  # two dated files, neither overwritten
    wh.materialize()
    rows = _adp_rows(wh)
    assert len(rows) == 12  # 6 players x 2 capture dates
    gibbs_dates = {r[7] for r in rows if r[0] == "gsis:gibbs"}
    assert gibbs_dates == {date(2026, 7, 16), date(2026, 7, 17)}


def test_materialize_loads_adp_into_duckdb(env: tuple) -> None:
    settings, wh, cx = env
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=CAPTURED,
    )
    wh.materialize()
    rows = _adp_rows(wh)
    assert len(rows) == 6
    gibbs = next(r for r in rows if r[0] == "gsis:gibbs")
    assert gibbs[1] == 1.7  # adp
    assert gibbs[2] == 0.9  # stdev (the survival input)
    assert gibbs[3] == 2026  # season
    assert gibbs[4] == "standard"
    assert gibbs[5] == 12
    assert gibbs[7] == CAPTURED


def test_projections_stays_empty(env: tuple) -> None:
    settings, wh, cx = env
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=CAPTURED,
    )
    wh.materialize()
    assert _count(wh, "projections") == 0  # μ/σ/floor/ceiling are Stage 5


def test_rebuild_reproduces_adp_for_fixed_parquet(env: tuple) -> None:
    settings, wh, cx = env
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=CAPTURED,
    )
    rebuild_warehouse(settings.jaaffl_data_dir)
    first = _adp_rows(wh)
    rebuild_warehouse(settings.jaaffl_data_dir)
    second = _adp_rows(wh)
    assert first == second  # no wall-clock in materialize's output -> byte-identical rebuild
    assert len(first) == 6


def test_materialize_is_idempotent(env: tuple) -> None:
    settings, wh, cx = env
    refresh_adp(
        2026,
        settings=settings,
        warehouse=wh,
        crosswalk=cx,
        providers=[_ffc(settings, cx)],
        captured_at=CAPTURED,
    )
    wh.materialize()
    wh.materialize()  # second pass must not duplicate rows
    assert len(_adp_rows(wh)) == 6


def test_rebuild_with_no_adp_parquet_leaves_adp_empty(env: tuple) -> None:
    settings, wh, cx = env
    rebuild_warehouse(settings.jaaffl_data_dir)  # no FFC pull happened
    assert _count(wh, "adp") == 0


def test_refresh_adp_returns_none_without_supporters(env: tuple) -> None:
    settings, wh, cx = env
    assert refresh_adp(2026, settings=settings, warehouse=wh, crosswalk=cx, providers=[]) is None


def test_refresh_nflverse_history_seeds_and_persists_parquet(
    env: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    settings, wh, cx = env
    playerids = pl.DataFrame(
        [
            {
                "gsis_id": "00-cmc",
                "cbs_id": "111",
                "fantasypros_id": "17246",
                "name": "Christian McCaffrey",
                "position": "RB",
                "team": "SF",
            }
        ]
    )
    stats = pl.DataFrame([{"player_id": "00-cmc", "fantasy_points": 300.0}])
    xep = pl.DataFrame([{"player_id": "00-cmc", "total_yards_gained_exp": 1500.0}])
    # Shared helper rather than a hand-rolled SimpleNamespace: it defaults every table this
    # provider reads (load_teams included), so adding a source doesn't break unrelated tests.
    from tests.test_providers import fake_nflreadpy

    fake_nflreadpy(
        monkeypatch,
        load_ff_playerids=lambda: playerids,
        load_player_stats=lambda seasons: stats,
        load_ff_opportunity=lambda seasons: xep,
    )
    from jaaffl.materialize import refresh_nflverse_history
    from jaaffl.providers.nflverse import NflreadpyProvider

    paths = refresh_nflverse_history(
        2026, warehouse=wh, crosswalk=cx, provider=NflreadpyProvider(crosswalk=cx)
    )
    assert paths["player_stats"].exists()
    assert paths["ff_opportunity"].exists()
    assert cx.resolve("cbs", "111") == "gsis:00-cmc"  # crosswalk was seeded as a side effect
