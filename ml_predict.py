"""
Ed Console - ML Prediction Module (unified seven-layer stack)
=============================================================
Loads and runs the unified stack ML layers (xgb, lstm, transformer) + meta combiner per ticker.

Architecture (one team — seven layers per governed_stack_contract.FULL_STACK_MODEL_LAYERS):
    Tabular + sequence ML layers (xgb, lstm, transformer) run in parallel for one tick.
    meta combines their triplets; monte_carlo, regime, and fusion follow in signals._run_model_stack.

Fallback chain (parallel, live inference):
    Full xgb + lstm + transformer triplets required as one team.
    meta-learner -> weighted average -> None (rules engine takes over).
    No 0.333 filler and no xgb-only parallel ensemble rows.

Pre-train observe experiment:
    ED_LIVE_ABLATION_EXPERIMENT=1 routes to models/parallel/{ticker}/ with relaxed bundle checks
    and survivor serve masks — cards can signal before scheduler promotion (ACTIVE_PROGRAM).

Fallback chain (5c documented exception):
    xgb_plus_transformer per ACTIVE_PROGRAM when horizon slug is 5c.

Fallback chain (cascade challenger):
    Cascade stage contract only; not mixed with partial parallel legs.

Integration:
    signals.py calls run_unified_stack_ml_once with inference_snapshot_v1= (InferenceSnapshotV1).
    Returns {up, down, flat} or None (rules engine takes over).
"""

import json
import pickle
import logging
import numpy as np
import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Optional, Any

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    PRIMARY_DECISION_HORIZONS,
    live_inference_horizon_slug,
    normalize_ml_horizon_slug,
)

from features.lstm_sequence_input import (
    LstmSequenceInputError,
    TransformerSequenceInputError,
    build_transformer_merged_window,
)
from features.xgb_model_input import XgbInferenceInputError
from features.parallel_stack_schema import (
    PARALLEL_STACK_SCHEMA_VERSION,
    build_unified_stack_layer_output,
)
from features.cascade_stack_contract import (
    CASCADE_UPSTREAM_BUNDLE_VERSION,
    CascadeChallengerError,
    CascadeStageError,
    assert_no_legacy_mvp_in_fusion_overlay,
    validate_cascade_inference_lineage,
)
from features.cascade_stack_schema import (
    CASCADE_STACK_SCHEMA_VERSION,
    build_cascade_challenger_run_metadata,
)

logger = logging.getLogger("ed_console.ml")


class ParallelRuntimeArtifactError(ValueError):
    """Loaded artifact expects cascade (upstream model) tensors; parallel runtime forbids that coupling."""

# "parallel" = production default; "cascade" = challenger challenger inference scope (models/cascade/{ticker}/).
_INFER_ARCHITECTURE: ContextVar[str] = ContextVar("ml_predict_infer_architecture", default="parallel")


def _reg_key(ticker: str) -> str:
    return f"{_INFER_ARCHITECTURE.get()}:{ticker.upper()}"


def _model_registry_key(ticker: str, hz: str | None = None) -> str:
    """
    In-memory cache key for base stack models (XGB / LSTM / Transformer / meta).

    Must include horizon slug so each governed horizon loads its own artifact
    (xgb_{TICKER}_{hz}.pkl, etc.) — not reused across horizons.
    """
    bt = _bundle_ticker_for_artifacts(ticker)
    su = normalize_ml_horizon_slug(hz) if hz is not None else get_ml_infer_horizon_slug()
    return f"{_reg_key(bt)}:{su}"


@contextmanager
def _cascade_challenger_inference_scope():
    tok = _INFER_ARCHITECTURE.set("cascade")
    try:
        yield
    finally:
        _INFER_ARCHITECTURE.reset(tok)


# Scheduler / eval sets this when loading non-1c artifacts from a candidate directory.
_ml_infer_horizon_cv: ContextVar[str] = ContextVar(
    "ml_infer_horizon_slug", default=DEFAULT_ML_HORIZON_SLUG
)

# Guest anchor: load promoted weights from anchor ticker while features stay on guest ticker.
_ml_bundle_ticker_cv: ContextVar[str | None] = ContextVar("ml_bundle_ticker_override", default=None)


@contextmanager
def ml_bundle_ticker_scope(bundle_ticker: str | None):
    """When set, artifact paths/registry keys resolve to ``bundle_ticker`` (anchor weights)."""
    if not bundle_ticker:
        yield
        return
    tok = _ml_bundle_ticker_cv.set(str(bundle_ticker).upper().strip())
    try:
        yield
    finally:
        _ml_bundle_ticker_cv.reset(tok)


def _bundle_ticker_for_artifacts(feature_ticker: str) -> str:
    override = _ml_bundle_ticker_cv.get()
    if override:
        return override
    return (feature_ticker or "").upper().strip()


def get_ml_infer_horizon_slug() -> str:
    return normalize_ml_horizon_slug(_ml_infer_horizon_cv.get())


