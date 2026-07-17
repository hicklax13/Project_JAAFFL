"""FastAPI application for the localhost companion service.

Receives normalized draft events from the extension and serves decomposed recommendations back to
the overlay and dashboard (pull via GET /recommendation, push via WS /recs/ws). Bound to localhost;
CORS is scoped to the user's own extension + dashboard, and every WS handler re-checks Origin.
"""

from __future__ import annotations

import json

import structlog
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from jaaffl import __version__
from jaaffl.api.origin import is_origin_allowed, parse_allowed_origins
from jaaffl.api.recs import PROTOCOL_VERSION, SCHEMA_VERSION, RecsHub
from jaaffl.config import Settings, get_settings
from jaaffl.data.warehouse import Warehouse, open_app_db
from jaaffl.domain import DraftEvent, DraftEventType, LeagueSettings, Recommendation
from jaaffl.engine.service import RecommendationEngine
from jaaffl.ingest import DraftLog, IngestResult, handle_event
from jaaffl.league.constitution import resolve_league_settings

log = structlog.get_logger(__name__)

# Events that advance the draft state and therefore warrant a fresh recommendation (§8.4 step 4).
_STATE_ADVANCING = {
    DraftEventType.PICK_MADE,
    DraftEventType.ON_THE_CLOCK,
    DraftEventType.DRAFT_STATE,
}


class RecordingBatch(BaseModel):
    """One record-mode flush from the extension (src/lib/record.ts). Module-scoped so
    FastAPI can resolve the PEP-563 string annotation."""

    session: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")  # filename-safe, no paths
    frames: list[dict] = Field(default_factory=list)


