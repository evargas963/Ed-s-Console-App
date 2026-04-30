"""
ml_scheduler.py - Nightly ML Training Scheduler
===============================================
RULE 3: Runs every weekday at 16:15 ET.
For every ticker in EdDB.logging_universe (authoritative enrollment — core + pinned + user_persisted):
  A. Train parallel (XGB, LSTM, Transformer, Meta) → models/parallel/{ticker}/
  B. Train cascade (XGB→LSTM→Transformer) → models/cascade/{ticker}/
  C. Compare both on full RTH
  D. Promote winner to models/active/{ticker}/ (gated: provenance + threshold)
  E. Write models/arch_state.json + training report

RULE: Do not promote unless provenance validates (timeframe, target, metric).

Cache / reuse (training_cache.py):
  - scheduler_run_manifest.json per candidate dir: skip train+eval when key matches DB fingerprint + versions
  - models/cache/features/{feature_cache_key}/: LSTM npz + parallel Transformer npz (invalidate on data/versions)
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Set
import argparse
import time

APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

from db import DB_PATH as _DB_PATH_OBJ  # noqa: E402 — after sys.path

DB_PATH = str(_DB_PATH_OBJ)
MODEL_DIR = APP_DIR / "models"
PARALLEL_DIR = MODEL_DIR / "parallel"
CASCADE_DIR = MODEL_DIR / "cascade"
ACTIVE_DIR = MODEL_DIR / "active"
ARCH_STATE_PATH = MODEL_DIR / "arch_state.json"
TRAINING_REPORT_PATH = MODEL_DIR / "training_report.jsonl"
RUN_AT_HOUR = 16
RUN_AT_MINUTE = 15

ET = timezone(timedelta(hours=-5))
log = logging.getLogger("ml_scheduler")

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    DEFAULT_TRAINING_LABEL_COLUMN,
    normalize_ml_horizon_slug,
    outcome_column,
    target_definition as horizon_target_definition,
)


def scheduler_arch_state_path(ml_horizon_slug: str) -> Path:
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return ARCH_STATE_PATH
    return MODEL_DIR / f"arch_state_{su}.json"


def scheduler_active_root(ml_horizon_slug: str) -> Path:
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return ACTIVE_DIR
    return MODEL_DIR / f"active_{su}"


def _infer_slug_from_target_column(target_column: str) -> str:
    col = (target_column or "").strip().lower()
    if col.startswith("outcome_"):
        return normalize_ml_horizon_slug(col[len("outcome_") :])
    return DEFAULT_ML_HORIZON_SLUG


def _now_et() -> datetime:
    return datetime.now(ET)


def _scheduler_auto_promote_to_active() -> bool:
    """Never True: production active/ updates use arch_competition.manual_control only (no scheduler/env copy)."""
    return False


@contextmanager
def _strict_off_for_candidate_inference():
    """Temporarily disable strict-active-only resolution for candidate model inference."""
    key = "ED_XGB_STRICT_ACTIVE_ONLY"
    prior = os.environ.get(key)
    os.environ[key] = "0"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


def _append_training_report(report: dict):
    """Append a per-ticker training report line to training_report.jsonl."""
    report["timestamp"] = _now_et().strftime("%Y-%m-%d %H:%M:%S ET")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(TRAINING_REPORT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")


def _is_market_day(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    md = (dt.month, dt.day)
    holidays = [
        (1, 1), (1, 20), (2, 17), (4, 18), (5, 26),
        (6, 19), (7, 4), (9, 1), (11, 27), (12, 25),
    ]
    return md not in holidays


def _wait_until_1615():
    now = _now_et()
    target = now.replace(hour=RUN_AT_HOUR, minute=RUN_AT_MINUTE, second=0, microsecond=0)
    if now >= target:
        return
    import time
    time.sleep(min((target - now).total_seconds(), 86400))


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
        from scheduler_user_tickers import load_user_scheduler_tickers

        tickers = load_user_scheduler_tickers()
    except Exception:
        tickers = []
    return sorted({t for t in tickers if t and not str(t).startswith("$")})


def _get_tickers_with_rth_data(
    db_path: str, timeframe: str = None, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    from ml_data_common import rth_where_clause, training_label_where_clause, weekday_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M
    _tf = timeframe or CANONICAL_TIMEFRAME
    if _tf != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"_get_tickers_with_rth_data: canonical 1m only; got timeframe={_tf!r}"
        )
    table = SNAPSHOT_TABLE_1M
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        f"""
        SELECT DISTINCT ticker FROM {table}
        WHERE timeframe = ? AND {training_label_where_clause(label_column)}
        AND {rth_where_clause()} AND ({weekday_where_clause()})
        ORDER BY ticker
        """,
        (_tf,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows if not r[0].startswith("$")]


def _diagnostic_db_tickers_not_enrolled(
    db_path: str,
    enrolled: list[str],
    *,
    timeframe: str | None = None,
    label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    """Non-authoritative: tickers with labeled RTH rows but not in logging_universe."""
    try:
        have = _get_tickers_with_rth_data(
            db_path, timeframe=timeframe, label_column=label_column
        )
    except Exception:
        return []
    e = {x.upper() for x in enrolled if x}
    return sorted({t for t in have if t.upper() not in e})


def _load_rth_rows_for_ticker(
    db_path: str, ticker: str, timeframe: str = None, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[dict]:
    from ml_data_common import rth_where_clause, training_label_where_clause, weekday_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M
    _tf = timeframe or CANONICAL_TIMEFRAME
    if _tf != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"_load_rth_rows_for_ticker: canonical 1m only; got timeframe={_tf!r}"
        )
    table = SNAPSHOT_TABLE_1M
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND timeframe = ?
        AND {training_label_where_clause(label_column)} AND {rth_where_clause()}
        AND ({weekday_where_clause()})
        ORDER BY ts_utc ASC
        """,
        (ticker, _tf),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _empty_realized_metrics(n_rows: int) -> dict[str, Any]:
    from realized_contract_eval import SKIP_RATE_FAIL_THRESHOLD, SKIP_RATE_WARNING_THRESHOLD

    sr = 1.0 if n_rows else 0.0
    return {
        "eval_pnl_realized_contract": None,
        "total_pnl_dollars": None,
        "avg_pnl_dollars": None,
        "median_pnl_dollars": None,
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "expectancy": None,
        "total_signals": n_rows,
        "skipped_trade_count": n_rows,
        "valid_trade_count": 0,
        "skip_rate": sr,
        "skip_reason_counts": {},
        "skip_reason_counts_coarse": {},
        "skip_rate_by_reason": {},
        "skip_rate_warning_threshold": SKIP_RATE_WARNING_THRESHOLD,
        "skip_rate_fail_threshold": SKIP_RATE_FAIL_THRESHOLD,
        "skip_rate_warning_flag": bool(sr >= SKIP_RATE_WARNING_THRESHOLD),
        "skip_rate_fail_flag": bool(sr >= SKIP_RATE_FAIL_THRESHOLD),
        "evaluation_quality_degraded": bool(sr >= SKIP_RATE_WARNING_THRESHOLD),
        "same_bar_conflict_trade_count": 0,
        "chain_selection_quality": {},
    }


