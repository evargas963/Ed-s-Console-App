"""
training_cache.py — Feature tensor cache + scheduler run manifest for ML training
=================================================================================
Directory layout:
  models/cache/features/{feature_cache_key}/
    lstm_tensors.npz, lstm_dataset_meta.json
    transformer_parallel_tensors.npz
    cascade_transformer_xgb_lstm.npz, cascade_transformer_identity.json
    feature_cache_identity.json

  models/{parallel|cascade}/{ticker}/scheduler_run_manifest.json  (schema v2)

Invalidation: data_fingerprint, training_code_fingerprint, feature/label/pipeline versions,
artifact SHA-256, optional max-age (policy).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

log = logging.getLogger("training_cache")

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, DEFAULT_TRAINING_LABEL_COLUMN

MANIFEST_FILENAME = "scheduler_run_manifest.json"
FEATURE_CACHE_ROOT = Path(__file__).parent / "models" / "cache" / "features"
LSTM_NPZ_NAME = "lstm_tensors.npz"
LSTM_META_NAME = "lstm_dataset_meta.json"
TRANSFORMER_NPZ_NAME = "transformer_parallel_tensors.npz"
CASCADE_TF_NPZ_NAME = "cascade_transformer_xgb_lstm.npz"
CASCADE_TF_IDENTITY_NAME = "cascade_transformer_identity.json"
FEATURE_IDENTITY_NAME = "feature_cache_identity.json"


def _app_models_dir() -> Path:
    return Path(__file__).parent / "models"


def file_sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_training_code_fingerprint() -> str:
    """SHA-256 of concatenated (path + length + contents) for policy-listed sources."""
    from training_cache_policy import CODE_FINGERPRINT_SOURCE_FILES, training_repo_root

    root = training_repo_root()
    h = hashlib.sha256()
    for rel in sorted(CODE_FINGERPRINT_SOURCE_FILES):
        p = root / rel
        if not p.is_file():
            h.update(f"MISSING:{rel}\n".encode())
            continue
        raw = p.read_bytes()
        h.update(rel.encode())
        h.update(str(len(raw)).encode())
        h.update(raw)
    return h.hexdigest()


def xgb_meta_content_sha256(meta_path: Path) -> str:
    if not meta_path.is_file():
        return f"MISSING:{meta_path.resolve()}"
    return file_sha256_hex(meta_path)


def db_training_fingerprint(
    db_path: str, ticker: str, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> dict[str, Any]:
    """
    Raw-data identity for one ticker: table, min/max ts_utc, row count.
    Must match ml_train.load_data filter (RTH, label column, weekday).
    """
    from ml_data_common import filter_ts_utc_list_to_rth, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME

    t = ticker
    conn = sqlite3.connect(db_path)
    where = training_base_where_clause(label_column, include_ticker=True)
    rows = conn.execute(
        f"SELECT ts_utc FROM snapshots_1m_normalized WHERE {where}",
        (CANONICAL_TIMEFRAME, t),
    ).fetchall()
    conn.close()
    ts_list = filter_ts_utc_list_to_rth(
        [float(r[0]) for r in rows if r[0] is not None]
    )
    if not ts_list:
        return {
            "table": "snapshots_1m_normalized",
            "timeframe": CANONICAL_TIMEFRAME,
            "ticker": str(t),
            "min_ts_utc": None,
            "max_ts_utc": None,
            "row_count": 0,
        }
    return {
        "table": "snapshots_1m_normalized",
        "timeframe": CANONICAL_TIMEFRAME,
        "ticker": str(t),
        "min_ts_utc": float(min(ts_list)),
        "max_ts_utc": float(max(ts_list)),
        "row_count": len(ts_list),
    }


def db_training_floor_stats(
    db_path: str, ticker: str, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> dict[str, Any]:
    """Per-ticker DATA-floor stats for promotion gating (Workstream A1).

    Returns labeled-row count and usable-RTH-day count using the SAME RTH /
    label / weekday filter as ``db_training_fingerprint`` (so the floor matches
    what training actually consumes). A usable day has
    ``>= training_provenance.USABLE_RTH_DAY_MIN_ROWS`` labeled 1m rows.
    """
    from ml_data_common import filter_ts_utc_list_to_rth, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME
    from training_provenance import USABLE_RTH_DAY_MIN_ROWS

    conn = sqlite3.connect(db_path)
    where = training_base_where_clause(label_column, include_ticker=True)
    rows = conn.execute(
        f"SELECT ts_utc, ts_et FROM snapshots_1m_normalized WHERE {where}",
        (CANONICAL_TIMEFRAME, ticker),
    ).fetchall()
    conn.close()

    rth_ts = set(
        filter_ts_utc_list_to_rth([float(r[0]) for r in rows if r[0] is not None])
    )
    per_day: dict[str, int] = {}
    for ts_utc, ts_et in rows:
        if ts_utc is None or float(ts_utc) not in rth_ts:
            continue
        day = str(ts_et)[:10] if ts_et else None
        if not day:
            continue
        per_day[day] = per_day.get(day, 0) + 1

    labeled_rows = sum(per_day.values())
    usable_days = sum(1 for c in per_day.values() if c >= USABLE_RTH_DAY_MIN_ROWS)
    return {
        "ticker": str(ticker),
        "labeled_rows": int(labeled_rows),
        "usable_days": int(usable_days),
        "label_column": label_column,
    }


def compute_scheduler_cache_key(
    ticker: str,
    architecture: str,
    data_fp: dict,
    code_fp: str,
    *,
    target_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> str:
    """Full run identity: data + versions + architecture + training source code fingerprint."""
    from training_provenance import (
        FEATURE_SCHEMA_VERSION,
        PREPROCESSING_VERSION,
        LABEL_CONFIG_VERSION,
        SCHEDULER_PIPELINE_VERSION,
    )
    from training_cache_policy import (
        ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
    )
    from arch_competition.stack_bundle_eval_v1 import ablation_survivors_fingerprint_part
    from features.canonical_contract import (
        CANONICAL_FEATURE_CONTRACT_VERSION,
        CANONICAL_FEATURE_TIMEFRAME,
    )

    raw = "|".join(
        [
            ticker.upper(),
            architecture,
            CANONICAL_FEATURE_CONTRACT_VERSION,
            CANONICAL_FEATURE_TIMEFRAME,
            _fingerprint_key_part(data_fp, "min_ts_utc"),
            _fingerprint_key_part(data_fp, "max_ts_utc"),
            _fingerprint_row_count_part(data_fp),
            _fingerprint_key_part(data_fp, "table"),
            _fingerprint_key_part(data_fp, "timeframe"),
            FEATURE_SCHEMA_VERSION,
            PREPROCESSING_VERSION,
            LABEL_CONFIG_VERSION,
            SCHEDULER_PIPELINE_VERSION,
            target_column,
            str(ROLLING_WINDOW_RTH_SESSIONS_TABULAR),
            str(ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE),
            ablation_survivors_fingerprint_part(),
            code_fp,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_feature_cache_key(
    ticker: str, data_fp: dict, code_fp: str, *, target_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> str:
    """Shared LSTM / parallel-Transformer / cascade-input tensor cache identity."""
    from training_provenance import (
        FEATURE_SCHEMA_VERSION,
        PREPROCESSING_VERSION,
        LABEL_CONFIG_VERSION,
    )
    from training_cache_policy import ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE
    from arch_competition.stack_bundle_eval_v1 import ablation_survivors_fingerprint_part
    from features.canonical_contract import (
        CANONICAL_FEATURE_CONTRACT_VERSION,
        CANONICAL_FEATURE_TIMEFRAME,
    )

    raw = "|".join(
        [
            ticker.upper(),
            "shared_features",
            CANONICAL_FEATURE_CONTRACT_VERSION,
            CANONICAL_FEATURE_TIMEFRAME,
            _fingerprint_key_part(data_fp, "min_ts_utc"),
            _fingerprint_key_part(data_fp, "max_ts_utc"),
            _fingerprint_row_count_part(data_fp),
            _fingerprint_key_part(data_fp, "table"),
            _fingerprint_key_part(data_fp, "timeframe"),
            FEATURE_SCHEMA_VERSION,
            PREPROCESSING_VERSION,
            LABEL_CONFIG_VERSION,
            ablation_survivors_fingerprint_part(),
            target_column,
            str(ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE),
            code_fp,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def feature_cache_dir(feature_cache_key: str) -> Path:
    p = FEATURE_CACHE_ROOT / feature_cache_key
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_distinct_rth_et_dates_for_ticker(
    db_path: str, ticker: str, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> list[str]:
    """Ordered YYYY-MM-DD session labels from DB (same filter as db_training_fingerprint)."""
    from ml_data_common import et_date_str_from_ts_utc, filter_ts_utc_list_to_rth, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME

    t = ticker.upper()
    conn = sqlite3.connect(db_path)
    where = training_base_where_clause(label_column, include_ticker=True)
    rows = conn.execute(
        f"SELECT ts_utc FROM snapshots_1m_normalized WHERE {where} ORDER BY ts_utc",
        (CANONICAL_TIMEFRAME, t),
    ).fetchall()
    conn.close()
    ts_list = filter_ts_utc_list_to_rth([float(r[0]) for r in rows if r[0] is not None])
    dates: list[str] = []
    seen: set[str] = set()
    for ts in ts_list:
        d = et_date_str_from_ts_utc(ts)
        if d not in seen:
            seen.add(d)
            dates.append(d)
    return dates


WALK_FORWARD_MAX_VAL_SESSIONS: int = 3
WALK_FORWARD_MIN_TOTAL_SESSIONS: int = 10


def split_sessions_walk_forward(
    days: Sequence[str],
    *,
    max_val_sessions: int = WALK_FORWARD_MAX_VAL_SESSIONS,
    min_total_sessions: int = WALK_FORWARD_MIN_TOTAL_SESSIONS,
) -> tuple[list[str], list[str]]:
    """Pure chronological walk-forward split (Workstream B1).

    The single authoritative split: hold out the most-recent ``n_val`` sorted
    sessions for evaluation, train on all earlier sessions, so eval rows are
    provably disjoint from — and strictly later than — train rows. ``days`` MUST be
    sorted ascending (``db_distinct_rth_et_dates_for_ticker`` is). Matches the
    canonical logic previously inline in train_compare:
    ``n_val = min(max_val_sessions, max(1, len - min_total_sessions))``.

    When fewer than ``min_total_sessions`` are available a holdout cannot be carved
    without starving training, so returns ``(list(days), [])`` and the caller falls
    back to no-holdout (and must not claim a clean walk-forward for that ticker).
    """
    ordered = list(days)
    if len(ordered) < min_total_sessions:
        return ordered, []
    n_val = min(max_val_sessions, max(1, len(ordered) - min_total_sessions))
    n_train = len(ordered) - n_val
    return ordered[:n_train], ordered[n_train:]


def walk_forward_session_split(
    db_path: str,
    ticker: str,
    *,
    label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
    max_val_sessions: int = WALK_FORWARD_MAX_VAL_SESSIONS,
    min_total_sessions: int = WALK_FORWARD_MIN_TOTAL_SESSIONS,
) -> tuple[list[str], list[str]]:
    """DB-backed walk-forward split: distinct RTH ET sessions then ``split_sessions_walk_forward``."""
    days = db_distinct_rth_et_dates_for_ticker(db_path, ticker, label_column=label_column)
    return split_sessions_walk_forward(
        days, max_val_sessions=max_val_sessions, min_total_sessions=min_total_sessions
    )


WALK_FORWARD_OOF_FOLDS: int = 3


def expanding_window_oof_folds(
    days: Sequence[str], *, n_folds: int = WALK_FORWARD_OOF_FOLDS,
) -> list[tuple[list[str], list[str]]]:
    """Expanding-window out-of-fold session folds (Workstream B2).

    Partition the ordered ``days`` into ``n_folds + 1`` contiguous chronological blocks
    ``B0..Bn``; for ``i`` in ``1..n_folds`` yield ``(train_days, oof_days)`` where
    ``train_days = B0..B(i-1)`` (strictly earlier) and ``oof_days = Bi``. ``B0`` is the
    seed block — it never appears as an OOF fold, so OOF predictions cover ``n_folds /
    (n_folds + 1)`` of the rows. Every OOF row is scored by a model trained ONLY on
    strictly-earlier sessions → no in-sample base probabilities feed the stacker.

    ``days`` MUST be sorted ascending. Returns ``[]`` when there are fewer sessions than
    blocks (cannot form ``n_folds + 1`` non-empty blocks) — caller falls back to the
    in-sample assembly (and must not claim clean OOF for that ticker).
    """
    ordered = list(days)
    n_blocks = int(n_folds) + 1
    if int(n_folds) < 1 or len(ordered) < n_blocks:
        return []
    # Contiguous, near-even chronological blocks (no gaps, no overlap).
    bounds = [round(j * len(ordered) / n_blocks) for j in range(n_blocks + 1)]
    blocks = [ordered[bounds[j]:bounds[j + 1]] for j in range(n_blocks)]
    if any(len(b) == 0 for b in blocks):
        return []
    folds: list[tuple[list[str], list[str]]] = []
    for i in range(1, n_blocks):
        train_days = [d for b in blocks[:i] for d in b]
        oof_days = list(blocks[i])
        folds.append((train_days, oof_days))
    return folds


def min_ts_utc_for_last_n_rth_sessions(
    db_path: str, ticker: str, n_sessions: int, *, label_column: str = DEFAULT_TRAINING_LABEL_COLUMN,
) -> Optional[float]:
    """
    Minimum ts_utc over the last N distinct RTH session dates (weekends/holidays excluded by DB rows).
    n_sessions <= 0 or fewer than N+1 sessions in DB => None (use full history).
    """
    if n_sessions is None or int(n_sessions) <= 0:
        return None
    ns = int(n_sessions)
    dates = db_distinct_rth_et_dates_for_ticker(db_path, ticker, label_column=label_column)
    if len(dates) <= ns:
        return None
    keep = dates[-ns:]
    from ml_data_common import et_date_str_from_ts_utc, filter_ts_utc_list_to_rth, training_base_where_clause
    from timeframe_config import CANONICAL_TIMEFRAME

    conn = sqlite3.connect(db_path)
    where = training_base_where_clause(label_column, include_ticker=True)
    rows = conn.execute(
        f"SELECT ts_utc FROM snapshots_1m_normalized WHERE {where}",
        (CANONICAL_TIMEFRAME, ticker.upper()),
    ).fetchall()
    conn.close()
    keep_set = set(keep)
    ts_list = [
        float(r[0])
        for r in rows
        if r[0] is not None
        and et_date_str_from_ts_utc(float(r[0])) in keep_set
    ]
    ts_list = filter_ts_utc_list_to_rth(ts_list)
    if not ts_list:
        return None
    return float(min(ts_list))


def compare_tabular_data_fingerprint_from_df(df, ticker: str) -> dict:
    """Same shape as db_training_fingerprint for train_compare slices (tabular rows only)."""
    import pandas as pd
    from timeframe_config import CANONICAL_TIMEFRAME

    t = ticker.upper()
    if df is None or len(df) == 0:
        return {
            "table": "compare_train_slice",
            "timeframe": CANONICAL_TIMEFRAME,
            "ticker": t,
            "min_ts_utc": None,
            "max_ts_utc": None,
            "row_count": 0,
        }
    ts = df["ts_utc"]
    s = pd.to_numeric(ts, errors="coerce")
    mn = float(s.min())
    mx = float(s.max())
    return {
        "table": "compare_train_slice",
        "timeframe": CANONICAL_TIMEFRAME,
        "ticker": t,
        "min_ts_utc": mn,
        "max_ts_utc": mx,
        "row_count": int(len(df)),
    }


def _fingerprint_key_part(data_fp: dict, field: str) -> str:
    if field not in data_fp or data_fp.get(field) is None:
        return ""
    return str(data_fp[field])


def _fingerprint_row_count_part(data_fp: dict) -> str:
    if "row_count" not in data_fp or data_fp.get("row_count") is None:
        return ""
    try:
        return str(int(data_fp["row_count"]))
    except (TypeError, ValueError):
        return ""


def _normalize_data_fp(d: Optional[dict]) -> dict:
    """Stable compare across JSON round-trip (int/float for ts_utc, row_count)."""
    if not d:
        return {}

    def _num(x):
        from numeric_contract import float_finite_or_none

        return float_finite_or_none(x)

    rc_raw = d.get("row_count")
    if rc_raw is None:
        row_count = None
    else:
        try:
            row_count = int(rc_raw)
        except (TypeError, ValueError):
            row_count = None

    return {
        "table": str(d.get("table", "")),
        "timeframe": str(d.get("timeframe", "")),
        "ticker": str(d.get("ticker", "")),
        "min_ts_utc": _num(d.get("min_ts_utc")),
        "max_ts_utc": _num(d.get("max_ts_utc")),
        "row_count": row_count,
    }


def _meta_required_positive_int(meta: dict, key: str) -> int | None:
    if key not in meta or meta.get(key) is None:
        return None
    try:
        value = int(meta[key])
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _canonical_lineage_identity_ok(stored: dict) -> bool:
    """Require persisted canonical contract + timeframe to match the code (fail-closed)."""
    from features.canonical_contract import (
        CANONICAL_FEATURE_CONTRACT_VERSION,
        CANONICAL_FEATURE_TIMEFRAME,
    )

    if stored.get("canonical_feature_contract_version") != CANONICAL_FEATURE_CONTRACT_VERSION:
        return False
    if stored.get("canonical_timeframe") != CANONICAL_FEATURE_TIMEFRAME:
        return False
    return True


def _write_feature_identity(cache_dir: Path, ticker: str, data_fp: dict, feature_key: str) -> None:
    from training_provenance import (
        FEATURE_SCHEMA_VERSION,
        PREPROCESSING_VERSION,
        LABEL_CONFIG_VERSION,
    )
    from features.training_canonical_input import training_canonical_lineage_header

    payload = {
        "ticker": ticker.upper(),
        "feature_cache_key": feature_key,
        "data_fingerprint": data_fp,
        "feature_version": FEATURE_SCHEMA_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "label_version": LABEL_CONFIG_VERSION,
        **training_canonical_lineage_header(),
    }
    (cache_dir / FEATURE_IDENTITY_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _feature_identity_matches(cache_dir: Path, ticker: str, data_fp: dict, feature_key: str) -> bool:
    p = cache_dir / FEATURE_IDENTITY_NAME
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not _canonical_lineage_identity_ok(d):
        return False
    return (
        d.get("feature_cache_key") == feature_key
        and d.get("ticker") == ticker.upper()
        and _normalize_data_fp(d.get("data_fingerprint")) == _normalize_data_fp(data_fp)
    )


def save_lstm_feature_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
    dataset,
) -> None:
    """Persist LSTMDataset arrays + JSON meta (tickers, timestamps, days, diagnostics)."""
    np.savez_compressed(
        cache_dir / LSTM_NPZ_NAME,
        X_5m=dataset.X_5m,
        X_1m=dataset.X_1m,
        X_conf=dataset.X_conf,
        y=dataset.y,
    )
    from features.training_canonical_input import training_canonical_lineage_header

    meta = {
        "tickers": dataset.tickers,
        "timestamps": dataset.timestamps,
        "days": dataset.days,
        "training_timeframe": getattr(dataset, "training_timeframe", ""),
        "target_column": getattr(dataset, "target_column", "") or "",
        "ml_horizon_slug": getattr(dataset, "ml_horizon_slug", "") or "",
        "target_definition": getattr(dataset, "target_definition", ""),
        "n_features_5m": dataset.n_features_5m,
        "n_features_1m": dataset.n_features_1m,
        "n_confluence": dataset.n_confluence,
        "n_samples": dataset.n_samples,
        "n_days": dataset.n_days,
        "n_tickers": dataset.n_tickers,
        "class_distribution": dataset.class_distribution,
        "skipped_reasons": dataset.skipped_reasons,
        **training_canonical_lineage_header(),
    }
    (cache_dir / LSTM_META_NAME).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_feature_identity(cache_dir, ticker, data_fp, feature_key)
    log.info("LSTM feature cache written: %s", cache_dir)


def load_lstm_feature_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
):
    """Return lstm_data.LSTMDataset or None if missing/invalid."""
    from lstm_data import LSTMDataset

    npz_p = cache_dir / LSTM_NPZ_NAME
    meta_p = cache_dir / LSTM_META_NAME
    if not npz_p.exists() or not meta_p.exists():
        return None
    if not _feature_identity_matches(cache_dir, ticker, data_fp, feature_key):
        log.info("LSTM feature cache identity mismatch: %s", cache_dir)
        return None
    try:
        z = np.load(npz_p)
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("LSTM feature cache load failed: %s", e)
        return None
    if not _canonical_lineage_identity_ok(meta):
        log.info("LSTM feature cache meta canonical lineage mismatch: %s", cache_dir)
        return None
    n_features_5m = _meta_required_positive_int(meta, "n_features_5m")
    n_features_1m = _meta_required_positive_int(meta, "n_features_1m")
    n_confluence = _meta_required_positive_int(meta, "n_confluence")
    if n_features_5m is None or n_features_1m is None or n_confluence is None:
        log.info("LSTM feature cache meta missing feature dimensions: %s", cache_dir)
        return None
    n_samples = _meta_required_positive_int(meta, "n_samples")
    if n_samples is None:
        n_samples = int(len(z["y"]))
    if n_samples <= 0:
        log.info("LSTM feature cache meta invalid n_samples: %s", cache_dir)
        return None
    return LSTMDataset(
        X_5m=z["X_5m"],
        X_1m=z["X_1m"],
        X_conf=z["X_conf"],
        y=z["y"],
        tickers=meta.get("tickers", []),
        timestamps=meta.get("timestamps", []),
        days=meta.get("days", []),
        training_timeframe=meta.get("training_timeframe", ""),
        target_column=str(meta.get("target_column") or ""),
        ml_horizon_slug=str(meta.get("ml_horizon_slug") or ""),
        target_definition=meta.get("target_definition", ""),
        n_features_5m=n_features_5m,
        n_features_1m=n_features_1m,
        n_confluence=n_confluence,
        n_samples=n_samples,
        n_days=int(meta.get("n_days", 0)),
        n_tickers=int(meta.get("n_tickers", 0)),
        class_distribution=meta.get("class_distribution", {}),
        skipped_reasons=meta.get("skipped_reasons", {}),
    )


def save_transformer_parallel_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
    X: np.ndarray,
    y: np.ndarray,
    days: np.ndarray,
    tickers_arr: np.ndarray,
    n_features: int,
) -> None:
    np.savez_compressed(
        cache_dir / TRANSFORMER_NPZ_NAME,
        X=X,
        y=y,
        days=days,
        tickers=tickers_arr,
        n_features=np.array([n_features], dtype=np.int32),
    )
    _write_feature_identity(cache_dir, ticker, data_fp, feature_key)
    log.info("Transformer parallel feature cache written: %s", cache_dir)


def load_transformer_parallel_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]]:
    npz_p = cache_dir / TRANSFORMER_NPZ_NAME
    if not npz_p.exists():
        return None
    if not _feature_identity_matches(cache_dir, ticker, data_fp, feature_key):
        return None
    try:
        z = np.load(npz_p)
        nf = int(z["n_features"][0])
        return z["X"], z["y"], z["days"], z["tickers"], nf
    except Exception as e:
        log.warning("Transformer feature cache load failed: %s", e)
        return None


def cascade_tensor_bind_slug(xgb_meta_path: Path, lstm_pt_path: Path) -> str:
    """Weights bind: XGB meta + LSTM .pt bytes (first path segment of cascade cache dir)."""
    h = hashlib.sha256()
    h.update(xgb_meta_content_sha256(xgb_meta_path).encode())
    if lstm_pt_path.is_file():
        h.update(file_sha256_hex(lstm_pt_path).encode())
    return h.hexdigest()[:16]


def xgb_lstm_tensor_sha256(arr: np.ndarray) -> str:
    a = np.ascontiguousarray(arr, dtype=np.float32)
    return hashlib.sha256(a.tobytes()).hexdigest()


def cascade_tensor_cache_dir_name(weights_bind: str, tensor_sha256_hex: str) -> str:
    """Full cache folder: cascade_tf_{weights16}_{tensor16} — tensor hash is part of the path key."""
    return f"cascade_tf_{weights_bind}_{tensor_sha256_hex[:16]}"


def _cascade_tensor_subdir_for_save(
    cache_dir: Path, weights_bind: str, tensor_sha256_hex: str
) -> Path:
    p = cache_dir / cascade_tensor_cache_dir_name(weights_bind, tensor_sha256_hex)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _iter_cascade_tensor_subdirs(cache_dir: Path, weights_bind: str) -> list[Path]:
    """Newest tensor-qualified dirs first; then legacy cascade_tf_{weights_bind}/ (no tensor suffix)."""
    pat = f"cascade_tf_{weights_bind}_*"
    dirs = [p for p in cache_dir.glob(pat) if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    legacy = cache_dir / f"cascade_tf_{weights_bind}"
    if legacy.is_dir():
        dirs.append(legacy)
    return dirs


def _cascade_identity_matches(
    subdir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
    code_fp: str,
    xgb_meta_sha: str,
    lstm_pt_sha: str,
    npz_n_rows: int,
    tensor_sha_expected: str,
    arr_on_disk: np.ndarray,
) -> bool:
    p = subdir / CASCADE_TF_IDENTITY_NAME
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if xgb_lstm_tensor_sha256(arr_on_disk) != tensor_sha_expected:
        return False
    if not _canonical_lineage_identity_ok(d):
        return False
    return (
        d.get("ticker") == ticker.upper()
        and d.get("feature_cache_key") == feature_key
        and d.get("training_code_fingerprint") == code_fp
        and d.get("xgb_meta_sha256") == xgb_meta_sha
        and (
            d.get("lstm_checkpoint_sha256") == lstm_pt_sha
            or d.get("lstm_1c_sha256") == lstm_pt_sha
        )
        and d.get("xgb_lstm_tensor_sha256") == tensor_sha_expected
        and int(d.get("n_cascade_rows", -1)) == int(npz_n_rows)
        and _normalize_data_fp(d.get("data_fingerprint")) == _normalize_data_fp(data_fp)
    )


def save_cascade_transformer_tensor_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
    code_fp: str,
    xgb_meta_path: Path,
    lstm_pt_path: Path,
    xgb_lstm: np.ndarray,
) -> None:
    """Persist (N,6) XGB+LSTM prob rows; path = weights_bind + tensor_sha (both in directory name)."""
    bind = cascade_tensor_bind_slug(xgb_meta_path, lstm_pt_path)
    xgb_lstm = xgb_lstm.astype(np.float32)
    tsha = xgb_lstm_tensor_sha256(xgb_lstm)
    sub = _cascade_tensor_subdir_for_save(cache_dir, bind, tsha)
    np.savez_compressed(sub / CASCADE_TF_NPZ_NAME, xgb_lstm=xgb_lstm)
    xms = xgb_meta_content_sha256(xgb_meta_path)
    lsha = file_sha256_hex(lstm_pt_path) if lstm_pt_path.is_file() else ""
    from features.training_canonical_input import training_canonical_lineage_header

    payload = {
        "ticker": ticker.upper(),
        "feature_cache_key": feature_key,
        "training_code_fingerprint": code_fp,
        "data_fingerprint": data_fp,
        "cascade_bind_slug": bind,
        "xgb_meta_sha256": xms,
        "lstm_checkpoint_sha256": lsha,
        "xgb_lstm_tensor_sha256": tsha,
        "n_cascade_rows": int(xgb_lstm.shape[0]),
        "n_cascade_cols": int(xgb_lstm.shape[1]) if xgb_lstm.ndim == 2 else 0,
        **training_canonical_lineage_header(),
    }
    (sub / CASCADE_TF_IDENTITY_NAME).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    log.info("Cascade Transformer tensor cache written: %s rows=%d bind=%s", sub, xgb_lstm.shape[0], bind)


def load_cascade_transformer_tensor_cache(
    cache_dir: Path,
    ticker: str,
    data_fp: dict,
    feature_key: str,
    code_fp: str,
    xgb_meta_path: Path,
    lstm_pt_path: Path,
) -> Optional[np.ndarray]:
    bind = cascade_tensor_bind_slug(xgb_meta_path, lstm_pt_path)
    xms = xgb_meta_content_sha256(xgb_meta_path)
    lsha = file_sha256_hex(lstm_pt_path) if lstm_pt_path.is_file() else ""
    for sub in _iter_cascade_tensor_subdirs(cache_dir, bind):
        npz_p = sub / CASCADE_TF_NPZ_NAME
        if not npz_p.exists():
            continue
        try:
            z = np.load(npz_p)
            arr = z["xgb_lstm"]
            n = int(arr.shape[0])
        except Exception as e:
            log.warning("Cascade Transformer cache load failed: %s", e)
            continue
        try:
            idata = json.loads((sub / CASCADE_TF_IDENTITY_NAME).read_text(encoding="utf-8"))
            texp = str(idata.get("xgb_lstm_tensor_sha256", ""))
        except Exception:
            continue
        if not _cascade_identity_matches(
            sub, ticker, data_fp, feature_key, code_fp, xms, lsha, n, texp, arr
        ):
            log.info("Cascade Transformer cache identity mismatch: %s", sub)
            continue
        return arr
    return None


def compute_artifact_sha256_map(out_dir: Path, basenames: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in basenames:
        p = out_dir / n
        if p.is_file():
            out[n] = file_sha256_hex(p)
        else:
            out[n] = f"MISSING:{p.resolve()}"
    return out


def validate_manifest_artifact_hashes(
    manifest: dict,
    out_dir: Path,
    ticker: str,
    architecture: str,
    horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG,
) -> tuple[bool, str]:
    """Strict: artifact_sha256 must exist, keys must match required artifact set exactly, all hashes verified."""
    required = (
        parallel_artifact_basenames(ticker, horizon_suffix=horizon_suffix)
        if architecture == "parallel"
        else cascade_artifact_basenames(ticker, horizon_suffix=horizon_suffix)
    )
    req_set = set(required)
    expected = manifest.get("artifact_sha256")
    if not isinstance(expected, dict) or len(expected) == 0:
        return False, "artifact_sha256_missing_or_empty"
    if set(expected.keys()) != req_set:
        return False, "artifact_sha256_key_set_mismatch"
    for name in required:
        p = out_dir / name
        if not p.is_file():
            return False, f"missing_file:{name}"
        if file_sha256_hex(p) != expected[name]:
            return False, f"hash_mismatch:{name}"
    return True, "ok"


_TRAINED_AT_UNAVAILABLE_AGE_DAYS: float = 1e9
"""COH-I-B sentinel: marker age returned when the trained_at field is missing OR
unparseable. Callers compare ``age > MANIFEST_SKIP_MAX_AGE_DAYS`` and treat this
as "force retrain"; the bare 1e9 magic is named so callers can also detect the
sentinel case explicitly when they need to distinguish "trained_at unavailable"
from "trained_at is real but old"."""


def trained_at_age_days(trained_at_iso: str, now: Optional[datetime] = None) -> float:
    """Age in days since trained_at; ``_TRAINED_AT_UNAVAILABLE_AGE_DAYS`` when missing/unparseable.

    COH-I-B closure: the two unavailable branches (missing field vs parse fail) are kept
    separate at the log layer so the operator can tell them apart, while the numeric
    return value still trips the same retrain gate.
    """
    if not trained_at_iso:
        log.debug("training_cache.trained_at_age_days: manifest missing trained_at field; sentinel age applied")
        return _TRAINED_AT_UNAVAILABLE_AGE_DAYS
    now = now or datetime.now(timezone.utc)
    try:
        ts = trained_at_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except (ValueError, TypeError, AttributeError) as e:
        log.debug("training_cache.trained_at_age_days: manifest trained_at unparseable (%r): %s — sentinel age applied", trained_at_iso, e)
        return _TRAINED_AT_UNAVAILABLE_AGE_DAYS


def full_skip_eligible(
    manifest: Optional[dict],
    scheduler_key: str,
    data_fp: dict,
    code_fp: str,
    out_dir: Path,
    ticker: str,
    architecture: str,
    *,
    bypass_cache: bool,
    force_retrain: bool = False,
    skip_inhibit_reason: Optional[str] = None,
    now: Optional[datetime] = None,
    horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG,
) -> tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Returns (eligible, skip_reason, retrain_reason, cache_miss_reason).
    skip_reason set when eligible True; retrain_reason / cache_miss_reason when False.
    """
    from training_cache_policy import (
        MANIFEST_SKIP_MAX_AGE_DAYS,
        MANIFEST_SCHEMA_VERSION,
        MIN_MANIFEST_SCHEMA_FOR_FULL_SKIP,
    )

    if bypass_cache:
        return False, None, "bypass_cache_flag", "user_bypass"

    if force_retrain:
        return False, None, "force_retrain_flag", "cli_force_retrain"

    if skip_inhibit_reason:
        return False, None, skip_inhibit_reason, "scheduler_skip_inhibited"

    if not manifest:
        return False, None, "no_manifest", "manifest_missing"

    sv = int(manifest.get("schema_version", 0))
    if sv < MIN_MANIFEST_SCHEMA_FOR_FULL_SKIP or sv != MANIFEST_SCHEMA_VERSION:
        return False, None, "manifest_schema_mismatch", "schema_strict_v2_required"

    if manifest.get("training_code_fingerprint") != code_fp:
        return False, None, "code_fingerprint_mismatch", "training_sources_changed"

    if not manifest_matches_current(
        manifest,
        scheduler_key,
        data_fp,
        code_fp,
        ticker,
        ml_horizon_suffix=horizon_suffix,
    ):
        return False, None, "scheduler_key_or_data_mismatch", "data_or_versions_changed"

    if MANIFEST_SKIP_MAX_AGE_DAYS > 0:
        age = trained_at_age_days(str(manifest.get("trained_at", "")), now)
        if age >= _TRAINED_AT_UNAVAILABLE_AGE_DAYS:
            # COH-I-B: distinguish "trained_at unavailable" from "trained_at is real but old"
            # in the caller-visible reason string. The numeric age still trips the same
            # retrain gate either way.
            return False, None, "manifest_trained_at_unavailable", "max_age_exceeded"
        if age > MANIFEST_SKIP_MAX_AGE_DAYS:
            return False, None, f"manifest_stale_age_{age:.1f}d", "max_age_exceeded"

    ok_hash, hreason = validate_manifest_artifact_hashes(
        manifest, out_dir, ticker, architecture, horizon_suffix=horizon_suffix,
    )
    if not ok_hash:
        return False, None, f"artifact_integrity:{hreason}", "hash_mismatch_or_missing"

    if not artifacts_present(out_dir, ticker, architecture, horizon_suffix=horizon_suffix):
        return False, None, "artifacts_incomplete", "binary_missing"

    return True, "full_skip_manifest_artifacts_hashes_age_ok", None, None


