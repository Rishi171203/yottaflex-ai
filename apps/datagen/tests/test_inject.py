"""Injection contract tests: determinism, source invariance, gold shape."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from datagen.cli import generate_dataset
from datagen.inject import GOLD_HEADER, run_injection

SEED = 20261022


def _file_hashes(out_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(out_dir)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out_dir.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("inject")
    src = tmp / "src"
    generate_dataset(SEED, "s0", src, None, force=True)
    before = _file_hashes(src)
    dst_a, dst_b = tmp / "anom_a", tmp / "anom_b"
    summary_a = run_injection(src, dst_a)
    summary_b = run_injection(src, dst_b)
    return {"src": src, "before": before, "dst_a": dst_a,
            "dst_b": dst_b, "summary_a": summary_a, "summary_b": summary_b}


def test_injection_is_deterministic_and_leaves_src_untouched(trees):
    assert _file_hashes(trees["src"]) == trees["before"], \
        "injection must not modify the clean source tree"
    assert _file_hashes(trees["dst_a"]) == _file_hashes(trees["dst_b"])
    assert trees["summary_a"]["by_code"] == trees["summary_b"]["by_code"]


def test_gold_layout_and_label_shape(trees):
    with (trees["dst_a"] / "gold" / "ground_truth_label.csv").open(
            newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == list(GOLD_HEADER)
        rows = list(reader)
    summary = trees["summary_a"]
    assert summary["labels"] == len(rows)
    assert len({r["label_id"] for r in rows}) == len(rows), "label ids must be unique"
    assert rows and all(r["anomaly_code"].startswith("ANOM-") for r in rows)
    for row in rows:
        assert row["injected_synthetic"] == "true"
        assert isinstance(json.loads(row["related_ids"]), list)
        assert row["severity"].isdigit()
        assert row["labelled_at"]


def test_every_anomaly_injected_at_least_once(trees):
    by_code = trees["summary_a"]["by_code"]
    assert by_code and all(count >= 1 for count in by_code.values()), by_code
