"""Action 11.12: regime_engine fail-closed on zero evidence and missing zone bars."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGIME_ENGINE = (ROOT / "regime_engine.py").read_text(encoding="utf-8")






def test_regime_engine_no_zone_since_bars_or_zero_pattern():
    assert "(inp.zone_since_bars_1m or inp.zone_since_bars) or 0" not in REGIME_ENGINE




