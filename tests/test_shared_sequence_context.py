"""Shared per-tick LSTM/TR sequence context: parity slices and DB call deduplication."""

from __future__ import annotations

from pathlib import Path


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




