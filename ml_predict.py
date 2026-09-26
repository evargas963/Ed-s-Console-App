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
import time
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Optional, Any

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    normalize_ml_horizon_slug,
)
# RC-345/F25: serving-side artifact/registry ticker identity delegates to the ONE
# canonical authority (same key the DB, cache, and on-disk $SPX bundle use). No local
# .upper() second faucet — bare 'SPX' and '$SPX' resolve to the identical bundle.
from instrument_identity import ticker_storage_key

from features.lstm_sequence_input import (
    LstmSequenceInputError,
    TransformerSequenceInputError,
    build_transformer_merged_window,
)
from features.xgb_model_input import XgbInferenceInputError
from features.cascade_stack_contract import (
    CascadeChallengerError,
)

logger = logging.getLogger("ed_console.ml")


class ParallelRuntimeArtifactError(ValueError):
    """Loaded artifact expects cascade (upstream model) tensors; parallel runtime forbids that coupling."""

# "parallel" = production default; "cascade" = challenger challenger inference scope (models/cascade/{ticker}/).
_INFER_ARCHITECTURE: ContextVar[str] = ContextVar("ml_predict_infer_architecture", default="parallel")


def _reg_key(ticker: str) -> str:
    return f"{_INFER_ARCHITECTURE.get()}:{ticker_storage_key(ticker)}"


def _model_registry_key(ticker: str, hz: str | None = None) -> str:
    """
    In-memory cache key for base stack models (XGB / LSTM / Transformer / meta).

    Must include horizon slug so each governed horizon loads its own artifact
    (xgb_{TICKER}_{hz}.pkl, etc.) — not reused across horizons.
    """
    bt = _bundle_ticker_for_artifacts(ticker)
    su = normalize_ml_horizon_slug(hz) if hz is not None else get_ml_infer_horizon_slug()
    return f"{_reg_key(bt)}:{su}"




# Scheduler / eval sets this when loading non-1c artifacts from a candidate directory.
_ml_infer_horizon_cv: ContextVar[str] = ContextVar(
    "ml_infer_horizon_slug", default=DEFAULT_ML_HORIZON_SLUG
)

# Guest anchor: load promoted weights from anchor ticker while features stay on guest ticker.
_ml_bundle_ticker_cv: ContextVar[str | None] = ContextVar("ml_bundle_ticker_override", default=None)




def _bundle_ticker_for_artifacts(feature_ticker: str) -> str:
    override = _ml_bundle_ticker_cv.get()
    if override:
        return override  # already canonical: set via ticker_storage_key in ml_bundle_ticker_scope
    return ticker_storage_key(feature_ticker or "")


def get_ml_infer_horizon_slug() -> str:
    return normalize_ml_horizon_slug(_ml_infer_horizon_cv.get())




def set_ml_infer_horizon_slug(slug: str) -> Token:
    return _ml_infer_horizon_cv.set(normalize_ml_horizon_slug(slug))


def reset_ml_infer_horizon_slug(token: Token) -> None:
    _ml_infer_horizon_cv.reset(token)




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
# Serving-contract verdict per (ticker, hz) for stack_probs_composition_record. That verdict costs
# a sha256 sweep of seven artifacts plus a torch.load of both sequence checkpoints and a pickle
# load of the meta stack — measured 0.050-0.055 s per (ticker, horizon). The record is consulted
# once per horizon per ticker per refresh, so calling it uncached put ~10 s of synchronous CPU on
# every 58-symbol sweep, directly on the /api/state latency that card_freshness_v1 turns into
# STALE cards. Cached with the SAME lifetime as _active_bundle_dir_cache and evicted from the same
# three places (reset_caches, invalidate_model_registry, the per-key provenance eviction below),
# so a promotion or retrain can never be served a stale compliance verdict.
_bundle_contract_cache: dict[str, dict] = {}
# ML-PIPE Item 4 — verification provenance per f"{registry_key}|{artifact_role}".
# Records the exact manifest + artifact identity every governed load was verified
# against (or the fail-closed reason), and the stat identity used by the
# staleness guard so a cached model cannot outlive artifact/manifest mutation.
_artifact_verification_registry: dict[str, dict] = {}


# ML-PIPE Item 4 §6: stat (size+mtime_ns) invalidation cannot detect a mutation
# that preserves both fields. Cached verification therefore expires after this
# TTL and the next access performs a FULL re-hash against the manifest, bounding
# the undetected-mutation window to the TTL instead of process lifetime.
ARTIFACT_REVERIFY_TTL_ENV = "ED_ARTIFACT_REVERIFY_TTL_SECONDS"
_ARTIFACT_REVERIFY_TTL_DEFAULT = 900.0


