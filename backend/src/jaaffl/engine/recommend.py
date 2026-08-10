"""Engine orchestrator (§3.7) + the risk term (§3.5): live DraftState → ranked Recommendation.

This *is* the stateless per-pick ``recompute()``: given ``(state, context, params)`` it masks picked
players, re-derives depletion-aware baselines, computes survival + VONA, scores the top candidates
into a fully-decomposed ``ScoreComponents``, and ranks them. It imports **no** concrete provider,
httpx, or nflreadpy and touches **no** network — all provider I/O happened in precompute (§4.7).

The canonical score (design §6.C.7), reconstructed exactly by ``ScoreComponents``:

    score = MLV + κ·max(0, VONA) − risk_penalty + cliff_bonus + Σ modifiers

where ``vona`` is stored RAW (pre-κ, may be < 0), and ``risk_penalty`` (λ·σ̂) and ``cliff_bonus``
(α·CliffBonus) are the APPLIED signed contributions.
"""

from __future__ import annotations

import time
from collections import Counter

from jaaffl.config import EngineParams
from jaaffl.domain import (
    DraftState,
    LeagueSettings,
    Position,
    Recommendation,
    RecommendedPick,
    ScoreComponents,
)
from jaaffl.engine.context import DraftContext
from jaaffl.engine.opponents import (
    board_adp_shift,
    expected_best_available,
    pick_probabilities,
    run_pressure_by_position,
)
from jaaffl.engine.optimize import lineup_value, marginal_lineup_value, value_over_replacement
from jaaffl.engine.risk import (
    SlotState,
    has_open_non_puntable_slot,
    is_punted,
    lambda_weight,
    open_startable_by_position,
    puntable_positions,
    seat_roster,
    slot_state_for,
)
from jaaffl.league.replacement import dynamic_replacement_values


def _positional_modifiers(
    candidate_id: str,
    my_roster: list[str],
    context: DraftContext,
    params: EngineParams,
) -> dict[str, float]:
    """UNIMPLEMENTED. §6.C.7's bounded tie-breakers (bye-stack −, handcuff-synergy +, SOS ±).

    This returns ``{}`` unconditionally and always has. Two earlier claims in this docstring were
    re-tested in Tier 6 and BOTH were wrong, so they are recorded here rather than repeated:

    * *"bye/handcuff/SOS data is not on the $0 tier yet."* **False for bye and handcuff.** nflverse
      ships schedules and depth charts free: measured 2026-07-27, ``load_schedules(2026)`` returns
      272 regular-season games and yields a clean bye for all 32 teams (now read for real — see
      ``league/schedule.py``); ``load_depth_charts(2026)`` returns 375k rows carrying ``gsis_id``.
    * *"v1 ships the capped mechanism with no active modifier."* **There is no mechanism.** No
      clamping code exists anywhere; the score assembly simply adds ``sum(mods.values())``, which is
      0.0 because the dict is empty. Nothing reads ``caps.modifiers`` at all.

    The real blocker is that **E2 cannot price any of these three**, so implementing one would ship
    an unvalidated coefficient into the live scorer. ``sample_season_outcomes`` draws ONE season
    total per player from ``N(mu, sigma)``, INDEPENDENTLY per player, and ``roster_season_values``
    optimises the lineup once over those totals. So the objective has **no week axis** — bye_stack
    and SOS have nothing to attach to — and **no cross-player correlation**, which is the entire
    value of a handcuff (it pays out exactly when the starter does not). Tier 4 learned this shape
    the expensive way: a term the objective cannot see gets "tuned" to noise.

    Implementing any of them therefore needs a weekly, correlated objective FIRST. Until then the
    honest state is: not implemented, not advertised (the caps are gone from
    ``config/engine.json``), and ``modifiers`` stays on ``ScoreComponents`` as an empty, truthful
    decomposition slot.
    """
    return {}


def _dominant_rationale(
    pick_pos: Position,
    components: ScoreComponents,
    params: EngineParams,
    situation_flag: str | None,
) -> str:
    """One line naming the dominant term behind the score (the anti-black-box guarantee, §6.5)."""
    kappa_vona = params.kappa * max(0.0, components.vona)
    terms = {
        "value (MLV)": components.mlv,
        "scarcity (VONA)": kappa_vona,
        "tier cliff": components.cliff_bonus,
        "risk tilt": -components.risk_penalty,
    }
    lead = max(terms, key=lambda k: abs(terms[k]))
    flag = f" · {situation_flag}" if situation_flag else ""
    return f"{pick_pos.value}: {lead} (MLV {components.mlv:.1f}, VONA {components.vona:.1f}){flag}"


