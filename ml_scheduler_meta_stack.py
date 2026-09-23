"""ml_scheduler.py meta/OOF shared-assembly cluster (RC-REHAB-1, ml_scheduler.py
decomposition slice 4): the meta-learner training-matrix assembly shared by BOTH the
parallel and cascade architectures, plus the training-basis manifest (ML-PIPE-V2 Phase 3)
that travels with a meta artifact so serving/promotion can tell OOF-governed evidence
apart from an in-sample fallback.

Cross-cutting note: `_assemble_meta_ml_layer_prob_vectors` is called from BOTH
`_train_parallel_meta_oof` and `_train_cascade_meta_oof`, neither of which has moved out
of ml_scheduler.py yet (they belong to the parallel-stack and cascade-stack training
clusters, later slices) -- this is why the shared assembly gets its own module rather
than living inside either training cluster.

Monkeypatch note: `_assemble_meta_ml_layer_prob_vectors` is patched directly on the
`ml_scheduler` module (`monkeypatch.setattr(ml_scheduler, "_assemble_meta_ml_layer_prob_vectors",
fake_assemble)`, 6 sites in tests/test_oof_stacker.py) -- ml_scheduler.py re-exports it,
which covers `_train_parallel_meta_oof`/`_train_cascade_meta_oof`'s bare-name calls (both
stay in ml_scheduler.py, so they resolve through ml_scheduler.py's own globals, which the
re-export binds and the monkeypatch replaces directly -- verified by reading both callers'
bodies, not assumed) and `ms._meta_ml_layer_triplet(...)` / test direct-attribute access.

`_eval_hist_db_for_labeled_rows` (ml_scheduler_rth_data.py, re-exported by ml_scheduler.py)
is ALSO monkeypatched directly on `ml_scheduler` (tests/test_arch_competition_eval_runner.py).
No current test exercises that patch through the REAL `_assemble_meta_ml_layer_prob_vectors`
body (every test that touches it replaces the whole function instead), but the call here
still goes through a lazy `import ml_scheduler` for design consistency with the rest of
this decomposition -- a top-level import would silently defeat that patch for any future
test that does exercise this path, and there is no cost to getting it right now.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from instrument_identity import ticker_storage_key

log = logging.getLogger("ml_scheduler")


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
    import ml_scheduler  # module-attribute access only -- see this file's own docstring
    from ml_scheduler_support import _strict_off_for_candidate_inference

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
            hist_db = ml_scheduler._eval_hist_db_for_labeled_rows(db_path, ticker, rows)
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
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
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
