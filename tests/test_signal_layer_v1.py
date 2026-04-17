"""signal_layer_v1: leakage bounds + synthetic predictive sanity."""

from __future__ import annotations

import math

import pytest

from features.signal_layer_v1 import (
    compute_signal_layer_v1,
    flatten_numeric_features,
    load_bars_before_decision,
)


def _synth_bars(n: int, t0: float = 1_000_000.0) -> list[dict]:
    bars = []
    for k in range(n):
        be = t0 + float(k + 1) * 60.0
        bs = be - 60.0
        c = 100.0 + 0.02 * float(k) + 0.15 * math.sin(k * 0.05)
        o = c - 0.01
        h = c + 0.05
        l_ = c - 0.05
        bars.append(
            {
                "bar_start_ts_utc": bs,
                "bar_end_ts_utc": be,
                "open": o,
                "high": h,
                "low": l_,
                "close": c,
                "volume": 1e6 + float(k) * 100.0,
            }
        )
    return bars


def test_no_future_bar_in_window() -> None:
    """Features at decision_ts must not use bars ending after decision_ts."""
    bars = _synth_bars(80)
    decision_ts = bars[50]["bar_end_ts_utc"]
    layer = compute_signal_layer_v1(bars[:51], decision_ts_utc=float(decision_ts), inp=None)
    assert int(layer["meta.n_bars"]) == 51
    assert layer["meta.bar_end_last"] == pytest.approx(float(bars[50]["bar_end_ts_utc"]))


def test_load_bars_respects_end_filter() -> None:
    """SQLite path: only bar_end_ts_utc <= decision."""
    import sqlite3

    from db import configure_sqlite_connection

    conn = sqlite3.connect(":memory:")
    configure_sqlite_connection(conn)
    conn.execute(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL NOT NULL,
            volume REAL,
            source TEXT DEFAULT 'test',
            PRIMARY KEY (ticker, bar_start_ts_utc)
        )
        """
    )
    tkr = "SPY"
    for k in range(30):
        be = 2_000_000.0 + k * 60.0
        bs = be - 60.0
        conn.execute(
            """
            INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume)
            VALUES (?, ?, ?, 100, 101, 99, 100, 1e6)
            """,
            (tkr, bs, be),
        )
    conn.commit()
    cut = 2_000_000.0 + 20 * 60.0
    rows = load_bars_before_decision(conn, tkr, cut, max_bars=200)
    conn.close()
    assert all(float(r["bar_end_ts_utc"]) <= cut for r in rows)
    assert len(rows) == 21


def test_synthetic_trend_slope_detectable() -> None:
    """Upward drift → positive log slope (sanity)."""
    bars = _synth_bars(120)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    sl = layer.get("ps.rolling_trend_slope_log20")
    assert sl is not None and float(sl) > 0.0


def test_flatten_numeric_strips_meta() -> None:
    layer = {"meta.n_bars": 3, "ps.rolling_trend_slope_log20": 0.01}
    f = flatten_numeric_features(layer)
    assert "meta.n_bars" not in f
    assert "ps.rolling_trend_slope_log20" in f