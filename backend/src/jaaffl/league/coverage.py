"""Board guards: can every STARTABLE slot be filled, and can the tier-cliff term move a pick?

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

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from jaaffl.data.crosswalk import team_norm
from jaaffl.domain import LeagueSettings, Player, Position

if TYPE_CHECKING:  # `engine` imports `league`, so the reverse must stay type-only
    from jaaffl.engine.optimize import StartingSlot


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


def inert_cliff_positions(
    settings: LeagueSettings,
    tiers: Mapping[str, int],
    cliff_bonus: Mapping[str, float],
    position: Mapping[str, Position],
) -> list[Position]:
    """Startable positions where the tier-cliff term can never move a pick, sorted.

    The same inversion as :func:`board_coverage_gaps`, one layer up. ``cliff_bonus`` was POPULATED
    and useless for four tiers of work: 447 entries on the live 2026 board and every one exactly
    0.0, so ``recommend``'s ``α·CliffBonus_p`` contributed 0.00 to every pick, the overlay's
    tier-cliff bar could never be non-zero, ``explain``'s "the talent drops off after this tier"
    sentence could never render, and E2 kept reporting a tuned α over a term that could not change
    a single choice. A map SIZE looked healthy the entire time — so this asks the only question
    that distinguishes the two states: **is any drop at this position priced above zero?**

    That single condition covers both live shapes of death. All 31 defenses landed in ONE tier, so
    DST had no boundary to price at all; the other five positions had boundaries that every one
    priced to ``max(0.0, 0.00 − 0.00)`` because both sides sat below replacement. Different causes,
    identical consequence, one report.

    Per position rather than board-wide on purpose: a board-wide "some cliff exists somewhere"
    check passes while the term is dead at two of the six positions, which is most of the way back
    to the bug.

    Deliberately reports rather than raises, and deliberately does NOT decide which positions are
    allowed to be flat — that is the caller's call, because it depends on WHEN the check runs and
    on engine config the league module has no business reading. ``engine.precompute`` logs a
    warning (a context can be rebuilt mid-draft, where a degraded board beats no board), while
    ``scripts/preflight.py`` hard-fails for non-puntable positions and merely reports K/DST: those
    are stream positions whose boards really are flat (the live 2026 kicker cliff tops out at 2.97
    points), so demanding a cliff there would manufacture urgency the data does not support.
    """
    live: set[Position] = {
        position[pid]
        for pid, bonus in cliff_bonus.items()
        if bonus > 0.0 and pid in position and pid in tiers
    }
    return sorted(startable_positions(settings) - live)


def teams_missing_bye_weeks(
    players: Mapping[str, Player], bye_week: Mapping[str, int]
) -> list[str]:
    """NFL teams with a player on the board but NO bye week, canonicalized and sorted.

    The third instance of this module's one question, and the third time the same shape of bug
    reached the live board: two free nflverse feeds spell teams differently — ``load_ff_playerids``
    says ``NOS``/``SFO``/``LAR``, ``load_schedules`` says ``NO``/``SF``/``LA`` — so joining them raw
    silently dropped **9 of 32 teams, 152 of the 510 projected players**, while the other 23 teams
    resolved perfectly and the map looked populated. A COUNT of bye entries would have read healthy
    the whole time (it was 1188), exactly as ``cliff_bonus``'s 447 entries did.

    Reported per TEAM rather than per player because the team is the unit the failure has: one
    unmapped code takes a whole roster with it, so a per-team list is short and names the cause.

    Free agents are NOT a gap: ``team_norm`` folds ``FA``/blank to ``None`` and they are skipped,
    because a player with no team cannot have a bye and reporting it forever would train the
    alarm away — the same reasoning that keeps K/DST out of the tier-cliff hard failure.
    """
    covered = {team_norm(players[pid].nfl_team) for pid in bye_week if pid in players}
    missing = {
        team_norm(player.nfl_team)
        for pid, player in players.items()
        if pid not in bye_week and team_norm(player.nfl_team) is not None
    }
    return sorted(team for team in missing - covered if team is not None)


def unfillable_starting_slots(
    roster: Sequence[str],
    position: Mapping[str, Position],
    slots: Sequence[StartingSlot],
) -> list[str]:
    """Starting slots this roster cannot fill, by slot label, sorted. Empty in the healthy case.

    The fourth instance of this module's one question, and the fourth time the same shape of bug
    reached the live board. A roster SIZE read healthy for six tiers: Tier 6 walked a full 12x17
    draft on the real board using the engine's own recommendations and got ``{RB:1, TE:13, WR:3}``
    — 17 of 17 picks made, and **three of the nine starting slots unfillable** — identically under
    both best-available and need-based opponents. ``cliff_bonus``'s 447 entries and the bye join's
    1188 read healthy the same way. A count is not a diagnostic; this asks the only question that
    distinguishes the two states: **can nine players actually take the field?**

    Feasibility, not value: it counts bodies per position rather than scoring a lineup, because a
    slot is legal to fill regardless of how badly the player projects. Dedicated slots are matched
    before the flex (a dedicated slot has no alternative), and the flex then draws from whichever
    eligible position has the most bodies left — which is optimal for this league's single WR/RB
    flex, so the flex is **honoured rather than assumed**.

    Deliberately reports rather than raises, like every guard in this module. The preflight has no
    roster to check before the draft, so this stays a post-draft / simulation assertion:
    ``backend/tests/test_late_round_legality.py`` walks a draft and requires this to be empty.
    """
    remaining: dict[Position, int] = {}
    for pid in roster:
        pos = position.get(pid)
        if pos is not None:
            remaining[pos] = remaining.get(pos, 0) + 1

    unfilled: list[str] = []
    for slot in sorted(slots, key=lambda s: len(s.eligible)):
        best = max(slot.eligible, key=lambda pos: remaining.get(pos, 0), default=None)
        if best is not None and remaining.get(best, 0) > 0:
            remaining[best] -= 1
        else:
            unfilled.append(slot.label)
    return sorted(unfilled)
