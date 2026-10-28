"""CLI: python -m eval --ops <dir> --gold <csv> [--out <json>].

Reads ops CSVs, runs the five detectors, scores findings against gold
labels and writes a JSON scorecard (defaults to stdout when --out is
omitted). Exit code is 0 even when F1 is low (it is a measurement, not a
test); use the tests for pass/fail semantics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import dataset, detectors, score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__.splitlines()[0])
    parser.add_argument("--ops", required=True, type=Path, help="ops dir holding the CSV extracts")
    parser.add_argument("--gold", required=True, type=Path, help="gold ground_truth_label.csv")
    parser.add_argument("--out", type=Path, default=None, help="write scorecard JSON here (optional)")
    args = parser.parse_args(argv)

    ds = dataset.load_dataset(args.ops)
    findings = detectors.run_all(ds)
    gold_rows = score.load_gold(args.gold)
    report = score.to_report(gold_rows, findings)

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    micro = report["micro"]
    print(f"findings={report['counts']['findings']} gold={report['counts']['gold_labels']} "
          f"precision={micro['precision']:.3f} recall={micro['recall']:.3f} f1={micro['f1']:.3f}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