def _evaluate_parallel_on_full_rth(
    db_path: str,
    ticker: str,
    model_dir: Path,
    *,
    allowed_et_dates: Optional[Set[str]] = None,
    target_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
    return_detail: bool = False,
) -> tuple[float, float, int, Optional[float], dict[str, Any]] | tuple:
    """Run parallel ensemble on full RTH data (or only ET dates in allowed_et_dates if set).

    Returns accuracy, balanced_accuracy, n_rows_scored, log_loss, realized_contract_metrics (see realized_contract_eval).
    If ``return_detail`` is True, appends a dict with prob_rows, y_true, rows_used for arch_competition eval.
    """
    rows = _load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
    if allowed_et_dates is not None:
        rows = [r for r in rows if r.get("ts_et") and str(r["ts_et"])[:10] in allowed_et_dates]
    if len(rows) < 10:
        out = (0.0, 0.0, len(rows), None, _empty_realized_metrics(len(rows)))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out

    try:
        from train_all import preload_historical_db_for_eval
        import ml_predict as mp
        import numpy as np
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
        from realized_contract_eval import evaluate_realized_contract_trades_for_rows
        from timeframe_config import SNAPSHOT_TABLE_1M

        orig_dir = mp.MODEL_DIR
        hz_slug = _infer_slug_from_target_column(target_column)
        htok = mp.set_ml_infer_horizon_slug(hz_slug)
        try:
            with _strict_off_for_candidate_inference():
                mp.MODEL_DIR = model_dir
                mp.reset_caches()

                preds: list[int] = []
                y_true: list[int] = []
                prob_rows: list[list[float]] = []
                rows_used: list[dict] = []
                from features.inference_snapshot import build_inference_snapshot_v1_from_db_row

                _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
                hist_db = (
                    preload_historical_db_for_eval(db_path, ticker, max(_tss))
                    if _tss
                    else None
                )

                for row in rows:
                    yt = {"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2)
                    inf_v1 = build_inference_snapshot_v1_from_db_row(
                        ticker=ticker,
                        expiry=None,
                        as_of_ts=row.get("ts_utc"),
                        db_row=row,
                    )
                    xgb_p = mp._predict_xgb(inf_v1, ticker, fusion_feature_overlay=row)
                    ts_utc = row.get("ts_utc")
                    lstm_p = tr_p = None
                    if ts_utc and hist_db is not None:
                        lstm_p = mp._predict_lstm(
                            ticker, hist_db, inference_snapshot_v1=inf_v1
                        )
                        tr_p = mp._predict_transformer(
                            ticker, hist_db, inference_snapshot_v1=inf_v1
                        )
                    if xgb_p is None:
                        continue
                    result = mp._predict_meta(ticker, xgb_p, lstm_p, tr_p)
                    if result is None:
                        result = mp._weighted_average(ticker, xgb_p, lstm_p, tr_p)
                    if not result:
                        continue
                    pu, pd, pf = (
                        float(result.get("up", 0.33)),
                        float(result.get("down", 0.33)),
                        float(result.get("flat", 0.34)),
                    )
                    s = pu + pd + pf
                    if s > 0:
                        pu, pd, pf = pu / s, pd / s, pf / s
                    prob_rows.append([pu, pd, pf])
                    dom = max(["up", "down", "flat"], key=lambda c: result.get(c, 0))
                    preds.append({"up": 0, "down": 1, "flat": 2}[dom])
                    y_true.append(yt)
                    rows_used.append(row)

            n = len(preds)
            if n < 10:
                out = (0.0, 0.0, n, None, _empty_realized_metrics(len(rows_used)))
                if return_detail:
                    return out + ({"prob_rows": prob_rows, "y_true": y_true, "rows_used": rows_used},)
                return out
            acc = float(accuracy_score(y_true, preds))
            bal = float(balanced_accuracy_score(y_true, preds))
            ll = float(
                log_loss(y_true, np.array(prob_rows, dtype=np.float64), labels=[0, 1, 2])
            )
            try:
                realized = evaluate_realized_contract_trades_for_rows(
                    db_path,
                    ticker,
                    "parallel",
                    rows_used,
                    snapshot_table=SNAPSHOT_TABLE_1M,
                )
            except Exception as _re:
                log.warning("Parallel realized contract eval failed %s: %s", ticker, _re)
                realized = _empty_realized_metrics(len(rows_used))
            detail = {
                "prob_rows": prob_rows,
                "y_true": y_true,
                "rows_used": rows_used,
            }
            if return_detail:
                return acc, bal, n, ll, realized, detail
            return acc, bal, n, ll, realized
        finally:
            mp.MODEL_DIR = orig_dir
            mp.reset_caches()
            mp.reset_ml_infer_horizon_slug(htok)
    except Exception as e:
        log.warning("Parallel eval failed for %s: %s", ticker, e)
        out = (0.0, 0.0, len(rows), None, _empty_realized_metrics(len(rows)))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out


def _evaluate_cascade_on_full_rth(
    db_path: str,
    ticker: str,
    model_dir: Path,
    *,
    allowed_et_dates: Optional[Set[str]] = None,
    target_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
    return_detail: bool = False,
) -> tuple[float, float, int, Optional[float], dict[str, Any]] | tuple:
    """Cascade: Transformer probabilities vs target_column; returns log_loss and realized_contract_metrics.

    If ``return_detail`` is True, appends prob_rows / y_true / rows_used for arch_competition.
    """
    rows = _load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
    if allowed_et_dates is not None:
        rows = [r for r in rows if r.get("ts_et") and str(r["ts_et"])[:10] in allowed_et_dates]
    if len(rows) < 10:
        out = (0.0, 0.0, len(rows), None, _empty_realized_metrics(len(rows)))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out

    try:
        from train_all import preload_historical_db_for_eval
        import ml_predict as mp
        import numpy as np
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
        from realized_contract_eval import evaluate_realized_contract_trades_for_rows
        from timeframe_config import SNAPSHOT_TABLE_1M

        orig_dir = mp.MODEL_DIR
        hz_slug = _infer_slug_from_target_column(target_column)
        htok = mp.set_ml_infer_horizon_slug(hz_slug)
        try:
            with _strict_off_for_candidate_inference():
                mp.MODEL_DIR = model_dir
                mp.reset_caches()

                preds: list[int] = []
                y_true: list[int] = []
                prob_rows: list[list[float]] = []
                rows_used: list[dict] = []
                from features.inference_snapshot import build_inference_snapshot_v1_from_db_row

                _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
                hist_db = (
                    preload_historical_db_for_eval(db_path, ticker, max(_tss))
                    if _tss
                    else None
                )

                for row in rows:
                    ts_utc = row.get("ts_utc")
                    if not ts_utc or hist_db is None:
                        continue
                    inf_v1 = build_inference_snapshot_v1_from_db_row(
                        ticker=ticker,
                        expiry=None,
                        as_of_ts=float(ts_utc),
                        db_row=row,
                    )
                    tr_p = mp._predict_transformer(
                        ticker, hist_db, inference_snapshot_v1=inf_v1
                    )
                    if not tr_p:
                        continue
                    pu = float(tr_p.get("up", 0.33))
                    pd = float(tr_p.get("down", 0.33))
                    pf = float(tr_p.get("flat", 0.34))
                    s = pu + pd + pf
                    if s > 0:
                        pu, pd, pf = pu / s, pd / s, pf / s
                    prob_rows.append([pu, pd, pf])
                    yt = {"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2)
                    y_true.append(yt)
                    dom = max(["up", "down", "flat"], key=lambda c: tr_p.get(c, 0))
                    preds.append({"up": 0, "down": 1, "flat": 2}[dom])
                    rows_used.append(row)

            n = len(preds)
            if n < 10:
                out = (0.0, 0.0, n, None, _empty_realized_metrics(len(rows_used)))
                if return_detail:
                    return out + ({"prob_rows": prob_rows, "y_true": y_true, "rows_used": rows_used},)
                return out
            acc = float(accuracy_score(y_true, preds))
            bal = float(balanced_accuracy_score(y_true, preds))
            ll = float(
                log_loss(y_true, np.array(prob_rows, dtype=np.float64), labels=[0, 1, 2])
            )
            try:
                realized = evaluate_realized_contract_trades_for_rows(
                    db_path,
                    ticker,
                    "cascade",
                    rows_used,
                    snapshot_table=SNAPSHOT_TABLE_1M,
                )
            except Exception as _re:
                log.warning("Cascade realized contract eval failed %s: %s", ticker, _re)
                realized = _empty_realized_metrics(len(rows_used))
            detail = {"prob_rows": prob_rows, "y_true": y_true, "rows_used": rows_used}
            if return_detail:
                return acc, bal, n, ll, realized, detail
            return acc, bal, n, ll, realized
        finally:
            mp.MODEL_DIR = orig_dir
            mp.reset_caches()
            mp.reset_ml_infer_horizon_slug(htok)
    except Exception as e:
        log.warning("Cascade eval failed for %s: %s", ticker, e)
        out = (0.0, 0.0, len(rows), None, _empty_realized_metrics(len(rows)))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out


def train_parallel_candidate(
    ticker: str,
    db_path: str,
    out_dir: Path,
    *,
    bypass_cache: bool = False,
    data_fp: Optional[dict] = None,
    code_fp: str = "",
    scheduler_cache_key: str = "",
    feature_cache_key: Optional[str] = None,
    allowed_et_dates: Optional[set] = None,
    prior_manifest: Optional[dict] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    """Train XGB, LSTM, Transformer, Meta into out_dir (production or compare)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz)

    from training_cache import (
        db_training_fingerprint,
        compute_training_code_fingerprint,
        compute_feature_cache_key,
        feature_cache_dir,
        load_lstm_feature_cache,
        save_lstm_feature_cache,
        load_transformer_parallel_cache,
        save_transformer_parallel_cache,
        min_ts_utc_for_last_n_rth_sessions,
    )
    from training_cache_policy import (
        ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
    )
    from ml_train import load_data, train_ticker
    from lstm_model import train_lstm, lstm_model_path
    from lstm_data import build_lstm_dataset
    from transformer_train import train_transformer, prepare_transformer_data, transformer_model_path
    import pickle
    from sklearn.linear_model import LogisticRegression
    from ml_predict import _predict_xgb, _predict_lstm, _predict_transformer, CLASS_NAMES
    from train_all import preload_historical_db_for_eval
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    import numpy as np

    used_feature_cache = False
    if data_fp is None:
        data_fp = db_training_fingerprint(db_path, ticker, label_column=target_column)
    if not code_fp:
        code_fp = compute_training_code_fingerprint()
    fk_computed = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=target_column)
    if feature_cache_key is not None:
        from features.training_canonical_input import TrainingCanonicalInputError

        if feature_cache_key != fk_computed:
            raise TrainingCanonicalInputError(
                "feature_cache_key override does not match computed shared key for this data/code/horizon"
            )
        fk = feature_cache_key
    else:
        fk = fk_computed
    fdir = feature_cache_dir(fk)

    if allowed_et_dates is not None:
        min_ts_tab = None
        min_ts_seq = None
    else:
        min_ts_tab = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_TABULAR, label_column=target_column,
        )
        min_ts_seq = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE, label_column=target_column,
        )

    prior_fp = (prior_manifest or {}).get("data_fingerprint") if prior_manifest else None

    df = load_data(
        db_path,
        ticker=ticker,
        min_ts_utc=min_ts_tab,
        allowed_et_dates=allowed_et_dates,
        ml_horizon_slug=hz,
    )
    if len(df) == 0:
        return {
            "used_feature_cache": False,
            "used_cascade_tensor_cache": False,
            "warm_resume": {},
        }
    train_ticker(
        ticker,
        df,
        model_dir=out_dir,
        prior_data_fingerprint=prior_fp,
        current_data_fingerprint=data_fp,
        ml_horizon_slug=hz,
    )

    # LSTM tensors: load from feature cache or build + save
    ds = None
    if not bypass_cache:
        ds = load_lstm_feature_cache(fdir, ticker, data_fp, fk)
    if ds is None:
        ds = build_lstm_dataset(
            tickers=[ticker],
            db_path=Path(db_path),
            min_ts_utc=min_ts_seq,
            allowed_et_dates=allowed_et_dates,
            ml_horizon_slug=hz,
        )
        if ds.n_samples > 0 and not bypass_cache:
            save_lstm_feature_cache(fdir, ticker, data_fp, fk, ds)
    else:
        used_feature_cache = True
        log.info("%s parallel: LSTM feature cache hit (%s)", ticker, fk[:12])

    lstm_rr = {}
    if ds is not None and getattr(ds, "n_samples", 0) > 0:
        lr = train_lstm(
            dataset=ds,
            db_path=db_path,
            ticker=ticker,
            model_dir=out_dir,
            scheduler_cache_key=scheduler_cache_key or None,
            data_fp=data_fp,
            architecture="parallel",
            bypass_torch_resume=bypass_cache,
            ml_horizon_slug=hz,
        )
        lstm_rr = {"lstm_warm_resume": lr.warm_resume_used, "lstm_warm_resume_detail": lr.warm_resume_detail}
    else:
        lr = train_lstm(
            db_path=db_path,
            ticker=ticker,
            model_dir=out_dir,
            scheduler_cache_key=scheduler_cache_key or None,
            data_fp=data_fp,
            architecture="parallel",
            bypass_torch_resume=bypass_cache,
            ml_horizon_slug=hz,
        )
        lstm_rr = {"lstm_warm_resume": lr.warm_resume_used, "lstm_warm_resume_detail": lr.warm_resume_detail}

    # Transformer parallel: load cached raw sequences or build + save
    preloaded = None
    if not bypass_cache:
        preloaded = load_transformer_parallel_cache(fdir, ticker, data_fp, fk)
    tr_rr = {}
    if preloaded is None:
        X, y, days, tickers_arr, n_features = prepare_transformer_data(
            db_path,
            ticker,
            min_ts_utc=min_ts_seq,
            allowed_et_dates=allowed_et_dates,
            ml_horizon_slug=hz,
        )
        if X is not None and len(y) > 0:
            if not bypass_cache:
                save_transformer_parallel_cache(
                    fdir, ticker, data_fp, fk, X, y, days, tickers_arr, n_features
                )
            tr = train_transformer(
                db_path=db_path,
                ticker=ticker,
                model_dir=out_dir,
                preloaded_sequences=(X, y, days, tickers_arr, n_features),
                allowed_et_dates=allowed_et_dates,
                scheduler_cache_key=scheduler_cache_key or None,
                data_fp=data_fp,
                architecture="parallel",
                bypass_torch_resume=bypass_cache,
                ml_horizon_slug=hz,
            )
            tr_rr = {
                "transformer_warm_resume": tr.warm_resume_used,
                "transformer_warm_resume_detail": tr.warm_resume_detail,
            }
        else:
            tr = train_transformer(
                db_path=db_path,
                ticker=ticker,
                model_dir=out_dir,
                allowed_et_dates=allowed_et_dates,
                scheduler_cache_key=scheduler_cache_key or None,
                data_fp=data_fp,
                architecture="parallel",
                bypass_torch_resume=bypass_cache,
                ml_horizon_slug=hz,
            )
            tr_rr = {
                "transformer_warm_resume": tr.warm_resume_used,
                "transformer_warm_resume_detail": tr.warm_resume_detail,
            }
    else:
        used_feature_cache = True
        log.info("%s parallel: Transformer feature cache hit (%s)", ticker, fk[:12])
        tr = train_transformer(
            db_path=db_path,
            ticker=ticker,
            model_dir=out_dir,
            preloaded_sequences=preloaded,
            allowed_et_dates=allowed_et_dates,
            scheduler_cache_key=scheduler_cache_key or None,
            data_fp=data_fp,
            architecture="parallel",
            bypass_torch_resume=bypass_cache,
            ml_horizon_slug=hz,
        )
        tr_rr = {
            "transformer_warm_resume": tr.warm_resume_used,
            "transformer_warm_resume_detail": tr.warm_resume_detail,
        }

    # Meta — keep ticker-leaf root so ml_predict resolves flat artifacts in this
    # candidate directory (xgb_SPY_<hz>.pkl, lstm_SPY_<hz>.pt, transformer_SPY_<hz>.pt).
    import ml_predict as mp
    orig_mp_dir = mp.MODEL_DIR
    htok_meta = mp.set_ml_infer_horizon_slug(hz)
    X_meta, y_meta = [], []
    try:
        with _strict_off_for_candidate_inference():
            mp.MODEL_DIR = out_dir
            mp.reset_caches()

            rows = df.to_dict("records")
            _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
            hist_db = (
                preload_historical_db_for_eval(db_path, ticker, max(_tss)) if _tss else None
            )
            for row in rows:
                inf_v1 = build_inference_snapshot_v1_from_db_row(
                    ticker=ticker,
                    expiry=None,
                    as_of_ts=row.get("ts_utc"),
                    db_row=row,
                )
                xgb_p = _predict_xgb(inf_v1, ticker, fusion_feature_overlay=row)
                lstm_p = tr_p = None
                ts_utc = row.get("ts_utc")
                if ts_utc and hist_db is not None:
                    # Sequence heads may be unavailable for a row (e.g., insufficient pre-history).
                    # Keep meta assembly robust by degrading to available branches for that row.
                    try:
                        lstm_p = _predict_lstm(ticker, hist_db, inference_snapshot_v1=inf_v1)
                    except Exception as _lstm_e:
                        log.debug("%s meta row: LSTM unavailable at ts=%s (%s)", ticker, ts_utc, _lstm_e)
                        lstm_p = None
                    try:
                        tr_p = _predict_transformer(ticker, hist_db, inference_snapshot_v1=inf_v1)
                    except Exception as _tr_e:
                        log.debug("%s meta row: Transformer unavailable at ts=%s (%s)", ticker, ts_utc, _tr_e)
                        tr_p = None
                if xgb_p is None:
                    continue
                vec = (
                    [xgb_p.get(c, 0.333) for c in CLASS_NAMES] +
                    ([lstm_p.get(c, 0.333) for c in CLASS_NAMES] if lstm_p else [0.333, 0.333, 0.334]) +
                    ([tr_p.get(c, 0.333) for c in CLASS_NAMES] if tr_p else [0.333, 0.333, 0.334])
                )
                X_meta.append(vec)
                y_meta.append({"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2))
    finally:
        mp.MODEL_DIR = orig_mp_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok_meta)

    if len(X_meta) >= 10:
        meta_mdl = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_mdl.fit(np.array(X_meta), np.array(y_meta))
        with open(out_dir / f"meta_{ticker.upper()}_{hz}.pkl", "wb") as f:
            pickle.dump(meta_mdl, f)

    warm_resume = {**lstm_rr, **tr_rr}
    return {
        "used_feature_cache": used_feature_cache,
        "used_cascade_tensor_cache": False,
        "warm_resume": warm_resume,
    }


def _train_parallel(
    ticker: str,
    db_path: str,
    *,
    out_dir: Optional[Path] = None,
    allowed_et_dates: Optional[Set[str]] = None,
    bypass_cache: bool = False,
    data_fp: Optional[dict] = None,
    code_fp: str = "",
    scheduler_cache_key: str = "",
    feature_cache_key: Optional[str] = None,
    prior_manifest: Optional[dict] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    """Production entry: same as nightly scheduler; optional out_dir / allowed_et_dates for compare tooling."""
    dest = out_dir if out_dir is not None else PARALLEL_DIR / ticker
    return train_parallel_candidate(
        ticker,
        db_path,
        dest,
        bypass_cache=bypass_cache,
        data_fp=data_fp,
        code_fp=code_fp,
        scheduler_cache_key=scheduler_cache_key,
        feature_cache_key=feature_cache_key,
        allowed_et_dates=allowed_et_dates,
        prior_manifest=prior_manifest,
        ml_horizon_slug=ml_horizon_slug,
    )


def train_cascade_candidate(
    ticker: str,
    db_path: str,
    out_dir: Path,
    *,
    bypass_cache: bool = False,
    data_fp: Optional[dict] = None,
    code_fp: str = "",
    scheduler_cache_key: str = "",
    feature_cache_key: Optional[str] = None,
    allowed_et_dates: Optional[set] = None,
    prior_manifest: Optional[dict] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    """Train XGB→LSTM(_XGB)→Transformer(_XGB+LSTM) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)

    from training_cache import (
        db_training_fingerprint,
        compute_training_code_fingerprint,
        compute_feature_cache_key,
        feature_cache_dir,
        load_lstm_feature_cache,
        save_lstm_feature_cache,
        load_cascade_transformer_tensor_cache,
        save_cascade_transformer_tensor_cache,
        min_ts_utc_for_last_n_rth_sessions,
    )
    from training_cache_policy import (
        ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
    )
    from ml_train import load_data, train_ticker, engineer_single_snapshot
    from lstm_model import train_lstm, load_lstm
    from features.training_canonical_input import training_snapshot_for_sequence_encode
    from lstm_data import (
        build_lstm_dataset,
        extract_rth_snapshots,
        encode_snapshot_5m,
        encode_snapshot_1m,
        compute_confluence_features,
        STREAM_5M_LOOKBACK,
        STREAM_1M_LOOKBACK,
        CONFLUENCE_FEATURES,
        _safe_float,
        TARGET_CLASSES,
        canonical_reference_spot_from_sequence_window_first_bar,
    )
    from transformer_train import train_transformer, prepare_transformer_data, SEQUENCE_LENGTH
    import pickle
    import numpy as np
    import torch

    _db = Path(db_path)

    used_feature_cache = False
    used_cascade_tensor_cache = False
    if data_fp is None:
        data_fp = db_training_fingerprint(db_path, ticker, label_column=label_col)
    if not code_fp:
        code_fp = compute_training_code_fingerprint()
    fk_computed = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=label_col)
    if feature_cache_key is not None:
        from features.training_canonical_input import TrainingCanonicalInputError

        if feature_cache_key != fk_computed:
            raise TrainingCanonicalInputError(
                "feature_cache_key override does not match computed shared key for this data/code/horizon"
            )
        fk = feature_cache_key
    else:
        fk = fk_computed
    fdir = feature_cache_dir(fk)

    if allowed_et_dates is not None:
        min_ts_tab = None
        min_ts_seq = None
    else:
        min_ts_tab = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_TABULAR, label_column=label_col,
        )
        min_ts_seq = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE, label_column=label_col,
        )
    _cascade_hist = max(int(SEQUENCE_LENGTH), int(STREAM_5M_LOOKBACK))

    def _ts_ok(snap) -> bool:
        if min_ts_seq is None:
            return True
        cts = snap.get("ts_utc")
        return cts is not None and float(cts) >= float(min_ts_seq)

    prior_fp = (prior_manifest or {}).get("data_fingerprint") if prior_manifest else None

    # Step 1: XGB
    df = load_data(
        db_path,
        ticker=ticker,
        min_ts_utc=min_ts_tab,
        allowed_et_dates=allowed_et_dates,
        ml_horizon_slug=hz,
    )
    if len(df) == 0:
        return {
            "used_feature_cache": False,
            "used_cascade_tensor_cache": False,
            "warm_resume": {},
        }
    train_ticker(
        ticker,
        df,
        model_dir=out_dir,
        prior_data_fingerprint=prior_fp,
        current_data_fingerprint=data_fp,
        ml_horizon_slug=hz,
    )

    xgb_path = out_dir / f"xgb_{ticker.upper()}_{hz}.pkl"
    xgb_meta_path = out_dir / f"xgb_{ticker.upper()}_{hz}_meta.json"
    if not xgb_path.exists():
        return {
            "used_feature_cache": False,
            "used_cascade_tensor_cache": False,
            "warm_resume": {},
        }
    with open(xgb_path, "rb") as f:
        xgb_model = pickle.load(f)
    with open(xgb_meta_path) as f:
        xgb_meta = json.load(f)

    from timeframe_config import CANONICAL_TIMEFRAME
    days_data = extract_rth_snapshots(
        ticker,
        timeframe=CANONICAL_TIMEFRAME,
        db_path=_db,
        require_outcome=True,
        allowed_et_dates=allowed_et_dates,
        target_column=label_col,
    )
    xgb_probs_list = []

    for day_key, snapshots in sorted(days_data.items()):
        n_snaps = len(snapshots)
        if n_snaps < STREAM_5M_LOOKBACK:
            continue
        for end_idx in range(STREAM_5M_LOOKBACK, n_snaps):
            window = snapshots[end_idx - STREAM_5M_LOOKBACK:end_idx]
            current = window[-1]
            if not _ts_ok(current):
                continue
            target_str = current.get(label_col)
            if target_str is None or target_str not in TARGET_CLASSES:
                continue
            ref_spot = _safe_float(window[0].get("spot"))
            if ref_spot <= 0:
                ref_spot = _safe_float(current.get("spot"))
            if ref_spot <= 0:
                continue
            X_row = engineer_single_snapshot(
                current, xgb_meta.get("category_maps", {}),
                xgb_meta.get("features", []),
                xgb_meta.get("vol_medians", {}), ticker,
            )
            if X_row is None:
                continue
            probs = xgb_model.predict_proba(X_row.values.astype(np.float64))[0]
            xgb_probs_list.append(probs)

    ds = None
    if not bypass_cache:
        ds = load_lstm_feature_cache(fdir, ticker, data_fp, fk)
    if ds is None:
        ds = build_lstm_dataset(
            tickers=[ticker],
            db_path=_db,
            min_ts_utc=min_ts_seq,
            allowed_et_dates=allowed_et_dates,
            ml_horizon_slug=hz,
        )
        if ds.n_samples > 0 and not bypass_cache:
            save_lstm_feature_cache(fdir, ticker, data_fp, fk, ds)
    else:
        used_feature_cache = True
        log.info("%s cascade: LSTM feature cache hit (%s)", ticker, fk[:12])

    lstm_rr: dict[str, Any] = {}
    if ds.n_samples < 10:
        return {
            "used_feature_cache": used_feature_cache,
            "used_cascade_tensor_cache": False,
            "warm_resume": lstm_rr,
        }
    if len(xgb_probs_list) != ds.n_samples:
        delta = len(xgb_probs_list) - ds.n_samples
        log.warning("%s: LSTM cascade — xgb_probs mismatch %d vs %d (delta=%d), falling back to parallel LSTM",
                    ticker, len(xgb_probs_list), ds.n_samples, delta)
        lr = train_lstm(
            dataset=ds,
            db_path=db_path,
            ticker=ticker,
            model_dir=out_dir,
            scheduler_cache_key=scheduler_cache_key or None,
            data_fp=data_fp,
            architecture="cascade",
            bypass_torch_resume=bypass_cache,
            ml_horizon_slug=hz,
        )
    else:
        xgb_probs = np.array(xgb_probs_list[: ds.n_samples], dtype=np.float32)
        lr = train_lstm(
            dataset=ds,
            db_path=db_path,
            ticker=ticker,
            model_dir=out_dir,
            xgb_probs=xgb_probs,
            scheduler_cache_key=scheduler_cache_key or None,
            data_fp=data_fp,
            architecture="cascade",
            bypass_torch_resume=bypass_cache,
            ml_horizon_slug=hz,
        )
    lstm_rr = {"lstm_warm_resume": lr.warm_resume_used, "lstm_warm_resume_detail": lr.warm_resume_detail}

    preload_tf = prepare_transformer_data(
        db_path,
        ticker,
        min_ts_utc=min_ts_seq,
        min_snapshots_before_sample=_cascade_hist,
        allowed_et_dates=allowed_et_dates,
        ml_horizon_slug=hz,
    )
    Xp, yp, daysp, tickp, nfp = preload_tf
    if Xp is None or yp is None or len(yp) < 10:
        return {
            "used_feature_cache": used_feature_cache,
            "used_cascade_tensor_cache": False,
            "warm_resume": lstm_rr,
        }

    lstm_pt_path = out_dir / f"lstm_{ticker.upper()}_{hz}.pt"
    xgb_lstm = None
    if not bypass_cache:
        xgb_lstm = load_cascade_transformer_tensor_cache(
            fdir, ticker, data_fp, fk, code_fp, xgb_meta_path, lstm_pt_path
        )
    if xgb_lstm is not None and xgb_lstm.shape[0] != len(yp):
        log.info("%s: cascade tensor cache row mismatch %d vs %d — rebuild",
                 ticker, xgb_lstm.shape[0], len(yp))
        xgb_lstm = None

    if xgb_lstm is None:
        lstm_model, lstm_ckpt = load_lstm(
            model_dir=out_dir, ticker=ticker, ml_horizon_slug=hz,
        )
        if lstm_model is None:
            return {
                "used_feature_cache": used_feature_cache,
                "used_cascade_tensor_cache": False,
                "warm_resume": lstm_rr,
            }

        lstm_model.eval()
        xgb_lstm_list = []
        for day_key, snapshots in sorted(days_data.items()):
            if len(snapshots) < _cascade_hist:
                continue
            for end_idx in range(_cascade_hist, len(snapshots)):
                window = snapshots[end_idx - SEQUENCE_LENGTH:end_idx]
                current = window[-1]
                if not _ts_ok(current):
                    continue
                if current.get(label_col) not in TARGET_CLASSES:
                    continue
                try:
                    ref_spot = canonical_reference_spot_from_sequence_window_first_bar(window)
                except ValueError:
                    continue
                X_row = engineer_single_snapshot(
                    current, xgb_meta.get("category_maps", {}),
                    xgb_meta.get("features", []),
                    xgb_meta.get("vol_medians", {}), ticker,
                )
                if X_row is None:
                    continue
                xgb_p = xgb_model.predict_proba(X_row.values.astype(np.float64))[0]

                lstm_window = snapshots[end_idx - STREAM_5M_LOOKBACK:end_idx]
                try:
                    lstm_ref = canonical_reference_spot_from_sequence_window_first_bar(lstm_window)
                except ValueError:
                    continue
                seq_5m = [
                    encode_snapshot_5m(training_snapshot_for_sequence_encode(s), lstm_ref)
                    for s in lstm_window
                ]
                micro = lstm_window[-STREAM_1M_LOOKBACK:]
                micro_ref = _safe_float(micro[0].get("spot")) or lstm_ref
                seq_1m = [
                    encode_snapshot_1m(training_snapshot_for_sequence_encode(s), micro_ref)
                    for s in micro
                ]
                snapshots_flat = [s for _, snaps in sorted(days_data.items()) for s in snaps]
                day_idx = min(
                    next((i for i, s in enumerate(snapshots_flat) if s.get("ts_et") == current.get("ts_et")), len(snapshots_flat) - 1),
                    len(snapshots_flat) - 1,
                )
                conf = compute_confluence_features(snapshots_flat, day_idx)
                conf_vec = np.array([conf[k] for k in CONFLUENCE_FEATURES], dtype=np.float32)
                conf_vec = np.hstack([conf_vec, xgb_p]).astype(np.float32)

                mask_5m = np.array(lstm_ckpt.get("mask_5m", [True] * len(seq_5m[0])))
                mask_1m = np.array(lstm_ckpt.get("mask_1m", [True] * len(seq_1m[0])))
                mask_conf = np.array(lstm_ckpt.get("mask_conf", [True] * len(conf_vec)))
                X_5m = np.array([seq_5m], dtype=np.float32)
                X_1m = np.array([seq_1m], dtype=np.float32)
                if len(mask_5m) == X_5m.shape[2]:
                    X_5m = X_5m[:, :, mask_5m]
                if len(mask_1m) == X_1m.shape[2]:
                    X_1m = X_1m[:, :, mask_1m]
                X_conf = np.array([conf_vec], dtype=np.float32)
                if len(mask_conf) == len(conf_vec):
                    X_conf = X_conf[:, mask_conf]
                norm = lstm_ckpt.get("norm_stats", {})
                if norm:
                    from lstm_model import align_lstm_norm_stats, apply_normalization

                    aligned = align_lstm_norm_stats(norm, mask_5m, mask_1m, mask_conf)
                    if aligned is None:
                        log.warning(
                            "%s cascade tensor: LSTM norm_stats / mask mismatch; skip row",
                            ticker,
                        )
                        continue
                    X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, aligned)
                X_5m = np.nan_to_num(X_5m, nan=0.0)
                X_1m = np.nan_to_num(X_1m, nan=0.0)
                X_conf = np.nan_to_num(X_conf, nan=0.0)
                with torch.no_grad():
                    logits = lstm_model(
                        torch.from_numpy(X_1m).float(),
                        torch.from_numpy(X_5m).float(),
                        torch.from_numpy(X_conf).float(),
                    )
                    lstm_p = torch.softmax(logits, dim=-1).squeeze().numpy()
                xgb_lstm_list.append(np.concatenate([xgb_p, lstm_p]))

        if len(xgb_lstm_list) < 10:
            return {
                "used_feature_cache": used_feature_cache,
                "used_cascade_tensor_cache": False,
                "warm_resume": lstm_rr,
            }
        xgb_lstm = np.array(xgb_lstm_list, dtype=np.float32)
        if not bypass_cache:
            save_cascade_transformer_tensor_cache(
                fdir, ticker, data_fp, fk, code_fp, xgb_meta_path, lstm_pt_path, xgb_lstm
            )
    else:
        used_cascade_tensor_cache = True
        log.info("%s cascade: Transformer tensor cache hit (%s)", ticker, fk[:12])

    tr = train_transformer(
        db_path=db_path,
        ticker=ticker,
        model_dir=out_dir,
        xgb_lstm_probs=xgb_lstm,
        preloaded_sequences=(Xp, yp, daysp, tickp, nfp),
        allowed_et_dates=allowed_et_dates,
        scheduler_cache_key=scheduler_cache_key or None,
        data_fp=data_fp,
        architecture="cascade",
        bypass_torch_resume=bypass_cache,
        ml_horizon_slug=hz,
    )
    warm_resume = {
        **lstm_rr,
        "transformer_warm_resume": tr.warm_resume_used,
        "transformer_warm_resume_detail": tr.warm_resume_detail,
    }
    return {
        "used_feature_cache": used_feature_cache,
        "used_cascade_tensor_cache": used_cascade_tensor_cache,
        "warm_resume": warm_resume,
    }


