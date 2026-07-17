"""Ingest layer — turn extension payloads into persisted domain state (Stage 1-2).

Ordering invariant (plan §2.6): validate/normalize -> **durable append to the SQLite
append-only log** -> fold -> return. The append commits (fsync) BEFORE any downstream
work, so a crash after it loses only recompute work — never a pick.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

import structlog

from jaaffl.domain import DraftEvent, DraftEventType, DraftState, Recommendation
from jaaffl.ingest.cbs import (
    normalize_draft_state,
    normalize_event_data,
    normalize_league_settings,
)
from jaaffl.ingest.log import DraftLog
from jaaffl.ingest.resolve import resolve_pick_ids

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
    "resolve_pick_ids",
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
    recommendations: list[Recommendation] | None = None,
) -> IngestResult:
    """Normalize, snapshot raw settings, durably append, then fold (the §2.6 ordering
    invariant). Raises pydantic.ValidationError on a malformed per-type payload BEFORE
    anything is persisted.

    When a ``warehouse`` is wired, a ``league_settings`` event is snapshotted to
    ``league_snapshots`` (SQLite only — hot-path safe) BEFORE the durable log append, so the
    raw CBS payload is owned locally for Stage-4 ``CbsOnPageProvider`` (never re-fetched). At
    ``draft_complete`` any ``recommendations`` the engine emitted are written alongside the
    terminal export as ``recommendations.jsonl`` (the app layer accumulates them; ingest stays
    engine-free — it only forwards the list)."""
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
    if (
        warehouse is not None
        and seq is not None
        and event.event_type == DraftEventType.DRAFT_COMPLETE
        and _is_first_complete(draft_log, event.league_id)
    ):
        # §2.8 offline backtest corpus: export final_state.json + events.parquet (+ the engine's
        # recommendations.jsonl, when the app passes them) exactly once at draft end. draft_complete
        # has no pick_number so it never dedups and the 3-probe capture can send several — the
        # first-complete guard keeps the export idempotent.
        warehouse.snapshot_draft_state(
            state, recommendations=recommendations, captured_at=captured_at
        )
    # The recompute + /recs/ws publish for a state-advancing, non-deduped event is orchestrated by
    # the API layer (jaaffl.api.app) after this returns, so ingest stays engine-free (§4.7).
    return IngestResult(seq=seq, deduped=seq is None, pick_number=pick_number, state=state)


def _is_first_complete(draft_log: DraftLog, league_id: str) -> bool:
    """True when exactly one draft_complete event exists for the league (the one just appended),
    so the terminal export fires once despite multi-probe / re-sent draft_complete events."""
    return (
        sum(1 for e in draft_log.events(league_id) if e.event_type == DraftEventType.DRAFT_COMPLETE)
        == 1
    )
