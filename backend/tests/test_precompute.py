"""Pre-draft precompute bridge (§3.7 / §4.7): the $0 registry → a RecommendationEngine context.

All provider I/O + network live in the injectable factory; the engine hot path then reads the
cached context. This whole module is exercised with FAKE providers + a fake player universe — no
network — so it proves the 503→200 bridge end-to-end offline.
"""

from __future__ import annotations

import os

import pytest

from jaaffl.config import Settings
from jaaffl.data.warehouse import Warehouse
from jaaffl.domain import Player, Position
from jaaffl.engine.precompute import build_registry_context_source
from jaaffl.engine.service import RecommendationEngine
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider
from tests.engine_fixtures import draft_state


class _CountingFake(FantasyDataProvider):
    """A fake provider that counts capability calls so a test can prove the hot path is
    provider-free (the count must not move once the context is cached)."""

    def __init__(self, name, caps, *, adp=None, rankings=None, projections=None, players=None):
        self._name, self._caps = name, frozenset(caps)
        self._adp, self._rankings = adp or {}, rankings or {}
        self._projections, self._players = projections or {}, players or []
        self.calls = 0

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def players(self, season):
        self.calls += 1
        return list(self._players)

    def adp(self, season):
        self.calls += 1
        return self._adp

    def rankings(self, season, week=None):
        self.calls += 1
        return self._rankings

    def projections(self, season, week=None):
        self.calls += 1
        return self._projections


def _universe():
    return [
        Player(player_id="rb0", name="rb0", position=Position.RB),
        Player(player_id="rb1", name="rb1", position=Position.RB),
        Player(player_id="wr0", name="wr0", position=Position.WR),
        Player(player_id="wr1", name="wr1", position=Position.WR),
        Player(player_id="te0", name="te0", position=Position.TE),
    ]


def _providers():
    """The $0 free-tier shape (nflverse HISTORICAL_STATS+RANKINGS, ffc ADP, cbs_onpage
    PROJECTIONS) — all fakes, no network."""
    return [
        _CountingFake(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS},
            rankings={"rb0": 1.0, "rb1": 5.0, "wr0": 2.0, "wr1": 6.0, "te0": 20.0},
            players=_universe(),
        ),
        _CountingFake(
            "ffc",
            {Capability.ADP},
            adp={"rb0": AdpRecord(adp=1.0, stdev=3.0), "wr0": AdpRecord(adp=2.0, stdev=None)},
        ),
        _CountingFake(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={
                "rb0": {"rushing_yards": 1500, "rushing_td": 12},
                "rb1": {"rushing_yards": 900, "rushing_td": 6},
                "wr0": {"receiving_yards": 1200, "receiving_td": 9},
                "wr1": {"receiving_yards": 800, "receiving_td": 5},
                "te0": {"receiving_yards": 700, "receiving_td": 5},
            },
        ),
    ]


def _source(providers, tmp_path):
    return build_registry_context_source(
        Settings(jaaffl_data_dir=tmp_path / "data"),
        warehouse=Warehouse(tmp_path / "data"),
        providers=providers,
    )


def test_factory_builds_a_valid_context_from_fake_providers(tmp_path) -> None:
    ctx = _source(_providers(), tmp_path)("cbs-local")
    assert ctx is not None
    # The immutable constitution roster, reproduced verbatim (draft_order NEVER inferred → None).
    assert ctx.settings.league_id == "cbs-local"
    assert ctx.settings.team_count == 12
    assert ctx.settings.draft_type == "snake"
    assert ctx.settings.draft_order is None
    assert len(ctx.starting_slots) == 9
    # Joined by canonical id: CBS points (1500·0.1 + 12·6 = 222) blended with ECR (300 − 1 = 299).
    assert ctx.projections["rb0"].sources["cbs"] == pytest.approx(222.0)
    assert ctx.mu["rb0"] == pytest.approx((222.0 + 299.0) / 2)
    assert ctx.adp_mean["rb0"] == pytest.approx(1.0)
    assert ctx.adp_sd["rb0"] == pytest.approx(3.0)  # FFC stdev
    assert ctx.adp_sd["wr0"] == pytest.approx(12.0)  # None stdev → wide default


