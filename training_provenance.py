"""
training_provenance.py — Training Provenance Schema & Promotion Gating
========================================================================
Persistent metadata for every trained artifact. Used by ml_scheduler,
ml_train, lstm_model, transformer_train for provenance and promotion decisions.

RULE: Do not promote unless provenance validates.

Promotion policy (all must pass):
  1. metadata present (training_timeframe, target_column, target_definition)
  2. training_timeframe == CANONICAL_TIMEFRAME (1m)
  3. target_column matches the scheduled ML horizon (e.g. outcome_1c, outcome_5c)
  4. target_definition contains the expected "{N} min" substring for that horizon
  5. rows_used >= MIN_ROWS_FOR_PROMOTION
  6. eval_accuracy >= MIN_PROMOTION_ACCURACY (above random 1/3)
  7. balanced_accuracy >= MIN_PROMOTION_BALANCED_ACC (when available)
  8. new score >= existing promotion_score (when active artifact exists)
  9. tie-break: prefer higher balanced_accuracy, then higher eval_accuracy
"""
from __future__ import annotations

import json
import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from timeframe_config import CANONICAL_TIMEFRAME

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    normalize_ml_horizon_slug,
    outcome_column,
    target_definition as horizon_target_definition,
    promotion_definition_substring,
)

log = logging.getLogger("training_provenance")

# ── Version constants (bump when features or preprocessing change) ─────────────
FEATURE_SCHEMA_VERSION: str = "v4_canonical_1m"
# v3: tabular load_data uses per-ticker 1m-preferred m5_* additive merge (ml_data_common); invalidates scheduler/cache keys.
PREPROCESSING_VERSION: str = "v3_rth_decay_m5_additive_canonical"
# Bump when label column, horizon definition, or outcome filter semantics change (invalidates training cache).
# Issue 15: 5c+ artifacts share this feature/label pipeline version; exact label column is in meta.target_column.
# Phase 1 (horizon-collapse fix): outcome_Nc now classified with a per-horizon ATR-scaled move
# threshold (classify_direction_pts + threshold_move_pts_for_slug) instead of a fixed 0.05%-of-spot
# cut, so each horizon is balanced on its own volatility scale. This is an outcome-filter semantics
# change → version bumped to force full retrain on the rebalanced labels (the DB column must also be
# refreshed via the force_refresh outcome backfill). horizon_outcome_schema_version (anchor/forward
# bar mechanics) is unchanged and stays "bar_forward_close_v1".
LABEL_CONFIG_VERSION: str = "outcome_perhorizon_volthr_v2"
# Bump when ml_scheduler / stacked training orchestration or artifact set changes (invalidates skip-retrain).
SCHEDULER_PIPELINE_VERSION: str = "scheduler_stack_v1"

# ── Expected values for patch / legacy defaults (live default product horizon) ─────────
EXPECTED_TARGET_COLUMN: str = outcome_column(DEFAULT_ML_HORIZON_SLUG)
EXPECTED_TARGET_DEFINITION: str = horizon_target_definition(DEFAULT_ML_HORIZON_SLUG)
MIN_PROMOTION_ACCURACY: float = 0.34       # above random (1/3)
MIN_PROMOTION_BALANCED_ACC: float = 0.33   # per-class recall avg; slightly below accuracy when balanced
MIN_ROWS_FOR_PROMOTION: int = 500         # minimum training rows for promotion
MIN_PROMOTION_EDGE_PP: float = -5.0       # allow small negative edge for now
# Per-ticker fail-closed DATA floor on the train→promote path (Workstream A1, operator brief
# 2026-05-29). Distinct from rows_used (model samples): this is raw labeled-row + usable-day
# availability in the DB. A "usable RTH day" has >= USABLE_RTH_DAY_MIN_ROWS labeled 1m rows —
# enough to fill the LSTM structure window (STREAM_5M_LOOKBACK=60). Below floor → ticker stays
# NON-COMPLIANT, no copy to models/active/, recorded (no silent skip).
MIN_USABLE_DAYS_FOR_PROMOTION: int = 5
USABLE_RTH_DAY_MIN_ROWS: int = 60


