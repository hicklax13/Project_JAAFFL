#!/usr/bin/env python
"""Thin shim: export the Pydantic contract schemas (see jaaffl.domain.export).

Run from anywhere with the backend venv: ``python scripts/export_schemas.py``. The
sys.path insert keeps the script runnable even without the editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from jaaffl.domain.export import main  # noqa: E402

if __name__ == "__main__":
    main()
