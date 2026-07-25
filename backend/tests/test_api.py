"""The companion-service wire path: health, ingest (REST + WS /draft/ws with the §8.4
frame contract), the /recommendation engine endpoint, and the /recs/ws push channel."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jaaffl import __version__
from jaaffl.api import create_app
from jaaffl.api.recs import RecsHub
from jaaffl.config import Settings
from jaaffl.domain import LeagueSettings, Player, Position, Recommendation, RecommendedPick
from jaaffl.engine.service import RecommendationEngine
from jaaffl.ingest.log import DraftLog
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider
from tests.engine_fixtures import make_context


def _primed_engine() -> RecommendationEngine:
    """An engine primed with a board context for league 'L1' (no providers/network)."""
    specs = [
        {
            "pid": f"rb{i}",
            "pos": Position.RB,
            "mu": 300.0 - 5 * i,
            "adp": float(i + 1),
            "sd": 6.0,
            "ecr": float(i + 1),
        }
        for i in range(12)
    ] + [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 280.0 - 4 * i,
            "adp": float(20 + i),
            "sd": 6.0,
            "ecr": float(20 + i),
        }
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    return engine


@pytest.fixture
def app(tmp_path: Path):
    """The shared app, pinned OFFLINE. ``jaaffl_precompute_enabled`` now defaults to True, so
    without this the first `/recommendation` in any test would reach out to nflverse/FFC for
    real. Tests that want the bridge inject fake providers explicitly."""
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "recordings",
            jaaffl_precompute_enabled=False,
        )
    )


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def pick_payload(overall: int) -> dict:
    return {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": overall,
        "source": "ws",
        "data": {
            "overall": overall,
            "round": 1,
            "pick_in_round": overall,
            "team_id": f"T{overall}",
        },
    }


class _FakeProvider(FantasyDataProvider):
    """A no-network provider for the precompute-enabled app path (mirrors the free-tier shape)."""

    def __init__(self, name, caps, *, adp=None, rankings=None, projections=None, players=None):
        self._name, self._caps = name, frozenset(caps)
        self._adp, self._rankings = adp or {}, rankings or {}
        self._projections, self._players = projections or {}, players or []

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def players(self, season):
        return list(self._players)

    def adp(self, season):
        return self._adp

    def rankings(self, season, week=None):
        return self._rankings

    def projections(self, season, week=None):
        return self._projections


def _fake_registry(*_args, **_kwargs):
    """A fake ``build_registry`` result (nflverse/ffc/cbs_onpage shape) — zero network."""
    universe = [
        Player(player_id="rb0", name="rb0", position=Position.RB),
        Player(player_id="rb1", name="rb1", position=Position.RB),
        Player(player_id="wr0", name="wr0", position=Position.WR),
        Player(player_id="wr1", name="wr1", position=Position.WR),
        Player(player_id="te0", name="te0", position=Position.TE),
    ]
    return [
        _FakeProvider(
            "nflverse",
            {Capability.HISTORICAL_STATS, Capability.RANKINGS},
            rankings={"rb0": 1.0, "rb1": 5.0, "wr0": 2.0, "wr1": 6.0, "te0": 20.0},
            players=universe,
        ),
        _FakeProvider(
            "ffc",
            {Capability.ADP},
            adp={"rb0": AdpRecord(adp=1.0, stdev=3.0), "wr0": AdpRecord(adp=2.0, stdev=None)},
        ),
        _FakeProvider(
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


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ingest_event_accepted_and_logged(client: TestClient, app) -> None:
    res = client.post("/draft/events", json=pick_payload(1))
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["deduped"] is False
    assert isinstance(body["seq"], int)
    log: DraftLog = app.state.draft_log
    assert log.state("L1").current_overall_pick == 2


def test_ingest_duplicate_pick_acks_idempotently(client: TestClient) -> None:
    assert client.post("/draft/events", json=pick_payload(1)).json()["deduped"] is False
    dup = client.post("/draft/events", json=pick_payload(1)).json()
    assert dup["accepted"] is True
    assert dup["deduped"] is True


def test_ingest_rejects_bad_event(client: TestClient) -> None:
    res = client.post("/draft/events", json={"event_type": "not_a_type", "league_id": "L1"})
    assert res.status_code == 422


def test_ingest_rejects_malformed_pick_payload(client: TestClient) -> None:
    res = client.post(
        "/draft/events",
        json={"event_type": "pick_made", "league_id": "L1", "data": {"overall": 1}},
    )
    assert res.status_code == 422


def test_recommendation_404_for_unknown_league(client: TestClient) -> None:
    res = client.get("/recommendation", params={"league_id": "never-seen"})
    assert res.status_code == 404


def test_recommendation_503_when_engine_not_primed(client: TestClient) -> None:
    """State exists but the default app has no precomputed context yet → engine warming up."""
    client.post("/draft/events", json=pick_payload(1))
    res = client.get("/recommendation", params={"league_id": "L1"})
    assert res.status_code == 503


def test_recommendation_returns_real_recommendation_when_primed(tmp_path: Path) -> None:
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    client.post("/draft/events", json=pick_payload(1))  # fold a DraftState for L1
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 3})
    assert res.status_code == 200
    body = res.json()
    Recommendation.model_validate(body)  # validates against the shared contract
    assert 1 <= len(body["ranked"]) <= 3
    assert body["ranked"][0]["components"] is not None
    stripped = client.get(
        "/recommendation",
        params={"league_id": "L1", "team_id": "t0", "include_components": "false"},
    ).json()
    assert stripped["ranked"][0]["components"] is None


def test_recommendation_masks_name_only_paste_pick(tmp_path: Path) -> None:
    """A manual-paste (name-only) pick is resolved to its canonical id via the crosswalk, then
    masked from the candidate pool — the live-recs correctness guarantee."""
    specs = [
        {"pid": "gsis:cmc", "pos": Position.RB, "mu": 330.0, "adp": 1.0, "sd": 6.0, "ecr": 1.0}
    ]
    specs += [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 300.0 - 4 * i,
            "adp": float(i + 2),
            "sd": 6.0,
            "ecr": float(i + 2),
        }
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=engine,
    )
    # Seed the crosswalk players row so the paste name resolves to the canonical id.
    app.state.crosswalk.upsert(
        Player(
            player_id="gsis:cmc", name="Christian McCaffrey", position=Position.RB, nfl_team="SF"
        )
    )
    client = TestClient(app)
    paste = {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": 1,
        "source": "paste",
        "data": {
            "overall": 1,
            "round": 1,
            "pick_in_round": 1,
            "team_id": "T1",
            "player_name": "Christian McCaffrey",
            "position": "RB",
            "player_team": "SF",
        },
    }
    client.post("/draft/events", json=paste)
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 50})
    assert res.status_code == 200
    ranked_ids = [p["player_id"] for p in res.json()["ranked"]]
    assert ranked_ids  # board still non-empty
    assert "gsis:cmc" not in ranked_ids  # elite RB resolved from the paste name, then masked


def test_recommendation_survives_unresolvable_paste_pick(tmp_path: Path) -> None:
    """An unresolvable manual-paste name degrades gracefully: 200 with a non-empty board (the
    player is simply left unmasked), never a 500."""
    specs = [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 300.0 - 4 * i,
            "adp": float(i + 1),
            "sd": 6.0,
            "ecr": float(i + 1),
        }
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=engine,
    )
    # Crosswalk deliberately NOT seeded → the paste name cannot resolve.
    client = TestClient(app)
    paste = {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": 1,
        "source": "paste",
        "data": {
            "overall": 1,
            "round": 1,
            "pick_in_round": 1,
            "team_id": "T1",
            "player_name": "Nobody InThe Crosswalk",
            "position": "RB",
            "player_team": "SF",
        },
    }
    client.post("/draft/events", json=paste)
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 5})
    assert res.status_code == 200  # graceful: served the board, did not 500
    assert res.json()["ranked"]


def test_recommendation_masks_real_cbs_pick(tmp_path: Path) -> None:
    """A real CBS pick (protocol §3: ID-only, player_id='cbs:<id>') resolves via the crosswalk's
    cbs source-id link (scripts/seed_cbs_crosswalk.py's seeding target), then masks from the
    candidate pool -- the live-recs correctness guarantee for the real (non-paste) capture path."""
    specs = [
        {"pid": "gsis:cmc", "pos": Position.RB, "mu": 330.0, "adp": 1.0, "sd": 6.0, "ecr": 1.0}
    ]
    specs += [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 300.0 - 4 * i,
            "adp": float(i + 2),
            "sd": 6.0,
            "ecr": float(i + 2),
        }
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=engine,
    )
    # Seed the crosswalk's cbs source-id link directly (what scripts/seed_cbs_crosswalk.py does).
    app.state.crosswalk.upsert(
        Player(
            player_id="gsis:cmc", name="Christian McCaffrey", position=Position.RB, nfl_team="SF"
        )
    )
    app.state.crosswalk.link("cbs", "3117251", "gsis:cmc", method="deterministic")
    client = TestClient(app)
    cbs_pick = {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": 1,
        "source": "ws",
        "data": {
            "overall": 1,
            "round": 1,
            "pick_in_round": 1,
            "team_id": "1",
            "player_id": "cbs:3117251",
            "cbs_player_id": "3117251",
        },
    }
    client.post("/draft/events", json=cbs_pick)
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 50})
    assert res.status_code == 200
    ranked_ids = [p["player_id"] for p in res.json()["ranked"]]
    assert ranked_ids  # board still non-empty
    assert "gsis:cmc" not in ranked_ids  # elite RB resolved from the cbs: id, then masked


def test_recommendation_survives_unresolved_cbs_pick(tmp_path: Path) -> None:
    """A CBS pick whose id has no crosswalk link yet degrades gracefully: 200 with a non-empty
    board (the player is simply left unmasked, and the raw cbs: id is preserved so a later
    scripts/seed_cbs_crosswalk.py run can still resolve it), never a 500."""
    specs = [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 300.0 - 4 * i,
            "adp": float(i + 1),
            "sd": 6.0,
            "ecr": float(i + 1),
        }
        for i in range(12)
    ]
    engine = RecommendationEngine()
    engine.prime("L1", make_context(specs))
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=engine,
    )
    # Crosswalk deliberately NOT seeded for this cbs id -> it cannot resolve.
    client = TestClient(app)
    cbs_pick = {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": 1,
        "source": "ws",
        "data": {
            "overall": 1,
            "round": 1,
            "pick_in_round": 1,
            "team_id": "1",
            "player_id": "cbs:999999",
            "cbs_player_id": "999999",
        },
    }
    client.post("/draft/events", json=cbs_pick)
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 5})
    assert res.status_code == 200  # graceful: served the board, did not 500
    assert res.json()["ranked"]


def test_pick_ingest_publishes_a_fresh_recommendation_to_recs_ws(tmp_path: Path) -> None:
    """§8.4 step 5: a state-advancing pick recomputes and pushes a rec to /recs/ws subscribers."""
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    with client.websocket_connect("/recs/ws") as ws:
        ws.receive_json()  # hello
        ws.receive_json()  # snapshot (None — nothing published yet)
        client.post("/draft/events", json=pick_payload(1))  # pick_made → publish
        frame = ws.receive_json()
        assert frame["type"] == "rec"
        Recommendation.model_validate(frame["recommendation"])


def test_league_settings_404_until_ingested(client: TestClient) -> None:
    assert client.get("/league/unknown-league").status_code == 404


def test_league_endpoint_serves_the_verbatim_constitution(tmp_path: Path) -> None:
    """/league/{configured} returns the immutable roster verbatim; /league/unknown stays 404."""
    app = create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            jaaffl_league_id="L1",
        )
    )
    client = TestClient(app)
    assert client.get("/league/unknown").status_code == 404
    res = client.get("/league/L1")
    assert res.status_code == 200
    ls = LeagueSettings.model_validate(res.json())  # validates against the shared contract
    assert ls.team_count == 12
    assert ls.draft_type == "snake"
    assert ls.draft_order is None  # never inferred from team count
    slots = {s.slot: s for s in ls.roster_slots}
    assert slots["QB"].count == 1
    assert slots["RB"].count == 1
    assert slots["WR"].count == 3
    assert slots["WR/RB"].count == 1
    assert set(slots["WR/RB"].eligible_positions) == {Position.WR, Position.RB}  # WR-or-RB only
    assert slots["TE"].count == 1
    assert slots["K"].count == 1
    assert slots["DST"].count == 1
    assert slots["BENCH"].count == 8
    assert slots["BENCH"].starting is False
    # Scoring overlay present (owner-provided jaaffl_scoring): 6pt pass TD + a SINGLE DST
    # points-allowed bracket (JAAFFL scores no yards-allowed tier).
    assert any(r.stat == "passing_td" and r.points_per_unit == 6.0 for r in ls.scoring)
    assert {t.stat for t in ls.scoring_tiers} == {"dst_points_allowed"}


def test_precompute_enabled_bridge_turns_recommendation_503_into_200(
    tmp_path: Path, monkeypatch
) -> None:
    """The 503→200 bridge: with the precompute flag on and INJECTED fake providers (no network),
    a folded pick yields a real decomposed recommendation."""
    monkeypatch.setattr("jaaffl.engine.precompute.build_registry", _fake_registry)
    app = create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            jaaffl_precompute_enabled=True,
            jaaffl_league_id="L1",
        )
    )
    client = TestClient(app)
    # Before any pick the league is unknown → 404 (state gate), not 503.
    assert client.get("/recommendation", params={"league_id": "L1"}).status_code == 404
    client.post("/draft/events", json=pick_payload(1))  # fold a DraftState for L1
    res = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0", "limit": 3})
    assert res.status_code == 200  # 503 → 200: the engine built a context from the registry
    body = res.json()
    Recommendation.model_validate(body)
    assert 1 <= len(body["ranked"]) <= 3
    assert body["ranked"][0]["components"] is not None


def test_draft_ws_acks_bare_event(client: TestClient) -> None:
    with client.websocket_connect("/draft/ws") as ws:
        ws.send_json(pick_payload(1))
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["v"] == 1
        assert ack["pick_number"] == 1
        assert ack["accepted"] is True
        assert ack["deduped"] is False


def test_draft_ws_acks_enveloped_event_and_dedups(client: TestClient) -> None:
    with client.websocket_connect("/draft/ws") as ws:
        ws.send_json(
            {"type": "event", "v": 1, "ts": "2026-08-30T18:04:11Z", "event": pick_payload(2)}
        )
        assert ws.receive_json()["deduped"] is False
        ws.send_json(pick_payload(2))  # slower probe re-sends the same pick
        ack = ws.receive_json()
        assert ack["accepted"] is True
        assert ack["deduped"] is True


def test_draft_ws_control_frames_never_reach_the_log(client: TestClient, app) -> None:
    """A10: heartbeats are control frames — dropped BEFORE the append-only log."""
    with client.websocket_connect("/draft/ws") as ws:
        ws.send_json({"control": "ping"})
        assert ws.receive_json() == {"control": "pong"}
        ws.send_json({"type": "ping", "v": 1})
        assert ws.receive_json() == {"type": "pong", "v": 1}
    log: DraftLog = app.state.draft_log
    with pytest.raises(ValueError):  # empty log — nothing was appended
        log.state("L1")


def test_draft_ws_invalid_event_errors_and_keeps_socket_open(client: TestClient) -> None:
    with client.websocket_connect("/draft/ws") as ws:
        ws.send_json({"event_type": "not_a_type", "league_id": "L1"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == 4422
        ws.send_json(pick_payload(3))  # socket must survive the bad frame
        assert ws.receive_json()["accepted"] is True


def test_dev_recordings_appends_jsonl_batches(client: TestClient) -> None:
    """Record-mode sink: frame batches append as JSONL under the recordings dir so one
    mock draft yields the real golden fixtures (Phase-1 capture tooling)."""
    batch = {
        "session": "rec-2026-08-30T18-00-00Z",
        "frames": [
            {"kind": "ws-message", "ts": 1, "payload": {"body": "{}"}},
            {"kind": "dom-snapshot", "ts": 2, "payload": {"html": "<div/>"}},
        ],
    }
    res = client.post("/dev/recordings", json=batch)
    assert res.status_code == 200
    assert res.json()["stored"] == 2
    recorded = Path(res.json()["file"])
    assert recorded.exists()
    assert len(recorded.read_text(encoding="utf-8").splitlines()) == 2
    # second batch appends to the same session file
    client.post("/dev/recordings", json=batch)
    assert len(recorded.read_text(encoding="utf-8").splitlines()) == 4


def test_dev_recordings_rejects_path_traversal_session(client: TestClient) -> None:
    res = client.post("/dev/recordings", json={"session": "../evil", "frames": []})
    assert res.status_code == 422


def test_browser_origins_outside_allowlist_are_rejected(client: TestClient) -> None:
    """§8.4/§8.6 Origin check: a hostile web page in another tab must not be able to
    poison the local draft log (WS is not gated by CORS — the server must check)."""
    with (
        pytest.raises(Exception),  # noqa: B017 - handshake rejected -> client raises
        client.websocket_connect("/draft/ws", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    res = client.post(
        "/draft/events", json=pick_payload(9), headers={"origin": "https://evil.example"}
    )
    assert res.status_code == 403
    res = client.post(
        "/dev/recordings",
        json={"session": "rec-x", "frames": []},
        headers={"origin": "https://evil.example"},
    )
    assert res.status_code == 403
    # The read-only /league constitution endpoint honours the same allowlist as its siblings
    # (defense-in-depth; matters if an operator ever widens jaaffl_allowed_origins).
    res = client.get("/league/cbs-local", headers={"origin": "https://evil.example"})
    assert res.status_code == 403


def test_extension_and_dashboard_origins_are_allowed(client: TestClient) -> None:
    ext_origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    with client.websocket_connect("/draft/ws", headers={"origin": ext_origin}) as ws:
        ws.send_json(pick_payload(8))
        assert ws.receive_json()["accepted"] is True
    res = client.post(
        "/draft/events", json=pick_payload(9), headers={"origin": "http://localhost:3000"}
    )
    assert res.status_code == 200


def test_recs_ws_sends_hello_then_snapshot_on_connect(client: TestClient, app) -> None:
    """SC4 (§8.5): after accept the server sends `hello`, then a `snapshot` of the current
    best Recommendation (null until the engine lands) so late joiners are always correct."""
    with client.websocket_connect("/recs/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["v"] == 1
        assert hello["server_version"] == __version__
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["recommendation"] is None  # no engine yet (stage 5)


def test_recs_ws_broadcasts_published_recommendation(client: TestClient, app) -> None:
    hub: RecsHub = app.state.recs_hub
    rec = Recommendation(
        league_id="L1",
        as_of_overall_pick=13,
        ranked=[RecommendedPick(player_id="p1", score=42.0)],
    )
    with client.websocket_connect("/recs/ws") as ws:
        ws.receive_json()  # hello
        ws.receive_json()  # snapshot
        hub.publish(rec)
        frame = ws.receive_json()
        assert frame["type"] == "rec"
        assert Recommendation.model_validate(frame["recommendation"]) == rec


def test_recs_ws_snapshot_replays_latest_rec_to_late_joiners(client: TestClient, app) -> None:
    hub: RecsHub = app.state.recs_hub
    rec = Recommendation(league_id="L1", as_of_overall_pick=14, ranked=[])
    hub.publish(rec)
    with client.websocket_connect("/recs/ws") as ws:
        ws.receive_json()  # hello
        snapshot = ws.receive_json()
        assert Recommendation.model_validate(snapshot["recommendation"]) == rec


def _named_paste_pick(overall: int, team_id: str, name: str, pos: str, team: str) -> dict:
    return {
        "event_type": "pick_made",
        "league_id": "L1",
        "pick_number": overall,
        "source": "paste",
        "data": {
            "overall": overall,
            "round": 1,
            "pick_in_round": overall,
            "team_id": team_id,
            "player_name": name,
            "position": pos,
            "player_team": team,
        },
    }


def test_state_404_for_unknown_league(client: TestClient) -> None:
    """No events + no snapshot → unknown league (distinct from a missing route's bare 404)."""
    res = client.get("/state", params={"league_id": "never-seen"})
    assert res.status_code == 404
    assert "unknown" in res.json()["detail"].lower()


def test_state_returns_named_board_after_named_pick(client: TestClient) -> None:
    """GET /state folds the log and enriches each pick with its drafted-player name — even a
    name-only paste pick whose canonical id never resolved still shows on the board."""
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))
    res = client.get("/state", params={"league_id": "L1"})
    assert res.status_code == 200
    body = res.json()
    assert body["league_id"] == "L1"
    assert len(body["picks"]) == 1
    pick = body["picks"][0]
    assert pick["overall"] == 1
    assert pick["team_id"] == "T1"
    assert pick["name"] == "Christian McCaffrey"
    assert pick["position"] == "RB"
    assert pick["nfl_team"] == "SF"