def _complete_providers():
    """Like ``_providers()`` but covering every STARTABLE position (adds QB, K, DST)."""
    universe = [
        *_universe(),
        Player(player_id="qb0", name="qb0", position=Position.QB),
        Player(player_id="k0", name="k0", position=Position.K),
        Player(player_id="dst0", name="dst0", position=Position.DST),
    ]
    return [
        _CountingFake(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS},
            rankings={"rb0": 1.0, "wr0": 2.0, "te0": 20.0, "qb0": 8.0, "k0": 150.0, "dst0": 160.0},
            players=universe,
        ),
    ]


def test_context_build_warns_when_a_startable_position_is_missing_from_the_board(
    tmp_path,
) -> None:
    """The drift alarm. The fake universe is RB/WR/TE only, so QB/K/DST cannot be started.

    Crucially NON-FATAL: the context is still returned. A context can be rebuilt mid-draft (the
    per-league cache is in-memory and a service restart empties it), and serving an incomplete
    board beats serving none at all.
    """
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        ctx = _source(_providers(), tmp_path)("cbs-local")

    assert ctx is not None, "coverage gaps must degrade, never block the board"
    warning = next(
        (entry for entry in logs if entry["event"] == "precompute_position_coverage_gap"), None
    )
    assert warning is not None, "a missing startable position must be surfaced"
    assert warning["log_level"] == "warning"
    assert warning["missing"] == ["DST", "K", "QB"]


def test_context_build_is_quiet_when_every_startable_position_is_on_the_board(tmp_path) -> None:
    """The alarm must START GREEN — an alarm that always fires is one you learn to ignore."""
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        ctx = _source(_complete_providers(), tmp_path)("cbs-local")

    assert ctx is not None
    assert not [e for e in logs if e["event"] == "precompute_position_coverage_gap"]


def test_factory_returns_none_when_universe_is_empty(tmp_path) -> None:
    """No player universe → None so /recommendation still 503s gracefully (never a 500)."""
    providers = [_CountingFake("nflverse", {Capability.HISTORICAL_STATS}, players=[])]
    assert _source(providers, tmp_path)("cbs-local") is None


def test_engine_using_source_turns_state_into_a_real_recommendation(tmp_path) -> None:
    engine = RecommendationEngine(context_source=_source(_providers(), tmp_path))
    state = draft_state(1, league_id="cbs-local", my_team_id="t0")
    rec = engine.recommend(state, limit=3)
    assert rec is not None
    assert 1 <= len(rec.ranked) <= 3
    top = rec.ranked[0]
    assert top.components is not None
    c = top.components
    kappa = engine.context_for("cbs-local").params.kappa
    reconstructed = (
        c.mlv
        + kappa * max(0.0, c.vona)
        - c.risk_penalty
        + c.cliff_bonus
        + sum(c.modifiers.values())
    )
    assert top.score == pytest.approx(reconstructed)


def test_hot_path_touches_no_provider_once_the_context_is_cached(tmp_path) -> None:
    """§4.7: precompute is the only provider I/O — a second recompute reads the cache with no
    provider calls."""
    providers = _providers()
    engine = RecommendationEngine(context_source=_source(providers, tmp_path))
    state = draft_state(1, league_id="cbs-local", my_team_id="t0")
    engine.recommend(state)  # builds + caches the context (providers hit here)
    calls_after_build = sum(p.calls for p in providers)
    assert calls_after_build > 0
    engine.recommend(state)  # cached → no provider touched
    assert sum(p.calls for p in providers) == calls_after_build


def test_registry_player_loader_uses_real_players_method(monkeypatch, tmp_path) -> None:
    """The 503→universe flip at the loader seam: the real NflreadpyProvider.players() (fake
    nflreadpy) yields a real universe dict through _registry_player_loader — where it used to
    swallow NotImplementedError to {} (the keystone before players() existed)."""
    import polars as pl

    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import _registry_player_loader
    from jaaffl.providers.nflverse import NflreadpyProvider
    from tests.test_providers import fake_nflreadpy

    Warehouse(tmp_path).init()
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
    fake_nflreadpy(monkeypatch, load_ff_playerids=lambda: pl.DataFrame([row]))
    provider = NflreadpyProvider(crosswalk=Crosswalk(tmp_path / "app.sqlite"))
    universe = _registry_player_loader([provider])(2026)
    assert set(universe) == {"gsis:00-0034796"}
    assert universe["gsis:00-0034796"].name == "CeeDee Lamb"


