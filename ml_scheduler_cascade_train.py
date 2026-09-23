"""ml_scheduler.py cascade-stack training cluster (RC-REHAB-1, ml_scheduler.py
decomposition final slice): trains XGB→LSTM(_XGB)→Transformer(_XGB+LSTM) into a candidate
dir (production or arch-compare tooling), including the expanding-window OOF cascade
tensor/meta-training builds. By far the largest and most tightly-coupled cluster in this
decomposition -- every internal call graph and monkeypatch claim here was verified by
reading the real function bodies and the real test file content directly, not inferred
from names or a single-line grep (a prior slice's grep missed a multi-line
`monkeypatch.setattr(...)` call; this file's design was built assuming grep alone is not
reliable evidence).

Monkeypatch note: `_train_cascade_ml_stack_layers_into` and
`_assemble_meta_ml_layer_prob_vectors` are both patched directly on the `ml_scheduler`
module (`monkeypatch.setattr(ml_scheduler, "_train_cascade_ml_stack_layers_into", ...)` /
`monkeypatch.setattr(ml_scheduler, "_assemble_meta_ml_layer_prob_vectors", ...)`,
tests/test_oof_stacker.py). `_train_cascade_meta_oof` calls both by bare name -- the
former now lives in THIS SAME file (moving together), the latter lives in
ml_scheduler_meta_stack.py -- both calls go through a lazy `import ml_scheduler` so the
patched value is what actually gets called.

`_oof_day_to_fold_map`, `_train_cascade_xgb_lstm_into`, `_build_in_sample_cascade_xgb_lstm_tensor`,
`_xgb_probs_aligned_to_lstm_dataset`, `train_cascade_candidate`, `_train_cascade` are each
directly CALLED by name in tests (`ml_scheduler.<name>(...)` or
`from ml_scheduler import <name>`) but never REPLACED -- verified via a repo-wide,
multi-line-aware search, not a single grep pattern. Their internal same-file calls to
each other stay as plain top-level references (no lazy-import needed; nothing here
monkeypatches them).

`_xgb_probs_aligned_to_lstm_dataset` has one external caller outside this file:
ml_scheduler_parallel_train.py's train_parallel_candidate reaches it via a lazy
`import ml_scheduler; ml_scheduler._xgb_probs_aligned_to_lstm_dataset(...)` (written when
that module was created, in slice 5, anticipating this move) to seed the
parallel->cascade bridge cache -- this module needs no code to support that; the
re-export from ml_scheduler.py is what makes it resolve correctly.

`_train_cascade` reaches the module-level CASCADE_DIR config constant (defined in
ml_scheduler.py) the same lazy way slice 5's `_train_parallel` reaches PARALLEL_DIR.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Set

from instrument_identity import ticker_storage_key
from ml_data_common import prepare_row_for_xgb_features
from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug, outcome_column
from ml_scheduler_meta_stack import _write_meta_training_basis_manifest

log = logging.getLogger("ml_scheduler")


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
                xgb_meta.get("category_maps", {}), xgb_meta.get("features", []),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                xgb_meta.get("vol_medians", {}), ticker,  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
            )
            if X_row is None:
                continue
            xgb_probs_list.append(xgb_model.predict_proba(X_row.values.astype(np.float64))[0])

    ds = build_lstm_dataset(
        tickers=[ticker], db_path=Path(db_path), allowed_et_dates=allowed_et_dates, ml_horizon_slug=hz,
    )
    if ds is None or ds.n_samples < 10:
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
                xgb_meta.get("category_maps", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                xgb_meta.get("features", []),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                xgb_meta.get("vol_medians", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
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

            mask_5m = np.array(lstm_ckpt.get("mask_5m", [True] * len(seq_5m[0])))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
            mask_1m = np.array(lstm_ckpt.get("mask_1m", [True] * len(seq_1m[0])))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
            mask_conf = np.array(lstm_ckpt.get("mask_conf", [True] * len(conf_vec)))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
            X_5m = np.array([seq_5m], dtype=np.float32)
            X_1m = np.array([seq_1m], dtype=np.float32)
            if len(mask_5m) == X_5m.shape[2]:
                X_5m = X_5m[:, :, mask_5m]
            if len(mask_1m) == X_1m.shape[2]:
                X_1m = X_1m[:, :, mask_1m]
            X_conf = np.array([conf_vec], dtype=np.float32)
            if len(mask_conf) == len(conf_vec):
                X_conf = X_conf[:, mask_conf]
            norm = lstm_ckpt.get("norm_stats", {})  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate norm_stats; the current writer always includes it, an existing bundle on disk may not
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

    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    folds = expanding_window_oof_folds(oof_universe_days)
    if not folds:
        X_meta, y_meta = ml_scheduler._assemble_meta_ml_layer_prob_vectors(
            out_dir, ticker, db_path, df, target_column, hz
        )
        return X_meta, y_meta, "in_sample_no_folds"

    X_meta: list = []
    y_meta: list = []
    tmp_root = Path(tempfile.mkdtemp(prefix=f"oof_cas_meta_{ticker}_{hz}_"))
    try:
        for fi, (tr_days, oof_days) in enumerate(folds):
            fold_dir = tmp_root / f"fold{fi}"
            if not ml_scheduler._train_cascade_ml_stack_layers_into(
                fold_dir, ticker, db_path, set(tr_days), data_fp=data_fp, hz=hz,
            ):
                log.warning("%s cascade meta OOF: fold %d ML stack train incomplete — skip", ticker, fi)
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
            "%s cascade meta: OOF produced %d usable rows (<10) — in-sample fallback", ticker, len(X_meta),
        )
        X_meta, y_meta = ml_scheduler._assemble_meta_ml_layer_prob_vectors(
            out_dir, ticker, db_path, df, target_column, hz
        )
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

    if ds is None or ds.n_samples <= 0:
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
            # extract_rth_snapshots does SELECT * on the snapshots table; ts_et is a real
            # column, always a key in the row dict
            ts_et = str(current["ts_et"])
            snap_index[(str(day_key), ts_et)] = current

    probs: list[np.ndarray] = []
    # ds is confirmed non-None above; LSTMDataset.days/.timestamps are required dataclass
    # fields (no default) always set to a real list by build_lstm_dataset
    days = ds.days
    timestamps = ds.timestamps
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
            xgb_meta.get("category_maps", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
            xgb_meta.get("features", []),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
            xgb_meta.get("vol_medians", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
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
                    xgb_meta.get("category_maps", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                    xgb_meta.get("features", []),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                    xgb_meta.get("vol_medians", {}), ticker,  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
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
                        xmeta_m.get("category_maps", {}),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                        xmeta_m.get("features", []),  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
                        xmeta_m.get("vol_medians", {}), ticker,  # caps-ok: xgb_..._meta.json is a persisted artifact that can predate this key (schema evolution across the writer's own history); train_ticker's CURRENT writer always includes it, but an already-trained bundle on disk may not
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

                    mask_5m = np.array(lck.get("mask_5m", [True] * len(seq_5m[0])))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
                    mask_1m = np.array(lck.get("mask_1m", [True] * len(seq_1m[0])))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
                    mask_conf = np.array(lck.get("mask_conf", [True] * len(conf_vec)))  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate ablation masks; the current writer always includes it, an existing bundle on disk may not
                    X_5m = np.array([seq_5m], dtype=np.float32)
                    X_1m = np.array([seq_1m], dtype=np.float32)
                    if len(mask_5m) == X_5m.shape[2]:
                        X_5m = X_5m[:, :, mask_5m]
                    if len(mask_1m) == X_1m.shape[2]:
                        X_1m = X_1m[:, :, mask_1m]
                    X_conf = np.array([conf_vec], dtype=np.float32)
                    if len(mask_conf) == len(conf_vec):
                        X_conf = X_conf[:, mask_conf]
                    norm = lck.get("norm_stats", {})  # caps-ok: the LSTM checkpoint is a persisted artifact trained by an earlier code version that may predate norm_stats; the current writer always includes it, an existing bundle on disk may not
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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    dest = out_dir if out_dir is not None else ml_scheduler.CASCADE_DIR / ticker_storage_key(ticker)  # RC-345/F25
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
