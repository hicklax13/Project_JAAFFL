"""Precompute assembler (§3.7): providers → an immutable DraftContext, joined by canonical id.

All provider I/O lives here; the assembled context is what the provider-free hot path reads.
"""

from __future__ import annotations

import pytest

from jaaffl.domain import Player, Position
from jaaffl.engine.context import build_draft_context
from jaaffl.league.defaults import cbs_standard_scoring
from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider
from tests.engine_fixtures import engine_params, jaaffl_settings, teams


class _Fake(FantasyDataProvider):
    def __init__(self, name, caps, *, adp=None, rankings=None, projections=None):
        self._name, self._caps = name, frozenset(caps)
        self._adp, self._rankings, self._projections = adp or {}, rankings or {}, projections or {}

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def adp(self, season):
        return self._adp

    def rankings(self, season, week=None):
        return self._rankings

    def projections(self, season, week=None):
        return self._projections


def _settings():
    rules, tiers, bonuses = cbs_standard_scoring()
    return jaaffl_settings(draft_order=teams(12)).model_copy(
        update={"scoring": rules, "scoring_tiers": tiers, "scoring_bonuses": bonuses}
    )


def _providers():
    return [
        _Fake("nflverse", {Capability.RANKINGS}, rankings={"rb0": 1.0, "wr0": 2.0, "te0": 50.0}),
        _Fake(
            "ffc",
            {Capability.ADP},
            adp={"rb0": AdpRecord(adp=1.0, stdev=3.0), "wr0": AdpRecord(adp=2.0, stdev=None)},
        ),
        _Fake(
            "cbs_onpage",
            {Capability.PROJECTIONS},
            projections={
                "rb0": {"rushing_yards": 1500, "rushing_td": 12},
                "wr0": {"receiving_yards": 1200, "receiving_td": 9},
                "te0": {"receiving_yards": 700, "receiving_td": 5},
            },
        ),
    ]


def _players():
    return {
        "rb0": Player(player_id="rb0", name="rb0", position=Position.RB),
        "wr0": Player(player_id="wr0", name="wr0", position=Position.WR),
        "te0": Player(player_id="te0", name="te0", position=Position.TE),
    }


def _build():
    return build_draft_context(
        _settings(),
        _providers(),
        engine_params(),
        2026,
        players=_players(),
        sigma_floor={p: 20.0 for p in Position},
        ecr_to_points=lambda pos, e: 300.0 - e,
    )


def test_context_joins_adp_projections_and_ecr_by_canonical_id() -> None:
    ctx = _build()
    assert ctx.adp_mean["rb0"] == pytest.approx(1.0)
    assert ctx.adp_sd["rb0"] == pytest.approx(3.0)  # FFC stdev
    assert ctx.adp_sd["wr0"] == pytest.approx(12.0)  # None stdev → wide default
    # CBS points: 1500·0.1 + 12·6 = 222; blended with the ECR source (300 − 1 = 299).
    assert ctx.projections["rb0"].sources["cbs"] == pytest.approx(222.0)
    assert ctx.mu["rb0"] == pytest.approx((222.0 + 299.0) / 2)


def test_context_fills_deep_round_adp_from_ecr() -> None:
    """te0 has ECR but no FFC ADP (past the FFC thinning cliff) → ADP is backed by ECR."""
    ctx = _build()
    assert "te0" not in {"rb0", "wr0"}  # sanity: te0 had no FFC row
    assert ctx.adp_mean["te0"] == pytest.approx(50.0)  # filled from ECR rank
    assert ctx.adp_sd["te0"] == pytest.approx(12.0)  # wide default for the fill


def test_context_precomputes_slots_tiers_and_baselines() -> None:
    ctx = _build()
    assert len(ctx.starting_slots) == 9
    assert set(ctx.tiers) == {"rb0", "wr0", "te0"}
    assert set(ctx.cliff_bonus) == {"rb0", "wr0", "te0"}
    assert ctx.flex_split == (8, 4)
    assert Position.RB in ctx.baselines and Position.WR in ctx.baselines
