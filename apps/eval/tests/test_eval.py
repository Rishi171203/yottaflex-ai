"""Eval contract tests: zero FPs on clean data, perfect recall on injected data."""
from __future__ import annotations

import json

import eval.dataset as dataset
import eval.detectors as detectors
import eval.score as score
import pytest
from datagen.cli import generate_dataset
from datagen.inject import run_injection

SEED = 20261022


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("eval")
    clean = tmp / "clean"
    generate_dataset(SEED, "s0", clean, None, force=True)
    anomalies = tmp / "anomalies"
    run_injection(clean, anomalies)
    return {"clean": clean, "anomalies": anomalies}


def test_clean_dataset_has_zero_findings(trees):
    ds = dataset.load_dataset(trees["clean"] / "ops")
    assert detectors.run_all(ds) == []


def test_injected_dataset_scores_f1_one(trees):
    ds = dataset.load_dataset(trees["anomalies"] / "ops")
    findings = detectors.run_all(ds)
    gold_rows = score.load_gold(trees["anomalies"] / "gold" / "ground_truth_label.csv")
    report = score.to_report(gold_rows, findings)

    assert report["micro"]["f1"] == 1.0, json.dumps(report["missed_labels"])
    assert report["micro"]["fp"] == 0 and report["micro"]["fn"] == 0
    for code, metrics in report["by_code"].items():
        assert metrics["fn"] == 0, (code, metrics)
    assert report["counts"]["findings"] == report["counts"]["gold_labels"]


def test_scorecard_is_deterministic(trees):
    ds = dataset.load_dataset(trees["anomalies"] / "ops")
    findings = detectors.run_all(ds)
    gold_rows = score.load_gold(trees["anomalies"] / "gold" / "ground_truth_label.csv")
    first = json.dumps(score.to_report(gold_rows, findings), sort_keys=True)
    second = json.dumps(score.to_report(gold_rows, findings), sort_keys=True)
    assert first == second


def test_score_math_on_synthetic_case():
    capacity, sla = detectors.CODE_CAPACITY, detectors.CODE_SLA
    gold_rows = [
        {"label_id": "1", "anomaly_code": capacity, "entity_type": "assignment_event",
         "entity_id": "AE1", "related_ids": "[]", "injected_synthetic": "true",
         "severity": "4", "explanation": "x", "labelled_at": "t",
         "created_at": "t", "updated_at": "t"},
        {"label_id": "2", "anomaly_code": capacity, "entity_type": "assignment_event",
         "entity_id": "AE2", "related_ids": "[]", "injected_synthetic": "true",
         "severity": "4", "explanation": "x", "labelled_at": "t",
         "created_at": "t", "updated_at": "t"},
        {"label_id": "3", "anomaly_code": sla, "entity_type": "ticket",
         "entity_id": "T1", "related_ids": "[]", "injected_synthetic": "true",
         "severity": "2", "explanation": "x", "labelled_at": "t",
         "created_at": "t", "updated_at": "t"},
    ]
    findings = [
        {"anomaly_code": capacity, "entity_type": "assignment_event", "entity_id": "AE1",
         "evidence": {}},
        {"anomaly_code": capacity, "entity_type": "assignment_event", "entity_id": "AE2",
         "evidence": {}},
        {"anomaly_code": capacity, "entity_type": "assignment_event", "entity_id": "AE3",
         "evidence": {}},
    ]
    report = score.evaluate(gold_rows, findings)
    cap = report["by_code"][capacity]
    sla_m = report["by_code"][sla]
    assert cap["tp"] == 2 and cap["fp"] == 1 and cap["fn"] == 0
    assert cap["precision"] == pytest.approx(2 / 3)
    assert cap["recall"] == 1.0 and cap["f1"] == pytest.approx(0.8)
    assert sla_m["fn"] == 1 and sla_m["f1"] == 0.0
    assert report["micro"]["tp"] == 2 and report["micro"]["fp"] == 1 \
        and report["micro"]["fn"] == 1