def meets_per_ticker_data_floor(labeled_rows: int, usable_days: int) -> tuple[bool, str]:
    """Fail-closed per-ticker data floor for promotion (A1).

    Requires >= MIN_ROWS_FOR_PROMOTION labeled rows AND >= MIN_USABLE_DAYS_FOR_PROMOTION
    usable RTH days (a usable day has >= USABLE_RTH_DAY_MIN_ROWS labeled 1m rows).
    Returns (ok, reason). Both conditions reported together when both fail.
    """
    reasons: list[str] = []
    if int(labeled_rows) < MIN_ROWS_FOR_PROMOTION:
        reasons.append(f"labeled_rows={int(labeled_rows)} < {MIN_ROWS_FOR_PROMOTION}")
    if int(usable_days) < MIN_USABLE_DAYS_FOR_PROMOTION:
        reasons.append(
            f"usable_days={int(usable_days)} < {MIN_USABLE_DAYS_FOR_PROMOTION} "
            f"(usable = >= {USABLE_RTH_DAY_MIN_ROWS} labeled 1m rows/day)"
        )
    if reasons:
        return False, "; ".join(reasons)
    return True, "ok"


@dataclass
class TrainingProvenance:
    """Full training provenance metadata for every trained artifact."""
    model_type: str
    ticker: str
    training_timeframe: str
    target_definition: str
    target_column: str
    feature_schema_version: str
    preprocessing_version: str
    sequence_length: Optional[int] = None  # LSTM/Transformer only
    train_start: str = ""
    train_end: str = ""
    validation_start: str = ""
    validation_end: str = ""
    rows_used: int = 0
    trained_at: str = ""
    promoted_at: str = ""
    source_cache_key: str = ""
    promotion_metric: str = ""
    promotion_score: float = 0.0
    balanced_accuracy: Optional[float] = None  # per-class recall avg when available

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TrainingProvenance":
        def _get(k: str, default):
            return d.get(k) if d.get(k) is not None else default

        return cls(
            model_type=_get("model_type", ""),
            ticker=_get("ticker", ""),
            training_timeframe=_get("training_timeframe", ""),
            target_definition=_get("target_definition", ""),
            target_column=_get("target_column", EXPECTED_TARGET_COLUMN),
            feature_schema_version=_get("feature_schema_version", ""),
            preprocessing_version=_get("preprocessing_version", ""),
            sequence_length=d.get("sequence_length"),
            train_start=_get("train_start", ""),
            train_end=_get("train_end", ""),
            validation_start=_get("validation_start", ""),
            validation_end=_get("validation_end", ""),
            rows_used=_get("rows_used", provenance_rows(d)),
            trained_at=_get("trained_at", ""),
            promoted_at=_get("promoted_at", ""),
            source_cache_key=_get("source_cache_key", ""),
            promotion_metric=_get("promotion_metric", ""),
            promotion_score=float(_get("promotion_score", d.get("train_accuracy", d.get("val_accuracy", 0))) or 0),
            balanced_accuracy=d.get("balanced_accuracy"),
        )


def cache_key(
    ticker: str,
    timeframe: str,
    target: str,
    feature_schema_version: str,
    preprocessing_version: str,
    train_start: str,
    train_end: str,
) -> str:
    """
    Generate strict cache identity for tensors/preprocessing outputs.
    Format: {ticker}_{timeframe}_{target}_{fsv}_{ppv}_{start}_{end}
    Hashed for filesystem-safe length.
    """
    raw = f"{ticker}|{timeframe}|{target}|{feature_schema_version}|{preprocessing_version}|{train_start}|{train_end}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def is_provenance_compliant(
    provenance: Optional[TrainingProvenance],
    horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> bool:
    """True if provenance matches the given ML horizon (default 1c for live stack)."""
    if not provenance:
        return False
    slug = normalize_ml_horizon_slug(horizon_slug)
    col = outcome_column(slug)
    sub = promotion_definition_substring(slug)
    return bool(
        provenance.training_timeframe
        and provenance.training_timeframe == CANONICAL_TIMEFRAME
        and provenance.target_column == col
        and provenance.target_definition
        and sub in provenance.target_definition
    )


