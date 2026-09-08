"""Smoke: edge discovery runs on accumulation DB when present."""

from __future__ import annotations

from pathlib import Path

import pytest

from calibration.edge_discovery import run_discovery


def test_edge_discovery_runs_on_accumulation_db():
    db = Path(__file__).resolve().parents[1] / "data" / "calibration_accumulation_validation.db"
    if not db.is_file():
        pytest.skip("run python -m calibration.run_production_accumulation_validation first")
    rep = run_discovery(db)
    assert rep["meta"]["labeled_anchored_count"] >= 30
    assert len(rep["slices_all"]) > 0
    assert "FINAL_SYSTEM_EDGE" in rep["system_level"]
