"""Core domain models.

Deliberately platform-agnostic where possible: CBS is the first (and, for the prototype,
only) platform, but league settings, players, and draft state are modeled generically so
the engine never hard-codes CBS assumptions.
"""

from __future__ import annotations

from datetime import datetime
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


class ScoringBracket(BaseModel):
    """One inclusive-lower bracket of a tiered stat. Points awarded when lower <= stat < upper
    (upper=None => open-ended top bracket)."""

    lower: float = Field(description="Inclusive lower bound of the bracket, in stat units.")
    upper: float | None = Field(
        default=None, description="Exclusive upper bound; None = open-ended."
    )
    points: float = Field(description="Points awarded when the stat falls in this bracket.")


class ScoringTier(BaseModel):
    """A bracketed (non-linear) scoring stat, e.g. CBS DST points-allowed / yards-allowed."""

    stat: str = Field(description="e.g. 'dst_points_allowed', 'dst_yards_allowed'.")
    applies_to: list[Position] | None = Field(
        default=None, description="Restrict to positions, e.g. [DST]."
    )
    brackets: list[ScoringBracket] = Field(default_factory=list)


class ScoringBonus(BaseModel):
    """A threshold bonus, e.g. K field goal of 50+ yards => +N points."""

    stat: str = Field(description="e.g. 'field_goal_distance'.")
    threshold: float = Field(description="Award when stat >= threshold (stat units).")
    points: float = Field(description="Bonus points at/over the threshold.")
    applies_to: list[Position] | None = Field(default=None, description="e.g. [K].")


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
    # CBS "Standard" scores DST on BOTH points-allowed AND yards-allowed brackets, and
    # awards threshold bonuses (e.g. K 50+ yd FG) that flat linear rules cannot express.
    scoring_tiers: list[ScoringTier] = Field(default_factory=list)
    scoring_bonuses: list[ScoringBonus] = Field(default_factory=list)
    draft_type: str = Field(default="snake", description="'snake' | 'auction' | 'custom'.")
    # Never inferred from team_count alone — read from the live room when available.
    draft_order: list[str] | None = Field(
        default=None, description="Team ids in overall pick order, if explicitly known."
    )
    keeper: bool = False
    dynasty: bool = False
    raw: dict = Field(default_factory=dict, description="Original CBS payload snapshot.")


class CbsPageSnapshot(BaseModel):
    """A point-in-time capture of the user's CBS draft room, written by the extension->ingest
    path and READ (never fetched) by ``CbsOnPageProvider`` (plan §4.5). Keyed by CBS's own
    player ids; the provider resolves those to canonical via the ``Crosswalk``.

    Backend-internal (no Zod mirror; not in the E5 contract surface).

    TODO(capture): the exact CBS field shapes are UNVERIFIED — record-mode capture is an
    owner-manual session (see docs/owner-manual-todo.md). These generic maps are the reader's
    contract; the ingest parser populates them once a real capture lands. Do NOT claim real
    CBS-frame support until then.
    """

    league_id: str
    projections: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="cbs_id -> stat_line (stat name -> value)."
    )
    injuries: dict[str, str] = Field(default_factory=dict, description="cbs_id -> injury status.")
    rankings: dict[str, float] = Field(default_factory=dict, description="cbs_id -> rank/ADP.")
    league_settings: LeagueSettings | None = Field(
        default=None, description="Authoritative CBS scoring/roster, when captured."
    )
    captured_at: datetime = Field(description="When this snapshot was captured (staleness clock).")


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
    # §2.6 reducer: a draft_complete event marks the state terminal.
    complete: bool = False


class DraftEventType(StrEnum):
    LEAGUE_SETTINGS = "league_settings"
    DRAFT_STATE = "draft_state"
    ON_THE_CLOCK = "on_the_clock"
    PICK_MADE = "pick_made"
    DRAFT_COMPLETE = "draft_complete"


class DraftEventSource(StrEnum):
    """Which capture probe won (§5.4): MAIN-world network patch, React-fiber read,
    MutationObserver DOM fallback, or the manual-paste fallback."""

    WS = "ws"
    FRAMEWORK = "framework"
    DOM = "dom"
    PASTE = "paste"


