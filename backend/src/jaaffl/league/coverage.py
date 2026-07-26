"""Board position-coverage guard: can every STARTABLE slot actually be filled?

Two live gaps reached the default $0 board silently and were found only by accident:

* **K** — nflverse's ff_playerids spells kicker ``PK`` while the domain spells it ``K``, so an
  un-aliased position gate dropped all 151 rostered kickers (fixed in
  ``crosswalk._PLAYERID_POSITION_ALIASES``).
* **DST** — ff_playerids carries no team-defense rows at all, so the universe had zero defenses
  until they were appended from ``load_teams`` (``providers.nflverse._team_defenses``).

Both were invisible for the same reason: the loader reports a SKIP COUNT, and ~8,000 skipped IDP
rows is normal-looking, so a few hundred missing kickers hid in the noise. This module inverts the
question. Instead of "were there unmapped source codes?" (noisy, unactionable, ignored) it asks
"is any startable position missing from the board?" — a list that is empty in the healthy case and
names the exact problem otherwise.

Startability is derived from the league's OWN roster slots rather than hard-coded, so the guard
tracks a league change automatically and never demands a bench-only IDP position this league
cannot start (which would make it fire forever and be trained away as noise).

Deliberately reports rather than raises. Callers choose the severity appropriate to WHEN they
run: ``engine.precompute`` logs a warning and still serves a degraded board (a context can be
rebuilt mid-draft after a restart, where crashing would be far worse than an incomplete board),
while the owner-run ``scripts/preflight.py`` exits non-zero — a hard failure is safe and useful
hours before the draft, when there is still time to fix it.
"""

from __future__ import annotations

from collections.abc import Mapping

from jaaffl.domain import LeagueSettings, Position


def startable_positions(settings: LeagueSettings) -> set[Position]:
    """Every position that can fill a STARTING slot, unioned across flex eligibility.

    Bench/IR slots are excluded (``starting=False``), as are ``count=0`` slots, so the result is
    exactly the set the board must be able to serve on draft day. For JAAFFL that is
    ``{QB, RB, WR, TE, K, DST}`` — the WR/RB flex adds no new position, and the 8 bench slots add
    none because a bench spot is never a slot the draft MUST fill from a specific position.
    """
    return {
        position
        for slot in settings.roster_slots
        if slot.starting and slot.count > 0
        for position in slot.eligible_positions
    }


def board_coverage_gaps(settings: LeagueSettings, board: Mapping[str, Position]) -> list[Position]:
    """Startable positions with NO player on ``board``, sorted for stable reporting.

    ``board`` maps player_id -> position for the players that are actually DRAFTABLE — i.e. the
    ones carrying a projection (``DraftContext.mu``), not merely the loaded universe. That
    distinction is the whole point: a defense with no projection is in the universe but can never
    be recommended, so a universe-only check would have reported healthy while the board was not.
    """
    present = set(board.values())
    return sorted(startable_positions(settings) - present)
