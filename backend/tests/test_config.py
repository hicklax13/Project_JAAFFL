"""EngineParams (plan §1.5): versioned tunables in config/engine.json, loaded via jaaffl.config.

config/engine.json is a *tunable* file (calibration writes back to it) and is expressly NOT
part of the immutable config/league.json constitution.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from jaaffl.config import EngineParams, Settings, get_engine_params, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_JSON = REPO_ROOT / "config" / "engine.json"


def test_engine_params_defaults_match_design_10_3() -> None:
    params = EngineParams()
    assert params.kappa == 0.65
    assert params.alpha == 0.40
    assert params.projection_blend == "simple_average"
    assert params.flex_split == {"RB": 8, "WR": 4}
    assert params.candidate_cap == 180
    assert params.mc_enabled is False
    assert params.mc_rollouts == 2000
    assert params.replacement_blend == {"vols_weight": 0.5, "mangames_weight": 0.5}


def test_engine_params_v11_round_aware_defaults() -> None:
    """§3.10 R1-R4 knobs (amended §1.5): present with the documented priors, tuned in E2."""
    params = EngineParams()
    assert params.reliability_shrinkage == {"K": 0.4, "DST": 0.4}  # others default to 1.0
    assert params.punt_guard == {"enabled": True, "stream_round": {"K": 17, "DST": 16}}
    assert params.vona_horizon_picks == 2  # 1 = one-step legacy; 2 = turn-aware v1
    assert params.board_survival_weight == 0.5  # beta; 0 = pure static ADP
    assert params.situation_adjust == {
        "enabled": True,
        "mu_cap_pct": 0.15,
        "vacated_regression": 0.5,
        "rookie_capital_weight": 0.6,
        "sigma_widen_on_change": 1.25,
    }


def test_committed_engine_json_has_every_required_key() -> None:
    params = EngineParams.model_validate_json(ENGINE_JSON.read_text(encoding="utf-8"))
    assert params.version == 1
    assert params.scoring_format == "standard"
    # The full five-band lambda schedule covering rounds 1..17 (floor early, ceiling late).
    bands = [(b["rounds"][0], b["rounds"][1]) for b in params.lambda_schedule]
    assert bands == [(1, 2), (3, 6), (7, 9), (10, 13), (14, 17)]
    lambdas = [b["lambda"] for b in params.lambda_schedule]
    assert lambdas[0] > 0 and lambdas[-1] < 0  # floor-tilt early, ceiling-tilt late
    assert params.lambda_slot_override == {
        "last_startable_slot_floor": 0.40,
        "surplus_stash_ceiling": -0.40,
    }
    assert params.caps["mu_refinement_pct"] == 0.15  # read for real by engine/projections.py
    # The positional-modifier caps are DELIBERATELY absent, and this asserts they stay absent.
    # `recommend._positional_modifiers` returns {} unconditionally, no clamping code exists, and
    # nothing anywhere read these keys — so the committed config was promising bye-stack, handcuff
    # and SOS handling the engine has never had. Re-adding a cap here would re-advertise it; add
    # the cap in the same change that makes the modifier real, not before. See §6.C.7.
    assert "modifiers" not in params.caps
    assert "modifier_abs_max" not in params.caps
    # §3.10 v1.1 keys are versioned in the committed file, not just model defaults.
    assert params.reliability_shrinkage == {"K": 0.4, "DST": 0.4}
    assert params.punt_guard["stream_round"] == {"K": 17, "DST": 16}
    assert params.vona_horizon_picks == 2
    assert params.board_survival_weight == 0.5
    assert params.situation_adjust["mu_cap_pct"] == 0.15


def test_engine_params_rejects_unknown_keys() -> None:
    """A typo'd or stale key in config/engine.json (the calibration-written file) must
    fail loud, never silently fall back to defaults."""
    with pytest.raises(ValidationError):
        EngineParams.model_validate({"kapa": 0.7})


def test_get_engine_params_loads_via_settings_path(monkeypatch) -> None:
    monkeypatch.setenv("JAAFFL_ENGINE_PARAMS_PATH", str(ENGINE_JSON))
    get_settings.cache_clear()
    get_engine_params.cache_clear()
    try:
        assert get_engine_params().kappa == 0.65
    finally:
        get_settings.cache_clear()
        get_engine_params.cache_clear()


def test_settings_carry_stage_4_provider_fields() -> None:
    settings = Settings()
    assert settings.jaaffl_season == 2026
    assert settings.jaaffl_enable_ffc is True
    assert settings.jaaffl_ffc_scoring == "standard"
    # Mirrors the fixed 12-team league setting but never overrides config/league.json.
    assert settings.jaaffl_ffc_teams == 12
    # Anchored to the repo root, not the CWD — see test_relative_path_settings_* below.
    assert settings.jaaffl_engine_params_path == ENGINE_JSON


def test_relative_path_settings_anchor_to_the_repo_root_not_the_cwd() -> None:
    """State must land in ONE tree regardless of where the process was launched.

    The service runs from ``backend/`` (pytest, the ``backend-dev`` target) and from the repo root
    (scripts), so CWD-relative defaults split state across two trees. Concretely: record-mode
    captures landed in ``backend/apps/extension/fixtures/cbs``, which is NOT covered by
    .gitignore's root-anchored ``apps/extension/fixtures/cbs/`` rule — so raw frames carrying the
    owner's league name became committable, exactly what the recording guide promises cannot happen.
    """
    settings = Settings()

    assert settings.jaaffl_recordings_dir == REPO_ROOT / "apps" / "extension" / "fixtures" / "cbs"
    assert settings.jaaffl_data_dir == REPO_ROOT / "data"
    assert settings.jaaffl_engine_params_path == REPO_ROOT / "config" / "engine.json"


def test_relative_path_settings_resolve_the_same_from_any_cwd(monkeypatch, tmp_path: Path) -> None:
    """The whole point: chdir must not move where captures and the warehouse live."""
    from_root = Settings().jaaffl_recordings_dir

    monkeypatch.chdir(tmp_path)
    assert Settings().jaaffl_recordings_dir == from_root


def test_absolute_path_settings_pass_through_untouched(tmp_path: Path) -> None:
    """Explicit absolute overrides (pytest's tmp_path, an owner override) must not be rewritten."""
    settings = Settings(
        jaaffl_data_dir=tmp_path / "data",
        jaaffl_recordings_dir=tmp_path / "rec",
        jaaffl_engine_params_path=tmp_path / "engine.json",
    )

    assert settings.jaaffl_data_dir == tmp_path / "data"
    assert settings.jaaffl_recordings_dir == tmp_path / "rec"
    assert settings.jaaffl_engine_params_path == tmp_path / "engine.json"


def test_env_file_is_anchored_to_the_repo_root() -> None:
    """``SettingsConfigDict(env_file=".env")`` resolves against the process CWD, so launching from
    ``backend/`` looked for ``backend/.env`` and silently ignored the real repo-root file. That cost
    a live debugging cycle mid-capture: an edit to .env appeared to have no effect at all.
    """
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()
    assert Path(env_file) == REPO_ROOT / ".env"


def test_precompute_is_on_by_default_so_a_fresh_clone_serves_real_recommendations() -> None:
    """The flag gates whether ``create_app`` builds a registry-backed ``context_source`` at all.
    Defaulting it OFF meant a documented fresh-clone setup ended at a permanent 503 — the engine
    could never serve a real pick without an undocumented env var. It fails soft (no data →
    ``None`` → 503, the old behaviour), so ON is the safe default, not the risky one.

    ``_env_file=None`` so the assertion is about the CODE default, not the owner's local .env.
    """
    assert Settings(_env_file=None).jaaffl_precompute_enabled is True
