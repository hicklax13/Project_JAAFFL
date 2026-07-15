"""The Stage-1 companion service wire path: health, event ingest, recommendation stub."""

from fastapi.testclient import TestClient

from jaaffl.api import create_app

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
