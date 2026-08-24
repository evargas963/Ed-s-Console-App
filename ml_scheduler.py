"""
ml_scheduler.py - Nightly ML Training Scheduler
===============================================
RULE 3: Runs every weekday at 16:15 ET.
For every ticker in EdDB.logging_universe (authoritative enrollment — core + pinned + user_persisted):
  A. Train parallel (XGB, LSTM, Transformer, Meta) → models/parallel/{ticker}/
  B. Train cascade (XGB→LSTM→Transformer) → models/cascade/{ticker}/
  C. Compare both on full RTH
  D. Promote winner to models/active/ or models/active_{hz}/ (governed; all four primaries via --all-horizons)
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
import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

# RC-345/F25: the trainer/scheduler writes artifact filenames and enrollment identity —
# every one delegates to the ONE canonical authority (instrument_identity.ticker_storage_key)
# so the files it WRITES ('$SPX') match what the verifier and predictor LOOK FOR, and match
# the DB storage key. No local .upper() second faucet for artifact/enrollment identity.
from instrument_identity import ticker_storage_key

# RC-340: THE row-enrichment authority for every engineer_single_snapshot call in this
# module — five cascade/bridge routes previously fed RAW rows (cf_* -> 0.0, dgex -> NaN).
from ml_data_common import prepare_row_for_xgb_features
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

from numeric_contract import direction_from_normalized_triplet
from time_et import ET

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
    from active_bundle_contract import scheduler_active_root as _contract_root

    return _contract_root(MODEL_DIR, ml_horizon_slug)


def _infer_slug_from_target_column(target_column: str) -> str:
    col = (target_column or "").strip().lower()
    if col.startswith("outcome_"):
        return normalize_ml_horizon_slug(col[len("outcome_") :])
    return DEFAULT_ML_HORIZON_SLUG


def _now_et() -> datetime:
    from time_et import now_et

    return now_et()


def _scheduler_auto_promote_to_active() -> bool:
    from arch_competition.scheduler_integration import scheduler_auto_promote_to_active_enabled

    return scheduler_auto_promote_to_active_enabled()


def _scheduler_skip_parallel_train() -> bool:
    """Operator: ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN=1 — train/eval cascade only; keep parallel artifacts."""
    return os.environ.get("ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


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


def _governed_report_fields(governed_slice: Optional[dict[str, Any]]) -> dict[str, Any]:
    blocked: list[Any] = []
    promotion_decision = None
    governed_failed_closed = False
    if isinstance(governed_slice, dict):
        governed_failed_closed = bool(governed_slice.get("failed_closed"))
        promotion_decision = governed_slice.get("latest_promotion_decision")
        if governed_failed_closed:
            err = governed_slice.get("error")
            blocked = [{"code": "governed_failed_closed", "detail": str(err) if err is not None else ""}]
        else:
            flags = governed_slice.get("blocked_promotion_flags")
            if isinstance(flags, list):
                blocked = list(flags)
    return {
        "governed_failed_closed": governed_failed_closed,
        "promotion_decision": promotion_decision,
        "blocked_promotion_flags": blocked,
    }


def _apply_pr2_report_fields(
    report: dict[str, Any],
    *,
    outcome: str,
    horizon: str,
    artifact_complete: bool,
    consecutive_cache_skips: int,
    governed_slice: Optional[dict[str, Any]],
) -> None:
    report["outcome"] = outcome
    report["horizon"] = horizon
    report["artifact_complete"] = artifact_complete
    report["consecutive_cache_skips"] = consecutive_cache_skips
    report.update(_governed_report_fields(governed_slice))


def _resolve_ticker_outcome(
    *,
    ticker: str,
    horizon: str,
    skip_governed_eval: bool,
    governed_slice: Optional[dict[str, Any]],
    parallel_skip: bool,
    cascade_skip: bool,
    promoted: bool,
    consecutive_cache_skips: int,
    auto_exec_result: Optional[dict[str, Any]] = None,
) -> tuple[str, int]:
    from training_outcome import TrainingOutcome, is_training_anchor_ticker
    from training_pipeline_status import (
        bump_cache_skip_streak,
        get_cache_skip_cap,
        reset_cache_skip_streak,
    )

    if skip_governed_eval:
        from training_outcome import is_training_anchor_ticker

        if is_training_anchor_ticker(ticker):
            return TrainingOutcome.eval_failed.value, consecutive_cache_skips
        return TrainingOutcome.promote_skipped.value, consecutive_cache_skips

    if isinstance(governed_slice, dict) and governed_slice.get("failed_closed"):
        return TrainingOutcome.eval_failed.value, consecutive_cache_skips

    if isinstance(auto_exec_result, dict):
        if auto_exec_result.get("skipped_reason") == "verify_failed":
            return TrainingOutcome.verify_failed.value, consecutive_cache_skips
        if auto_exec_result.get("executed"):
            reset_cache_skip_streak(ticker, horizon)
            return TrainingOutcome.promote_ok.value, 0
        would_promote = bool(
            isinstance(governed_slice, dict)
            and governed_slice.get("would_promote_challenger")
            and not governed_slice.get("failed_closed")
        )
        if would_promote and not auto_exec_result.get("executed"):
            if parallel_skip and cascade_skip:
                streak = bump_cache_skip_streak(ticker, horizon)
                cap = get_cache_skip_cap()
                if streak > cap:
                    return TrainingOutcome.cache_skip_streak_exceeded.value, streak
                return TrainingOutcome.cache_skipped.value, streak
            reset_cache_skip_streak(ticker, horizon)
            return TrainingOutcome.promote_skipped.value, 0

    if parallel_skip and cascade_skip:
        streak = bump_cache_skip_streak(ticker, horizon)
        cap = get_cache_skip_cap()
        if streak > cap:
            return TrainingOutcome.cache_skip_streak_exceeded.value, streak
        return TrainingOutcome.cache_skipped.value, streak

    reset_cache_skip_streak(ticker, horizon)
    if promoted:
        return TrainingOutcome.promote_ok.value, 0
    return TrainingOutcome.trained.value, 0


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
    try:
        have = _get_tickers_with_rth_data(
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


def _evaluate_parallel_on_full_rth(
    db_path: str,
    ticker: str,
    model_dir: Path,
    *,
    allowed_et_dates: Optional[Set[str]] = None,
    target_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
    return_detail: bool = False,
    max_eval_rows: Optional[int] = None,
) -> tuple[float, float, int, Optional[float], dict[str, Any]] | tuple:
    """Run parallel ensemble on full RTH data (or only ET dates in allowed_et_dates if set).

    Returns accuracy, balanced_accuracy, n_rows_scored, log_loss, realized_contract_metrics (see realized_contract_eval).
    If ``return_detail`` is True, appends a dict with prob_rows, y_true, rows_used for arch_competition eval.
    When ``max_eval_rows`` is set, only the most recent N labeled rows are scored (fast gates).
    """
    rows = _load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
    if allowed_et_dates is not None:
        rows = [r for r in rows if r.get("ts_et") and str(r["ts_et"])[:10] in allowed_et_dates]
    if max_eval_rows is not None and int(max_eval_rows) > 0 and len(rows) > int(max_eval_rows):
        rows = rows[-int(max_eval_rows) :]
    if len(rows) < 10:
        out = (0.0, 0.0, len(rows), None, _empty_realized_metrics(len(rows)))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out

    try:
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
                from features.training_canonical_input import normalize_pandas_sql_null_row_dict

                hist_db = _eval_hist_db_for_labeled_rows(db_path, ticker, rows)

                skip_stats = {
                    "rows_total": len(rows),
                    "missing_hist_db": 0,
                    "xgb_unavailable": 0,
                    "lstm_unavailable": 0,
                    "transformer_unavailable": 0,
                    "ensemble_failed": 0,
                    "scored_full_triplet": 0,
                    "nonfinite_triplet": 0,
                }

                for row in rows:
                    yt = {"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2)
                    row_db = normalize_pandas_sql_null_row_dict(row)
                    ts_utc = row_db.get("ts_utc")
                    inf_v1 = build_inference_snapshot_v1_from_db_row(
                        ticker=ticker,
                        expiry=None,
                        as_of_ts=float(ts_utc) if ts_utc is not None else None,
                        db_row=row_db,
                    )
                    if ts_utc is None or hist_db is None:
                        if hist_db is None:
                            skip_stats["missing_hist_db"] += 1
                        continue
                    try:
                        xgb_p = mp._predict_xgb(inf_v1, ticker, fusion_feature_overlay=row_db)
                    except Exception as _xgb_e:
                        skip_stats["xgb_unavailable"] += 1
                        log.debug(
                            "%s parallel eval row: XGB unavailable at ts=%s (%s)",
                            ticker,
                            ts_utc,
                            _xgb_e,
                        )
                        continue
                    if xgb_p is None:
                        skip_stats["xgb_unavailable"] += 1
                        continue
                    try:
                        lstm_p = mp._predict_lstm(
                            ticker,
                            hist_db,
                            inference_snapshot_v1=inf_v1,
                            parallel_runtime=True,
                        )
                    except Exception as _lstm_e:
                        skip_stats["lstm_unavailable"] += 1
                        log.debug(
                            "%s parallel eval row: LSTM unavailable at ts=%s (%s)",
                            ticker,
                            ts_utc,
                            _lstm_e,
                        )
                        continue
                    if not lstm_p:
                        skip_stats["lstm_unavailable"] += 1
                        continue
                    try:
                        tr_p = mp._predict_transformer(
                            ticker,
                            hist_db,
                            inference_snapshot_v1=inf_v1,
                            parallel_runtime=True,
                        )
                    except Exception as _tr_e:
                        skip_stats["transformer_unavailable"] += 1
                        log.debug(
                            "%s parallel eval row: Transformer unavailable at ts=%s (%s)",
                            ticker,
                            ts_utc,
                            _tr_e,
                        )
                        continue
                    if not tr_p:
                        skip_stats["transformer_unavailable"] += 1
                        continue
                    result = mp._ensemble_parallel_probs(ticker, xgb_p, lstm_p, tr_p)
                    if not result:
                        skip_stats["ensemble_failed"] += 1
                        continue
                    skip_stats["scored_full_triplet"] += 1
                    pu, pd, pf = (
                        float(result.get("up", 0.33)),
                        float(result.get("down", 0.33)),
                        float(result.get("flat", 0.34)),
                    )
                    s = pu + pd + pf
                    if s > 0:
                        pu, pd, pf = pu / s, pd / s, pf / s
                    dom = direction_from_normalized_triplet(pu, pd, pf)
                    if dom is None:
                        # RC-363 WITHHELD: non-finite probability leg — skip the row so
                        # it never corrupts preds/y_true/log_loss alignment.
                        skip_stats["nonfinite_triplet"] += 1
                        continue
                    prob_rows.append([pu, pd, pf])
                    preds.append({"up": 0, "down": 1, "flat": 2}[dom])
                    y_true.append(yt)
                    rows_used.append(row_db)

            n = len(preds)
            if n < 10:
                log.warning(
                    "%s parallel eval triplet starvation: scored=%d need>=10 skip_stats=%s",
                    ticker,
                    n,
                    skip_stats,
                )
                out = (0.0, 0.0, n, None, _empty_realized_metrics(len(rows_used)))
                if return_detail:
                    return out + (
                        {
                            "prob_rows": prob_rows,
                            "y_true": y_true,
                            "rows_used": rows_used,
                            "skip_stats": skip_stats,
                        },
                    )
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
                "skip_stats": skip_stats,
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
        out = (0.0, 0.0, 0, None, _empty_realized_metrics(0))
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
                from features.training_canonical_input import normalize_pandas_sql_null_row_dict

                hist_db = _eval_hist_db_for_labeled_rows(db_path, ticker, rows)

                for row in rows:
                    row_db = normalize_pandas_sql_null_row_dict(row)
                    ts_utc = row_db.get("ts_utc")
                    if ts_utc is None or hist_db is None:
                        continue
                    inf_v1 = build_inference_snapshot_v1_from_db_row(
                        ticker=ticker,
                        expiry=None,
                        as_of_ts=float(ts_utc),
                        db_row=row_db,
                    )
                    try:
                        tr_p = mp._predict_transformer(
                            ticker, hist_db, inference_snapshot_v1=inf_v1
                        )
                    except Exception as _tr_e:
                        log.debug(
                            "%s cascade eval row: Transformer unavailable at ts=%s (%s)",
                            ticker,
                            ts_utc,
                            _tr_e,
                        )
                        continue
                    if not tr_p:
                        continue
                    pu = float(tr_p.get("up", 0.33))
                    pd = float(tr_p.get("down", 0.33))
                    pf = float(tr_p.get("flat", 0.34))
                    s = pu + pd + pf
                    if s > 0:
                        pu, pd, pf = pu / s, pd / s, pf / s
                    dom = direction_from_normalized_triplet(pu, pd, pf)
                    if dom is None:
                        # RC-363 WITHHELD: non-finite probability leg — skip the row so
                        # it never corrupts preds/y_true/log_loss alignment.
                        continue
                    prob_rows.append([pu, pd, pf])
                    yt = {"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2)
                    y_true.append(yt)
                    preds.append({"up": 0, "down": 1, "flat": 2}[dom])
                    rows_used.append(row_db)

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
        out = (0.0, 0.0, 0, None, _empty_realized_metrics(0))
        if return_detail:
            return out + ({"prob_rows": [], "y_true": [], "rows_used": []},)
        return out


def _meta_ml_layer_triplet(layer_name: str, probs, collapsed) -> list:
    """One unified-stack ML layer's ``[up, down, flat]`` contribution to the meta-training vector.

    CLOSEOUT #3: a layer flagged ``val_single_class_collapse`` is degenerate (all-flat); treat
    it as absent and substitute the neutral filler so the meta LogisticRegression never learns
    to trust it. Empty ``collapsed`` with present ``probs`` reproduces the prior assembly
    byte-for-byte (``[probs.get(c, 0.333) for c in up/down/flat]``).
    """
    if layer_name in collapsed or not probs:
        return [0.333, 0.333, 0.334]
    return [probs.get(c, 0.333) for c in ("up", "down", "flat")]


def _assemble_meta_ml_layer_prob_vectors(
    model_dir: Path,
    ticker: str,
    db_path: str,
    rows_df: Any,
    target_column: str,
    hz: str,
) -> tuple[list, list]:
    """Assemble parallel meta-learner [xgb|lstm|transformer] prob vectors + labels by running
    the xgb/lstm/transformer layers in ``model_dir`` over the rows in ``rows_df``.

    Used both for the in-sample fallback (``model_dir`` = deployed ``out_dir``, rows = full
    training df) and for each OOF fold (``model_dir`` = a fold dir trained on strictly-earlier
    sessions, rows = the held-out fold) — Workstream B2.
    """
    import ml_predict as mp
    from ml_predict import _predict_xgb, _predict_lstm, _predict_transformer
    from features.fusion_model_input import meta_tabular_vector_from_overlay
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.training_canonical_input import records_for_mvp_from_dataframe

    X_meta: list = []
    y_meta: list = []
    orig_mp_dir = mp.MODEL_DIR
    htok_meta = mp.set_ml_infer_horizon_slug(hz)
    try:
        with _strict_off_for_candidate_inference():
            mp.MODEL_DIR = model_dir
            mp.reset_caches()
            rows = records_for_mvp_from_dataframe(rows_df)
            hist_db = _eval_hist_db_for_labeled_rows(db_path, ticker, rows)
            # B3+ collapse guard (CLOSEOUT #3): bases flagged val_single_class_collapse in
            # model_dir are degenerate (all-flat); substitute the neutral filler so the meta
            # LR never learns to trust them. Empty set => identical to prior assembly.
            collapsed = mp.read_stack_layer_collapse_flags(model_dir, ticker, hz)
            for row in rows:
                inf_v1 = build_inference_snapshot_v1_from_db_row(
                    ticker=ticker, expiry=None, as_of_ts=row.get("ts_utc"), db_row=row,
                )
                xgb_p = _predict_xgb(inf_v1, ticker, fusion_feature_overlay=row)
                lstm_p = tr_p = None
                ts_utc = row.get("ts_utc")
                if ts_utc and hist_db is not None:
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
                    _meta_ml_layer_triplet("xgb", xgb_p, collapsed)
                    + _meta_ml_layer_triplet("lstm", lstm_p, collapsed)
                    + _meta_ml_layer_triplet("transformer", tr_p, collapsed)
                    + meta_tabular_vector_from_overlay(row)
                )
                X_meta.append(vec)
                y_meta.append({"up": 0, "down": 1, "flat": 2}.get(row.get(target_column), 2))
    finally:
        mp.MODEL_DIR = orig_mp_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok_meta)
    return X_meta, y_meta


def _train_parallel_ml_stack_layers_into(
    temp_dir: Path,
    ticker: str,
    db_path: str,
    allowed_et_dates: Set[str],
    *,
    data_fp: Optional[dict],
    hz: str,
) -> bool:
    """Train XGB + LSTM + Transformer (parallel ML stack layers) on ``allowed_et_dates`` into
    ``temp_dir`` for OOF meta-learner prob generation (Workstream B2). ``bypass_cache``/
    ``bypass_torch_resume`` always on — the fold's date subset has a different fingerprint
    than the full-data feature cache. Returns True when at least XGB is present
    (LSTM/Transformer degrade gracefully in assembly via the 0.333 fallback)."""
    from ml_train import load_data, train_ticker
    from lstm_model import train_lstm
    from lstm_data import build_lstm_dataset
    from transformer_train import train_transformer, prepare_transformer_data

    temp_dir.mkdir(parents=True, exist_ok=True)
    df = load_data(db_path, ticker=ticker, allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz)
    if len(df) == 0:
        return False
    train_ticker(
        ticker, df, model_dir=temp_dir, current_data_fingerprint=data_fp, ml_horizon_slug=hz,
        db_path=db_path,  # RC-344/F35: same DB as load_data above
    )
    ds = build_lstm_dataset(
        tickers=[ticker], db_path=Path(db_path), allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz,
    )
    if ds is not None and getattr(ds, "n_samples", 0) > 0:
        train_lstm(
            dataset=ds, db_path=db_path, ticker=ticker, model_dir=temp_dir, data_fp=data_fp,
            architecture="parallel", bypass_torch_resume=True, ml_horizon_slug=hz,
        )
    Xp, yp, daysp, tickp, nfp = prepare_transformer_data(
        db_path, ticker, allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz,
    )
    if Xp is not None and len(yp) > 0:
        train_transformer(
            db_path=db_path, ticker=ticker, model_dir=temp_dir,
            preloaded_sequences=(Xp, yp, daysp, tickp, nfp), allowed_et_dates=allowed_et_dates,
            data_fp=data_fp, architecture="parallel", bypass_torch_resume=True, ml_horizon_slug=hz,
        )
    return (temp_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl").exists()


def _write_meta_training_basis_manifest(
    out_dir: Path,
    ticker: str,
    hz: str,
    *,
    architecture: str,
    basis: str,
    n_rows: int,
) -> Path:
    """ML-PIPE-V2 Phase 3 (2026-07-11): the meta learner's training BASIS must
    travel with the artifact. Before this manifest, ``meta_basis`` was only a
    log line — an in-sample-fallback-trained meta pickle was byte-identical to
    an expanding-window-OOF one for every downstream consumer (serving, eval,
    promotion), so base-model overfit inherited via the fallback could never be
    distinguished from governed OOF evidence. ``oof_governed`` is the
    machine-readable gate field: False for every in-sample basis.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — training-provenance manifest only; no
      market field read, derived, or emitted by this lane (meta inputs are the
      already-persisted stack probabilities and snapshot overlay columns).
    Derived-field disposition: none required (no derivation touched).
    All consumers checked: yes — read_meta_training_basis_manifest is the only
      reader; meta pickle contents and serving paths are byte-identical.
    SCHWAB_CSV_CHECKED"""
    manifest = {
        "artifact": f"meta_{ticker_storage_key(ticker)}_{hz}.pkl",
        "ticker": ticker_storage_key(ticker),
        "horizon_slug": hz,
        "architecture": architecture,
        "meta_training_basis": basis,
        "oof_governed": basis == "expanding_window_oof",
        "n_training_rows": int(n_rows),
        "written_at_epoch": time.time(),
        "schema": "META_TRAINING_BASIS_MANIFEST_V1",
    }
    out_path = out_dir / f"meta_{ticker_storage_key(ticker)}_{hz}_training_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def read_meta_training_basis_manifest(
    out_dir: Path, ticker: str, hz: str
) -> Optional[dict]:
    """Read META_TRAINING_BASIS_MANIFEST_V1 for a bundle's meta artifact.

    Returns None when absent (pre-manifest legacy bundle). Downstream promotion
    / predictive-validity surfaces MUST treat ``oof_governed is not True`` as
    not-OOF-governed evidence (legacy absence never upgrades to governed)."""
    p = Path(out_dir) / f"meta_{ticker_storage_key(ticker)}_{hz}_training_manifest.json"
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _train_parallel_meta_oof(
    out_dir: Path,
    ticker: str,
    db_path: str,
    df: Any,
    oof_universe_days: list,
    target_column: str,
    hz: str,
    *,
    data_fp: Optional[dict],
) -> tuple[list, list, str]:
    """Build the parallel meta-learner's training matrix from EXPANDING-WINDOW OUT-OF-FOLD
    base predictions (Workstream B2). For each fold the ML stack layers are trained on
    strictly-earlier sessions into a temp dir and scored on the held-out fold, so the meta
    never sees in-sample base probs. The deployed base artifacts in ``out_dir`` are untouched
    (they stay full-data trained). Falls back to in-sample assembly when no folds can be
    formed (too few sessions) or OOF yields < 10 usable rows. Returns (X_meta, y_meta, basis)."""
    import shutil
    import tempfile

    from ml_train import load_data
    from training_cache import expanding_window_oof_folds

    folds = expanding_window_oof_folds(oof_universe_days)
    if not folds:
        X_meta, y_meta = _assemble_meta_ml_layer_prob_vectors(out_dir, ticker, db_path, df, target_column, hz)
        return X_meta, y_meta, "in_sample_no_folds"

    X_meta: list = []
    y_meta: list = []
    tmp_root = Path(tempfile.mkdtemp(prefix=f"oof_par_{ticker}_{hz}_"))
    try:
        for fi, (tr_days, oof_days) in enumerate(folds):
            fold_dir = tmp_root / f"fold{fi}"
            if not _train_parallel_ml_stack_layers_into(
                fold_dir, ticker, db_path, set(tr_days), data_fp=data_fp, hz=hz,
            ):
                log.warning("%s parallel meta OOF: fold %d ML stack train incomplete — skip", ticker, fi)
                continue
            df_oof = load_data(db_path, ticker=ticker, allowed_et_dates=set(oof_days), ml_horizon_slug=hz)
            if len(df_oof) == 0:
                continue
            fx, fy = _assemble_meta_ml_layer_prob_vectors(fold_dir, ticker, db_path, df_oof, target_column, hz)
            X_meta.extend(fx)
            y_meta.extend(fy)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if len(X_meta) < 10:
        log.warning(
            "%s parallel meta: OOF produced %d usable rows (<10) — in-sample fallback", ticker, len(X_meta),
        )
        X_meta, y_meta = _assemble_meta_ml_layer_prob_vectors(out_dir, ticker, db_path, df, target_column, hz)
        return X_meta, y_meta, "in_sample_fallback"
    return X_meta, y_meta, "expanding_window_oof"


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
    from lstm_model import train_lstm
    from lstm_data import build_lstm_dataset
    from transformer_train import train_transformer, prepare_transformer_data
    import pickle
    from sklearn.linear_model import LogisticRegression
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
        sequence_allowed_dates = allowed_et_dates
    else:
        min_ts_tab = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_TABULAR, label_column=target_column,
        )
        min_ts_seq = min_ts_utc_for_last_n_rth_sessions(
            db_path, ticker, ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE, label_column=target_column,
        )
        sequence_allowed_dates = None
        if ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE > 0:
            from training_cache import db_distinct_rth_et_dates_for_ticker

            _seq_dates = db_distinct_rth_et_dates_for_ticker(
                db_path, ticker, label_column=target_column,
            )
            _ns = int(ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE)
            if len(_seq_dates) >= _ns:
                sequence_allowed_dates = set(_seq_dates[-_ns:])
            elif _seq_dates:
                sequence_allowed_dates = set(_seq_dates)

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
        db_path=db_path,  # RC-344/F35: same DB as load_data
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
            allowed_et_dates=sequence_allowed_dates,
            ml_horizon_slug=hz,
        )
        if ds.n_samples > 0 and not bypass_cache:
            save_lstm_feature_cache(fdir, ticker, data_fp, fk, ds)
    else:
        used_feature_cache = True
        log.info("%s parallel: LSTM feature cache hit (%s)", ticker, fk[:12])

    try:
        from training_cache import save_parallel_cascade_bridge

        xgb_pkl = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl"
        xgb_meta_p = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}_meta.json"
        if (
            ds is not None
            and getattr(ds, "n_samples", 0) >= 10
            and xgb_pkl.is_file()
            and xgb_meta_p.is_file()
            and not bypass_cache
        ):
            with open(xgb_pkl, "rb") as f:
                _bridge_xgb = pickle.load(f)
            with open(xgb_meta_p, encoding="utf-8") as f:
                _bridge_meta = json.load(f)
            _aligned_probs = _xgb_probs_aligned_to_lstm_dataset(
                ds,
                ticker,
                db_path,
                _bridge_xgb,
                _bridge_meta,
                hz,
                min_ts_utc=min_ts_seq,
                allowed_et_dates=sequence_allowed_dates,
            )
            if _aligned_probs is not None and _aligned_probs.shape[0] == ds.n_samples:
                save_parallel_cascade_bridge(
                    fdir,
                    ticker,
                    data_fp,
                    fk,
                    _aligned_probs,
                    xgb_pkl,
                    xgb_meta_p,
                )
            else:
                log.warning(
                    "%s parallel: parallel→cascade bridge not saved (alignment failed)",
                    ticker,
                )
    except Exception as _bridge_exc:
        log.warning("%s parallel: parallel→cascade bridge save error: %s", ticker, _bridge_exc)

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
            allowed_et_dates=sequence_allowed_dates,
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

    # Meta-learner (parallel stacker). Workstream B2: train the meta on EXPANDING-WINDOW
    # OUT-OF-FOLD base predictions so it never sees in-sample base probs; the deployed
    # XGB/LSTM/Transformer trained above stay full-data (only the stacker's TRAINING
    # features become out-of-fold). Falls back to in-sample assembly when too few sessions
    # exist for folds. The meta is resolved by ml_predict from this candidate dir's flat
    # artifacts (xgb_SPY_<hz>.pkl, lstm_SPY_<hz>.pt, transformer_SPY_<hz>.pt).
    if allowed_et_dates is not None:
        oof_universe_days = sorted(set(allowed_et_dates))
    else:
        from training_cache import db_distinct_rth_et_dates_for_ticker

        oof_universe_days = db_distinct_rth_et_dates_for_ticker(
            db_path, ticker, label_column=target_column
        )
    X_meta, y_meta, meta_basis = _train_parallel_meta_oof(
        out_dir, ticker, db_path, df, oof_universe_days, target_column, hz, data_fp=data_fp,
    )
    if len(X_meta) >= 10:
        meta_mdl = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_mdl.fit(np.array(X_meta), np.array(y_meta))
        with open(out_dir / f"meta_{ticker_storage_key(ticker)}_{hz}.pkl", "wb") as f:
            pickle.dump(meta_mdl, f)
        _write_meta_training_basis_manifest(
            out_dir, ticker, hz, architecture="parallel", basis=meta_basis, n_rows=len(X_meta),
        )
        log.info(
            "%s parallel meta trained on %d rows (basis=%s)", ticker, len(X_meta), meta_basis,
        )

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
    dest = out_dir if out_dir is not None else PARALLEL_DIR / ticker_storage_key(ticker)  # RC-345/F25
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


def _oof_day_to_fold_map(folds: list) -> dict:
    """Map each OOF (held-out) session day to its fold index (Workstream B2, commit 2).

    Seed-block days — present only in fold 0's train set and never as an OOF block — are
    ABSENT from the map; the cascade excludes them from stacker training (no in-sample row).
    Every mapped day belongs to a fold whose train sessions are strictly earlier than that
    day (guaranteed by ``expanding_window_oof_folds``)."""
    m: dict = {}
    for fi, (_train_days, oof_days) in enumerate(folds):
        for d in oof_days:
            m[d] = fi
    return m


def _train_cascade_xgb_lstm_into(
    temp_dir: Path,
    ticker: str,
    db_path: str,
    allowed_et_dates: Set[str],
    *,
    data_fp: Optional[dict],
    hz: str,
) -> bool:
    """Train XGB + cascade-LSTM on exactly ``allowed_et_dates`` into ``temp_dir`` for OOF
    base-prob generation feeding the cascade transformer (Workstream B2, commit 2).

    Mirrors the deployed cascade's XGB→LSTM steps: the fold LSTM consumes the fold XGB's
    in-sample probs over the fold's OWN train sessions (the cost-bounded design the operator
    locked — K=3, no nested per-fold OOF inside the LSTM; the LSTM's own honesty is B3's
    temporal holdout). ``bypass`` cache/resume always on (the fold's date subset has a
    different fingerprint than the full-data cache). Returns True when both XGB + LSTM
    artifacts exist."""
    import json
    import pickle

    import numpy as np

    from ml_train import load_data, train_ticker, engineer_single_snapshot
    from lstm_model import train_lstm
    from lstm_data import (
        build_lstm_dataset, extract_rth_snapshots, STREAM_5M_LOOKBACK, TARGET_CLASSES,
        canonical_reference_spot_from_sequence_window_first_bar,
    )
    from timeframe_config import CANONICAL_TIMEFRAME

    temp_dir.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(hz)
    label_col = outcome_column(hz)
    df = load_data(db_path, ticker=ticker, allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz)
    if len(df) == 0:
        return False
    train_ticker(ticker, df, model_dir=temp_dir, current_data_fingerprint=data_fp,
                 ml_horizon_slug=hz, db_path=db_path)  # RC-344/F35
    xgb_path = temp_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl"
    if not xgb_path.exists():
        return False
    with open(xgb_path, "rb") as f:
        xgb_model = pickle.load(f)
    with open(temp_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}_meta.json") as f:
        xgb_meta = json.load(f)

    days_data = extract_rth_snapshots(
        ticker, timeframe=CANONICAL_TIMEFRAME, db_path=Path(db_path),
        require_outcome=True, allowed_et_dates=allowed_et_dates, target_column=label_col,
        model_family="xgb", horizon_slug=hz,  # cascade: snapshot feeds XGB-prob generation
    )
    xgb_probs_list: list = []
    for _day, snapshots in sorted(days_data.items()):
        if len(snapshots) < STREAM_5M_LOOKBACK:
            continue
        for end_idx in range(STREAM_5M_LOOKBACK, len(snapshots)):
            window = snapshots[end_idx - STREAM_5M_LOOKBACK:end_idx]
            current = window[-1]
            if current.get(label_col) not in TARGET_CLASSES:
                continue
            # RC-318: this gate exists ONLY to mirror build_lstm_dataset's window eligibility
            # (xgb_probs_list must align 1:1 with ds samples, checked below). The old
            # `_safe_float(first) or _safe_float(current)` form used a last-bar fallback the
            # canonical producer forbids and let NaN through — any divergence silently broke
            # the alignment and discarded the cascade probs. Use the SAME canonical drop.
            try:
                canonical_reference_spot_from_sequence_window_first_bar(window)
            except ValueError:
                continue
            X_row = engineer_single_snapshot(
                prepare_row_for_xgb_features(current),  # RC-340 (no cache var in this scope)
                xgb_meta.get("category_maps", {}), xgb_meta.get("features", []),
                xgb_meta.get("vol_medians", {}), ticker,
            )
            if X_row is None:
                continue
            xgb_probs_list.append(xgb_model.predict_proba(X_row.values.astype(np.float64))[0])

    ds = build_lstm_dataset(
        tickers=[ticker], db_path=Path(db_path), allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz,
    )
    if ds is None or getattr(ds, "n_samples", 0) < 10:
        return False
    if len(xgb_probs_list) == ds.n_samples:
        train_lstm(
            dataset=ds, db_path=db_path, ticker=ticker, model_dir=temp_dir,
            xgb_probs=np.array(xgb_probs_list[: ds.n_samples], dtype=np.float32),
            data_fp=data_fp, architecture="cascade", bypass_torch_resume=True, ml_horizon_slug=hz,
        )
    else:
        train_lstm(
            dataset=ds, db_path=db_path, ticker=ticker, model_dir=temp_dir, data_fp=data_fp,
            architecture="cascade", bypass_torch_resume=True, ml_horizon_slug=hz,
        )
    return (temp_dir / f"lstm_{ticker_storage_key(ticker)}_{hz}.pt").exists()


def _build_in_sample_cascade_xgb_lstm_tensor(
    model_dir: Path,
    ticker: str,
    db_path: str,
    allowed_et_dates: Set[str],
    *,
    hz: str,
) -> Optional[Any]:
    """Build in-sample [xgb|lstm] prob vectors for cascade transformer training on ``model_dir``."""
    import json
    import pickle

    import numpy as np
    import torch

    from lstm_model import align_lstm_norm_stats, apply_normalization, load_lstm
    from lstm_data import (
        CONFLUENCE_FEATURES,
        STREAM_1M_LOOKBACK,
        STREAM_5M_LOOKBACK,
        TARGET_CLASSES,
        canonical_reference_spot_from_sequence_window_first_bar,
        encode_snapshot_1m,
        encode_snapshot_5m,
        extract_rth_snapshots,
        micro_reference_spot_from_window,
    )
    from ml_data_common import confluence_features_for_bar
    from ml_train import engineer_single_snapshot
    from features.training_canonical_input import training_snapshot_for_sequence_encode
    from transformer_train import SEQUENCE_LENGTH
    from timeframe_config import CANONICAL_TIMEFRAME

    _conf_cache: dict = {}          # RC-332: one canonical-history pool per (ticker, UTC day)
    hz = normalize_ml_horizon_slug(hz)
    label_col = outcome_column(hz)
    t = ticker_storage_key(ticker)
    xgb_path = model_dir / f"xgb_{t}_{hz}.pkl"
    xgb_meta_path = model_dir / f"xgb_{t}_{hz}_meta.json"
    if not xgb_path.is_file() or not xgb_meta_path.is_file():
        return None
    with open(xgb_path, "rb") as f:
        xgb_model = pickle.load(f)
    with open(xgb_meta_path, encoding="utf-8") as f:
        xgb_meta = json.load(f)
    lstm_model, lstm_ckpt = load_lstm(model_dir=model_dir, ticker=ticker, ml_horizon_slug=hz)
    if lstm_model is None or lstm_ckpt is None:
        return None
    lstm_model.eval()

    _cascade_hist = max(int(SEQUENCE_LENGTH), int(STREAM_5M_LOOKBACK))
    days_lstm = extract_rth_snapshots(
        ticker,
        timeframe=CANONICAL_TIMEFRAME,
        db_path=Path(db_path),
        require_outcome=True,
        allowed_et_dates=allowed_et_dates,
        target_column=label_col,
        model_family="lstm",
        horizon_slug=hz,
    )
    days_xgb = extract_rth_snapshots(
        ticker,
        timeframe=CANONICAL_TIMEFRAME,
        db_path=Path(db_path),
        require_outcome=True,
        allowed_et_dates=allowed_et_dates,
        target_column=label_col,
        model_family="xgb",
        horizon_slug=hz,
    )
    vectors: list = []
    for _day_key, snapshots in sorted(days_lstm.items()):
        snapshots_xgb = days_xgb.get(_day_key)
        if not snapshots_xgb or len(snapshots_xgb) != len(snapshots):
            log.warning(
                "%s cascade tensor: xgb/lstm day %s row count mismatch (%s vs %s); skip day",
                ticker,
                _day_key,
                len(snapshots_xgb or ()),
                len(snapshots),
            )
            continue
        if len(snapshots) < _cascade_hist:
            continue
        for end_idx in range(_cascade_hist, len(snapshots)):
            window = snapshots[end_idx - SEQUENCE_LENGTH : end_idx]
            current_lstm = window[-1]
            if current_lstm.get(label_col) not in TARGET_CLASSES:
                continue
            try:
                canonical_reference_spot_from_sequence_window_first_bar(window)
            except ValueError:
                continue
            current_xgb = snapshots_xgb[end_idx - 1]
            X_row = engineer_single_snapshot(
                prepare_row_for_xgb_features(current_xgb, cache=_conf_cache),  # RC-340
                xgb_meta.get("category_maps", {}),
                xgb_meta.get("features", []),
                xgb_meta.get("vol_medians", {}),
                ticker,
            )
            if X_row is None:
                continue
            xgb_p = xgb_model.predict_proba(X_row.values.astype(np.float64))[0]

            lstm_window = snapshots[end_idx - STREAM_5M_LOOKBACK : end_idx]
            try:
                lstm_ref = canonical_reference_spot_from_sequence_window_first_bar(lstm_window)
            except ValueError:
                continue
            seq_5m = [
                encode_snapshot_5m(training_snapshot_for_sequence_encode(s), lstm_ref)
                for s in lstm_window
            ]
            micro = lstm_window[-STREAM_1M_LOOKBACK:]
            # RC-318: single typed-absence producer (None/NaN/<=0 tested -> validated lstm_ref).
            micro_ref = micro_reference_spot_from_window(micro, lstm_ref)
            seq_1m = [
                encode_snapshot_1m(training_snapshot_for_sequence_encode(s), micro_ref)
                for s in micro
            ]
            # RC-332: cf_* history is the single authority's population, not this lane's
            # flattened RTH-filtered days. Flattening days_lstm produced a THIRD population
            # shape for one feature name, and the linear ts_et scan it needed to locate the
            # bar was O(n) per row on top of that. Both go away: the lane supplies the bar,
            # the authority owns the history.
            conf = confluence_features_for_bar(
                ticker, current_lstm.get("ts_utc"), str(db_path), cache=_conf_cache)
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
                aligned = align_lstm_norm_stats(norm, mask_5m, mask_1m, mask_conf)
                if aligned is None:
                    log.warning("%s cascade fold tensor: LSTM norm_stats / mask mismatch; skip row", ticker)
                    continue
                X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, aligned)
            X_5m = np.nan_to_num(X_5m, nan=0.0)
            X_1m = np.nan_to_num(X_1m, nan=0.0)
            X_conf = np.nan_to_num(X_conf, nan=0.0)
            try:
                from arch_competition.stack_bundle_eval_v1 import (
                    ablation_survivors_training_enabled,
                    zero_ablated_sequence_channels_for_model,
                )
                from lstm_data import (
                    ENCODED_FEATURES_1M,
                    ENCODED_FEATURES_5M,
                    FEATURES_1M,
                    FEATURES_5M,
                )

                if ablation_survivors_training_enabled():
                    X_5m, X_1m = zero_ablated_sequence_channels_for_model(
                        X_5m,
                        X_1m,
                        mask_5m,
                        mask_1m,
                        model_family="lstm",
                        horizon_slug=hz,
                        features_5m=FEATURES_5M,
                        features_1m=FEATURES_1M,
                        encoded_features_5m=ENCODED_FEATURES_5M,
                        encoded_features_1m=ENCODED_FEATURES_1M,
                    )
            except Exception as exc:
                log.warning("%s cascade tensor: LSTM ablation channel zero failed: %s", ticker, exc)
                continue
            with torch.no_grad():
                logits = lstm_model(
                    torch.from_numpy(X_1m).float(),
                    torch.from_numpy(X_5m).float(),
                    torch.from_numpy(X_conf).float(),
                )
                lstm_p = torch.softmax(logits, dim=-1).squeeze().numpy()
            vectors.append(np.concatenate([xgb_p, lstm_p]))
    if len(vectors) < 10:
        return None
    return np.array(vectors, dtype=np.float32)


def _train_cascade_ml_stack_layers_into(
    temp_dir: Path,
    ticker: str,
    db_path: str,
    allowed_et_dates: Set[str],
    *,
    data_fp: Optional[dict],
    hz: str,
) -> bool:
    """Train full cascade stack (XGB, cascade-LSTM, cascade-Transformer) on ``allowed_et_dates``.

    Used for OOF meta-learner folds: each fold trains on strictly-earlier sessions; the meta
    stacker scores held-out rows via ``_assemble_meta_ml_layer_prob_vectors`` against the fold dir.
    """
    from lstm_data import STREAM_5M_LOOKBACK
    from transformer_train import SEQUENCE_LENGTH, prepare_transformer_data, train_transformer

    if not _train_cascade_xgb_lstm_into(
        temp_dir, ticker, db_path, allowed_et_dates, data_fp=data_fp, hz=hz,
    ):
        return False
    xgb_lstm = _build_in_sample_cascade_xgb_lstm_tensor(
        temp_dir, ticker, db_path, allowed_et_dates, hz=hz,
    )
    if xgb_lstm is None:
        return False
    preload_tf = prepare_transformer_data(
        db_path,
        ticker,
        allowed_et_dates=allowed_et_dates,
        min_snapshots_before_sample=max(int(SEQUENCE_LENGTH), int(STREAM_5M_LOOKBACK)),
        ml_horizon_slug=hz,
    )
    Xp, yp, daysp, tickp, nfp = preload_tf
    if Xp is None or yp is None or len(yp) < 10:
        return False
    if len(xgb_lstm) != len(yp):
        log.warning(
            "%s cascade fold: xgb_lstm row mismatch %d vs %d — skip fold",
            ticker,
            len(xgb_lstm),
            len(yp),
        )
        return False
    train_transformer(
        db_path=db_path,
        ticker=ticker,
        model_dir=temp_dir,
        xgb_lstm_probs=xgb_lstm,
        preloaded_sequences=(Xp, yp, daysp, tickp, nfp),
        allowed_et_dates=allowed_et_dates,
        data_fp=data_fp,
        architecture="cascade",
        bypass_torch_resume=True,
        ml_horizon_slug=hz,
    )
    return (temp_dir / f"transformer_{ticker_storage_key(ticker)}_{hz}.pt").exists()


def _train_cascade_meta_oof(
    out_dir: Path,
    ticker: str,
    db_path: str,
    df: Any,
    oof_universe_days: list,
    target_column: str,
    hz: str,
    *,
    data_fp: Optional[dict],
) -> tuple[list, list, str]:
    """Build cascade meta-learner training matrix from expanding-window OOF ML stack layer predictions."""
    import shutil
    import tempfile

    from ml_train import load_data
    from training_cache import expanding_window_oof_folds

    folds = expanding_window_oof_folds(oof_universe_days)
    if not folds:
        X_meta, y_meta = _assemble_meta_ml_layer_prob_vectors(out_dir, ticker, db_path, df, target_column, hz)
        return X_meta, y_meta, "in_sample_no_folds"

    X_meta: list = []
    y_meta: list = []
    tmp_root = Path(tempfile.mkdtemp(prefix=f"oof_cas_meta_{ticker}_{hz}_"))
    try:
        for fi, (tr_days, oof_days) in enumerate(folds):
            fold_dir = tmp_root / f"fold{fi}"
            if not _train_cascade_ml_stack_layers_into(
                fold_dir, ticker, db_path, set(tr_days), data_fp=data_fp, hz=hz,
            ):
                log.warning("%s cascade meta OOF: fold %d ML stack train incomplete — skip", ticker, fi)
                continue
            df_oof = load_data(db_path, ticker=ticker, allowed_et_dates=set(oof_days), ml_horizon_slug=hz)
            if len(df_oof) == 0:
                continue
            fx, fy = _assemble_meta_ml_layer_prob_vectors(fold_dir, ticker, db_path, df_oof, target_column, hz)
            X_meta.extend(fx)
            y_meta.extend(fy)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if len(X_meta) < 10:
        log.warning(
            "%s cascade meta: OOF produced %d usable rows (<10) — in-sample fallback", ticker, len(X_meta),
        )
        X_meta, y_meta = _assemble_meta_ml_layer_prob_vectors(out_dir, ticker, db_path, df, target_column, hz)
        return X_meta, y_meta, "in_sample_fallback"
    return X_meta, y_meta, "expanding_window_oof"


def _xgb_probs_aligned_to_lstm_dataset(
    ds,
    ticker: str,
    db_path: str,
    xgb_model,
    xgb_meta: dict,
    ml_horizon_slug: str,
    *,
    min_ts_utc: Optional[float] = None,
    allowed_et_dates: Optional[set] = None,
) -> Optional[Any]:
    """Build XGB predict_proba rows in exact LSTMDataset sample order (mirror build_lstm_dataset)."""
    import numpy as np
    from ml_train import engineer_single_snapshot
    from lstm_data import (
        extract_rth_snapshots,
        STREAM_5M_LOOKBACK,
        TARGET_CLASSES,
        canonical_reference_spot_from_sequence_window_first_bar,
    )
    from ml_horizon import outcome_column
    from timeframe_config import CANONICAL_TIMEFRAME

    if ds is None or getattr(ds, "n_samples", 0) <= 0:
        return None
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)
    _db = Path(db_path)
    days_data = extract_rth_snapshots(
        ticker,
        timeframe=CANONICAL_TIMEFRAME,
        db_path=_db,
        require_outcome=True,
        allowed_et_dates=allowed_et_dates,
        min_ts_utc=min_ts_utc,
        target_column=label_col,
        skip_normalized_sync=True,
        model_family="lstm",
        horizon_slug=hz,
    )
    snap_index: dict[tuple[str, str], dict] = {}
    for day_key, snapshots in sorted(days_data.items()):
        n_snaps = len(snapshots)
        if n_snaps < STREAM_5M_LOOKBACK:
            continue
        for end_idx in range(STREAM_5M_LOOKBACK, n_snaps):
            window = snapshots[end_idx - STREAM_5M_LOOKBACK : end_idx]
            current = window[-1]
            if min_ts_utc is not None:
                cts = current.get("ts_utc")
                if cts is None or float(cts) < float(min_ts_utc):
                    continue
            target_str = current.get(label_col)
            if target_str is None or target_str not in TARGET_CLASSES:
                continue
            try:
                canonical_reference_spot_from_sequence_window_first_bar(window)
            except ValueError:
                continue
            ts_et = str(current.get("ts_et", ""))
            snap_index[(str(day_key), ts_et)] = current

    probs: list[np.ndarray] = []
    days = getattr(ds, "days", []) or []
    timestamps = getattr(ds, "timestamps", []) or []
    if len(days) != ds.n_samples or len(timestamps) != ds.n_samples:
        log.warning(
            "%s bridge alignment: ds metadata length mismatch days=%d ts=%d n=%d",
            ticker,
            len(days),
            len(timestamps),
            ds.n_samples,
        )
        return None
    for day_key, ts_et in zip(days, timestamps):
        current = snap_index.get((str(day_key), str(ts_et)))
        if current is None:
            log.warning(
                "%s bridge alignment: missing snapshot for day=%s ts_et=%s",
                ticker,
                day_key,
                ts_et,
            )
            return None
        X_row = engineer_single_snapshot(
            prepare_row_for_xgb_features(current),  # RC-340
            xgb_meta.get("category_maps", {}),
            xgb_meta.get("features", []),
            xgb_meta.get("vol_medians", {}),
            ticker,
        )
        if X_row is None:
            log.warning("%s bridge alignment: engineer_single_snapshot failed", ticker)
            return None
        probs.append(xgb_model.predict_proba(X_row.values.astype(np.float64))[0])
    return np.array(probs, dtype=np.float32)


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
    parallel_out: Optional[Path] = None,
) -> dict[str, Any]:
    """Train XGB→LSTM(_XGB)→Transformer(_XGB+LSTM) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)
    days_data: dict | None = None

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
        load_parallel_cascade_bridge,
        copy_parallel_xgb_artifacts_to_cascade,
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
        STREAM_5M_LOOKBACK,
        STREAM_1M_LOOKBACK,
        CONFLUENCE_FEATURES,
        TARGET_CLASSES,
        canonical_reference_spot_from_sequence_window_first_bar,
        micro_reference_spot_from_window,
    )
    from ml_data_common import confluence_features_for_bar

    _conf_cache: dict = {}          # RC-332: one canonical-history pool per (ticker, UTC day)
    from transformer_train import train_transformer, prepare_transformer_data, SEQUENCE_LENGTH
    import pickle
    import numpy as np
    import torch

    _db = Path(db_path)

    used_feature_cache = False
    used_cascade_tensor_cache = False
    used_parallel_cascade_bridge = False
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

    # Step 1: XGB — reuse parallel weights + aligned probs when same-run bridge is available.
    bridge_probs: Optional[np.ndarray] = None
    if not bypass_cache:
        bridge_probs = load_parallel_cascade_bridge(fdir, ticker, data_fp, fk)
    xgb_probs_list: list = []
    xgb_model = None
    xgb_meta: dict = {}
    df = None

    if (
        bridge_probs is not None
        and parallel_out is not None
        and copy_parallel_xgb_artifacts_to_cascade(parallel_out, out_dir, ticker, horizon_suffix=hz)
    ):
        xgb_path = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl"
        xgb_meta_path = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}_meta.json"
        with open(xgb_path, "rb") as f:
            xgb_model = pickle.load(f)
        with open(xgb_meta_path) as f:
            xgb_meta = json.load(f)
        xgb_probs_list = bridge_probs.tolist()
        used_parallel_cascade_bridge = True
        log.info(
            "%s cascade: parallel→cascade bridge hit — skip XGB retrain + prob rescan (%d rows)",
            ticker,
            bridge_probs.shape[0],
        )
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
                "used_parallel_cascade_bridge": used_parallel_cascade_bridge,
                "warm_resume": {},
            }
    else:
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
                "used_parallel_cascade_bridge": False,
                "warm_resume": {},
            }
        train_ticker(
            ticker,
            df,
            model_dir=out_dir,
            prior_data_fingerprint=prior_fp,
            current_data_fingerprint=data_fp,
            ml_horizon_slug=hz,
            db_path=db_path,  # RC-344/F35: same DB as load_data
        )

        xgb_path = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl"
        xgb_meta_path = out_dir / f"xgb_{ticker_storage_key(ticker)}_{hz}_meta.json"
        if not xgb_path.exists():
            return {
                "used_feature_cache": False,
                "used_cascade_tensor_cache": False,
                "used_parallel_cascade_bridge": False,
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
            model_family="xgb", horizon_slug=hz,  # cascade: snapshot feeds XGB-prob generation
        )

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
                # RC-318: eligibility gate mirrors build_lstm_dataset's canonical window drop
                # exactly (xgb_probs_list must align 1:1 with ds.n_samples, checked below).
                # The old two-step _safe_float form used the forbidden last-bar fallback and
                # let NaN through — either way silently breaking the cascade alignment.
                try:
                    canonical_reference_spot_from_sequence_window_first_bar(window)
                except ValueError:
                    continue
                X_row = engineer_single_snapshot(
                    prepare_row_for_xgb_features(current, cache=_conf_cache),  # RC-340
                    xgb_meta.get("category_maps", {}),
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
        prob_count_mismatch = len(xgb_probs_list) - ds.n_samples
        log.warning(
            "%s: LSTM cascade — xgb_probs mismatch %d vs %d (prob_count_mismatch=%d), falling back to parallel LSTM",
            ticker,
            len(xgb_probs_list),
            ds.n_samples,
            prob_count_mismatch,
        )
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

    lstm_pt_path = out_dir / f"lstm_{ticker_storage_key(ticker)}_{hz}.pt"

    # Workstream B2 (commit 2) — train the cascade TRANSFORMER (final stacker) on EXPANDING-
    # WINDOW OUT-OF-FOLD [xgb|lstm] ML layer predictions. Each kept row is scored by xgb/lstm layers
    # trained ONLY on strictly-earlier sessions (fold models); seed-block rows (no earlier
    # fold) are excluded so the stacker never sees an in-sample base prob. The deployed
    # XGB/LSTM in out_dir stay full-data trained — only the transformer's TRAINING features
    # and row set become out-of-fold. The intermediate LSTM-over-XGB feature inside each
    # base trainer stays in-sample to its own train split (cost-bounded K=3 design; the LSTM's
    # own honesty is B3's temporal holdout).
    from training_cache import expanding_window_oof_folds

    if allowed_et_dates is not None:
        _oof_universe_days = sorted(set(allowed_et_dates))
    else:
        from training_cache import db_distinct_rth_et_dates_for_ticker

        _oof_universe_days = db_distinct_rth_et_dates_for_ticker(
            db_path, ticker, label_column=label_col
        )
    _oof_folds = expanding_window_oof_folds(_oof_universe_days)
    use_oof = bool(_oof_folds)

    xgb_lstm = None
    if not use_oof and not bypass_cache:
        xgb_lstm = load_cascade_transformer_tensor_cache(
            fdir, ticker, data_fp, fk, code_fp, xgb_meta_path, lstm_pt_path
        )
        if xgb_lstm is not None and xgb_lstm.shape[0] != len(yp):
            log.info("%s: cascade tensor cache row mismatch %d vs %d — rebuild",
                     ticker, xgb_lstm.shape[0], len(yp))
            xgb_lstm = None

    if xgb_lstm is None:
        import json as _json
        import shutil as _shutil
        import tempfile as _tempfile

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

        if days_data is None:
            from timeframe_config import CANONICAL_TIMEFRAME

            days_data = extract_rth_snapshots(
                ticker,
                timeframe=CANONICAL_TIMEFRAME,
                db_path=_db,
                require_outcome=True,
                allowed_et_dates=allowed_et_dates,
                target_column=label_col,
                model_family="transformer",
                horizon_slug=hz,
            )

        def _assemble_cascade_rows(select_models):
            """Single ordered pass over sorted(days_data) — order MUST match
            prepare_transformer_data so the result aligns positionally to (Xp, yp).
            ``select_models(day_key) -> (xgb_m, xgb_meta_m, lstm_m, lstm_ckpt_m, keep)``.
            Returns (vectors, keep_mask): one entry per emitted row; keep=False rows still
            carry a real vector (computed with deployed models) to preserve positional
            alignment, then the caller filters them out."""
            vectors: list = []
            keeps: list = []
            for day_key, snapshots in sorted(days_data.items()):
                if len(snapshots) < _cascade_hist:
                    continue
                xm, xmeta_m, lm, lck, keep = select_models(day_key)
                for end_idx in range(_cascade_hist, len(snapshots)):
                    window = snapshots[end_idx - SEQUENCE_LENGTH:end_idx]
                    current = window[-1]
                    if not _ts_ok(current):
                        continue
                    if current.get(label_col) not in TARGET_CLASSES:
                        continue
                    try:
                        canonical_reference_spot_from_sequence_window_first_bar(window)
                    except ValueError:
                        continue
                    X_row = engineer_single_snapshot(
                        prepare_row_for_xgb_features(current, cache=_conf_cache),  # RC-340
                        xmeta_m.get("category_maps", {}),
                        xmeta_m.get("features", []),
                        xmeta_m.get("vol_medians", {}), ticker,
                    )
                    if X_row is None:
                        continue
                    xgb_p = xm.predict_proba(X_row.values.astype(np.float64))[0]

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
                    # RC-318: single typed-absence producer (None/NaN/<=0 -> validated lstm_ref).
                    micro_ref = micro_reference_spot_from_window(micro, lstm_ref)
                    seq_1m = [
                        encode_snapshot_1m(training_snapshot_for_sequence_encode(s), micro_ref)
                        for s in micro
                    ]
                    # RC-332: same rewire as the parallel path above — one population
                    # authority for cf_*, and the O(n) ts_et scan disappears with it.
                    conf = confluence_features_for_bar(
                        ticker, current.get("ts_utc"), str(db_path), cache=_conf_cache)
                    conf_vec = np.array([conf[k] for k in CONFLUENCE_FEATURES], dtype=np.float32)
                    conf_vec = np.hstack([conf_vec, xgb_p]).astype(np.float32)

                    mask_5m = np.array(lck.get("mask_5m", [True] * len(seq_5m[0])))
                    mask_1m = np.array(lck.get("mask_1m", [True] * len(seq_1m[0])))
                    mask_conf = np.array(lck.get("mask_conf", [True] * len(conf_vec)))
                    X_5m = np.array([seq_5m], dtype=np.float32)
                    X_1m = np.array([seq_1m], dtype=np.float32)
                    if len(mask_5m) == X_5m.shape[2]:
                        X_5m = X_5m[:, :, mask_5m]
                    if len(mask_1m) == X_1m.shape[2]:
                        X_1m = X_1m[:, :, mask_1m]
                    X_conf = np.array([conf_vec], dtype=np.float32)
                    if len(mask_conf) == len(conf_vec):
                        X_conf = X_conf[:, mask_conf]
                    norm = lck.get("norm_stats", {})
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
                        logits = lm(
                            torch.from_numpy(X_1m).float(),
                            torch.from_numpy(X_5m).float(),
                            torch.from_numpy(X_conf).float(),
                        )
                        lstm_p = torch.softmax(logits, dim=-1).squeeze().numpy()
                    vectors.append(np.concatenate([xgb_p, lstm_p]))
                    keeps.append(bool(keep))
            return vectors, keeps

        def _deployed_selector(_day_key):
            return (xgb_model, xgb_meta, lstm_model, lstm_ckpt, True)

        # Build per-fold ML stack layers (OOF). Each fold trains XGB+LSTM on strictly-earlier
        # sessions; its held-out block's rows are scored by that fold (out-of-sample).
        oof_tmp_root = None
        fold_models: dict = {}
        day_to_fold: dict = {}
        if use_oof:
            from lstm_model import load_lstm as _load_lstm_fold

            oof_tmp_root = Path(_tempfile.mkdtemp(prefix=f"oof_cas_{ticker}_{hz}_"))
            day_to_fold = _oof_day_to_fold_map(_oof_folds)
            for fi, (tr_days, oof_days) in enumerate(_oof_folds):
                fdir_fold = oof_tmp_root / f"fold{fi}"
                if not _train_cascade_xgb_lstm_into(
                    fdir_fold, ticker, db_path, set(tr_days), data_fp=data_fp, hz=hz,
                ):
                    log.warning("%s cascade OOF: fold %d base train incomplete — skip", ticker, fi)
                    continue
                try:
                    with open(fdir_fold / f"xgb_{ticker_storage_key(ticker)}_{hz}.pkl", "rb") as f:
                        _xm = pickle.load(f)
                    with open(fdir_fold / f"xgb_{ticker_storage_key(ticker)}_{hz}_meta.json") as f:
                        _xmeta = _json.load(f)
                    _lm, _lck = _load_lstm_fold(model_dir=fdir_fold, ticker=ticker, ml_horizon_slug=hz)
                except Exception as _fe:  # noqa: BLE001 — fold load is best-effort; row degrades to seed
                    log.warning("%s cascade OOF: fold %d artifact load failed (%s)", ticker, fi, _fe)
                    continue
                if _lm is None:
                    continue
                _lm.eval()
                fold_models[fi] = (_xm, _xmeta, _lm, _lck)
            if not fold_models:
                log.warning("%s cascade OOF: no usable fold models — in-sample fallback", ticker)
                use_oof = False
                _shutil.rmtree(oof_tmp_root, ignore_errors=True)
                oof_tmp_root = None

        if use_oof:
            def _oof_selector(day_key):
                fi = day_to_fold.get(day_key)
                if fi is None or fi not in fold_models:
                    # Seed-block day (no earlier fold) or a fold that failed to train ->
                    # excluded from the transformer's training set (keep=False).
                    return (xgb_model, xgb_meta, lstm_model, lstm_ckpt, False)
                xm, xmeta_m, lm, lck = fold_models[fi]
                return (xm, xmeta_m, lm, lck, True)

            vectors, keeps = _assemble_cascade_rows(_oof_selector)
            if oof_tmp_root is not None:
                _shutil.rmtree(oof_tmp_root, ignore_errors=True)
                oof_tmp_root = None
        else:
            vectors, keeps = _assemble_cascade_rows(_deployed_selector)

        if len(vectors) < 10:
            return {
                "used_feature_cache": used_feature_cache,
                "used_cascade_tensor_cache": False,
                "warm_resume": lstm_rr,
            }
        xgb_lstm = np.array(vectors, dtype=np.float32)

        if use_oof:
            keep_arr = np.array(keeps, dtype=bool)
            if len(keep_arr) == len(yp) and int(keep_arr.sum()) >= 10:
                Xp = Xp[keep_arr]
                yp = yp[keep_arr]
                daysp = daysp[keep_arr]
                tickp = tickp[keep_arr]
                xgb_lstm = xgb_lstm[keep_arr]
                log.info(
                    "%s cascade: transformer trains on %d OUT-OF-FOLD rows (of %d; seed block excluded)",
                    ticker, int(keep_arr.sum()), len(keep_arr),
                )
            else:
                # Misaligned with prepare_transformer_data, or too few OOF rows: rebuild a clean
                # in-sample matrix (deployed models, all rows) rather than feed a mixed
                # in-sample/OOF array. Disclosed degrade to in-sample cascade.
                log.warning(
                    "%s cascade OOF: assembled %d rows vs %d sequences (OOF kept %d) — in-sample fallback",
                    ticker, len(keep_arr), len(yp), int(keep_arr.sum()),
                )
                vectors, _keeps2 = _assemble_cascade_rows(_deployed_selector)
                xgb_lstm = np.array(vectors, dtype=np.float32)
        elif not bypass_cache:
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

    # Meta-learner (cascade stacker). Same OOF contract as parallel meta: train on expanding-
    # window out-of-fold base predictions from cascade checkpoints in each fold dir; deployed
    # XGB/LSTM/Transformer above stay full-data trained.
    from sklearn.linear_model import LogisticRegression

    if allowed_et_dates is not None:
        meta_oof_universe_days = sorted(set(allowed_et_dates))
    else:
        from training_cache import db_distinct_rth_et_dates_for_ticker

        meta_oof_universe_days = db_distinct_rth_et_dates_for_ticker(
            db_path, ticker, label_column=label_col
        )
    X_meta, y_meta, meta_basis = _train_cascade_meta_oof(
        out_dir, ticker, db_path, df, meta_oof_universe_days, label_col, hz, data_fp=data_fp,
    )
    if len(X_meta) >= 10:
        meta_mdl = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_mdl.fit(np.array(X_meta), np.array(y_meta))
        with open(out_dir / f"meta_{ticker_storage_key(ticker)}_{hz}.pkl", "wb") as f:
            pickle.dump(meta_mdl, f)
        _write_meta_training_basis_manifest(
            out_dir, ticker, hz, architecture="cascade", basis=meta_basis, n_rows=len(X_meta),
        )
        log.info(
            "%s cascade meta trained on %d rows (basis=%s)", ticker, len(X_meta), meta_basis,
        )

    warm_resume = {
        **lstm_rr,
        "transformer_warm_resume": tr.warm_resume_used,
        "transformer_warm_resume_detail": tr.warm_resume_detail,
    }
    return {
        "used_feature_cache": used_feature_cache,
        "used_cascade_tensor_cache": used_cascade_tensor_cache,
        "used_parallel_cascade_bridge": used_parallel_cascade_bridge,
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
    parallel_out: Optional[Path] = None,
) -> dict[str, Any]:
    """Production entry: same as nightly scheduler; optional out_dir / allowed_et_dates for compare tooling."""
    dest = out_dir if out_dir is not None else CASCADE_DIR / ticker_storage_key(ticker)  # RC-345/F25
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
        parallel_out=parallel_out,
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
    preflip_candidate_root: Path | None = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry

    run_ticker_outcomes: list[dict[str, Any]] = []
    live_reload_batch: list[dict[str, str]] = []
    hz_sched = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz_sched)
    arch_target_path = scheduler_arch_state_path(hz_sched)
    if wait:
        _wait_until_1615()
    now = _now_et()
    if not allow_non_market_day and not _is_market_day(now):
        log.info(
            "Skipping - not a market day (scheduled mode). "
            "Use --run-now to train on any calendar day when data exists."
        )
        return {"exit_code": 0, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}

    log.info(
        "ML scheduler run started at %s ET (ml_horizon=%s, label=%s, arch_state=%s)",
        now.strftime("%H:%M"),
        hz_sched,
        target_column,
        arch_target_path.name,
    )

    if not Path(DB_PATH).exists():
        log.warning("DB not found at %s", DB_PATH)
        return {"exit_code": 1, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}

    _gate_skip = os.environ.get("ED_ML_SCHEDULER_SKIP_PRE_TRAIN_GATE", "").strip().lower()
    if _gate_skip not in ("1", "true", "yes"):
        try:
            from db_health_audit import run_audit
            from audit_model_readiness import evaluate_training_readiness

            _health = run_audit(
                Path(DB_PATH),
                flow_sample=500,
                deep_flow=False,
                flow_tol=0.02,
                strict_flow=False,
            )
            _readiness = evaluate_training_readiness(Path(DB_PATH))
            _gate_reasons: list[str] = []
            if not _health.get("critical_ok"):
                _gate_reasons.append(
                    "db_health_audit critical_ok=false"
                    + (f": {_health.get('fatal')}" if _health.get("fatal") else "")
                )
            if not _readiness.get("training_ok"):
                _gate_reasons.extend(_readiness.get("reasons") or ["audit_model_readiness NO-GO"])
            if _gate_reasons:
                for _gr in _gate_reasons:
                    log.error("pre_train_gate blocked: %s", _gr)
                return {
                    "exit_code": 2,
                    "ticker_outcomes": [],
                    "ml_horizon": hz_sched,
                    "skipped": True,
                    "pre_train_gate_failed": True,
                    "pre_train_gate_reasons": _gate_reasons,
                }
            log.info("pre_train_gate passed (db_health + model readiness GO)")
            from arch_competition.stack_bundle_eval_v1 import ablation_survivors_training_enabled

            if ablation_survivors_training_enabled():
                from tools.feature_curation_gate import run_survivor_retrain_preflight

                from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS

                _core = list(TRAINING_ANCHOR_TICKERS)
                _spf = run_survivor_retrain_preflight(db_path=str(DB_PATH), tickers=_core)
                if not _spf.get("ready"):
                    _gate_reasons = list(_spf.get("issues") or ["survivor_retrain_preflight_failed"])
                    for _gr in _gate_reasons:
                        log.error("survivor_retrain_preflight blocked: %s", _gr)
                    return {
                        "exit_code": 2,
                        "ticker_outcomes": [],
                        "ml_horizon": hz_sched,
                        "skipped": True,
                        "pre_train_gate_failed": True,
                        "pre_train_gate_reasons": _gate_reasons,
                    }
                log.info("survivor_retrain_preflight passed (confirm pass + floors)")
        except Exception as _gate_exc:
            log.error("pre_train_gate error (fail-closed): %s", _gate_exc, exc_info=True)
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": [str(_gate_exc)],
            }
    else:
        log.warning("pre_train_gate skipped (ED_ML_SCHEDULER_SKIP_PRE_TRAIN_GATE)")

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

    # One sync at scheduler entry; block per-row load_data/extract re-entry for this process
    # (avoids snapshot_id UNIQUE races with the live server's debounced materialize mid-train).
    os.environ["ED_TRAINING_SKIP_INLINE_NORMSYNC"] = "1"

    tickers = _training_ticker_union(DB_PATH, label_column=target_column)
    if not tickers:
        log.warning(
            "No tickers: logging_universe enrollment empty. "
            "Enroll via UI/API (user_persisted/pinned), ensure sync_core rows exist, or run server once; "
            "legacy user_scheduler_tickers.json migrates once. "
            "Training also needs labeled RTH rows per ticker in snapshots_1m_normalized."
        )
        return {"exit_code": 0, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}
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
    except Exception as e:
        log.debug("db_only ticker diagnostic block failed: %s", e, exc_info=True)

    from scheduler_user_tickers import resolve_ml_training_roster

    _before_roster = len(tickers)
    tickers = resolve_ml_training_roster(tickers, DB_PATH)
    if len(tickers) < _before_roster:
        log.info(
            "ML training roster: %d of %d enrolled tickers scheduled (anchors + guest policy)",
            len(tickers),
            _before_roster,
        )

    _pfx = " (promote-from-manifests-only)" if promote_from_manifests_only else ""
    log.info("Tickers (logging_universe authoritative): %s%s", tickers, _pfx)

    from arch_competition.stack_bundle_eval_v1 import ablation_survivors_training_enabled

    if ablation_survivors_training_enabled():
        from arch_competition.promotion_execution import (
            ensure_survivor_retrain_incumbent_reset_at_run_start,
        )
        from tools.feature_curation_gate import (
            run_survivor_edge_probe,
            run_survivor_stack_refit_backtest,
            run_survivor_validation_run,
        )

        _inc_reset = ensure_survivor_retrain_incumbent_reset_at_run_start(MODEL_DIR, tickers)
        log.info(
            "survivor_retrain incumbent reset for scheduled tickers: reset_count=%s reason=%s",
            _inc_reset.get("reset_count"),
            _inc_reset.get("reason"),
        )
        _backtest = run_survivor_stack_refit_backtest(
            tickers=tickers[:3] or None,
            db_path=str(DB_PATH),
        )
        if not _backtest.get("ready_for_production"):
            log.error(
                "survivor_stack_refit_backtest blocked retrain: issues=%s summary=%s",
                _backtest.get("issues"),
                _backtest.get("summary"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(
                    _backtest.get("issues") or ["survivor_stack_refit_backtest_failed"]
                ),
            }
        log.info(
            "survivor_stack_refit_backtest passed: summary=%s",
            _backtest.get("summary"),
        )
        _edge = run_survivor_edge_probe(tickers=tickers[:3] or None)
        if not _edge.get("ready_for_full_retrain"):
            log.error(
                "survivor_edge_probe blocked retrain: issues=%s",
                _edge.get("issues"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(_edge.get("issues") or ["survivor_edge_probe_failed"]),
            }
        log.info(
            "survivor_edge_probe passed: edge_cells=%s",
            (_edge.get("summary") or {}).get("edge_cells"),
        )
        _val = run_survivor_validation_run(tickers=tickers[:3] or None, db_path=str(DB_PATH))
        if not _val.get("ready_for_full_retrain"):
            log.error(
                "survivor_validation_run blocked retrain: issues=%s",
                _val.get("issues"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(_val.get("issues") or ["survivor_validation_run_failed"]),
            }
        log.info(
            "survivor_validation_run passed: cells=%s",
            len(_val.get("cells") or []),
        )

    # DATA-PIPELINE-INTEGRITY-CHAIN Pass 2 (2026-05-26): MVP coercion preflight
    # gate. Catches the row-0 NaN class of failure in seconds instead of after
    # a multi-hour wall-time run. Pass 1 (fd0accd) fixed the NaN-from-pandas
    # root cause; this gate ensures any FUTURE regression of similar shape is
    # caught early. Tickers that fail are excluded from the run with a
    # preflight_failed outcome (distinct from train_failed); the run aborts
    # only if no tickers survive.
    try:
        from features.training_canonical_input import preflight_tickers_for_training

        _pf = preflight_tickers_for_training(DB_PATH, tickers, sample_rows=100)
        if _pf["tickers_failed"]:
            log.warning(
                "preflight: %d of %d tickers failed MVP coercion in %.2fs — excluded from run",
                len(_pf["tickers_failed"]),
                len(tickers),
                _pf["elapsed_sec"],
            )
            for _failed_ticker, _err in _pf["tickers_failed"].items():
                log.warning("  preflight_failed %s: %s", _failed_ticker, _err)
                run_ticker_outcomes.append(
                    outcome_entry(
                        ticker=_failed_ticker,
                        horizon=hz_sched,
                        outcome=TrainingOutcome.preflight_failed,
                        extra={"error": _err, "stage": "preflight"},
                    )
                )
            tickers = [t for t in tickers if t not in _pf["tickers_failed"]]
            if not tickers:
                log.error(
                    "preflight: ALL selected tickers failed MVP coercion; aborting run "
                    "(elapsed=%.2fs). See OPEN_ITEMS DATA-PIPELINE-INTEGRITY-CHAIN.",
                    _pf["elapsed_sec"],
                )
                try:
                    from training_pipeline_status import record_run_finish

                    record_run_finish(
                        ml_horizon=hz_sched,
                        ticker_outcomes=run_ticker_outcomes,
                        exit_code_hint=1,
                    )
                except Exception as _tps_e2:
                    log.debug("record_run_finish on preflight abort: %s", _tps_e2, exc_info=True)
                return {
                    "exit_code": 1,
                    "ticker_outcomes": run_ticker_outcomes,
                    "ml_horizon": hz_sched,
                    "skipped": False,
                    "preflight_blocked": True,
                }
        else:
            log.info(
                "preflight OK: %d of %d tickers passed MVP coercion in %.2fs",
                len(_pf["tickers_ok"]),
                len(tickers),
                _pf["elapsed_sec"],
            )
        if _pf["tickers_no_data"]:
            log.info(
                "preflight: %d tickers had no normalized rows yet (training will skip them naturally): %s",
                len(_pf["tickers_no_data"]),
                _pf["tickers_no_data"][:30],
            )
    except Exception as _pf_e:
        # Preflight gate must NOT itself block a working training run — fail
        # open with a loud warning. The gate is best-effort prevention; the
        # worst case if it errors is the same 65-min wall-time as today.
        log.warning(
            "preflight gate errored (continuing without it — see DATA-PIPELINE-INTEGRITY-CHAIN): %s",
            _pf_e,
            exc_info=True,
        )
    try:
        from training_pipeline_status import enrollment_category_counts, record_run_start

        _enroll_counts = enrollment_category_counts(DB_PATH)
        log.info("Enrolled universe category counts: %s", _enroll_counts)
        record_run_start(
            ml_horizon=hz_sched,
            target_column=target_column,
            tickers=tickers,
            db_path=DB_PATH,
        )
    except Exception as _tps_e:
        log.debug("training_pipeline_status record_run_start: %s", _tps_e, exc_info=True)

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

            # Workstream B1 — single authoritative walk-forward split (shared fn).
            # Train on earlier sessions; evaluate (incl. the governed promotion eval) only
            # on the strictly-later held-out tail, so eval rows are provably disjoint from
            # train rows. Thin tickers (< WALK_FORWARD_MIN_TOTAL_SESSIONS) cannot carve a
            # holdout → fall back to full-RTH (in-sample, NOT promotion-clean; A1 floor still
            # gates promotion). NOTE: passing allowed_et_dates overrides the per-stream
            # ROLLING_WINDOW_RTH_SESSIONS_* windows (both default 0 = full history), matching
            # the train_compare reference; revisit if per-stream windowing is enabled.
            from training_cache import walk_forward_session_split, WALK_FORWARD_MIN_TOTAL_SESSIONS

            wf_train_days, wf_val_days = walk_forward_session_split(
                DB_PATH, ticker, label_column=target_column
            )
            if wf_val_days:
                wf_train_dates: Optional[Set[str]] = set(wf_train_days)
                wf_eval_dates: Optional[Set[str]] = set(wf_val_days)
                assert wf_train_dates.isdisjoint(wf_eval_dates), "walk-forward train/eval overlap"
                log.info(
                    "%s: walk-forward split — train %d sessions, eval %d held-out sessions (%s..%s)",
                    ticker, len(wf_train_days), len(wf_val_days), wf_val_days[0], wf_val_days[-1],
                )
            else:
                wf_train_dates = None
                wf_eval_dates = None
                log.warning(
                    "%s: < %d RTH sessions — walk-forward holdout unavailable; training+eval on "
                    "full RTH (in-sample, not promotion-clean)",
                    ticker, WALK_FORWARD_MIN_TOTAL_SESSIONS,
                )
            fk = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=target_column)
            parallel_key = compute_scheduler_cache_key(
                ticker, "parallel", data_fp, code_fp, target_column=target_column,
            )
            cascade_key = compute_scheduler_cache_key(
                ticker, "cascade", data_fp, code_fp, target_column=target_column,
            )
            parallel_out = PARALLEL_DIR / ticker_storage_key(ticker)  # RC-345/F25: one identity
            cascade_out = CASCADE_DIR / ticker_storage_key(ticker)
            if preflip_candidate_root is not None:
                frozen_t = preflip_candidate_root / ticker_storage_key(ticker)
                parallel_out = frozen_t / "parallel"
                cascade_out = frozen_t / "cascade"
            run_ts = _now_et().isoformat()
            utc_now = datetime.now(timezone.utc)
            _gov_manifest: dict[str, Any] | None = None
            _gov_record: dict[str, Any] | None = None
            auto_exec_result: dict[str, Any] = {}
            skip_train = bool(promote_from_manifests_only or preflip_candidate_root is not None)

            if skip_train:
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
                if not (parallel_out / f"xgb_{ticker_storage_key(ticker)}_{mf_hz}.pkl").exists():
                    log.warning(
                        "%s: --promote-from-manifests skipped (parallel xgb missing for horizon %s)",
                        ticker,
                        mf_hz,
                    )
                    continue
                if not (cascade_out / f"xgb_{ticker_storage_key(ticker)}_{mf_hz}.pkl").exists():
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
                cas_used_bridge = bool(cascade_man.get("used_parallel_cascade_bridge", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
                log.info(
                    "%s: skip train (%s)",
                    ticker,
                    "preflip frozen candidates" if preflip_candidate_root else "--promote-from-manifests",
                )
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

            if not skip_train:
                parallel_ll: Optional[float] = None
                parallel_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                cascade_ll: Optional[float] = None
                cascade_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                n_cascade_rows: int = 0
                cas_used_bridge: bool = False

            if not skip_train and parallel_skip:
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
            elif not skip_train and _scheduler_skip_parallel_train():
                log.info(
                    "%s: parallel train skipped (ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN); eval existing artifacts",
                    ticker,
                )
                parallel_acc, parallel_bal, n_rows, parallel_ll, parallel_realized_metrics = (
                    _evaluate_parallel_on_full_rth(
                        DB_PATH,
                        ticker,
                        parallel_out,
                        allowed_et_dates=wf_eval_dates,
                        target_column=target_column,
                    )
                )
                par_skipped_train = True
                par_skipped_eval = False
                par_used_fc = bool((parallel_man or {}).get("used_feature_cache", False))
                par_used_ctc = bool((parallel_man or {}).get("used_cascade_tensor_cache", False))
                pm_trained_at = str((parallel_man or {}).get("trained_at", run_ts))
                par_warm_resume = (parallel_man or {}).get("warm_resume") or {}
            elif not skip_train:
                log.info("%s: Training parallel...", ticker)
                archive_candidate_directory_before_train(parallel_out, MODEL_DIR, "parallel", ticker)
                par_ret = _train_parallel(
                    ticker,
                    DB_PATH,
                    allowed_et_dates=wf_train_dates,
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
                        DB_PATH, ticker, parallel_out,
                        allowed_et_dates=wf_eval_dates, target_column=target_column,
                    )
                )
                par_skipped_train = False
                par_skipped_eval = False
                par_used_fc = bool(par_ret.get("used_feature_cache", False))
                par_used_ctc = bool(par_ret.get("used_cascade_tensor_cache", False))
                pm_trained_at = run_ts
                par_warm_resume = par_ret.get("warm_resume") or {}

            if not skip_train and cascade_skip:
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
                cas_used_bridge = bool(cascade_man.get("used_parallel_cascade_bridge", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
            elif not skip_train:
                log.info("%s: Training cascade...", ticker)
                archive_candidate_directory_before_train(cascade_out, MODEL_DIR, "cascade", ticker)
                cas_ret = _train_cascade(
                    ticker,
                    DB_PATH,
                    allowed_et_dates=wf_train_dates,
                    bypass_cache=bypass_cache,
                    data_fp=data_fp,
                    code_fp=code_fp,
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    prior_manifest=cascade_man,
                    ml_horizon_slug=hz_sched,
                    parallel_out=parallel_out,
                )
                cascade_acc, cascade_bal, n_cascade_rows, cascade_ll, cascade_realized_metrics = (
                    _evaluate_cascade_on_full_rth(
                        DB_PATH, ticker, cascade_out,
                        allowed_et_dates=wf_eval_dates, target_column=target_column,
                    )
                )
                cas_skipped_train = False
                cas_skipped_eval = False
                cas_used_fc = bool(cas_ret.get("used_feature_cache", False))
                cas_used_ctc = bool(cas_ret.get("used_cascade_tensor_cache", False))
                cas_used_bridge = bool(cas_ret.get("used_parallel_cascade_bridge", False))
                cm_trained_at = run_ts
                cas_warm_resume = cas_ret.get("warm_resume") or {}

            from training_cache import sync_candidate_manifest_lineage_before_governed_eval
            from active_bundle_contract import candidate_bundles_complete
            from training_pipeline_status import get_cache_skip_streak

            artifact_complete, _par_bundle_chk, _cas_bundle_chk = candidate_bundles_complete(
                ticker, hz_sched, parallel_out, cascade_out
            )
            consecutive_cache_skips = get_cache_skip_streak(ticker, hz_sched)
            skip_governed_eval = not artifact_complete

            governed_slice: Optional[dict[str, Any]] = None
            governed_paths: Optional[dict[str, str]] = None

            if skip_governed_eval:
                log.warning(
                    "%s: partial candidate bundle — skip governed eval (parallel_ok=%s cascade_ok=%s)",
                    ticker,
                    _par_bundle_chk.get("compliant"),
                    _cas_bundle_chk.get("compliant"),
                )
                governed_slice = {
                    "schema_version": "1",
                    "error": "partial_candidate_bundle",
                    "failed_closed": True,
                    "issues": {
                        "parallel": _par_bundle_chk.get("issues", []),
                        "cascade": _cas_bundle_chk.get("issues", []),
                    },
                }
            else:
                _lineage_par_eval = {
                    "eval_accuracy": round(parallel_acc, 6),
                    "balanced_accuracy": round(parallel_bal, 6),
                    "n_rows": n_rows,
                    **(
                        {"eval_log_loss": round(parallel_ll, 6)}
                        if parallel_ll is not None
                        else {}
                    ),
                    "realized_contract_metrics": parallel_realized_metrics,
                }
                _lineage_cas_eval = {
                    "eval_accuracy": round(cascade_acc, 6),
                    "balanced_accuracy": round(cascade_bal, 6),
                    "n_rows": n_cascade_rows,
                    **(
                        {"eval_log_loss": round(cascade_ll, 6)}
                        if cascade_ll is not None
                        else {}
                    ),
                    "realized_contract_metrics": cascade_realized_metrics,
                }
                sync_candidate_manifest_lineage_before_governed_eval(
                    parallel_out,
                    ticker=ticker,
                    architecture="parallel",
                    ml_horizon_suffix=hz_sched,
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    training_code_fingerprint=code_fp,
                    evaluation=_lineage_par_eval,
                    trained_at=pm_trained_at,
                )
                sync_candidate_manifest_lineage_before_governed_eval(
                    cascade_out,
                    ticker=ticker,
                    architecture="cascade",
                    ml_horizon_suffix=hz_sched,
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    training_code_fingerprint=code_fp,
                    evaluation=_lineage_cas_eval,
                    trained_at=cm_trained_at,
                )

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
                        allowed_et_dates=wf_eval_dates,
                    )
                    _man = _gov["evaluation_manifest"]
                    _prec = _gov["promotion_record"]
                    _gov_manifest = _man
                    _gov_record = _prec
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
                    log.exception(
                        "%s: governed architecture competition pass failed: %s",
                        ticker,
                        _gov_e,
                    )
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
            active_dir = active_root / ticker_storage_key(ticker)  # RC-345/F25: one identity
            active_dir.mkdir(parents=True, exist_ok=True)

            parallel_xgb_meta = parallel_out / f"xgb_{ticker_storage_key(ticker)}_{hz_sched}_meta.json"
            cascade_xgb_meta = cascade_out / f"xgb_{ticker_storage_key(ticker)}_{hz_sched}_meta.json"
            parallel_prov = load_provenance(parallel_xgb_meta) if parallel_xgb_meta.exists() else None
            cascade_prov = load_provenance(cascade_xgb_meta) if cascade_xgb_meta.exists() else None

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
            except Exception as e:
                log.debug(
                    "compare_parallel_cascade_trade_logs failed: %s",
                    e,
                    exc_info=True,
                )

            # Diagnostic log-loss winner only — production copy uses governed promotion_record (PR4).
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
            report["scheduler_log_loss_winner"] = "parallel" if parallel_wins else "cascade"

            promoted = False
            reason = ""
            auto_active = _scheduler_auto_promote_to_active()
            production_write_held = True
            auto_exec_result: dict[str, Any] = {}

            if (
                isinstance(governed_slice, dict)
                and not governed_slice.get("failed_closed")
                and _gov_manifest is not None
                and _gov_record is not None
            ):
                from arch_competition.promotion_execution import execute_promotion_if_eligible

                auto_exec_result = execute_promotion_if_eligible(
                    MODEL_DIR,
                    ticker,
                    hz_sched,
                    manifest=_gov_manifest,
                    promotion_record=_gov_record,
                    scheduler_run_id=run_ts,
                    db_path=DB_PATH,
                    walk_forward_holdout_available=bool(wf_eval_dates),
                )
                promoted = bool(auto_exec_result.get("executed"))
                production_write_held = not promoted
                if auto_exec_result.get("skipped_reason") == "verify_failed":
                    reason = "verify_failed"
                elif promoted:
                    reason = "governed_auto_promote_ok"
                    if auto_exec_result.get("post_promote_verify_passed") is not False:
                        live_reload_batch.append({"ticker": ticker_storage_key(ticker), "horizon": hz_sched})
                else:
                    reason = str(auto_exec_result.get("skipped_reason") or "promote_skipped")

            report["promoted"] = promoted
            report["promotion_reason"] = "governed_auto_promote" if promoted else reason
            report["rejection_reason"] = reason if not promoted else ""
            report["auto_promote_execution"] = auto_exec_result
            report["production_write_held"] = production_write_held
            report["post_promote_verify_passed"] = auto_exec_result.get("post_promote_verify_passed")
            report["verify_failed_rolled_back"] = auto_exec_result.get("verify_failed_rolled_back")

            if isinstance(governed_slice, dict):
                governed_slice = dict(governed_slice)
                governed_slice["production_write_held"] = production_write_held
                governed_slice["auto_promote_executed"] = promoted
                report["governed_competition"] = governed_slice

            arch_key = ticker_storage_key(ticker)  # RC-345/F25: arch_state writer key == canonical identity (reader in server.py matches)
            prior_arch = arch_state.get(arch_key, {}).get("active_architecture", "none")
            new_arch = prior_arch
            if promoted and auto_exec_result.get("target_architecture"):
                new_arch = auto_exec_result["target_architecture"]
            prov_dict = arch_state.get(arch_key, {}).get("provenance")
            if promoted:
                win_prov = cascade_prov if new_arch == "cascade" else parallel_prov
                if win_prov:
                    prov_dict = win_prov.to_dict()
            arch_state[arch_key] = {
                "active_architecture": new_arch,
                "parallel_acc": round(parallel_acc, 4),
                "cascade_acc": round(cascade_acc, 4),
                "parallel_balanced_acc": round(parallel_bal, 4),
                "cascade_balanced_acc": round(cascade_bal, 4),
                "last_trained_at": _now_et().strftime("%Y-%m-%d %H:%M:%S"),
                "rows_at_training": n_rows,
                "promoted": promoted,
                "promotion_reason": reason if not promoted else "ok",
                "provenance": prov_dict,
            }
            if promoted:
                log.info("%s: governed auto-promote to %s", ticker, new_arch)
            elif auto_active and reason:
                log.info("%s: auto-promote held: %s", ticker, reason)

            if governed_slice is not None:
                arch_state[arch_key]["governed_competition"] = governed_slice

            promotion_decision_record = {
                "scheduler_log_loss_winner": "parallel" if parallel_wins else "cascade",
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
                except Exception as e:
                    log.debug("load_dashboard_eval_metrics failed: %s", e, exc_info=True)
                _prev["updated_at"] = run_ts
                _prev["primary_metric"] = "eval_log_loss"
                _prev["realized_contract_pricing"] = (
                    "entry=ask exit=bid; underlying stop/target/time exit per Call plan; "
                    "trade logs: models/realized_contract_trade_log_parallel.csv + _cascade.csv"
                )
                _prev[ticker_storage_key(ticker)] = {  # RC-345/F25: dashboard-metrics key canonical (reader matches)
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
                    "scheduler_log_loss_winner": "parallel" if parallel_wins else "cascade",
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
                    used_parallel_cascade_bridge=cas_used_bridge,
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

            outcome_val, consecutive_cache_skips = _resolve_ticker_outcome(
                ticker=ticker,
                horizon=hz_sched,
                skip_governed_eval=skip_governed_eval,
                governed_slice=governed_slice,
                parallel_skip=parallel_skip,
                cascade_skip=cascade_skip,
                promoted=promoted,
                consecutive_cache_skips=consecutive_cache_skips,
                auto_exec_result=auto_exec_result,
            )
            would_promote = bool(
                isinstance(governed_slice, dict)
                and governed_slice.get("would_promote_challenger")
                and not governed_slice.get("failed_closed")
            )
            _apply_pr2_report_fields(
                report,
                outcome=outcome_val,
                horizon=hz_sched,
                artifact_complete=artifact_complete,
                consecutive_cache_skips=consecutive_cache_skips,
                governed_slice=governed_slice,
            )
            run_ticker_outcomes.append(
                outcome_entry(
                    ticker=ticker,
                    horizon=hz_sched,
                    outcome=TrainingOutcome(outcome_val),
                    extra={"would_promote": would_promote} if would_promote else None,
                )
            )

            _append_training_report(report)

        except Exception as e:
            log.exception("%s: failed: %s", ticker, e)
            run_ticker_outcomes.append(
                outcome_entry(
                    ticker=ticker,
                    horizon=hz_sched,
                    outcome=TrainingOutcome.train_failed,
                    extra={"error": str(e)},
                )
            )

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

    exit_code = compute_run_exit_code(run_ticker_outcomes)
    try:
        from training_pipeline_status import record_run_finish

        # P1-1: ticker_outcomes populated with per-(ticker, horizon) TrainingOutcome values.
        record_run_finish(
            ml_horizon=hz_sched,
            ticker_outcomes=run_ticker_outcomes,
            exit_code_hint=exit_code,
        )
    except Exception as _tps_fin:
        log.debug("training_pipeline_status record_run_finish: %s", _tps_fin, exc_info=True)

    # Active artifact verification — flag non-compliant
    try:
        from verify_active_models import check_artifact_compliance, _get_active_tickers
        for tkr in _get_active_tickers():
            r = check_artifact_compliance(tkr)
            if not r["compliant"]:
                log.warning("NON-COMPLIANT active %s: %s — retrain required", tkr, r["issues"])
    except Exception as e:
        log.warning("Verification skipped: %s", e)

    live_reload_report: dict[str, Any] | None = None
    if live_reload_batch:
        try:
            from arch_competition.live_model_reload import build_live_reload_report

            live_reload_report = build_live_reload_report(reloads=live_reload_batch)
            log.info("live_reload batch: %s", live_reload_report)
        except Exception as _lr_e:
            log.warning("live_reload batch failed: %s", _lr_e, exc_info=True)

    return {
        "exit_code": exit_code,
        "ticker_outcomes": run_ticker_outcomes,
        "ml_horizon": hz_sched,
        "skipped": False,
        "live_reload": live_reload_report,
    }


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

    Default (ED_ML_SCHEDULER_ALL_HORIZONS=1): trains/promotes all four primary horizons per night.
    Set ED_ML_SCHEDULER_ALL_HORIZONS=0 to run only ED_ML_SCHEDULER_HORIZON (legacy single-horizon).
    """
    global _bg_scheduler_thread, _bg_scheduler_started
    with _bg_scheduler_lock:
        if _bg_scheduler_started:
            log.warning("start_background_scheduler: already started; ignoring duplicate")
            return
        _bg_scheduler_started = True

    from arch_competition.scheduler_auto_promote_policy import scheduler_nightly_all_horizons_enabled

    single_hz = os.environ.get("ED_ML_SCHEDULER_HORIZON", DEFAULT_ML_HORIZON_SLUG)

    def _run_scheduled_nightly() -> None:
        if scheduler_nightly_all_horizons_enabled():
            from ml_horizon import ALL_GOVERNED_HORIZONS

            agg_exit = 0
            for _hz in ALL_GOVERNED_HORIZONS:
                log.info("ML scheduler background: starting horizon %s", _hz)
                summary = run_once(
                    wait=False,
                    force_retrain=False,
                    bypass_cache=False,
                    allow_non_market_day=False,
                    promote_from_manifests_only=False,
                    ml_horizon_slug=str(_hz),
                )
                code = int(summary.get("exit_code", 0))
                agg_exit |= code
                log.info(
                    "ML scheduler background: finished horizon %s (exit=%s)",
                    _hz,
                    code,
                )
            if agg_exit:
                log.warning(
                    "ML scheduler background: one or more horizons failed (agg_exit=%s)",
                    agg_exit,
                )
        else:
            run_once(
                wait=False,
                force_retrain=False,
                bypass_cache=False,
                allow_non_market_day=False,
                promote_from_manifests_only=False,
                ml_horizon_slug=str(single_hz),
            )

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
                _run_scheduled_nightly()
            except Exception as e:
                log.exception("ML scheduler background loop error: %s", e)
                time.sleep(300.0)

    _bg_scheduler_thread = threading.Thread(
        target=_loop,
        name="ml_scheduler_nightly",
        daemon=True,
    )
    _bg_scheduler_thread.start()
    if scheduler_nightly_all_horizons_enabled():
        log.info(
            "ML background scheduler thread started (nightly market-day %02d:%02d ET; all horizons)",
            RUN_AT_HOUR,
            RUN_AT_MINUTE,
        )
    else:
        log.info(
            "ML background scheduler thread started (nightly market-day %02d:%02d ET; horizon=%s)",
            RUN_AT_HOUR,
            RUN_AT_MINUTE,
            single_hz,
        )


# deprecated aliases — unified-stack vocabulary migration
_meta_base_triplet = _meta_ml_layer_triplet
_assemble_meta_base_prob_vectors = _assemble_meta_ml_layer_prob_vectors
_train_parallel_base_models_into = _train_parallel_ml_stack_layers_into
_train_cascade_base_models_into = _train_cascade_ml_stack_layers_into


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    ap.add_argument(
        "--run-now",
        action="store_true",
        help="Do not wait until 16:15 ET; allow training on weekends/holidays (still needs DB rows).",
    )
    ap.add_argument("--force-retrain", action="store_true",
                    help="Ignore scheduler cache-skip / inhibitor and force a fresh train+eval this run "
                         "(training_cache skip bypass). Does NOT override the promotion score/row gate.")
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
    ap.add_argument(
        "--all-horizons",
        action="store_true",
        help=(
            "Sequentially invoke run_once for every primary decision horizon (1c, 5c, 15c, 60c) "
            "in one CLI call. Each horizon runs train/eval/governed competition; when "
            "ED_SCHEDULER_AUTO_PROMOTE=1 (default), execute_promotion_if_eligible copies the "
            "seven-file bundle into models/active/ or models/active_{hz}/. Overrides --horizon."
        ),
    )
    ap.add_argument(
        "--preflip-candidate-root",
        type=str,
        default=None,
        help="PR4: skip train; use frozen candidate tree at PATH/{TICKER}/parallel|cascade for governed eval + auto-promote replay.",
    )
    args = ap.parse_args()
    _preflip_root = Path(args.preflip_candidate_root).resolve() if args.preflip_candidate_root else None
    run_now = bool(args.run_now or args.promote_from_manifests)
    if args.all_horizons:
        from ml_horizon import ALL_GOVERNED_HORIZONS

        agg_exit = 0
        for _hz in ALL_GOVERNED_HORIZONS:
            log.info("ml_scheduler --all-horizons: starting horizon %s", _hz)
            summary = run_once(
                wait=False if run_now else args.wait,
                force_retrain=args.force_retrain,
                bypass_cache=args.bypass_cache,
                allow_non_market_day=run_now,
                promote_from_manifests_only=bool(args.promote_from_manifests),
                preflip_candidate_root=_preflip_root,
                ml_horizon_slug=str(_hz),
            )
            agg_exit |= int(summary.get("exit_code", 0))
            log.info("ml_scheduler --all-horizons: finished horizon %s (exit=%s)", _hz, summary.get("exit_code"))
        sys.exit(agg_exit)
    summary = run_once(
        wait=False if run_now else args.wait,
        force_retrain=args.force_retrain,
        bypass_cache=args.bypass_cache,
        allow_non_market_day=run_now,
        promote_from_manifests_only=bool(args.promote_from_manifests),
        preflip_candidate_root=_preflip_root,
        ml_horizon_slug=str(args.horizon),
    )
    sys.exit(int(summary.get("exit_code", 0)))
