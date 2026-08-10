"""TIER 3 / TASK 4 — the overlay's VONA was structurally zero on draft night.

Found by the Tier-3 replay harness, not by any unit test. Three facts compose into a defect
that every individual test misses:

1. No CBS frame names the VIEWER's own team, so ``parse.ts`` cannot emit ``my_team_id`` and
   the folded ``DraftState`` never has one.
2. ``opponents._my_overall_picks`` raises without it, and ``recommend`` catches that and
   degrades survival to "everyone is available" — a documented, deliberate fallback.
3. ``GET /recommendation?team_id=`` supplies the slot. The ``/recs/ws`` PUSH path, which is
   what actually feeds the overlay after every pick, does not.

So the surface the owner watches during the draft renders ``vona 0.00`` on its best pick,
looking exactly like a computed number. That is the Tier-1 failure signature again: a healthy
response carrying a dead model.

Fixed two ways, because either alone is a trap: the slot is configurable
(``JAAFFL_MY_TEAM_ID``) so the push path can compute real survival, AND the recommendation
states which basis it used, so an unset slot is visible rather than silently zero.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from jaaffl.api import create_app
from jaaffl.config import Settings
from jaaffl.domain import Recommendation
from tests.test_api import _primed_engine, pick_payload


def _app(tmp_path: Path, **settings):
    return create_app(
        Settings(
            jaaffl_data_dir=tmp_path / "data",
            jaaffl_recordings_dir=tmp_path / "rec",
            **settings,
        ),
        rec_engine=_primed_engine(),
    )


class TestTheSurvivalBasisIsStated:
    """The degradation must be legible on the contract, not inferable from a zero."""

    def test_a_recommendation_with_a_known_slot_says_so(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"}).json()
        Recommendation.model_validate(body)
        assert body["survival_basis"] == "my_slot"

    def test_a_recommendation_without_one_admits_the_model_is_degraded(
        self, tmp_path: Path
    ) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        Recommendation.model_validate(body)
        assert body["survival_basis"] == "degraded_no_slot"

    def test_the_degraded_reason_distinguishes_a_missing_order_from_a_missing_slot(
        self, tmp_path: Path
    ) -> None:
        """⚠️ TIER 12. Every test in this class runs against ``_primed_engine()``, whose context
        carries a draft order from ``engine_fixtures.make_context``'s default — which is exactly
        why this file passed for nine tiers while the LIVE path could never reach 'my_slot' at
        all. Here the order IS known and the slot is not, so 'degraded_no_slot' is the honest
        answer. The wiring version of this assertion, taken from
        ``league.constitution.resolve_league_settings`` instead of a fixture, lives in
        ``test_draft_order_wiring.py``."""
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        assert body["survival_basis"] == "degraded_no_slot"

    def test_the_degraded_basis_is_exactly_when_vona_collapses(self, tmp_path: Path) -> None:
        # Ties the flag to the thing it is warning about, so the two cannot drift apart.
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        degraded = client.get("/recommendation", params={"league_id": "L1"}).json()
        assert degraded["survival_basis"] == "degraded_no_slot"
        assert degraded["ranked"][0]["components"]["vona"] == 0.0

        real = client.get("/recommendation", params={"league_id": "L1", "team_id": "t0"}).json()
        assert real["survival_basis"] == "my_slot"
        assert real["ranked"][0]["components"]["vona"] != 0.0


class TestThePushPathGetsTheSlot:
    """The overlay never passes a query parameter — it just receives pushes."""

    @staticmethod
    def _push_after_a_pick(client: TestClient) -> dict:
        """Ingest one pick and return the Recommendation the server PUSHED (§8.5 envelope:
        hello -> snapshot -> rec)."""
        with client.websocket_connect("/recs/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "snapshot"
            client.post("/draft/events", json=pick_payload(1))
            frame = ws.receive_json()
            assert frame["type"] == "rec"
            return Recommendation.model_validate(frame["recommendation"]).model_dump()

    def test_the_pushed_recommendation_uses_the_configured_slot(self, tmp_path: Path) -> None:
        rec = self._push_after_a_pick(TestClient(_app(tmp_path, jaaffl_my_team_id="t0")))
        assert rec["survival_basis"] == "my_slot"
        assert rec["ranked"][0]["components"]["vona"] != 0.0

    def test_without_the_setting_the_push_says_it_is_degraded(self, tmp_path: Path) -> None:
        # The pre-fix behaviour, kept visible rather than removed: an owner who never sets
        # the slot still gets a recommendation, and it no longer pretends VONA is computed.
        rec = self._push_after_a_pick(TestClient(_app(tmp_path)))
        assert rec["survival_basis"] == "degraded_no_slot"
        assert rec["ranked"][0]["components"]["vona"] == 0.0

    def test_an_explicit_query_slot_still_wins_over_the_setting(self, tmp_path: Path) -> None:
        app = _app(tmp_path, jaaffl_my_team_id="t0")
        client = TestClient(app)
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1", "team_id": "t3"}).json()
        # The caller asked about t3's board; the configured default must not override it.
        assert body["survival_basis"] == "my_slot"
        assert body["roster_filled"] is not None


class TestThePullPathGetsTheSlotToo:
    """TIER 12. The push path reads jaaffl_my_team_id (Tier 3); the pull path did not, so
    apps/web/lib/api.ts — which calls /recommendation?league_id=... with NO team_id — rendered a
    degraded model while the overlay next to it rendered a live one, on the same draft. Two
    surfaces disagreeing about the same board, with the quieter one wrong."""

    def test_the_configured_slot_is_the_pull_default(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path, jaaffl_my_team_id="t0"))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        assert body["survival_basis"] == "my_slot"

    def test_an_explicit_query_slot_still_wins_on_the_pull_path(self, tmp_path: Path) -> None:
        """Auditing another seat's board stays possible — the setting is a default, not a lock."""
        client = TestClient(_app(tmp_path, jaaffl_my_team_id="t0"))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1", "team_id": "t3"}).json()
        assert body["survival_basis"] == "my_slot"
        assert body["roster_filled"] is not None

    def test_with_no_setting_the_pull_path_is_still_honestly_degraded(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        assert body["survival_basis"] == "degraded_no_slot"

    def test_an_EMPTY_configured_slot_does_not_clobber_a_folded_one(self, tmp_path: Path) -> None:
        """⚠️ Found in code review — a regression Tier 12 introduced, reachable with the owner's
        real .env. `JAAFFL_MY_TEAM_ID=` parses as '' (not None), so `if resolved is not None`
        overwrote a slot the fold already knew with an empty string. The push path was never
        affected: it fills only when absent and tests truthiness. The two paths must agree."""
        client = TestClient(_app(tmp_path, jaaffl_my_team_id=""))
        client.post("/draft/events", json=pick_payload(1))
        client.post(
            "/draft/events",
            json={
                "event_type": "league_settings",
                "league_id": "L1",
                "data": {"team_count": 12, "my_team_id": "t0"},
            },
        )
        body = client.get("/recommendation", params={"league_id": "L1"}).json()
        assert body["survival_basis"] == "my_slot"


class TestTheDashboardsMarkersAreLiveToo:
    """⚠️ Found in code review, and it is instance EIGHT committed by Tier 12's own new test.

    `analytics._marker_picks` needs BOTH the room's order and my slot. Tier 12 wired the order and
    declared the dashboard fixed — but `grep -rn my_team_id apps/extension/src/` returns NOTHING,
    so the folded state never carries a slot on the live path, and the markers stayed empty. The
    test that said otherwise passed only because its fixture supplied a slot by hand.

    This one drives the API with the exact event shape the extension emits, so it can only pass if
    the WIRING produces both inputs.
    """

    @staticmethod
    def _order_event() -> dict:
        return {
            "event_type": "league_settings",
            "league_id": "L1",
            "source": "ws",
            "data": {
                "league_id": "L1",
                "team_count": 12,
                "draft_order": [f"t{i}" for i in range(12)],
            },
        }

    def test_markers_are_live_from_the_wiring_alone(self, tmp_path: Path) -> None:
        client = TestClient(_app(tmp_path, jaaffl_my_team_id="t0"))
        assert client.post("/draft/events", json=self._order_event()).status_code == 200
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/analytics", params={"league_id": "L1"}).json()
        assert body["my_next_picks"], "markers empty: the live wiring cannot supply order + slot"

    def test_without_a_configured_slot_the_markers_degrade_rather_than_lie(
        self, tmp_path: Path
    ) -> None:
        client = TestClient(_app(tmp_path))
        client.post("/draft/events", json=self._order_event())
        client.post("/draft/events", json=pick_payload(1))
        body = client.get("/analytics", params={"league_id": "L1"}).json()
        assert body["my_next_picks"] == []
