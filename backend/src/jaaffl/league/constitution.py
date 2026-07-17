"""Load the immutable league constitution (config/league.json) into a normalized ``LeagueSettings``.

``config/league.json`` is the OWNER-PROVIDED, IMMUTABLE constitution (CLAUDE.md · ADR 0002): Snake ·
12 teams · Standard (non-PPR) · QB1/RB1/WR3/(WR-RB flex)1/TE1/K1/DST1/Bench8. This module reads
those values **verbatim** — team_count, draft_type, and the roster slots/counts — and NEVER infers a
``draft_order`` from team count (it stays ``None`` until the real CBS room order is read, per the
league rule / ``agent_usage_contract``).

The file carries no per-category scoring values (§ ``league.json`` ``scoring_note``);
``resolve_league_settings`` layers scoring on top: the owner-provided ``jaaffl_scoring()`` map is
authoritative (only CBS live-frame *parsing* stays capture-blocked, not the scoring values),
overridden by a captured CBS snapshot's ``league_settings`` scoring when present. The immutable
roster is never rewritten by a snapshot (conflicts are surfaced upstream, never silently applied).
"""

from __future__ import annotations

import json
from pathlib import Path

from jaaffl.domain import CbsPageSnapshot, LeagueSettings, Position, RosterSlot
from jaaffl.league.defaults import jaaffl_scoring

# backend/src/jaaffl/league/constitution.py → repo root is parents[4].
_REPO_ROOT = Path(__file__).resolve().parents[4]
_LEAGUE_JSON = _REPO_ROOT / "config" / "league.json"

# Bench holds offensive skill players only (no K/DST/IDP) — a JAAFFL modeling choice mirrored across
# the engine (tests.engine_fixtures.jaaffl_settings). The constitution's "Bench" key encodes only a
# count, not eligibility, so this default supplies the eligible set.
_BENCH_ELIGIBLE = (Position.QB, Position.RB, Position.WR, Position.TE)


def _roster_slots(roster: dict) -> list[RosterSlot]:
    """Map the constitution's ``roster_slots_per_team`` (ordered) to ``RosterSlot``s.

    Single-position keys ("QB", "RB", …) become that one position; a "/"-joined flex key ("WR/RB")
    becomes its listed positions (WR-or-RB only — no TE/QB); "Bench" is the non-starting depth slot.
    Labels are upper-cased so they match the engine's slot vocabulary ("WR/RB", "BENCH", …).
    """
    slots: list[RosterSlot] = []
    for key, count in roster.items():
        label = key.strip().upper()
        if label == "BENCH":
            slots.append(
                RosterSlot(
                    slot="BENCH",
                    eligible_positions=list(_BENCH_ELIGIBLE),
                    count=int(count),
                    starting=False,
                )
            )
            continue
        eligible = [Position(token) for token in label.split("/")]  # "WR/RB" → [WR, RB]
        slots.append(RosterSlot(slot=label, eligible_positions=eligible, count=int(count)))
    return slots


def load_constitution(league_id: str, *, path: Path | None = None) -> LeagueSettings:
    """The immutable constitution as a scoring-less ``LeagueSettings`` (roster/counts/draft_type).

    ``draft_order`` is ALWAYS ``None`` — never inferred from team count
    (``league.json`` → ``draft_order.infer_from_team_count = false``). Scoring is applied separately
    by :func:`resolve_league_settings`.
    """
    league = json.loads((path or _LEAGUE_JSON).read_text(encoding="utf-8"))["league"]
    return LeagueSettings(
        league_id=league_id,
        team_count=int(league["teams"]),
        draft_type=str(league["draft_type"]),
        draft_order=None,  # league rule: read from the live CBS room, never inferred here
        roster_slots=_roster_slots(league["roster_slots_per_team"]),
    )


def resolve_league_settings(
    league_id: str,
    *,
    path: Path | None = None,
    snapshot: CbsPageSnapshot | None = None,
) -> LeagueSettings:
    """The normalized settings the engine/dashboard consume: constitution roster + CBS scoring.

    Scoring is the owner-provided ``jaaffl_scoring()`` map (authoritative — only CBS live-frame
    parsing stays capture-blocked, not the values), overridden by a captured CBS snapshot's
    ``league_settings`` scoring when one is present. The immutable roster / team_count / draft_type
    / ``None`` draft_order are preserved verbatim — a snapshot never rewrites them.
    """
    base = load_constitution(league_id, path=path)
    rules, tiers, bonuses = jaaffl_scoring()
    captured = snapshot.league_settings if snapshot is not None else None
    if captured is not None and captured.scoring:  # a real capture wins over the offline default
        rules, tiers, bonuses = captured.scoring, captured.scoring_tiers, captured.scoring_bonuses
    return base.model_copy(
        update={"scoring": rules, "scoring_tiers": tiers, "scoring_bonuses": bonuses}
    )
