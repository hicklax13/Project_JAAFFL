"""Core domain models.

Deliberately platform-agnostic where possible: CBS is the first (and, for the prototype,
only) platform, but league settings, players, and draft state are modeled generically so
the engine never hard-codes CBS assumptions.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Position(StrEnum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DST = "DST"
    # Common IDP / bench-eligible extras; extend as leagues require.
    DL = "DL"
    LB = "LB"
    DB = "DB"


class RosterSlot(BaseModel):
    """A startable (or bench/IR) slot with its position eligibility.

    Flex slots list multiple eligible positions (e.g. FLEX -> RB/WR/TE,
    SUPERFLEX -> QB/RB/WR/TE). Modeled generically to support CBS custom leagues.
    """

    slot: str = Field(description="Slot label, e.g. 'QB', 'FLEX', 'SUPERFLEX', 'BENCH', 'IR'.")
    eligible_positions: list[Position]
    count: int = Field(ge=0, description="Number of slots of this type.")
    starting: bool = Field(default=True, description="False for BENCH/IR slots.")


class ScoringRule(BaseModel):
    """Points awarded per unit of a stat, e.g. stat='reception', points_per_unit=1.0 (PPR)."""

    stat: str
    points_per_unit: float
    applies_to: list[Position] | None = Field(
        default=None, description="Restrict to positions, or None for all."
    )


class Team(BaseModel):
    team_id: str
    name: str | None = None
    manager: str | None = None
    draft_position: int | None = Field(default=None, description="1-indexed draft slot, if known.")


class Player(BaseModel):
    """A canonical player with cross-source identifiers."""

    player_id: str = Field(description="JAAFFL canonical id.")
    name: str
    position: Position
    nfl_team: str | None = None
    external_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Crosswalk to source ids, e.g. {'cbs': ..., 'gsis': ..., 'fantasypros': ...}.",
    )


class LeagueSettings(BaseModel):
    """Normalized league configuration parsed from CBS."""

    league_id: str
    platform: str = "cbs"
    name: str | None = None
    team_count: int = Field(ge=2)
    roster_slots: list[RosterSlot] = Field(default_factory=list)
    scoring: list[ScoringRule] = Field(default_factory=list)
    draft_type: str = Field(default="snake", description="'snake' | 'auction' | 'custom'.")
    # Never inferred from team_count alone — read from the live room when available.
    draft_order: list[str] | None = Field(
        default=None, description="Team ids in overall pick order, if explicitly known."
    )
    keeper: bool = False
    dynasty: bool = False
    raw: dict = Field(default_factory=dict, description="Original CBS payload snapshot.")


class DraftPick(BaseModel):
    overall: int = Field(ge=1)
    round: int = Field(ge=1)
    pick_in_round: int = Field(ge=1)
    team_id: str
    player_id: str | None = None


class DraftState(BaseModel):
    """A snapshot of the live draft at a point in time."""

    league_id: str
    current_overall_pick: int = Field(ge=1)
    on_the_clock_team_id: str | None = None
    my_team_id: str | None = None
    picks: list[DraftPick] = Field(default_factory=list)
    available_player_ids: list[str] | None = None


class DraftEventType(StrEnum):
    LEAGUE_SETTINGS = "league_settings"
    DRAFT_STATE = "draft_state"
    ON_THE_CLOCK = "on_the_clock"
    PICK_MADE = "pick_made"
    DRAFT_COMPLETE = "draft_complete"


class DraftEvent(BaseModel):
    """A normalized event emitted by the extension and ingested by the backend.

    ``data`` is validated by ``jaaffl.ingest`` into the concrete model for its type.
    """

    model_config = ConfigDict(use_enum_values=True)

    event_type: DraftEventType
    league_id: str
    data: dict = Field(default_factory=dict)


class RecommendedPick(BaseModel):
    player_id: str
    score: float = Field(description="Blended recommendation score (higher is better).")
    projected_points: float | None = None
    vorp: float | None = Field(default=None, description="Value over replacement, league-adjusted.")
    adp: float | None = None
    next_turn_availability: float | None = Field(
        default=None, ge=0.0, le=1.0, description="P(player still available at your next pick)."
    )
    tier: int | None = None
    rationale: str | None = None


class Recommendation(BaseModel):
    """The engine's answer for the current pick."""

    league_id: str
    as_of_overall_pick: int
    ranked: list[RecommendedPick] = Field(default_factory=list)
    reasoning: str | None = None

    @property
    def best(self) -> RecommendedPick | None:
        return self.ranked[0] if self.ranked else None
