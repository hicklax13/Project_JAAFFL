"""Normalize raw CBS payloads (captured by the extension) into domain models.

The extension does light normalization in the browser; this module owns the
authoritative parse into ``LeagueSettings`` / ``DraftState``. Draft order is read from
the live room, never inferred from league size alone. Conflicts with the immutable
league constitution (config/league.json) are SURFACED as-read, never silently corrected
(agent_usage_contract).
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from jaaffl.domain import DraftEvent, DraftEventType, DraftPick, DraftState, LeagueSettings

log = structlog.get_logger(__name__)

# The immutable constitution these payloads are checked against (config/league.json).
_IMMUTABLE_TEAM_COUNT = 12
_IMMUTABLE_DRAFT_TYPE = "snake"


class _OnTheClockData(BaseModel):
    """Minimal shape of an on_the_clock payload (fold reads exactly these keys)."""

    current_overall_pick: int = Field(ge=1)
    team_id: str | None = None


def normalize_league_settings(raw: dict) -> LeagueSettings:
    """Validate an extension-normalized CBS settings payload into ``LeagueSettings``.

    Reports the payload AS READ: a value conflicting with the immutable league
    (team_count != 12, draft_type != snake) is surfaced via a warning and returned
    verbatim — downstream consumers decide; nothing is silently corrected. Full CBS
    raw-DOM parsing (scoring map extraction) is the extension's parse.ts job; the
    stage-2 track deepens this normalizer.
    """
    settings = LeagueSettings.model_validate(raw)
    if settings.team_count != _IMMUTABLE_TEAM_COUNT:
        log.warning(
            "league_settings_conflict",
            field="team_count",
            read=settings.team_count,
            immutable=_IMMUTABLE_TEAM_COUNT,
        )
    if settings.draft_type != _IMMUTABLE_DRAFT_TYPE:
        log.warning(
            "league_settings_conflict",
            field="draft_type",
            read=settings.draft_type,
            immutable=_IMMUTABLE_DRAFT_TYPE,
        )
    return settings


def normalize_draft_state(raw: dict) -> DraftState:
    """Validate a live CBS draft-board snapshot into a ``DraftState``.

    The snapshot's pick order is the live CBS order (decided in person, entered into
    CBS) — this function never synthesizes an order from team count.
    """
    return DraftState.model_validate(raw)


def normalize_event_data(event: DraftEvent) -> None:
    """Per-type validation gate for ``DraftEvent.data`` (§2.3: the stored payload is the
    validated data for its concrete model). Raises pydantic.ValidationError on a
    malformed payload; extra CBS passthrough keys (cbs_player_id, player_name, ...) are
    preserved in the stored payload for the stage-3 crosswalk."""
    if event.event_type == DraftEventType.PICK_MADE:
        DraftPick.model_validate(event.data)
    elif event.event_type == DraftEventType.ON_THE_CLOCK:
        _OnTheClockData.model_validate(event.data)
    elif event.event_type == DraftEventType.DRAFT_STATE:
        normalize_draft_state({"league_id": event.league_id, **event.data})
    elif event.event_type == DraftEventType.LEAGUE_SETTINGS:
        normalize_league_settings({"league_id": event.league_id, **event.data})
    # draft_complete carries no payload contract.
