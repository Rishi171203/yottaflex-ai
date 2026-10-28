"""Generation contract tests: determinism, manifest, overwrite guard."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from datagen.cli import generate_dataset
from datagen.config import ScaleConfigError, load_scale_config

SEED = 20261022


def _file_hashes(out_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(out_dir)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out_dir.rglob("*"))
        if p.is_file() and p.name != "_manifest_compare.txt"
    }


@pytest.fixture(scope="module")
def s0_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("s0_run")
    generate_dataset(SEED, "s0", out, None, force=True)
    return out


def test_two_runs_byte_identical(s0_dir: Path, tmp_path: Path) -> None:
    out2 = tmp_path / "s0_again"
    generate_dataset(SEED, "s0", out2, None, force=True)
    first, second = _file_hashes(s0_dir), _file_hashes(out2)
    assert first.keys() == second.keys()
    assert first == second


def test_manifest_shape(s0_dir: Path) -> None:
    manifest = json.loads((s0_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == SEED
    assert manifest["scale"]["name"] == "s0"
    assert manifest["scale"]["n_tickets"] == 50
    assert manifest["scale"]["window"]["end"] and manifest["scale"]["window"]["start"]
    assert manifest["files"]["ticket"]["rows"] == 50
    assert manifest["files"]["message"]["rows"] > 0
    for name, entry in manifest["files"].items():
        assert entry["schema"] in {"", "ops", "gold"}
        assert len(entry["sha256"]) == 64
        actual = hashlib.sha256(
            (s0_dir / entry["schema"] / f"{name}.csv").read_bytes()
        ).hexdigest()
        if entry["schema"]:
            assert entry["sha256"] == actual, name


def test_generated_csvs_match_manifest_counts(s0_dir: Path) -> None:
    manifest = json.loads((s0_dir / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        path = s0_dir / entry["schema"] / f"{name}.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert len(rows) - 1 == entry["rows"], name


def test_refuses_overwrite_without_force(s0_dir: Path) -> None:
    with pytest.raises(SystemExit):
        generate_dataset(SEED, "s0", s0_dir, None, force=False)


def test_unknown_preset_raises() -> None:
    with pytest.raises(ScaleConfigError, match="unknown scale preset"):
        load_scale_config("does_not_exist", SEED)