def validate_for_promotion(
    provenance: TrainingProvenance,
    promotion_metric: float,
    existing_provenance: Optional[TrainingProvenance] = None,
    balanced_accuracy: Optional[float] = None,
    force_replace_non_compliant: bool = False,
    horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    single_class_collapse: bool = False,
) -> tuple[bool, str]:
    """
    Validate whether a trained artifact may be promoted.
    All criteria must pass. Returns (ok, reason).

    Promotion metrics:
      - promotion_metric: eval_accuracy (ensemble accuracy on full RTH)
      - balanced_accuracy: (recall_up + recall_down + recall_flat) / 3 when available
      - single_class_collapse: True when the candidate predicted exactly ONE class across the
        eval set (all-flat / majority collapse). Such a model's top-line accuracy is just the
        majority base rate (balanced_accuracy ~ 1/n_classes = chance) — it is blocked regardless
        of accuracy, because MIN_PROMOTION_BALANCED_ACC=0.33 does NOT catch a 3-class all-flat
        model whose balanced_accuracy is exactly 0.333.
    """
    if not provenance:
        return False, "missing provenance"

    if single_class_collapse:
        return False, (
            "single_class_collapse: candidate predicts one class on the eval set "
            "(all-flat majority collapse) — blocked regardless of top-line accuracy"
        )

    if not provenance.training_timeframe:
        return False, "missing training_timeframe in provenance"

    if provenance.training_timeframe != CANONICAL_TIMEFRAME:
        return False, f"training_timeframe={provenance.training_timeframe} != {CANONICAL_TIMEFRAME}"

    slug = normalize_ml_horizon_slug(horizon_slug)
    col = outcome_column(slug)
    sub = promotion_definition_substring(slug)
    if provenance.target_column != col:
        return False, f"target_column={provenance.target_column} != {col} (horizon {slug})"

    if provenance.target_definition and sub not in (provenance.target_definition or ""):
        return False, f"target_definition missing {sub!r} for horizon {slug}: {provenance.target_definition}"

    if provenance.rows_used < MIN_ROWS_FOR_PROMOTION:
        return False, f"rows_used={provenance.rows_used} < {MIN_ROWS_FOR_PROMOTION}"

    if promotion_metric < MIN_PROMOTION_ACCURACY:
        return False, f"eval_accuracy={promotion_metric:.4f} < {MIN_PROMOTION_ACCURACY}"

    if balanced_accuracy is not None and balanced_accuracy < MIN_PROMOTION_BALANCED_ACC:
        return False, f"balanced_accuracy={balanced_accuracy:.4f} < {MIN_PROMOTION_BALANCED_ACC}"

    if existing_provenance:
        existing_compliant = is_provenance_compliant(existing_provenance, horizon_slug=slug)
        if force_replace_non_compliant and not existing_compliant:
            pass  # allow promotion to replace non-compliant
        elif promotion_metric < existing_provenance.promotion_score:
            return False, f"new eval_accuracy {promotion_metric:.4f} < existing {existing_provenance.promotion_score:.4f}"
        elif promotion_metric == existing_provenance.promotion_score and balanced_accuracy is not None:
            existing_bal = getattr(existing_provenance, "balanced_accuracy", None)
            if existing_bal is not None and balanced_accuracy < existing_bal:
                return False, f"tie: new balanced_accuracy {balanced_accuracy:.4f} < existing {existing_bal:.4f}"

    return True, "ok"


def load_provenance(meta_path: Path) -> Optional[TrainingProvenance]:
    """Load provenance from a *_meta.json or checkpoint. Returns None if missing/invalid."""
    if not meta_path or not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        if "model_type" in data or "training_timeframe" in data or "ticker" in data:
            return TrainingProvenance.from_dict(data)
        return None
    except Exception as e:
        log.warning("load_provenance %s: %s", meta_path, e)
        return None


def provenance_rows(data: dict) -> int:
    """Infer rows_used from common meta keys."""
    return int(data.get("rows_used") or data.get("n_train") or data.get("samples") or 0)


