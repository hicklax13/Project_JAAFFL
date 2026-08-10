"""TIER 12 — the room's entered order reaches the engine, or the survival model is dead.

Measured 2026-08-10 on the real board (581 players): with ``settings.draft_order`` None, ZERO of
50 ranked candidates carry a positive VONA in ANY of the 17 rounds, so ``kappa * max(0, VONA)`` —
kappa 0.65 in ``config/engine.json`` — contributes exactly nothing to every live pick. Supplying
the order moves the top recommendation in 3 of 17 rounds on an identical board, and the
per-round positive-VONA count runs 0-13 (round 13 measures 0; the range is not 1-13).

Why no test saw it: ``engine_fixtures.make_context()`` defaults to
``jaaffl_settings(draft_order=teams(12))``, so every engine test in the suite — including Tier 3's
own ``test_my_team_slot.py``, via ``test_api._primed_engine()`` — hands the engine an order the
production wiring drops. These tests take their settings from
``league.constitution.resolve_league_settings``, the function the live service actually calls.
"""

from __future__ import annotations

from jaaffl.domain import DraftPick, DraftState, LeagueSettings, Position
from jaaffl.engine.recommend import recommend
from jaaffl.league.constitution import resolve_league_settings
from tests.engine_fixtures import engine_params, make_context

ORDER = [str(i) for i in range(1, 13)]


def _live_settings() -> LeagueSettings:
    """EXACTLY what the live service gives the engine: ``engine/precompute.py`` calls this, with
    no snapshot on a fresh room. Its ``draft_order`` is None by construction
    (``league/constitution.py`` — "read from the live CBS room, never inferred here")."""
    return resolve_league_settings("cbs-live")


def _board() -> list[dict]:
    return [
        {
            "pid": f"rb{i}",
            "pos": Position.RB,
            "mu": 300.0 - 5 * i,
            "adp": float(i + 1),
            "sd": 6.0,
            "ecr": float(i + 1),
        }
        for i in range(24)
    ] + [
        {
            "pid": f"wr{i}",
            "pos": Position.WR,
            "mu": 280.0 - 4 * i,
            "adp": float(25 + i),
            "sd": 6.0,
            "ecr": float(25 + i),
        }
        for i in range(24)
    ]


def _state(**over) -> DraftState:
    base: dict = {
        "league_id": "cbs-live",
        "current_overall_pick": 13,
        "my_team_id": "7",
        "picks": [
            DraftPick(
                overall=o, round=1, pick_in_round=o, team_id=ORDER[o - 1], player_id=f"rb{o - 1}"
            )
            for o in range(1, 13)
        ],
    }
    base.update(over)
    return DraftState(**base)


def _ctx(settings: LeagueSettings | None = None):
    return make_context(_board(), params=engine_params(), settings=settings or _live_settings())


class TestTheLiveWiringCanReachMySlot:
    def test_the_constitution_alone_cannot_produce_a_survival_model(self) -> None:
        """Pins the production fact this tier routes around, so a future change to
        constitution.py cannot make the tests below vacuous without failing here first."""
        assert _live_settings().draft_order is None

    def test_the_state_order_gives_the_engine_my_slot(self) -> None:
        ctx = _ctx()
        assert recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50).survival_basis == (
            "my_slot"
        )

    def test_without_it_the_engine_says_the_ORDER_is_what_is_missing(self) -> None:
        """One string used to cover two different owner actions. The overlay told the owner to
        set a draft slot when the missing input can be the order — which no setting supplies."""
        ctx = _ctx()
        assert recommend(_state(), ctx, ctx.params, limit=50).survival_basis == "degraded_no_order"

    def test_a_missing_slot_is_still_reported_as_a_missing_slot(self) -> None:
        ctx = _ctx()
        rec = recommend(_state(draft_order=ORDER, my_team_id=None), ctx, ctx.params, limit=50)
        assert rec.survival_basis == "degraded_no_slot"

    def test_a_slot_that_is_not_a_team_in_the_room_is_a_missing_slot(self) -> None:
        """JAAFFL_MY_TEAM_ID is typed by hand. A '13' in a 12-team room must degrade loudly, not
        raise and not silently pick a seat."""
        ctx = _ctx()
        rec = recommend(_state(draft_order=ORDER, my_team_id="13"), ctx, ctx.params, limit=50)
        assert rec.survival_basis == "degraded_no_slot"


class TestTheTermItActuallyTurnsOn:
    """survival_basis is a label; VONA is the thing. Tie them together so they cannot drift."""

    @staticmethod
    def _positive_vona(rec) -> int:
        return sum(1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0)

    def test_a_degraded_model_prices_scarcity_at_zero_for_every_candidate(self) -> None:
        ctx = _ctx()
        assert self._positive_vona(recommend(_state(), ctx, ctx.params, limit=50)) == 0

    def test_the_rooms_order_makes_the_scarcity_term_live(self) -> None:
        ctx = _ctx()
        rec = recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50)
        assert self._positive_vona(rec) > 0

    def test_the_context_settings_are_not_mutated_by_the_call(self) -> None:
        """DraftContext is cached per league and shared across every pick and every connected
        client. The override must live for one call only."""
        ctx = _ctx()
        recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=5)
        assert ctx.settings.draft_order is None


class TestAContextThatAlreadyKnowsTheOrderStillWorks:
    """A captured-settings future, and every existing test, passes the order on the settings."""

    def test_context_settings_are_used_when_the_state_has_none(self) -> None:
        ctx = _ctx(_live_settings().model_copy(update={"draft_order": ORDER}))
        assert recommend(_state(), ctx, ctx.params, limit=5).survival_basis == "my_slot"

    def test_the_state_wins_when_both_are_present(self) -> None:
        """The room is the authority; a stale precomputed order must not override it.

        Asserted on the SURVIVAL NUMBERS, not the ranking. Slot "7" of "1..12" and slot "7" of
        "12..1" are one pick apart (17 vs 18), and measured on this 36-player board that moves
        every next-turn availability (0.8783 vs 0.8413 at the top) without reordering anything.
        Asserting on the ranking would have made this test pass or fail on how steep the value
        curve happens to be — which is exactly the vacuous-fixture failure this tier is about.
        """
        stale = [str(i) for i in range(12, 0, -1)]
        ctx = _ctx(_live_settings().model_copy(update={"draft_order": stale}))
        rec_state = recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=50)
        rec_ctx = recommend(_state(), ctx, ctx.params, limit=50)
        assert rec_state.survival_basis == rec_ctx.survival_basis == "my_slot"
        assert [p.next_turn_availability for p in rec_state.ranked] != [
            p.next_turn_availability for p in rec_ctx.ranked
        ]

    def test_the_state_order_decides_WHETHER_a_slot_exists_at_all(self) -> None:
        """The sharpest precedence test available: a context order that does not contain my team
        can only ever produce 'degraded_no_slot'. If the state's order is honoured the answer is
        'my_slot' — a binary signal that no amount of numerical similarity can wash out."""
        foreign = [f"other{i}" for i in range(12)]
        ctx = _ctx(_live_settings().model_copy(update={"draft_order": foreign}))
        assert recommend(_state(), ctx, ctx.params, limit=5).survival_basis == "degraded_no_slot"
        assert (
            recommend(_state(draft_order=ORDER), ctx, ctx.params, limit=5).survival_basis
            == "my_slot"
        )
