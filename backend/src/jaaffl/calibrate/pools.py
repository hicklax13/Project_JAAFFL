"""The shared deterministic fixture pool for E2 (`--smoke`) and E6 (plan §9.2 / §9.3).

`scripts/tune_engine_params.py` and `scripts/run_tournament.py` each carried their own copy of this
context. They have one now, because the property that matters is easy to lose in a copy and
invisible when lost: **the pool has to be able to measure the terms being tuned.**

Measured on the pre-Tier-4 pools, turning kappa, alpha AND lambda off together left a bit-identical
roster in 96/96 (slot x seed x opponent-field) cells — `cliff_bonus` was empty so alpha multiplied
zero, `sigma` took two values so lambda was a per-position constant, there were no K/DST players for
`reliability_shrinkage` to shrink, and the value gradient swamped the rest. The Optuna study was
maximising a constant while reporting a tuned vector. `tests/test_calibrate_pools.py` guards each
term individually.

This pool is still a FIXTURE, not the board: a reduced 10-slot roster (vs the league's 17) keeps a
smoke run fast. It is faithful where faithfulness is load-bearing — the sigma anchors are the real
measured ones, and the clamp saturates at the top exactly as the live board does.
"""

from __future__ import annotations

from jaaffl.config import EngineParams
from jaaffl.domain import LeagueSettings, Position, RosterSlot
from jaaffl.engine.optimize import expand_starting_slots, roster_capacity
from jaaffl.engine.risk import median_sigma_by_position
from jaaffl.engine.simulate import SimContext

# Per-position player counts, tier size, and the value curve. Values decay GENTLY inside a tier and
# DROP between tiers, so (a) real cliffs exist for alpha to price and (b) within-tier MLV gaps stay
# small enough that kappa/lambda can actually re-rank — on a uniformly steep curve the MLV gradient
# swamps every strategic term, which is how the old pool went blind.
_TIER_SIZE = 5
_PLAN: dict[Position, tuple[int, float, float, float]] = {
    # position: (count, top value, within-tier decay, between-tier drop)
    Position.RB: (45, 260.0, 1.4, 14.0),  # steepest cliffs -> the scarce position
    Position.WR: (55, 250.0, 1.2, 7.0),
    Position.QB: (24, 230.0, 1.0, 9.0),
    Position.TE: (24, 200.0, 1.1, 11.0),
    Position.K: (15, 120.0, 0.6, 2.0),  # flat: streaming positions have no real cliff
    Position.DST: (15, 125.0, 0.7, 2.5),
}

# The sigma anchors are the MEASURED ones (SD of realized season points minus prior-season xEP under
# the owner-verified JAAFFL map, two year-pairs) — imported, not copied, so a re-measurement flows
# straight through. Tier 1 nearly DOUBLED the QB anchor (55 -> 106.3) while cutting TE's (40 ->
# 29.2); a fixture with flat sigma hides that shift entirely.
_VOL_RATIO_MIN = 0.6
_VOL_RATIO_MAX = 1.6

# The owner-adopted flex allocation from `config/engine.json` (8 RB / 4 WR), used only to place the
# replacement rank. Kept as the same literal the engine ships with so the fixture's baselines are
# the ones the live board would produce, not a fixture-specific guess.
_FLEX_SPLIT = (8, 4)


def _sigma_anchor() -> dict[Position, float]:
    from jaaffl.engine.precompute import _DEFAULT_SIGMA_FLOOR

    return dict(_DEFAULT_SIGMA_FLOOR)


def committed_engine_params() -> EngineParams:
    """The vector the ENGINE actually runs — ``config/engine.json``, as ``precompute`` loads it.

    E2 used bare ``EngineParams()`` as its baseline and E6 used it as the "ours" contender. Its
    ``lambda_schedule`` default is ``[]``, so ``_phase_lambda`` returned 0.0 in every round and both
    experiments were quietly measuring a **risk-free** agent. Calibration has to compare against the
    shipped vector or it is not calibrating the shipped engine.
    """
    from jaaffl.config import get_settings
    from jaaffl.engine.precompute import _load_engine_params

    return _load_engine_params(get_settings())