def _train_cascade(
    ticker: str,
    db_path: str,
    *,
    out_dir: Optional[Path] = None,
    allowed_et_dates: Optional[Set[str]] = None,
    bypass_cache: bool = False,
    data_fp: Optional[dict] = None,
    code_fp: str = "",
    scheduler_cache_key: str = "",
    feature_cache_key: Optional[str] = None,
    prior_manifest: Optional[dict] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    """Production entry: same as nightly scheduler; optional out_dir / allowed_et_dates for compare tooling."""
    dest = out_dir if out_dir is not None else CASCADE_DIR / ticker
    return train_cascade_candidate(
        ticker,
        db_path,
        dest,
        bypass_cache=bypass_cache,
        data_fp=data_fp,
        code_fp=code_fp,
        scheduler_cache_key=scheduler_cache_key,
        feature_cache_key=feature_cache_key,
        allowed_et_dates=allowed_et_dates,
        prior_manifest=prior_manifest,
        ml_horizon_slug=ml_horizon_slug,
    )


def _artifact_paths_relative(out_dir: Path, ticker: str, *, horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG) -> dict[str, str]:
    from training_cache import parallel_artifact_basenames

    rel: dict[str, str] = {}
    for n in parallel_artifact_basenames(ticker, horizon_suffix=horizon_suffix):
        p = out_dir / n
        if p.exists():
            try:
                rel[n] = str(p.relative_to(MODEL_DIR))
            except ValueError:
                rel[n] = str(p.resolve())
    return rel


def run_once(
    wait: bool = False,
    force_retrain: bool = False,
    bypass_cache: bool = False,
    *,
    allow_non_market_day: bool = False,
    promote_from_manifests_only: bool = False,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
):
    if wait:
        _wait_until_1615()
    now = _now_et()
    if not allow_non_market_day and not _is_market_day(now):
        log.info(
            "Skipping - not a market day (scheduled mode). "
            "Use --run-now to train on any calendar day when data exists."
        )
        return

    hz_sched = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz_sched)
    arch_target_path = scheduler_arch_state_path(hz_sched)
    log.info(
        "ML scheduler run started at %s ET (ml_horizon=%s, label=%s, arch_state=%s)",
        now.strftime("%H:%M"),
        hz_sched,
        target_column,
        arch_target_path.name,
    )

    if not Path(DB_PATH).exists():
        log.warning("DB not found at %s", DB_PATH)
        return

    try:
        from normalized_training_sync import ensure_normalized_training_table

        _ns = ensure_normalized_training_table(DB_PATH, force=False, logger=log)
        if not _ns.get("ok"):
            log.warning("normalized_training_sync failed before training: %s", _ns.get("errors"))
        elif _ns.get("materialized"):
            log.info(
                "snapshots_1m_normalized rematerialized: %s rows",
                (_ns.get("materialize") or {}).get("normalized_rows"),
            )
    except Exception as _e:
        log.warning("normalized_training_sync error (continuing): %s", _e)

    tickers = _training_ticker_union(DB_PATH, label_column=target_column)
    if not tickers:
        log.warning(
            "No tickers: logging_universe enrollment empty. "
            "Enroll via UI/API (user_persisted/pinned), ensure sync_core rows exist, or run server once; "
            "legacy user_scheduler_tickers.json migrates once. "
            "Training also needs labeled RTH rows per ticker in snapshots_1m_normalized."
        )
        return
    try:
        db_only = _diagnostic_db_tickers_not_enrolled(DB_PATH, tickers, label_column=target_column)
        if db_only:
            log.info(
                "Diagnostic (not enrolled): %d ticker(s) have labeled RTH rows but are absent from "
                "logging_universe — skipped unless enrolled: %s%s",
                len(db_only),
                db_only[:30],
                "…" if len(db_only) > 30 else "",
            )
    except Exception:
        pass

    _subset = (os.environ.get("ED_ML_SCHEDULER_TICKERS") or "").strip()
    if _subset:
        want = {t.strip().upper() for t in _subset.split(",") if t.strip()}
        before = len(tickers)
        tickers = [t for t in tickers if t in want]
        log.info(
            "ED_ML_SCHEDULER_TICKERS filter: %d of %d enrolled tickers selected",
            len(tickers),
            before,
        )

    _pfx = " (promote-from-manifests-only)" if promote_from_manifests_only else ""
    log.info("Tickers (logging_universe authoritative): %s%s", tickers, _pfx)

    arch_state = {}
    if arch_target_path.exists():
        try:
            arch_state = json.loads(arch_target_path.read_text())
        except Exception:
            arch_state = {}

    for ticker in tickers:
        try:
            from training_cache import (
                db_training_fingerprint,
                compute_training_code_fingerprint,
                compute_scheduler_cache_key,
                compute_feature_cache_key,
                load_run_manifest,
                save_run_manifest,
                build_manifest,
                full_skip_eligible,
                compute_artifact_sha256_map,
                parallel_artifact_basenames,
                cascade_artifact_basenames,
                archive_candidate_directory_before_train,
            )
            from training_cache_policy import (
                ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                MAX_CONSECUTIVE_SCHEDULER_SKIPS,
            )
            from training_provenance import (
                load_provenance,
                validate_for_promotion,
                TrainingProvenance,
                is_provenance_compliant,
            )
            from timeframe_config import CANONICAL_TIMEFRAME

            data_fp = db_training_fingerprint(DB_PATH, ticker, label_column=target_column)
            if int(data_fp.get("row_count") or 0) < 1:
                log.info(
                    "%s: skip — no RTH labeled rows for %s in snapshots_1m_normalized (needed for training)",
                    ticker,
                    target_column,
                )
                continue
            code_fp = compute_training_code_fingerprint()
            fk = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=target_column)
            parallel_key = compute_scheduler_cache_key(
                ticker, "parallel", data_fp, code_fp, target_column=target_column,
            )
            cascade_key = compute_scheduler_cache_key(
                ticker, "cascade", data_fp, code_fp, target_column=target_column,
            )
            parallel_out = PARALLEL_DIR / ticker
            cascade_out = CASCADE_DIR / ticker
            run_ts = _now_et().isoformat()
            utc_now = datetime.now(timezone.utc)

            if promote_from_manifests_only:
                parallel_man = load_run_manifest(parallel_out)
                cascade_man = load_run_manifest(cascade_out)
                if not parallel_man or not cascade_man:
                    log.warning(
                        "%s: --promote-from-manifests skipped (parallel and/or cascade manifest missing)",
                        ticker,
                    )
                    continue
                pe = parallel_man.get("evaluation") or {}
                ce = cascade_man.get("evaluation") or {}
                if not pe or not ce:
                    log.warning(
                        "%s: --promote-from-manifests skipped (evaluation missing)",
                        ticker,
                    )
                    continue
                mf_hz = normalize_ml_horizon_slug(
                    parallel_man.get("ml_horizon_suffix") or cascade_man.get("ml_horizon_suffix") or hz_sched
                )
                if not (parallel_out / f"xgb_{ticker.upper()}_{mf_hz}.pkl").exists():
                    log.warning(
                        "%s: --promote-from-manifests skipped (parallel xgb missing for horizon %s)",
                        ticker,
                        mf_hz,
                    )
                    continue
                if not (cascade_out / f"xgb_{ticker.upper()}_{mf_hz}.pkl").exists():
                    log.warning(
                        "%s: --promote-from-manifests skipped (cascade xgb missing for horizon %s)",
                        ticker,
                        mf_hz,
                    )
                    continue
                mf_code = parallel_man.get("training_code_fingerprint")
                code_fp = mf_code if isinstance(mf_code, str) and mf_code else compute_training_code_fingerprint()
                mf_df = parallel_man.get("data_fingerprint")
                data_fp = mf_df if isinstance(mf_df, dict) and mf_df else data_fp
                fk_mf = parallel_man.get("feature_cache_key")
                _tc_promo = outcome_column(mf_hz)
                fk = fk_mf if isinstance(fk_mf, str) and fk_mf else compute_feature_cache_key(
                    ticker, data_fp, code_fp, target_column=_tc_promo,
                )
                pk_mf = parallel_man.get("scheduler_cache_key")
                parallel_key = (
                    pk_mf
                    if isinstance(pk_mf, str) and pk_mf
                    else compute_scheduler_cache_key(
                        ticker, "parallel", data_fp, code_fp, target_column=_tc_promo,
                    )
                )
                ck_mf = cascade_man.get("scheduler_cache_key")
                cascade_key = (
                    ck_mf
                    if isinstance(ck_mf, str) and ck_mf
                    else compute_scheduler_cache_key(
                        ticker, "cascade", data_fp, code_fp, target_column=_tc_promo,
                    )
                )
                par_streak_prev = int(parallel_man.get("consecutive_scheduler_skips", 0) or 0)
                cas_streak_prev = int(cascade_man.get("consecutive_scheduler_skips", 0) or 0)
                par_skip_reason = "promote_from_manifests_only"
                cas_skip_reason = "promote_from_manifests_only"
                par_retrain_reason = None
                cas_retrain_reason = None
                par_miss_reason = None
                cas_miss_reason = None
                parallel_skip = True
                cascade_skip = True
                evp = pe
                evc = ce
                parallel_acc = float(evp.get("eval_accuracy", 0.0))
                parallel_bal = float(evp.get("balanced_accuracy", 0.0))
                n_rows = int(evp.get("n_rows", 0))
                parallel_ll = evp.get("eval_log_loss")
                if parallel_ll is not None:
                    parallel_ll = float(parallel_ll)
                _prm = evp.get("realized_contract_metrics")
                parallel_realized_metrics = (
                    dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                )
                cascade_acc = float(evc.get("eval_accuracy", 0.0))
                cascade_bal = float(evc.get("balanced_accuracy", 0.0))
                n_cascade_rows = int(evc.get("n_rows", 0))
                cascade_ll = evc.get("eval_log_loss")
                if cascade_ll is not None:
                    cascade_ll = float(cascade_ll)
                _crm = evc.get("realized_contract_metrics")
                cascade_realized_metrics = (
                    dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                )
                par_skipped_train = True
                par_skipped_eval = True
                cas_skipped_train = True
                cas_skipped_eval = True
                par_used_fc = bool(parallel_man.get("used_feature_cache", False))
                par_used_ctc = bool(parallel_man.get("used_cascade_tensor_cache", False))
                pm_trained_at = str(parallel_man.get("trained_at", run_ts))
                par_warm_resume = parallel_man.get("warm_resume") or {}
                cas_used_fc = bool(cascade_man.get("used_feature_cache", False))
                cas_used_ctc = bool(cascade_man.get("used_cascade_tensor_cache", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
                log.info("%s: --promote-from-manifests (no training; eval from manifest)", ticker)
            else:
                parallel_man = load_run_manifest(parallel_out) if not bypass_cache else None
                cascade_man = load_run_manifest(cascade_out) if not bypass_cache else None

                par_streak_prev = int(parallel_man.get("consecutive_scheduler_skips", 0) or 0) if parallel_man else 0
                cas_streak_prev = int(cascade_man.get("consecutive_scheduler_skips", 0) or 0) if cascade_man else 0
                par_inhibit = (
                    not bypass_cache
                    and not force_retrain
                    and MAX_CONSECUTIVE_SCHEDULER_SKIPS > 0
                    and par_streak_prev >= MAX_CONSECUTIVE_SCHEDULER_SKIPS
                )
                cas_inhibit = (
                    not bypass_cache
                    and not force_retrain
                    and MAX_CONSECUTIVE_SCHEDULER_SKIPS > 0
                    and cas_streak_prev >= MAX_CONSECUTIVE_SCHEDULER_SKIPS
                )
                if par_inhibit:
                    log.info(
                        "%s: parallel — consecutive skips %d >= cap %d, forcing train",
                        ticker,
                        par_streak_prev,
                        MAX_CONSECUTIVE_SCHEDULER_SKIPS,
                    )
                if cas_inhibit:
                    log.info(
                        "%s: cascade — consecutive skips %d >= cap %d, forcing train",
                        ticker,
                        cas_streak_prev,
                        MAX_CONSECUTIVE_SCHEDULER_SKIPS,
                    )

                par_elig, par_skip_reason, par_retrain_reason, par_miss_reason = full_skip_eligible(
                    parallel_man,
                    parallel_key,
                    data_fp,
                    code_fp,
                    parallel_out,
                    ticker,
                    "parallel",
                    bypass_cache=bypass_cache,
                    force_retrain=force_retrain,
                    skip_inhibit_reason="max_consecutive_scheduler_skips" if par_inhibit else None,
                    now=utc_now,
                    horizon_suffix=hz_sched,
                )
                parallel_skip = par_elig

                cas_elig, cas_skip_reason, cas_retrain_reason, cas_miss_reason = full_skip_eligible(
                    cascade_man,
                    cascade_key,
                    data_fp,
                    code_fp,
                    cascade_out,
                    ticker,
                    "cascade",
                    bypass_cache=bypass_cache,
                    force_retrain=force_retrain,
                    skip_inhibit_reason="max_consecutive_scheduler_skips" if cas_inhibit else None,
                    now=utc_now,
                    horizon_suffix=hz_sched,
                )
                cascade_skip = cas_elig

            if not promote_from_manifests_only:
                parallel_ll: Optional[float] = None
                parallel_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                cascade_ll: Optional[float] = None
                cascade_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                n_cascade_rows: int = 0

            if not promote_from_manifests_only and parallel_skip:
                log.info("%s: parallel scheduler cache hit — skip train + eval (key=%s…)", ticker, parallel_key[:12])
                evp = parallel_man.get("evaluation") or {}
                parallel_acc = float(evp.get("eval_accuracy", 0.0))
                parallel_bal = float(evp.get("balanced_accuracy", 0.0))
                n_rows = int(evp.get("n_rows", 0))
                parallel_ll = evp.get("eval_log_loss")
                _prm = evp.get("realized_contract_metrics")
                parallel_realized_metrics = (
                    dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                )
                if parallel_ll is not None:
                    parallel_ll = float(parallel_ll)
                par_skipped_train = True
                par_skipped_eval = True
                par_used_fc = bool(parallel_man.get("used_feature_cache", False))
                par_used_ctc = bool(parallel_man.get("used_cascade_tensor_cache", False))
                pm_trained_at = str(parallel_man.get("trained_at", run_ts))
                par_warm_resume = parallel_man.get("warm_resume") or {}
            elif not promote_from_manifests_only:
                log.info("%s: Training parallel...", ticker)
                archive_candidate_directory_before_train(parallel_out, MODEL_DIR, "parallel", ticker)
                par_ret = _train_parallel(
                    ticker,
                    DB_PATH,
                    bypass_cache=bypass_cache,
                    data_fp=data_fp,
                    code_fp=code_fp,
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    prior_manifest=parallel_man,
                    ml_horizon_slug=hz_sched,
                )
                parallel_acc, parallel_bal, n_rows, parallel_ll, parallel_realized_metrics = (
                    _evaluate_parallel_on_full_rth(
                        DB_PATH, ticker, parallel_out, target_column=target_column,
                    )
                )
                par_skipped_train = False
                par_skipped_eval = False
                par_used_fc = bool(par_ret.get("used_feature_cache", False))
                par_used_ctc = bool(par_ret.get("used_cascade_tensor_cache", False))
                pm_trained_at = run_ts
                par_warm_resume = par_ret.get("warm_resume") or {}

            if not promote_from_manifests_only and cascade_skip:
                log.info("%s: cascade scheduler cache hit — skip train + eval (key=%s…)", ticker, cascade_key[:12])
                evc = cascade_man.get("evaluation") or {}
                cascade_acc = float(evc.get("eval_accuracy", 0.0))
                cascade_bal = float(evc.get("balanced_accuracy", 0.0))
                n_cascade_rows = int(evc.get("n_rows", 0))
                cascade_ll = evc.get("eval_log_loss")
                _crm = evc.get("realized_contract_metrics")
                cascade_realized_metrics = (
                    dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                )
                if cascade_ll is not None:
                    cascade_ll = float(cascade_ll)
                cas_skipped_train = True
                cas_skipped_eval = True
                cas_used_fc = bool(cascade_man.get("used_feature_cache", False))
                cas_used_ctc = bool(cascade_man.get("used_cascade_tensor_cache", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
            elif not promote_from_manifests_only:
                log.info("%s: Training cascade...", ticker)
                archive_candidate_directory_before_train(cascade_out, MODEL_DIR, "cascade", ticker)
                cas_ret = _train_cascade(
                    ticker,
                    DB_PATH,
                    bypass_cache=bypass_cache,
                    data_fp=data_fp,
                    code_fp=code_fp,
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    prior_manifest=cascade_man,
                    ml_horizon_slug=hz_sched,
                )
                cascade_acc, cascade_bal, n_cascade_rows, cascade_ll, cascade_realized_metrics = (
                    _evaluate_cascade_on_full_rth(
                        DB_PATH, ticker, cascade_out, target_column=target_column,
                    )
                )
                cas_skipped_train = False
                cas_skipped_eval = False
                cas_used_fc = bool(cas_ret.get("used_feature_cache", False))
                cas_used_ctc = bool(cas_ret.get("used_cascade_tensor_cache", False))
                cm_trained_at = run_ts
                cas_warm_resume = cas_ret.get("warm_resume") or {}

            governed_slice: Optional[dict[str, Any]] = None
            governed_paths: Optional[dict[str, str]] = None
            try:
                from arch_competition.scheduler_integration import (
                    build_governed_arch_state_slice,
                    run_governed_architecture_competition_pass,
                    scheduler_auto_promote_to_active_enabled,
                )

                _gov = run_governed_architecture_competition_pass(
                    model_dir=MODEL_DIR,
                    db_path=DB_PATH,
                    ticker=ticker,
                    parallel_model_dir=parallel_out,
                    cascade_model_dir=cascade_out,
                    ml_horizon_slug=hz_sched,
                    allowed_et_dates=None,
                )
                _man = _gov["evaluation_manifest"]
                _prec = _gov["promotion_record"]
                governed_paths = _gov["paths"]
                parallel_acc = float(_man["metrics"]["parallel"]["accuracy"])
                parallel_bal = float(_man["metrics"]["parallel"]["balanced_accuracy"])
                n_rows = int(_man["metrics"]["parallel"]["n_rows_scored"])
                _pll = _man["metrics"]["parallel"].get("log_loss")
                parallel_ll = float(_pll) if _pll is not None else None
                _prm = _man["metrics"]["parallel"].get("realized_contract_metrics")
                parallel_realized_metrics = (
                    dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                )
                cascade_acc = float(_man["metrics"]["cascade"]["accuracy"])
                cascade_bal = float(_man["metrics"]["cascade"]["balanced_accuracy"])
                n_cascade_rows = int(_man["metrics"]["cascade"]["n_rows_scored"])
                _cll = _man["metrics"]["cascade"].get("log_loss")
                cascade_ll = float(_cll) if _cll is not None else None
                _crm = _man["metrics"]["cascade"].get("realized_contract_metrics")
                cascade_realized_metrics = (
                    dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                )
                governed_slice = build_governed_arch_state_slice(
                    manifest=_man,
                    promotion_record=_prec,
                    paths=_gov["paths"],
                    auto_promote_to_active=scheduler_auto_promote_to_active_enabled(),
                )
            except Exception as _gov_e:
                log.exception("%s: governed architecture competition pass failed: %s", ticker, _gov_e)
                governed_slice = {
                    "schema_version": "1",
                    "error": str(_gov_e),
                    "failed_closed": True,
                }

            try:
                from realized_contract_eval import save_eval_aggregate_merge

                if not parallel_skip:
                    save_eval_aggregate_merge(ticker, "parallel", parallel_realized_metrics, run_ts)
                if not cascade_skip:
                    save_eval_aggregate_merge(ticker, "cascade", cascade_realized_metrics, run_ts)
            except Exception as _sa_e:
                log.warning("realized aggregate save: %s", _sa_e)

            active_root = scheduler_active_root(hz_sched)
            active_dir = active_root / ticker
            active_dir.mkdir(parents=True, exist_ok=True)

            parallel_xgb_meta = parallel_out / f"xgb_{ticker.upper()}_{hz_sched}_meta.json"
            cascade_xgb_meta = cascade_out / f"xgb_{ticker.upper()}_{hz_sched}_meta.json"
            parallel_prov = load_provenance(parallel_xgb_meta) if parallel_xgb_meta.exists() else None
            cascade_prov = load_provenance(cascade_xgb_meta) if cascade_xgb_meta.exists() else None

            existing_meta = active_dir / f"xgb_{ticker.upper()}_{hz_sched}_meta.json"
            existing_prov = load_provenance(existing_meta) if existing_meta.exists() else None

            promoted_at_str = _now_et().strftime("%Y-%m-%d %H:%M:%S ET")

            # Issue 11: --force-retrain must allow promoting fresh contract-complete artifacts when
            # active models fail loader contract (label_config_version, etc.) even if legacy
            # TrainingProvenance still looks "compliant" to is_provenance_compliant().
            _active_contract_broken = False
            if force_retrain and active_dir.exists() and hz_sched == DEFAULT_ML_HORIZON_SLUG:
                try:
                    from verify_active_models import check_artifact_compliance

                    _acr = check_artifact_compliance(ticker)
                    _active_contract_broken = not _acr.get("compliant", False)
                except Exception:
                    _active_contract_broken = False

            _force_replace = bool(
                force_retrain
                and (
                    (
                        existing_prov is not None
                        and not is_provenance_compliant(existing_prov, horizon_slug=hz_sched)
                    )
                    or _active_contract_broken
                )
            )
            # Loader contract broken: do not block promotion on legacy promotion_score alone.
            _promotion_existing_prov = (
                None if (force_retrain and _active_contract_broken) else existing_prov
            )

            def _promote_candidate(
                acc: float,
                bal_acc: Optional[float],
                prov: Optional[TrainingProvenance],
                src_dir: Path,
                arch_name: str,
            ) -> tuple[bool, str]:
                if not prov:
                    return False, "missing provenance"
                ok, reason = validate_for_promotion(
                    prov,
                    acc,
                    _promotion_existing_prov,
                    balanced_accuracy=bal_acc,
                    force_replace_non_compliant=_force_replace,
                    horizon_slug=hz_sched,
                )
                if not ok:
                    return False, reason
                for f in src_dir.glob("*"):
                    if f.is_file():
                        shutil.copy2(f, active_dir / f.name)
                for meta_name in parallel_artifact_basenames(ticker, horizon_suffix=hz_sched):
                    if not str(meta_name).endswith("_meta.json"):
                        continue
                    mp = active_dir / meta_name
                    if mp.exists():
                        try:
                            m = json.loads(mp.read_text())
                            m["promoted_at"] = promoted_at_str
                            m["promotion_score"] = acc
                            m["promotion_metric"] = "eval_accuracy"
                            if bal_acc is not None:
                                m["balanced_accuracy"] = bal_acc
                            mp.write_text(json.dumps(m, indent=2))
                        except Exception:
                            pass
                return True, "ok"

            pprov = parallel_prov or cascade_prov
            report = {
                "ticker": ticker,
                "model_type": "ensemble",
                "training_timeframe": CANONICAL_TIMEFRAME,
                "ml_horizon_suffix": hz_sched,
                "target_column": target_column,
                "target_definition": horizon_target_definition(hz_sched),
                "train_start": pprov.train_start if pprov else "",
                "train_end": pprov.train_end if pprov else "",
                "rows_used": n_rows,
                "eval_accuracy": round(parallel_acc, 4),
                "eval_accuracy_cascade": round(cascade_acc, 4),
                "balanced_accuracy": round(parallel_bal, 4),
                "balanced_accuracy_cascade": round(cascade_bal, 4),
                "eval_log_loss": round(parallel_ll, 6) if parallel_ll is not None else None,
                "eval_log_loss_cascade": round(cascade_ll, 6) if cascade_ll is not None else None,
                "eval_pnl_realized_contract": parallel_realized_metrics.get("eval_pnl_realized_contract"),
                "eval_pnl_realized_contract_cascade": cascade_realized_metrics.get(
                    "eval_pnl_realized_contract"
                ),
                "realized_contract_metrics": parallel_realized_metrics,
                "realized_contract_metrics_cascade": cascade_realized_metrics,
                "realized_parallel_cascade_comparison": None,
                "promoted": False,
                "promotion_reason": "",
                "rejection_reason": "",
                "parallel_cache_skip": parallel_skip,
                "cascade_cache_skip": cascade_skip,
                "bypass_cache": bypass_cache,
                "governed_competition": governed_slice,
                "governed_artifact_paths": governed_paths,
                "auto_promote_to_active": _scheduler_auto_promote_to_active(),
            }
            try:
                from realized_contract_eval import compare_parallel_cascade_trade_logs

                report["realized_parallel_cascade_comparison"] = compare_parallel_cascade_trade_logs()
            except Exception:
                pass

            # Primary comparison: lower log loss wins; tie → accuracy → balanced accuracy → realized contract PnL (avg $ / valid trade).
            _par_avg = parallel_realized_metrics.get("eval_pnl_realized_contract")
            _cas_avg = cascade_realized_metrics.get("eval_pnl_realized_contract")
            _pnl_tie_parallel = (
                (float("-inf") if _par_avg is None else float(_par_avg))
                >= (float("-inf") if _cas_avg is None else float(_cas_avg))
            )
            if parallel_ll is not None and cascade_ll is not None:
                parallel_wins = parallel_ll < cascade_ll - 1e-9 or (
                    abs(parallel_ll - cascade_ll) <= 1e-9
                    and (
                        parallel_acc > cascade_acc
                        or (
                            parallel_acc == cascade_acc
                            and (
                                parallel_bal > cascade_bal
                                or (parallel_bal == cascade_bal and _pnl_tie_parallel)
                            )
                        )
                    )
                )
            else:
                parallel_wins = parallel_acc > cascade_acc or (
                    parallel_acc == cascade_acc and parallel_bal >= cascade_bal
                )

            promoted = False
            reason = ""
            auto_active = _scheduler_auto_promote_to_active()
            if parallel_wins:
                if auto_active:
                    promoted, reason = _promote_candidate(
                        parallel_acc, parallel_bal, parallel_prov, parallel_out, "parallel"
                    )
                else:
                    promoted, reason = False, "scheduler does not copy to active/ (use arch_competition.manual_control)"
                report["promoted"] = promoted
                report["promotion_reason"] = (
                    f"parallel (acc={parallel_acc:.2%}, bal={parallel_bal:.2%})" if promoted else ""
                )
                if not auto_active and not promoted:
                    report["promotion_reason"] = (
                        f"parallel_wins_log_loss (no active copy; {reason})"
                    )
                report["rejection_reason"] = reason if not promoted else ""
                arch_state[ticker] = {
                    "active_architecture": "parallel" if promoted else arch_state.get(ticker, {}).get("active_architecture", "none"),
                    "parallel_acc": round(parallel_acc, 4),
                    "cascade_acc": round(cascade_acc, 4),
                    "parallel_balanced_acc": round(parallel_bal, 4),
                    "cascade_balanced_acc": round(cascade_bal, 4),
                    "last_trained_at": _now_et().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows_at_training": n_rows,
                    "promoted": promoted,
                    "promotion_reason": reason if not promoted else "ok",
                    "provenance": parallel_prov.to_dict()
                    if parallel_prov and promoted
                    else (arch_state.get(ticker, {}).get("provenance")),
                }
                if promoted:
                    log.info("PARALLEL promoted %s: acc=%.1f%% bal=%.1f%%", ticker, parallel_acc * 100, parallel_bal * 100)
                else:
                    log.info("PARALLEL not promoted %s: %s", ticker, reason)
            else:
                if auto_active:
                    promoted, reason = _promote_candidate(
                        cascade_acc, cascade_bal, cascade_prov, cascade_out, "cascade"
                    )
                else:
                    promoted, reason = False, "scheduler does not copy to active/ (use arch_competition.manual_control)"
                report["promoted"] = promoted
                report["promotion_reason"] = (
                    f"cascade (acc={cascade_acc:.2%}, bal={cascade_bal:.2%})" if promoted else ""
                )
                if not auto_active and not promoted:
                    report["promotion_reason"] = (
                        f"cascade_wins_log_loss (no active copy; {reason})"
                    )
                report["rejection_reason"] = reason if not promoted else ""
                arch_state[ticker] = {
                    "active_architecture": "cascade" if promoted else arch_state.get(ticker, {}).get("active_architecture", "none"),
                    "parallel_acc": round(parallel_acc, 4),
                    "cascade_acc": round(cascade_acc, 4),
                    "parallel_balanced_acc": round(parallel_bal, 4),
                    "cascade_balanced_acc": round(cascade_bal, 4),
                    "last_trained_at": _now_et().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows_at_training": n_rows,
                    "promoted": promoted,
                    "promotion_reason": reason if not promoted else "ok",
                    "provenance": cascade_prov.to_dict()
                    if cascade_prov and promoted
                    else (arch_state.get(ticker, {}).get("provenance")),
                }
                if promoted:
                    log.info("CASCADE promoted %s: acc=%.1f%% bal=%.1f%%", ticker, cascade_acc * 100, cascade_bal * 100)
                else:
                    log.info("CASCADE not promoted %s: %s", ticker, reason)

            if governed_slice is not None:
                arch_state[ticker]["governed_competition"] = governed_slice

            promotion_decision_record = {
                "winner": "parallel" if parallel_wins else "cascade",
                "primary_metric": "eval_log_loss",
                "promoted_to_active": promoted,
                "promotion_reason": report["promotion_reason"],
                "rejection_reason": report["rejection_reason"],
                "ml_horizon_suffix": hz_sched,
                "target_column": target_column,
                "governed_promotion_decision": (
                    None
                    if not governed_slice or governed_slice.get("failed_closed")
                    else governed_slice.get("latest_promotion_decision")
                ),
                "governed_evaluation_paths": governed_paths,
                "auto_promote_to_active": auto_active,
            }

            try:
                from eval_metrics_store import save_arch_eval_proof_merge, save_dashboard_eval_metrics

                _prev = {}
                try:
                    from eval_metrics_store import load_dashboard_eval_metrics

                    _prev = load_dashboard_eval_metrics()
                except Exception:
                    pass
                _prev["updated_at"] = run_ts
                _prev["primary_metric"] = "eval_log_loss"
                _prev["realized_contract_pricing"] = (
                    "entry=ask exit=bid; underlying stop/target/time exit per Call plan; "
                    "trade logs: models/realized_contract_trade_log_parallel.csv + _cascade.csv"
                )
                _prev[ticker] = {
                    "parallel": {
                        "eval_accuracy": parallel_acc,
                        "balanced_accuracy": parallel_bal,
                        "eval_log_loss": parallel_ll,
                        "eval_pnl_realized_contract": parallel_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "realized_contract_metrics": parallel_realized_metrics,
                        "n_rows": n_rows,
                    },
                    "cascade": {
                        "eval_accuracy": cascade_acc,
                        "balanced_accuracy": cascade_bal,
                        "eval_log_loss": cascade_ll,
                        "eval_pnl_realized_contract": cascade_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "realized_contract_metrics": cascade_realized_metrics,
                        "n_rows": n_cascade_rows,
                    },
                    "winner": "parallel" if parallel_wins else "cascade",
                }
                save_dashboard_eval_metrics(_prev)
                from realized_contract_eval import (
                    TRADE_LOG_PARALLEL,
                    TRADE_LOG_CASCADE,
                    aggregate_path,
                    compare_parallel_cascade_trade_logs,
                )

                _pw = "parallel" if parallel_wins else "cascade"
                save_arch_eval_proof_merge(
                    ticker,
                    {
                        "updated_at": run_ts,
                        "parallel_eval_log_loss": parallel_ll,
                        "cascade_eval_log_loss": cascade_ll,
                        "parallel_eval_accuracy": parallel_acc,
                        "cascade_eval_accuracy": cascade_acc,
                        "parallel_eval_pnl_realized_contract": parallel_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "cascade_eval_pnl_realized_contract": cascade_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "comparison_winner_by_log_loss": _pw,
                        "final_promoted_winner": (_pw if promoted else None),
                        "promoted_to_active": promoted,
                        "primary_metric": "eval_log_loss",
                        "trade_log_path_parallel": str(TRADE_LOG_PARALLEL.resolve()),
                        "trade_log_path_cascade": str(TRADE_LOG_CASCADE.resolve()),
                        "parallel_cascade_trade_log_comparison": compare_parallel_cascade_trade_logs(),
                        "aggregate_metrics_path": str(aggregate_path().resolve()),
                    },
                )
            except Exception as _em_e:
                log.warning("eval_metrics_store: %s", _em_e)

            par_skip_streak_next = (par_streak_prev + 1) if parallel_skip else 0
            cas_skip_streak_next = (cas_streak_prev + 1) if cascade_skip else 0

            par_sha = compute_artifact_sha256_map(
                parallel_out, parallel_artifact_basenames(ticker, horizon_suffix=hz_sched),
            )
            cas_sha = compute_artifact_sha256_map(
                cascade_out, cascade_artifact_basenames(ticker, horizon_suffix=hz_sched),
            )

            save_run_manifest(
                parallel_out,
                build_manifest(
                    ticker=ticker,
                    architecture="parallel",
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    trained_at=pm_trained_at,
                    artifact_rel_paths=_artifact_paths_relative(
                        parallel_out, ticker, horizon_suffix=hz_sched,
                    ),
                    artifact_sha256=par_sha,
                    training_code_fingerprint=code_fp,
                    evaluation={
                        "realized_contract_eval_ref": "realized_contract_eval.py",
                        "eval_accuracy": round(parallel_acc, 6),
                        "balanced_accuracy": round(parallel_bal, 6),
                        "n_rows": n_rows,
                        **(
                            {"eval_log_loss": round(parallel_ll, 6)}
                            if parallel_ll is not None
                            else {}
                        ),
                        "realized_contract_metrics": parallel_realized_metrics,
                    },
                    promotion_decision=promotion_decision_record,
                    skipped_train=par_skipped_train,
                    skipped_eval=par_skipped_eval,
                    used_feature_cache=par_used_fc,
                    used_cascade_tensor_cache=par_used_ctc,
                    rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    consecutive_scheduler_skips=par_skip_streak_next,
                    skip_reason=par_skip_reason if parallel_skip else None,
                    retrain_reason=(None if parallel_skip else (par_retrain_reason or "trained_fresh")),
                    cache_miss_reason=(None if parallel_skip else par_miss_reason),
                    warm_resume=par_warm_resume,
                    ml_horizon_suffix=hz_sched,
                ),
            )
            save_run_manifest(
                cascade_out,
                build_manifest(
                    ticker=ticker,
                    architecture="cascade",
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    trained_at=cm_trained_at,
                    artifact_rel_paths=_artifact_paths_relative(
                        cascade_out, ticker, horizon_suffix=hz_sched,
                    ),
                    artifact_sha256=cas_sha,
                    training_code_fingerprint=code_fp,
                    evaluation={
                        "realized_contract_eval_ref": "realized_contract_eval.py",
                        "eval_accuracy": round(cascade_acc, 6),
                        "balanced_accuracy": round(cascade_bal, 6),
                        "n_rows": n_cascade_rows,
                        **(
                            {"eval_log_loss": round(cascade_ll, 6)}
                            if cascade_ll is not None
                            else {}
                        ),
                        "realized_contract_metrics": cascade_realized_metrics,
                    },
                    promotion_decision=promotion_decision_record,
                    skipped_train=cas_skipped_train,
                    skipped_eval=cas_skipped_eval,
                    used_feature_cache=cas_used_fc,
                    used_cascade_tensor_cache=cas_used_ctc,
                    rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    consecutive_scheduler_skips=cas_skip_streak_next,
                    skip_reason=cas_skip_reason if cascade_skip else None,
                    retrain_reason=(None if cascade_skip else (cas_retrain_reason or "trained_fresh")),
                    cache_miss_reason=(None if cascade_skip else cas_miss_reason),
                    warm_resume=cas_warm_resume,
                    ml_horizon_suffix=hz_sched,
                ),
            )

            _append_training_report(report)

        except Exception as e:
            log.exception("%s: failed: %s", ticker, e)

    try:
        from training_cache import cleanup_feature_cache_directories, prune_model_archives

        _n_removed = cleanup_feature_cache_directories()
        if _n_removed:
            log.info("Feature cache cleanup removed %d director(ies)", _n_removed)
        _np = prune_model_archives(MODEL_DIR)
        if _np:
            log.info("Model archive prune removed %d snapshot(s)", _np)
    except Exception as ex:
        log.warning("Feature cache / archive cleanup skipped: %s", ex)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    arch_target_path.write_text(json.dumps(arch_state, indent=2))
    log.info("%s updated", arch_target_path.name)
    log.info("Training report appended to %s", TRAINING_REPORT_PATH)

    # Active artifact verification — flag non-compliant
    try:
        from verify_active_models import check_artifact_compliance, _get_active_tickers
        for tkr in _get_active_tickers():
            r = check_artifact_compliance(tkr)
            if not r["compliant"]:
                log.warning("NON-COMPLIANT active %s: %s — retrain required", tkr, r["issues"])
    except Exception as e:
        log.warning("Verification skipped: %s", e)


_bg_scheduler_lock = threading.Lock()
_bg_scheduler_thread: Optional[threading.Thread] = None
_bg_scheduler_started = False


def _next_scheduled_run_et(now: datetime) -> datetime:
    """Earliest RUN_AT_HOUR:RUN_AT_MINUTE ET on a market day strictly after ``now``."""
    from datetime import time as dtime

    for i in range(0, 28):
        day = now.date() + timedelta(days=i)
        cand = datetime.combine(day, dtime(RUN_AT_HOUR, RUN_AT_MINUTE)).replace(tzinfo=ET)
        if cand <= now:
            continue
        if _is_market_day(cand):
            return cand
    return now + timedelta(days=1)


def start_background_scheduler() -> None:
    """
    Start a daemon thread that sleeps until the next market-day 16:15 ET, then calls ``run_once``
    (scheduled mode: no --run-now). Safe to call once per process; duplicates are ignored.
    """
    global _bg_scheduler_thread, _bg_scheduler_started
    with _bg_scheduler_lock:
        if _bg_scheduler_started:
            log.warning("start_background_scheduler: already started; ignoring duplicate")
            return
        _bg_scheduler_started = True

    hz = os.environ.get("ED_ML_SCHEDULER_HORIZON", DEFAULT_ML_HORIZON_SLUG)

    def _loop() -> None:
        while True:
            try:
                now = _now_et()
                nxt = _next_scheduled_run_et(now)
                delay = max(1.0, (nxt - now).total_seconds())
                log.info(
                    "ML scheduler background: next run at %s ET (in %.0f s)",
                    nxt.strftime("%Y-%m-%d %H:%M"),
                    delay,
                )
                time.sleep(delay)
                run_once(
                    wait=False,
                    force_retrain=False,
                    bypass_cache=False,
                    allow_non_market_day=False,
                    promote_from_manifests_only=False,
                    ml_horizon_slug=str(hz),
                )
            except Exception as e:
                log.exception("ML scheduler background loop error: %s", e)
                time.sleep(300.0)

    _bg_scheduler_thread = threading.Thread(
        target=_loop,
        name="ml_scheduler_nightly",
        daemon=True,
    )
    _bg_scheduler_thread.start()
    log.info("ML background scheduler thread started (nightly market-day %02d:%02d ET)", RUN_AT_HOUR, RUN_AT_MINUTE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    ap.add_argument(
        "--run-now",
        action="store_true",
        help="Do not wait until 16:15 ET; allow training on weekends/holidays (still needs DB rows).",
    )
    ap.add_argument("--force-retrain", action="store_true",
                    help="Replace non-compliant active artifacts even when new score < existing")
    ap.add_argument("--bypass-cache", action="store_true",
                    help="Ignore scheduler + feature tensor cache (full retrain + re-eval)")
    ap.add_argument(
        "--promote-from-manifests",
        action="store_true",
        help="Issue 11: skip training; re-run promotion from existing parallel/ cascade artifacts + manifests (implies --run-now).",
    )
    ap.add_argument(
        "--horizon",
        type=str,
        default=os.environ.get("ED_ML_SCHEDULER_HORIZON", DEFAULT_ML_HORIZON_SLUG),
        help="ML horizon slug for this scheduler run (1c, 5c, 15c, 60c). Non-1c promotes to models/active_{slug}/.",
    )
    args = ap.parse_args()
    run_now = bool(args.run_now or args.promote_from_manifests)
    run_once(
        wait=False if run_now else args.wait,
        force_retrain=args.force_retrain,
        bypass_cache=args.bypass_cache,
        allow_non_market_day=run_now,
        promote_from_manifests_only=bool(args.promote_from_manifests),
        ml_horizon_slug=str(args.horizon),
    )
