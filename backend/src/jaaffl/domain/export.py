"""JSON Schema export of the contract surface for the E5 parity gate (plan §9.5).

Pydantic is the source of truth; the js side derives JSON Schema from the Zod mirrors and
structurally compares (packages/shared/tests/parity.test.ts). CI fails on a stale export
(backend/tests/test_schema_parity.py + ``git diff --exit-code``). Regenerate with
``python scripts/export_schemas.py`` (or ``python -m jaaffl.domain.export``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from jaaffl.domain.models import (
    DraftEvent,
    DraftPick,
    DraftState,
    LeagueSettings,
    Position,
    Recommendation,
    RecommendedPick,
    RosterSlot,
    ScoringRule,
)

# The contract surface (§9.5) — must match CONTRACT_SCHEMAS in
# packages/shared/tests/parity.test.ts.
CONTRACT_MODELS = [
    Position,
    RosterSlot,
    ScoringRule,
    LeagueSettings,
    DraftPick,
    DraftState,
    DraftEvent,
    RecommendedPick,
    Recommendation,
]

# backend/src/jaaffl/domain/export.py -> repo root is parents[4].
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = REPO_ROOT / "packages" / "shared" / "schemas"


def render_all() -> dict[str, str]:
    """Deterministic name -> rendered-JSON-schema mapping (sorted keys, trailing newline)."""
    rendered: dict[str, str] = {}
    for model in CONTRACT_MODELS:
        schema = TypeAdapter(model).json_schema()
        rendered[model.__name__] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return rendered


def main(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in render_all().items():
        (out_dir / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {out_dir / (name + '.json')}")


if __name__ == "__main__":
    main()
