"""
training_cache_policy.py — Single source of truth for cache, resume, rolling windows, retention
================================================================================================
See CACHE_LAYERS, SCHEDULER_FAILURE_CONDITIONS, SCHEDULER_DECISION_TREE at bottom.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Manifest ─────────────────────────────────────────────────────────────────
MANIFEST_SCHEMA_VERSION: int = 2
MIN_MANIFEST_SCHEMA_FOR_FULL_SKIP: int = 2
# Full skip requires schema_version == MANIFEST_SCHEMA_VERSION exactly (strict).

# ── Code fingerprint (hashed file contents; invalidates cache keys) ─────────
CODE_FINGERPRINT_SOURCE_FILES: tuple[str, ...] = (
    "training_cache_policy.py",
    "training_cache.py",
    "training_provenance.py",
    "ml_scheduler.py",
    "ml_train.py",
    "lstm_model.py",
    "transformer_train.py",
    "lstm_data.py",
    "train_compare.py",
    "ml_data_common.py",
    "timeframe_config.py",
    "features/canonical_contract.py",
    "features/training_canonical_input.py",
    "arch_competition/stack_bundle_eval_v1.py",
)


def training_repo_root() -> Path:
    return Path(__file__).resolve().parent


def env_disable_torch_resume() -> bool:
    return os.environ.get("ED_DISABLE_TORCH_RESUME", "").strip().lower() in ("1", "true", "yes")


# ── Rolling RTH *sessions* (trading days in DB), not calendar days. 0 = full history. ──
# Env ED_TRAIN_ROLLING_RTH_SESSIONS_* preferred; ED_TRAIN_ROLLING_DAYS_* kept as fallback (same int semantics = sessions).
ROLLING_WINDOW_RTH_SESSIONS_TABULAR: int = int(
    os.environ.get(
        "ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR",
        os.environ.get("ED_TRAIN_ROLLING_DAYS_TABULAR", "0"),
    )
)
ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE: int = int(
    os.environ.get(
        "ED_TRAIN_ROLLING_RTH_SESSIONS_SEQUENCE",
        os.environ.get("ED_TRAIN_ROLLING_DAYS_SEQUENCE", "0"),
    )
)

# ── Staleness ───────────────────────────────────────────────────────────────
MANIFEST_SKIP_MAX_AGE_DAYS: int = int(os.environ.get("ED_MANIFEST_MAX_AGE_DAYS", "7"))
# Force full train+eval after this many consecutive scheduler runs ended in cache skip (0 = off).
MAX_CONSECUTIVE_SCHEDULER_SKIPS: int = int(os.environ.get("ED_MAX_CONSECUTIVE_SKIPS", "14"))

# ── XGBoost ─────────────────────────────────────────────────────────────────
# Default: full refit. Optional native continuation (see ml_train.train_ticker).
XGBOOST_INCREMENTAL_TRAIN_ALLOWED: bool = os.environ.get("ED_XGB_INCREMENTAL", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

# ── PyTorch resume / mid-epoch checkpoints ──────────────────────────────────
LSTM_CHECKPOINT_RESUME_ALLOWED: bool = True
TRANSFORMER_CHECKPOINT_RESUME_ALLOWED: bool = True
LSTM_RESUME_REQUIRES_SAME_DATA_FINGERPRINT: bool = True
TRANSFORMER_RESUME_REQUIRES_SAME_DATA_FINGERPRINT: bool = True
TORCH_CHECKPOINT_EVERY_N_EPOCHS: int = int(os.environ.get("ED_TORCH_CHECKPOINT_EVERY_N_EPOCHS", "5"))


# ── Training epochs (runtime lever; full history preserved) ──────────────────
# Per-anchor production-retrain runtime knob (2026-06-03). Sequence training dominates wall-clock
# and runs the full epoch count (best-val checkpointing already selects the best epoch, so fewer
# epochs trades a little convergence for large time savings WITHOUT cutting history, breaching the
# promotion floor, or touching the survivor-retrain env contract). Unset -> canonical defaults
# (no behavior change). Invalid/blank -> default. Floors at 1.
def _env_epochs(var: str, default: int) -> int:
    raw = os.environ.get(var, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


LSTM_TRAIN_EPOCHS: int = _env_epochs("ED_TRAIN_EPOCHS_LSTM", 50)
TRANSFORMER_TRAIN_EPOCHS: int = _env_epochs("ED_TRAIN_EPOCHS_TRANSFORMER", 60)

# ── Early stopping (the principled runtime lever — no guessed epoch count) ────
# EPOCHS above is the CEILING; training stops early once the held-out val loss stops improving for
# PATIENCE epochs, then best_state (best val epoch) is restored. Only fires when a real holdout
# exists (thin tickers select on train loss in-sample and must NOT early-stop on it). Default ON.
# Disable with ED_TRAIN_EARLY_STOP=0; widen/narrow with the patience vars; MIN_DELTA filters noise.
EARLY_STOP_ENABLED: bool = os.environ.get("ED_TRAIN_EARLY_STOP", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LSTM_EARLY_STOP_PATIENCE: int = _env_epochs("ED_TRAIN_EARLY_STOP_PATIENCE_LSTM", 8)
TRANSFORMER_EARLY_STOP_PATIENCE: int = _env_epochs("ED_TRAIN_EARLY_STOP_PATIENCE_TRANSFORMER", 8)
EARLY_STOP_MIN_DELTA: float = float(os.environ.get("ED_TRAIN_EARLY_STOP_MIN_DELTA", "0.0001"))


def should_early_stop(*, enabled: bool, has_holdout: bool, patience: int, epochs_no_improve: int) -> bool:
    """Decide whether sequence training should stop early.

    Fires ONLY on a real held-out val signal — never on in-sample train loss (thin tickers with no
    holdout select on train loss, which monotonically falls and must not trigger a stop). Requires
    early-stop enabled, a positive patience, and a no-improvement streak that reached patience.
    """
    return bool(enabled and has_holdout and patience > 0 and epochs_no_improve >= patience)

# ── Feature cache retention (models/cache/features/) ─────────────────────────
FEATURE_CACHE_RETAIN_MAX_DIRS: int = int(os.environ.get("ED_FEATURE_CACHE_MAX_DIRS", "96"))
FEATURE_CACHE_MIN_AGE_SEC_BEFORE_DELETE: int = int(os.environ.get("ED_FEATURE_CACHE_MIN_AGE_SEC", "3600"))

# ── Model artifact archive + prune (never delete live active/ candidate in-place without archive) ──
MODEL_ARCHIVE_ENABLED: bool = os.environ.get("ED_MODEL_ARCHIVE", "1").strip().lower() not in ("0", "false", "no")
MODEL_ARCHIVE_SUBDIR: str = "_artifact_archive"
MODEL_ARCHIVE_MAX_SNAPSHOTS_PER_TICKER_ARCH: int = int(os.environ.get("ED_MODEL_ARCHIVE_MAX_SNAPSHOTS", "8"))
MODEL_ARCHIVE_MAX_AGE_DAYS: int = int(os.environ.get("ED_MODEL_ARCHIVE_MAX_AGE_DAYS", "120"))