# --- measured σ (replacing the v1 flat placeholder) ---------------------------------------


def test_sigma_floors_are_the_measured_positional_drift_not_one_flat_constant() -> None:
    """`_DEFAULT_SIGMA_FLOOR` used to be a hand-picked ~50-for-everyone placeholder. It is now
    the year-over-year projection error measured from nflverse xEP under the JAAFFL map, whose
    substantive finding is the ORDERING: a QB season is far less predictable in raw points than
    a TE season, and WR is tighter than RB — none of which a flat constant can express."""
    from jaaffl.engine.precompute import _DEFAULT_SIGMA_FLOOR

    qb = _DEFAULT_SIGMA_FLOOR[Position.QB]
    rb = _DEFAULT_SIGMA_FLOOR[Position.RB]
    wr = _DEFAULT_SIGMA_FLOOR[Position.WR]
    te = _DEFAULT_SIGMA_FLOOR[Position.TE]
    assert qb > rb > wr > te
    assert set(_DEFAULT_SIGMA_FLOOR) == set(Position)  # a stray IDP row can never KeyError


def test_precompute_asks_for_xep_from_the_last_completed_season(tmp_path) -> None:
    """The draft season has no xEP rows at all (nflreadpy raises for 2026) — precompute must
    request season − 1 or the whole source silently evaporates."""
    seen: list[int] = []

    class _XepFake(_CountingFake):
        def expected_points(self, season, week=None):
            seen.append(season)
            return []

    providers = [
        _XepFake(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS, Capability.EXPECTED_POINTS},
            rankings={"rb0": 1.0, "rb1": 5.0, "wr0": 2.0, "wr1": 6.0, "te0": 20.0},
            players=_universe(),
        )
    ]
    source = build_registry_context_source(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_season=2026),
        warehouse=Warehouse(tmp_path / "data"),
        providers=providers,
    )
    assert source("cbs-local") is not None
    assert seen == [2025]


# --- automatic id-crosswalk seeding --------------------------------------------------------


class _SeedingFake(_CountingFake):
    """A provider that also exposes ``seed_crosswalk`` (as NflreadpyProvider does), recording
    the order of operations so a test can prove the seed lands BEFORE the provider reads."""

    def __init__(self, *args, seed_error=None, log=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._seed_error = seed_error
        self.log = log if log is not None else []
        self.seed_calls = 0

    def seed_crosswalk(self):
        self.seed_calls += 1
        self.log.append("seed")
        if self._seed_error is not None:
            raise self._seed_error
        return 4428

    def rankings(self, season, week=None):
        self.log.append("rankings")
        return super().rankings(season, week)

    def players(self, season):
        self.log.append("players")
        return super().players(season)


def _seeding_providers(**kwargs):
    log: list[str] = []
    return log, [
        _SeedingFake(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS},
            rankings={"rb0": 1.0, "rb1": 5.0, "wr0": 2.0, "wr1": 6.0, "te0": 20.0},
            players=_universe(),
            log=log,
            **kwargs,
        )
    ]


def test_crosswalk_is_seeded_before_any_provider_is_read(tmp_path) -> None:
    """ADP resolves by name and ECR by FantasyPros id — both need a populated crosswalk. On a
    fresh clone it is EMPTY, so an unseeded precompute resolves 0 ADP and 0 ECR rows and every
    recommendation comes back with vona = 0. The seed must therefore precede the reads."""
    log, providers = _seeding_providers()
    assert _source(providers, tmp_path)("cbs-local") is not None
    assert log[0] == "seed"
    assert providers[0].seed_calls == 1


def test_the_crosswalk_is_seeded_once_per_process_not_once_per_league(tmp_path) -> None:
    """Seeding pulls ~4.5k rows and rewrites them; doing it per league (or per cache miss) would
    pay that cost repeatedly for no benefit."""
    _, providers = _seeding_providers()
    source = _source(providers, tmp_path)
    source("cbs-local")
    source("another-league")
    source("cbs-local")
    assert providers[0].seed_calls == 1