def archive_candidate_directory_before_train(
    candidate_dir: Path,
    models_root: Path,
    arch_label: str,
    ticker: str,
) -> None:
    """Copy models/{parallel|cascade}/{ticker}/ to models/_artifact_archive/{arch}/{ticker}/{utc}/ before overwrite."""
    from training_cache_policy import MODEL_ARCHIVE_ENABLED, MODEL_ARCHIVE_SUBDIR

    if not MODEL_ARCHIVE_ENABLED:
        return
    if not candidate_dir.is_dir():
        return
    if not any(candidate_dir.iterdir()):
        return
    import shutil
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = models_root / MODEL_ARCHIVE_SUBDIR / arch_label / ticker.upper() / ts
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate_dir, dest, dirs_exist_ok=False)
        log.info("Archived candidate %s/%s -> %s", arch_label, ticker, dest)
    except Exception as e:
        log.warning("Archive skipped %s: %s", candidate_dir, e)


def prune_model_archives(models_root: Path) -> int:
    """Remove old snapshots under _artifact_archive; never touches active/ or live parallel|cascade dirs."""
    from training_cache_policy import (
        MODEL_ARCHIVE_ENABLED,
        MODEL_ARCHIVE_SUBDIR,
        MODEL_ARCHIVE_MAX_SNAPSHOTS_PER_TICKER_ARCH,
        MODEL_ARCHIVE_MAX_AGE_DAYS,
    )

    if not MODEL_ARCHIVE_ENABLED:
        return 0
    root = models_root / MODEL_ARCHIVE_SUBDIR
    if not root.is_dir():
        return 0
    import shutil

    now = time.time()
    max_age = float(MODEL_ARCHIVE_MAX_AGE_DAYS) * 86400.0
    removed = 0
    for arch_dir in root.iterdir():
        if not arch_dir.is_dir():
            continue
        for tick_dir in arch_dir.iterdir():
            if not tick_dir.is_dir():
                continue
            snaps = [p for p in tick_dir.iterdir() if p.is_dir()]
            snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for i, p in enumerate(snaps):
                age_exceeded = (now - p.stat().st_mtime) > max_age if MODEL_ARCHIVE_MAX_AGE_DAYS > 0 else False
                over_cap = i >= MODEL_ARCHIVE_MAX_SNAPSHOTS_PER_TICKER_ARCH
                if over_cap or age_exceeded:
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        removed += 1
                    except Exception as e:
                        log.warning("Archive prune failed %s: %s", p, e)
    if removed:
        log.info("Model archive prune: removed %d snapshot(s)", removed)
    return removed


