"""ml_scheduler.py parallel-stack training cluster (RC-REHAB-1, ml_scheduler.py
decomposition slice 5): trains XGB + LSTM + Transformer + Meta into a candidate dir
(production or arch-compare tooling), including the expanding-window OOF meta-training
matrix build shared in spirit (not in code -- see ml_scheduler_meta_stack.py) with the
cascade architecture.

Monkeypatch note: `_train_parallel_ml_stack_layers_into` and
`_assemble_meta_ml_layer_prob_vectors` are both patched directly on the `ml_scheduler`
module (`monkeypatch.setattr(ml_scheduler, "_train_parallel_ml_stack_layers_into", ...)`
/ `monkeypatch.setattr(ml_scheduler, "_assemble_meta_ml_layer_prob_vectors", ...)`,
tests/test_oof_stacker.py). `_train_parallel_meta_oof` calls both by bare name -- the
former now lives in THIS SAME file (moving together, same class of hazard as
ml_scheduler_rth_data.py's _diagnostic_db_tickers_not_enrolled/_get_tickers_with_rth_data
pair), the latter lives in ml_scheduler_meta_stack.py -- both calls go through a lazy
`import ml_scheduler` so the patched value is what actually gets called.

Circular-import note (distinct from the monkeypatch class above): `train_parallel_candidate`
calls `_xgb_probs_aligned_to_lstm_dataset`, which is NOT monkeypatched but STAYS in
ml_scheduler.py (it belongs to the cascade-stack training cluster, a later, larger slice
of this same decomposition, coupled here to seed the parallel->cascade bridge cache).
ml_scheduler.py imports this module at its own top level, before its own
`_xgb_probs_aligned_to_lstm_dataset` def is reached further down the file -- a top-level
`from ml_scheduler import _xgb_probs_aligned_to_lstm_dataset` here would be a real import
cycle. This call also goes through the same lazy `import ml_scheduler` pattern, purely to
avoid that cycle (whether or not it is ever monkeypatched).

`_train_parallel` reaches the module-level PARALLEL_DIR config constant (defined in
ml_scheduler.py, imported by THIS module before ml_scheduler.py finishes its own load) the
same lazy way.
"""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any, Optional, Set

from instrument_identity import ticker_storage_key
from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug, outcome_column
from ml_scheduler_meta_stack import _write_meta_training_basis_manifest

log = logging.getLogger("ml_scheduler")


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
    if ds is not None and ds.n_samples > 0:
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

    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    folds = expanding_window_oof_folds(oof_universe_days)
    if not folds:
        X_meta, y_meta = ml_scheduler._assemble_meta_ml_layer_prob_vectors(
            out_dir, ticker, db_path, df, target_column, hz
        )
        return X_meta, y_meta, "in_sample_no_folds"

    X_meta: list = []
    y_meta: list = []
    tmp_root = Path(tempfile.mkdtemp(prefix=f"oof_par_{ticker}_{hz}_"))
    try:
        for fi, (tr_days, oof_days) in enumerate(folds):
            fold_dir = tmp_root / f"fold{fi}"
            if not ml_scheduler._train_parallel_ml_stack_layers_into(
                fold_dir, ticker, db_path, set(tr_days), data_fp=data_fp, hz=hz,
            ):
                log.warning("%s parallel meta OOF: fold %d ML stack train incomplete — skip", ticker, fi)
                continue
            df_oof = load_data(db_path, ticker=ticker, allowed_et_dates=set(oof_days), ml_horizon_slug=hz)
            if len(df_oof) == 0:
                continue
            fx, fy = ml_scheduler._assemble_meta_ml_layer_prob_vectors(
                fold_dir, ticker, db_path, df_oof, target_column, hz
            )
            X_meta.extend(fx)
            y_meta.extend(fy)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if len(X_meta) < 10:
        log.warning(
            "%s parallel meta: OOF produced %d usable rows (<10) — in-sample fallback", ticker, len(X_meta),
        )
        X_meta, y_meta = ml_scheduler._assemble_meta_ml_layer_prob_vectors(
            out_dir, ticker, db_path, df, target_column, hz
        )
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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

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
            and ds.n_samples >= 10
            and xgb_pkl.is_file()
            and xgb_meta_p.is_file()
            and not bypass_cache
        ):
            with open(xgb_pkl, "rb") as f:
                _bridge_xgb = pickle.load(f)
            with open(xgb_meta_p, encoding="utf-8") as f:
                _bridge_meta = json.load(f)
            _aligned_probs = ml_scheduler._xgb_probs_aligned_to_lstm_dataset(
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
    if ds is not None and ds.n_samples > 0:
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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    dest = out_dir if out_dir is not None else ml_scheduler.PARALLEL_DIR / ticker_storage_key(ticker)  # RC-345/F25
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
