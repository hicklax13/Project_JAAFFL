"""Ingest layer — turn extension payloads into persisted domain state (Stage 1–2)."""

from __future__ import annotations

import structlog

from jaaffl.domain import DraftEvent
from jaaffl.ingest.cbs import normalize_draft_state, normalize_league_settings

log = structlog.get_logger(__name__)

__all__ = ["handle_event", "normalize_draft_state", "normalize_league_settings"]


def handle_event(event: DraftEvent) -> None:
    """Route and persist a normalized draft event.

    TODO(stage 1–3): validate ``event.data`` into its concrete model, snapshot it to the
    warehouse (``jaaffl.data``), and on pick/clock events refresh the current recommendation.
    For now this is an observable no-op so the wire path can be exercised end to end.
    """
    log.info("draft_event", event_type=event.event_type, league_id=event.league_id)