def _volatility_ratio(rank: int) -> float:
    """Per-player volatility multiplier over ``[0.6, 1.6]``, mirroring ``league/xep.py``'s clamp.

    **Decorrelated from rank on purpose.** On the real board the ratio comes from a player's own
    measured weekly residuals against his position's median — two adjacent-ranked RBs routinely
    differ a lot. The obvious way to write a fixture (sigma decreasing smoothly with rank) makes
    ``-lambda * sigma`` a monotone function of value, i.e. a rescaling of the value curve that can
    never re-rank anyone; the first cut of this pool did exactly that and still could not measure
    lambda. Roughly a quarter saturate at the clamp, matching the live board's 47-of-top-200.
    """
    unit = ((rank * 7919 + 13) % 101) / 100.0  # deterministic, reproducible, rank-decorrelated
    if unit > 0.76:
        return _VOL_RATIO_MAX
    return _VOL_RATIO_MIN + (_VOL_RATIO_MAX - _VOL_RATIO_MIN) * (unit / 0.76)


def demo_settings() -> LeagueSettings:
    """A REDUCED rehearsal of the league roster — WR2 (not 3) and Bench2 (not 8), so a smoke draft
    is 12x10 rather than 12x17. K and DST slots are present on purpose: without them
    `reliability_shrinkage` (which `run_study` tunes) cannot affect a single pick."""
    return LeagueSettings(
        league_id="demo",
        team_count=12,
        roster_slots=[
            RosterSlot(slot="QB", eligible_positions=[Position.QB], count=1, starting=True),
            RosterSlot(slot="RB", eligible_positions=[Position.RB], count=1, starting=True),
            RosterSlot(slot="WR", eligible_positions=[Position.WR], count=2, starting=True),
            RosterSlot(
                slot="WR/RB",
                eligible_positions=[Position.WR, Position.RB],
                count=1,
                starting=True,
            ),
            RosterSlot(slot="TE", eligible_positions=[Position.TE], count=1, starting=True),
            RosterSlot(slot="K", eligible_positions=[Position.K], count=1, starting=True),
            RosterSlot(slot="DST", eligible_positions=[Position.DST], count=1, starting=True),
            RosterSlot(
                slot="BENCH",
                eligible_positions=[Position.QB, Position.RB, Position.WR, Position.TE],
                count=2,
                starting=False,
            ),
        ],
    )


def _baselines(
    value: dict[str, float], position: dict[str, Position], settings: LeagueSettings
) -> dict[Position, float]:
    """Per-position replacement = the value of the LAST STARTABLE player at that position, the same
    definition `league/replacement.py` uses (dedicated demand + the WR/RB flex split).

    A single flat baseline for every position — which this pool used to carry — is not a shortcut,
    it is a distortion. It handed K an MLV of 80 (raw 120 vs a 40 baseline) when a real kicker sits
    a handful of points above replacement, and it inflated every skill MLV into the 100-220 band
    where `lambda*sigma` (at most ~30) can never re-rank anything. Getting replacement right is what
    puts MLV back on the same scale as the strategic terms.
    """
    demand: dict[Position, int] = {}
    for slot in settings.roster_slots:
        if slot.starting and len(slot.eligible_positions) == 1:
            pos = slot.eligible_positions[0]
            demand[pos] = demand.get(pos, 0) + slot.count * settings.team_count
    rb_flex, wr_flex = _FLEX_SPLIT
    demand[Position.RB] = demand.get(Position.RB, 0) + rb_flex
    demand[Position.WR] = demand.get(Position.WR, 0) + wr_flex

    out: dict[Position, float] = dict.fromkeys(Position, 0.0)
    for pos, rank in demand.items():
        ranked = sorted((value[pid] for pid in value if position[pid] is pos), reverse=True)
        if ranked:
            out[pos] = ranked[rank - 1] if rank <= len(ranked) else ranked[-1]
    return out