def _mc_expected_best(
    state: DraftState,
    settings: LeagueSettings,
    context: DraftContext,
    params: EngineParams,
    available: list[str],
    by_position: dict[Position, list[str]],
    mlv: dict[str, float],
    baselines: dict[Position, float],
) -> dict[Position, float]:
    """Monte-Carlo ``E_π`` per position for the opt-in ``?mc=true`` path (§3.9), or ``{}`` to
    signal "fall back to analytic".

    Everything here is deliberately lazy and off the default path: ``simulate`` (and therefore
    numpy) is imported only when MC is actually requested, so the analytic hot path — the one
    ``test_engine_latency`` holds to p95 < 200 ms — pays nothing for this existing.

    Returns ``{}`` when the real draft order is unreadable. Without it there is no honest count of
    picks between now and my next turn, and fabricating a snake from team count is exactly what
    ``config/league.json`` (``infer_from_team_count: false``) forbids. Reporting a Monte-Carlo
    number computed against an invented board would be worse than the silent no-op this replaces.
    """
    from jaaffl.engine.opponents import next_overall_pick
    from jaaffl.engine.simulate import SimContext, mc_expected_best_available

    try:
        my_next = next_overall_pick(settings, state, horizon=max(1, params.vona_horizon_picks))
    except ValueError:
        return {}

    # Picks landing strictly between my current pick and my next turn — the same window the
    # analytic survival integrates over.
    picks_between = max(0, my_next - state.current_overall_pick - 1)
    if picks_between == 0:
        return {}

    sim_ctx = SimContext(
        value=context.mu,
        position=context.position,
        baselines=baselines,
        slots=context.starting_slots,
        roster_size=sum(slot.count for slot in settings.roster_slots),
        adp=context.adp_mean,
        adp_stdev=context.adp_sd,
    )
    return mc_expected_best_available(
        sim_ctx,
        available=available,
        candidates_by_position=by_position,
        mlv=mlv,
        picks_between=picks_between,
        n_sims=max(1, params.mc_rollouts),
        # Seeded off the pick so the same board always yields the same answer (no flicker between
        # refreshes) while different picks get independent rollouts.
        seed=state.current_overall_pick,
    )


