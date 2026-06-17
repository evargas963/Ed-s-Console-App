"""Layer 5 shared_sequence_context chunk-1: gap-fill contract locks (11/11 features sweep)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from features.shared_sequence_context import (
    SharedSequenceContext,
    _require_ticker,
    build_shared_sequence_context,
    transformer_window_chronological,
)
from features.lstm_sequence_input import TransformerSequenceInputError


def test_require_ticker_strips_and_uppercases():
    assert _require_ticker("  spy  ") == "SPY"


def test_transformer_window_raises_when_insufficient_chron():
    ctx = SharedSequenceContext(
        as_of_ts=1.0,
        chron_snapshots=({"ts_utc": 1.0}, {"ts_utc": 2.0}),
        lstm_merged_window=(),
        lstm_merged_days=(),
        n_fetch=2,
        meta={},
    )
    with pytest.raises(TransformerSequenceInputError, match="at least 5 snapshots"):
        transformer_window_chronological(ctx, 5)


def test_build_missing_as_of_ts_returns_error_tuple():
    db = MagicMock()
    ctx, err = build_shared_sequence_context(db, "SPY", {"features": {}})
    assert ctx is None
    assert err is not None
    assert "as_of_ts" in err.lower()


def test_build_db_fetch_exception_returns_none(monkeypatch):
    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    db = MagicMock()
    db.get_recent_snapshots.side_effect = RuntimeError("db down")
    ctx, err = build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert ctx is None
    assert err is not None
    assert "get_recent_snapshots_failed" in err


def test_build_non_comparable_ts_returns_error(monkeypatch):
    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    rows = [{"ts_utc": "bad", "spot": 1.0} for _ in range(100)]
    rows[-1]["ts_utc"] = 2000.0
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    ctx, err = build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert ctx is None
    assert err == "snapshot_ts_utc_not_comparable"


def test_build_success_populates_meta(monkeypatch):
    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 24)
    rows = [{"ts_utc": 3000.0 - i, "spot": 450.0} for i in range(100)]
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    mw = [{"ts_utc": float(i)} for i in range(60)]
    md = [{"ts_utc": float(i)} for i in range(80)]
    with patch(
        "features.lstm_sequence_input.build_lstm_merged_windows",
        return_value=(mw, md),
    ):
        ctx, err = build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert err is None
    assert ctx is not None
    assert ctx.meta["max_transformer_seq_len_scanned"] == 24
    assert ctx.meta["chron_row_count"] == 100
    assert len(ctx.lstm_merged_window) == 60


def test_shared_sequence_context_dataclass_is_immutable():
    ctx = SharedSequenceContext(
        as_of_ts=1.0,
        chron_snapshots=(),
        lstm_merged_window=(),
        lstm_merged_days=(),
        n_fetch=1,
        meta={},
    )
    with pytest.raises(Exception):
        ctx.n_fetch = 2  # type: ignore[misc]


def test_coh_i_f_meta_is_read_only_mapping_view(monkeypatch):
    """COH-I-F: meta is wrapped in MappingProxyType in build_shared_sequence_context, so
    mutating ctx.meta raises TypeError. Frozen dataclass attribute-reassign guard already
    locked above; this guard locks the nested-dict mutation surface.
    """
    from types import MappingProxyType

    from features import shared_sequence_context as ssc
    from tests.test_parallel_stack_runtime import _minimal_inf_v1

    monkeypatch.setattr(ssc, "_max_transformer_seq_len_for_ticker", lambda _t: 20)
    rows = [{"ts_utc": 3000.0 - i, "spot": 450.0} for i in range(100)]  # newest first
    db = MagicMock()
    db.get_recent_snapshots.return_value = rows
    mw = [{"ts_utc": float(i)} for i in range(60)]
    md = [{"ts_utc": float(i)} for i in range(80)]
    with patch(
        "features.lstm_sequence_input.build_lstm_merged_windows",
        return_value=(mw, md),
    ):
        ctx, err = build_shared_sequence_context(db, "SPY", _minimal_inf_v1())
    assert err is None and ctx is not None
    assert isinstance(ctx.meta, MappingProxyType)
    with pytest.raises(TypeError):
        ctx.meta["new_key"] = "no"  # type: ignore[index]
