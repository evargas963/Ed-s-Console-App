#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_contract_validation import validate_feature_contracts


def main() -> int:
    report = validate_feature_contracts(ROOT)
    print("=" * 72)
    print("FEATURE CONTRACT VALIDATION")
    print("=" * 72)
    print(f"PASS: {report.passed}")
    print("Layer checks:")
    for k, v in sorted(report.layer_results.items()):
        print(f"  - {k}: {'PASS' if v else 'FAIL'}")
    if report.failures:
        print("\nFailures:")
        for f in report.failures:
            print(f"  - {f}")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")
    print("\nDetails JSON:")
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
