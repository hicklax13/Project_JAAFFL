"""CbsOnPageProvider — the zero-network reader of the CBS warehouse snapshot (plan §4.5).

The provider performs NO network I/O; it reads ``warehouse.latest_cbs_snapshot`` (fed by the
extension->ingest path). The real CBS field shapes are UNVERIFIED / capture-blocked, so these
tests exercise the reader + graceful-empty behavior against a SYNTHETIC CbsPageSnapshot. The
snapshot's cbs ids resolve to canonical via the Crosswalk; unresolved ids are skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import CbsPageSnapshot, LeagueSettings, Player
from jaaffl.providers.base import Capability, CapabilityNotSupported
from jaaffl.providers.cbs_onpage import CbsOnPageProvider

LEAGUE = "cbs-98765"


@pytest.fixture
def wh(tmp_path: Path) -> Warehouse:
    w = Warehouse(tmp_path)
    w.init()
    return w


@pytest.fixture
def cx(tmp_path: Path, wh: Warehouse) -> Crosswalk:
    cx = Crosswalk(tmp_path / "app.sqlite")
    cx.upsert(
        Player(
            player_id="gsis:cmc",
            name="Christian McCaffrey",
            position="RB",
            nfl_team="SF",
            external_ids={"cbs": "111", "gsis": "cmc"},
        )
    )
    cx.upsert(
        Player(
            player_id="gsis:jj",
            name="Justin Jefferson",
            position="WR",
            nfl_team="MIN",
            external_ids={"cbs": "222", "gsis": "jj"},
        )
    )
    return cx


def _snapshot(**over: object) -> CbsPageSnapshot:
    data: dict = {
        "league_id": LEAGUE,
        "projections": {"111": {"points": 320.5}, "999": {"points": 10.0}},  # cbs 999 unresolved
        "injuries": {"222": "Questionable"},
        "rankings": {"111": 1.0, "222": 3.0},
        "league_settings": LeagueSettings(league_id=LEAGUE, team_count=12),
        "captured_at": datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
    }
    data.update(over)
    return CbsPageSnapshot(**data)


# --- warehouse snapshot storage ------------------------------------------------------


def test_snapshot_round_trips_through_warehouse(wh: Warehouse) -> None:
    wh.snapshot_cbs_page(LEAGUE, _snapshot())
    got = wh.latest_cbs_snapshot(LEAGUE)
    assert got is not None
    assert got.league_id == LEAGUE
    assert got.projections["111"] == {"points": 320.5}
    assert got.league_settings.team_count == 12


def test_snapshot_dedups_byte_identical_repush(wh: Warehouse) -> None:
    first = wh.snapshot_cbs_page(LEAGUE, _snapshot())
    second = wh.snapshot_cbs_page(LEAGUE, _snapshot())
    assert first is not None
    assert second is None  # identical content hash -> ignored


def test_latest_returns_newest_by_captured_at(wh: Warehouse) -> None:
    wh.snapshot_cbs_page(
        LEAGUE,
        _snapshot(captured_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC), rankings={"111": 1.0}),
    )
    wh.snapshot_cbs_page(
        LEAGUE,
        _snapshot(captured_at=datetime(2026, 7, 16, 13, 0, tzinfo=UTC), rankings={"111": 9.0}),
    )
    assert wh.latest_cbs_snapshot(LEAGUE).rankings == {"111": 9.0}


def test_latest_none_when_empty(wh: Warehouse) -> None:
    assert wh.latest_cbs_snapshot(LEAGUE) is None
    assert wh.latest_cbs_snapshot() is None


# --- provider behavior ---------------------------------------------------------------


def test_capabilities_are_projections_injuries_rankings(wh: Warehouse, cx: Crosswalk) -> None:
    p = CbsOnPageProvider(wh, cx)
    assert p.name == "cbs_onpage"
    assert p.supports(Capability.PROJECTIONS)
    assert p.supports(Capability.INJURIES)
    assert p.supports(Capability.RANKINGS)
    assert not p.supports(Capability.ADP)


def test_undeclared_capability_raises(wh: Warehouse, cx: Crosswalk) -> None:
    with pytest.raises(CapabilityNotSupported):
        CbsOnPageProvider(wh, cx).adp(2026)


def test_all_reads_return_empty_before_any_snapshot(wh: Warehouse, cx: Crosswalk) -> None:
    p = CbsOnPageProvider(wh, cx)
    assert p.projections(2026) == {}
    assert p.injuries(2026) == {}
    assert p.rankings(2026) == {}
    assert p.league_settings() is None  # None, not raise


def test_projections_resolve_cbs_to_canonical_skipping_unresolved(
    wh: Warehouse, cx: Crosswalk
) -> None:
    wh.snapshot_cbs_page(LEAGUE, _snapshot())
    proj = CbsOnPageProvider(wh, cx, league_id=LEAGUE).projections(2026)
    assert proj == {"gsis:cmc": {"points": 320.5}}  # cbs 999 has no crosswalk row -> skipped


def test_injuries_and_rankings_resolve(wh: Warehouse, cx: Crosswalk) -> None:
    wh.snapshot_cbs_page(LEAGUE, _snapshot())
    p = CbsOnPageProvider(wh, cx, league_id=LEAGUE)
    assert p.injuries(2026) == {"gsis:jj": "Questionable"}
    assert p.rankings(2026) == {"gsis:cmc": 1.0, "gsis:jj": 3.0}


def test_league_settings_returns_authoritative_settings(wh: Warehouse, cx: Crosswalk) -> None:
    wh.snapshot_cbs_page(LEAGUE, _snapshot())
    ls = CbsOnPageProvider(wh, cx, league_id=LEAGUE).league_settings()
    assert ls is not None
    assert ls.league_id == LEAGUE
    assert ls.team_count == 12


def test_bare_provider_resolves_sole_active_league(wh: Warehouse, cx: Crosswalk) -> None:
    wh.snapshot_cbs_page(LEAGUE, _snapshot())
    p = CbsOnPageProvider(wh, cx)  # league_id=None -> sole active league (ADR 0002)
    assert p.projections(2026) == {"gsis:cmc": {"points": 320.5}}
    assert p.league_settings().team_count == 12
