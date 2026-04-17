from __future__ import annotations

from pathlib import Path

import pytest

from calibration.signal_engineering import run_engineering


def test_signal_engineering_runs():
    db = Path(__file__).resolve().parents[1] / "data" / "calibration_accumulation_validation.db"
    if not db.is_file():
        pytest.skip("run accumulation harness first")
    rep = run_engineering(db)
    assert "diagnostics" in rep
    assert "FINAL_RESULT" in rep["FINAL_SYSTEM"]
    long_n = rep["diagnostics"]["pct_canonical_effective"]["long"]
    assert isinstance(long_n, int) and long_n > 0
