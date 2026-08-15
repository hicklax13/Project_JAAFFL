"""Typed application settings loaded from the environment / ``.env``.

Field names match the environment variable names (case-insensitive). Paid providers
and the unofficial CBS adapter default to disabled — see ``docs/adr/0003`` and
``docs/legal-and-compliance.md``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/jaaffl/config.py → the repo root is parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]


class EngineParams(BaseModel):
    """Versioned engine tunables (design §10.3), single source of truth: config/engine.json.

    Calibration scripts (E1/E2) write back to that file, bumping ``version``. Expressly NOT
    part of the immutable config/league.json constitution. ``extra="forbid"`` so a typo'd
    or stale key in the file fails loud instead of silently running on defaults.
    """

    model_config = ConfigDict(extra="forbid")

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
    # Only `mu_refinement_pct` is real (read by engine/projections.py). The positional-modifier
    # caps that used to sit here promised bye-stack / handcuff / SOS handling the engine has never
    # had: `recommend._positional_modifiers` returns {} and no clamping code exists. Removed in
    # Tier 6 rather than left as a default that would silently restore the advertisement whenever
    # `config/engine.json` omits the key. See recommend._positional_modifiers for the measurements.
    caps: dict = Field(default_factory=lambda: {"mu_refinement_pct": 0.15})
    candidate_cap: int = 180
    mc_enabled: bool = False
    mc_rollouts: int = 2000
    # §3.10 v1.1 round-aware refinements (R1-R4), tuned in E2.
    reliability_shrinkage: dict[str, float] = Field(
        default_factory=lambda: {"K": 0.4, "DST": 0.4}  # unlisted positions default to 1.0
    )
    punt_guard: dict = Field(
        default_factory=lambda: {"enabled": True, "stream_round": {"K": 17, "DST": 16}}
    )
    vona_horizon_picks: int = 2  # 1 = one-step (legacy); 2 = turn-aware v1 default
    board_survival_weight: float = 0.5  # beta; 0 = pure static ADP
    situation_adjust: dict = Field(
        default_factory=lambda: {  # §3.10 R4 opportunity/situation mu/sigma layer
            "enabled": True,
            "mu_cap_pct": 0.15,
            "vacated_regression": 0.5,
            "rookie_capital_weight": 0.6,
            "sigma_widen_on_change": 1.25,
        }
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute: the service launches from backend/ (pytest, backend-dev) AND the repo root
        # (scripts). A CWD-relative ".env" made the repo-root file silently invisible from
        # backend/, so edits to it appeared to do nothing at all.
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Companion service
    jaaffl_api_host: str = "127.0.0.1"
    jaaffl_api_port: int = 8788
    jaaffl_log_level: str = "INFO"
    jaaffl_data_dir: Path = Path("./data")
    # Cross-origin allowlist for the localhost service. A WebSocket handshake is NOT gated
    # by CORS, so the app checks Origin itself: only the user's own extension
    # (chrome-extension://) and the local dashboard may write. "*" opens it to any web page
    # in another tab — set only for debugging.
    jaaffl_allowed_origins: str = (
        "chrome-extension://*,http://localhost:3000,http://127.0.0.1:3000,"
        # Record mode: the extension's content script runs INSIDE the CBS page, so its
        # requests carry the CBS page origin -- not chrome-extension://. Without CBS here a
        # capture session silently records zero frames.
        "https://*.cbssports.com"
    )
    jaaffl_season: int = 2026
    jaaffl_engine_params_path: Path = Path("./config/engine.json")
    # Pre-draft precompute bridge (§4.7). ON by default: create_app builds a registry-backed
    # context_source (the $0 providers) so a fresh clone reaches a real /recommendation with no
    # extra configuration. It FAILS SOFT — an empty universe or no projections returns None and
    # /recommendation 503s exactly as it did when this was off — so ON is the safe default, and
    # OFF was a documented setup that could never serve a pick. All provider I/O stays inside the
    # precompute closure (lazy, on first use); the per-pick hot path still touches no provider.
    # Set false to pin the old "warming up" behaviour (the test suite does, to stay offline).
    jaaffl_precompute_enabled: bool = True
    # The primary/demo league id the local dashboard + precompute target (single-user, ADR 0002).
    # GET /league/{id} serves the immutable constitution for THIS id (or any id that already has a
    # CBS snapshot or folded draft events); every other id is 404.
    jaaffl_league_id: str = "cbs-local"
    # MY draft slot, as CBS numbers the teams in the room ("1".."12").
    #
    # No CBS frame names the VIEWER's own team, so parse.ts cannot emit it and the folded
    # DraftState never carries one. Without it, opponents._my_overall_picks raises, survival
    # degrades to "everyone available", and VONA collapses to 0.00 on the best pick.
    # GET /recommendation?team_id= supplies it for a manual call; the /recs/ws PUSH path that
    # actually feeds the overlay has no query string, so it reads this instead. Leave unset and
    # the engine still ranks (on MLV) but reports survival_basis="degraded_no_slot" — degraded
    # loudly rather than silently. The owner knows their slot: config/league.json records that
    # the order is decided in person and entered into CBS.
    jaaffl_my_team_id: str | None = None
    # Stage-3 ID crosswalk (data/crosswalk.py) Stage-B fuzzy fallback acceptance threshold τ:
    # a name-similarity score (0–1, rapidfuzz/100) at/above this — with exact position + team
    # (team-agnostic for FAs) — is accepted as a 'fuzzy' match; below it stays unresolved for
    # manual mapping. 0.90 per plan §2.7; lower to widen recall, raise to reduce false links.
    jaaffl_crosswalk_fuzzy_threshold: float = 0.90
    # Record-mode capture sink (Phase 1): raw mock-draft frames land here for fixture
    # curation. Git-ignored — raw recordings may carry league names; only redacted
    # goldens are committed (plan §5.10).
    jaaffl_recordings_dir: Path = Path("./apps/extension/fixtures/cbs")
    # TIER 12 rehearsal evidence sink (api/rehearsal.py). UNSET = off, and off is the draft-night
    # default: a rehearsal is worth a log line per pick, a real draft is not worth a new failure
    # mode. When set, one JSONL line per recommendation actually served (push AND pull), written
    # fail-soft. Read by scripts/rehearsal_report.py. Like the raw captures, a real league's log
    # names other drafters' teams — keep it under the git-ignored data dir.
    jaaffl_rehearsal_log: Path | None = None

    @field_validator("jaaffl_rehearsal_log", mode="before")
    @classmethod
    def _blank_means_off(cls, value: object) -> object:
        """``JAAFFL_REHEARSAL_LOG=`` means OFF, not "append to the current directory".

        pydantic coerces the empty string to ``Path('')``, which IS ``Path('.')``, so a bare
        ``KEY=`` line read as a configured path. ``RehearsalLog`` then opened a DIRECTORY for
        append on every recommendation: ``PermissionError: [Errno 13] Permission denied: '.'``.
        Fail-soft swallowed it, so the sink reported itself ENABLED while writing nothing.

        ⚠️ Same bug class Tier 12 already fixed for ``JAAFFL_MY_TEAM_ID``, where ``KEY=`` in the
        owner's real ``.env`` parses as ``''`` rather than ``None`` — which is why ``api/app.py``
        tests that one for truthiness instead of ``is not None``. The owner's ``.env`` still
        carries a bare ``KEY=`` line, so this shape is routine, not hypothetical. Fixed at the
        parse boundary so every reader inherits it, not just the one that got bitten.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("jaaffl_data_dir", "jaaffl_engine_params_path", "jaaffl_recordings_dir")
    @classmethod
    def _anchor_to_repo_root(cls, value: Path) -> Path:
        """Resolve a RELATIVE configured path against the repo root, never the process CWD.

        The service legitimately runs from more than one directory — ``backend/`` for pytest and
        the ``backend-dev`` target, the repo root for scripts — so CWD-relative defaults silently
        split state across two trees. That was not cosmetic: record-mode captures landed in
        ``backend/apps/extension/fixtures/cbs``, which .gitignore does NOT cover (its
        ``apps/extension/fixtures/cbs/`` rule contains a slash and is therefore anchored to the
        repo root). Raw frames carry the owner's league name, so they became committable — exactly
        what docs/live-draft-recording-guide.md promises cannot happen. The warehouse split the
        same way, producing a second ``backend/data/app.sqlite``.

        Absolute values pass through untouched, so pytest's ``tmp_path`` fixtures and a deliberate
        owner override still win.
        """
        return value if value.is_absolute() else (_REPO_ROOT / value).resolve()

    # FantasyFootballCalculator ADP ($0 tier; stage 4). scoring/teams MIRROR the immutable
    # config/league.json ("Standard"/12) — surfaced (never silently changed) if they diverge.
    jaaffl_enable_ffc: bool = True
    jaaffl_ffc_scoring: str = "standard"  # path segment; mirrors league.json Scoring Format
    jaaffl_ffc_teams: int = 12  # query param; mirrors league.json Teams
    jaaffl_ffc_cache_ttl_hours: int = 24  # DAILY cache (FFC etiquette); do not lower below 24
    jaaffl_ffc_base_url: str = "https://fantasyfootballcalculator.com/api/v1"

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
