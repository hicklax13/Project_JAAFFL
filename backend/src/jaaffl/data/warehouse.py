"""Local-first warehouse: DuckDB + Parquet for analytics, SQLite for app/league state.

Single-user default per ADR 0002. The domain schema is kept stable enough to graduate to
PostgreSQL ``jsonb`` + Redis Streams later without changing callers.
"""

from __future__ import annotations

from pathlib import Path

from jaaffl.config import get_settings
from jaaffl.domain import DraftState, LeagueSettings


class Warehouse:
    """Handle to the local data stores under ``JAAFFL_DATA_DIR``."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or get_settings().jaaffl_data_dir

    def init(self) -> None:
        """Create the data directory and initialize DuckDB/SQLite schemas if absent."""
        raise NotImplementedError("stage 3: create warehouse schemas")

    def snapshot_league(self, settings: LeagueSettings) -> None:
        """Persist a league-settings snapshot so historical analysis is owned locally."""
        raise NotImplementedError("stage 3: persist league snapshot")

    def snapshot_draft_state(self, state: DraftState) -> None:
        """Append a draft-state snapshot for replay, backtesting, and manager modeling."""
        raise NotImplementedError("stage 3: persist draft-state snapshot")
