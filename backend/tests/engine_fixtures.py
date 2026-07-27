"""Shared factory helpers for the Stage-5 engine tests.

Plain callables (matching the repo's ``sample_settings()`` helper style, not pytest fixtures) so
they compose freely across the many engine test modules. ``tests`` is an importable package
(``tests/__init__.py`` exists), so ``from tests.engine_fixtures import ...`` resolves in pytest's
prepend import mode.

The league here is THE immutable JAAFFL constitution (config/league.json): Snake · 12 teams ·
Standard (non-PPR) · QB1/RB1/WR3/(WR-RB flex)1/TE1/K1/DST1/Bench8. The flex is WR-or-RB only.
"""

from __future__ import annotations

from typing import Any

from jaaffl.config import EngineParams
from jaaffl.domain import DraftPick, DraftState, LeagueSettings, Player, Position, RosterSlot
from jaaffl.engine.context import DraftContext
from jaaffl.engine.optimize import expand_starting_slots, marginal_lineup_value
from jaaffl.engine.projections import Z_SCORE, PlayerProjection
from jaaffl.engine.tiers import assign_tiers, cliff_bonuses
from jaaffl.league.replacement import replacement_values

# The λ schedule from config/engine.json (EngineParams defaults it to [] since it is calibrated).
_LAMBDA_SCHEDULE = [
    {"rounds": [1, 2], "lambda": 0.3},
    {"rounds": [3, 6], "lambda": 0.2},
    {"rounds": [7, 9], "lambda": 0.0},
    {"rounds": [10, 13], "lambda": -0.3},
    {"rounds": [14, 17], "lambda": -0.4},
]


def engine_params(**overrides: Any) -> EngineParams:
    """EngineParams mirroring config/engine.json (all other fields use the config.py defaults,
    which equal the file). Pass overrides to probe specific knobs."""
    base: dict[str, Any] = {"lambda_schedule": _LAMBDA_SCHEDULE}
    base.update(overrides)
    return EngineParams(**base)


# Canonical ids are ``gsis:<gsis_id>`` (data/crosswalk.py) — mirror that scheme in fixtures.
FLEX_ELIGIBLE = [Position.WR, Position.RB]  # WR/RB only — NO TE/QB/K/DST (league rule).


def jaaffl_settings(
    league_id: str = "cbs-test", *, draft_order: list[str] | None = None
) -> LeagueSettings:
    """The immutable JAAFFL roster as a ``LeagueSettings`` (scoring left to callers/defaults).

    ``draft_order`` is the round-1 team order actually entered into CBS (never inferred from team
    count); pass it when the survival/next-pick math needs the real snake schedule.
    """
    return LeagueSettings(
        league_id=league_id,
        team_count=12,
        draft_order=draft_order,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=3),
            RosterSlot(slot="WR/RB", eligible_positions=FLEX_ELIGIBLE, count=1),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1),
            RosterSlot(slot="K", eligible_positions=[Position.K], count=1),
            RosterSlot(slot="DST", eligible_positions=[Position.DST], count=1),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=8,
                starting=False,
            ),
        ],
    )


def player(pid: str, position: Position, name: str | None = None, nfl_team: str = "FA") -> Player:
    return Player(player_id=pid, name=name or pid, position=position, nfl_team=nfl_team)


def teams(n: int = 12) -> list[str]:
    return [f"t{i}" for i in range(n)]


def draft_state(
    current_overall_pick: int,
    *,
    league_id: str = "cbs-test",
    my_team_id: str = "t0",
    picks: list[DraftPick] | None = None,
) -> DraftState:
    return DraftState(
        league_id=league_id,
        current_overall_pick=current_overall_pick,
        my_team_id=my_team_id,
        picks=picks or [],
    )


def make_context(
    specs: list[dict[str, Any]],
    *,
    params: EngineParams | None = None,
    settings: LeagueSettings | None = None,
    bye_week: dict[str, int] | None = None,
) -> DraftContext:
    """Build a DraftContext directly from ``{pid, pos, mu, sigma?, adp?, sd?, ecr?, sources?}``
    specs — no providers/network — so the orchestrator can be exercised in isolation (uses the real
    baseline/tier/cliff/MLV code paths)."""
    params = params or engine_params()
    settings = settings or jaaffl_settings(draft_order=teams(12))

    players: dict[str, Player] = {}
    mu: dict[str, float] = {}
    position: dict[str, Position] = {}
    projections: dict[str, PlayerProjection] = {}
    adp_mean: dict[str, float] = {}
    adp_sd: dict[str, float] = {}
    ecr: dict[str, float] = {}
    for spec in specs:
        pid, pos, m = spec["pid"], spec["pos"], spec["mu"]
        sigma = spec.get("sigma", 20.0)
        players[pid] = Player(player_id=pid, name=pid, position=pos)
        mu[pid], position[pid] = m, pos
        projections[pid] = PlayerProjection(
            player_id=pid,
            position=pos,
            mu=m,
            sigma=sigma,
            floor=m - Z_SCORE * sigma,
            ceiling=m + Z_SCORE * sigma,
            reliability=1.0,
            # Which $0 sources actually backed this mu ({"xep","ecr"} vs a bare {"ecr"} fallback).
            sources=dict(spec.get("sources", {})),
        )
        if spec.get("adp") is not None:
            adp_mean[pid] = spec["adp"]
            adp_sd[pid] = spec.get("sd", 8.0)
        if spec.get("ecr") is not None:
            ecr[pid] = spec["ecr"]

    flex = (int(params.flex_split["RB"]), int(params.flex_split["WR"]))
    baselines = replacement_values(settings, mu, players, flex_split=flex)
    slots = expand_starting_slots(settings)
    static_mlv = {pid: marginal_lineup_value(pid, [], mu, position, baselines, slots) for pid in mu}
    tiers = assign_tiers(ecr, position) if ecr else dict.fromkeys(mu, 1)
    cliff = cliff_bonuses(tiers, static_mlv, position)
    return DraftContext(
        settings=settings,
        params=params,
        projections=projections,
        mu=mu,
        position=position,
        baselines=baselines,
        flex_split=flex,
        tiers=tiers,
        cliff_bonus=cliff,
        adp_mean=adp_mean,
        adp_sd=adp_sd,
        ecr=ecr,
        starting_slots=slots,
        players=players,
        bye_week=dict(bye_week or {}),
    )
