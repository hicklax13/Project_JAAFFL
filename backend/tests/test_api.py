"""The Stage-1 companion service wire path: health, event ingest, recommendation stub."""

from fastapi.testclient import TestClient

from jaaffl import __version__
from jaaffl.api import create_app
from jaaffl.api.recs import recs_hub
from jaaffl.domain import Recommendation, RecommendedPick

client = TestClient(create_app())


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ingest_event_accepted() -> None:
    event = {
        "event_type": "pick_made",
        "league_id": "L1",
        "data": {"overall": 1, "round": 1, "pick_in_round": 1, "team_id": "T3"},
    }
    res = client.post("/draft/events", json=event)
    assert res.status_code == 200
    assert res.json() == {"accepted": True}


def test_ingest_rejects_bad_event() -> None:
    res = client.post("/draft/events", json={"event_type": "not_a_type", "league_id": "L1"})
    assert res.status_code == 422


def test_recommendation_stubbed_until_engine() -> None:
    res = client.get("/recommendation", params={"league_id": "L1"})
    assert res.status_code == 501


def test_league_settings_404_until_ingested() -> None:
    res = client.get("/league/unknown-league")
    assert res.status_code == 404


def test_recs_ws_sends_hello_then_snapshot_on_connect() -> None:
    """SC4 (§8.5): after accept the server sends `hello`, then a `snapshot` of the current
    best Recommendation (null until the engine lands) so late joiners are always correct."""
    recs_hub.reset()
    with client.websocket_connect("/recs/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["v"] == 1
        assert hello["server_version"] == __version__
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["v"] == 1
        assert snapshot["recommendation"] is None  # no engine yet (stage 5)


def test_recs_ws_broadcasts_published_recommendation() -> None:
    """A Recommendation published on the hub reaches subscribers as a `rec` frame that
    round-trips the shared Recommendation contract verbatim (no bespoke socket shape)."""
    recs_hub.reset()
    rec = Recommendation(
        league_id="L1",
        as_of_overall_pick=13,
        ranked=[RecommendedPick(player_id="p1", score=42.0)],
    )
    with client.websocket_connect("/recs/ws") as ws:
        ws.receive_json()  # hello
        ws.receive_json()  # snapshot
        recs_hub.publish(rec)
        frame = ws.receive_json()
        assert frame["type"] == "rec"
        assert frame["v"] == 1
        assert Recommendation.model_validate(frame["recommendation"]) == rec


def test_recs_ws_snapshot_replays_latest_rec_to_late_joiners() -> None:
    recs_hub.reset()
    rec = Recommendation(league_id="L1", as_of_overall_pick=14, ranked=[])
    recs_hub.publish(rec)
    with client.websocket_connect("/recs/ws") as ws:
        ws.receive_json()  # hello
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert Recommendation.model_validate(snapshot["recommendation"]) == rec
