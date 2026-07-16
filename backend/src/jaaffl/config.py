"""Typed application settings loaded from the environment / ``.env``.

Field names match the environment variable names (case-insensitive). Paid providers
and the unofficial CBS adapter default to disabled — see ``docs/adr/0003`` and
``docs/legal-and-compliance.md``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineParams(BaseModel):
    """Versioned engine tunables (design §10.3), single source of truth: config/engine.json.

    Calibration scripts (E1/E2) write back to that file, bumping ``version``. Expressly NOT
    part of the immutable config/league.json constitution.
    """

    version: int = 1
    scoring_format: str = "standard"
    kappa: float = 0.65  # weight on max(0, VONA); design range 0.5–0.8
    alpha: float = 0.40  # weight on CliffBonus; design range 0.3–0.5
    projection_blend: str = "simple_average"
    # WR/RB flex demand allocation — MEASURE LIVE (top-60 method, §9 E1).
    flex_split: dict[str, int] = Field(default_factory=lambda: {"RB": 8, "WR": 4})
    # [{"rounds": [lo, hi], "lambda": float}, ...] — floor-tilt >0 early, ceiling-tilt <0 late.
    lambda_schedule: list[dict] = Field(default_factory=list)
    lambda_slot_override: dict[str, float] = Field(
        default_factory=lambda: {"last_startable_slot_floor": 0.40, "surplus_stash_ceiling": -0.40}
    )
    replacement_blend: dict[str, float] = Field(
        default_factory=lambda: {"vols_weight": 0.5, "mangames_weight": 0.5}
    )
    caps: dict = Field(
        default_factory=lambda: {
            "modifier_abs_max": 5.0,
            "mu_refinement_pct": 0.15,
            "modifiers": {"bye_stack": 3.0, "handcuff_synergy": 5.0, "sos": 3.0},
        }
    )
    candidate_cap: int = 180
    mc_enabled: bool = False
    mc_rollouts: int = 2000


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
    jaaffl_season: int = 2026
    jaaffl_engine_params_path: Path = Path("./config/engine.json")

    # FantasyFootballCalculator ADP ($0 tier; stage 4). Teams mirrors the fixed 12-team
    # league setting (config/league.json) but never overrides it.
    jaaffl_enable_ffc: bool = True
    jaaffl_ffc_scoring: str = "standard"
    jaaffl_ffc_teams: int = 12

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


@lru_cache
def get_engine_params() -> EngineParams:
    """Load the versioned engine tunables from ``jaaffl_engine_params_path`` (cached)."""
    path = get_settings().jaaffl_engine_params_path
    return EngineParams.model_validate_json(path.read_text(encoding="utf-8"))