def _artifact_reverify_ttl_seconds() -> float:
    raw = os.environ.get(ARTIFACT_REVERIFY_TTL_ENV, "").strip()
    try:
        val = float(raw)
    except ValueError:
        return _ARTIFACT_REVERIFY_TTL_DEFAULT
    return val if val > 0 else _ARTIFACT_REVERIFY_TTL_DEFAULT


def _record_artifact_verification(rk: str, role: str, prov: dict) -> None:
    prov["verified_at_epoch"] = time.time()
    _artifact_verification_registry[f"{rk}|{role}"] = prov


def _verify_governed_artifact(base: Path, bt: str, hz: str, role: str, filename: str) -> dict | None:
    """
    Canonical pre-deserialization integrity boundary for serve-path model loads.

    Verifies artifact bytes against the bundle integrity manifest BEFORE any
    pickle/torch deserialization. Every governed failure fails closed and is
    recorded with a stable reason code. Returns provenance on success, None when
    the load must be refused.

    ABSENT MANIFEST (RC-377 F3 correction, 2026-08-15): this docstring used to say
    absence yields legacy provenance "unless ED_ARTIFACT_INTEGRITY_STRICT=1", and
    that sentence misled two independent audits into recording a hole that is not
    open. The environment flag is NOT the only lever and is no longer the operative
    one. `artifact_integrity_strict_absence()` resolves the COMMITTED policy in
    config/ML_ITEM4_MIGRATION_POLICY.json, which carries strict_default=true
    with legacy_allowance.enabled=false, expired 2026-07-12. Measured: strict is
    True with the flag unset, AND True at ED_ARTIFACT_INTEGRITY_STRICT=0 — once the
    allowance is disabled the environment cannot reopen legacy serving. So a bundle
    with no manifest RAISES MANIFEST_MISSING and the load is refused today. Legacy
    provenance is reachable only if the committed policy is changed to re-enable an
    unexpired allowance, which is an operator-lane commit.
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
    when a legacy bundle gained a manifest, or when the verification is older
    than the re-verify TTL (Item 4 §6: a mutation preserving both size and
    mtime_ns escapes stat detection, so cached trust expires and the next
    access re-hashes — the undetected-mutation window is bounded by the TTL,
    not the process lifetime). Eviction triggers a full re-verify; a negative
    entry never flips positive without recomputing the hash.
    """
    prefix = f"{rk}|"
    provs = [p for k, p in _artifact_verification_registry.items() if k.startswith(prefix)]
    if not provs:
        return False
    stale = False
    now = time.time()
    ttl = _artifact_reverify_ttl_seconds()
    for prov in provs:
        verified_at = prov.get("verified_at_epoch")
        if not isinstance(verified_at, (int, float)) or now - verified_at >= ttl:
            stale = True  # TTL expiry (or missing timestamp) -> full re-hash
            break
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
    _bundle_contract_cache.pop(rk, None)
    _strict_bundle_warned.discard(rk)



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






def _enforce_active_serve_policy(bt: str, hz: str, bundle_dir: Path) -> None:
    """Cursor-audit F10: the MODEL-04 vintage gate. Raise FileNotFoundError if the active bundle at
    bundle_dir is serve-blocked (WITHHELD / NOT_PROVEN provenance). Applied on EVERY path that serves
    the active canonical bundle — strict AND relaxed — so ED_XGB_STRICT_ACTIVE_ONLY=0 can no longer
    serve a policy-withheld vintage (its bytes hash-verify against their own manifest, so Layer-2
    integrity alone would pass it). Never a silent substitute: the block carries the explicit reason."""
    from model_serve_policy import bundle_serve_eligibility

    _elig = bundle_serve_eligibility(bt, hz, bundle_dir)
    if _elig["direct_serve_blocked"]:
        raise FileNotFoundError(
            f"MODEL_SERVE_POLICY {_elig['status']} for {bt} hz={hz} at {bundle_dir}: "
            f"{_elig['reason']}"
        )


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
        # MODEL-04 serve policy (operator-approved 2026-07-10): a complete bundle must ALSO be
        # serve-eligible by manifest vintage. Withheld/unproven provenance fails closed with the
        # explicit reason (anchor routing resolves upstream via _bundle_ticker_for_artifacts).
        _enforce_active_serve_policy(bt, hz, canonical)
        return canonical
    # Cursor-audit F10: the MODEL-04 vintage gate is NOT strict-mode-only. With
    # ED_XGB_STRICT_ACTIVE_ONLY=0 the relaxed resolver can STILL land on the active canonical bundle
    # (models/active/*), whose bytes hash-verify against their own manifest — so a policy-WITHHELD or
    # NOT_PROVEN vintage would load and serve real direction signals with no block. Apply the same
    # gate whenever the resolved dir IS the active bundle; parallel/cascade/flat dev experiments (the
    # flag's intended probing use) are not the active bundle and are untouched.
    resolved = _model_dir_for_ticker_relaxed(bt, hz)
    if str(resolved).startswith(str(MODEL_DIR / "active")):
        _enforce_active_serve_policy(bt, hz, resolved)
    return resolved