def build_xgb_provenance(
    ticker: str,
    df,
    meta: dict,
    horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> TrainingProvenance:
    """Build provenance for XGB training."""
    slug = normalize_ml_horizon_slug(horizon_slug)
    col = outcome_column(slug)
    tdef = horizon_target_definition(slug)
    ts = df["ts_et"] if hasattr(df, "columns") and "ts_et" in df.columns else []
    train_start = str(ts.iloc[0])[:19] if len(ts) > 0 else ""
    train_end = str(ts.iloc[-1])[:19] if len(ts) > 0 else ""
    return TrainingProvenance(
        model_type="XGBClassifier",
        ticker=ticker,
        training_timeframe=CANONICAL_TIMEFRAME,
        target_definition=tdef,
        target_column=col,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        sequence_length=None,
        train_start=train_start,
        train_end=train_end,
        validation_start=train_start,
        validation_end=train_end,
        rows_used=len(df),
        trained_at=meta.get("trained_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        promoted_at="",
        source_cache_key=cache_key(ticker, CANONICAL_TIMEFRAME, col, FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION, train_start[:10] if train_start else "", train_end[:10] if train_end else ""),
        promotion_metric="accuracy",
        promotion_score=float(meta.get("train_accuracy", 0)),
        balanced_accuracy=meta.get("balanced_accuracy"),
    )


def build_lstm_provenance(
    ticker: str,
    dataset,
    meta: dict,
    sequence_length: int,
    horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> TrainingProvenance:
    """Build provenance for LSTM training."""
    slug = normalize_ml_horizon_slug(
        getattr(dataset, "ml_horizon_slug", None) or horizon_slug
    )
    col = getattr(dataset, "target_column", None) or outcome_column(slug)
    timestamps = getattr(dataset, "timestamps", []) or []
    train_start = str(timestamps[0])[:19] if timestamps else ""
    train_end = str(timestamps[-1])[:19] if timestamps else ""
    tf = getattr(dataset, "training_timeframe", None) or CANONICAL_TIMEFRAME
    target_def = getattr(dataset, "target_definition", None) or horizon_target_definition(slug)
    return TrainingProvenance(
        model_type="dual_stream_lstm",
        ticker=ticker,
        training_timeframe=tf,
        target_definition=target_def,
        target_column=col,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        sequence_length=sequence_length,
        train_start=train_start,
        train_end=train_end,
        validation_start=train_start,
        validation_end=train_end,
        rows_used=getattr(dataset, "n_samples", 0),
        trained_at=meta.get("trained_at", datetime.now().isoformat()),
        promoted_at="",
        source_cache_key=cache_key(ticker, tf, col, FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION, train_start[:10] if train_start else "", train_end[:10] if train_end else ""),
        promotion_metric="val_accuracy",
        promotion_score=float(meta.get("val_accuracy", 0)),
        balanced_accuracy=meta.get("balanced_accuracy"),
    )


def build_transformer_provenance(
    ticker: str,
    timestamps: list,
    meta: dict,
    sequence_length: int,
    n_samples: int,
    horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> TrainingProvenance:
    """Build provenance for Transformer training."""
    slug = normalize_ml_horizon_slug(horizon_slug)
    col = outcome_column(slug)
    tdef = horizon_target_definition(slug)
    train_start = str(timestamps[0])[:19] if timestamps else ""
    train_end = str(timestamps[-1])[:19] if timestamps else ""
    return TrainingProvenance(
        model_type="transformer_encoder",
        ticker=ticker,
        training_timeframe=CANONICAL_TIMEFRAME,
        target_definition=tdef,
        target_column=col,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        sequence_length=sequence_length,
        train_start=train_start,
        train_end=train_end,
        validation_start=train_start,
        validation_end=train_end,
        rows_used=n_samples,
        trained_at=meta.get("trained_at", datetime.now().isoformat()),
        promoted_at="",
        source_cache_key=cache_key(ticker, CANONICAL_TIMEFRAME, col, FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION, train_start[:10] if train_start else "", train_end[:10] if train_end else ""),
        promotion_metric="val_accuracy",
        promotion_score=float(meta.get("val_accuracy", 0)),
        balanced_accuracy=meta.get("balanced_accuracy"),
    )
