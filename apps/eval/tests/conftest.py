"""Test bootstrap: make the eval package and sibling apps importable."""
from __future__ import annotations

import sys
from pathlib import Path

APPS = Path(__file__).resolve().parents[2]
for entry in (APPS / "eval", APPS / "datagen", APPS / "api"):
    as_str = str(entry)
    if as_str not in sys.path:
        sys.path.insert(0, as_str)
