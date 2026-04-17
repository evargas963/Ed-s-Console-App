"""Shared per-tick LSTM/TR sequence context: parity slices and DB call deduplication."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from features.shared_sequence_context import (
    SharedSequenceContext,
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

    rows = [{"ts_utc": 1000.0 + i, "spot": 450.0} for i in range(100)]
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
