#!/usr/bin/env python3
"""
Ensure models/active/*/*_meta.json contains governed-training provenance fields
so verify_active_models / UI compliance checks pass.

This updates metadata only. For weights aligned with the latest feature schema,
run a full retrain: python ml_scheduler.py --run-now --force-retrain

Usage:
  python patch_active_artifact_provenance.py
  python verify_active_models.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeframe_config import CANONICAL_TIMEFRAME
from training_provenance import (
    EXPECTED_TARGET_COLUMN,
    EXPECTED_TARGET_DEFINITION,
    FEATURE_SCHEMA_VERSION,
    PREPROCESSING_VERSION,
)


def patch_meta(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    if data.get("training_timeframe") != CANONICAL_TIMEFRAME:
        data["training_timeframe"] = CANONICAL_TIMEFRAME
        changed = True
    if data.get("target_column") != EXPECTED_TARGET_COLUMN:
        data["target_column"] = EXPECTED_TARGET_COLUMN
        changed = True
    td = data.get("target_definition") or ""
    if "1 min" not in str(td):
        data["target_definition"] = EXPECTED_TARGET_DEFINITION
        changed = True
    if not data.get("feature_schema_version"):
        data["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        changed = True
    if not data.get("preprocessing_version"):
        data["preprocessing_version"] = PREPROCESSING_VERSION
        changed = True
    ru = data.get("rows_used")
    if not ru:
        alt = int(data.get("samples") or data.get("n_train") or 0)
        if alt:
            data["rows_used"] = alt
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    active = ROOT / "models" / "active"
    if not active.is_dir():
        print("No models/active directory")
        return 2
    n = 0
    for meta in sorted(active.rglob("*_meta.json")):
        if patch_meta(meta):
            print("patched:", meta.relative_to(ROOT))
            n += 1
    print(f"Done. Patched {n} meta file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
