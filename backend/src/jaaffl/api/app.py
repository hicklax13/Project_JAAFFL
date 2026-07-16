"""FastAPI application for the localhost companion service.

Receives normalized draft events from the extension, and (once the engine lands in
Stage 5) serves recommendations back to the overlay and dashboard. Bound to localhost;
CORS is permissive because the only callers are the user's own extension and dashboard.
"""

from __future__ import annotations

import json

import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from jaaffl import __version__
from jaaffl.api.origin import is_origin_allowed, parse_allowed_origins
from jaaffl.api.recs import PROTOCOL_VERSION, SCHEMA_VERSION, RecsHub
from jaaffl.config import Settings, get_settings
from jaaffl.data.warehouse import Warehouse, open_app_db
from jaaffl.domain import DraftEvent, LeagueSettings, Recommendation
from jaaffl.ingest import DraftLog, handle_event

log = structlog.get_logger(__name__)


class RecordingBatch(BaseModel):
    """One record-mode flush from the extension (src/lib/record.ts). Module-scoped so
    FastAPI can resolve the PEP-563 string annotation."""

    session: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")  # filename-safe, no paths
    frames: list[dict] = Field(default_factory=list)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="JAAFFL companion service", version=__version__)
    app.state.recs_hub = RecsHub()
    app.state.draft_log = DraftLog(settings.jaaffl_data_dir / "app.sqlite")
    app.state.warehouse = Warehouse(settings.jaaffl_data_dir)
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

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/draft/events")
    async def ingest_event(event: DraftEvent, request: Request) -> dict:
        """Ingest one normalized draft event (REST fail-soft path, §5.6): durable append
        -> fold -> idempotent ack. Malformed per-type payloads 422 before any append."""
        require_allowed_origin(request)
        try:
            result = handle_event(event, app.state.draft_log, warehouse=app.state.warehouse)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=exc.errors(include_url=False, include_context=False)
            ) from exc
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
        except WebSocketDisconnect:
            log.info("draft_ws_disconnected")

    @app.get("/recommendation", response_model=Recommendation)
    def recommendation(league_id: str) -> Recommendation:
        # TODO(stage 5): load current DraftState + LeagueSettings from the warehouse and
        # call jaaffl.engine.recommend(...).
        raise HTTPException(status_code=501, detail="engine not yet implemented (roadmap stage 5)")

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
    def league(league_id: str) -> LeagueSettings:
        # TODO(stage 2): serve the normalized settings ingested from the CBS league pages.
        raise HTTPException(
            status_code=404, detail="league settings not yet ingested (roadmap stage 2)"
        )

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
