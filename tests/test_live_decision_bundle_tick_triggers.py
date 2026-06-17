"""live_decision_bundle coherence triggers fail-closed on check errors (SWEEP-EP-4)."""

from __future__ import annotations

from unittest.mock import patch

from live_decision_bundle import tick_triggers_coherent_refresh


def _base_ms() -> dict:
    return {
        "spot": 100.0,
        "zone": "pin_bull",
        "bias_signal": "bull",
        "net_delta": 1.0,
        "session_label": "RTH",
        "decision_timestamp_utc": 1_700_000_000.0,
        "vwap": 99.5,
        "vwap_side": "above",
        "nearest_above_name": "wall_a",
        "nearest_below_name": "wall_b",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 2.0,
    }


def test_tick_triggers_fail_closed_when_zone_check_raises():
    ms = _base_ms()
    with patch("market_state.derive_zone", side_effect=RuntimeError("zone")):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True


def test_tick_triggers_fail_closed_when_session_label_check_raises():
    ms = _base_ms()
    with patch(
        "live_decision_bundle._live_session_label",
        side_effect=RuntimeError("session_label"),
    ):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True


def test_tick_triggers_fail_closed_when_session_bucket_check_raises():
    ms = _base_ms()
    with patch(
        "live_decision_bundle._session_bucket_from_utc_ts",
        side_effect=RuntimeError("session_bucket"),
    ):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True


def test_tick_triggers_fail_closed_when_vwap_side_check_raises():
    ms = _base_ms()
    with patch(
        "math_snapshot_derive.derive_vwap_side",
        side_effect=RuntimeError("vwap_side"),
    ):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True


def test_tick_triggers_fail_closed_when_nearest_wall_check_raises():
    ms = _base_ms()
    with patch(
        "live_decision_bundle.recompute_nearest_struct_at_spot",
        side_effect=RuntimeError("nearest_wall"),
    ):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True


def test_tick_triggers_fail_closed_when_derive_session_raises_internally():
    """Production failure mode regression: _derive_session raising inside
    _live_session_label must propagate to the caller's outer try/except so
    refresh is triggered (not silently skipped via the wrapper swallowing).

    Before the fix, _live_session_label caught Exception and returned None;
    caller then skipped the session-label check on any market_context outage,
    diverging from the file's fail-closed-toward-refresh discipline.
    """
    ms = _base_ms()
    with patch("market_context._derive_session", side_effect=RuntimeError("derive_session")):
        assert tick_triggers_coherent_refresh(ms, stream_spot=100.0, stream_of_regime=None) is True