def cleanup_feature_cache_directories() -> int:
    """Delete oldest feature dirs by mtime, retaining FEATURE_CACHE_RETAIN_MAX_DIRS."""
    from training_cache_policy import (
        FEATURE_CACHE_RETAIN_MAX_DIRS,
        FEATURE_CACHE_MIN_AGE_SEC_BEFORE_DELETE,
    )

    if not FEATURE_CACHE_ROOT.is_dir():
        return 0
    subdirs = [p for p in FEATURE_CACHE_ROOT.iterdir() if p.is_dir()]
    if len(subdirs) <= FEATURE_CACHE_RETAIN_MAX_DIRS:
        return 0
    subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    victims = subdirs[FEATURE_CACHE_RETAIN_MAX_DIRS:]
    removed = 0
    now = time.time()
    for p in victims:
        try:
            if now - p.stat().st_mtime < FEATURE_CACHE_MIN_AGE_SEC_BEFORE_DELETE:
                continue
            import shutil

            shutil.rmtree(p, ignore_errors=True)
            removed += 1
        except Exception as e:
            log.warning("Feature cache cleanup failed %s: %s", p, e)
    if removed:
        log.info("Feature cache cleanup: removed %d dirs (retain=%d)", removed, FEATURE_CACHE_RETAIN_MAX_DIRS)
    return removed


