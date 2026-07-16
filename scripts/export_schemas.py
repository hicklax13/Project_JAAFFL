#!/usr/bin/env python
"""Export the Pydantic contract models to JSON Schema for the E5 parity gate (plan §9.5).

Writes one ``packages/shared/schemas/<Model>.json`` per contract model (checked in).
Pydantic is the source of truth; the js side derives JSON Schema from the Zod mirrors and
structurally compares (packages/shared/tests/parity.test.ts). CI fails on a stale export
(backend/tests/test_schema_parity.py + ``git diff --exit-code``).

Run from anywhere with the backend venv: ``python scripts/export_schemas.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from pydantic import TypeAdapter  # noqa: E402

from jaaffl.domain import (  # noqa: E402
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

OUT_DIR = REPO_ROOT / "packages" / "shared" / "schemas"


def render_all() -> dict[str, str]:
    """Deterministic name -> rendered-JSON-schema mapping (sorted keys, trailing newline)."""
    rendered: dict[str, str] = {}
    for model in CONTRACT_MODELS:
        schema = TypeAdapter(model).json_schema()
        rendered[model.__name__] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return rendered


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in render_all().items():
        (OUT_DIR / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT_DIR / (name + '.json')}")


if __name__ == "__main__":
    main()