def test_a_failed_seed_is_non_fatal_so_an_offline_draft_still_gets_a_board(tmp_path) -> None:
    """Draft night with no internet must still serve the cached/degraded board rather than
    losing the engine entirely to a seeding error."""
    from jaaffl.providers.base import ProviderError

    _, providers = _seeding_providers(seed_error=ProviderError("nflverse unreachable"))
    ctx = _source(providers, tmp_path)("cbs-local")
    assert ctx is not None
    assert ctx.mu  # the board still assembled


def test_precompute_seeds_real_cbs_links_into_the_warehouse_sqlite(monkeypatch, tmp_path) -> None:
    """The cross-module link that makes drafted-player masking work without manual setup: the
    REAL NflreadpyProvider seeds cbs→canonical rows into the SAME app.sqlite that the API's
    ``cbs_resolver`` (``crosswalk.resolve("cbs", id)``) reads. Fully offline — nflreadpy is faked,
    but the crosswalk, the provider and the seeding path are all real."""
    import polars as pl

    from jaaffl.data import Crosswalk
    from jaaffl.providers.nflverse import NflreadpyProvider
    from tests.test_providers import fake_nflreadpy

    warehouse = Warehouse(tmp_path / "data")
    warehouse.init()
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
    fake_nflreadpy(
        monkeypatch,
        load_ff_playerids=lambda: pl.DataFrame([row]),
        # The real provider also declares RANKINGS + EXPECTED_POINTS, so both loaders must exist;
        # empty is fine — this test is about the seed, not the board.
        load_ff_rankings=lambda: pl.DataFrame(schema={"page_type": pl.Utf8}),
        load_ff_opportunity=lambda seasons: pl.DataFrame(
            schema={"player_id": pl.Utf8, "week": pl.Float64}
        ),
    )
    crosswalk = Crosswalk(warehouse.app_sqlite)
    assert crosswalk.resolve("cbs", "2181292") is None  # fresh clone: nothing to resolve with

    build_registry_context_source(
        Settings(jaaffl_data_dir=tmp_path / "data"),
        warehouse=warehouse,
        # The real provider goes LAST so the fakes still serve every capability read; it is
        # reached only for ``seed_crosswalk``, which is the behaviour under test.
        providers=[*_providers(), NflreadpyProvider(crosswalk=crosswalk)],
    )("cbs-local")

    # The exact lookup api/app.py performs for an ID-only CBS pick — now satisfied automatically.
    assert crosswalk.resolve("cbs", "2181292") == "gsis:00-0034796"


@pytest.mark.skipif(
    not os.environ.get("JAAFFL_RUN_NETWORK_TESTS"),
    reason="opt-in: real nflverse network pull; set JAAFFL_RUN_NETWORK_TESTS=1 to run",
)
def test_live_default_universe_can_roster_every_league_position(tmp_path, monkeypatch) -> None:
    """END-TO-END SEVERITY GUARD: the DEFAULT ($0-tier) live universe must cover every startable
    position.

    This is the wiring an actual draft uses — ``build_registry()`` with no keys yields
    ``[nflverse, ffc, cbs_onpage]``, and ``_registry_player_loader`` picks the first
    HISTORICAL_STATS provider (nflverse). Measured before the fixes (2026-07-25): 4426 players,
    positions ``{WR, LB, RB, QB, TE, DL, DB}`` — **zero K and zero DST**, i.e. two of the nine
    starting slots were unfillable. Kickers were dropped because db_playerids spells the position
    ``PK``; defenses were absent because that table has no team rows at all. Every unit test
    passed throughout, because each fixture spelled the positions ``K``/``DST`` — only the real
    feed says otherwise.
    """
    pytest.importorskip("nflreadpy")
    from jaaffl.engine.precompute import _registry_player_loader
    from jaaffl.providers.registry import build_registry

    monkeypatch.setenv("JAAFFL_DATA_DIR", str(tmp_path))  # never touch the owner's real db
    universe = _registry_player_loader(build_registry())(2026)

    positions = {str(p.position) for p in universe.values()}
    missing = {"QB", "RB", "WR", "TE", "K", "DST"} - positions
    assert not missing, (
        f"live default universe cannot roster {sorted(missing)}; got {sorted(positions)}"
    )