def demo_sim_context() -> SimContext:
    """The tiered fixture pool: per-player sigma, real cliffs, every rosterable position."""
    anchors = _sigma_anchor()
    value: dict[str, float] = {}
    position: dict[str, Position] = {}
    sigma: dict[str, float] = {}
    cliff_bonus: dict[str, float] = {}

    for pos, (count, top, decay, drop) in _PLAN.items():
        for rank in range(count):
            pid = f"{pos.value.lower()}{rank}"
            tier, within = divmod(rank, _TIER_SIZE)
            value[pid] = top - tier * drop - within * decay
            position[pid] = pos
            sigma[pid] = anchors[pos] * _volatility_ratio(rank)
        # CliffBonus_p = value(p) - value(best player in the next tier down), for the LAST player of
        # each tier only (design §6.C.6). Everyone else carries 0.0.
        for rank in range(_TIER_SIZE - 1, count - 1, _TIER_SIZE):
            cliff_bonus[f"{pos.value.lower()}{rank}"] = (
                value[f"{pos.value.lower()}{rank}"] - value[f"{pos.value.lower()}{rank + 1}"]
            )

    # ADP follows the global value order, and its spread WIDENS down the board the way a real
    # consensus does — a constant stdev would make every opponent equally predictable everywhere.
    by_value = sorted(value, key=lambda pid: value[pid], reverse=True)
    adp = {pid: float(i + 1) for i, pid in enumerate(by_value)}
    adp_stdev = {pid: 4.0 + 0.06 * i for i, pid in enumerate(by_value)}

    settings = demo_settings()
    return SimContext(
        value=value,
        position=position,
        baselines=_baselines(value, position, settings),
        slots=expand_starting_slots(settings),
        roster_size=sum(slot.count for slot in settings.roster_slots),
        adp=adp,
        adp_stdev=adp_stdev,
        sigma=sigma,
        cliff_bonus=cliff_bonus,
        roster_capacity=roster_capacity(settings),
        sigma_median=median_sigma_by_position(sigma, position),
    )


def real_sim_context(cap: int = 300, *, per_position: int = 20) -> SimContext:
    """A precompute-backed :class:`SimContext` — real projections + FFC ADP. **NETWORK + slow.**

    Lives here rather than in a script because **three** calibration CLIs need it — E2
    (``tune_engine_params.py``), E6 (``run_tournament.py``) and the Tier 8 risk-term arms
    (``measure_risk_term.py``) — and the one thing this project has learned five times over is that
    a rule implemented twice diverges silently. Two private copies already existed, and the second
    lived in **the one CLI that can write** ``config/engine.json``: had its cap or per-position
    keep-back drifted, E2 would have tuned on one real pool while E6 validated on another, and no
    test compares them. Every heavy import is function-local, so importing this module stays free —
    pinned by ``tests/test_calibrate_pools.py``, which asserts in a clean interpreter that importing
    this does not pull ``nflreadpy``.

    Capped by :func:`~jaaffl.calibrate.tune.cap_sim_pool`, which keeps the top ``per_position`` of
    each position as well as the top ``cap`` by value — a plain value cap drops K and DST.
    """
    import sys

    from jaaffl.calibrate.tune import cap_sim_pool, sim_context_from_draft_context
    from jaaffl.config import get_settings
    from jaaffl.data import Crosswalk, Warehouse
    from jaaffl.engine.precompute import build_registry_context_source
    from jaaffl.providers.nflverse import NflreadpyProvider

    settings = get_settings()
    if not settings.jaaffl_season:
        raise SystemExit("[pools] set jaaffl_season to build the real pool")
    warehouse = Warehouse(settings.jaaffl_data_dir)
    crosswalk = Crosswalk(warehouse.app_sqlite)
    print("[pools] building the real DraftContext ...", file=sys.stderr)
    NflreadpyProvider(crosswalk=crosswalk).seed_crosswalk()
    source = build_registry_context_source(
        settings, warehouse=warehouse, crosswalk=crosswalk, season=settings.jaaffl_season
    )
    dc = source(settings.jaaffl_league_id)
    if dc is None:
        raise SystemExit("[pools] precompute returned no context")
    ctx = sim_context_from_draft_context(dc)
    print(f"[pools] real pool: {len(ctx.value)} players -> top {cap}", file=sys.stderr)
    return cap_sim_pool(ctx, cap, per_position=per_position)
