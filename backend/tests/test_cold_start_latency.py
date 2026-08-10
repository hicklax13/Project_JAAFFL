"""TIER 12 — the FIRST recommendation of a draft cost 40x every later one, and no test could see it.

Found by this tier's own rehearsal instrumentation, not by a unit test. The evidence log from a
smoke run against a real running server:

    overall 2  push  my_slot  205.1 ms   <- the first recompute
    overall 3  push  my_slot    6.3 ms
    overall 4  push  my_slot    7.3 ms   ... and ~6 ms for every row after

Reproduced outside the API at 268.6 ms / 0.6 ms / 0.5 ms / 0.5 ms. The cause is not the board:
``engine/opponents.py`` and ``engine/optimize.py`` import ``numpy`` and ``scipy`` LAZILY, inside
the hot path, so the first pick of the draft pays the import cost of both — on the clock.

⚠️ Why ``test_engine_latency.py`` cannot catch this. It measures **p95 over repeated calls in an
already-warm process**, and by the time it runs some earlier test in the suite has already
imported scipy. It calls that "the pick-1 worst case"; the real worst case is 40x larger and
happens exactly once, at the pick that matters most.

These tests therefore run in a FRESH INTERPRETER (subprocess), which is the only way to observe a
cold start from inside a warm suite.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

# Builds a fixture context, then reports which modules ONE recommend() call imports. Printed as
# JSON on the last line so the parent can read it regardless of any logging noise above.
_PROBE = """
import json, sys
sys.path.insert(0, r"{backend}")
sys.path.insert(0, r"{backend}/tests")
from tests.engine_fixtures import engine_params, make_context
from jaaffl.domain import DraftState, Position
from jaaffl.engine.recommend import recommend

specs = [
    {{"pid": f"rb{{i}}", "pos": Position.RB, "mu": 300.0 - i, "adp": float(i + 1),
      "sd": 6.0, "ecr": float(i + 1)}}
    for i in range(60)
]
ctx = make_context(specs, params=engine_params())
{warm}
state = DraftState(league_id="cbs-test", current_overall_pick=1, my_team_id="t0")
before = set(sys.modules)
recommend(state, ctx, ctx.params, limit=50)
new = sorted({{m.split(".")[0] for m in set(sys.modules) - before}})
print(json.dumps(new))
"""


def _modules_imported_by_one_recompute(*, warm: str) -> list[str]:
    code = _PROBE.format(backend=BACKEND.as_posix(), warm=warm)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_hot_path_imports_nothing_once_the_context_is_built() -> None:
    """The invariant, stated as the thing that actually matters: after precompute has produced a
    context, serving a pick must not import anything. An import is unbounded work on the clock.

    Asserted on "imported nothing", not on a millisecond threshold, so it stays deterministic in
    CI and so it also catches a NEW lazy import that a timing bound might absorb.
    """
    imported = _modules_imported_by_one_recompute(
        warm="from jaaffl.engine.warmup import warm_hot_path; warm_hot_path()"
    )
    assert imported == [], f"the per-pick hot path imported {imported} — that cost lands on a pick"


def test_without_the_warm_up_the_first_pick_really_does_pay_for_scipy() -> None:
    """The defect itself, pinned. This is what makes the test above meaningful rather than
    vacuous: remove the warm-up and numpy + scipy are imported by the first recompute — measured
    at 205-269 ms, against a documented <200 ms budget.

    If this ever starts passing (i.e. the probe imports nothing WITHOUT the warm-up), the lazy
    imports have moved to module scope and `warm_hot_path` is dead code that should be deleted —
    not a test to relax.
    """
    imported = _modules_imported_by_one_recompute(warm="")
    assert "scipy" in imported, (
        "the hot path no longer imports scipy lazily; warm_hot_path may now be dead code"
    )
