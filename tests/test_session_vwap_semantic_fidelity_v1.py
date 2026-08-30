"""Session VWAP semantic fidelity — collision close, warning class, RTH availability.

# universal-scope-ok: hermetic multi-ticker proof over CORE_TICKERS; not a live Chart claim.
# next-rth-ok: 2026-08-31 Monday (computed: next RTH after 2026-08-29 Saturday).
# chart-intent-ok: Collect/feature semantics only; Chart yellow/GEX bars not claimed Done.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from features.signal_layer_v1 import compute_signal_layer_v1
from liquidity_value_engine import (
    SESSION_VWAP_EXPECTED_ABSENT,
    SESSION_VWAP_PRESENT,
    SESSION_VWAP_RTH_PRODUCER_FAILURE,
    classify_session_vwap_presence,
    compute_session_vwap,
    count_session_rth_positive_volume_bars,
)
from lstm_data import compute_confluence_features
from time_et import ET, RTH_START_MINS, is_trading_day_et

# Standing enrolled core (server.CORE_TICKERS). Logging-universe extras need a live DB.
CORE_TICKERS = (
    "SPY", "QQQ", "IWM",
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA",
    "GOOGL", "AVGO",
)

FRIDAY = date(2026, 8, 28)
SATURDAY = date(2026, 8, 29)


def _rth_bar(session: date, minutes_after_open: int, close: float, volume: float = 1_000.0) -> dict:
    mins = int(RTH_START_MINS) + minutes_after_open
    dt = datetime(session.year, session.month, session.day, mins // 60, mins % 60, tzinfo=ET)
    return {
        "timestamp": int(dt.timestamp() * 1000),
        "_ts": dt.timestamp(),
        "open": close - 0.05,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
        "volume": volume,
        "bar_start_ts_utc": dt.timestamp() - 60.0,
        "bar_end_ts_utc": dt.timestamp(),
    }


def test_friday_is_trading_day_saturday_is_not() -> None:
    assert is_trading_day_et(FRIDAY.isoformat()) is True
    assert is_trading_day_et(SATURDAY.isoformat()) is False


def test_missing_session_vwap_does_not_occupy_session_slots() -> None:
    bars = [_rth_bar(FRIDAY, i, 100.0 + 0.01 * i) for i in range(80)]
    layer = compute_signal_layer_v1(
        bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"]), inp=None,
    )
    assert layer["meta.vwap_source"] is None
    assert layer["vl.price_vs_vwap_pct"] is None
    assert layer["vl.vwap_distance_pts"] is None
    assert layer["vl.vwap_zscore"] is None
    assert layer["vl.dist_to_vwap_band_upper_pts"] is None
    assert layer["vl.dist_to_vwap_band_lower_pts"] is None


def test_session_vwap_present_fills_session_slots() -> None:
    bars = [_rth_bar(FRIDAY, i, 100.0 + 0.01 * i) for i in range(80)]
    layer = compute_signal_layer_v1(
        bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"]),
        inp=SimpleNamespace(vwap=100.40),
    )
    assert layer["meta.vwap_source"] == "session"
    assert layer["vl.price_vs_vwap_pct"] is not None
    assert abs(float(layer["vl.vwap_distance_pts"]) - (100.79 - 100.40)) < 1e-6


def test_pa_vwap_zscore_source_is_session_only() -> None:
    from features.signal_layer_v1 import SNAPSHOT_PRICE_ACTION_COLUMNS, compute_price_action_snapshot_columns

    assert ("pa_vwap_zscore", "vl.vwap_zscore") in SNAPSHOT_PRICE_ACTION_COLUMNS
    bars = [_rth_bar(FRIDAY, i, 100.0 + 0.01 * i) for i in range(80)]
    absent = compute_price_action_snapshot_columns(
        bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"]), inp=None,
    )
    assert absent["pa_vwap_zscore"] is None
    present = compute_price_action_snapshot_columns(
        bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"]),
        inp=SimpleNamespace(vwap=100.40),
    )
    assert present["pa_vwap_zscore"] is not None


def test_classify_weekend_and_premarket_expected_absent() -> None:
    sat_noon = datetime(2026, 8, 29, 12, 0, tzinfo=ET)
    assert classify_session_vwap_presence(
        vwap=None, session_date=SATURDAY, now_et_dt=sat_noon,
        session_rth_positive_volume_bars=0,
    ) == SESSION_VWAP_EXPECTED_ABSENT

    premarket = datetime(2026, 8, 28, 8, 0, tzinfo=ET)
    assert classify_session_vwap_presence(
        vwap=None, session_date=FRIDAY, now_et_dt=premarket,
        session_rth_positive_volume_bars=0,
    ) == SESSION_VWAP_EXPECTED_ABSENT


def test_classify_rth_producer_failure_vs_present() -> None:
    rth = datetime(2026, 8, 28, 10, 15, tzinfo=ET)
    assert classify_session_vwap_presence(
        vwap=None, session_date=FRIDAY, now_et_dt=rth,
        session_rth_positive_volume_bars=12,
    ) == SESSION_VWAP_RTH_PRODUCER_FAILURE
    assert classify_session_vwap_presence(
        vwap=501.25, session_date=FRIDAY, now_et_dt=rth,
        session_rth_positive_volume_bars=12,
    ) == SESSION_VWAP_PRESENT


def test_prior_rth_tape_on_non_trading_day_is_not_current_session_volume() -> None:
    friday_bars = [_rth_bar(FRIDAY, i, 500.0) for i in range(30)]
    assert count_session_rth_positive_volume_bars(friday_bars, SATURDAY) == 0
    assert compute_session_vwap(friday_bars, SATURDAY) is None
    sat_noon = datetime(2026, 8, 29, 12, 0, tzinfo=ET)
    assert classify_session_vwap_presence(
        vwap=None, session_date=SATURDAY, now_et_dt=sat_noon,
        session_rth_positive_volume_bars=count_session_rth_positive_volume_bars(friday_bars, SATURDAY),
    ) == SESSION_VWAP_EXPECTED_ABSENT


def test_first_positive_volume_rth_bar_produces_session_vwap_all_core_tickers() -> None:
    """After the first valid +volume RTH bar, canonical session VWAP exists — all CORE_TICKERS."""
    assert len(CORE_TICKERS) == 11
    for ticker in CORE_TICKERS:
        bars = [_rth_bar(FRIDAY, 0, 100.0 + float(abs(hash(ticker)) % 50), volume=2_500.0)]
        vwap = compute_session_vwap(bars, FRIDAY)
        assert vwap is not None, f"{ticker}: VWAP absent after first +volume RTH bar"
        assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 1


def test_zero_volume_rth_bar_does_not_create_session_vwap() -> None:
    bars = [_rth_bar(FRIDAY, 0, 100.0, volume=0.0)]
    assert compute_session_vwap(bars, FRIDAY) is None
    assert count_session_rth_positive_volume_bars(bars, FRIDAY) == 0


def test_lstm_cf_vwap_still_encodes_absence_as_zero_requires_retrain() -> None:
    """Active LSTM contract: missing session VWAP and true zero distance are both 0.0."""
    ts = datetime(2026, 8, 28, 10, 0, tzinfo=ET).timestamp()
    absent = compute_confluence_features(
        [{"ts_utc": ts, "spot": 500.0, "vwap": None}], 0,
    )
    at_vwap = compute_confluence_features(
        [{"ts_utc": ts, "spot": 500.0, "vwap": 500.0}], 0,
    )
    assert absent["cf_vwap_distance_pct"] == 0.0
    assert at_vwap["cf_vwap_distance_pct"] == 0.0
    assert absent["cf_vwap_distance_pct"] == at_vwap["cf_vwap_distance_pct"]


def test_next_rth_after_saturday_2026_08_29_is_monday_2026_08_31() -> None:
    d = SATURDAY + timedelta(days=1)
    while not is_trading_day_et(d.isoformat()):
        d += timedelta(days=1)
    assert d == date(2026, 8, 31)
    assert d.strftime("%A") == "Monday"
