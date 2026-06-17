"""resample_to_1m must skip minute buckets with missing OHLC — never fabricate zeros."""

from __future__ import annotations

from snapshot_normalizer import resample_to_1m

_TS = 1_710_000_060.0


def _row(**kwargs: object) -> dict:
    base = {"ts_utc": _TS, "ticker": "SPY"}
    base.update(kwargs)
    return base


def test_omits_bucket_when_open_and_spot_missing():
    rows = [
        _row(
            candle_open=None,
            spot=None,
            candle_high=10,
            candle_low=9,
            candle_close=9.5,
        )
    ]
    assert resample_to_1m(rows, "SPY") == []


def test_omits_bucket_when_high_low_missing():
    rows = [
        _row(
            candle_open=100,
            candle_high=None,
            candle_low=None,
            spot=None,
        )
    ]
    assert resample_to_1m(rows, "SPY") == []


def test_keeps_bucket_when_all_ohlc_present():
    rows = [
        _row(
            candle_open=100,
            candle_high=101,
            candle_low=99,
            candle_close=100.5,
            spot=100.5,
        )
    ]
    out = resample_to_1m(rows, "SPY")
    assert len(out) == 1
    row = out[0]
    assert row["candle_open"] == 100
    assert row["candle_high"] == 101
    assert row["candle_low"] == 99
    assert row["candle_close"] == 100.5
    assert row["spot"] == 100.5


def test_close_falls_back_to_spot_when_close_missing():
    rows = [
        _row(
            candle_open=100,
            candle_high=101,
            candle_low=99,
            candle_close=None,
            spot=100.5,
        )
    ]
    out = resample_to_1m(rows, "SPY")
    assert len(out) == 1
    assert out[0]["candle_close"] == 100.5
    assert out[0]["spot"] == 100.5


def test_omits_bucket_when_open_would_be_fabricated_from_zero_spot():
    """Regression: parent f25cec4 accepted spot=0.0 as open proxy."""
    rows = [
        _row(
            candle_open=None,
            spot=0.0,
            candle_high=10,
            candle_low=9,
            candle_close=9.5,
        )
    ]
    assert resample_to_1m(rows, "SPY") == []
