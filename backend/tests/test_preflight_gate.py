"""TIER 12 — preflight now answers the question that decided this tier.

``scripts/preflight.py`` checked that every startable position was fillable and that the
tier-cliff term was alive. It never asked whether the engine could compute a survival model AT
ALL — which is why "survival_basis is degraded on 100% of live recommendations, and no setting
fixes it" survived eleven tiers behind a completely healthy-looking response.

The probe order is a PROBE, labelled as one everywhere it appears. ``config/league.json`` forbids
inferring the real order from team count, and preflight runs hours before that order exists; its
only job is to prove the WIRING can produce a survival model.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from jaaffl.domain import Position
from tests.engine_fixtures import engine_params, jaaffl_settings, make_context

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    path = REPO_ROOT / "scripts" / "preflight.py"
    spec = importlib.util.spec_from_file_location("preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preflight = _load_script()
survival_probe = preflight.survival_probe


def _ctx():
    """A context whose settings carry NO draft order — exactly what the live wiring produces
    (``league/constitution.py``: "read from the live CBS room, never inferred here")."""
    specs = [
        {
            "pid": f"rb{i}",
            "pos": Position.RB,
            "mu": 300.0 - 5 * i,
            "adp": float(i + 1),
            "sd": 6.0,
            "ecr": float(i + 1),
        }
        for i in range(24)
    ]
    return make_context(specs, params=engine_params(), settings=jaaffl_settings(draft_order=None))


def test_the_probe_reports_a_live_survival_model() -> None:
    basis, positive = survival_probe(_ctx(), my_team_id="7")
    assert basis == "my_slot"
    assert positive > 0


def test_the_probe_fails_when_the_slot_is_unset() -> None:
    basis, positive = survival_probe(_ctx(), my_team_id=None)
    assert basis != "my_slot"
    assert positive == 0


def test_the_probe_fails_when_the_slot_is_not_a_team_in_the_room() -> None:
    """JAAFFL_MY_TEAM_ID is typed by hand. '99' in a 12-team room must be caught the morning of
    the draft, not discovered from a dead VONA while the clock runs."""
    basis, positive = survival_probe(_ctx(), my_team_id="99")
    assert basis == "degraded_no_slot"
    assert positive == 0


def test_the_probe_never_leaks_its_order_into_the_context() -> None:
    """The probe order is a fiction for one call. If it stuck to the cached context, preflight
    would leave the engine believing a snake order the room never entered."""
    context = _ctx()
    survival_probe(context, my_team_id="7")
    assert context.settings.draft_order is None


class TestTheGateDecisionItself:
    """The probe was covered and the DECISION was not — the same shape of blind spot this tier
    exists to close. Mutating `if basis != "my_slot" or positive == 0:` to `if False:` left all
    four probe tests green while the real script wrongly exited 0 on an empty slot."""

    def test_a_live_model_with_a_priced_term_passes(self) -> None:
        assert preflight.survival_gate_failed("my_slot", 12) is False

    def test_a_degraded_basis_stops_the_draft(self) -> None:
        assert preflight.survival_gate_failed("degraded_no_slot", 0) is True
        assert preflight.survival_gate_failed("degraded_no_order", 0) is True

    def test_a_reachable_model_that_prices_NOTHING_also_stops_the_draft(self) -> None:
        """basis alone is not enough: 'my_slot' with zero positive VONA is a survival model that
        exists and moves no pick — exactly the healthy-looking dead term this tier found."""
        assert preflight.survival_gate_failed("my_slot", 0) is True
