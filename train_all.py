"""
Ed Console - train_all.py
=========================
One command trains everything: XGBoost + LSTM + Transformer + Meta (parallel path).
RULE 2: No gates — train if data exists. No minimum row counts.
"""

import os
import argparse
import bisect
import sqlite3
from pathlib import Path
from typing import List

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import DB_PATH as _DB_PATH_OBJ

DB_PATH = str(_DB_PATH_OBJ)
MODEL_DIR = Path("models")

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug, outcome_column
# RC-345/F25 (train-write faucet): every identity-bearing ticker use here (DB-query key,
# training roster identity, direct artifact basename) consumes the ONE canonical authority so
# bare 'SPX' and '$SPX' resolve to the same rows and the same artifact the writers/readers use.
from instrument_identity import ticker_storage_key
import logging

log = logging.getLogger(__name__)



def run_xgb(
    ticker: str = None,
    model_dir: Path = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    *,
    db_path: str = DB_PATH,
    **kw,
) -> dict:
    """Train XGBoost for ticker(s)."""
    print("\n" + "=" * 60)
    print("STEP 1: XGBoost Training")
    print("=" * 60)
    try:
        from ml_train import load_data, train_ticker
    except ImportError as e:
        print(f"  ERROR: {e}")
        return {}

    out = model_dir or MODEL_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    outcome_column(hz)
    if ticker:
        from scheduler_user_tickers import require_ml_training_ticker_allowed

        ticker = require_ml_training_ticker_allowed(ticker)
        df = load_data(db_path, ticker=ticker_storage_key(ticker), ml_horizon_slug=hz)
        tickers = [ticker_storage_key(ticker)] if len(df) > 0 else []
    else:
        try:
            from scheduler_user_tickers import (
                load_user_scheduler_tickers_or_empty,
                resolve_ml_training_roster,
            )

            enrolled = load_user_scheduler_tickers_or_empty()
            tickers = resolve_ml_training_roster(enrolled, db_path)
        except Exception:
            tickers = []
        tickers = [t for t in tickers if t and not str(t).startswith("$")]

    results = {}
    for tkr in tickers:
        df = load_data(db_path, ticker=tkr, ml_horizon_slug=hz)
        if len(df) == 0:
            continue
        try:
            r = train_ticker(tkr, df, model_dir=out, ml_horizon_slug=hz,
                              db_path=db_path, **kw)  # RC-344/F35: same DB as load_data
            results[tkr] = r
        except Exception as e:
            print(f"  ERROR {tkr}: {e}")
    return results


