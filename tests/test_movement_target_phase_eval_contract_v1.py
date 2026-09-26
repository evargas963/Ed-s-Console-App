"""Smoke tests: movement-target Phase 5/6/6.5 eval modules import and helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
