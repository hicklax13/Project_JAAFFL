"""The companion-service wire path: health, ingest (REST + WS /draft/ws with the §8.4
frame contract), the /recommendation engine endpoint, and the /recs/ws push channel."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jaaffl import __version__
from jaaffl.api import create_app
from jaaffl.api.recs import RecsHub
from jaaffl.config import Settings
from jaaffl.domain import Position, Recommendation, RecommendedPick
from jaaffl.engine.service import RecommendationEngine
from jaaffl.ingest.log import DraftLog
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
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "recordings",
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
