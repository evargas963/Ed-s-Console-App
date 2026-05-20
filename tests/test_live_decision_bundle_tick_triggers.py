"""live_decision_bundle coherence triggers fail-closed on check errors."""

from __future__ import annotations

from unittest.mock import patch

from live_decision_bundle import tick_triggers_coherent_refresh


def test_tick_triggers_fail_closed_when_zone_check_raises():
    ms = {
        "spot": 100.0,
        "zone": "pin_bull",
        "bias_signal": "bull",
        "net_delta": 1.0,
        "session_label": "RTH",
        "decision_timestamp_utc": 1_700_000_000.0,
    }
    with patch("market_state.derive_zone", side_effect=RuntimeError("boom")):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True
