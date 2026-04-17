#!/usr/bin/env python3
"""Clone an existing dir head to a missing horizon path; patch meta (no RTH labels for target hz)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_horizon import directional_label_column, normalize_ml_horizon_slug


def clone(tkr: str, hz_from: str, hz_to: str) -> None:
    hz_from = normalize_ml_horizon_slug(hz_from)
    hz_to = normalize_ml_horizon_slug(hz_to)
    base = ROOT / "models" / "active" / tkr
    sp = base / f"xgb_{tkr}_{hz_from}_dir.pkl"
    tp = base / f"xgb_{tkr}_{hz_to}_dir.pkl"
    sm = base / f"xgb_{tkr}_{hz_from}_dir_meta.json"
    tm = base / f"xgb_{tkr}_{hz_to}_dir_meta.json"
    if not sp.is_file() or not sm.is_file():
        raise SystemExit(f"missing source {sp} or {sm}")
    shutil.copy2(sp, tp)
    meta = json.loads(sm.read_text(encoding="utf-8"))
    lc = directional_label_column(hz_to)
    meta["ml_horizon_slug"] = hz_to
    meta["target"] = lc
    meta["cloned_from_horizon"] = hz_from
    meta["clone_note"] = "Sibling clone: zero RTH rows with valid_dir for target horizon in snapshots_1m_normalized."
    tm.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("OK", tkr, hz_from, "->", hz_to)


def main() -> int:
    clone("TSL", "13c", "15c")
    clone("TSL", "13c", "60c")
    clone("PCG", "15c", "60c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
