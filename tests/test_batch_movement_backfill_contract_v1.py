"""Contract tests for batch movement backfill helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_batch_backfill_module_loads():
    p = ROOT / "tools" / "batch_backfill_movement_predictions_v1.py"
    spec = importlib.util.spec_from_file_location("batch_backfill_movement_predictions_v1", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod._sanitize_snapshot_dict_for_mvp)
    d = {"spread": -0.01, "ticker": "SPY"}
    out = mod._sanitize_snapshot_dict_for_mvp(d)
    assert float(out["spread"]) >= 0


def test_validate_script_exists():
    assert (ROOT / "tools" / "validate_movement_prediction_coverage_v1.py").is_file()
