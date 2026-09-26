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

# ── Compare runs ─────────────────────────────────────────────────────────────
COMPARE_MANIFEST_FILENAME: str = "compare_run_manifest.json"
COMPARE_USE_PRODUCTION_CACHE_KEYS: bool = True

# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER DECISION TREE (executable order in ml_scheduler.run_once)
# ══════════════════════════════════════════════════════════════════════════════
SCHEDULER_DECISION_TREE = """
1) if bypass_cache:
       -> full_rebuild (train+eval all; torch resume disabled via bypass)
2) if force_retrain (CLI flag):
       -> same as bypass for skip gating only (must train+eval); promotion logic unchanged
3) if consecutive_scheduler_skips >= MAX_CONSECUTIVE_SCHEDULER_SKIPS:
       -> force_train (retrain_reason=consecutive_skips_cap)
4) full_skip_eligible(manifest, ...) strict:
       a) schema_version == MANIFEST_SCHEMA_VERSION (exact)
       b) training_code_fingerprint == current
       c) scheduler_cache_key + data_fingerprint match
       d) trained_at age <= MANIFEST_SKIP_MAX_AGE_DAYS (if enabled)
       e) artifact_sha256 present, keys == exact required set, every file on disk matches hash
       f) all inference artifacts exist
       -> if all pass: full_skip_train_eval (reuse manifest eval metrics)
5) else:
       -> train+eval (retrain_reason / cache_miss_reason from full_skip_eligible failure)
6) Promotion: validate_for_promotion; copy winner to active (never pruned as "current")
"""

# ══════════════════════════════════════════════════════════════════════════════
# CACHE LAYERS (read order)
# ══════════════════════════════════════════════════════════════════════════════
CACHE_LAYERS = """
L1  scheduler_run_manifest.json (per models/{parallel|cascade}/{ticker}/)
    strict schema v2 + artifact_sha256 set equality + code_fp + scheduler key + data_fp
L2  models/cache/features/{feature_cache_key}/  (LSTM npz, parallel Transformer npz, identity)
L3  models/cache/features/{feature_cache_key}/cascade_tf_{w16}_{t16}/  (cascade XGB+LSTM tensor npz;
    w16 = sha256(xgb_meta|lstm.pt)[:16], t16 = sha256(tensor bytes)[:16] — path invalidates on weights or tensor)
L4  PyTorch resume blobs lstm_*_train_resume.pt, transformer_*_train_resume.pt (+ every-N-epoch writes)
L5  Optional XGBoost continuation when ED_XGB_INCREMENTAL=1 and append-only + schema checks pass
L6  models/_artifact_archive/{parallel|cascade}/{ticker}/{utc_ts}/  snapshots before each full train
"""

# ══════════════════════════════════════════════════════════════════════════════
# RETENTION BEHAVIOR
# ══════════════════════════════════════════════════════════════════════════════
RETENTION_BEHAVIOR = """
- features/: cleanup_feature_cache_directories() — retain newest ED_FEATURE_CACHE_MAX_DIRS by mtime
- _artifact_archive/: prune snapshots per (arch,ticker) — keep <= ED_MODEL_ARCHIVE_MAX_SNAPSHOTS, drop older than ED_MODEL_ARCHIVE_MAX_AGE_DAYS
- models/active/{ticker}/: NEVER deleted by retention (current production tree)
- models/parallel|/cascade/{ticker}/: live candidate dirs overwritten on train; pre-train copy goes to archive only
"""

# ══════════════════════════════════════════════════════════════════════════════
# FAILURE CONDITIONS (skip / cache miss)
# ══════════════════════════════════════════════════════════════════════════════
SCHEDULER_FAILURE_CONDITIONS = """
full_skip_eligible returns False when any of:
- bypass_cache or force_retrain
- manifest missing
- schema_version != MANIFEST_SCHEMA_VERSION
- training_code_fingerprint mismatch
- scheduler_cache_key or data_fingerprint mismatch
- trained_at older than MANIFEST_SKIP_MAX_AGE_DAYS
- artifact_sha256 missing, wrong key set, missing file, or hash mismatch
- required model files absent on disk
- consecutive_scheduler_skips cap (handled before full_skip_eligible in run_once)

Feature cache miss: identity json / npz mismatch or missing.

Cascade tensor cache miss: no cascade_tf_{w16}_*/ match, identity/tensor/hash/row mismatch, or legacy dir stale.

Torch resume rejected: policy off, env ED_DISABLE_TORCH_RESUME, blob schema mismatch, fingerprint/key/architecture/n_features/cascade tensor fp / xgb_probs fp mismatch.

XGB incremental rejected: ED_XGB_INCREMENTAL not set, or feature list / target / non-append-only fingerprint / missing prior model.
"""
