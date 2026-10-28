"""Precision / recall / F1 of detector findings against gold labels.

Keys are (anomaly_code, entity_type, entity_id): a finding matches a gold
label only when all three agree, so partial credit per family is honest.
"""
from __future__ import annotations

import csv

from app.services.domain_config import ANOMALY_CODES

(CODE_CAPACITY, CODE_SLA, CODE_HISTORY, CODE_LOOP, CODE_PRIORITY) = ANOMALY_CODES


def _zero() -> dict:
    return {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}


def _keys(rows) -> set[tuple[str, str, str]]:
    got = set()
    for row in rows:
        key = (row["anomaly_code"], row["entity_type"], row["entity_id"])
        got.add(key)
    return got


def load_gold(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [dict(r) for r in csv.DictReader(fh)]
    rows.sort(key=lambda r: (r["anomaly_code"], r["entity_id"], r["label_id"]))
    return rows


def evaluate(gold_rows: list[dict], findings: list[dict]) -> dict:
    gold_keys = _keys(gold_rows)
    finding_keys = _keys(findings)
    by_code: dict[str, dict] = {code: _zero() for code in ANOMALY_CODES}
    for code in ANOMALY_CODES:
        m = by_code[code]
        m["tp"] = len({k for k in finding_keys if k[0] == code} & {k for k in gold_keys if k[0] == code})
        m["fp"] = len({k for k in finding_keys if k[0] == code} - gold_keys)
        m["fn"] = len({k for k in gold_keys if k[0] == code} - finding_keys)
        m["precision"] = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else 0.0
        m["recall"] = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else 0.0
        m["f1"] = _f1(m["precision"], m["recall"])

    micro = _zero()
    micro["tp"] = sum(m["tp"] for m in by_code.values())
    micro["fp"] = sum(m["fp"] for m in by_code.values())
    micro["fn"] = sum(m["fn"] for m in by_code.values())
    micro["precision"] = micro["tp"] / (micro["tp"] + micro["fp"]) if micro["tp"] + micro["fp"] else 0.0
    micro["recall"] = micro["tp"] / (micro["tp"] + micro["fn"]) if micro["tp"] + micro["fn"] else 0.0
    micro["f1"] = _f1(micro["precision"], micro["recall"])

    return {
        "counts": {"gold_labels": len(gold_keys), "findings": len(finding_keys)},
        "by_code": by_code,
        "micro": micro,
    }


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean, 0.0 on empty denominators."""
    denom = precision + recall
    return 2 * precision * recall / denom if denom else 0.0


def false_positives(gold_rows: list[dict], findings: list[dict]) -> list[dict]:
    """Findings that did not match a gold label (sorted, for diagnosis)."""
    gold_keys = _keys(gold_rows)
    extra = [f for f in findings
             if (f["anomaly_code"], f["entity_type"], f["entity_id"]) not in gold_keys]
    extra.sort(key=lambda f: (f["anomaly_code"], f["entity_id"]))
    return extra


def missed_labels(gold_rows: list[dict], findings: list[dict]) -> list[dict]:
    """Gold labels with no matching finding (sorted, for diagnosis)."""
    finding_keys = _keys(findings)
    missed = [g for g in gold_rows
              if (g["anomaly_code"], g["entity_type"], g["entity_id"]) not in finding_keys]
    missed.sort(key=lambda g: (g["anomaly_code"], g["entity_id"]))
    return missed


def to_report(gold_rows: list[dict], findings: list[dict]) -> dict:
    report = evaluate(gold_rows, findings)
    report["false_positives"] = false_positives(gold_rows, findings)
    report["missed_labels"] = missed_labels(gold_rows, findings)
    return report