def recommend(
    state: DraftState,
    context: DraftContext,
    params: EngineParams,
    *,
    use_mc_vona: bool = False,  # analytic VONA is the v1 default; MC is stretch (§3.9)
    limit: int | None = None,
) -> Recommendation:
    """Score every candidate into a decomposed, ranked Recommendation (stateless hot path)."""
    started = time.perf_counter()
    # The entered round-1 order is decided in person minutes before the draft, while DraftContext
    # is precomputed and cached per league beforehand — and `resolve_league_settings` returns
    # draft_order=None by construction, so nothing on the settings side ever carries it. The ROOM's
    # order therefore arrives on the state, and the state wins. Overlaid for THIS CALL ONLY: the
    # context is a cached object shared across every pick and every connected client.
    settings = context.settings
    if state.draft_order:
        settings = settings.model_copy(update={"draft_order": state.draft_order})
    picked = {pick.player_id for pick in state.picks if pick.player_id}
    available = [pid for pid in context.mu if pid not in picked]
    my_roster = [
        pick.player_id
        for pick in state.picks
        if pick.player_id and pick.team_id == state.my_team_id
    ]
    team_count = settings.team_count or 12
    round_no = (state.current_overall_pick - 1) // team_count + 1
    pick_in_round = (state.current_overall_pick - 1) % team_count + 1

    # 1) Depletion-aware baselines over what's still available (design §3.2 Dynamic VBD).
    drafted_at_pos: Counter[Position] = Counter(
        context.position[pid] for pid in picked if pid in context.position
    )
    baselines = dynamic_replacement_values(
        settings,
        context.mu,
        context.players,
        available,
        drafted_at_pos=drafted_at_pos,
        flex_split=context.flex_split,
    )

    # 2) Survival at N₁* (display) and N_H* (VONA horizon, R2), board-conditioned (R3). When the
    # snake order / my_team_id is unknown (e.g. before we know our slot), survival degrades to
    # "everyone available" so the engine still ranks on MLV rather than crashing.
    available_adp = {pid: context.adp_mean[pid] for pid in available if pid in context.adp_mean}
    try:
        run_pressure = run_pressure_by_position(state, settings, available_adp, context.position)
    except ValueError:
        run_pressure = {}
    shift = board_adp_shift(run_pressure, context.position, beta=params.board_survival_weight)
    horizon = max(1, int(params.vona_horizon_picks))

    # Whether survival could condition on MY slot at all, and if not, WHICH input was missing.
    # One string used to cover both, and the overlay rendered it as "no draft slot set" — which
    # told the owner to set JAAFFL_MY_TEAM_ID even when the missing input was the ORDER, which no
    # setting supplies (it is folded from the room's league_settings event, or pasted as an
    # ORDER: line). A degraded model still ranks (on MLV), but every VONA is 0.00 and that is
    # indistinguishable on the wire from a computed 0.00. See Recommendation.survival_basis.
    if not settings.draft_order:
        survival_basis = "degraded_no_order"
    elif state.my_team_id is None or state.my_team_id not in settings.draft_order:
        survival_basis = "degraded_no_slot"
    else:
        survival_basis = "my_slot"

    def _survival(h: int) -> dict[str, float]:
        nonlocal survival_basis
        try:
            taken = pick_probabilities(
                state, settings, available_adp, context.adp_sd, horizon=h, adp_shift=shift
            )
        except ValueError:
            taken = {}  # no draft_order / my_team_id (e.g. pre-draft) → treat everyone as available
            # Belt and braces: the branch above should already have classified this, but
            # _my_overall_picks is the authority on what it can actually compute.
            if survival_basis == "my_slot":
                survival_basis = "degraded_no_slot"
        return {pid: 1.0 - taken.get(pid, 0.0) for pid in available}

    survival_display = _survival(1)
    survival_vona = survival_display if horizon == 1 else _survival(horizon)

    # 3) Static-ish MLV for every available player (dynamic baselines); cache the base lineup once.
    # Picks left to me, including this one. A replacement phantom is only worth counting while a
    # pick remains to draft it — without this the engine priced an empty QB slot at its baseline
    # forever, scored a 13th tight end and the quarterback it desperately needed identically at
    # 0.00, and finished a 17-round draft unable to fill four of its nine starting slots (Tier 7).
    picks_remaining = max(0, sum(slot.count for slot in settings.roster_slots) - len(my_roster))
    base_value = lineup_value(
        my_roster,
        context.mu,
        context.position,
        baselines,
        context.starting_slots,
        picks_remaining=picks_remaining,
    )
    mlv = {
        pid: marginal_lineup_value(
            pid,
            my_roster,
            context.mu,
            context.position,
            baselines,
            context.starting_slots,
            base_value=base_value,
            picks_remaining=picks_remaining,
        )
        for pid in available
    }

    # 4) VONA baseline E_π per position (expected best surviving MLV at that position by N_H*).
    by_position: dict[Position, list[str]] = {}
    for pid in available:
        by_position.setdefault(context.position[pid], []).append(pid)

    expected_best: dict[Position, float] = {}
    vona_method = "analytic"
    if use_mc_vona:
        expected_best = _mc_expected_best(
            state, settings, context, params, available, by_position, mlv, baselines
        )
        if expected_best:
            vona_method = "monte_carlo"
    if vona_method == "analytic":
        for pos, pids in by_position.items():
            ranked_pos = sorted(pids, key=lambda p: mlv[p], reverse=True)
            expected_best[pos] = expected_best_available(
                ranked_pos, mlv, survival_vona, replacement=baselines.get(pos, 0.0)
            )

    # 5) Candidate pool: top-K available by MLV (bounded hot path), as a TOTAL order — ties broken
    # by the value MLV floors away, then by id, never by dict order on this ANALYTIC path (Tier 10;
    # the opt-in MC-VONA rollout in `simulate.mc_expected_best_available` still breaks ADP ties by
    # pool index, and is off by default). MLV is exactly 0.00
    # for every candidate who cannot improve the optimal nine, which is not merely the
    # below-replacement tail: with a strong lineup already seated it includes players far ABOVE
    # replacement. Their whole score collapses with it — `κ·max(0, VONA)` clamps because
    # `expected_best_available` is never negative, `α·cliff_bonus` is legitimately 0 below
    # replacement, and a SURPLUS position takes `lambda_slot_override`'s ceiling. Measured on the
    # real board at round 14 with that override zeroed: 180 of 180 candidates shared the score
    # 0.000000, this cap was choosing 180 of 425 players by `context.mu` insertion order, and the
    # #1 recommendation was 81.4 projected points worse than the best player it tied with.
    # `picks.sort` below is stable, so it inherits this order among equal scores — which is what
    # makes the ranking a decision rather than an accident of how precompute filled a dict.
    vor = {
        pid: value_over_replacement(pid, context.mu, context.position, baselines)
        for pid in available
    }
    candidates = sorted(available, key=lambda p: (-mlv[p], -vor[p], p))[: params.candidate_cap]

    # Slot-state accounting for my current roster (drives the λ override + punt guard). The
    # puntable positions come from the config (punt_guard.stream_round keys) — one source of truth,
    # so making, say, TE streamable is a config change, not a code change.
    puntable = puntable_positions(params)
    filled = seat_roster(my_roster, context.position, context.starting_slots)
    open_startable = open_startable_by_position(filled, context.starting_slots)
    has_open_non_puntable = has_open_non_puntable_slot(filled, context.starting_slots, puntable)

    picks: list[tuple[bool, RecommendedPick]] = []
    for pid in candidates:
        pos = context.position[pid]
        proj = context.projections[pid]
        mlv_p = mlv[pid]
        vona = mlv_p - expected_best.get(pos, 0.0)  # RAW (may be < 0)
        slot_state = slot_state_for(pos, open_startable)
        risk_penalty = lambda_weight(round_no, slot_state, params) * proj.sigma
        applied_cliff = params.alpha * context.cliff_bonus.get(pid, 0.0)
        mods = _positional_modifiers(pid, my_roster, context, params)
        score = (
            mlv_p
            + params.kappa * max(0.0, vona)
            - risk_penalty
            + applied_cliff
            + sum(mods.values())
        )
        components = ScoreComponents(
            mlv=mlv_p,
            vona=vona,
            risk_penalty=risk_penalty,
            cliff_bonus=applied_cliff,
            sigma=proj.sigma,
            floor=proj.floor,
            ceiling=proj.ceiling,
            replacement_baseline=baselines.get(pos, 0.0),
            modifiers=mods,
            reliability=proj.reliability,
            vona_horizon=horizon,
            best_available_next=expected_best.get(pos, 0.0),
        )
        # Punt guard (R1): demote K/DST out of #1 before their stream round unless the rest of the
        # startable roster is full — it re-ranks, never changes the score.
        punted = is_punted(pos, round_no, params, has_open_non_puntable=has_open_non_puntable)
        player = context.players.get(pid)
        picks.append(
            (
                punted,
                RecommendedPick(
                    player_id=pid,
                    score=score,
                    # Display identity from the precomputed player universe (§6.2) — makes the
                    # pick self-describing for the overlay/dashboard. ``bye_week`` stays None when
                    # the schedule feed did not resolve this player's team, so the overlay's
                    # `bye N` chip is absent rather than wrong.
                    name=player.name if player else None,
                    bye_week=context.bye_week.get(pid),
                    position=pos,
                    nfl_team=player.nfl_team if player else None,
                    projected_points=proj.mu,
                    vorp=mlv_p,
                    adp=context.adp_mean.get(pid),
                    next_turn_availability=survival_display.get(pid),
                    tier=context.tiers.get(pid),
                    rationale=_dominant_rationale(pos, components, params, proj.situation_flag),
                    # Provenance of mu (§5 live-data honesty). Sorted so the rendered chip is
                    # stable between recomputes rather than dict-insertion dependent.
                    projection_sources=sorted(proj.sources) if proj.sources else None,
                    components=components,
                ),
            )
        )

    picks.sort(key=lambda item: (item[0], -item[1].score))  # non-punted first, then score desc
    ranked = [pick for _, pick in picks]
    if limit is not None:
        ranked = ranked[:limit]

    normal_lambda = lambda_weight(round_no, SlotState.NORMAL, params)
    vona_note = (
        f"MC VONA, {params.mc_rollouts} rollouts"
        if vona_method == "monte_carlo"
        else "analytic VONA"
    )
    reasoning = (
        f"R{round_no}P{pick_in_round} · λ={normal_lambda:+.2f} · κ={params.kappa} · "
        f"α={params.alpha} · flex_split={context.flex_split[0]}RB/{context.flex_split[1]}WR "
        f"(EngineParams v{params.version}; {vona_note}, horizon {horizon})"
    )
    # Overlay foot (§6.3 anatomy #6): the roster the owner has actually filled. Published here
    # because the overlay only ever receives a Recommendation — inferring it client-side from
    # pick numbers would synthesize draft structure, which the league constitution forbids.
    roster_by_position: Counter[Position] = Counter(
        context.position[pid] for pid in my_roster if pid in context.position
    )
    roster_size = sum(slot.count for slot in settings.roster_slots)

    return Recommendation(
        league_id=state.league_id,
        as_of_overall_pick=state.current_overall_pick,
        ranked=ranked,
        reasoning=reasoning,
        roster_filled=len(my_roster),
        roster_size=roster_size or None,
        roster_by_position={pos.value: n for pos, n in roster_by_position.items()},
        vona_method=vona_method,
        survival_basis=survival_basis,
        # Measured LAST so it covers the whole recompute — this is the <200ms budget (§6.7)
        # made auditable on the surface rather than asserted only in a test.
        recompute_ms=(time.perf_counter() - started) * 1000.0,
    )
