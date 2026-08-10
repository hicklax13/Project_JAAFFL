"""Pay the hot path's lazy imports at PRECOMPUTE, not at the owner's first pick.

``engine/opponents.py`` and ``engine/optimize.py`` import ``numpy`` and ``scipy`` inside their
functions rather than at module scope — deliberately, so that importing the engine (and therefore
booting the API, or running a script that only needs the domain models) does not drag in the
scientific stack. The cost does not disappear, though; it moves to whoever calls first.

Measured 2026-08-10, Tier 12, and found by the rehearsal instrumentation rather than by a test:

    first  recommend()  268.6 ms
    second recommend()    0.6 ms
    third                 0.5 ms

On draft night the first caller is the owner's **first pick**, against a documented <200 ms
budget and a live clock. ``test_engine_latency.py`` never saw it because it measures p95 over
repeated calls in an already-warm process — see ``tests/test_cold_start_latency.py``.

So: `build_registry_context_source` already owns every one-time cost in this system (it is where
all provider I/O and network live, by design §4.7). Warming these imports there costs nothing
extra — precompute has already imported far heavier things — and makes the per-pick hot path
import-free, which is the invariant the tests assert.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def warm_hot_path() -> None:
    """Import everything ``recommend()`` imports lazily, so no pick ever pays for it.

    Import-only and idempotent (``sys.modules`` makes the second call free). Never raises: a
    failure here means the very next recompute pays the cost it would have paid anyway, which is
    strictly better than refusing to build a context over it.
    """
    try:
        import numpy  # noqa: F401 — imported for its side effect on sys.modules
        import scipy.optimize  # noqa: F401 — engine/optimize.py::linear_sum_assignment
        import scipy.special  # noqa: F401 — engine/opponents.py::ndtr
    except Exception:  # noqa: BLE001 — see the docstring: warming is best-effort by design
        log.warning("engine_warmup_failed", exc_info=True)