def run_lstm(
    db_path: str = DB_PATH,
    ticker: str = None,
    model_dir: Path = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict:
    """Train LSTM per ticker."""
    print("\n" + "=" * 60)
    print("STEP 2: LSTM Training")
    print("=" * 60)
    try:
        from lstm_model import train_lstm, lstm_model_path
        from lstm_data import build_lstm_dataset
    except ImportError as e:
        print(f"  ERROR: {e}")
        return {}

    out = model_dir or MODEL_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    if ticker:
        from scheduler_user_tickers import require_ml_training_ticker_allowed

        ticker = require_ml_training_ticker_allowed(ticker)
    tickers = [ticker_storage_key(ticker)] if ticker else None
    if not tickers:
        ds = build_lstm_dataset(db_path=db_path, ml_horizon_slug=hz)
        tickers = sorted(set(ds.tickers)) if ds.tickers else []

    results = {}
    for tkr in tickers:
        try:
            train_lstm(db_path=db_path, ticker=tkr, model_dir=out, ml_horizon_slug=hz)
            results[tkr] = lstm_model_path(tkr, out, ml_horizon_slug=hz).exists()
        except Exception as e:
            print(f"  ERROR {tkr}: {e}")
            results[tkr] = False
    return results


def run_transformer(
    db_path: str = DB_PATH,
    ticker: str = None,
    model_dir: Path = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict:
    """Train Transformer per ticker."""
    print("\n" + "=" * 60)
    print("STEP 3: Transformer Training")
    print("=" * 60)
    try:
        from transformer_train import train_transformer, transformer_model_path
        from lstm_data import build_lstm_dataset
    except ImportError as e:
        print(f"  ERROR: {e}")
        return {}

    out = model_dir or MODEL_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    if ticker:
        from scheduler_user_tickers import require_ml_training_ticker_allowed

        ticker = require_ml_training_ticker_allowed(ticker)
    tickers = [ticker_storage_key(ticker)] if ticker else None
    if not tickers:
        ds = build_lstm_dataset(db_path=db_path, ml_horizon_slug=hz)
        tickers = sorted(set(ds.tickers)) if ds.tickers else []

    results = {}
    for tkr in tickers:
        try:
            train_transformer(db_path=db_path, ticker=tkr, model_dir=out, ml_horizon_slug=hz)
            results[tkr] = transformer_model_path(tkr, out, ml_horizon_slug=hz).exists()
        except Exception as e:
            print(f"  ERROR {tkr}: {e}")
            results[tkr] = False
    return results


def run_meta(
    db_path: str = DB_PATH,
    tickers: list = None,
    model_dir: Path = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict:
    """Train meta-learner per ticker. Requires XGB+LSTM+Transformer in model_dir.

    Env ED_META_TRAIN_MAX_ROWS: if > 0, use only the last N rows (chronological) for meta
    fitting — speeds recovery when per-row LSTM/Transformer calls are expensive. Default 0 = all rows.
    """
    print("\n" + "=" * 60)
    print("STEP 4: Meta-Learner Training")
    print("=" * 60)
    try:
        import numpy as np
        import pickle
        from sklearn.linear_model import LogisticRegression
        from ml_train import load_data, encode_target
        from ml_predict import _predict_xgb, _predict_lstm, _predict_transformer, CLASS_NAMES
    except ImportError as e:
        print(f"  ERROR: {e}")
        return {}

    out = model_dir or MODEL_DIR
    from train_all import _HistoricalDB

    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)

    if not tickers:
        from scheduler_user_tickers import (
            load_user_scheduler_tickers_or_empty,
            resolve_ml_training_roster,
        )

        enrolled = load_user_scheduler_tickers_or_empty()
        tickers = resolve_ml_training_roster(enrolled, db_path)
    else:
        from scheduler_user_tickers import require_ml_training_ticker_allowed

        tickers = [require_ml_training_ticker_allowed(t) for t in tickers]

    import ml_predict as mp
    orig_dir = mp.MODEL_DIR
    mp.MODEL_DIR = out
    mp.reset_caches()
    htok = mp.set_ml_infer_horizon_slug(hz)
    results = {}
    try:
        for tkr in tickers:
            _tk = ticker_storage_key(tkr)  # RC-345/F25: artifact basename identity == writers
            xgb_ok = (out / f"xgb_{_tk}_{hz}.pkl").exists()
            lstm_ok = (out / f"lstm_{_tk}_{hz}.pt").exists()
            tr_ok = (out / f"transformer_{_tk}_{hz}.pt").exists()
            if not xgb_ok:
                continue
            try:
                df = load_data(db_path, ticker=tkr, ml_horizon_slug=hz)
                if len(df) < 10:
                    continue
                _meta_cap = int(os.environ.get("ED_META_TRAIN_MAX_ROWS", "0") or "0")
                if _meta_cap > 0 and len(df) > _meta_cap:
                    df = df.iloc[-_meta_cap:].reset_index(drop=True)
                    print(f"  meta: ED_META_TRAIN_MAX_ROWS={_meta_cap} — using last {_meta_cap} rows")
                y = encode_target(df, label_col)
                from features.training_canonical_input import records_for_mvp_from_dataframe

                rows = records_for_mvp_from_dataframe(df)
                stacked, ys = [], []
                conn = sqlite3.connect(db_path)
                from features.inference_snapshot import build_inference_snapshot_v1_from_db_row

                from features.fusion_model_input import meta_tabular_vector_from_overlay

                for i, row in enumerate(rows):
                    inf_v1 = build_inference_snapshot_v1_from_db_row(
                        ticker=tkr,
                        expiry=None,
                        as_of_ts=row.get("ts_utc"),
                        db_row=row,
                    )
                    xgb_p = _predict_xgb(inf_v1, tkr, fusion_feature_overlay=row)
                    lstm_p = tr_p = None
                    if row.get("ts_utc"):
                        hist_db = _HistoricalDB(conn, tkr, float(row["ts_utc"]))
                        if lstm_ok:
                            lstm_p = _predict_lstm(
                                tkr, hist_db, inference_snapshot_v1=inf_v1
                            )
                        if tr_ok:
                            tr_p = _predict_transformer(
                                tkr, hist_db, inference_snapshot_v1=inf_v1
                            )
                    if xgb_p is None:
                        continue
                    vec = (
                        [xgb_p.get(c, 0.333) for c in CLASS_NAMES] +
                        ([lstm_p.get(c, 0.333) for c in CLASS_NAMES] if lstm_p else [0.333, 0.333, 0.334]) +
                        ([tr_p.get(c, 0.333) for c in CLASS_NAMES] if tr_p else [0.333, 0.333, 0.334]) +
                        meta_tabular_vector_from_overlay(row)
                    )
                    stacked.append(vec)
                    ys.append(y[i])
                conn.close()

                if len(stacked) < 10:
                    continue
                X = np.array(stacked)
                y_meta = np.array(ys[: len(stacked)])
                meta_mdl = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
                meta_mdl.fit(X, y_meta)
                out.mkdir(parents=True, exist_ok=True)
                with open(out / f"meta_{ticker_storage_key(tkr)}_{hz}.pkl", "wb") as f:  # RC-345/F25
                    pickle.dump(meta_mdl, f)
                results[tkr] = {"n_rows": len(stacked)}
            except Exception as e:
                print(f"  ERROR {tkr}: {e}")
    finally:
        mp.MODEL_DIR = orig_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok)
    return results


class _HistoricalDB:
    """
    Read-only DB shim for in-sample prediction. Uses snapshots_1m_normalized
    when timeframe is 1m (canonical) so evaluation matches training data source.
    """
    def __init__(self, conn, ticker: str, ts_utc: float):
        self.conn = conn
        self.ticker = ticker
        self.ts_utc = ts_utc

    def get_recent_snapshots(
        self,
        ticker: str,
        timeframe: str,
        n: int = 5000,
        filled_only: bool = False,
        *,
        as_of_ts_utc=None,
    ) -> list:
        if ticker != self.ticker:
            return []
        from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

        if timeframe != CANONICAL_TIMEFRAME:
            return []
        table = SNAPSHOT_TABLE_1M
        filled = "AND outcome_filled = 1" if filled_only else ""
        bound = float(as_of_ts_utc) if as_of_ts_utc is not None else float(self.ts_utc)
        ts_cmp = "ts_utc < ?" if as_of_ts_utc is not None else "ts_utc <= ?"
        self.conn.row_factory = sqlite3.Row
        rows = self.conn.execute(
            f"SELECT * FROM {table} WHERE ticker=? AND timeframe=? AND {ts_cmp} {filled} ORDER BY ts_utc DESC LIMIT ?",
            (ticker, timeframe, bound, n),
        ).fetchall()
        return [dict(r) for r in rows]


class PreloadedHistoricalDB:
    """
    Same contract as _HistoricalDB for get_recent_snapshots, backed by RAM.

    Used for offline validation / eval: one SQL load for all rows with
    ts_utc < max_as_of_ts_utc, then O(log N + k) slices per call — no per-row queries.
    """

    __slots__ = ("_rows", "_ts_list", "ticker", "ts_utc")

    def __init__(self, rows_asc: List[dict], ticker: str, ts_utc: float):
        self._rows = rows_asc
        self._ts_list = [float(r["ts_utc"]) for r in rows_asc]
        self.ticker = ticker
        self.ts_utc = ts_utc

    def get_recent_snapshots(
        self,
        ticker: str,
        timeframe: str,
        n: int = 5000,
        filled_only: bool = False,
        *,
        as_of_ts_utc=None,
    ) -> list:
        if ticker != self.ticker:
            return []
        from timeframe_config import CANONICAL_TIMEFRAME

        if timeframe != CANONICAL_TIMEFRAME:
            return []
        bound = float(as_of_ts_utc) if as_of_ts_utc is not None else float(self.ts_utc)
        if as_of_ts_utc is not None:
            hi = bisect.bisect_left(self._ts_list, bound)
            pool = self._rows[:hi]
        else:
            hi = bisect.bisect_right(self._ts_list, bound)
            pool = self._rows[:hi]
        if filled_only:
            pool = [r for r in pool if r.get("outcome_filled") == 1]
        if len(pool) > n:
            pool = pool[-n:]
        return list(reversed(pool))


def preload_historical_db_for_eval(
    db_path: str,
    ticker: str,
    max_as_of_ts_utc: float,
    *,
    min_ts_utc: float | None = None,
) -> PreloadedHistoricalDB:
    """
    Load 1m snapshots for ``ticker`` with ``min_ts_utc <= ts_utc < max_as_of_ts_utc``.

    For each evaluation row at ``T``, LSTM/Transformer call
    ``get_recent_snapshots(..., as_of_ts_utc=T)`` (strictly causal: only rows with
    ``ts_utc < T``). ``min_ts_utc`` should be ``min(eval_row_ts) - lookback_buffer`` so
    the first scored row still has enough pre-history across RTH gaps (governed eval
  2026-05-26: without ``min_ts_utc``, loading from row 0 of the table was correct but
    eval aborted on the first thin-history row; callers now pass a wall-clock buffer).
    """
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = "ticker = ? AND timeframe = ? AND ts_utc < ?"
    params: list = [ticker, CANONICAL_TIMEFRAME, float(max_as_of_ts_utc)]
    if min_ts_utc is not None:
        where += " AND ts_utc >= ?"
        params.append(float(min_ts_utc))
    raw = conn.execute(
        f"""
        SELECT * FROM {SNAPSHOT_TABLE_1M}
        WHERE {where}
        ORDER BY ts_utc ASC
        """,
        params,
    ).fetchall()
    conn.close()
    return PreloadedHistoricalDB([dict(r) for r in raw], ticker, float(max_as_of_ts_utc))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--model-dir", type=str, default=None)
    ap.add_argument("--xgb-only", action="store_true")
    ap.add_argument("--lstm-only", action="store_true")
    ap.add_argument("--transformer-only", action="store_true")
    ap.add_argument("--meta-only", action="store_true")
    ap.add_argument("--skip-xgb", action="store_true")
    ap.add_argument("--skip-lstm", action="store_true")
    ap.add_argument("--skip-transformer", action="store_true")
    ap.add_argument(
        "--horizon",
        type=str,
        default=DEFAULT_ML_HORIZON_SLUG,
        help="ML horizon slug (1c, 5c, 15c, 60c); selects outcome_* label and artifact names.",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="train_all", write_capable=False)
    hz = normalize_ml_horizon_slug(args.horizon)

    model_dir = Path(args.model_dir) if args.model_dir else MODEL_DIR
    MODEL_DIR.mkdir(exist_ok=True)

    run_xgb_flag = not (args.lstm_only or args.transformer_only or args.meta_only or args.skip_xgb)
    run_lstm_flag = not (args.xgb_only or args.transformer_only or args.meta_only or args.skip_lstm)
    run_tr_flag = not (args.xgb_only or args.lstm_only or args.meta_only or args.skip_transformer)
    run_meta_flag = args.meta_only or (run_xgb_flag and run_lstm_flag and run_tr_flag)

    if run_xgb_flag:
        run_xgb(ticker=args.ticker, model_dir=model_dir, ml_horizon_slug=hz, db_path=str(Path(args.db).resolve()))
    if run_lstm_flag:
        run_lstm(db_path=args.db, ticker=args.ticker, model_dir=model_dir, ml_horizon_slug=hz)
    if run_tr_flag:
        run_transformer(db_path=args.db, ticker=args.ticker, model_dir=model_dir, ml_horizon_slug=hz)
    if run_meta_flag:
        tickers_arg = [ticker_storage_key(args.ticker)] if args.ticker else None
        run_meta(db_path=args.db, tickers=tickers_arg, model_dir=model_dir, ml_horizon_slug=hz)

    try:
        import ml_predict
        ml_predict.reset_caches()
    except Exception as e:
        log.debug("train_all: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
