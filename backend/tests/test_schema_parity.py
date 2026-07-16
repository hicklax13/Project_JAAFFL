"""E5 schema-parity gate, Python side (plan §9.5).

Two checks: (1) every canonical fixture under packages/shared/fixtures validates under its
Pydantic model; (2) the checked-in JSON Schemas under packages/shared/schemas match a fresh
export (staleness check — run ``scripts/export_schemas.py`` after any model change).
The js side (packages/shared/tests/parity.test.ts) parses the SAME fixtures with Zod and
structurally compares the schemas, so a change on one side without the other fails CI.
"""

import json

import pytest
from pydantic import TypeAdapter

from jaaffl.domain.export import CONTRACT_MODELS, REPO_ROOT, render_all

FIXTURES = REPO_ROOT / "packages" / "shared" / "fixtures"
SCHEMAS = REPO_ROOT / "packages" / "shared" / "schemas"

MODEL_NAMES = [model.__name__ for model in CONTRACT_MODELS]


@pytest.mark.parametrize("model", CONTRACT_MODELS, ids=MODEL_NAMES)
def test_pydantic_accepts_canonical_fixture(model) -> None:
    payload = json.loads((FIXTURES / f"{model.__name__}.json").read_text(encoding="utf-8"))
    TypeAdapter(model).validate_python(payload)  # must not raise


def test_new_scaffold_fields_are_exercised_by_fixtures() -> None:
    """§1.6: the parity set must cover scoring_tiers + scoring_bonuses and a fully-populated
    ScoreComponents — the gate is meaningless if the fixtures skip the new fields."""
    league = json.loads((FIXTURES / "LeagueSettings.json").read_text(encoding="utf-8"))
    assert {t["stat"] for t in league["scoring_tiers"]} == {
        "dst_points_allowed",
        "dst_yards_allowed",
    }
    assert league["scoring_bonuses"], "K 50+ bonus fixture missing"
    pick = json.loads((FIXTURES / "RecommendedPick.json").read_text(encoding="utf-8"))
    assert pick["components"] is not None
    assert set(pick["components"]) == {
        "mlv",
        "vona",
        "risk_penalty",
        "cliff_bonus",
        "sigma",
        "floor",
        "ceiling",
        "replacement_baseline",
        "modifiers",
        # §3.10.5 v1.1 additive round-aware fields — exercised, not just declared.
        "reliability",
        "vona_horizon",
        "best_available_next",
    }


def test_checked_in_schemas_match_fresh_export() -> None:
    rendered = render_all()
    for name, text in rendered.items():
        on_disk = SCHEMAS / f"{name}.json"
        assert on_disk.exists(), f"{on_disk} missing — run scripts/export_schemas.py"
        assert on_disk.read_text(encoding="utf-8") == text, (
            f"{name}.json is stale — run scripts/export_schemas.py and commit the diff"
        )
    on_disk_names = {p.stem for p in SCHEMAS.glob("*.json")}
    assert on_disk_names == set(rendered), "orphan schema files present"


def test_every_contract_model_has_a_fixture() -> None:
    fixture_names = {p.stem for p in FIXTURES.glob("*.json")}
    assert fixture_names == set(MODEL_NAMES)
