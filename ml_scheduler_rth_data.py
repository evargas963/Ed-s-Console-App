"""ml_scheduler.py ticker-roster + RTH-data-loading cluster (RC-REHAB-1, ml_scheduler.py
decomposition slice 2): authoritative training-ticker enrollment, the RTH-labeled-row DB
scans that back it, and the causal-history preload used by the offline eval cluster.

Monkeypatch note: `_get_tickers_with_rth_data` and `_eval_hist_db_for_labeled_rows` are
monkeypatched directly via `monkeypatch.setattr("ml_scheduler.<name>", ...)`
(tests/test_issue22_logging_universe.py, tests/test_arch_competition_eval_runner.py) --
ml_scheduler.py re-exports both (`from ml_scheduler_rth_data import ...`) so that attribute
still exists to patch. `_diagnostic_db_tickers_not_enrolled` calls `_get_tickers_with_rth_data`
internally and BOTH now live in this file, so that one call goes through a LAZY
`import ml_scheduler; ml_scheduler._get_tickers_with_rth_data(...)` rather than a same-module
direct reference -- a direct reference would resolve through this file's own globals, which
the test's `ml_scheduler.` patch never touches, silently defeating it (same class of hazard
already handled in db.py/db_snapshots.py). `_eval_hist_db_for_labeled_rows`'s own callers
(`_evaluate_parallel_on_full_rth`, `_evaluate_cascade_on_full_rth`,
`_assemble_meta_ml_layer_prob_vectors`) have NOT moved out of ml_scheduler.py in this slice,
so their existing bare-name calls still resolve through ml_scheduler.py's own globals (which
the re-export binds and the monkeypatch replaces) -- no lazy-import needed for that symbol
in this slice.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from instrument_identity import ticker_storage_key
from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN


def _training_ticker_union(
    db_path: str | None = None,
    timeframe: str | None = None,
    *,
    label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    """Authoritative enrollment only: EdDB.logging_universe (see scheduler_user_tickers).

    db_path / timeframe / label_column are unused here; kept for call-site stability.
    RTH-labeled rows in snapshots determine whether training *runs* per ticker, not *membership*.
    """
    try:
        from scheduler_user_tickers import load_user_scheduler_tickers_or_empty

        tickers = load_user_scheduler_tickers_or_empty()
    except Exception:
        tickers = []
    return sorted({t for t in tickers if t and not str(t).startswith("$")})


def _get_tickers_with_rth_data(
    db_path: str, timeframe: str = None, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    from ml_data_common import is_rth_ts_utc, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M
    _tf = timeframe or CANONICAL_TIMEFRAME
    if _tf != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"_get_tickers_with_rth_data: canonical 1m only; got timeframe={_tf!r}"
        )
    table = SNAPSHOT_TABLE_1M
    conn = sqlite3.connect(db_path)
    where = training_base_where_clause(label_column, include_ticker=False)
    rows = conn.execute(
        f"SELECT ticker, ts_utc FROM {table} WHERE {where} ORDER BY ticker",
        (_tf,),
    ).fetchall()
    conn.close()
    tickers: set[str] = set()
    for r in rows:
        tkr = r[0]
        if not tkr or str(tkr).startswith("$"):
            continue
        try:
            if is_rth_ts_utc(float(r[1])):
                tickers.add(tkr)
        except (TypeError, ValueError):
            continue
    return sorted(tickers)


def _diagnostic_db_tickers_not_enrolled(
    db_path: str,
    enrolled: list[str],
    *,
    timeframe: str | None = None,
    label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    """Non-authoritative: tickers with labeled RTH rows but not in logging_universe."""
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    try:
        have = ml_scheduler._get_tickers_with_rth_data(
            db_path, timeframe=timeframe, label_column=label_column
        )
    except Exception:
        return []
    # RC-345/F25: enrollment identity through the one authority — enrolled 'SPX' and
    # DB-stored '$SPX' must compare equal, not diverge under bare .upper().
    e = {ticker_storage_key(x) for x in enrolled if x}
    return sorted({t for t in have if ticker_storage_key(t) not in e})


def _load_rth_rows_for_ticker(
    db_path: str, ticker: str, timeframe: str = None, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[dict]:
    from ml_data_common import filter_ts_utc_list_to_rth, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M
    _tf = timeframe or CANONICAL_TIMEFRAME
    if _tf != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"_load_rth_rows_for_ticker: canonical 1m only; got timeframe={_tf!r}"
        )
    table = SNAPSHOT_TABLE_1M
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = training_base_where_clause(label_column, include_ticker=False)
    rows = conn.execute(
        f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND {where}
        ORDER BY ts_utc ASC
        """,
        (ticker, _tf),
    ).fetchall()
    conn.close()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            if filter_ts_utc_list_to_rth([float(d["ts_utc"])]):
                out.append(d)
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _empty_realized_metrics(n_rows: int) -> dict[str, Any]:
    from realized_contract_eval import SKIP_RATE_FAIL_THRESHOLD, SKIP_RATE_WARNING_THRESHOLD

    # ECON-01 (2026-07-11): the empty shape mirrors the denominator-first
    # aggregate — no tradeable rows were evaluated, so execution economics are
    # unmeasurable (skip_rate None), not "100% skipped".
    return {
        "eval_pnl_realized_contract": None,
        "total_pnl_dollars": None,
        "avg_pnl_dollars": None,
        "median_pnl_dollars": None,
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "expectancy": None,
        "total_signals": 0,
        "skipped_trade_count": 0,
        "valid_trade_count": 0,
        "skip_rate": None,
        "universe_rows_total": n_rows,
        "non_decision_row_counts": {},
        "decision_no_trade_rows": 0,
        "tradeable_signal_rows": 0,
        "execution_economics_measurable": False,
        "skip_reason_counts": {},
        "skip_reason_counts_coarse": {},
        "skip_rate_by_reason": {},
        "skip_rate_warning_threshold": SKIP_RATE_WARNING_THRESHOLD,
        "skip_rate_fail_threshold": SKIP_RATE_FAIL_THRESHOLD,
        "skip_rate_warning_flag": False,
        "skip_rate_fail_flag": False,
        "evaluation_quality_degraded": False,
        "same_bar_conflict_trade_count": 0,
        "chain_selection_quality": {},
    }


def _eval_hist_db_for_labeled_rows(
    db_path: str,
    ticker: str,
    rows: list[dict],
):
    """Preload causal 1m history for offline RTH eval (parallel/cascade arch competition)."""
    from train_all import preload_historical_db_for_eval
    from lstm_data import STREAM_5M_LOOKBACK, STREAM_1M_LOOKBACK

    _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
    if not _tss:
        return None
    max_ts = max(_tss)
    min_ts = min(_tss)
    buffer_sec = float(STREAM_5M_LOOKBACK + STREAM_1M_LOOKBACK + 30) * 60.0
    return preload_historical_db_for_eval(
        db_path,
        ticker,
        max_ts,
        min_ts_utc=max(0.0, min_ts - buffer_sec),
    )
