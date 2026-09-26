"""Layer 5 shared_sequence_context chunk-1: gap-fill contract locks (11/11 features sweep)."""

from __future__ import annotations


import pytest

from features.shared_sequence_context import (
    SharedSequenceContext,
    transformer_window_chronological,
)
from features.lstm_sequence_input import TransformerSequenceInputError




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


