"""Shared per-tick LSTM/TR sequence context: parity slices and DB call deduplication."""

from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path

import pytest

from features.shared_sequence_context import (
    SharedSequenceContext,
    _max_transformer_seq_len_for_ticker,
    build_shared_sequence_context,
    transformer_window_chronological,
)


def test_chronological_window_unified_matches_independent_fetches():
    """Last 60 of full chron equals last 60 of chron from a 65-row fetch (newest-first DB order)."""
    rows_desc = [{"ts_utc": 3000.0 - i, "spot": 100.0} for i in range(100)]
    chron = list(reversed(rows_desc))
    w_unified = chron[-60:]

    rows65 = rows_desc[:65]
    chron65 = list(reversed(rows65))
    w_legacy = chron65[-60:]

    assert w_unified == w_legacy
    assert len(w_unified) == 60


def test_transformer_window_nested_slices_horizon_isolation():
    """Different seq_len takes disjoint-length tails; no cross-horizon tensor sharing."""
    ch = tuple({"ts_utc": float(i)} for i in range(50))
    ctx = SharedSequenceContext(
        as_of_ts=99.0,
        chron_snapshots=ch,
        lstm_merged_window=(),
        lstm_merged_days=(),
        n_fetch=50,
        meta={},
    )
    w10 = transformer_window_chronological(ctx, 10)
    w5 = transformer_window_chronological(ctx, 5)
    assert len(w10) == 10
    assert len(w5) == 5
    assert w5 == w10[-5:]


def test_build_shared_sequence_context_single_db_fetch(monkeypatch):
    """Builder issues exactly one get_recent_snapshots for the tick (merge stubbed)."""
    from unittest.mock import patch

    from features import shared_sequence_context as ssc

    def _fake_max_seq(_t: str) -> int:
        return 20

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", _fake_max_seq)

    rows = [{"ts_utc": 2000.0 - i, "spot": 450.0} for i in range(100)]
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows

    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    inf = _minimal_inf_v1()
    mw = [{"ts_utc": float(i), "x": 1} for i in range(60)]
    md = [{"ts_utc": float(i), "y": 1} for i in range(100)]
    with patch(
        "features.lstm_sequence_input.build_lstm_merged_windows",
        return_value=(mw, md),
    ):
        ctx, err = ssc.build_shared_sequence_context(db, "SPY", inf)

    assert err is None
    assert ctx is not None
    assert db.get_recent_snapshots.call_count == 1


def test_build_shared_sequence_context_insufficient_returns_none():
    from features.shared_sequence_context import build_shared_sequence_context

    db = MagicMock()
    db.get_recent_snapshots.return_value = [{"ts_utc": 1.0}] * 5
    inf = {"as_of_ts": 10.0, "features": {}}
    ctx, err = build_shared_sequence_context(db, "SPY", inf)
    assert ctx is None
    assert err is not None


def test_max_transformer_seq_len_rejects_empty_ticker():
    with pytest.raises(ValueError, match="ticker is required"):
        _max_transformer_seq_len_for_ticker("")
    with pytest.raises(ValueError, match="ticker is required"):
        _max_transformer_seq_len_for_ticker("   ")


def test_build_shared_sequence_context_rejects_empty_ticker():
    db = MagicMock()
    with pytest.raises(ValueError, match="ticker is required"):
        build_shared_sequence_context(db, "", {"as_of_ts": 10.0, "features": {}})


def test_max_transformer_seq_len_warns_on_corrupt_meta(monkeypatch, tmp_path, caplog):
    """Corrupt meta must not silently pretend seq_len was read; valid horizon still wins."""
    from features import shared_sequence_context as ssc
    import ml_predict

    one_c_dir = tmp_path / "active_1c" / "SPY"
    one_c_dir.mkdir(parents=True)
    (one_c_dir / "transformer_SPY_1c_meta.json").write_text('{"seq_len": 48}', encoding="utf-8")
    bad_dir = tmp_path / "active_5c" / "SPY"
    bad_dir.mkdir(parents=True)
    (bad_dir / "transformer_SPY_5c_meta.json").write_text("not-json", encoding="utf-8")

    monkeypatch.setattr(ssc, "ALL_GOVERNED_HORIZONS", ("1c", "5c"))

    def _fake_model_dir(ticker: str) -> Path:
        hz = ml_predict.get_ml_infer_horizon_slug()
        return tmp_path / f"active_{hz}" / ticker

    monkeypatch.setattr(ml_predict, "_model_dir_for_ticker", _fake_model_dir)

    with caplog.at_level("WARNING"):
        assert _max_transformer_seq_len_for_ticker("SPY") == 48
    assert any("JSON corrupt" in r.message or "corrupt" in r.message.lower() for r in caplog.records)


def test_build_shared_sequence_context_rejects_missing_ts_utc_first_bound(monkeypatch):
    from unittest.mock import patch

    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    rows = [{"ts_utc": 2000.0 - i, "spot": 450.0} for i in range(100)]
    rows[99]["ts_utc"] = None
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    mw = [{"ts_utc": float(i)} for i in range(60)]
    md = [{"ts_utc": float(i)} for i in range(100)]
    with patch(
        "features.lstm_sequence_input.build_lstm_merged_windows",
        return_value=(mw, md),
    ):
        ctx, err = ssc.build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert ctx is None
    assert err == "snapshot_ts_utc_missing"


def test_build_shared_sequence_context_rejects_missing_ts_utc_last_bound(monkeypatch):
    from unittest.mock import patch

    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    rows = [{"ts_utc": 2000.0 - i, "spot": 450.0} for i in range(100)]
    rows[0]["ts_utc"] = None
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    mw = [{"ts_utc": float(i)} for i in range(60)]
    md = [{"ts_utc": float(i)} for i in range(100)]
    with patch(
        "features.lstm_sequence_input.build_lstm_merged_windows",
        return_value=(mw, md),
    ):
        ctx, err = ssc.build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert ctx is None
    assert err == "snapshot_ts_utc_missing"


def test_build_shared_sequence_context_rejects_non_chronological_rows(monkeypatch):
    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    rows = [{"ts_utc": 1000.0 + i, "spot": 1.0} for i in range(100)]
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    ctx, err = build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert ctx is None
    assert err == "snapshot_order_not_chronological"


def test_max_transformer_seq_len_skips_missing_secondary_active_bundle(monkeypatch, tmp_path):
    """Missing diagnostics-only active bundles must not abort shared-context fallback."""
    from features import shared_sequence_context as ssc
    import ml_predict

    one_c_dir = tmp_path / "active_1c" / "SPY"
    one_c_dir.mkdir(parents=True)
    (one_c_dir / "transformer_SPY_1c_meta.json").write_text('{"seq_len": 48}', encoding="utf-8")

    monkeypatch.setattr(ssc, "ALL_GOVERNED_HORIZONS", ("1c", "5c"))

    def _fake_model_dir(ticker: str) -> Path:
        hz = ml_predict.get_ml_infer_horizon_slug()
        if hz == "5c":
            raise FileNotFoundError("no active 5c bundle")
        return one_c_dir

    monkeypatch.setattr(ml_predict, "_model_dir_for_ticker", _fake_model_dir)

    assert ssc._max_transformer_seq_len_for_ticker("SPY") == 48