class DraftEvent(BaseModel):
    """A normalized event emitted by the extension and ingested by the backend.

    ``data`` is validated by ``jaaffl.ingest`` into the concrete model for its type.
    """

    model_config = ConfigDict(use_enum_values=True)

    event_type: DraftEventType
    league_id: str
    # Cross-probe de-dup key (§5.8): overall pick (1..204 for 12x17); required-when-present
    # for pick_made, None for non-pick events.
    pick_number: int | None = Field(default=None, ge=1)
    source: DraftEventSource | None = Field(
        default=None, description="Winning probe: ws | framework | dom | paste."
    )
    data: dict = Field(default_factory=dict)


class ScoreComponents(BaseModel):
    """Auditable decomposition of Score(p) (design §10.3) — never a black box.

    Reconstruction (kappa/alpha and caps from EngineParams):
        score ~= mlv + kappa*max(0.0, vona) - risk_penalty + cliff_bonus + sum(modifiers.values())
    Convention: ``vona`` is RAW (pre-kappa, may be negative — the overlay shows urgency even
    when gated to 0); ``risk_penalty`` and ``cliff_bonus`` are the APPLIED signed contributions;
    ``sigma``/``floor``/``ceiling``/``replacement_baseline`` are descriptive, not summed.
    """

    mlv: float = Field(
        description="Flex-aware Marginal Lineup Value (Hungarian, 9 slots). Weight 1."
    )
    vona: float = Field(
        description="Raw Value Over Next Available (pre-kappa, pre-max-gate). May be < 0."
    )
    risk_penalty: float = Field(
        description="Applied signed risk term lambda(phase,slot)*sigma; Score SUBTRACTS it."
    )
    cliff_bonus: float = Field(description="Applied tier-cliff term alpha*CliffBonus_p (points).")
    sigma: float = Field(ge=0.0, description="Projection stdev sigma_p used for the risk term.")
    floor: float = Field(description="Downside (~p10) projection, league points.")
    ceiling: float = Field(description="Upside (~p90) projection, league points.")
    replacement_baseline: float = Field(
        description="Positional replacement baseline (league points) for MLV fill."
    )
    modifiers: dict[str, float] = Field(
        default_factory=dict,
        description="Named capped modifiers already in points, e.g. "
        "{'bye_stack': -1.5, 'handcuff_synergy': 2.0, 'sos': 0.5}; each within EngineParams caps.",
    )
    # §3.10 v1.1 additive/optional — round-aware explainability (default None; safe for the
    # Phase-0/Stage-3 scaffold and for pre-v1.1 payloads).
    reliability: float | None = Field(
        default=None, description="r_pos reliability shrinkage applied to mu (§3.10 R1)."
    )
    vona_horizon: int | None = Field(
        default=None, description="Upcoming picks VONA looked ahead, H (§3.10 R2)."
    )
    best_available_next: float | None = Field(
        default=None,
        description="E[best MLV still available at pos(p) by your H-th pick N_H*] (§3.10 R2).",
    )


class RecommendedPick(BaseModel):
    player_id: str
    score: float = Field(description="Blended recommendation score (higher is better).")
    # Display metadata so a pick is self-describing for the UI (name/pos/team/bye); the engine
    # fills these from the DraftContext player universe. All optional — additive, so pre-
    # enrichment payloads still validate and the UI degrades to the player_id.
    name: str | None = None
    position: Position | None = None
    nfl_team: str | None = None
    bye_week: int | None = None
    projected_points: float | None = None
    vorp: float | None = Field(default=None, description="Value over replacement, league-adjusted.")
    adp: float | None = None
    next_turn_availability: float | None = Field(
        default=None, ge=0.0, le=1.0, description="P(player still available at your next pick)."
    )
    tier: int | None = None
    rationale: str | None = None
    # Populated by engine.recommend for every v1 rec (Stage 5); optional so that
    # pre-engine (Stage 1-4) payloads still validate.
    components: ScoreComponents | None = None


class Recommendation(BaseModel):
    """The engine's answer for the current pick."""

    league_id: str
    as_of_overall_pick: int
    ranked: list[RecommendedPick] = Field(default_factory=list)
    reasoning: str | None = None

    @property
    def best(self) -> RecommendedPick | None:
        return self.ranked[0] if self.ranked else None
