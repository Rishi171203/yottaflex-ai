"""manifest.json emission (DATA_DICTIONARY 16.6)."""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from typing import Any

MANIFEST_VERSION = 1


def build_manifest(
    seed: int,
    scale_name: str,
    config_sha256: str,
    files: dict[str, dict[str, Any]],  # table -> {"sha256": ..., "rows": n, "schema": ...}
    n_tickets: int,
    window_start: str,
    window_end: str,
) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "seed": seed,
        "scale": {
            "name": scale_name,
            "config_sha256": config_sha256,
            "window": {"start": window_start, "end": window_end, "days": None},
            "n_tickets": n_tickets,
        },
        "generator": {
            "python": sys.version.split(" ")[0],
            "platform": platform.platform(),
        },
        "files": files,
    }


def write_manifest(path: pathlib.Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
