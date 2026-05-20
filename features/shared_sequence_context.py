"""
Per-tick shared DB sequence preparation for LSTM + Transformer (one fetch, one LSTM merge).

Horizon-specific model masks and Transformer merged windows are still built per horizon;
this module only deduplicates identical work across the governed-horizon loop.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from lstm_data import CANONICAL_TIMEFRAME, STREAM_5M_LOOKBACK
from ml_horizon import ALL_GOVERNED_HORIZONS

log = logging.getLogger(__name__)

_DEFAULT_TRANSFORMER_SEQ_LEN = 20


def _require_ticker(ticker: str) -> str:
    if not ticker or not str(ticker).strip():
        raise ValueError("ticker is required")
    return str(ticker).strip().upper()


@dataclass(frozen=True)
class SharedSequenceContext:
    """Immutable handles to shared sequence data (do not mutate nested dicts)."""

    as_of_ts: float
    chron_snapshots: tuple[dict[str, Any], ...]
    lstm_merged_window: tuple[dict[str, Any], ...]
    lstm_merged_days: tuple[dict[str, Any], ...]
    n_fetch: int
    meta: dict[str, Any]


def _max_transformer_seq_len_for_ticker(ticker: str) -> int:
    """Scan transformer meta on disk per governed horizon; default 20 when missing."""
    tkr = _require_ticker(ticker)
    m = _DEFAULT_TRANSFORMER_SEQ_LEN
    from ml_predict import (  # lazy: ml_predict already loaded when builder runs from signals
        _model_dir_for_ticker,
        reset_ml_infer_horizon_slug,
        set_ml_infer_horizon_slug,
    )

    for hz in ALL_GOVERNED_HORIZONS:
        tok = set_ml_infer_horizon_slug(hz)
        try:
            try:
                base = _model_dir_for_ticker(tkr)
            except FileNotFoundError as e:
                log.debug("shared sequence context: no active model bundle for %s %s: %s", tkr, hz, e)
                continue
            mp = base / f"transformer_{tkr}_{hz}_meta.json"
            if mp.is_file():
                try:
                    raw = mp.read_text(encoding="utf-8")
                except OSError as e:
                    log.warning(
                        "transformer meta unreadable for %s %s at %s: %s — using default seq_len",
                        tkr,
                        hz,
                        mp,
                        e,
                    )
                    continue
                try:
                    meta_data = json.loads(raw)
                except json.JSONDecodeError as e:
                    log.warning(
                        "transformer meta JSON corrupt for %s %s at %s: %s — using default seq_len",
                        tkr,
                        hz,
                        mp,
                        e,
                    )
                    continue
                seq_raw = meta_data.get("seq_len")
                if seq_raw is None:
                    log.warning(
                        "transformer meta for %s %s at %s missing seq_len key — using default seq_len",
                        tkr,
                        hz,
                        mp,
                    )
                    continue
                try:
                    seq_int = int(seq_raw)
                except (ValueError, TypeError):
                    log.warning(
                        "transformer meta for %s %s at %s has non-int seq_len %r — using default seq_len",
                        tkr,
                        hz,
                        mp,
                        seq_raw,
                    )
                    continue
                if seq_int < 1:
                    log.warning(
                        "transformer meta for %s %s at %s has invalid seq_len %r — using default seq_len",
                        tkr,
                        hz,
                        mp,
                        seq_int,
                    )
                    continue
                m = max(m, seq_int)
        finally:
            reset_ml_infer_horizon_slug(tok)
    return max(1, m)


def build_shared_sequence_context(
    db: Any,
    ticker: str,
    inference_snapshot_v1: dict,
) -> tuple[Optional[SharedSequenceContext], Optional[str]]:
    """
    Single DB fetch + single LSTM merge for the current tick.

    Returns (context, None) on success, or (None, error_reason) on failure — caller falls back
    to per-horizon DB reads (legacy behavior).
    """
    from features.lstm_sequence_input import LstmSequenceInputError, build_lstm_merged_windows
    from ml_predict import _require_as_of_ts_utc_for_sequence_db

    tkr = _require_ticker(ticker)
    try:
        _asof = _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1)
    except LstmSequenceInputError as e:
        return None, str(e)

    max_tr_seq = _max_transformer_seq_len_for_ticker(tkr)
    n_fetch = max(100, STREAM_5M_LOOKBACK + 5, max_tr_seq + 5)

    try:
        rows = db.get_recent_snapshots(
            tkr,
            CANONICAL_TIMEFRAME,
            n=n_fetch,
            filled_only=False,
            as_of_ts_utc=_asof,
        )
    except Exception as e:
        return None, f"get_recent_snapshots_failed:{e!r}"

    if not rows or len(rows) < STREAM_5M_LOOKBACK:
        return None, f"insufficient_snapshots:{len(rows or [])}"

    chron = tuple(reversed(rows))
    if len(chron) >= 2:
        t_first = chron[0].get("ts_utc")
        t_last = chron[-1].get("ts_utc")
        if t_first is None or t_last is None:
            return None, "snapshot_ts_utc_missing"
        try:
            if float(t_first) > float(t_last):
                return None, "snapshot_order_not_chronological"
        except (TypeError, ValueError):
            return None, "snapshot_ts_utc_not_comparable"
    lstm_window = list(chron[-STREAM_5M_LOOKBACK:])
    day_snaps = list(chron[-100:]) if len(chron) >= 100 else list(chron)

    try:
        merged_window, merged_days = build_lstm_merged_windows(
            lstm_window,
            day_snaps,
            inference_snapshot_v1=inference_snapshot_v1,
        )
    except LstmSequenceInputError as e:
        return None, str(e)

    meta = {
        "lookback_5m": STREAM_5M_LOOKBACK,
        "n_fetch": n_fetch,
        "chron_row_count": len(chron),
        "max_transformer_seq_len_scanned": max_tr_seq,
    }
    return (
        SharedSequenceContext(
            as_of_ts=float(_asof),
            chron_snapshots=chron,
            lstm_merged_window=tuple(merged_window),
            lstm_merged_days=tuple(merged_days),
            n_fetch=n_fetch,
            meta=meta,
        ),
        None,
    )


def transformer_window_chronological(
    ctx: SharedSequenceContext,
    seq_len: int,
) -> list[dict[str, Any]]:
    """Last ``seq_len`` chronological snapshots (newest at end) — for Transformer merge."""
    ch = ctx.chron_snapshots
    if len(ch) < seq_len:
        from features.lstm_sequence_input import TransformerSequenceInputError

        raise TransformerSequenceInputError(
            f"Transformer needs at least {seq_len} snapshots, got {len(ch)}"
        )
    return list(ch[-seq_len:])