# MODEL_SERVING_PROVENANCE_SURFACE_V1 — universal, read-only serving provenance.
# Reports which bundle a serve resolves to and why (guest routing, strict gate,
# relaxation, contract match, vintage) without touching loaders, registries,
# routing, or gates. Ticker is runtime data; the build path is identical for
# every ticker (no ticker-conditional behavior).
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — model-artifact metadata (bundle paths,
#   trained_at, schema/preprocessing versions, gate states); no market field
#   read, derivation, or emission changed.
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (observability only).
# All consumers checked: yes — model_serving_provenance_v1 is an additive
#   diagnostics surface (SignalOutput -> MarketState -> _ms_to_dict); trust,
#   freshness, actionability, sizing, and synthesis unchanged (locks in
#   tests/test_model_contract_enforcement.py provenance section).
# SCHWAB_CSV_CHECKED
def build_model_serving_provenance(requested_ticker: str) -> dict:
    """Read-only provenance for the bundle this serve resolves to. Never raises."""
    try:
        from arch_competition.stack_bundle_eval_v1 import (
            unified_stack_bundle_relaxation_active,
        )
        from active_bundle_contract import (
            active_bundle_dir,
            bundle_artifact_paths,
            check_active_bundle_complete,
        )
        from governed_stack_contract import active_guest_anchor_context
        from model_contract import meta_matches_system_contract

        rt = (requested_ticker or "").upper().strip()
        bt = _bundle_ticker_for_artifacts(rt)
        hz = get_ml_infer_horizon_slug()
        ctx = active_guest_anchor_context()
        strict_active_only = os.environ.get(
            "ED_XGB_STRICT_ACTIVE_ONLY", "1"
        ).strip().lower() not in ("0", "false", "no")
        relaxation_active = unified_stack_bundle_relaxation_active()

        bd = active_bundle_dir(bt, hz, models_dir=MODEL_DIR)
        comp = check_active_bundle_complete(bt, hz, bundle_dir=bd, models_dir=MODEL_DIR)
        missing = list(comp.get("issues", []))
        for art in (comp.get("artifacts") or {}).values():
            missing.extend(art.get("issues", []))

        trained_at = feature_schema_version = preprocessing_version = None
        contract_match = None
        contract_mismatch_reason = None
        for kind, _model_path, meta_path in bundle_artifact_paths(bt, hz, bd):
            if kind != "xgb" or not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as ex:
                contract_mismatch_reason = f"meta unreadable: {type(ex).__name__}"
                break
            trained_at = meta.get("trained_at") or None
            feature_schema_version = meta.get("feature_schema_version") or None
            preprocessing_version = meta.get("preprocessing_version") or None
            ok, reason = meta_matches_system_contract(meta)
            contract_match = bool(ok)
            contract_mismatch_reason = reason or None
            break

        # Probe the REAL resolver for its fail-closed verdict (read-only call).
        model_load_status = "dir_resolved"
        fail_closed_reason = None
        try:
            _model_dir_for_ticker(rt)
        except Exception as ex:
            model_load_status = "fail_closed"
            fail_closed_reason = f"{type(ex).__name__}: {str(ex)[:300]}"

        if relaxation_active:
            runtime_class = "RELAXATION_ACTIVE"
        elif not strict_active_only:
            runtime_class = "RELAXED_RESOLUTION"
        elif comp.get("compliant") and contract_match:
            runtime_class = "STRICT_ACTIVE_SERVABLE"
        else:
            runtime_class = "STRICT_ACTIVE_FAIL_CLOSED"

        # ML-PIPE Item 4 — artifact integrity identity of every governed load
        # already performed for this bundle (empty until first load).
        integrity_prov = get_artifact_verification_provenance(bt, hz)
        if not integrity_prov:
            artifact_integrity = "NOT_LOADED"
        elif any(
            p.get("integrity_class") == "VERIFICATION_FAILED_CLOSED"
            for p in integrity_prov.values()
        ):
            artifact_integrity = "VERIFICATION_FAILED_CLOSED"
        elif any(p.get("legacy") for p in integrity_prov.values()):
            artifact_integrity = "LEGACY_UNVERIFIED_NO_BUNDLE_MANIFEST"
        else:
            artifact_integrity = "VERIFIED_AGAINST_BUNDLE_MANIFEST"

        return {
            "requested_ticker": rt,
            "bundle_ticker": bt,
            "guest_anchor": ctx is not None or bt != rt,
            "guest_anchor_ticker": (
                ctx.anchor_ticker if ctx is not None else (bt if bt != rt else None)
            ),
            "horizon": hz,
            "bundle_dir": str(bd),
            "bundle_complete": bool(comp.get("compliant")),
            "missing_artifacts": missing[:12],
            "trained_at": trained_at,
            "feature_schema_version": feature_schema_version,
            "preprocessing_version": preprocessing_version,
            "contract_match": contract_match,
            "contract_mismatch_reason": contract_mismatch_reason,
            "strict_active_only": strict_active_only,
            "relaxation_active": relaxation_active,
            "runtime_class": runtime_class,
            "model_load_status": model_load_status,
            "fail_closed_reason": fail_closed_reason,
            "artifact_integrity": artifact_integrity,
            "artifact_verification": {
                role: {
                    k: p.get(k)
                    for k in (
                        "verified", "legacy", "integrity_class", "reason_code",
                        "manifest_sha256", "artifact_sha256", "artifact_filename",
                        "verified_at_utc",
                    )
                }
                for role, p in sorted(integrity_prov.items())
            },
        }
    except Exception as ex:
        # Provenance must never disturb the serve path.
        return {
            "requested_ticker": (requested_ticker or "").upper().strip(),
            "provenance_error": f"{type(ex).__name__}: {str(ex)[:200]}",
            "runtime_class": "PROVENANCE_ERROR",
        }


def set_ml_infer_horizon_slug(slug: str) -> Token:
    return _ml_infer_horizon_cv.set(normalize_ml_horizon_slug(slug))


def reset_ml_infer_horizon_slug(token: Token) -> None:
    _ml_infer_horizon_cv.reset(token)


def stack_probs_bundle_key() -> str:
    """Dict key for stacked ML probabilities in run_unified_stack_ml_once / signals.ml_bundle (Issue 15)."""
    return f"stack_probs_{get_ml_infer_horizon_slug()}"


# Cascade training appends these extras (must match lstm_model / transformer_train).
_CASCADE_LSTM_CONF_EXTRA = 3
_CASCADE_TRANSFORMER_SEQ_EXTRA = 6


def _snap_dict(row: Any) -> Optional[dict]:
    """Normalize DB row to dict without ablation (O-56: masks are per-model in each predictor)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return None


def _apply_serve_ablation_snapshot(snap: dict, model_family: str) -> dict:
    """Per (model_family, horizon) survivor nulls — must match training/eval assembly (O-56)."""
    out = dict(snap)
    try:
        from arch_competition.stack_bundle_eval_v1 import (
            ablation_experiment_serve_masks_active,
            apply_ablation_survivor_nulls_to_snapshot_for_model,
        )

        if ablation_experiment_serve_masks_active():
            hz = get_ml_infer_horizon_slug()
            apply_ablation_survivor_nulls_to_snapshot_for_model(
                out, model_family=model_family, horizon_slug=hz
            )
    except Exception:
        logger.error(
            "ablation survivor serve-mask failed for %s/%s — refusing unmasked serve (train/serve skew)",
            model_family,
            get_ml_infer_horizon_slug(),
            exc_info=True,
        )
        raise
    return out


def _mask_sequence_bars_for_model(bars: list, model_family: str) -> list:
    return [_apply_serve_ablation_snapshot(dict(b), model_family) for b in bars]


def _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1: dict | None) -> float:
    """Causal upper bound for LSTM/Transformer rolling DB history (rows must have ts_utc < as_of)."""
    if not inference_snapshot_v1:
        raise LstmSequenceInputError(
            "LSTM/Transformer sequence inference requires inference_snapshot_v1 with as_of_ts "
            "for causal DB history (EdDB.get_recent_snapshots(..., as_of_ts_utc=...))."
        )
    ts = inference_snapshot_v1.get("as_of_ts")
    if ts is None:
        raise LstmSequenceInputError(
            "InferenceSnapshotV1.as_of_ts is required for LSTM/Transformer DB history "
            "(strict causal cutoff: only snapshots with ts_utc < as_of_ts are used from the DB; "
            "the current bar MVP is merged from inference_snapshot_v1)."
        )
    return float(ts)


def _probs_dict_to_arr(p: Optional[dict]) -> np.ndarray:
    u = 1.0 / 3.0
    if not p:
        return np.array([u, u, u], dtype=np.float32)
    return np.array(
        [float(p.get("up", u)), float(p.get("down", u)), float(p.get("flat", u))],
        dtype=np.float32,
    )


def _transformer_normalize_and_select(X_raw: np.ndarray, checkpoint: dict) -> np.ndarray:
    """
    Match transformer_train.train_transformer: per-column normalize using raw means/stds,
    then keep columns where feature_mask is True (same order as training).
    """
    fm = np.asarray(checkpoint.get("feature_mask", np.ones(X_raw.shape[2], dtype=bool)), dtype=bool)
    if X_raw.shape[2] != fm.shape[0]:
        raise ValueError(f"raw width {X_raw.shape[2]} != feature_mask len {fm.shape[0]}")
    mean_m = np.asarray(checkpoint["norm_mean"], dtype=np.float32)
    std_m = np.asarray(checkpoint["norm_std"], dtype=np.float32)
    std_m = np.where(std_m < 1e-8, 1.0, std_m)
    kept = np.flatnonzero(fm)
    # Train-time bug once saved full-width mean/std with per-position mask; repair at inference.
    if mean_m.size == fm.shape[0] and std_m.size == fm.shape[0]:
        mean_m = mean_m[kept]
        std_m = std_m[kept]
    if mean_m.size != kept.size or std_m.size != kept.size:
        raise ValueError(
            f"norm_mean/std ({mean_m.size}) != kept columns ({kept.size})"
        )
    parts = []
    for k, j in enumerate(kept):
        col = X_raw[:, :, j].astype(np.float32)
        parts.append((col - mean_m[k]) / std_m[k])
    return np.nan_to_num(np.stack(parts, axis=2), nan=0.0, posinf=0.0, neginf=0.0)


def _transformer_apply_ablation_channel_zero(X: np.ndarray, checkpoint: dict) -> np.ndarray:
    """Post-normalize channel zero — must match transformer_train.train_transformer (O-56)."""
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

        if not ablation_survivors_training_enabled():
            return X
        fm = np.asarray(checkpoint.get("feature_mask", np.ones(X.shape[2], dtype=bool)), dtype=bool)
        dummy_1m = np.zeros((X.shape[0], X.shape[1], 0), dtype=X.dtype)
        X, _ = zero_ablated_sequence_channels_for_model(
            X,
            dummy_1m,
            fm,
            np.array([], dtype=bool),
            model_family="transformer",
            horizon_slug=get_ml_infer_horizon_slug(),
            features_5m=FEATURES_5M,
            features_1m=FEATURES_1M,
            encoded_features_5m=ENCODED_FEATURES_5M,
            encoded_features_1m=ENCODED_FEATURES_1M,
        )
        return X
    except Exception:
        logger.error(
            "Transformer post-norm ablation channel zero failed — refusing train/serve skew",
            exc_info=True,
        )
        raise

MODEL_DIR = Path("models")
ARCH_STATE_PATH = MODEL_DIR / "arch_state.json"

# Per-(ticker, horizon) model registry — loaded on first call per slug
_xgb_registry   = {}   # _model_registry_key -> {model, meta, feature_names, category_maps, vol_medians}
_xgb_movehead_registry: dict[str, dict | None] = {}  # movement-target v1 binary XGB heads
_meta_registry  = {}   # _model_registry_key -> sklearn LogisticRegression
_lstm_registry  = {}   # _model_registry_key -> (model, checkpoint)
_trans_registry = {}   # _model_registry_key -> (model, checkpoint)
_collapse_flag_registry: dict[str, set] = {}  # _model_registry_key -> {collapsed base names}
# Strict-active bundle resolution — cache blocked/ok per (ticker, hz); warn once per key.
_active_bundle_dir_cache: dict[str, Path | None] = {}
_strict_bundle_warned: set[str] = set()
# ML-PIPE Item 4 — verification provenance per f"{registry_key}|{artifact_role}".
# Records the exact manifest + artifact identity every governed load was verified
# against (or the fail-closed reason), and the stat identity used by the
# staleness guard so a cached model cannot outlive artifact/manifest mutation.
_artifact_verification_registry: dict[str, dict] = {}


def _record_artifact_verification(rk: str, role: str, prov: dict) -> None:
    _artifact_verification_registry[f"{rk}|{role}"] = prov


def _verify_governed_artifact(base: Path, bt: str, hz: str, role: str, filename: str) -> dict | None:
    """
    Canonical pre-deserialization integrity boundary for serve-path model loads.

    Verifies artifact bytes against the bundle integrity manifest BEFORE any
    pickle/torch deserialization. Absent manifest -> explicit legacy provenance
    (pre-Item-4 bundles; production authorization stays the MODEL-04 strict serve
    gate upstream) unless ED_ARTIFACT_INTEGRITY_STRICT=1. Every governed failure
    fails closed and is recorded with a stable reason code. Returns provenance on
    success, None when the load must be refused.
    """
    from active_bundle_contract import (
        ArtifactVerificationError,
        classify_legacy_absent_manifest,
        load_bundle_integrity_manifest,
        verify_artifact_against_manifest,
    )

    rk = _model_registry_key(bt, hz)
    try:
        manifest = load_bundle_integrity_manifest(base)
        if manifest is None:
            prov = classify_legacy_absent_manifest(base, bt, hz, role, filename)
        else:
            prov = verify_artifact_against_manifest(base, bt, hz, role, filename, manifest=manifest)
    except ArtifactVerificationError as exc:
        logger.error(
            "Artifact integrity fail-closed for %s %s hz=%s (%s): %s",
            role, bt, hz, filename, exc,
        )
        # Record stat identity of the failing artifact + manifest so the
        # staleness guard re-verifies (never silently flips positive) once
        # either file changes on disk — no process restart required.
        from active_bundle_contract import bundle_integrity_manifest_path

        art_sig = _stat_signature(str(base / filename))
        man_path = str(bundle_integrity_manifest_path(base))
        man_sig = _stat_signature(man_path)
        _record_artifact_verification(rk, role, {
            "verified": False,
            "legacy": False,
            "integrity_class": "VERIFICATION_FAILED_CLOSED",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
            "inference_blocked": True,
            "fallback_attempted": False,
            "artifact_path": str(base / filename),
            "artifact_bytes": art_sig[0] if art_sig else None,
            "artifact_mtime_ns": art_sig[1] if art_sig else None,
            "manifest_path": man_path,
            "manifest_bytes": man_sig[0] if man_sig else None,
            "manifest_mtime_ns": man_sig[1] if man_sig else None,
            **exc.identity,
        })
        return None
    _record_artifact_verification(rk, role, prov)
    if prov.get("legacy"):
        logger.warning(
            "LEGACY_UNVERIFIED artifact load (no bundle integrity manifest) for %s %s hz=%s (%s)",
            role, bt, hz, filename,
        )
    return prov


def _stat_signature(path_str: str | None) -> tuple[int, int] | None:
    """(size, mtime_ns) of a path, or None when absent/unreadable."""
    if not path_str:
        return None
    try:
        st = os.stat(path_str)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _stat_changed(path_str: str | None, size: int | None, mtime_ns: int | None) -> bool:
    recorded = None if size is None and mtime_ns is None else (size, mtime_ns)
    return _stat_signature(path_str) != recorded


def _artifact_registry_entry_stale(rk: str) -> bool:
    """
    Staleness guard for cached model registry entries (ML-PIPE Item 4).

    A cached in-memory model (verified, legacy-classified, or fail-closed
    negative) is evicted when its artifact bytes, its integrity manifest, or
    the bundle directory identity changed on disk (stat: size + mtime_ns), or
    when a legacy bundle gained a manifest. Eviction triggers a full re-verify;
    a negative entry never flips positive without recomputing the hash. Honest
    limit: a mutation preserving both size and mtime_ns is not detected without
    a full rehash.
    """
    prefix = f"{rk}|"
    provs = [p for k, p in _artifact_verification_registry.items() if k.startswith(prefix)]
    if not provs:
        return False
    stale = False
    for prov in provs:
        if _stat_changed(prov.get("artifact_path"), prov.get("artifact_bytes"), prov.get("artifact_mtime_ns")):
            stale = True
            break
        manifest_path = prov.get("manifest_path")
        if prov.get("legacy"):
            if manifest_path and Path(manifest_path).is_file():
                stale = True  # legacy bundle gained an integrity manifest — re-verify
                break
        elif _stat_changed(manifest_path, prov.get("manifest_bytes"), prov.get("manifest_mtime_ns")):
            stale = True
            break
    if stale:
        logger.info("ml_predict: artifact identity changed on disk — evicting registry for %s", rk)
        invalidate_model_registry_key(rk)
    return stale


def invalidate_model_registry_key(rk: str) -> None:
    """Evict every registry + provenance entry for one registry key (bundle identity)."""
    for reg in (_xgb_registry, _meta_registry, _lstm_registry, _trans_registry, _collapse_flag_registry):
        reg.pop(rk, None)
    movehead_prefix = f"{rk}:"
    for key in list(_xgb_movehead_registry):
        if key == rk or key.startswith(movehead_prefix):
            del _xgb_movehead_registry[key]
    prov_prefix = f"{rk}|"
    for key in list(_artifact_verification_registry):
        if key.startswith(prov_prefix):
            del _artifact_verification_registry[key]
    _active_bundle_dir_cache.pop(rk, None)
    _strict_bundle_warned.discard(rk)


def get_artifact_verification_provenance(ticker: str, hz: str | None = None) -> dict[str, dict]:
    """{artifact_role: verification provenance} recorded for (ticker, horizon) loads."""
    rk = _model_registry_key(ticker, hz)
    prefix = f"{rk}|"
    return {
        k[len(prefix):]: dict(p)
        for k, p in _artifact_verification_registry.items()
        if k.startswith(prefix)
    }

CLASS_NAMES = ["up", "down", "flat"]
# Visible uniform when no base is trustworthy (all single-class-collapsed). Distinct from a
# confident-flat triplet so downstream balanced_accuracy reads it as chance, not a real call.
_UNIFORM_PROBS = {"up": 0.3333, "down": 0.3333, "flat": 0.3334}


def _require_direction_probability_triplet(
    p: Optional[dict],
) -> Optional[tuple[float, float, float]]:
    """All three class probabilities must be present; no silent 0.33 fabrication."""
    if not isinstance(p, dict):
        return None
    up, down, flat = p.get("up"), p.get("down"), p.get("flat")
    if up is None or down is None or flat is None:
        return None
    try:
        return float(up), float(down), float(flat)
    except (TypeError, ValueError):
        return None


def _model_probs_to_fusion_out(p: Optional[dict], hint: str) -> Optional[dict]:
    tri = _require_direction_probability_triplet(p)
    if tri is None:
        return None
    up, down, flat = tri
    by_class = {"up": up, "down": down, "flat": flat}
    dominant = max(CLASS_NAMES, key=lambda c: by_class[c])
    edge = by_class[dominant] - (1.0 / 3.0)
    conf_label = "high" if edge >= 0.15 else "medium" if edge >= 0.08 else "low"
    if hint == "long":
        cont_support, rev_support = up, down
    elif hint == "short":
        cont_support, rev_support = down, up
    else:
        cont_support, rev_support = flat, max(up, down)
    return {
        "available": True,
        "prob_up": up,
        "prob_down": down,
        "prob_flat": flat,
        "dominant_class": dominant,
        "confidence_label": conf_label,
        "continuation_support": cont_support,
        "reversal_support": rev_support,
    }


def _model_probs_to_ui_output(p: Optional[dict], approved: bool) -> dict:
    unavailable = {
        "available": False,
        "dominant": None,
        "confidence": None,
        "approved": False,
    }
    if p is None:
        return unavailable
    tri = _require_direction_probability_triplet(p)
    if tri is None:
        return unavailable
    up, down, flat = tri
    by_class = {"up": up, "down": down, "flat": flat}
    dominant = max(CLASS_NAMES, key=lambda c: by_class[c])
    confidence = round(by_class[dominant] - (1.0 / 3.0), 4)
    return {
        "available": True,
        "dominant": dominant,
        "confidence": confidence,
        "approved": approved,
        "up": round(up, 4),
        "down": round(down, 4),
        "flat": round(flat, 4),
    }


def _model_dir_for_ticker(ticker: str) -> Path:
    """Resolve bundle dir: strict active, live ablation experiment (parallel), or offline scoring pass."""
    bt = _bundle_ticker_for_artifacts(ticker)
    hz = get_ml_infer_horizon_slug()
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_scoring_pass_active,
        live_ablation_experiment_active,
        resolve_experiment_bundle_dir,
    )

    if live_ablation_experiment_active():
        return resolve_experiment_bundle_dir(bt, hz, models_dir=MODEL_DIR)
    if ablation_scoring_pass_active():
        from active_bundle_contract import active_bundle_dir

        return active_bundle_dir(bt, hz, models_dir=MODEL_DIR)
    strict_active_only = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    if strict_active_only:
        from active_bundle_contract import active_bundle_dir, check_active_bundle_complete

        canonical = active_bundle_dir(bt, hz, models_dir=MODEL_DIR)
        if not check_active_bundle_complete(bt, hz, bundle_dir=canonical, models_dir=MODEL_DIR)[
            "compliant"
        ]:
            raise FileNotFoundError(
                f"ED_XGB_STRICT_ACTIVE_ONLY=1: no complete active model bundle for {bt} hz={hz} "
                f"at canonical {canonical} (requires xgb+lstm+transformer+meta_stack per active_bundle_contract)"
            )
        # MODEL-04 serve policy (operator-approved 2026-07-10): a complete
        # bundle must ALSO be serve-eligible by manifest vintage. Withheld or
        # unproven provenance fails closed with the explicit policy reason —
        # never a silent substitute (anchor routing resolves upstream via
        # _bundle_ticker_for_artifacts and is unchanged by this gate).
        from model_serve_policy import bundle_serve_eligibility

        _elig = bundle_serve_eligibility(bt, hz, canonical)
        if _elig["direct_serve_blocked"]:
            raise FileNotFoundError(
                f"MODEL_SERVE_POLICY {_elig['status']} for {bt} hz={hz} at {canonical}: "
                f"{_elig['reason']}"
            )
        return canonical
    return _model_dir_for_ticker_relaxed(bt, hz)


def _model_dir_for_ticker_relaxed(ticker: str, hz: str) -> Path:
    """Non-strict resolution: cascade challenger, arch_state, or parallel default."""
    if _INFER_ARCHITECTURE.get() == "cascade":
        cd = MODEL_DIR / "cascade" / ticker
        if not cd.is_dir():
            raise CascadeChallengerError(f"cascade challenger directory missing: {cd}")
        if not (cd / f"xgb_{ticker}_{hz}.pkl").exists():
            raise CascadeChallengerError(
                f"cascade challenger XGB artifact missing under {cd} (same horizon {hz} as parallel)"
            )
        return cd
    # Movement-only bundles: prefer models/active/{ticker}/ when dir/move heads exist for this horizon.
    active_early = MODEL_DIR / "active" / ticker
    if active_early.exists():
        if (active_early / f"xgb_{ticker}_{hz}_dir.pkl").exists() or (
            active_early / f"xgb_{ticker}_{hz}_move.pkl"
        ).exists():
            return active_early
    if ARCH_STATE_PATH.exists():
        try:
            data = json.loads(ARCH_STATE_PATH.read_text())
            if ticker in data:
                active = MODEL_DIR / "active" / ticker
                # Use active if any of xgb/lstm/transformer binary exists
                if active.exists():
                    has_any = (
                        (active / f"xgb_{ticker}_{hz}.pkl").exists()
                        or (active / f"xgb_{ticker}_{hz}_dir.pkl").exists()
                        or (active / f"xgb_{ticker}_{hz}_move.pkl").exists()
                        or (active / f"lstm_{ticker}_{hz}.pt").exists()
                        or (active / f"transformer_{ticker}_{hz}.pt").exists()
                    )
                    if has_any:
                        return active
        except Exception as e:
            logger.debug("active model dir probe: %s", e, exc_info=True)
    # Default to parallel: models/parallel/{ticker}/
    parallel = MODEL_DIR / "parallel" / ticker
    if parallel.exists():
        has_any = (
            (parallel / f"xgb_{ticker}_{hz}.pkl").exists()
            or (parallel / f"xgb_{ticker}_{hz}_dir.pkl").exists()
            or (parallel / f"xgb_{ticker}_{hz}_move.pkl").exists()
            or (parallel / f"lstm_{ticker}_{hz}.pt").exists()
            or (parallel / f"transformer_{ticker}_{hz}.pt").exists()
        )
        if has_any:
            return parallel
    # Fallback: flat models/ (train_all output) or per-ticker subdir for flat layout
    flat_pt = MODEL_DIR / f"lstm_{ticker}_{hz}.pt"
    flat_pkl = MODEL_DIR / f"xgb_{ticker}_{hz}.pkl"
    if flat_pt.exists() or flat_pkl.exists():
        return MODEL_DIR
    return MODEL_DIR


def _strict_bundle_block_detail(ticker: str, hz: str) -> str:
    """One-line compliance issues for operator-first strict-bundle warning."""
    from active_bundle_contract import check_active_bundle_complete

    bt = _bundle_ticker_for_artifacts(ticker)
    chk = check_active_bundle_complete(bt, hz, models_dir=MODEL_DIR)
    issues: list[str] = []
    for kind, art in (chk.get("artifacts") or {}).items():
        for msg in art.get("issues") or []:
            issues.append(f"{kind}: {msg}")
    if issues:
        return "; ".join(issues)
    for msg in chk.get("issues") or []:
        issues.append(str(msg))
    return "; ".join(issues) if issues else "bundle incomplete"


def _active_bundle_dir_for_load(ticker: str) -> Path | None:
    """Resolve bundle dir for serve-path model load; None when strict contract blocks."""
    rk = _model_registry_key(ticker)
    if rk in _active_bundle_dir_cache:
        return _active_bundle_dir_cache[rk]

    hz = get_ml_infer_horizon_slug()
    try:
        base = _model_dir_for_ticker(ticker)
    except FileNotFoundError as exc:
        _active_bundle_dir_cache[rk] = None
        if rk not in _strict_bundle_warned:
            _strict_bundle_warned.add(rk)
            logger.warning(
                "Active bundle blocked for %s hz=%s (%s)",
                ticker,
                hz,
                _strict_bundle_block_detail(ticker, hz),
            )
        else:
            logger.debug("Active bundle still blocked for %s hz=%s: %s", ticker, hz, exc)
        return None

    _active_bundle_dir_cache[rk] = base
    return base


# ══════════════════════════════════════════════════════════════════════════════
# XGBoost - per-ticker
# ══════════════════════════════════════════════════════════════════════════════


def build_xgb_pre_engineering_snapshot_for_tick(
    inference_snapshot_v1: dict,
    fusion_feature_overlay: dict | None,
) -> dict:
    """
    Engineering snapshot after MVP map + fusion overlay + net_gamma_prev for ΔGEX.

    Identical for every governed horizon on a single tick; call once and pass into
    ``run_unified_stack_ml_once(..., xgb_pre_engineering_snapshot=...)`` so XGB tri-class
    and movement heads skip repeated ingest/merge work (per-horizon work remains:
    ``engineer_single_snapshot`` + ``predict_proba`` per artifact).
    """
    from features.xgb_model_input import (
        assert_not_raw_l1_payload,
        inference_snapshot_v1_to_engineering_snapshot,
        merge_xgb_fusion_overlay,
    )
    from ml_data_common import attach_confluence_features_for_serve, attach_net_gamma_prev_for_dgex
    from ml_train import DB_PATH as _ML_DB

    assert_not_raw_l1_payload(inference_snapshot_v1)
    if fusion_feature_overlay is not None:
        assert_not_raw_l1_payload(fusion_feature_overlay)
    base = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
    snap = merge_xgb_fusion_overlay(base, fusion_feature_overlay)
    snap = attach_net_gamma_prev_for_dgex(snap, _ML_DB)
    snap = attach_confluence_features_for_serve(snap, _ML_DB)
    return _apply_serve_ablation_snapshot(snap, "xgb")


def _load_xgb(ticker: str) -> bool:
    bt = _bundle_ticker_for_artifacts(ticker)
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(bt, hz)
    if rk in _xgb_registry and not _artifact_registry_entry_stale(rk):
        return _xgb_registry[rk] is not None

    base = _active_bundle_dir_for_load(bt)
    if base is None:
        _xgb_registry[rk] = None
        return False
    mp  = base / f"xgb_{bt}_{hz}.pkl"
    mtp = base / f"xgb_{bt}_{hz}_meta.json"

    if not mp.exists():
        logger.debug("XGBoost model not found for %s (bundle=%s)", ticker, bt)
        _xgb_registry[rk] = None
        return False

    # Item 4: verify artifact bytes against the bundle integrity manifest
    # BEFORE pickle deserialization (fail closed on any governed failure).
    if (
        _verify_governed_artifact(base, bt, hz, "xgb", mp.name) is None
        or _verify_governed_artifact(base, bt, hz, "xgb_meta", mtp.name) is None
    ):
        _xgb_registry[rk] = None
        return False

    try:
        with open(mp, "rb") as f:
            model = pickle.load(f)
        with open(mtp, "r") as f:
            meta = json.load(f)

        from arch_competition.stack_bundle_eval_v1 import unified_stack_bundle_relaxation_active

        if unified_stack_bundle_relaxation_active():
            from arch_competition.ablation_bundle_inference import validate_ablation_scoring_bundle_meta

            ok, reason = validate_ablation_scoring_bundle_meta(meta, "xgb")
        else:
            from model_contract import validate_artifact_contract

            ok, reason = validate_artifact_contract(meta, "xgb")
        if not ok:
            logger.error(
                "XGBoost %s: incompatible model contract (%s). Retrain; refusing load.",
                ticker,
                reason,
            )
            _xgb_registry[rk] = None
            return False

        _xgb_registry[rk] = dict(
            model=model, meta=meta,
            feature_names=meta["features"],
            category_maps=meta.get("category_maps", {}),
            vol_medians=meta.get("vol_medians", {}),
        )
        logger.info("XGBoost loaded for %s hz=%s: %d features", bt, hz, len(meta["features"]))
        return True

    except Exception as e:
        logger.error("Failed to load XGBoost for %s: %s", ticker, e)
        _xgb_registry[rk] = None
        return False


def _predict_xgb(
    inference_snapshot_v1: dict,
    ticker: str,
    fusion_feature_overlay: dict | None = None,
    *,
    xgb_pre_engineering_snapshot: dict | None = None,
) -> Optional[dict]:
    """
    XGBoost tabular inference: MVP fields come exclusively from InferenceSnapshotV1
    (mapped via `features.xgb_model_input`). Optional `fusion_feature_overlay` supplies
    non-MVP keys only (pred_*, et_hour from fusion, …); it must not override MVP columns.

    When ``xgb_pre_engineering_snapshot`` is set (from ``build_xgb_pre_engineering_snapshot_for_tick``),
    ``fusion_feature_overlay`` is ignored — the snapshot must already include that merge.
    """
    if not _load_xgb(ticker):
        return None

    reg = _xgb_registry[_model_registry_key(ticker)]
    try:
        from features.xgb_model_input import (
            assert_not_raw_l1_payload,
            inference_snapshot_v1_to_engineering_snapshot,
            merge_xgb_fusion_overlay,
        )
        from ml_data_common import attach_net_gamma_prev_for_dgex
        from ml_train import (
            apply_xgb_imputation_matrix,
            engineer_single_snapshot,
            DB_PATH as _ML_DB,
        )

        if xgb_pre_engineering_snapshot is not None:
            snap = _apply_serve_ablation_snapshot(dict(xgb_pre_engineering_snapshot), "xgb")
        else:
            assert_not_raw_l1_payload(inference_snapshot_v1)
            if fusion_feature_overlay is not None:
                assert_not_raw_l1_payload(fusion_feature_overlay)

            base = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
            snap = merge_xgb_fusion_overlay(base, fusion_feature_overlay)

            snap = attach_net_gamma_prev_for_dgex(snap, _ML_DB)
            snap = _apply_serve_ablation_snapshot(snap, "xgb")
        X = engineer_single_snapshot(
            snapshot=snap,
            category_maps=reg["category_maps"],
            feature_names=reg["feature_names"],
            vol_medians=reg["vol_medians"],
            ticker=_bundle_ticker_for_artifacts(ticker),
        )
        if X is None:
            return None
        impute = reg["meta"].get("impute_medians") or {}
        x_mat = apply_xgb_imputation_matrix(
            X.values.astype(np.float64),
            reg["feature_names"],
            impute,
        )
        nfi = getattr(reg["model"], "n_features_in_", None)
        if nfi is not None and x_mat.shape[1] != int(nfi):
            logger.warning(
                "XGBoost %s: feature mismatch (have %d, model expects %d)",
                ticker,
                x_mat.shape[1],
                int(nfi),
            )
            return None
        probs = reg["model"].predict_proba(x_mat)[0]
        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}
    except XgbInferenceInputError:
        raise
    except Exception as e:
        logger.warning("XGBoost prediction failed for %s: %s", ticker, e)
        return None


def _normalize_binary_head_probs(raw: np.ndarray, class_names: list[str]) -> dict[str, float]:
    p = np.asarray(raw, dtype=np.float64).reshape(-1)
    p = np.nan_to_num(np.clip(p, 0.0, 1.0), nan=0.5, posinf=1.0, neginf=0.0)
    names = list(class_names)
    if len(names) >= 2 and p.size >= 2:
        s = float(p[0] + p[1])
        if s <= 0:
            u = 0.5
            return {names[0]: u, names[1]: u}
        return {names[0]: float(p[0]) / s, names[1]: float(p[1]) / s}
    if len(names) >= 2 and p.size == 1:
        p1 = float(p[0])
        return {names[1]: p1, names[0]: max(0.0, 1.0 - p1)}
    u = 1.0 / max(len(names), 1)
    return {n: u for n in names}


def _predict_xgb_movement_heads(
    inference_snapshot_v1: dict,
    ticker: str,
    fusion_feature_overlay: dict | None = None,
    *,
    xgb_pre_engineering_snapshot: dict | None = None,
) -> dict[str, float]:
    """
    Optional XGB binary classifiers: conditional direction (up/down) and move vs no_move.
    Canonical keys: pred_dir_up_prob_{hz}, pred_dir_down_prob_{hz}, pred_move_prob_{hz}, pred_no_move_prob_{hz}.
    Also mirrors legacy pred_{hz}_dir_* / pred_{hz}_move_* for backward compatibility.

    Inference contract — Option 1: when both heads load successfully, direction probabilities are
    emitted for every scored row (same engineered features as training). Downstream evaluation may
    restrict to valid_dir rows for outcome_dir calibration; move head uses the full labeled row set.
    """
    hz = get_ml_infer_horizon_slug()
    tkr = ticker.strip().upper()
    bt = _bundle_ticker_for_artifacts(ticker)
    out: dict[str, float] = {}
    _m5_snap_cached: dict | None = xgb_pre_engineering_snapshot
    _artifact_registry_entry_stale(_model_registry_key(bt, hz))
    for suffix, names_default in (("dir", ["up", "down"]), ("move", ["move", "no_move"])):
        reg_key = f"{_model_registry_key(bt, hz)}:{suffix}"
        if reg_key not in _xgb_movehead_registry:
            base = _active_bundle_dir_for_load(bt)
            if base is None:
                _xgb_movehead_registry[reg_key] = None
                continue
            mp = base / f"xgb_{bt}_{hz}_{suffix}.pkl"
            mtp = base / f"xgb_{bt}_{hz}_{suffix}_meta.json"
            if not mp.is_file() or not mtp.is_file():
                _xgb_movehead_registry[reg_key] = None
            elif (
                # Item 4: verify bytes vs bundle integrity manifest before pickle.load.
                _verify_governed_artifact(base, bt, hz, f"xgb_{suffix}", mp.name) is None
                or _verify_governed_artifact(base, bt, hz, f"xgb_{suffix}_meta", mtp.name) is None
            ):
                _xgb_movehead_registry[reg_key] = None
            else:
                try:
                    with open(mtp, encoding="utf-8") as fm:
                        meta = json.load(fm)
                    from model_contract import validate_artifact_contract

                    ok, reason = validate_artifact_contract(meta, "xgb")
                    if not ok:
                        logger.debug("movement head %s contract fail %s: %s", suffix, ticker, reason)
                        _xgb_movehead_registry[reg_key] = None
                    else:
                        with open(mp, "rb") as f:
                            model = pickle.load(f)
                        cnames = list(meta.get("class_names") or names_default)
                        _xgb_movehead_registry[reg_key] = dict(
                            model=model,
                            meta=meta,
                            feature_names=meta["features"],
                            category_maps=meta.get("category_maps", {}),
                            vol_medians=meta.get("vol_medians", {}),
                            class_names=cnames,
                        )
                except Exception as e:
                    logger.debug("movement head %s load failed for %s: %s", suffix, ticker, e)
                    _xgb_movehead_registry[reg_key] = None
        reg = _xgb_movehead_registry[reg_key]
        if reg is None:
            continue
        try:
            from features.xgb_model_input import (
                assert_not_raw_l1_payload,
                inference_snapshot_v1_to_engineering_snapshot,
                merge_xgb_fusion_overlay,
            )
            from ml_data_common import attach_net_gamma_prev_for_dgex
            from ml_train import (
                DB_PATH as _ML_DB,
                apply_xgb_imputation_matrix,
                engineer_single_snapshot,
            )

            if _m5_snap_cached is None:
                assert_not_raw_l1_payload(inference_snapshot_v1)
                if fusion_feature_overlay is not None:
                    assert_not_raw_l1_payload(fusion_feature_overlay)
                base_snap = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
                snap = merge_xgb_fusion_overlay(base_snap, fusion_feature_overlay)
                _m5_snap_cached = attach_net_gamma_prev_for_dgex(snap, _ML_DB)
            snap = _m5_snap_cached
            X = engineer_single_snapshot(
                snapshot=snap,
                category_maps=reg["category_maps"],
                feature_names=reg["feature_names"],
                vol_medians=reg["vol_medians"],
                ticker=_bundle_ticker_for_artifacts(ticker),
            )
            if X is None:
                continue
            impute = reg["meta"].get("impute_medians") or {}
            x_mat = apply_xgb_imputation_matrix(
                X.values.astype(np.float64),
                reg["feature_names"],
                impute,
            )
            nfi = getattr(reg["model"], "n_features_in_", None)
            if nfi is not None and x_mat.shape[1] != int(nfi):
                continue
            probs = reg["model"].predict_proba(x_mat)[0]
            norm = _normalize_binary_head_probs(probs, reg["class_names"])
            sm = sum(norm.values())
            if sm > 0:
                norm = {k: round(v / sm, 6) for k, v in norm.items()}
            else:
                norm = {k: round(1.0 / len(reg["class_names"]), 6) for k in reg["class_names"]}
            if suffix == "dir":
                pu = float(norm.get("up", 0.5))
                pd_ = float(norm.get("down", 0.5))
                out[f"pred_dir_up_prob_{hz}"] = pu
                out[f"pred_dir_down_prob_{hz}"] = pd_
                out[f"pred_{hz}_dir_up_prob"] = pu
                out[f"pred_{hz}_dir_down_prob"] = pd_
            else:
                pm = float(norm.get("move", 0.5))
                pn = float(norm.get("no_move", 0.5))
                out[f"pred_move_prob_{hz}"] = pm
                out[f"pred_no_move_prob_{hz}"] = pn
                out[f"pred_{hz}_move_prob"] = pm
                out[f"pred_{hz}_no_move_prob"] = pn
        except Exception as e:
            logger.debug("movement head %s predict failed for %s: %s", suffix, ticker, e)
    for k, v in list(out.items()):
        if v is None or not np.isfinite(v):
            out.pop(k, None)
        else:
            out[k] = float(min(1.0, max(0.0, v)))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LSTM - per-ticker model
# ══════════════════════════════════════════════════════════════════════════════

def _load_lstm(ticker: str) -> bool:
    bt = _bundle_ticker_for_artifacts(ticker)
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(bt, hz)
    if rk in _lstm_registry and not _artifact_registry_entry_stale(rk):
        return _lstm_registry[rk] is not None

    base = _active_bundle_dir_for_load(bt)
    if base is None:
        _lstm_registry[rk] = None
        return False
    mp = base / f"lstm_{bt}_{hz}.pt"
    if not mp.exists():
        logger.debug("LSTM model not found for %s (bundle=%s) at %s", ticker, bt, mp)
        _lstm_registry[rk] = None
        return False

    # Item 4: verify checkpoint bytes vs bundle integrity manifest before torch.load.
    if _verify_governed_artifact(base, bt, hz, "lstm", mp.name) is None:
        _lstm_registry[rk] = None
        return False

    try:
        from lstm_model import load_lstm

        model, checkpoint = load_lstm(
            model_path=mp, ticker=bt, model_dir=base, ml_horizon_slug=hz,
        )
        if model is None:
            logger.error("LSTM load failed for %s (bundle=%s): %s", ticker, bt, checkpoint)
            _lstm_registry[rk] = None
            return False

        model.eval()
        _lstm_registry[rk] = (model, checkpoint)
        logger.info("LSTM model loaded for %s hz=%s (bundle=%s)", ticker, hz, bt)
        return True

    except ImportError as e:
        logger.debug("LSTM load skipped (missing dep: %s)", e)
        _lstm_registry[rk] = None
        return False
    except Exception as e:
        logger.error("LSTM load failed for %s: %s", ticker, e)
        _lstm_registry[rk] = None
        return False


def _predict_lstm(
    ticker: str,
    db,
    snapshot: Optional[dict] = None,
    xgb_probs_arr: Optional[np.ndarray] = None,
    timeframe: Optional[str] = None,
    *,
    inference_snapshot_v1: dict | None = None,
    parallel_runtime: bool = False,
    shared_sequence_context: Any = None,
) -> Optional[dict]:
    if not _load_lstm(ticker) or db is None:
        return None

    model, checkpoint = _lstm_registry[_model_registry_key(ticker)]
    try:
        import torch
        from features.lstm_sequence_input import (
            build_lstm_merged_windows,
            encode_lstm_micro_sequence_bar_for_checkpoint,
            encode_lstm_structure_sequence_bar_for_checkpoint,
        )
        from lstm_data import (
            CANONICAL_TIMEFRAME,
            compute_confluence_features,
            CONFLUENCE_FEATURES,
            STREAM_5M_LOOKBACK,
            STREAM_1M_LOOKBACK,
            _safe_float,
            canonical_reference_spot_from_merged_window,
            assert_lstm_encoder_checkpoint_compatible,
            encoded_width_5m_for_checkpoint,
            encoded_width_1m_for_checkpoint,
        )

        tf = timeframe or CANONICAL_TIMEFRAME
        if shared_sequence_context is not None:
            merged_window = list(shared_sequence_context.lstm_merged_window)
            merged_days = list(shared_sequence_context.lstm_merged_days)
        else:
            _asof = _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1)
            recent = db.get_recent_snapshots(
                ticker,
                tf,
                n=STREAM_5M_LOOKBACK + 5,
                filled_only=False,
                as_of_ts_utc=_asof,
            )
            if not recent or len(recent) < STREAM_5M_LOOKBACK:
                raise LstmSequenceInputError(
                    f"LSTM needs at least {STREAM_5M_LOOKBACK} snapshots, got {len(recent or [])}"
                )
            recent = list(reversed(recent))
            window = recent[-STREAM_5M_LOOKBACK:]

            day_snaps = db.get_recent_snapshots(
                ticker, tf, n=100, filled_only=False, as_of_ts_utc=_asof
            )
            day_snaps = list(reversed(day_snaps)) if day_snaps else list(window)

            merged_window, merged_days = build_lstm_merged_windows(
                window, day_snaps, inference_snapshot_v1=inference_snapshot_v1
            )

        merged_window = _mask_sequence_bars_for_model(merged_window, "lstm")
        merged_days = _mask_sequence_bars_for_model(merged_days, "lstm")

        try:
            ref_spot = canonical_reference_spot_from_merged_window(merged_window)
        except ValueError as e:
            raise LstmSequenceInputError(str(e)) from e

        try:
            assert_lstm_encoder_checkpoint_compatible(checkpoint)
        except ValueError as e:
            logger.error("LSTM %s: %s", ticker, e)
            return None

        seq_5m = [
            encode_lstm_structure_sequence_bar_for_checkpoint(s, ref_spot, checkpoint)
            for s in merged_window
        ]
        micro = merged_window[-STREAM_1M_LOOKBACK:]
        mr = _safe_float(micro[0].get("spot")) or ref_spot
        seq_1m = [
            encode_lstm_micro_sequence_bar_for_checkpoint(s, mr, checkpoint) for s in micro
        ]

        X_5m   = np.array([seq_5m],   dtype=np.float32)
        X_1m   = np.array([seq_1m],   dtype=np.float32)
        exp5 = encoded_width_5m_for_checkpoint(checkpoint)
        exp1 = encoded_width_1m_for_checkpoint(checkpoint)
        if len(seq_5m[0]) != exp5 or len(seq_1m[0]) != exp1:
            logger.error(
                "LSTM %s: encoder width mismatch (5m=%d expected %d, 1m=%d expected %d)",
                ticker,
                len(seq_5m[0]),
                exp5,
                len(seq_1m[0]),
                exp1,
            )
            return None

        conf = compute_confluence_features(merged_days, len(merged_days) - 1)
        conf_vec = [conf[k] for k in CONFLUENCE_FEATURES]

        snap = snapshot if snapshot is not None else _snap_dict(merged_window[-1])
        mask_conf = np.array(
            checkpoint.get("mask_conf", [True] * (len(conf_vec))),
            dtype=bool,
        )
        n_conf_base = len(CONFLUENCE_FEATURES)
        if mask_conf.shape[0] > n_conf_base:
            need = mask_conf.shape[0] - n_conf_base
            if need == _CASCADE_LSTM_CONF_EXTRA:
                if parallel_runtime:
                    raise ParallelRuntimeArtifactError(
                        f"LSTM {ticker}: checkpoint confluence mask expects cascade extras "
                        f"({mask_conf.shape[0]} vs base {n_conf_base}); use parallel-trained artifacts "
                        f"for production parallel runtime."
                    )
                xa = xgb_probs_arr
                if xa is None and snap is not None:
                    if inference_snapshot_v1 is None:
                        xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                    else:
                        xa = _probs_dict_to_arr(
                            _predict_xgb(inference_snapshot_v1, ticker, fusion_feature_overlay=snap)
                        )
                elif xa is None:
                    xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                xa = np.asarray(xa, dtype=np.float32).reshape(-1)
                if xa.shape[0] != _CASCADE_LSTM_CONF_EXTRA:
                    xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                conf_vec = conf_vec + xa.tolist()
            else:
                logger.warning(
                    "LSTM %s: unexpected cascade confluence width (mask %d, base %d)",
                    ticker, mask_conf.shape[0], n_conf_base,
                )
                return None

        X_conf = np.array([conf_vec], dtype=np.float32)

        mask_5m = np.array(checkpoint.get("mask_5m", [True] * X_5m.shape[2]))
        mask_1m = np.array(checkpoint.get("mask_1m", [True] * X_1m.shape[2]))
        if mask_5m.shape[0] != X_5m.shape[2]:
            logger.error(
                "LSTM %s: checkpoint mask_5m len %d != encoded width %d; retrain required",
                ticker,
                mask_5m.shape[0],
                X_5m.shape[2],
            )
            return None
        if mask_1m.shape[0] != X_1m.shape[2]:
            logger.error(
                "LSTM %s: checkpoint mask_1m len %d != encoded width %d; retrain required",
                ticker,
                mask_1m.shape[0],
                X_1m.shape[2],
            )
            return None
        if mask_conf.shape[0] != X_conf.shape[1]:
            logger.warning(
                "LSTM %s: mask_conf len %d vs conf width %d",
                ticker, mask_conf.shape[0], X_conf.shape[1],
            )
            return None
        X_5m   = X_5m[:, :, mask_5m]
        X_1m   = X_1m[:, :, mask_1m]
        X_conf = X_conf[:, mask_conf]

        norm = checkpoint.get("norm_stats", {})
        if norm:
            from lstm_model import align_lstm_norm_stats, apply_normalization

            aligned = align_lstm_norm_stats(norm, mask_5m, mask_1m, mask_conf)
            if aligned is None:
                logger.warning(
                    "LSTM %s: norm_stats could not be aligned to feature masks", ticker
                )
                return None
            X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, aligned)

        X_5m   = np.nan_to_num(X_5m,   nan=0.0, posinf=0.0, neginf=0.0)
        X_1m   = np.nan_to_num(X_1m,   nan=0.0, posinf=0.0, neginf=0.0)
        X_conf = np.nan_to_num(X_conf, nan=0.0, posinf=0.0, neginf=0.0)

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
                    horizon_slug=get_ml_infer_horizon_slug(),
                    features_5m=FEATURES_5M,
                    features_1m=FEATURES_1M,
                    encoded_features_5m=ENCODED_FEATURES_5M,
                    encoded_features_1m=ENCODED_FEATURES_1M,
                )
                from arch_competition.stack_bundle_eval_v1 import zero_ablated_lstm_conf_channels

                X_conf = zero_ablated_lstm_conf_channels(
                    X_conf,
                    model_family="lstm",
                    horizon_slug=get_ml_infer_horizon_slug(),
                )
        except Exception:
            logger.error(
                "LSTM %s: post-norm ablation channel zero failed — refusing train/serve skew",
                ticker,
                exc_info=True,
            )
            return None

        with torch.no_grad():
            logits = model(torch.from_numpy(X_1m).float(),
                           torch.from_numpy(X_5m).float(),
                           torch.from_numpy(X_conf).float())
            probs = torch.softmax(logits, dim=-1).squeeze().numpy()

        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}

    except LstmSequenceInputError:
        raise
    except ParallelRuntimeArtifactError:
        raise
    except Exception as e:
        logger.warning("LSTM prediction failed for %s: %s", ticker, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# TRANSFORMER - per-ticker model
# ══════════════════════════════════════════════════════════════════════════════

def _load_transformer(ticker: str) -> bool:
    bt = _bundle_ticker_for_artifacts(ticker)
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(bt, hz)
    if rk in _trans_registry and not _artifact_registry_entry_stale(rk):
        return _trans_registry[rk] is not None

    base = _active_bundle_dir_for_load(bt)
    if base is None:
        _trans_registry[rk] = None
        return False
    mp = base / f"transformer_{bt}_{hz}.pt"
    mtp = base / f"transformer_{bt}_{hz}_meta.json"
    if not mp.exists():
        logger.debug("Transformer model not found for %s (bundle=%s) at %s", ticker, bt, mp)
        _trans_registry[rk] = None
        return False
    if not mtp.exists():
        logger.error("Transformer %s: missing meta %s; refusing load.", ticker, mtp.name)
        _trans_registry[rk] = None
        return False

    # Item 4: verify checkpoint + meta bytes vs bundle integrity manifest before torch.load.
    if (
        _verify_governed_artifact(base, bt, hz, "transformer", mp.name) is None
        or _verify_governed_artifact(base, bt, hz, "transformer_meta", mtp.name) is None
    ):
        _trans_registry[rk] = None
        return False

    try:
        with open(mtp, "r", encoding="utf-8") as f:
            tr_meta = json.load(f)
        from model_contract import validate_artifact_contract

        ok, reason = validate_artifact_contract(tr_meta, "transformer")
        if not ok:
            logger.error(
                "Transformer %s: incompatible model contract (%s). Retrain; refusing load.",
                ticker,
                reason,
            )
            _trans_registry[rk] = None
            return False

        import torch
        import numpy as np
        checkpoint = torch.load(str(mp), map_location="cpu", weights_only=False)
        from lstm_data import assert_lstm_encoder_checkpoint_compatible

        try:
            assert_lstm_encoder_checkpoint_compatible(checkpoint)
        except ValueError as exc:
            logger.error("Transformer %s: %s", ticker, exc)
            _trans_registry[rk] = None
            return False
        n_enc = int(checkpoint.get("n_features", 0))
        fm = checkpoint.get("feature_mask")
        if fm is not None:
            n_masked = int(np.asarray(fm, dtype=bool).sum())
            if n_enc and n_enc != n_masked:
                logger.error(
                    "Transformer %s: n_features=%s != feature_mask active count %s; retrain",
                    ticker,
                    n_enc,
                    n_masked,
                )
                _trans_registry[rk] = None
                return False
        else:
            from lstm_data import encoded_width_5m_for_checkpoint

            enc_base = encoded_width_5m_for_checkpoint(checkpoint)
            if n_enc and n_enc != enc_base:
                logger.error(
                    "Transformer %s: n_features=%s != encoder width %s; retrain",
                    ticker,
                    n_enc,
                    enc_base,
                )
                _trans_registry[rk] = None
                return False
        from transformer_train import build_transformer
        model = build_transformer(
            checkpoint["n_features"],
            seq_len=checkpoint.get("seq_len", 20),
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        _trans_registry[rk] = (model, checkpoint)
        logger.info("Transformer model loaded for %s hz=%s", ticker, hz)
        return True

    except ImportError as e:
        logger.debug("Transformer load skipped (missing dep: %s)", e)
        _trans_registry[rk] = None
        return False
    except Exception as e:
        logger.error("Transformer load failed for %s: %s", ticker, e)
        _trans_registry[rk] = None
        return False


def _predict_transformer(
    ticker: str,
    db,
    snapshot: Optional[dict] = None,
    xgb_probs_arr: Optional[np.ndarray] = None,
    lstm_probs_arr: Optional[np.ndarray] = None,
    timeframe: Optional[str] = None,
    *,
    inference_snapshot_v1: dict | None = None,
    parallel_runtime: bool = False,
    shared_sequence_context: Any = None,
) -> Optional[dict]:
    if not _load_transformer(ticker) or db is None:
        return None

    model, checkpoint = _trans_registry[_model_registry_key(ticker)]

    try:
        _asof = _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1)
    except LstmSequenceInputError as e:
        raise TransformerSequenceInputError(str(e)) from e

    try:
        import torch
        from features.lstm_sequence_input import (
            encode_lstm_structure_sequence_bar_for_checkpoint,
        )
        from lstm_data import (
            CANONICAL_TIMEFRAME,
            canonical_reference_spot_from_merged_window,
            assert_lstm_encoder_checkpoint_compatible,
            encoded_width_5m_for_checkpoint,
        )

        tf = timeframe or CANONICAL_TIMEFRAME
        seq_len = checkpoint.get("seq_len", 20)
        n_enc_base = encoded_width_5m_for_checkpoint(checkpoint)
        try:
            assert_lstm_encoder_checkpoint_compatible(checkpoint)
        except ValueError as exc:
            logger.error("Transformer %s: %s", ticker, exc)
            return None

        if shared_sequence_context is not None:
            from features.shared_sequence_context import transformer_window_chronological

            window = transformer_window_chronological(shared_sequence_context, seq_len)
        else:
            recent = db.get_recent_snapshots(
                ticker, tf, n=seq_len + 5, filled_only=False, as_of_ts_utc=_asof
            )
            if not recent or len(recent) < seq_len:
                raise TransformerSequenceInputError(
                    f"Transformer needs at least {seq_len} snapshots, got {len(recent or [])}"
                )
            recent = list(reversed(recent))
            window = recent[-seq_len:]

        merged_window = build_transformer_merged_window(
            window, inference_snapshot_v1=inference_snapshot_v1
        )
        merged_window = _mask_sequence_bars_for_model(merged_window, "transformer")

        try:
            ref_spot = canonical_reference_spot_from_merged_window(merged_window)
        except ValueError as e:
            raise TransformerSequenceInputError(str(e)) from e

        snap = snapshot if snapshot is not None else _snap_dict(merged_window[-1])
        seq = [
            encode_lstm_structure_sequence_bar_for_checkpoint(s, ref_spot, checkpoint)
            for s in merged_window
        ]
        base = np.array([seq], dtype=np.float32)
        if len(seq[0]) != n_enc_base:
            logger.error(
                "Transformer %s: encoder width %d != expected %d",
                ticker,
                len(seq[0]),
                n_enc_base,
            )
            return None

        fm = np.asarray(
            checkpoint.get("feature_mask", np.ones(base.shape[2], dtype=bool)),
            dtype=bool,
        )

        if fm.shape[0] != base.shape[2]:
            if (
                fm.shape[0] == n_enc_base + _CASCADE_TRANSFORMER_SEQ_EXTRA
                and base.shape[2] == n_enc_base
            ):
                if parallel_runtime:
                    raise ParallelRuntimeArtifactError(
                        f"Transformer {ticker}: checkpoint feature_mask expects cascade sequence extras "
                        f"({fm.shape[0]} vs encode {n_enc_base}); use parallel-trained artifacts "
                        f"for production parallel runtime."
                    )
                if xgb_probs_arr is None:
                    if snap is None or inference_snapshot_v1 is None:
                        xgb_probs_arr = _probs_dict_to_arr(None)
                    else:
                        xgb_probs_arr = _probs_dict_to_arr(
                            _predict_xgb(inference_snapshot_v1, ticker, fusion_feature_overlay=snap)
                        )
                if lstm_probs_arr is None:
                    lstm_probs_arr = _probs_dict_to_arr(
                        _predict_lstm(
                            ticker,
                            db,
                            snapshot=snap,
                            xgb_probs_arr=xgb_probs_arr,
                            timeframe=tf,
                            inference_snapshot_v1=inference_snapshot_v1,
                            shared_sequence_context=shared_sequence_context,
                        )
                    )
                xa = np.asarray(xgb_probs_arr, dtype=np.float32).reshape(-1)
                la = np.asarray(lstm_probs_arr, dtype=np.float32).reshape(-1)
                if xa.shape[0] != 3:
                    xa = np.full(3, 1.0 / 3.0, dtype=np.float32)
                if la.shape[0] != 3:
                    la = np.full(3, 1.0 / 3.0, dtype=np.float32)
                six = np.concatenate([xa, la], axis=0)
                extra = np.broadcast_to(six.reshape(1, 1, 6), (1, seq_len, 6))
                X_raw = np.concatenate([base, extra.astype(np.float32)], axis=2)
            else:
                logger.warning(
                    "Transformer %s: cannot align feature_mask (%d) with encode width (%d)",
                    ticker, fm.shape[0], base.shape[2],
                )
                return None
        else:
            X_raw = base

        if X_raw.shape[2] != fm.shape[0]:
            logger.warning(
                "Transformer %s: raw tensor width %d vs feature_mask %d",
                ticker, X_raw.shape[2], fm.shape[0],
            )
            return None

        X = _transformer_normalize_and_select(X_raw, checkpoint)
        X = _transformer_apply_ablation_channel_zero(X, checkpoint)

        with torch.no_grad():
            logits = model(torch.from_numpy(X).float())
            probs_t = torch.softmax(logits, dim=-1)
            probs = probs_t.squeeze().detach().cpu().numpy()
        if probs.ndim > 1:
            probs = probs.reshape(-1, probs.shape[-1])[0]
        if probs.shape[0] != 3:
            logger.warning(
                "Transformer %s: unexpected prob shape %s", ticker, getattr(probs, "shape", None)
            )
            return None

        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}

    except TransformerSequenceInputError:
        raise
    except ParallelRuntimeArtifactError:
        raise
    except LstmSequenceInputError as e:
        # Cascade transformer depends on the LSTM head (XGB+LSTM probs as input features),
        # so it inherits the LSTM's 60-snapshot lookback. During warmup (<60 snapshots) this
        # is expected fail-closed behavior, not a failure — log quietly, don't flood WARNING.
        logger.debug("Transformer %s: cascade LSTM dependency not ready (%s)", ticker, e)
        return None
    except Exception as e:
        logger.warning("Transformer prediction failed for %s: %s", ticker, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# META-LEARNER - logistic regression on stacked Layer 1 outputs
# ══════════════════════════════════════════════════════════════════════════════

def _load_meta(ticker: str) -> bool:
    bt = _bundle_ticker_for_artifacts(ticker)
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(bt, hz)
    if rk in _meta_registry and not _artifact_registry_entry_stale(rk):
        return _meta_registry[rk] is not None

    base = _active_bundle_dir_for_load(bt)
    if base is None:
        _meta_registry[rk] = None
        return False
    mp = base / f"meta_{bt}_{hz}.pkl"
    if not mp.exists():
        _meta_registry[rk] = None
        return False

    # Item 4: verify pickle bytes vs bundle integrity manifest before pickle.load.
    if _verify_governed_artifact(base, bt, hz, "meta", mp.name) is None:
        _meta_registry[rk] = None
        return False

    try:
        with open(mp, "rb") as f:
            _meta_registry[rk] = pickle.load(f)
        logger.info("Meta-learner loaded for %s hz=%s", ticker, hz)
        return True
    except Exception as e:
        logger.error("Meta-learner load failed for %s: %s", ticker, e)
        _meta_registry[rk] = None
        return False


def _parallel_base_stack_complete(
    xgb_p: Optional[dict],
    lstm_p: Optional[dict],
    trans_p: Optional[dict],
) -> bool:
    """True only when all three parallel ML stack layers returned complete probability triplets."""
    return all(
        _require_direction_probability_triplet(p) is not None
        for p in (xgb_p, lstm_p, trans_p)
    )


def _stack_probs(xgb_p, lstm_p, trans_p) -> Optional[np.ndarray]:
    """Stack Layer 1 outputs into 9-feature vector. Fail-closed when any leg is missing."""
    if not _parallel_base_stack_complete(xgb_p, lstm_p, trans_p):
        return None

    def _to_vec(p: dict) -> list[float]:
        tri = _require_direction_probability_triplet(p)
        assert tri is not None
        return [tri[0], tri[1], tri[2]]

    return np.array(
        _to_vec(xgb_p) + _to_vec(lstm_p) + _to_vec(trans_p),
        dtype=np.float64,
    ).reshape(1, -1)


def _meta_model_input_width(ticker: str) -> int | None:
    """Feature width the loaded meta pickle expects (9 legacy or 9+tabular v2)."""
    if not _load_meta(ticker):
        return None
    mdl = _meta_registry[_model_registry_key(ticker)]
    n = getattr(mdl, "n_features_in_", None)
    try:
        return int(n) if n is not None else None
    except (TypeError, ValueError):
        return None


def _meta_stack_feature_matrix(
    ticker: str,
    xgb_p,
    lstm_p,
    trans_p,
    *,
    meta_tabular_overlay: dict | None = None,
) -> Optional[np.ndarray]:
    """Build meta input row: stacked base probs + optional tabular overlay (v2)."""
    stack = _stack_probs(xgb_p, lstm_p, trans_p)
    if stack is None:
        return None
    expected = _meta_model_input_width(ticker)
    if expected is None:
        return stack
    from features.fusion_model_input import meta_tabular_input_dim, meta_tabular_vector_from_overlay
    from governed_stack_contract import META_STACK_PROB_DIM

    tab_dim = meta_tabular_input_dim()
    if expected == META_STACK_PROB_DIM:
        return stack
    if expected == META_STACK_PROB_DIM + tab_dim:
        if meta_tabular_overlay is None:
            return None
        tab = np.array(
            meta_tabular_vector_from_overlay(meta_tabular_overlay),
            dtype=np.float64,
        ).reshape(1, -1)
        if tab.shape[1] != tab_dim:
            return None
        return np.concatenate([stack, tab], axis=1)
    logger.warning(
        "Meta %s: unexpected n_features_in_=%s (expected %s or %s)",
        ticker,
        expected,
        META_STACK_PROB_DIM,
        META_STACK_PROB_DIM + tab_dim,
    )
    return None


def _predict_meta(
    ticker: str,
    xgb_p,
    lstm_p,
    trans_p,
    *,
    meta_tabular_overlay: dict | None = None,
) -> Optional[dict]:
    if not _load_meta(ticker):
        return None
    try:
        X = _meta_stack_feature_matrix(
            ticker,
            xgb_p,
            lstm_p,
            trans_p,
            meta_tabular_overlay=meta_tabular_overlay,
        )
        if X is None:
            return None
        probs = _meta_registry[_model_registry_key(ticker)].predict_proba(X)[0]
        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}
    except Exception as e:
        logger.warning("Meta-learner prediction failed for %s: %s", ticker, e)
        return None


def _weighted_average(
    ticker: str, xgb_p, lstm_p, trans_p, collapsed: Optional[set] = None
) -> Optional[dict]:
    """Weighted average fallback when the meta-learner is not trained. Requires the full
    XGB+LSTM+TR stack to be *present*; bases flagged ``val_single_class_collapse`` (B3+
    degeneracy) are dropped and the remaining weights re-normalized so a confident all-flat
    base cannot drag the ensemble flat. All bases collapsed -> visible uniform.

    Back-compat: ``collapsed`` empty/None weights all three at 0.40/0.35/0.25 (sum 1.0),
    byte-identical to the prior behavior.
    """
    if not _parallel_base_stack_complete(xgb_p, lstm_p, trans_p):
        return None
    assert xgb_p is not None and lstm_p is not None and trans_p is not None
    collapsed = collapsed or set()
    base_weights = (("xgb", xgb_p, 0.40), ("lstm", lstm_p, 0.35), ("transformer", trans_p, 0.25))
    healthy = [(name, p, w) for name, p, w in base_weights if name not in collapsed]
    if not healthy:
        logger.warning(
            "Parallel combiner %s: all bases single-class-collapsed — returning uniform", ticker
        )
        return dict(_UNIFORM_PROBS)
    total_w = sum(w for _, _, w in healthy)
    result = {c: 0.0 for c in CLASS_NAMES}
    for _name, probs, w in healthy:
        tri = _require_direction_probability_triplet(probs)
        assert tri is not None
        nw = w / total_w
        result["up"] += tri[0] * nw
        result["down"] += tri[1] * nw
        result["flat"] += tri[2] * nw
    return {c: round(result[c], 4) for c in CLASS_NAMES}


def _weighted_average_partial(
    ticker: str,
    weighted_parts: list[tuple[str, Optional[dict], float]],
    *,
    collapsed: Optional[set] = None,
) -> Optional[dict]:
    """Renormalized blend over available base legs (e.g. 5c xgb_plus_transformer without LSTM)."""
    collapsed = collapsed or set()
    healthy: list[tuple[str, dict, float]] = []
    for name, probs, weight in weighted_parts:
        if name in collapsed:
            continue
        tri = _require_direction_probability_triplet(probs)
        if tri is None:
            continue
        healthy.append((name, probs, float(weight)))
    if not healthy:
        return None
    total_w = sum(w for _, _, w in healthy)
    result = {c: 0.0 for c in CLASS_NAMES}
    for _name, probs, w in healthy:
        tri = _require_direction_probability_triplet(probs)
        assert tri is not None
        nw = w / total_w
        result["up"] += tri[0] * nw
        result["down"] += tri[1] * nw
        result["flat"] += tri[2] * nw
    return {c: round(result[c], 4) for c in CLASS_NAMES}


def read_stack_layer_collapse_flags(model_dir, ticker: str, hz: str) -> set:
    """Set of base names ('xgb'/'lstm'/'transformer') whose persisted meta in ``model_dir``
    carries ``val_single_class_collapse=True`` (the B3+ all-flat degeneracy flag written by
    ml_train / lstm_model / transformer_train). Same read pattern the A2 promotion gate uses.
    """
    bt = _bundle_ticker_for_artifacts(ticker)
    flags: set = set()
    for base in ("xgb", "lstm", "transformer"):
        meta_json = Path(model_dir) / f"{base}_{bt}_{hz}_meta.json"
        if not meta_json.is_file():
            continue
        try:
            data = json.loads(meta_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if bool(data.get("val_single_class_collapse")):
            flags.add(base)
    return flags


def _active_base_collapse_flags(ticker: str) -> set:
    """Cached per-(ticker,hz) collapse flags for the active bundle (called per eval row)."""
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(ticker, hz)
    cached = _collapse_flag_registry.get(rk)
    if cached is not None:
        return cached
    # Best-effort: if the active bundle dir can't be resolved (e.g. strict-active-only with an
    # incomplete bundle), fall back to "no collapse flags" — identical to prior combiner behavior.
    try:
        flags = read_stack_layer_collapse_flags(_model_dir_for_ticker(ticker), ticker, hz)
    except Exception as e:
        logger.debug("collapse-flag read skipped for %s: %s", ticker, e)
        flags = set()
    _collapse_flag_registry[rk] = flags
    return flags


def _ensemble_parallel_probs(
    ticker: str,
    xgb_p: Optional[dict],
    lstm_p: Optional[dict],
    trans_p: Optional[dict],
    *,
    meta_tabular_overlay: dict | None = None,
) -> Optional[dict]:
    """Meta when trained, else weighted average — only when full parallel stack is present.

    A base flagged ``val_single_class_collapse`` is degenerate (all-flat); the meta is
    re-fit clean against it on retrain (see ml_scheduler._assemble_meta_base_prob_vectors),
    so the meta path needs no row-time change EXCEPT the all-collapsed guard below. The
    weighted-average fallback drops collapsed bases.
    """
    if not _parallel_base_stack_complete(xgb_p, lstm_p, trans_p):
        return None
    collapsed = _active_base_collapse_flags(ticker)
    if collapsed >= {"xgb", "lstm", "transformer"}:
        logger.warning(
            "Parallel combiner %s: all three bases single-class-collapsed — uniform (not false-flat)",
            ticker,
        )
        return dict(_UNIFORM_PROBS)
    stack_probs = _predict_meta(
        ticker,
        xgb_p,
        lstm_p,
        trans_p,
        meta_tabular_overlay=meta_tabular_overlay,
    )
    if stack_probs is None:
        stack_probs = _weighted_average(ticker, xgb_p, lstm_p, trans_p, collapsed=collapsed)
    return stack_probs


def _apply_5c_xgb_plus_transformer_isotonic_calibration(
    ticker: str,
    probs: Optional[dict],
) -> Optional[dict]:
    """
    Runtime calibration for 5c winning stack (xgb_plus_transformer) using
    one-vs-rest isotonic regression maps fit from validation outputs.

    Applies only to SPY/5c blended probabilities and preserves simplex normalization.
    """
    if not probs:
        return probs
    feature_ticker = (ticker or "").upper().strip()
    bt = _bundle_ticker_for_artifacts(ticker)
    if feature_ticker != "SPY" or bt != "SPY":
        return probs
    if get_ml_infer_horizon_slug() != "5c":
        return probs

    # OVR isotonic maps from validation cohort (X_thresholds_, y_thresholds_).
    maps = {
        "up": {
            "x": [0.0639, 0.1053, 0.10531053105310531, 0.1442, 0.1443, 0.1593, 0.15978402159784022, 0.1937, 0.194, 0.20492049204920493, 0.205, 0.3056, 0.3071, 0.3242, 0.3243, 0.3498, 0.3512, 0.3971, 0.3986, 0.44144414441444146, 0.4436, 0.4645, 0.4667533246675332, 0.4765, 0.4774, 0.4908509149085092, 0.4914, 0.5041495850414959, 0.5050505050505051, 0.5116, 0.512, 0.5696, 0.579, 0.6160383961603839],
            "y": [0.0, 0.0, 0.028846153846153848, 0.028846153846153848, 0.09090909090909091, 0.09090909090909091, 0.14754098360655737, 0.14754098360655737, 0.15384615384615385, 0.15384615384615385, 0.2222222222222222, 0.2222222222222222, 0.2631578947368421, 0.2631578947368421, 0.4074074074074074, 0.4074074074074074, 0.4090909090909091, 0.4090909090909091, 0.5, 0.5, 0.5625, 0.5625, 0.6363636363636364, 0.6363636363636364, 0.6470588235294118, 0.6470588235294118, 0.6666666666666666, 0.6666666666666666, 0.75, 0.75, 0.8888888888888888, 0.8888888888888888, 1.0, 1.0],
        },
        "down": {
            "x": [0.0471, 0.08680868086808681, 0.0869, 0.1111, 0.1114111411141114, 0.1386, 0.1389, 0.15548445155484447, 0.1559, 0.2506, 0.251, 0.26030000000000003, 0.2604, 0.3232, 0.32356764323567644, 0.436, 0.43755624437556245, 0.4625, 0.4642, 0.471, 0.4714, 0.4753, 0.4755, 0.4819, 0.4822, 0.5019, 0.5023, 0.607039296070393],
            "y": [0.0, 0.0, 0.014598540145985401, 0.014598540145985401, 0.0375, 0.0375, 0.043478260869565216, 0.043478260869565216, 0.08695652173913043, 0.08695652173913043, 0.1111111111111111, 0.1111111111111111, 0.18867924528301888, 0.18867924528301888, 0.32, 0.32, 0.5, 0.5, 0.6363636363636364, 0.6363636363636364, 0.75, 0.75, 0.7692307692307693, 0.7692307692307693, 0.8, 0.8, 0.9333333333333333, 0.9333333333333333],
        },
        "flat": {
            "x": [0.2429, 0.2636736326367363, 0.29892989298929895, 0.3063306330633063, 0.36423642364236425, 0.3662, 0.3828382838283828, 0.38303830383038306, 0.3986, 0.399, 0.4172, 0.4177, 0.41885811418858115, 0.419, 0.4281571842815718, 0.4293, 0.4423, 0.4436, 0.45825417458254175, 0.4588458845884588, 0.4995, 0.4996, 0.5050494950504949, 0.5053, 0.5333, 0.5335, 0.5428, 0.5437456254374562, 0.5672, 0.568, 0.5937406259374063, 0.5939, 0.6129, 0.6129612961296129, 0.6453, 0.6454, 0.6845, 0.685, 0.6932, 0.6951, 0.734073407340734, 0.7348, 0.7418, 0.7443, 0.7861786178617862, 0.7867786778677868, 0.8318, 0.8325, 0.8816],
            "y": [0.0, 0.125, 0.125, 0.19230769230769232, 0.19230769230769232, 0.2222222222222222, 0.2222222222222222, 0.25, 0.25, 0.3125, 0.3125, 0.375, 0.375, 0.4444444444444444, 0.4444444444444444, 0.4642857142857143, 0.4642857142857143, 0.4666666666666667, 0.4666666666666667, 0.4923076923076923, 0.4923076923076923, 0.5, 0.5, 0.5106382978723404, 0.5106382978723404, 0.5555555555555556, 0.5555555555555556, 0.5609756097560976, 0.5609756097560976, 0.5636363636363636, 0.5636363636363636, 0.7441860465116279, 0.7441860465116279, 0.8163265306122449, 0.8163265306122449, 0.8428571428571429, 0.8428571428571429, 0.8666666666666667, 0.8666666666666667, 0.8771929824561403, 0.8771929824561403, 0.9333333333333333, 0.9333333333333333, 0.9565217391304348, 0.9565217391304348, 0.9702970297029703, 0.9702970297029703, 1.0, 1.0],
        },
    }

    calibrated = {}
    for c in CLASS_NAMES:
        p = float(probs.get(c, 1.0 / 3.0))
        p = max(0.0, min(1.0, p))
        x = np.asarray(maps[c]["x"], dtype=np.float64)
        y = np.asarray(maps[c]["y"], dtype=np.float64)
        calibrated[c] = float(np.interp(p, x, y, left=y[0], right=y[-1]))

    s = float(sum(calibrated.values()))
    if s <= 0.0:
        return {"up": 1.0 / 3.0, "down": 1.0 / 3.0, "flat": 1.0 / 3.0}
    norm = {c: float(calibrated[c] / s) for c in CLASS_NAMES}
    # Keep exact simplex sum after float math.
    norm["flat"] = max(0.0, 1.0 - norm["up"] - norm["down"])
    return norm


# ══════════════════════════════════════════════════════════════════════════════
# FUSION API — model outputs with probabilities for bayesian_fusion
# ══════════════════════════════════════════════════════════════════════════════


def _resolve_ml_inference_ticker(
    ticker: str | None,
    snapshot: dict,
    *,
    inference_snapshot_v1: dict | None = None,
) -> str:
    """Resolve ticker for ML paths; fail closed when none of ticker / snapshot / envelope provide it."""
    for raw in (
        ticker,
        snapshot.get("ticker") if isinstance(snapshot, dict) else None,
        inference_snapshot_v1.get("ticker") if isinstance(inference_snapshot_v1, dict) else None,
    ):
        if raw is not None and str(raw).strip():
            return str(raw).strip().upper()
    raise ValueError(
        "ML inference requires a resolvable ticker (ticker=, snapshot['ticker'], or "
        "inference_snapshot_v1['ticker'])"
    )


def run_unified_stack_ml_once(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
    xgb_pre_engineering_snapshot: dict | None = None,
    shared_sequence_context: Any = None,
    meta_tabular_overlay: dict | None = None,
) -> dict:
    """
    Unified stack ML layers (xgb, lstm, transformer) — one team pass per tick/horizon.

    Each layer runs independently (no cross-model tensors). Sequence models use
    ``parallel_runtime=True`` and refuse cascade-only checkpoints.

    Feeds fusion helpers, UI model_outputs, and meta / weighted stack_probs — single pass.

    XGBoost requires InferenceSnapshotV1. Pass `snapshot` as fusion overlay only (pred_*, et_hour, …);
    MVP comes only from `inference_snapshot_v1`.

    Optional ``xgb_pre_engineering_snapshot`` (from ``build_xgb_pre_engineering_snapshot_for_tick``)
    avoids repeating MVP→overlay→m5 ingest for each governed horizon on the same tick.

    Optional ``shared_sequence_context`` (from ``features.shared_sequence_context.build_shared_sequence_context``)
    supplies one DB fetch + one LSTM merge for the tick; LSTM/Transformer skip redundant history reads.
    """
    if inference_snapshot_v1 is None:
        raise ValueError(
            "run_unified_stack_ml_once requires inference_snapshot_v1= (InferenceSnapshotV1 dict). "
            "Raw fusion snapshots are not accepted for XGB."
        )

    tkr = _resolve_ml_inference_ticker(
        ticker, snapshot, inference_snapshot_v1=inference_snapshot_v1
    )

    xgb_p = _predict_xgb(
        inference_snapshot_v1,
        tkr,
        fusion_feature_overlay=snapshot,
        xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
    )
    lstm_p = _predict_lstm(
        tkr,
        db,
        snapshot=snapshot,
        xgb_probs_arr=None,
        inference_snapshot_v1=inference_snapshot_v1,
        parallel_runtime=True,
        shared_sequence_context=shared_sequence_context,
    )
    tr_p = _predict_transformer(
        tkr,
        db,
        snapshot=snapshot,
        xgb_probs_arr=None,
        lstm_probs_arr=None,
        inference_snapshot_v1=inference_snapshot_v1,
        parallel_runtime=True,
        shared_sequence_context=shared_sequence_context,
    )

    fusion_pack = {
        "xgb": _model_probs_to_fusion_out(xgb_p, direction_hint),
        "lstm": _model_probs_to_fusion_out(lstm_p, direction_hint),
        "transformer": _model_probs_to_fusion_out(tr_p, direction_hint),
    }
    def _parallel_model_output_record(p: Optional[dict], approved: bool) -> dict:
        r = build_unified_stack_layer_output(probs=p, approved=approved and p is not None)
        if r.get("available"):
            r["up"] = r["prob_up"]
            r["down"] = r["prob_down"]
            r["flat"] = r["prob_flat"]
            r["confidence"] = r["confidence_score"]
        else:
            r["up"] = None
            r["down"] = None
            r["flat"] = None
            r["confidence"] = None
            r["dominant"] = None
        return r

    model_outputs = {
        "xgb": _parallel_model_output_record(xgb_p, xgb_p is not None),
        "lstm": _parallel_model_output_record(lstm_p, lstm_p is not None),
        "transformer": _parallel_model_output_record(tr_p, tr_p is not None),
    }

    stack_probs = None
    if xgb_p is not None or lstm_p is not None or tr_p is not None:
        # 5c default runtime path: winning stack is xgb_plus_transformer with
        # calibrated probabilities before downstream decision consumption.
        if get_ml_infer_horizon_slug() == "5c":
            stack_probs = _weighted_average_partial(
                tkr,
                [("xgb", xgb_p, 0.40), ("transformer", tr_p, 0.25)],
                collapsed=_active_base_collapse_flags(tkr),
            )
            stack_probs = _apply_5c_xgb_plus_transformer_isotonic_calibration(
                tkr, stack_probs
            )
        else:
            _meta_overlay = meta_tabular_overlay if meta_tabular_overlay is not None else snapshot
            stack_probs = _ensemble_parallel_probs(
                tkr,
                xgb_p,
                lstm_p,
                tr_p,
                meta_tabular_overlay=_meta_overlay,
            )

    logger.debug(
        "run_unified_stack_ml_once %s: xgb=%s lstm=%s tr=%s",
        tkr,
        _fmt(xgb_p),
        _fmt(lstm_p),
        _fmt(tr_p),
    )
    _mh = _predict_xgb_movement_heads(
        inference_snapshot_v1,
        tkr,
        fusion_feature_overlay=snapshot,
        xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
    )
    return {
        "fusion": fusion_pack,
        "model_outputs": model_outputs,
        stack_probs_bundle_key(): stack_probs,
        "movement_head_probs": _mh,
        "parallel_runtime": True,
        "stack_schema_version": PARALLEL_STACK_SCHEMA_VERSION,
    }


def run_cascade_models_once(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
    expected_data_fingerprint: str | None = None,
    actual_data_fingerprint: str | None = None,
    expected_feature_contract_version: str | None = None,
    expected_canonical_timeframe: str | None = None,
    lineage_extra: dict | None = None,
) -> dict:
    """
    Challenger-only **cascade** inference: XGB → LSTM (with XGB prob tensor) → Transformer
    (with XGB + LSTM prob tensors). Loads artifacts from ``models/cascade/{ticker}/`` only.

    Does **not** change production routing; use ``run_unified_stack_ml_once`` for live parallel stack.

    Lineage kwargs enforce parity with shared training cache when set (evaluation harness).
    """
    tkr = ticker or snapshot.get("ticker", "") or ""
    if not tkr:
        raise CascadeChallengerError("cascade challenger: empty ticker")

    validate_cascade_inference_lineage(
        inference_snapshot_v1,
        expected_data_fingerprint=expected_data_fingerprint,
        actual_data_fingerprint=actual_data_fingerprint,
        expected_feature_contract_version=expected_feature_contract_version,
        expected_canonical_timeframe=expected_canonical_timeframe,
    )
    assert_no_legacy_mvp_in_fusion_overlay(snapshot)

    def _parallel_model_output_record(p: Optional[dict], approved: bool) -> dict:
        r = build_unified_stack_layer_output(probs=p, approved=approved and p is not None)
        if r.get("available"):
            r["up"] = r["prob_up"]
            r["down"] = r["prob_down"]
            r["flat"] = r["prob_flat"]
            r["confidence"] = r["confidence_score"]
        else:
            r["up"] = None
            r["down"] = None
            r["flat"] = None
            r["confidence"] = None
            r["dominant"] = None
        return r

    with _cascade_challenger_inference_scope():
        xgb_p = _predict_xgb(inference_snapshot_v1, tkr, fusion_feature_overlay=snapshot)
        if xgb_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 1 (XGB) produced no probabilities")
        xgb_arr = _probs_dict_to_arr(xgb_p)

        lstm_p = _predict_lstm(
            tkr,
            db,
            snapshot=snapshot,
            xgb_probs_arr=xgb_arr,
            inference_snapshot_v1=inference_snapshot_v1,
            parallel_runtime=False,
        )
        if lstm_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 2 (LSTM) produced no probabilities")
        lstm_arr = _probs_dict_to_arr(lstm_p)

        tr_p = _predict_transformer(
            tkr,
            db,
            snapshot=snapshot,
            xgb_probs_arr=xgb_arr,
            lstm_probs_arr=lstm_arr,
            inference_snapshot_v1=inference_snapshot_v1,
            parallel_runtime=False,
        )
        if tr_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 3 (Transformer) produced no probabilities")

        fusion_pack = {
            "xgb": _model_probs_to_fusion_out(xgb_p, direction_hint),
            "lstm": _model_probs_to_fusion_out(lstm_p, direction_hint),
            "transformer": _model_probs_to_fusion_out(tr_p, direction_hint),
        }
        model_outputs = {
            "xgb": _parallel_model_output_record(xgb_p, True),
            "lstm": _parallel_model_output_record(lstm_p, True),
            "transformer": _parallel_model_output_record(tr_p, True),
        }

        stack_probs = None
        if _load_meta(tkr):
            stack_probs = _predict_meta(
                tkr,
                xgb_p,
                lstm_p,
                tr_p,
                meta_tabular_overlay=snapshot,
            )
        if stack_probs is None:
            stack_probs = _weighted_average(tkr, xgb_p, lstm_p, tr_p)

    lineage = build_cascade_challenger_run_metadata(
        data_fingerprint=actual_data_fingerprint,
        ml_horizon_slug=get_ml_infer_horizon_slug(),
    )
    if lineage_extra:
        lineage = {**lineage, **lineage_extra}

    stages = {
        "1_xgb": {
            "probabilities": xgb_p,
            "upstream_bundle_version": CASCADE_UPSTREAM_BUNDLE_VERSION,
        },
        "2_lstm": {
            "probabilities": lstm_p,
            "cascade_inputs_from_xgb_probs": [float(x) for x in xgb_arr.reshape(-1)],
        },
        "3_transformer": {
            "probabilities": tr_p,
            "cascade_inputs_from_xgb_probs": [float(x) for x in xgb_arr.reshape(-1)],
            "cascade_inputs_from_lstm_probs": [float(x) for x in lstm_arr.reshape(-1)],
        },
    }

    return {
        "architecture": "cascade",
        "schema_version": CASCADE_STACK_SCHEMA_VERSION,
        "parallel_runtime": False,
        "upstream_bundle_version": CASCADE_UPSTREAM_BUNDLE_VERSION,
        "fusion": fusion_pack,
        "model_outputs": model_outputs,
        stack_probs_bundle_key(): stack_probs,
        "stages": stages,
        "lineage": lineage,
    }


def get_model_outputs_for_fusion(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """
    Return structured outputs for fusion. Delegates to run_unified_stack_ml_once — single inference truth per tick.
    """
    tkr = ticker or snapshot.get("ticker", "") or ""
    if not tkr:
        return {"xgb": None, "lstm": None, "transformer": None}
    return run_unified_stack_ml_once(
        snapshot, tkr, db, direction_hint, inference_snapshot_v1=inference_snapshot_v1
    )["fusion"]


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_model_outputs(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """
    Run XGBoost, LSTM, Transformer individually and return availability,
    dominant direction, and confidence for each. Used for stack visibility
    in snapshots — does not affect prediction logic.

    Returns:
        {
            "xgb": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
            "lstm": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
            "transformer": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
        }
    """
    tkr = ticker or snapshot.get("ticker", "")
    if not tkr:
        return {
            "xgb": {"available": False, "dominant": None, "confidence": None, "approved": False},
            "lstm": {"available": False, "dominant": None, "confidence": None, "approved": False},
            "transformer": {"available": False, "dominant": None, "confidence": None, "approved": False},
        }
    return run_unified_stack_ml_once(
        snapshot, tkr, db, "wait", inference_snapshot_v1=inference_snapshot_v1
    )["model_outputs"]


def predict_direction(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> Optional[dict]:
    """
    Full stacked prediction.

    Runs XGBoost + LSTM + Transformer, combines via meta-learner (or
    weighted average if meta-learner not yet trained).

    Returns {up, down, flat} or None (caller uses rules engine).

    Args:
        snapshot: fusion overlay (pred_*, et_hour, …) — not used for MVP tabular fields
        ticker:   ticker symbol; uses snapshot['ticker'] if None
        db:       EdDB instance (needed for LSTM/Transformer sequence access)
        inference_snapshot_v1: required InferenceSnapshotV1 dict for XGB MVP path
    """
    tkr = ticker or snapshot.get("ticker", "")
    if not tkr:
        return None
    return run_unified_stack_ml_once(
        snapshot, tkr, db, "wait", inference_snapshot_v1=inference_snapshot_v1
    )[stack_probs_bundle_key()]


def predict_all_horizons(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """Predict for UI horizon keys; only the live ML product horizon runs the trained stack."""
    result = {}
    live_ml_hz = live_inference_horizon_slug()
    for hz in PRIMARY_DECISION_HORIZONS:
        result[hz] = (
            predict_direction(snapshot, ticker, db, inference_snapshot_v1=inference_snapshot_v1)
            if hz == live_ml_hz
            else None
        )
    return result


def is_available(ticker: str) -> bool:
    """True if ANY of xgb, LSTM, or Transformer model exists for this ticker."""
    hz = get_ml_infer_horizon_slug()
    base = _active_bundle_dir_for_load(ticker)
    if base is None:
        return False
    return (
        (base / f"xgb_{ticker}_{hz}.pkl").exists()
        or (base / f"lstm_{ticker}_{hz}.pt").exists()
        or (base / f"transformer_{ticker}_{hz}.pt").exists()
    )


def get_model_version(ticker: str) -> str:
    """Version string for dashboard display."""
    hz = get_ml_infer_horizon_slug()
    base = _active_bundle_dir_for_load(ticker)
    if base is None:
        return "rules_v1"
    parts = []
    if (base / f"xgb_{ticker}_{hz}.pkl").exists():        parts.append("xgb")
    if (base / f"lstm_{ticker}_{hz}.pt").exists():        parts.append("lstm")
    if (base / f"transformer_{ticker}_{hz}.pt").exists(): parts.append("tr")
    if (base / f"meta_{ticker}_{hz}.pkl").exists():       parts.append("meta")
    if parts:
        return f"stack({'_'.join(parts)})_{hz}"
    return "rules_v1"


def get_component_status(ticker: str) -> dict:
    """Which components are active. Used for dashboard health display."""
    return {
        "xgb":         "approved" if _load_xgb(ticker)       else "unavailable",
        "lstm":        "approved" if _load_lstm(ticker)      else "unavailable",
        "transformer": "approved" if _load_transformer(ticker) else "unavailable",
        "meta":        "loaded"   if _load_meta(ticker)     else "not trained yet",
        "stack_ready": _load_xgb(ticker) or _load_lstm(ticker) or _load_transformer(ticker),
    }


def reset_caches():
    """Clear all loaded models. Call this after retraining."""
    global _xgb_registry, _xgb_movehead_registry, _meta_registry, _lstm_registry, _trans_registry
    global _collapse_flag_registry, _active_bundle_dir_cache, _strict_bundle_warned
    _xgb_registry   = {}
    _xgb_movehead_registry = {}
    _meta_registry  = {}
    _lstm_registry  = {}
    _trans_registry = {}
    _collapse_flag_registry = {}
    _active_bundle_dir_cache = {}
    _strict_bundle_warned = set()
    logger.info("ml_predict: all model caches cleared")


def invalidate_model_registry(ticker: str, hz: str | None = None) -> bool:
    """Evict in-memory caches for one (ticker, horizon) tuple (PR4 P3-10)."""
    rk = _model_registry_key(ticker, hz)
    removed = False
    for reg in (_xgb_registry, _meta_registry, _lstm_registry, _trans_registry, _collapse_flag_registry):
        if rk in reg:
            del reg[rk]
            removed = True
    movehead_prefix = f"{rk}:"
    for key in list(_xgb_movehead_registry.keys()):
        if key == rk or key.startswith(movehead_prefix):
            del _xgb_movehead_registry[key]
            removed = True
    if removed:
        logger.info("ml_predict: invalidated registry for %s", rk)
    if rk in _active_bundle_dir_cache:
        del _active_bundle_dir_cache[rk]
        _strict_bundle_warned.discard(rk)
    return removed


def prewarm_inference_models_for_ticker(ticker: str) -> dict[str, bool]:
    """
    UI-MAXIMIZE — load XGB/LSTM/TR artifacts for all primary horizons into registries.
    Disk I/O only; no forward pass. Honors guest-anchor bundle routing when enabled.
    """
    from ml_horizon import PRIMARY_DECISION_HORIZONS
    from governed_stack_contract import (
        guest_anchor_context_scope,
        resolve_guest_anchor_for_ticker,
    )

    t = (ticker or "").upper().strip()
    if not t:
        return {}
    guest_ctx = resolve_guest_anchor_for_ticker(t)
    out: dict[str, bool] = {}
    with guest_anchor_context_scope(guest_ctx), ml_bundle_ticker_scope(
        guest_ctx.anchor_ticker if guest_ctx else None
    ):
        for hz in PRIMARY_DECISION_HORIZONS:
            tok = set_ml_infer_horizon_slug(hz)
            try:
                out[f"xgb_{hz}"] = _load_xgb(t)
                out[f"lstm_{hz}"] = _load_lstm(t)
                out[f"transformer_{hz}"] = _load_transformer(t)
            finally:
                reset_ml_infer_horizon_slug(tok)
    logger.info("prewarm_inference_models_for_ticker %s: %s", t, out)
    return out


def _fmt(p):
    if p is None: return "None"
    return f"up={p['up']:.2f} dn={p['down']:.2f} fl={p['flat']:.2f}"


# Deprecated aliases — mechanical lock: new code must use canonical names above.
run_base_models_once = run_unified_stack_ml_once
read_base_collapse_flags = read_stack_layer_collapse_flags
