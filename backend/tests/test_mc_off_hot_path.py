"""Monte-Carlo VONA must never reach the ``/recs/ws`` push path (§3.9 budget guardrail).

MC-VONA is opt-in and slow ON PURPOSE. Measured on the pick-1 worst case: analytic p95 **9 ms**
vs MC p95 **1.14 s** at the shipped ``mc_rollouts = 2000``, against the plan's <2 s MC budget.
The overlay is pushed a fresh recommendation after EVERY pick, so if MC ever leaked onto that
path the draft-night surface would inherit a ~1.1 s recompute — 125x the analytic cost, with no
one asking for it.

This asserts the invariant STRUCTURALLY rather than by timing. A wall-clock gate at 2000
rollouts has ~43% headroom locally, which a slower CI runner would eat, so it would either flake
or have to be loosened until it stopped meaning anything. What actually protects the budget is
that the push path cannot request MC at all — and that is checkable exactly, on every runner.
See docs/owner-manual-todo.md for why the 2000-rollout wall-clock number stays a local
measurement.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from jaaffl.engine.recommend import recommend
from jaaffl.engine.service import RecommendationEngine

_APP_PY = Path(__file__).resolve().parents[1] / "src" / "jaaffl" / "api" / "app.py"


def _publish_recommendation_source() -> str:
    """The body of api/app.py::publish_recommendation — the /recs/ws push path (§8.4 step 4)."""
    tree = ast.parse(_APP_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "publish_recommendation":
            return ast.unparse(node)
    raise AssertionError("publish_recommendation not found in api/app.py")


class TestTheAnalyticPathIsTheDefault:
    def test_recommend_defaults_to_analytic_vona(self) -> None:
        default = inspect.signature(recommend).parameters["use_mc_vona"].default
        assert default is False

    def test_the_engine_service_defaults_to_analytic_too(self) -> None:
        # A default that flips here would reach the push path without app.py changing a line.
        assert (
            inspect.signature(RecommendationEngine.recommend).parameters["use_mc"].default is False
        )


class TestThePushPathCannotAskForMonteCarlo:
    def test_it_never_passes_use_mc(self) -> None:
        source = _publish_recommendation_source()
        assert "use_mc" not in source, (
            "the /recs/ws push path must not request Monte-Carlo VONA: it runs after EVERY pick, "
            "and MC costs ~1.14s vs the analytic path's 9ms"
        )

    def test_it_calls_the_engine_with_state_only(self) -> None:
        # Guards the shape, not just the literal: a **kwargs splat or a params dict could carry
        # use_mc in without the substring above ever appearing.
        tree = ast.parse(_publish_recommendation_source())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "recommend"
        ]
        assert calls, "expected publish_recommendation to call .recommend(...)"
        for call in calls:
            assert not any(kw.arg is None for kw in call.keywords), (
                "a **kwargs splat could smuggle use_mc onto the push path"
            )
            assert {kw.arg for kw in call.keywords} <= {"limit"}, (
                f"unexpected keyword on the push path: {[kw.arg for kw in call.keywords]}"
            )