def candidate_manifest_path(out_dir: Path) -> Path:
    return out_dir / MANIFEST_FILENAME


def load_run_manifest(out_dir: Path) -> Optional[dict]:
    p = candidate_manifest_path(out_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Manifest load failed %s: %s", p, e)
        return None


def save_run_manifest(out_dir: Path, manifest: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_manifest_path(out_dir).write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )


def sync_candidate_manifest_lineage_before_governed_eval(
    out_dir: Path,
    *,
    ticker: str,
    architecture: str,
    ml_horizon_suffix: str,
    scheduler_cache_key: str,
    feature_cache_key: str,
    data_fp: dict,
    training_code_fingerprint: str,
    evaluation: dict[str, Any] | None = None,
    trained_at: str | None = None,
) -> None:
    """
    Stamp scheduler_run_manifest.json with current run lineage before governed eval (G3-R3).

    Governed evaluation reads on-disk manifests; without this, a fresh train for horizon 5c
    can still see a stale ml_horizon_suffix=1c until the end-of-ticker manifest save.
    """
    from training_provenance import (
        FEATURE_SCHEMA_VERSION,
        LABEL_CONFIG_VERSION,
        SCHEDULER_PIPELINE_VERSION,
    )
    from training_cache_policy import MANIFEST_SCHEMA_VERSION as MSV
    from features.training_canonical_input import training_canonical_lineage_header

    existing = load_run_manifest(out_dir) or {}
    hz = str(ml_horizon_suffix or DEFAULT_ML_HORIZON_SLUG).strip().lower()

    def _ts_label(v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    patched: dict[str, Any] = dict(existing)
    patched.update(
        {
            "schema_version": existing.get("schema_version") or MSV,
            "ticker": ticker.upper(),
            "architecture": architecture,
            "ml_horizon_suffix": hz,
            "scheduler_cache_key": scheduler_cache_key,
            "feature_cache_key": feature_cache_key,
            "training_code_fingerprint": training_code_fingerprint,
            **training_canonical_lineage_header(),
            "data_fingerprint": data_fp,
            "data_start": _ts_label(data_fp.get("min_ts_utc")),
            "data_end": _ts_label(data_fp.get("max_ts_utc")),
            "row_count": _normalize_data_fp(data_fp).get("row_count"),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "label_config_version": LABEL_CONFIG_VERSION,
            "scheduler_pipeline_version": SCHEDULER_PIPELINE_VERSION,
        }
    )
    if evaluation is not None:
        patched["evaluation"] = evaluation
    if trained_at:
        patched["trained_at"] = trained_at
    save_run_manifest(out_dir, patched)


def compare_aggregate_manifest_path() -> Path:
    from training_cache_policy import COMPARE_MANIFEST_FILENAME

    return Path(__file__).resolve().parent / "models" / COMPARE_MANIFEST_FILENAME


def save_compare_aggregate_manifest(payload: dict) -> Path:
    p = compare_aggregate_manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def parallel_artifact_basenames(ticker: str, horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG) -> list[str]:
    t = ticker.upper()
    hz = (horizon_suffix or DEFAULT_ML_HORIZON_SLUG).strip().lower()
    return [
        f"xgb_{t}_{hz}.pkl",
        f"xgb_{t}_{hz}_meta.json",
        f"lstm_{t}_{hz}.pt",
        f"lstm_{t}_{hz}_meta.json",
        f"transformer_{t}_{hz}.pt",
        f"transformer_{t}_{hz}_meta.json",
        f"meta_{t}_{hz}.pkl",
    ]


def cascade_artifact_basenames(ticker: str, horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG) -> list[str]:
    return parallel_artifact_basenames(ticker, horizon_suffix=horizon_suffix)


def artifacts_present(
    out_dir: Path, ticker: str, architecture: str, horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG,
) -> bool:
    names = (
        parallel_artifact_basenames(ticker, horizon_suffix=horizon_suffix)
        if architecture == "parallel"
        else cascade_artifact_basenames(ticker, horizon_suffix=horizon_suffix)
    )
    return all((out_dir / n).exists() for n in names)


def manifest_matches_current(
    manifest: dict,
    scheduler_key: str,
    data_fp: dict,
    code_fp: str,
    ticker: str,
    *,
    ml_horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG,
) -> bool:
    if not manifest:
        return False
    if not _canonical_lineage_identity_ok(manifest):
        return False
    if manifest.get("scheduler_cache_key") != scheduler_key:
        return False
    if _normalize_data_fp(manifest.get("data_fingerprint")) != _normalize_data_fp(data_fp):
        return False
    mf_hz = str(manifest.get("ml_horizon_suffix") or DEFAULT_ML_HORIZON_SLUG).strip().lower()
    if mf_hz != str(ml_horizon_suffix or DEFAULT_ML_HORIZON_SLUG).strip().lower():
        return False
    from ml_horizon import outcome_column, normalize_ml_horizon_slug

    hz = normalize_ml_horizon_slug(ml_horizon_suffix)
    tc = outcome_column(hz)
    expected_fk = compute_feature_cache_key(
        ticker,
        data_fp,
        code_fp,
        target_column=tc,
    )
    if manifest.get("feature_cache_key") != expected_fk:
        return False
    return True


def build_manifest(
    *,
    ticker: str,
    architecture: str,
    scheduler_cache_key: str,
    feature_cache_key: str,
    data_fp: dict,
    trained_at: str,
    artifact_rel_paths: dict[str, str],
    artifact_sha256: dict[str, str],
    training_code_fingerprint: str,
    evaluation: dict[str, Any],
    promotion_decision: Optional[dict] = None,
    skipped_train: bool = False,
    skipped_eval: bool = False,
    used_feature_cache: bool = False,
    used_cascade_tensor_cache: bool = False,
    rolling_window_days_tabular: int = 0,
    rolling_window_days_sequence: int = 0,
    rolling_rth_sessions_tabular: int = 0,
    rolling_rth_sessions_sequence: int = 0,
    consecutive_scheduler_skips: int = 0,
    skip_reason: Optional[str] = None,
    retrain_reason: Optional[str] = None,
    cache_miss_reason: Optional[str] = None,
    warm_resume: Optional[dict[str, Any]] = None,
    ml_horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict:
    from training_provenance import (
        FEATURE_SCHEMA_VERSION,
        LABEL_CONFIG_VERSION,
        SCHEDULER_PIPELINE_VERSION,
    )
    from training_cache_policy import MANIFEST_SCHEMA_VERSION as MSV
    from features.training_canonical_input import training_canonical_lineage_header

    def _ts_label(v):
        if v is None:
            return ""
        return str(v)

    return {
        "schema_version": MSV,
        "ticker": ticker.upper(),
        "architecture": architecture,
        "ml_horizon_suffix": str(ml_horizon_suffix or DEFAULT_ML_HORIZON_SLUG).lower(),
        "scheduler_cache_key": scheduler_cache_key,
        "feature_cache_key": feature_cache_key,
        "training_code_fingerprint": training_code_fingerprint,
        **training_canonical_lineage_header(),
        "data_fingerprint": data_fp,
        "data_start": _ts_label(data_fp.get("min_ts_utc")),
        "data_end": _ts_label(data_fp.get("max_ts_utc")),
        "row_count": _normalize_data_fp(data_fp).get("row_count"),
        "feature_version": FEATURE_SCHEMA_VERSION,
        "label_version": LABEL_CONFIG_VERSION,
        "pipeline_version": SCHEDULER_PIPELINE_VERSION,
        "trained_at": trained_at,
        "artifact_paths": artifact_rel_paths,
        "artifact_sha256": artifact_sha256,
        "evaluation": evaluation,
        "promotion_decision": promotion_decision,
        "skipped_train": skipped_train,
        "skipped_eval": skipped_eval,
        "used_feature_cache": used_feature_cache,
        "used_cascade_tensor_cache": used_cascade_tensor_cache,
        "rolling_window_days_tabular": rolling_window_days_tabular,
        "rolling_window_days_sequence": rolling_window_days_sequence,
        "rolling_rth_sessions_tabular": rolling_rth_sessions_tabular,
        "rolling_rth_sessions_sequence": rolling_rth_sessions_sequence,
        "consecutive_scheduler_skips": int(consecutive_scheduler_skips),
        "skip_reason": skip_reason,
        "retrain_reason": retrain_reason,
        "cache_miss_reason": cache_miss_reason,
        "warm_resume": warm_resume or {},
    }


# Legacy helpers (unused by scheduler; kept for compatibility)
def cache_exists(
    ticker: str,
    timeframe: str,
    target: str,
    train_start: str,
    train_end: str,
) -> bool:
    from training_provenance import cache_key, FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION

    key = cache_key(ticker, timeframe, target, FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION, train_start[:10], train_end[:10])
    p = FEATURE_CACHE_ROOT.parent / key
    return (p / "meta.json").exists()


def read_cache_meta(cache_key_str: str) -> Optional[dict]:
    p = FEATURE_CACHE_ROOT.parent / cache_key_str / "meta.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None
