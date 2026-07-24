"""Board / pick-log view over the folded draft (dashboard ``GET /state``).

The dashboard board + pick-log need each drafted pick's display name / position / team. The folded
:class:`DraftState`'s picks carry only ``player_id`` (a frozen contract), so the names are joined
from the raw ``pick_made`` event payloads — the same source :func:`resolve_pick_ids` reads. Pure
function, no I/O: the endpoint wires it to the live log.

Backend-internal view model: no Zod mirror and NOT in the E5 contract surface (like
:class:`CbsPageSnapshot`). The dashboard parses it with a local schema, so the strict Pydantic⇄Zod
parity set stays the fixed nine.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from jaaffl.domain import DraftEventType, DraftState
from jaaffl.ingest.log import LoggedEvent


class BoardPick(BaseModel):
    """One drafted pick, enriched with the drafted player's display fields for the board."""

    overall: int = Field(ge=1)
    round: int = Field(ge=1)
    pick_in_round: int = Field(ge=1)
    team_id: str
    player_id: str | None = None
    name: str | None = None
    position: str | None = None
    nfl_team: str | None = None


class DraftBoardState(BaseModel):
    """The folded draft plus name-enriched picks — the dashboard board + pick-log feed."""

    league_id: str
    current_overall_pick: int = Field(ge=1)
    on_the_clock_team_id: str | None = None
    my_team_id: str | None = None
    complete: bool = False
    picks: list[BoardPick] = Field(default_factory=list)


def build_board_state(state: DraftState, events: Iterable[LoggedEvent]) -> DraftBoardState:
    """Join the folded ``state`` with drafted-player names from the raw ``pick_made`` events.

    Names / positions / teams come from the event payloads (present for every ``pick_made``),
    keyed by ``overall``. A pick with no name-bearing event keeps its id and shows no name — the
    board degrades a cell rather than raising.
    """
    name_index: dict[int, dict] = {}
    for ev in events:
        if ev.event_type == DraftEventType.PICK_MADE:
            overall = ev.data.get("overall")
            if overall is not None:
                name_index[int(overall)] = ev.data

    picks: list[BoardPick] = []
    for pick in state.picks:
        data = name_index.get(pick.overall) or {}
        picks.append(
            BoardPick(
                overall=pick.overall,
                round=pick.round,
                pick_in_round=pick.pick_in_round,
                team_id=pick.team_id,
                player_id=pick.player_id,
                name=data.get("player_name"),
                position=data.get("position"),
                nfl_team=data.get("player_team") or data.get("nfl_team"),
            )
        )
    return DraftBoardState(
        league_id=state.league_id,
        current_overall_pick=state.current_overall_pick,
        on_the_clock_team_id=state.on_the_clock_team_id,
        my_team_id=state.my_team_id,
        complete=state.complete,
        picks=picks,
    )
