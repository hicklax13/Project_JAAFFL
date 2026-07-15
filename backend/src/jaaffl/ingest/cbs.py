"""Normalize raw CBS payloads (captured by the extension) into domain models.

The extension does light normalization in the browser; this module owns the
authoritative parse into ``LeagueSettings`` / ``DraftState``. Draft order is read from
the live room, never inferred from league size alone.
"""

from __future__ import annotations

from jaaffl.domain import DraftState, LeagueSettings


def normalize_league_settings(raw: dict) -> LeagueSettings:
    """Parse CBS roster slots, flex eligibility, scoring rules, team count, keeper/dynasty
    flags, and (if present) explicit draft order into ``LeagueSettings``."""
    raise NotImplementedError("stage 2: parse CBS league settings")


def normalize_draft_state(raw: dict) -> DraftState:
    """Parse the live CBS draft board / pick feed into a ``DraftState`` snapshot."""
    raise NotImplementedError("stage 1–2: parse CBS live draft state")
