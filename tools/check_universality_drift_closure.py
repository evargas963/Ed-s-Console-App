#!/usr/bin/env python3
"""Mechanical lock — universality drift closure proof on CI triage matrix rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

TRIAGE_JSON = "reports/ci/ci_nonblocking_failure_triage_2026-06-18.json"


def check_universality_drift_closure() -> list[str]:
    from verification.universality_drift_closure import validate_triage_universality_closure

    path = _REPO / TRIAGE_JSON
    if not path.is_file():
        return [f"universality_drift: missing {TRIAGE_JSON}"]
    try:
        triage = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"universality_drift: invalid JSON in {TRIAGE_JSON}: {exc}"]
    if int(triage.get("schema_version") or 0) < 6:
        return [
            f"universality_drift: {TRIAGE_JSON} schema_version must be >= 6 "
            f"(got {triage.get('schema_version')!r})"
        ]
    return [f"universality_drift: {e}" for e in validate_triage_universality_closure(triage)]


def main() -> int:
    errors = check_universality_drift_closure()
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print("check_universality_drift_closure: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
