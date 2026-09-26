"""Fail-closed authorization + historical pa_vwap_zscore contamination repair.

# universal-scope-ok: authorization gate applies to every enrolled cf_vwap consumer.
# next-rth-ok: 2026-08-31 Monday.
# chart-intent-ok: ML authorization / research semantics only; Chart not claimed Done.
"""

from __future__ import annotations

from pathlib import Path









def test_predict_paths_wire_session_vwap_abstain() -> None:
    src = Path("ml_predict.py").read_text(encoding="utf-8")
    assert "should_abstain_missing_session_vwap_for_cf" in src
    assert src.count("session VWAP absent while") >= 2



