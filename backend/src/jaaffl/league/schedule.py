"""Bye weeks, derived from the free nflverse regular-season schedule.

A bye is not a projection or a coefficient — it is a **fact about the calendar**, published months
ahead and carrying no uncertainty to model. That is why it lands here rather than in the scorer:
``RecommendedPick.bye_week`` is display metadata the overlay already renders, and the honest way to
fill it is to read the schedule, not to weight anything by it.

Deliberately derived by ABSENCE rather than read from a bye column, because the schedule feed has
no such column: a team's bye is the week it appears in no game. That inversion is only safe with a
strict arity rule — see :func:`bye_weeks`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from jaaffl.data.crosswalk import team_norm
from jaaffl.domain import Player


def bye_weeks(games: Iterable[tuple[int, str, str]]) -> dict[str, int]:
    """Map each team to its single bye week, from ``(week, home_team, away_team)`` rows.

    ``games`` must be REGULAR-SEASON rows only. A team is assigned a bye **only when exactly one
    week in the observed span is missing** for it; a team missing zero or several weeks is omitted
    entirely rather than guessed at. That rule is what makes the absence-based derivation safe:
    hand it playoff rows by mistake and almost every team misses many weeks, so the result is an
    empty map — a visibly absent bye — instead of a plausible wrong one on every player's chip.

    The span is the observed ``max(week)``, not a hard-coded 18, so a future schedule expansion
    needs no edit here.
    """
    played: dict[str, set[int]] = {}
    weeks: set[int] = set()
    for week, home, away in games:
        weeks.add(week)
        for team in (home, away):
            played.setdefault(team, set()).add(week)
    if not weeks:
        return {}

    span = set(range(1, max(weeks) + 1))
    byes: dict[str, int] = {}
    for team, team_weeks in played.items():
        missing = span - team_weeks
        if len(missing) == 1:
            byes[team] = next(iter(missing))
    return byes


def player_bye_weeks(players: Mapping[str, Player], team_byes: Mapping[str, int]) -> dict[str, int]:
    """Join the per-team bye onto players, keyed by canonical player id.

    A player whose ``nfl_team`` is unknown (free agent, unresolved crosswalk row) or whose team has
    no derived bye is simply ABSENT from the result rather than carrying a placeholder — the
    contract's ``bye_week`` is ``int | None`` and the overlay only renders the chip when it is set,
    so absence degrades to "no chip" instead of a wrong week.

    Both sides are canonicalized through :func:`jaaffl.data.crosswalk.team_norm`, because the two
    FREE nflverse feeds do not agree: ``load_ff_playerids`` spells teams ``NOS``/``SFO``/``LAR``
    while ``load_schedules`` spells them ``NO``/``SF``/``LA``. Joining raw dropped 9 of 32 teams —
    152 of the 510 projected players on the live 2026 board — while looking perfectly healthy,
    because the remaining 23 teams resolved fine.
    """
    canonical = {}
    for team, week in team_byes.items():
        code = team_norm(team)
        if code is not None:
            canonical[code] = week
    out: dict[str, int] = {}
    for pid, player in players.items():
        code = team_norm(player.nfl_team)
        if code is not None and code in canonical:
            out[pid] = canonical[code]
    return out
