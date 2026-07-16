"""Origin allowlist for the localhost companion service (plan §8.4/§8.6, §5.10).

The service binds 127.0.0.1, but a hostile web page in another browser tab can still reach
it: CORS does not gate WebSocket handshakes, and a simple/preflighted POST can be sent
cross-origin. So state-changing endpoints check the ``Origin`` header themselves against a
configured allowlist (the user's own extension + the local dashboard). A missing Origin
(non-browser clients: curl, the replay script, tests) is allowed — the browser-driven
cross-origin threat always carries an Origin.
"""

from __future__ import annotations

import fnmatch


def parse_allowed_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


def is_origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """True if ``origin`` matches the allowlist. None (no Origin header) is allowed —
    only browsers attach Origin, and that is the threat we gate. ``*`` allows everything."""
    if origin is None:
        return True
    if "*" in allowed:
        return True
    return any(fnmatch.fnmatch(origin, pattern) for pattern in allowed)
