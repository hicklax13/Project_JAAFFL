"""Stage-5 materialization: engine projections → Parquet → DuckDB ``projections``, and the
draft-corpus ``recommendations.jsonl`` export (closes the Phase-3 TODO)."""

from __future__ import annotations

import pytest

from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import (
    Player,
    Position,
    Recommendation,
    RecommendedPick,
    ScoreComponents,
)
from jaaffl.league.defaults import jaaffl_scoring
from jaaffl.materialize import refresh_projections
from jaaffl.providers.base import Capability, FantasyDataProvider
from tests.engine_fixtures import draft_state, engine_params, jaaffl_settings


class _Fake(FantasyDataProvider):
    def __init__(self, name, caps, *, rankings=None, projections=None):
        self._name, self._caps = name, frozenset(caps)
        self._rankings, self._projections = rankings or {}, projections or {}

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def rankings(self, season, week=None):
        return self._rankings

    def projections(self, season, week=None):
        return self._projections


def _warehouse(tmp_path) -> Warehouse:
    wh = Warehouse(tmp_path)
    wh.init()  # create dirs + app.sqlite schema + empty DuckDB tables
    return wh


def _settings():
    rules, tiers, bonuses = jaaffl_scoring()
    return jaaffl_settings().model_copy(
        update={"scoring": rules, "scoring_tiers": tiers, "scoring_bonuses": bonuses}
    )


def test_refresh_projections_then_materialize_populates_duckdb(tmp_path) -> None:
    wh = _warehouse(tmp_path)
    providers = [
        _Fake(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={
                "rb0": {"rushing_yards": 1500, "rushing_td": 12},
                "wr0": {"receiving_yards": 1200, "receiving_td": 9},
            },
        ),
    ]
    players = {
        "rb0": Player(player_id="rb0", name="rb0", position=Position.RB),
        "wr0": Player(player_id="wr0", name="wr0", position=Position.WR),
    }
    path = refresh_projections(
        2026,
        _settings(),
        engine_params(),
        players=players,
        sigma_floor={p: 20.0 for p in Position},
        warehouse=wh,
        crosswalk=Crosswalk(db_path=wh.app_sqlite),
        providers=providers,
    )
    assert path is not None and path.exists()

    wh.materialize()  # reload DuckDB from Parquet (network-free rebuild step)
    con = wh._duckdb_connect()
    try:
        rows = dict(
            con.execute("SELECT player_id, mu FROM projections ORDER BY player_id").fetchall()
        )
    finally:
        con.close()
    assert set(rows) == {"rb0", "wr0"}
    assert rows["rb0"] == pytest.approx(1500 * 0.1 + 12 * 6)  # 222 under the CBS map, Rec = 0


def test_materialize_is_reproducible_for_fixed_parquet(tmp_path) -> None:
    wh = _warehouse(tmp_path)
    providers = [
        _Fake(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={"rb0": {"rushing_yards": 1000, "rushing_td": 8}},
        )
    ]
    players = {"rb0": Player(player_id="rb0", name="rb0", position=Position.RB)}
    refresh_projections(
        2026,
        _settings(),
        engine_params(),
        players=players,
        sigma_floor={p: 20.0 for p in Position},
        warehouse=wh,
        crosswalk=Crosswalk(db_path=wh.app_sqlite),
        providers=providers,
    )

    def _snapshot():
        wh.materialize()
        con = wh._duckdb_connect()
        try:
            return con.execute("SELECT player_id, mu, sigma FROM projections").fetchall()
        finally:
            con.close()

    assert _snapshot() == _snapshot()  # rebuild is a pure function of the Parquet


def test_snapshot_draft_state_writes_recommendations_jsonl(tmp_path) -> None:
    wh = _warehouse(tmp_path)
    state = draft_state(5, league_id="cbs-x")
    comps = ScoreComponents(
        mlv=10.0,
        vona=1.0,
        risk_penalty=0.5,
        cliff_bonus=0.0,
        sigma=8.0,
        floor=1.0,
        ceiling=20.0,
        replacement_baseline=5.0,
    )
    recs = [
        Recommendation(
            league_id="cbs-x",
            as_of_overall_pick=n,
            ranked=[RecommendedPick(player_id=f"p{n}", score=float(n), components=comps)],
        )
        for n in (1, 2, 3)
    ]
    out = wh.snapshot_draft_state(state, recommendations=recs)
    lines = (out / "recommendations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    reloaded = [Recommendation.model_validate_json(line) for line in lines]
    assert [r.as_of_overall_pick for r in reloaded] == [1, 2, 3]
    assert reloaded[0].ranked[0].components is not None