def test_state_honours_origin_allowlist(client: TestClient) -> None:
    """Read-only, but scoped to the same Origin allowlist as its siblings (defense-in-depth)."""
    res = client.get(
        "/state", params={"league_id": "cbs-local"}, headers={"origin": "https://evil.example"}
    )
    assert res.status_code == 403


def test_analytics_404_for_unknown_league(client: TestClient) -> None:
    res = client.get("/analytics", params={"league_id": "never-seen"})
    assert res.status_code == 404
    assert "unknown" in res.json()["detail"].lower()


def test_analytics_503_while_engine_context_is_warming(client: TestClient) -> None:
    """The board only needs events; analytics needs a precomputed context. Different gates —
    this is exactly why analytics is NOT folded into GET /state."""
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))
    res = client.get("/analytics", params={"league_id": "L1"})
    assert res.status_code == 503

    # ...and the board still renders from the same events.
    assert client.get("/state", params={"league_id": "L1"}).status_code == 200


def test_analytics_returns_both_series_when_primed(tmp_path: Path) -> None:
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))

    res = client.get("/analytics", params={"league_id": "L1"})
    assert res.status_code == 200
    body = res.json()
    assert body["league_id"] == "L1"
    assert body["value_curves"]
    assert {c["position"] for c in body["value_curves"]} <= {"QB", "RB", "WR", "TE"}
    assert body["survival_curves"]
    for curve in body["survival_curves"]:
        assert all(0.0 <= p["survival"] <= 1.0 for p in curve["points"])


