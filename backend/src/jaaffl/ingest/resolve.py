"""Resolve name-only drafted picks to canonical player ids (the live-recs keystone).

Manual-paste picks arrive name-only (``DraftPick.player_id is None``); the ``player_name`` /
``position`` / ``player_team`` live in the raw ``pick_made`` event payload, not the folded
``DraftState`` (``fold_state`` stays pure; ``DraftPick`` stays a frozen contract model). This module
bridges the two: given the folded state, the league's logged events, and an injected name resolver
(the crosswalk), it fills ``player_id`` for name-only picks so ``engine.recommend`` masks them from
the candidate pool. It does NO provider/network I/O (the resolver is injected) and never mutates the
log. Picks already carrying an id are left untouched — the out-of-scope ``cbs:`` capture path stays
out of it. Unresolved names stay ``None`` and are logged (a drafted-but-unmasked player is a real
correctness gap — surfaced, never silently swallowed).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import structlog

from jaaffl.domain import DraftEventType, DraftPick, DraftState
from jaaffl.ingest.log import LoggedEvent

log = structlog.get_logger(__name__)

# (name, nfl_team|None, canonical_position) -> canonical player_id | None
NameResolver = Callable[[str, str | None, str], str | None]

# Source position codes (manual-paste is user-typed) -> canonical Position value. resolve_name
# requires a canonical position; anything not aliased is upper-cased and passed through (already-
# canonical codes like RB/WR/QB/TE match as-is; an unknown code finds no candidates and stays
# unresolved).
_POSITION_ALIASES = {
    "DEF": "DST",
    "D/ST": "DST",
    "DEFENSE": "DST",
    "DST": "DST",
    "PK": "K",
    "K": "K",
}


def _canonical_position(raw: object) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip().upper()
    if not code:
        return None
    return _POSITION_ALIASES.get(code, code)


def resolve_pick_ids(
    state: DraftState, events: Iterable[LoggedEvent], resolver: NameResolver
) -> DraftState:
    """Return ``state`` with name-only picks' ``player_id`` filled from their event name via
    ``resolver``. Returns the same object when nothing changed."""
    name_index: dict[int, dict] = {}
    for ev in events:
        if ev.event_type == DraftEventType.PICK_MADE:
            overall = ev.data.get("overall")
            if overall is not None:
                name_index[int(overall)] = ev.data

    resolved = 0
    unresolved = 0
    changed = False
    new_picks: list[DraftPick] = []
    for pick in state.picks:
        if pick.player_id is not None:
            new_picks.append(pick)
            continue
        data = name_index.get(pick.overall)
        name = data.get("player_name") if data else None
        pos = _canonical_position(data.get("position")) if data else None
        if not name or pos is None:
            new_picks.append(pick)
            unresolved += 1
            continue
        team = data.get("player_team") or data.get("nfl_team")
        canonical = resolver(str(name), str(team) if team else None, pos)
        if canonical is None:
            new_picks.append(pick)
            unresolved += 1
            continue
        new_picks.append(pick.model_copy(update={"player_id": canonical}))
        resolved += 1
        changed = True

    if resolved or unresolved:
        log.info("drafted_pick_name_resolution", resolved=resolved, unresolved=unresolved)
    return state.model_copy(update={"picks": new_picks}) if changed else state
