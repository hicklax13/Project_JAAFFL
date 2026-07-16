"""FantasyFootballCalculatorProvider — free Standard/12-team ADP with stdev (plan §4.4).

Tests replay RECORDED fixtures via httpx.MockTransport — the real httpx/URL/JSON path, zero
live network (CI-safe). Fixtures were curated 2026-07-16 from the public free endpoint
fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year=YYYY. Ground-truth quirks:
FFC positions are DEF/PK (not DST/K) and a past year returns status='Error' with no players.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from structlog.testing import capture_logs

from jaaffl.config import Settings
from jaaffl.data import Crosswalk, Warehouse
from jaaffl.domain import Player
from jaaffl.providers.base import AdpRecord, Capability, ProviderError
from jaaffl.providers.ffc import FantasyFootballCalculatorProvider

FIXTURES = Path(__file__).parent / "fixtures" / "ffc"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(
    payload: dict, counter: dict | None = None, capture: dict | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter["n"] += 1
        if capture is not None:
            capture["url"] = str(request.url)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(jaaffl_data_dir=tmp_path, jaaffl_season=2026)


@pytest.fixture
def cx(tmp_path: Path) -> Crosswalk:
    """Seed 6 of the fixture's 9 players (using their FFC names as canonical) so resolution +
    the DEF->DST / PK->K position map are exercised end-to-end; the 3 unseeded rows must skip."""
    Warehouse(tmp_path).init()
    cx = Crosswalk(tmp_path / "app.sqlite")
    seeds = [
        ("gsis:gibbs", "Jahmyr Gibbs", "RB", "DET"),
        ("gsis:nacua", "Puka Nacua", "WR", "LAR"),
        ("gsis:allen", "Josh Allen", "QB", "BUF"),
        ("gsis:mcbride", "Trey McBride", "TE", "ARI"),
        ("gsis:sea-dst", "Seattle Defense", "DST", "SEA"),  # FFC sends 'Seattle Defense' pos DEF
        ("gsis:aubrey", "Brandon Aubrey", "K", "DAL"),  # FFC sends pos PK
    ]
    for pid, name, pos, team in seeds:
        cx.upsert(Player(player_id=pid, name=name, position=pos, nfl_team=team))
    return cx


def test_adp_returns_records_with_stdev(settings: Settings, cx: Crosswalk) -> None:
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"))
    )
    adp = prov.adp(2026)
    rec = adp["gsis:gibbs"]
    assert isinstance(rec, AdpRecord)
    assert rec.adp == 1.7
    assert rec.stdev == 0.9  # the survival input FFC uniquely provides
    assert rec.bye == 6
    assert rec.times_drafted == 40


def test_adp_maps_def_and_pk_positions_before_resolving(settings: Settings, cx: Crosswalk) -> None:
    # Without DEF->DST / PK->K mapping these would query a non-existent position and silently drop.
    adp = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"))
    ).adp(2026)
    assert "gsis:sea-dst" in adp  # Seattle Defense (DEF -> DST)
    assert "gsis:aubrey" in adp  # Brandon Aubrey (PK -> K)


def test_adp_skips_unresolved_rows(settings: Settings, cx: Crosswalk) -> None:
    adp = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"))
    ).adp(2026)
    # Exactly the 6 seeded players resolve; Bijan/Chase/McLaughlin (unseeded) are skipped.
    assert len(adp) == 6
    assert set(adp) == {
        "gsis:gibbs",
        "gsis:nacua",
        "gsis:allen",
        "gsis:mcbride",
        "gsis:sea-dst",
        "gsis:aubrey",
    }


def test_adp_builds_the_standard_12_current_year_url(settings: Settings, cx: Crosswalk) -> None:
    cap: dict = {}
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"), capture=cap)
    )
    prov.adp(2026)
    assert (
        cap["url"] == "https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year=2026"
    )


def test_adp_defaults_season_from_settings(settings: Settings, cx: Crosswalk) -> None:
    cap: dict = {}
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"), capture=cap)
    )
    prov.adp()  # None -> settings.jaaffl_season (2026)
    assert "year=2026" in cap["url"]


def test_adp_past_year_raises_and_caches_nothing(
    settings: Settings, cx: Crosswalk, tmp_path: Path
) -> None:
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2025_error.json"))
    )
    with pytest.raises(ProviderError):
        prov.adp(2025)
    assert not (tmp_path / "cache" / "ffc" / "adp_standard_12_2025.json").exists()


def test_adp_empty_players_raises(settings: Settings, cx: Crosswalk) -> None:
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client({"status": "Success", "players": [], "meta": {}})
    )
    with pytest.raises(ProviderError):
        prov.adp(2026)


def test_adp_second_call_serves_from_memo_no_second_get(settings: Settings, cx: Crosswalk) -> None:
    counter = {"n": 0}
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"), counter)
    )
    prov.adp(2026)
    prov.adp(2026)
    assert counter["n"] == 1


def test_adp_file_cache_reused_across_instances(settings: Settings, cx: Crosswalk) -> None:
    counter = {"n": 0}
    client = _client(_fixture("adp_standard_12_2026.json"), counter)
    FantasyFootballCalculatorProvider(settings, cx, client=client).adp(
        2026
    )  # writes 24h file cache
    FantasyFootballCalculatorProvider(settings, cx, client=client).adp(
        2026
    )  # fresh memo, reads file
    assert counter["n"] == 1


def test_capabilities_is_adp_only(settings: Settings, cx: Crosswalk) -> None:
    prov = FantasyFootballCalculatorProvider(settings, cx)
    assert prov.name == "ffc"
    assert prov.supports(Capability.ADP)
    assert not prov.supports(Capability.RANKINGS)


def test_enabled_follows_kill_switch(tmp_path: Path, cx: Crosswalk) -> None:
    on = Settings(jaaffl_data_dir=tmp_path, jaaffl_enable_ffc=True)
    off = Settings(jaaffl_data_dir=tmp_path, jaaffl_enable_ffc=False)
    assert FantasyFootballCalculatorProvider(on, cx).enabled is True
    assert FantasyFootballCalculatorProvider(off, cx).enabled is False


def test_diverging_teams_setting_is_surfaced_not_silently_changed(
    tmp_path: Path, cx: Crosswalk
) -> None:
    # jaaffl_ffc_teams must equal league.json (12). A divergence is WARNED and used as-configured
    # (never silently rewritten to 12, never touching league.json).
    settings = Settings(jaaffl_data_dir=tmp_path, jaaffl_season=2026, jaaffl_ffc_teams=10)
    cap: dict = {}
    prov = FantasyFootballCalculatorProvider(
        settings, cx, client=_client(_fixture("adp_standard_12_2026.json"), capture=cap)
    )
    with capture_logs() as logs:
        prov.adp(2026)
    assert "teams=10" in cap["url"]  # surfaced as-configured, not silently 12
    assert any(e.get("event") == "ffc_settings_conflict" for e in logs)
