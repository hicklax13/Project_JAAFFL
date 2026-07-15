"""Typed application settings loaded from the environment / ``.env``.

Field names match the environment variable names (case-insensitive). Paid providers
and the unofficial CBS adapter default to disabled — see ``docs/adr/0003`` and
``docs/legal-and-compliance.md``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Companion service
    jaaffl_api_host: str = "127.0.0.1"
    jaaffl_api_port: int = 8787
    jaaffl_log_level: str = "INFO"
    jaaffl_data_dir: Path = Path("./data")

    # Providers — $0 default is nflverse (free) + CBS on-page data. Everything below opt-in.
    fantasypros_api_key: str | None = None
    jaaffl_enable_fantasypros: bool = False
    sportsdataio_api_key: str | None = None
    jaaffl_enable_sportsdataio: bool = False
    sportradar_api_key: str | None = None
    jaaffl_enable_sportradar: bool = False
    # Unofficial/deprecated CBS API adapter — keep off unless you understand the risk.
    jaaffl_enable_cbs_unofficial_api: bool = False

    # AI assistant (text-only; no voice)
    openai_api_key: str | None = None
    jaaffl_assistant_model: str = "gpt-4.1-mini"
    jaaffl_assistant_enable_web_search: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings (cached)."""
    return Settings()