def _model_dir_for_ticker_relaxed(ticker: str, hz: str) -> Path:
    """Non-strict resolution: cascade challenger, arch_state, or parallel default."""
    ticker = ticker_storage_key(ticker)  # RC-345/F25: callee consumes canonical directly (no caller masking)
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


def _never_trained_ticker(ticker: str, hz: str) -> bool:
    """True when NO active bundle directory exists for (ticker, horizon) — RC-244.

    The discriminator between "the operator enrolled this symbol for quotes and never trained
    it" and "this symbol's model is broken". Only the first is a configuration state; the
    second is a defect and must keep its WARNING. Deliberately asks the filesystem rather than
    the exception text, because the message wording is not a contract. Fail-closed: if the
    path cannot be resolved at all, report False so the louder branch wins.
    """
    try:
        from active_bundle_contract import active_bundle_dir

        return not active_bundle_dir(
            _bundle_ticker_for_artifacts(ticker), hz, models_dir=MODEL_DIR
        ).exists()
    except Exception:  # institutional-swallow-ok: severity choice must never mask the event; unresolvable path falls through to WARNING
        return False


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
            # RC-244: absence-by-CHOICE and absence-by-BREAKAGE arrive as the same exception,
            # and they are not the same event. A ticker enrolled for market data that was
            # never trained has NO bundle directory — that is a configuration state the
            # operator chose, and logging it as a failure every serve makes the channel
            # unreadable (it was the sole cause of the quiet-window FAIL for AMD). A ticker
            # whose bundle EXISTS but fails the strict contract is a genuine regression and
            # keeps its WARNING untouched — the PM's order forbids demoting that, and the
            # existing fail-closed test asserts it. Serve is skipped identically either way;
            # only the severity differs, and the reason is stated in the line itself.
            if _never_trained_ticker(ticker, hz):
                logger.info(
                    "No active ML bundle for %s hz=%s — ticker is enrolled for market data "
                    "but has never been trained; ML serve skipped (not a failure)",
                    ticker,
                    hz,
                )
            else:
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
        from ml_train import (
            apply_xgb_imputation_matrix,
            engineer_single_snapshot,
            engineered_features_missing_withheld_wall_distances,
            should_abstain_missing_session_vwap_for_cf,
        )

        if xgb_pre_engineering_snapshot is not None:
            snap = _apply_serve_ablation_snapshot(dict(xgb_pre_engineering_snapshot), "xgb")
        else:
            # RC-336: ONE preparation sequence. This branch used to re-implement it inline
            # and omitted `attach_confluence_features_for_serve`, so whenever a caller did
            # not pass a pre-built snapshot the six cf_* keys were simply absent — and
            # `engineer_single_snapshot` turns an absent cf_* into 0.0, i.e. "confluence
            # measured, and it is exactly flat". Training supplies real confluence for those
            # same columns, so every prediction down this branch fed the model a vector the
            # model was never trained on. Delegating means the sequence cannot be partially
            # reproduced again: net_gamma_prev, confluence and serve ablation are whatever
            # the one preparer says they are.
            snap = build_xgb_pre_engineering_snapshot_for_tick(
                inference_snapshot_v1, fusion_feature_overlay)
        X = engineer_single_snapshot(
            snapshot=snap,
            category_maps=reg["category_maps"],
            feature_names=reg["feature_names"],
            vol_medians=reg["vol_medians"],
            ticker=_bundle_ticker_for_artifacts(ticker),
        )
        if X is None:
            return None
        x_raw = X.values.astype(np.float64)
        # RC-435 / F4: OI/vanna wall distances are structurally withheld live (RC-422).
        # Median impute / nan_to_num would invent proximity the producer refused.
        if engineered_features_missing_withheld_wall_distances(
            x_raw[0], reg["feature_names"]
        ):
            logger.info(
                "XGBoost %s: abstain — structurally withheld OI/vanna wall distance missing",
                ticker,
            )
            return None
        if should_abstain_missing_session_vwap_for_cf(
            session_vwap=snap.get("vwap"),
            feature_names=reg["feature_names"],
        ):
            logger.info(
                "XGBoost %s: abstain — session VWAP absent while feature contract "
                "includes cf_vwap_distance_pct",
                ticker,
            )
            return None
        impute = reg["meta"].get("impute_medians") or {}
        x_mat = apply_xgb_imputation_matrix(
            x_raw,
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
    mtp = base / f"lstm_{bt}_{hz}_meta.json"
    if not mp.exists():
        logger.debug("LSTM model not found for %s (bundle=%s) at %s", ticker, bt, mp)
        _lstm_registry[rk] = None
        return False
    if not mtp.exists():
        logger.error("LSTM %s: missing meta %s; refusing load.", ticker, mtp.name)
        _lstm_registry[rk] = None
        return False

    # Item 4 (RC-376 port of a107412): verify checkpoint + meta bytes vs bundle
    # integrity manifest BEFORE load_lstm reads lstm_*_meta.json — the same
    # pre-deserialization boundary xgb_meta / transformer_meta already have.
    if (
        _verify_governed_artifact(base, bt, hz, "lstm", mp.name) is None
        or _verify_governed_artifact(base, bt, hz, "lstm_meta", mtp.name) is None
    ):
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
            CONFLUENCE_FEATURES,
            FEATURES_5M,
            LEGACY_ENCODER_SCHEMA_VERSION,
            LEGACY_V2_FEATURES_5M,
            STREAM_5M_LOOKBACK,
            STREAM_1M_LOOKBACK,
            assert_lstm_encoder_checkpoint_compatible,
            canonical_reference_spot_from_merged_window,
            checkpoint_encoder_schema_version,
            encoded_width_5m_for_checkpoint,
            encoded_width_1m_for_checkpoint,
            micro_reference_spot_from_window,
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

        # RC-435 / F4: refuse zero-fill of structurally withheld OI/vanna wall distances.
        from ml_train import snapshot_missing_structurally_withheld_wall_distances

        _seq_feats = (
            LEGACY_V2_FEATURES_5M
            if checkpoint_encoder_schema_version(checkpoint) == LEGACY_ENCODER_SCHEMA_VERSION
            else FEATURES_5M
        )
        if snapshot_missing_structurally_withheld_wall_distances(
            merged_window[-1], _seq_feats
        ):
            logger.info(
                "LSTM %s: abstain — structurally withheld OI/vanna wall distance missing",
                ticker,
            )
            return None

        from ml_train import should_abstain_missing_session_vwap_for_cf

        _cf_idx = CONFLUENCE_FEATURES.index("cf_vwap_distance_pct")
        _mask_conf_probe = np.array(
            checkpoint.get("mask_conf", [True] * len(CONFLUENCE_FEATURES)),
            dtype=bool,
        )
        _consumes_cf_vwap = (
            _cf_idx < _mask_conf_probe.shape[0] and bool(_mask_conf_probe[_cf_idx])
        )
        # Authorization uses the current-tick session VWAP only. merged_window[-1]
        # is the last causal history bar (as_of exclusive), not the decision
        # generation — its vwap can be a prior row / prior session.
        _sess_vwap = None
        if snapshot is not None:
            _sess_vwap = snapshot.get("vwap") if isinstance(snapshot, dict) else getattr(snapshot, "vwap", None)
        if should_abstain_missing_session_vwap_for_cf(
            session_vwap=_sess_vwap,
            consumes_cf_vwap=_consumes_cf_vwap,
        ):
            logger.info(
                "LSTM %s: abstain — session VWAP absent while confluence contract "
                "includes cf_vwap_distance_pct",
                ticker,
            )
            return None

        seq_5m = [
            encode_lstm_structure_sequence_bar_for_checkpoint(s, ref_spot, checkpoint)
            for s in merged_window
        ]
        micro = merged_window[-STREAM_1M_LOOKBACK:]
        # RC-318: single typed-absence producer (None/NaN/<=0 tested -> validated ref_spot;
        # the old `_safe_float(...) or ref_spot` let a truthy NaN through as the reference).
        mr = micro_reference_spot_from_window(micro, ref_spot)
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

        # RC-332: cf_* comes from the single population authority, not from this lane's
        # merged window. `merged_days` is masked and merged for SEQUENCE encoding; using it
        # as confluence history made the live LSTM read a different population than offline
        # training, which diverged on 179 of 4956 sampled cells (cf_alignment_score by up to
        # 3.0 of its -4..+4 range). The bar is this lane's; the history is canonical.
        from ml_data_common import confluence_features_for_bar
        from ml_train import DB_PATH as _conf_db

        conf = confluence_features_for_bar(
            ticker, merged_days[-1].get("ts_utc") if merged_days else None, _conf_db)
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
            FEATURES_5M,
            LEGACY_ENCODER_SCHEMA_VERSION,
            LEGACY_V2_FEATURES_5M,
            assert_lstm_encoder_checkpoint_compatible,
            canonical_reference_spot_from_merged_window,
            checkpoint_encoder_schema_version,
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

        # RC-435 / F4: same withheld-distance abstain as LSTM (encode→nan_to_num would invent 0).
        from ml_train import snapshot_missing_structurally_withheld_wall_distances

        _seq_feats = (
            LEGACY_V2_FEATURES_5M
            if checkpoint_encoder_schema_version(checkpoint) == LEGACY_ENCODER_SCHEMA_VERSION
            else FEATURES_5M
        )
        if snapshot_missing_structurally_withheld_wall_distances(
            merged_window[-1], _seq_feats
        ):
            logger.info(
                "Transformer %s: abstain — structurally withheld OI/vanna wall distance missing",
                ticker,
            )
            return None

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
    # Role must be the governed META_STACK_KIND ("meta_stack") — the role the
    # manifest stamper records for meta_{ticker}_{hz}.pkl. Requesting "meta"
    # was rejected as an unknown role and failed the meta layer closed
    # fleet-wide (2026-07-16 regression).
    from active_bundle_contract import META_STACK_KIND

    if _verify_governed_artifact(base, bt, hz, META_STACK_KIND, mp.name) is None:
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


def _ensemble_parallel_probs_with_execution(
    ticker: str,
    xgb_p: Optional[dict],
    lstm_p: Optional[dict],
    trans_p: Optional[dict],
    *,
    meta_tabular_overlay: dict | None = None,
) -> tuple[Optional[dict], str | None]:
    """Return probabilities plus the computation that actually produced them.

    A base flagged ``val_single_class_collapse`` is degenerate (all-flat); the meta is
    re-fit clean against it on retrain (see ml_scheduler._assemble_meta_base_prob_vectors),
    so the meta path needs no row-time change EXCEPT the all-collapsed guard below. The
    weighted-average fallback drops collapsed bases.
    """
    if not _parallel_base_stack_complete(xgb_p, lstm_p, trans_p):
        return None, None
    collapsed = _active_base_collapse_flags(ticker)
    if collapsed >= {"xgb", "lstm", "transformer"}:
        logger.warning(
            "Parallel combiner %s: all three bases single-class-collapsed — uniform (not false-flat)",
            ticker,
        )
        return dict(_UNIFORM_PROBS), "all_collapsed_uniform"
    stack_probs = _predict_meta(
        ticker,
        xgb_p,
        lstm_p,
        trans_p,
        meta_tabular_overlay=meta_tabular_overlay,
    )
    if stack_probs is not None:
        return stack_probs, "meta_stack"
    stack_probs = _weighted_average(ticker, xgb_p, lstm_p, trans_p, collapsed=collapsed)
    return stack_probs, ("weighted_average_fallback" if stack_probs is not None else None)


def _ensemble_parallel_probs(
    ticker: str,
    xgb_p: Optional[dict],
    lstm_p: Optional[dict],
    trans_p: Optional[dict],
    *,
    meta_tabular_overlay: dict | None = None,
) -> Optional[dict]:
    """Compatibility wrapper for callers that do not consume computation provenance."""
    probs, _executed = _ensemble_parallel_probs_with_execution(
        ticker,
        xgb_p,
        lstm_p,
        trans_p,
        meta_tabular_overlay=meta_tabular_overlay,
    )
    return probs




# ══════════════════════════════════════════════════════════════════════════════
# FUSION API — model outputs with probabilities for bayesian_fusion
# ══════════════════════════════════════════════════════════════════════════════










# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════















def reset_caches():
    """Clear all loaded models. Call this after retraining."""
    global _xgb_registry, _xgb_movehead_registry, _meta_registry, _lstm_registry, _trans_registry
    global _collapse_flag_registry, _active_bundle_dir_cache, _strict_bundle_warned
    global _bundle_contract_cache
    _xgb_registry   = {}
    _xgb_movehead_registry = {}
    _meta_registry  = {}
    _lstm_registry  = {}
    _trans_registry = {}
    _collapse_flag_registry = {}
    _active_bundle_dir_cache = {}
    _bundle_contract_cache = {}
    _strict_bundle_warned = set()
    logger.info("ml_predict: all model caches cleared")








