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


def allowed_origin_regex(allowed: list[str]) -> str | None:
    """The glob allowlist as ONE regex, for Starlette's ``CORSMiddleware``.

    ``CORSMiddleware(allow_origins=[...])`` compares origins by EXACT string equality — it never
    matches a glob such as ``https://*.cbssports.com``. Left unhandled, that desynchronizes the two
    gates: :func:`is_origin_allowed` (fnmatch) accepts the origin, so the WebSocket handshake
    succeeds, while the CORS preflight for a JSON POST fails (``OPTIONS`` → 400) and the request
    never happens. That is not hypothetical — it silently dropped every record-mode frame during a
    live capture session while the sockets looked healthy.

    Translating the same globs keeps both gates in lockstep. ``None`` when ``*`` is present, since
    the caller then opens CORS wholesale.
    """
    if "*" in allowed:
        return None
    return "|".join(fnmatch.translate(pattern) for pattern in allowed)