def create_app(
    settings: Settings | None = None,
    *,
    rec_engine: RecommendationEngine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="JAAFFL companion service", version=__version__)
    app.state.recs_hub = RecsHub()
    app.state.draft_log = DraftLog(settings.jaaffl_data_dir / "app.sqlite")
    app.state.warehouse = Warehouse(settings.jaaffl_data_dir)
    # The Stage-5 engine. An injected engine wins (tests prime one). Otherwise, when the precompute
    # bridge is enabled, build a registry-backed context_source (the $0 providers) so the engine
    # lazily precomputes a real DraftContext per league on first use (→ /recommendation 503 → 200);
    # all provider I/O + network live in that source, not the hot path (§4.7). When disabled (the
    # default), the engine has no context yet and /recommendation stays 503 "warming up" until a
    # context is primed. Per-league recommendation history feeds the recommendations.jsonl export.
    if rec_engine is not None:
        app.state.rec_engine = rec_engine
    elif settings.jaaffl_precompute_enabled:
        from jaaffl.engine.precompute import build_registry_context_source

        app.state.rec_engine = RecommendationEngine(
            context_source=build_registry_context_source(settings, warehouse=app.state.warehouse)
        )
    else:
        app.state.rec_engine = RecommendationEngine()
    app.state.rec_history = {}
    # Ensure the SQLite app-state schema (league_snapshots, players, id_crosswalk, ...) exists
    # from boot — stdlib sqlite only, no DuckDB import, so the base ($0) install still starts
    # without the `data` extra. Full DuckDB/Parquet materialization is `make warehouse`.
    open_app_db(app.state.warehouse.app_sqlite).close()
    allowed_origins = parse_allowed_origins(settings.jaaffl_allowed_origins)

    # Local-only service. CORS is scoped to the user's own extension + local dashboard;
    # a WebSocket handshake is not gated by CORS, so each WS handler re-checks Origin.
    cors_origins = ["*"] if "*" in allowed_origins else allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=None if "*" in allowed_origins else r"chrome-extension://.*",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_allowed_origin(request: Request) -> None:
        if not is_origin_allowed(request.headers.get("origin"), allowed_origins):
            raise HTTPException(status_code=403, detail="origin not allowed")

    def ws_origin_ok(ws: WebSocket) -> bool:
        return is_origin_allowed(ws.headers.get("origin"), allowed_origins)

    def publish_recommendation(event: DraftEvent, result: IngestResult) -> None:
        """On a state-advancing, non-deduped event, recompute and push to /recs/ws (§8.4 step 4).

        Provider-free hot path: the engine reads its precomputed context, never a provider. A
        deduped re-send (a slower capture probe) does NOT re-broadcast. Recommendations accumulate
        per league for the draft-complete recommendations.jsonl export."""
        if result.seq is None or event.event_type not in _STATE_ADVANCING:
            return
        recommendation = app.state.rec_engine.recommend(result.state)
        if recommendation is not None:
            app.state.recs_hub.publish(recommendation)
            app.state.rec_history.setdefault(event.league_id, []).append(recommendation)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/draft/events")
    async def ingest_event(event: DraftEvent, request: Request) -> dict:
        """Ingest one normalized draft event (REST fail-soft path, §5.6): durable append
        -> fold -> idempotent ack. Malformed per-type payloads 422 before any append."""
        require_allowed_origin(request)
        try:
            result = handle_event(
                event,
                app.state.draft_log,
                warehouse=app.state.warehouse,
                recommendations=app.state.rec_history.get(event.league_id),
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=exc.errors(include_url=False, include_context=False)
            ) from exc
        publish_recommendation(event, result)
        return {"accepted": True, "seq": result.seq, "deduped": result.deduped}

    @app.websocket("/draft/ws")
    async def draft_ws(ws: WebSocket) -> None:
        """Ingest socket (§8.4): accepts bare DraftEvents or {type:"event",...} envelopes,
        answers control heartbeats, and acks every accepted event idempotently. Control
        frames are dropped BEFORE the append-only log (A10) so replay stays clean."""
        if not ws_origin_ok(ws):
            await ws.close(code=1008)  # policy violation (§8.6)
            return
        await ws.accept()
        log.info("draft_ws_connected")
        try:
            while True:
                frame = await ws.receive_json()
                if not isinstance(frame, dict):
                    await ws.send_json(
                        {
                            "type": "error",
                            "v": PROTOCOL_VERSION,
                            "code": 4400,
                            "detail": "frame must be a JSON object",
                        }
                    )
                    continue
                # Heartbeats — both vocabularies (§5.6 {control:"ping"}, §8.4 {type:"ping"}).
                if frame.get("control") in ("ping", "pong"):
                    if frame["control"] == "ping":
                        await ws.send_json({"control": "pong"})
                    continue
                if frame.get("type") in ("ping", "pong"):
                    if frame["type"] == "ping":
                        await ws.send_json({"type": "pong", "v": PROTOCOL_VERSION})
                    continue
                payload = frame.get("event") if frame.get("type") == "event" else frame
                captured_at = frame.get("ts") if frame.get("type") == "event" else None
                try:
                    event = DraftEvent.model_validate(payload)
                    result = handle_event(
                        event,
                        app.state.draft_log,
                        warehouse=app.state.warehouse,
                        captured_at=captured_at,
                        recommendations=app.state.rec_history.get(event.league_id),
                    )
                except ValidationError as exc:
                    await ws.send_json(
                        {
                            "type": "error",
                            "v": PROTOCOL_VERSION,
                            "code": 4422,
                            "detail": "DraftEvent validation failed",
                            "errors": exc.errors(include_url=False, include_context=False),
                        }
                    )
                    continue
                await ws.send_json(
                    {
                        "type": "ack",
                        "v": PROTOCOL_VERSION,
                        "seq": result.seq,
                        "pick_number": result.pick_number,
                        "accepted": True,
                        "deduped": result.deduped,
                    }
                )
                publish_recommendation(event, result)  # push a fresh rec to /recs/ws (§8.4 step 5)
        except WebSocketDisconnect:
            log.info("draft_ws_disconnected")

    @app.get("/recommendation", response_model=Recommendation)
    def recommendation(
        request: Request,
        league_id: str,
        as_of_overall_pick: int | None = Query(default=None, ge=1),
        team_id: str | None = None,
        limit: int = Query(default=5, ge=1, le=50),
        include_components: bool = True,
        mc: bool = False,
    ) -> Recommendation:
        """The decomposed recommendation for the current pick (§8.3.3) — the pull twin of the
        /recs/ws push. Loads the folded DraftState and calls the stateless engine recompute."""
        require_allowed_origin(request)
        if not app.state.draft_log.events(league_id):
            known = app.state.warehouse.latest_cbs_snapshot(league_id) is not None
            raise HTTPException(
                status_code=409 if known else 404,
                detail=(
                    f"draft not started for league '{league_id}'"
                    if known
                    else f"unknown league '{league_id}'"
                ),
            )
        state = app.state.draft_log.state(league_id)
        if as_of_overall_pick is not None:
            # Audit a past pick: reconstruct the board as of then — drop picks at/after that pick
            # so players taken later are AVAILABLE again (not masked), matching what the engine
            # actually saw at the time.
            state = state.model_copy(
                update={
                    "current_overall_pick": as_of_overall_pick,
                    "picks": [p for p in state.picks if p.overall < as_of_overall_pick],
                }
            )
        if team_id is not None:
            state = state.model_copy(update={"my_team_id": team_id})
        rec = app.state.rec_engine.recommend(state, limit=limit, use_mc=mc)
        if rec is None:
            raise HTTPException(status_code=503, detail="engine warming up")
        if not include_components:
            rec = rec.model_copy(
                update={"ranked": [p.model_copy(update={"components": None}) for p in rec.ranked]}
            )
        return rec

    @app.websocket("/recs/ws")
    async def recs_ws(ws: WebSocket) -> None:
        """PUSH channel: backend -> overlay/dashboard, read-only to the client (§8.5).

        Sends `hello` then a `snapshot` of the latest Recommendation on connect (late
        joiners resynchronize from state, never a replayed stream), then one `rec` frame
        per published Recommendation. Frames reuse the shared Recommendation contract
        verbatim — no bespoke socket shape.
        """
        if not ws_origin_ok(ws):
            await ws.close(code=1008)  # policy violation (§8.6)
            return
        await ws.accept()
        hub: RecsHub = ws.app.state.recs_hub
        queue = hub.subscribe()
        log.info("recs_ws_connected")
        try:
            await ws.send_json(
                {
                    "type": "hello",
                    "v": PROTOCOL_VERSION,
                    "server_version": __version__,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            latest = hub.latest
            await ws.send_json(
                {
                    "type": "snapshot",
                    "v": PROTOCOL_VERSION,
                    "recommendation": latest.model_dump() if latest else None,
                }
            )
            while True:
                await ws.send_text(await queue.get())  # frames pre-serialized by the hub
        except WebSocketDisconnect:
            log.info("recs_ws_disconnected")
        finally:
            hub.unsubscribe(queue)

    @app.post("/dev/recordings")
    def store_recording(batch: RecordingBatch, request: Request) -> dict:
        """Record-mode capture sink (Phase-1 tooling, localhost-only): appends observed
        frames as JSONL under the recordings dir so ONE real CBS mock draft yields the
        golden fixtures that finalize parse.ts (TODO(capture))."""
        require_allowed_origin(request)
        settings.jaaffl_recordings_dir.mkdir(parents=True, exist_ok=True)
        out = settings.jaaffl_recordings_dir / f"{batch.session}.jsonl"
        with out.open("a", encoding="utf-8", newline="\n") as fh:
            for frame in batch.frames:
                fh.write(json.dumps(frame, sort_keys=True) + "\n")
        log.info("recording_stored", session=batch.session, frames=len(batch.frames))
        return {"stored": len(batch.frames), "file": str(out)}

    @app.get("/league/{league_id}", response_model=LeagueSettings)
    def league(request: Request, league_id: str) -> LeagueSettings:
        """Serve the normalized LeagueSettings the dashboard needs: the immutable constitution
        (config/league.json) roster + the CBS scoring overlay (offline cbs_standard_scoring until a
        live capture lands, TODO(capture); a captured CBS snapshot's scoring wins when present).

        200 for the configured primary league, or any league that already has a CBS snapshot or
        folded draft events; 404 otherwise. The immutable roster is reproduced verbatim (team_count
        12, snake, QB1/RB1/WR3/flex1/TE1/K1/DST1/Bench8, draft_order null — never inferred).

        Read-only, but it honours the same Origin allowlist as its siblings — a hostile
        cross-origin page can't read the constitution even if origins are widened."""
        require_allowed_origin(request)
        snapshot = app.state.warehouse.latest_cbs_snapshot(league_id)
        known = (
            league_id == settings.jaaffl_league_id
            or snapshot is not None
            or bool(app.state.draft_log.events(league_id))
        )
        if not known:
            raise HTTPException(status_code=404, detail=f"unknown league '{league_id}'")
        return resolve_league_settings(league_id, snapshot=snapshot)

    return app


def main() -> None:
    """Console entrypoint (``jaaffl-api``) and ``python -m jaaffl.api``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "jaaffl.api.app:create_app",
        factory=True,
        host=settings.jaaffl_api_host,
        port=settings.jaaffl_api_port,
    )
