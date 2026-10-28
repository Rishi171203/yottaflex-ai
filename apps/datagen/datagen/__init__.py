"""Datagen package: deterministic synthetic dataset generator + anomaly injection.

Layout:

    apps/datagen/datagen/
        cli.py         python -m datagen --seed <n> --scale s0 --out <dir> [--force]
        inject.py      python -m datagen.inject --src <clean> --dst <anomaly dir>

Import side effects: puts ``apps/api`` on sys.path so the generators reuse the
shared SLA_POLICY_MATRIX / ANOMALY_CODES from the API app.
"""
from __future__ import annotations

import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[2] / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))
