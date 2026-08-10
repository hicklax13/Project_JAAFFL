"""E7 perf gate + the provider-free hot-path guarantee (§3.8, §4.7).

The per-pick ``recompute()`` (== ``engine.recommend``) must (a) import no concrete provider, httpx,
or nflreadpy — all provider I/O is precompute — and (b) meet the latency budget (< 2 s/pick,
analytic < 200 ms) at the pick-1 worst case (~300 available players).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from jaaffl.domain import Position
from jaaffl.engine.recommend import recommend
from tests.engine_fixtures import draft_state, make_context

_ENGINE_DIR = Path(__file__).resolve().parents[1] / "src" / "jaaffl" / "engine"
_LEAGUE_DIR = Path(__file__).resolve().parents[1] / "src" / "jaaffl" / "league"
# The engine may import ONLY jaaffl.providers.base + registry.providers_supporting (§4.7).
_FORBIDDEN_MODULES = {
    "jaaffl.providers.nflverse",
    "jaaffl.providers.ffc",
    "jaaffl.providers.cbs_onpage",
    "jaaffl.providers.fantasypros",
    "jaaffl.providers.sportradar",
    "jaaffl.providers.sportsdataio",
}
_FORBIDDEN_PREFIXES = ("httpx", "nflreadpy")


def _imported_modules(path: Path) -> set[str]:
    """Every module name reached by an ``import`` / ``from ... import`` in this file (AST-accurate
    — docstring/comment mentions do not count)."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _big_context():
    plan = [
        (Position.RB, 55, 300.0, 4.0, 30.0),
        (Position.WR, 80, 280.0, 3.0, 32.0),
        (Position.QB, 28, 340.0, 2.0, 25.0),
        (Position.TE, 28, 200.0, 4.0, 22.0),
        (Position.K, 24, 150.0, 2.0, 10.0),
        (Position.DST, 24, 160.0, 2.0, 12.0),
    ]
    specs, overall = [], 1
    for pos, n, top, step, sigma in plan:
        for i in range(n):
            specs.append(
                {
                    "pid": f"{pos.value.lower()}{i}",
                    "pos": pos,
                    "mu": top - step * i,
                    "sigma": sigma,
                    "adp": float(overall),
                    "sd": 8.0,
                    "ecr": float(overall),
                }
            )
            overall += 1
    return make_context(specs)


@pytest.mark.parametrize("module_dir", [_ENGINE_DIR, _LEAGUE_DIR])
def test_engine_source_never_imports_a_concrete_provider_or_network(module_dir: Path) -> None:
    """grep-clean: the hot-path packages carry no concrete-provider / httpx / nflreadpy import."""
    for path in module_dir.glob("*.py"):
        for module in _imported_modules(path):
            assert module not in _FORBIDDEN_MODULES, f"{path.name} imports {module}"
            assert not module.startswith(_FORBIDDEN_PREFIXES), f"{path.name} imports {module}"


def test_recompute_meets_the_latency_budget_at_pick_one() -> None:
    """p95 recompute() < 2 s end-to-end, and comfortably under the 200 ms analytic budget."""
    ctx = _big_context()
    assert len(ctx.mu) >= 200  # pick-1 worst case
    state = draft_state(1)
    recommend(state, ctx, ctx.params)  # warm up imports/JITless caches

    samples_ms = []
    for _ in range(25):
        start = time.perf_counter()
        recommend(state, ctx, ctx.params)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    samples_ms.sort()
    p95 = samples_ms[int(0.95 * (len(samples_ms) - 1))]
    assert p95 < 2000.0  # hard end-to-end budget
    assert p95 < 200.0, f"analytic recompute p95 {p95:.1f}ms exceeds the 200ms budget"


def test_the_rooms_draft_order_does_not_cost_the_latency_budget() -> None:
    """TIER 12 — the room's entered order is overlaid onto the context's settings on every
    recompute (``engine/context.py::effective_settings``), so it is one ``model_copy`` per pick on
    the hot path. Pinned against the same <200 ms analytic budget, on the same worst case.

    ⚠️ This measures the STEADY STATE, like the test above, and that is now stated rather than
    assumed: the FIRST recompute of a draft is a different measurement entirely (it used to cost
    205-269 ms of lazy scipy/numpy import), and it is pinned structurally in
    ``tests/test_cold_start_latency.py`` because no p95 over a warm process can see it.
    """
    ctx = _big_context()
    state = draft_state(1, my_team_id="t0").model_copy(
        update={"draft_order": [f"t{i}" for i in range(12)]}
    )
    recommend(state, ctx, ctx.params)  # warm up, exactly as the budget test above does

    samples_ms = []
    for _ in range(25):
        start = time.perf_counter()
        rec = recommend(state, ctx, ctx.params)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    samples_ms.sort()
    p95 = samples_ms[int(0.95 * (len(samples_ms) - 1))]
    assert rec.survival_basis == "my_slot", "the order never reached the engine; budget is moot"
    assert p95 < 200.0, f"analytic recompute p95 {p95:.1f}ms exceeds the 200ms budget"
