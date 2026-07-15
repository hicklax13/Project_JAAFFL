"""FastAPI application for the localhost companion service.

Receives normalized draft events from the extension, and (once the engine lands in
Stage 5) serves recommendations back to the overlay and dashboard. Bound to localhost;
CORS is permissive because the only callers are the user's own extension and dashboard.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from jaaffl import __version__
from jaaffl.config import get_settings
from jaaffl.domain import DraftEvent, Recommendation
from jaaffl.ingest import handle_event

log = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="JAAFFL companion service", version=__version__)

    # Local-only service; callers are the user's extension (chrome-extension://) and
    # dashboard (http://localhost:3000). Allow all origins since we bind to 127.0.0.1.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/draft/events")
    async def ingest_event(event: DraftEvent) -> dict:
        """Ingest a single normalized draft event from the extension."""
        handle_event(event)
        return {"accepted": True}

    @app.websocket("/draft/ws")
    async def draft_ws(ws: WebSocket) -> None:
        """Stream normalized draft events for the duration of a live draft."""
        await ws.accept()
        log.info("draft_ws_connected")
        try:
            while True:
                payload = await ws.receive_json()
                handle_event(DraftEvent.model_validate(payload))
                await ws.send_json({"accepted": True})
        except WebSocketDisconnect:
            log.info("draft_ws_disconnected")

    @app.get("/recommendation", response_model=Recommendation)
    def recommendation(league_id: str) -> Recommendation:
        # TODO(stage 5): load current DraftState + LeagueSettings from the warehouse and
        # call jaaffl.engine.recommend(...).
        raise HTTPException(status_code=501, detail="engine not yet implemented (roadmap stage 5)")

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
