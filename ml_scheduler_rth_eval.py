"""ml_scheduler.py RTH evaluation/comparison cluster (RC-REHAB-1, ml_scheduler.py
decomposition slice 3): runs the trained parallel/cascade model stacks over full RTH
history to score accuracy/balanced-accuracy/log-loss/realized-contract metrics. Called
directly from `run_once` as a sibling step to training, not from inside the trainers.

Monkeypatch note: `_evaluate_parallel_on_full_rth`/`_evaluate_cascade_on_full_rth`
themselves are patched directly on the `ml_scheduler` module (`unittest.mock.patch(
"ml_scheduler._evaluate_parallel_on_full_rth", ...)` in
tests/test_arch_competition_eval_runner.py) -- ml_scheduler.py re-exports both, which
covers this (their caller, run_once, stays in ml_scheduler.py and the external callers
in arch_competition/eval_runner.py, verify_ml_pipeline.py, tools/run_shuffled_label_control.py,
train_compare.py already import `from ml_scheduler import _evaluate_parallel_on_full_rth`
etc.).

`_load_rth_rows_for_ticker` and `_eval_hist_db_for_labeled_rows` (both in
ml_scheduler_rth_data.py) are ALSO monkeypatched directly on `ml_scheduler`
(monkeypatch.setattr("ml_scheduler._load_rth_rows_for_ticker", ...) /
monkeypatch.setattr("ml_scheduler._eval_hist_db_for_labeled_rows", ...), same test file,
multiple sites). Since both eval functions here now live in a DIFFERENT file than
ml_scheduler.py, their calls to these two symbols go through a LAZY `import ml_scheduler`
at call time so the patched value on the `ml_scheduler` module is what actually gets
called -- a top-level `from ml_scheduler_rth_data import ...` here would bind the
ORIGINAL function into this file's own globals at import time, and the test's
`ml_scheduler.` patch would never touch that binding, silently defeating it.

`_infer_slug_from_target_column`, `_strict_off_for_candidate_inference`, and
`_empty_realized_metrics` are NOT monkeypatched anywhere (verified via repo-wide grep
before this move) -- ordinary top-level imports.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Set

from numeric_contract import direction_from_normalized_triplet
from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN
from ml_scheduler_support import _infer_slug_from_target_column, _strict_off_for_candidate_inference
from ml_scheduler_rth_data import _empty_realized_metrics

log = logging.getLogger("ml_scheduler")


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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    rows = ml_scheduler._load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
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

                hist_db = ml_scheduler._eval_hist_db_for_labeled_rows(db_path, ticker, rows)

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
                    # every non-None _ensemble_parallel_probs return path (uniform/meta/
                    # weighted-average) always populates all three keys
                    pu, pd, pf = (
                        float(result["up"]),
                        float(result["down"]),
                        float(result["flat"]),
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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    rows = ml_scheduler._load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
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

                hist_db = ml_scheduler._eval_hist_db_for_labeled_rows(db_path, ticker, rows)

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
                    # every non-None _predict_transformer return path always populates all
                    # three keys (CLASS_NAMES[i] dict comprehension, never partial)
                    pu = float(tr_p["up"])
                    pd = float(tr_p["down"])
                    pf = float(tr_p["flat"])
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