def test_analytics_accepts_explicit_candidates(tmp_path: Path) -> None:
    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec"),
        rec_engine=_primed_engine(),
    )
    client = TestClient(app)
    client.post("/draft/events", json=_named_paste_pick(1, "T1", "Christian McCaffrey", "RB", "SF"))

    res = client.get("/analytics", params={"league_id": "L1", "candidates": "wr1,wr2"})
    assert res.status_code == 200
    assert [c["player_id"] for c in res.json()["survival_curves"]] == ["wr1", "wr2"]


def test_analytics_honours_origin_allowlist(client: TestClient) -> None:
    res = client.get(
        "/analytics", params={"league_id": "cbs-local"}, headers={"origin": "https://evil.example"}
    )
    assert res.status_code == 403


def _origin_app(tmp_path: Path, allowed: str):
    """An app whose Origin allowlist is exactly ``allowed`` (comma-separated globs)."""
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            jaaffl_allowed_origins=allowed,
        )
    )


def test_glob_allowlist_entry_passes_the_origin_check_AND_the_cors_preflight(
    tmp_path: Path,
) -> None:
    """The two Origin gates must never disagree.

    ``CORSMiddleware`` compares ``allow_origins`` by EXACT string equality, so a glob such as
    ``https://*.cbssports.com`` silently never matched there — while ``is_origin_allowed``
    (fnmatch) DID match it. That desynchronization is not theoretical: during a live record-mode
    capture the WebSocket handshakes succeeded and the service looked healthy, while every JSON
    POST died at its preflight (``OPTIONS`` -> 400) and the whole session recorded zero frames.
    """
    client = TestClient(_origin_app(tmp_path, "chrome-extension://*,https://*.cbssports.com"))
    origin = "https://mockdraft-1.football.cbssports.com"

    # Gate 1 — the app's own Origin check (this half always worked).
    res = client.post(
        "/dev/recordings", json={"session": "rec-x", "frames": []}, headers={"origin": origin}
    )
    assert res.status_code == 200

    # Gate 2 — the browser's CORS preflight. THIS is what silently blocked the capture.
    pre = client.options(
        "/dev/recordings",
        headers={
            "origin": origin,
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_still_refuses_an_origin_outside_the_allowlist(tmp_path: Path) -> None:
    """Translating globs must not widen CORS into allow-anything."""
    client = TestClient(_origin_app(tmp_path, "chrome-extension://*,https://*.cbssports.com"))

    pre = client.options(
        "/dev/recordings",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert pre.headers.get("access-control-allow-origin") is None


def test_cbs_is_allowed_by_the_shipped_default_allowlist(tmp_path: Path) -> None:
    """Record mode must work out of the box: the extension's content script runs in the CBS page,
    so its requests carry the CBS page origin, NOT chrome-extension://."""
    client = TestClient(
        create_app(
            Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec")
        )
    )

    res = client.post(
        "/dev/recordings",
        json={"session": "rec-x", "frames": []},
        headers={"origin": "https://mockdraft-1.football.cbssports.com"},
    )
    assert res.status_code == 200


def test_concurrent_recording_posts_never_corrupt_the_jsonl(tmp_path: Path) -> None:
    """Every appended line must be valid JSON, even under concurrent same-session flushes.

    A real capture came back with 2 of 223 lines unparseable (one logical line split in two) after
    four same-session flushes landed in the same second. NOTE: this test does NOT reproduce that
    corruption against the pre-fix code — TestClient appears to serialize requests — so it is a
    regression guard on the write contract, not a proof of the original defect.
    """
    from concurrent.futures import ThreadPoolExecutor

    app = create_app(
        Settings(jaaffl_data_dir=tmp_path / "data", jaaffl_recordings_dir=tmp_path / "rec")
    )
    client = TestClient(app)
    big = {"kind": "ws-message", "payload": {"body": "x" * 500_000}}  # real captures hit 509 KB

    def flush(i: int):
        return client.post(
            "/dev/recordings", json={"session": "rec-concurrent", "frames": [big, big]}
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(code == 200 for code in pool.map(flush, range(16)))

    out = (tmp_path / "rec" / "rec-concurrent.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 32
    for ln in lines:
        json.loads(ln)  # must not raise — a split line would


def test_default_app_wires_a_registry_backed_context_source(tmp_path: Path) -> None:
    """With precompute on by default, a plain ``create_app`` gives the engine a context source —
    so `/recommendation` can reach 200. Construction alone must stay network-free (the registry
    is built eagerly; every provider pull happens lazily inside the closure)."""
    app = create_app(
        Settings(
            _env_file=None,
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
        )
    )
    assert app.state.rec_engine._context_source is not None


def test_precompute_can_still_be_switched_off(tmp_path: Path) -> None:
    """The kill-switch still works — an owner (or a test) can pin the old warming-up behaviour."""
    app = create_app(
        Settings(
            _env_file=None,
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            jaaffl_precompute_enabled=False,
        )
    )
    assert app.state.rec_engine._context_source is None
