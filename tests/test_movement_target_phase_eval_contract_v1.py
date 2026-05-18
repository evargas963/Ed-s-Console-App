"""Smoke tests: movement-target Phase 5/6/6.5 eval modules import and helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_phase_eval_modules_import():
    from calibration.movement_target_eval_common_v1 import binary_baselines_move, HORIZONS_MV
    from calibration import movement_target_phase5_discrimination_v1 as p5
    from calibration import movement_target_phase6_edge_v1 as p6
    from calibration import movement_target_phase65_isolation_v1 as p65
    from calibration import movement_target_phase65_cleanup_v1 as p65c

    assert len(HORIZONS_MV) == 4
    assert binary_baselines_move([1, 0, 1])["prior_majority_accuracy"] is not None
    assert callable(p5.run)
    assert callable(p6.run)
    assert callable(p65.run_phase65_movement)
    assert callable(p65c.main)


def test_run_bundle_script_exists():
    p = ROOT / "calibration" / "run_movement_target_evaluation_bundle_v1.py"
    assert p.is_file()


@pytest.mark.skipif(
    not (ROOT / "data" / "movement_target_phase5_discrimination_v1.json").is_file(),
    reason="evaluation JSON not generated in this workspace",
)
def test_phase5_json_has_label_statistics_when_present():
    data = json.loads((ROOT / "data" / "movement_target_phase5_discrimination_v1.json").read_text(encoding="utf-8"))
    hz = data.get("horizons", {}).get("5c", {})
    assert "label_statistics" in hz or hz == {}


def test_json_no_invalid_nan_literals_in_phase6_sample():
    p = ROOT / "data" / "movement_target_phase6_edge_v1.json"
    if not p.is_file():
        pytest.skip("phase6 json missing")
    raw = p.read_text(encoding="utf-8")
    assert "NaN" not in raw
