"""Ingest layer — turn extension payloads into persisted domain state (Stage 1-2).

Ordering invariant (plan §2.6): validate/normalize -> **durable append to the SQLite
append-only log** -> fold -> return. The append commits (fsync) BEFORE any downstream
work, so a crash after it loses only recompute work — never a pick.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

import structlog

from jaaffl.domain import DraftEvent, DraftEventType, DraftState
from jaaffl.ingest.cbs import (
    normalize_draft_state,
    normalize_event_data,
    normalize_league_settings,
)
from jaaffl.ingest.log import DraftLog

if TYPE_CHECKING:  # avoid importing the data layer (and its optional deps) at runtime
    from jaaffl.data.warehouse import Warehouse

log = structlog.get_logger(__name__)

__all__ = [
    "DraftLog",
    "IngestResult",
    "handle_event",
    "normalize_draft_state",
    "normalize_event_data",
    "normalize_league_settings",
]


class IngestResult(NamedTuple):
    seq: int | None  # None when the storage layer de-duped the event
    deduped: bool
    pick_number: int | None  # the storage de-dup key actually used (may be derived)
    state: DraftState


def _dedup_pick_number(event: DraftEvent) -> int | None:
    """Derive the storage de-dup key (§2.3 ux_event_pick) when the envelope omits it."""
    if event.pick_number is not None:
        return event.pick_number
    if event.event_type == DraftEventType.PICK_MADE:
        overall = event.data.get("overall")
        return int(overall) if overall is not None else None
    if event.event_type == DraftEventType.ON_THE_CLOCK:
        current = event.data.get("current_overall_pick")
        return int(current) if current is not None else None
    return None


def handle_event(
    event: DraftEvent,
    draft_log: DraftLog,
    *,
    warehouse: Warehouse | None = None,
    captured_at: str | None = None,
) -> IngestResult:
    """Normalize, snapshot raw settings, durably append, then fold (the §2.6 ordering
    invariant). Raises pydantic.ValidationError on a malformed per-type payload BEFORE
    anything is persisted.

    When a ``warehouse`` is wired, a ``league_settings`` event is snapshotted to
    ``league_snapshots`` (SQLite only — hot-path safe) BEFORE the durable log append, so the
    raw CBS payload is owned locally for Stage-4 ``CbsOnPageProvider`` (never re-fetched)."""
    normalize_event_data(event)  # the validation gate — §2.3 "payload is validated"
    if warehouse is not None and event.event_type == DraftEventType.LEAGUE_SETTINGS:
        settings = normalize_league_settings({"league_id": event.league_id, **event.data})
        warehouse.snapshot_league(settings)  # raw CBS → league_snapshots, before the append
    pick_number = _dedup_pick_number(event)
    seq = draft_log.append(
        event,
        pick_number=pick_number,
        source=str(event.source) if event.source else None,
        captured_at=captured_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    )
    state = draft_log.state(event.league_id)
    log.info(
        "draft_event",
        event_type=event.event_type,
        league_id=event.league_id,
        pick_number=pick_number,
        source=event.source,
        seq=seq,
        deduped=seq is None,
    )
    # TODO(stage 5): on state-advancing, non-deduped events call engine.recompute() and
    # publish the fresh Recommendation on app.state.recs_hub (/recs/ws).
    return IngestResult(seq=seq, deduped=seq is None, pick_number=pick_number, state=state)
