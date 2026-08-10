"""TIER 12 rehearsal evidence sink.

A live CBS draft is a one-shot, unrepeatable event on someone else's clock. Watching the overlay
during one yields impressions; this yields a file. One JSONL line per recommendation actually
served, from both the push (``/recs/ws``) and pull (``GET /recommendation``) paths, carrying
exactly the fields ``scripts/rehearsal_report.py`` turns into a pass/fail evidence table.

OFF unless ``jaaffl_rehearsal_log`` is set, and fail-soft when on — a recommendation must never
fail because a log line could not be written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from jaaffl.domain import DraftState, Recommendation
from jaaffl.engine.context import DraftContext

log = structlog.get_logger(__name__)


class RehearsalLog:
    """Append-only evidence sink. ``path=None`` makes every call a no-op."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def record(
        self,
        path_label: str,
        state: DraftState,
        rec: Recommendation,
        context: DraftContext | None,
    ) -> None:
        """Append one row. Swallows EVERY exception on purpose — see the module docstring."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            row = json.dumps(self._row(path_label, state, rec, context))
            with self._path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(row + "\n")
        except Exception:  # noqa: BLE001 — fail-soft is the whole point; see the module docstring
            log.warning("rehearsal_log_write_failed", path=str(self._path), exc_info=True)

    @staticmethod
    def _row(
        path_label: str,
        state: DraftState,
        rec: Recommendation,
        context: DraftContext | None,
    ) -> dict:
        board = context.mu if context is not None else {}
        # A pick is MASKED only when its id is a real candidate id. An unresolved name-only pick
        # (player_id None) or an unresolved "cbs:<id>" one is still on the owner's board and can
        # be recommended again — that is the correctness question a rehearsal must answer, and
        # `ingest/resolve.py` already logs it as a warning without anyone counting it.
        masked = sum(1 for p in state.picks if p.player_id and p.player_id in board)
        unresolved = [
            p.player_id or f"<name-only overall {p.overall}>"
            for p in state.picks
            if not p.player_id or p.player_id not in board
        ]
        top = rec.ranked[0] if rec.ranked else None
        top_components = top.components if top else None
        return {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "path": path_label,
            "league_id": rec.league_id,
            "overall": rec.as_of_overall_pick,
            "survival_basis": rec.survival_basis,
            "vona_method": rec.vona_method,
            "recompute_ms": rec.recompute_ms,
            "draft_order_len": len(state.draft_order) if state.draft_order else 0,
            "my_team_id": state.my_team_id,
            "ranked_n": len(rec.ranked),
            "positive_vona_n": sum(
                1 for p in rec.ranked if p.components and (p.components.vona or 0) > 0
            ),
            "picks_total": len(state.picks),
            "picks_masked": masked,
            "picks_unresolved": len(unresolved),
            "unresolved_ids": unresolved,
            "roster_filled": rec.roster_filled,
            "top": {
                "player_id": top.player_id if top else None,
                "name": top.name if top else None,
                "vona": top_components.vona if top_components else None,
                "mlv": top_components.mlv if top_components else None,
                "projected_points": top.projected_points if top else None,
            },
        }
