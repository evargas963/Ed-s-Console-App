"""Edge metrics harness: deterministic stub data must not auto-pass strict directional-alpha gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from calibration.edge_validation import analyze_edge


def test_edge_validation_stub_fails_strict_alpha_same_as_always_long(tmp_path: Path) -> None:
    """CI stub: dominant canonical class ties to 'up' → effective signal equals always-long; strict EV gate fails."""
    db = Path(__file__).resolve().parents[1] / "data" / "calibration_accumulation_validation.db"
    if not db.is_file():
        pytest.skip("run python -m calibration.run_production_accumulation_validation first")
    rep = analyze_edge(db)
    assert rep["pass_gates"]["aggregate_n_sufficient"] is True
    assert rep["pass_gates"]["ev_mean_actual_gt_mean_random_mix"] is True
    assert rep["pass_gates"]["ev_mean_actual_strictly_gt_always_long"] is False
    assert rep["binary_pass"] is False
