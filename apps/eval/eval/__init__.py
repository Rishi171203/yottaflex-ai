"""Evaluation package: anomaly detectors + precision/recall/F1 scorecard.

Layout:

    apps/eval/eval/
        dataset.py    CSV loaders for ops tables
        detectors.py  five independent ANOM-* predicates (ops data only)
        score.py      gold-labelled precision / recall / F1
        __main__.py   python -m eval --ops <dir> --gold <csv> --out <json>

Import side effects: puts ``apps/datagen`` and ``apps/api`` on sys.path so the
SLA recomputation reuses the generator's exact math and the shared
SLA_POLICY_MATRIX / ANOMALY_CODES from the API app.
"""
from __future__ import annotations

import sys
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2]
for _p in (_APPS / "api", _APPS / "datagen"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
