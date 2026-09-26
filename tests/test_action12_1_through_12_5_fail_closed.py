"""Actions 12.1–12.5 + 11.1d: fail-closed fixes in prediction/MH/vol/rules/news paths."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


























def test_prediction_engine_no_fusion_prob_one_third_default():
    text = (ROOT / "prediction_engine.py").read_text(encoding="utf-8")
    assert 'getattr(snap, "prob_up", 1.0 / 3.0)' not in text
    assert "0.33" not in text
    assert "0.34" not in text
