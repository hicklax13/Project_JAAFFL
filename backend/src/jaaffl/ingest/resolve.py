"""Resolve name-only AND cbs:-id-only drafted picks to canonical player ids (the live-recs
keystone).

Two kinds of pick arrive without a canonical id:

* **Manual-paste** picks are name-only (``DraftPick.player_id is None``); the ``player_name`` /
  ``position`` / ``player_team`` live in the raw ``pick_made`` event payload, not the folded
  ``DraftState`` (``fold_state`` stays pure; ``DraftPick`` stays a frozen contract model).
* **Real CBS** picks are ID-only (docs/research/cbs-draft-protocol.md §3/§5): ``parse.ts`` sets
  ``player_id`` to ``cbs:<cbsid>`` directly on the pick, but that id is a raw source id, NOT
  canonical — CBS frames carry no name/position/team at all, only the numeric id.

This module bridges both to the engine's candidate pool, which only masks a drafted player when
its ``player_id`` matches a CANDIDATE's canonical id: given the folded state, the league's logged
events, an injected name resolver, and an injected cbs-id resolver (both backed by the crosswalk),
it fills ``player_id`` for name-only picks from their event name, and for ``cbs:``-prefixed picks
from a ``('cbs', cbsid)`` crosswalk lookup. It does NO provider/network I/O (both resolvers are
injected) and never mutates the log. A pick that already carries any OTHER (i.e. canonical) id is
left untouched — never re-resolved. Unresolved picks (name found nothing, or no crosswalk link for
the cbs id yet) keep their original ``player_id`` (``None`` for a name-only miss, ``cbs:<id>`` for
a cbs miss — never guessed, never dropped from ``state.picks``) and are logged (a drafted-but-
unmasked player is a real correctness gap — surfaced, never silently swallowed).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import structlog

from jaaffl.domain import DraftEventType, DraftPick, DraftState
from jaaffl.ingest.log import LoggedEvent

log = structlog.get_logger(__name__)

# (name, nfl_team|None, canonical_position) -> canonical player_id | None
NameResolver = Callable[[str, str | None, str], str | None]

# cbs source id (WITHOUT the "cbs:" prefix) -> canonical player_id | None. Typically
# ``lambda cbs_id: crosswalk.resolve("cbs", cbs_id)`` — a pure indexed lookup, no fuzzy match (the
# crosswalk is seeded ahead of time by scripts/seed_cbs_crosswalk.py; a live pick never guesses).
CbsIdResolver = Callable[[str], str | None]

# parse.ts's convention for a real CBS pick (playerData()/cbsPlayerData() in parse.ts) — matches
# docs/research/cbs-draft-protocol.md §5: "Canonical id form stays cbs:<cbsid>".
_CBS_ID_PREFIX = "cbs:"

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
    state: DraftState,
    events: Iterable[LoggedEvent],
    resolver: NameResolver,
    cbs_resolver: CbsIdResolver | None = None,
) -> DraftState:
    """Return ``state`` with name-only picks' ``player_id`` filled via ``resolver`` and
    ``cbs:``-id-only picks' ``player_id`` filled via ``cbs_resolver``. A pick already carrying any
    other id (canonical, e.g. ``gsis:...``) is never touched — no double resolution. Returns the
    same object when nothing changed. ``cbs_resolver`` defaults to ``None`` (no cbs: id can
    resolve on that call — every ``cbs:`` pick degrades exactly like a crosswalk miss) so callers
    that only ever see manual-paste picks don't need to wire one."""
    name_index: dict[int, dict] = {}
    for ev in events:
        if ev.event_type == DraftEventType.PICK_MADE:
            overall = ev.data.get("overall")
            if overall is not None:
                name_index[int(overall)] = ev.data

    resolved = 0
    unresolved = 0
    unresolved_overalls: list[int] = []
    changed = False
    new_picks: list[DraftPick] = []
    for pick in state.picks:
        pid = pick.player_id

        if pid is not None and pid.startswith(_CBS_ID_PREFIX):
            cbs_id = pid[len(_CBS_ID_PREFIX) :]
            canonical = cbs_resolver(cbs_id) if cbs_resolver is not None else None
            if canonical is None:
                new_picks.append(pick)  # degrade honestly: keep "cbs:<id>", never guess/drop
                unresolved += 1
                unresolved_overalls.append(pick.overall)
                continue
            new_picks.append(pick.model_copy(update={"player_id": canonical}))
            resolved += 1
            changed = True
            continue

        if pid is not None:  # already canonical (or any other non-cbs id): never re-resolved
            new_picks.append(pick)
            continue

        data = name_index.get(pick.overall)
        name = data.get("player_name") if data else None
        pos = _canonical_position(data.get("position")) if data else None
        if not name or pos is None:
            new_picks.append(pick)
            unresolved += 1
            unresolved_overalls.append(pick.overall)
            continue
        team = data.get("player_team") or data.get("nfl_team")
        canonical = resolver(str(name), str(team) if team else None, pos)
        if canonical is None:
            new_picks.append(pick)
            unresolved += 1
            unresolved_overalls.append(pick.overall)
            continue
        new_picks.append(pick.model_copy(update={"player_id": canonical}))
        resolved += 1
        changed = True

    if unresolved:
        # An unresolved pick (name-only or cbs:-only) means a drafted player is NOT masked and can
        # be recommended again — a real correctness gap (loudest when the crosswalk was never
        # seeded and EVERY pick fails). Surface it at WARNING with the offending picks; never a
        # silent swallow.
        log.warning(
            "drafted_pick_name_resolution_incomplete",
            resolved=resolved,
            unresolved=unresolved,
            unresolved_overalls=unresolved_overalls,
        )
    elif resolved:
        log.info("drafted_pick_name_resolution", resolved=resolved, unresolved=0)
    return state.model_copy(update={"picks": new_picks}) if changed else state
