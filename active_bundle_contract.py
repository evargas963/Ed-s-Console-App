"""Shared active-bundle completeness contract (G3-R1).

Single definition used by verify_active_models and ml_predict strict resolution.
PR3 (P2-1): canonical active root = scheduler_active_root(hz) only.

ML-PIPE Item 4 (artifact-manifest load verification): this module is also the
single owner of the bundle integrity manifest written at promotion time and the
canonical pre-deserialization verification boundary
(``verify_artifact_against_manifest``). Loaders must verify artifact bytes
against the bundle integrity manifest BEFORE ``pickle.load`` / ``torch.load``.
Hash verification proves integrity relative to the trusted manifest and identity
contract only — it does not make arbitrary pickle files generically safe.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug
from instrument_identity import ticker_storage_key


def artifact_ticker_key(ticker: str) -> str:
    """RC-345 / F25: THE one canonical ticker identity for model-artifact / bundle-dir keys —
    delegates to instrument_identity.ticker_storage_key (the SAME authority the DB storage key
    uses), so a model directory can never independently normalize a ticker differently from the
    row storage. For the production ETF universe (SPY/QQQ/IWM) this equals the uppercased root;
    for a $-indexed root it yields the $-prefixed canonical key ($SPX). This does NOT
    independently decide ticker truth — it is a delegation to the one authority. Legacy note:
    the $-indexed bundles on disk are ALREADY stored under the canonical $-prefixed identity
    (e.g. models/active/$SPX/), so routing a bare index root here RESOLVES to the existing
    artifact rather than orphaning it — no dual-read shim is required."""
    return ticker_storage_key(ticker)

MODELS_DIR = Path(__file__).resolve().parent / "models"
ACTIVE_DIR = MODELS_DIR / "active"

# (model_kind, model_file, meta_file) per horizon bundle — six ML layer artifact pairs + meta-stack pkl.
BUNDLE_ARTIFACT_TRIPLE = (
    ("xgb", "xgb_{ticker}_{hz}.pkl", "xgb_{ticker}_{hz}_meta.json"),
    ("lstm", "lstm_{ticker}_{hz}.pt", "lstm_{ticker}_{hz}_meta.json"),
    ("transformer", "transformer_{ticker}_{hz}.pt", "transformer_{ticker}_{hz}_meta.json"),
)
META_STACK_KIND = "meta_stack"
META_STACK_MODEL_PATTERN = "meta_{ticker}_{hz}.pkl"

# ══════════════════════════════════════════════════════════════════════════════
# ML-PIPE Item 4 — bundle integrity manifest + canonical verification boundary
# ══════════════════════════════════════════════════════════════════════════════

BUNDLE_INTEGRITY_MANIFEST_FILENAME = "bundle_integrity_manifest.json"
BUNDLE_INTEGRITY_SCHEMA_VERSION = 1
# Operator lever: 1 = manifest absence fails closed even for MODEL-04-authorized
# legacy bundles (default 0 preserves the operator-approved MODEL-04 serve set,
# with explicit LEGACY_UNVERIFIED provenance instead of silence).
ARTIFACT_INTEGRITY_STRICT_ENV = "ED_ARTIFACT_INTEGRITY_STRICT"

# Stable machine-readable verification failure reasons (single owner — do not
# duplicate this vocabulary elsewhere). Codes marked (owner: X) are part of the
# governed vocabulary but raised/enforced by the named existing authority to
# avoid a duplicate truth source:
#   FEATURE_SCHEMA_MISMATCH        (owner: model_contract.validate_artifact_contract)
#   TRAINING_CUTOFF_MISMATCH       (owner: model_serve_policy MODEL-04 vintage gate)
#   CALIBRATION_IDENTITY_MISMATCH  (owner: calibration a1 artifact loaders, run-id pinned)
#   CURRENT_POINTER_FOR_HISTORICAL_REPLAY (owner: scheduler eval MODEL_DIR pin +
#       no-current-pointer lock @ tests/test_shuffled_label_control_v1.py)
ARTIFACT_VERIFICATION_FAILURE_REASONS: tuple[str, ...] = (
    "MANIFEST_MISSING",
    "MANIFEST_UNREADABLE",
    "MANIFEST_MALFORMED",
    "MANIFEST_VERSION_UNSUPPORTED",
    "ARTIFACT_ENTRY_MISSING",
    "ARTIFACT_FILE_MISSING",
    "ARTIFACT_UNREADABLE",
    "EXPECTED_HASH_INVALID",
    "ARTIFACT_HASH_MISMATCH",
    "ARTIFACT_PATH_OUTSIDE_BUNDLE",
    "TICKER_IDENTITY_MISMATCH",
    "HORIZON_IDENTITY_MISMATCH",
    "MODEL_IDENTITY_MISMATCH",
    "ARTIFACT_ROLE_MISMATCH",
    "FEATURE_SCHEMA_MISMATCH",
    "TRAINING_CUTOFF_MISMATCH",
    "CALIBRATION_IDENTITY_MISMATCH",
    "BUNDLE_IDENTITY_MISMATCH",
    "FOLD_IDENTITY_MISMATCH",
    "LEGACY_ARTIFACT_NOT_GOVERNED",
    "CURRENT_POINTER_FOR_HISTORICAL_REPLAY",
    "VERIFICATION_CACHE_STALE",
    "VERIFICATION_PROVENANCE_MISSING",
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# role -> filename pattern for one (ticker, hz) bundle; single source of the
# governed artifact-role vocabulary (derived from BUNDLE_ARTIFACT_TRIPLE).
_BUNDLE_ROLE_PATTERNS: dict[str, str] = {
    "xgb": "xgb_{ticker}_{hz}.pkl",
    "xgb_meta": "xgb_{ticker}_{hz}_meta.json",
    "lstm": "lstm_{ticker}_{hz}.pt",
    "lstm_meta": "lstm_{ticker}_{hz}_meta.json",
    "transformer": "transformer_{ticker}_{hz}.pt",
    "transformer_meta": "transformer_{ticker}_{hz}_meta.json",
    META_STACK_KIND: META_STACK_MODEL_PATTERN,
}
# Optional governed artifacts (XGB movement heads) — not part of the required
# 7-file bundle contract; hashed into the integrity manifest when present at
# stamping time and verified with the same fail-closed boundary when loaded.
_OPTIONAL_BUNDLE_ROLE_PATTERNS: dict[str, str] = {
    "xgb_dir": "xgb_{ticker}_{hz}_dir.pkl",
    "xgb_dir_meta": "xgb_{ticker}_{hz}_dir_meta.json",
    "xgb_move": "xgb_{ticker}_{hz}_move.pkl",
    "xgb_move_meta": "xgb_{ticker}_{hz}_move_meta.json",
}


class ArtifactVerificationError(ValueError):
    """Fail-closed artifact-integrity violation with a stable machine-readable reason."""

    def __init__(self, reason_code: str, detail: str, *, identity: dict[str, Any] | None = None):
        if reason_code not in ARTIFACT_VERIFICATION_FAILURE_REASONS:
            raise ValueError(f"unknown artifact verification reason code: {reason_code!r}")
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail
        self.identity = dict(identity or {})


MIGRATION_POLICY_PATH = Path(__file__).resolve().parent / "governance" / "ML_ITEM4_MIGRATION_POLICY.json"


def _load_migration_policy() -> dict[str, Any] | None:
    """Committed Item-4 migration policy; None on missing/malformed (callers fail closed)."""
    try:
        doc = json.loads(MIGRATION_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _legacy_allowance_open(policy: dict[str, Any] | None) -> bool:
    """True only while the committed policy's legacy allowance is enabled AND unexpired."""
    if not policy:
        return False
    allowance = policy.get("legacy_allowance")
    if not isinstance(allowance, dict) or allowance.get("enabled") is not True:
        return False
    expires = allowance.get("expires_at_utc")
    if not isinstance(expires, str):
        return False
    try:
        exp = datetime.fromisoformat(expires)
    except ValueError:
        return False
    return datetime.now(timezone.utc) < exp


def artifact_integrity_strict_absence() -> bool:
    """True when manifest absence must fail closed (ML-PIPE Item 4 strict mode).

    The environment flag is NOT the only mechanism — the committed migration
    policy is the repository-side default:
      * ED_ARTIFACT_INTEGRITY_STRICT=1 -> always strict (operator hard lever).
      * ED_ARTIFACT_INTEGRITY_STRICT=0 -> honored ONLY while the committed
        policy's legacy allowance is enabled and unexpired; once the allowance
        is disabled or expired the environment cannot reopen legacy serving.
      * unset -> policy strict_default; a missing or malformed policy file is
        strict (fail closed), never permissive.
    """
    env = os.environ.get(ARTIFACT_INTEGRITY_STRICT_ENV, "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    policy = _load_migration_policy()
    if env in ("0", "false", "no"):
        return not _legacy_allowance_open(policy)
    if policy is None:
        return True
    return policy.get("strict_default") is not False


def bundle_integrity_manifest_path(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / BUNDLE_INTEGRITY_MANIFEST_FILENAME


def bundle_role_filenames(ticker: str, hz: str, *, include_optional: bool = False) -> dict[str, str]:
    """{artifact_role: canonical filename} for one (ticker, horizon) bundle."""
    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    patterns: dict[str, str] = dict(_BUNDLE_ROLE_PATTERNS)
    if include_optional:
        patterns.update(_OPTIONAL_BUNDLE_ROLE_PATTERNS)
    return {role: pat.format(ticker=t, hz=su) for role, pat in patterns.items()}


def _contained_artifact_path(bundle_dir: Path, artifact_filename: str, identity: dict[str, Any]) -> Path:
    """Resolve artifact_filename inside bundle_dir; reject traversal/substitution."""
    name = str(artifact_filename)
    # Reject both separator styles explicitly: on POSIX a backslash is a legal
    # filename character, so Path(name).name alone would let "..\\evil.pkl"
    # through on Linux CI while Windows treats it as traversal.
    if not name or "/" in name or "\\" in name or Path(name).name != name or name in (".", ".."):
        raise ArtifactVerificationError(
            "ARTIFACT_PATH_OUTSIDE_BUNDLE",
            f"artifact filename must be a bare basename inside the bundle (got {name!r})",
            identity=identity,
        )
    bd = Path(bundle_dir).resolve()
    resolved = (bd / name).resolve()
    if resolved.parent != bd:
        raise ArtifactVerificationError(
            "ARTIFACT_PATH_OUTSIDE_BUNDLE",
            f"{name!r} escapes bundle dir {bd}",
            identity=identity,
        )
    return resolved


def write_bundle_integrity_manifest(
    bundle_dir: Path,
    ticker: str,
    hz: str,
    *,
    source_run_manifest: dict | None = None,
    allow_missing_required: bool = False,
) -> dict[str, Any]:
    """
    Stamp the bundle integrity manifest for one promoted (ticker, horizon) bundle.

    Hashes the artifact bytes that live in ``bundle_dir`` (what will be served is
    what is hashed) and binds ticker/horizon/role identity plus the training-run
    lineage from the candidate ``scheduler_run_manifest.json`` when available.

    ``allow_missing_required`` exists ONLY for the Item-4 fleet migration's
    reconstruction of INCOMPLETE legacy bundles: present files get pinned while
    the missing files stay visible to the completeness contract, which keeps the
    bundle fail-closed for serving. Promotion stamping never sets this.
    """
    from training_cache import file_sha256_hex

    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    bd = Path(bundle_dir)
    required = bundle_role_filenames(t, su)
    optional_roles = set(bundle_role_filenames(t, su, include_optional=True)) - set(required)
    artifacts: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    for role, name in bundle_role_filenames(t, su, include_optional=True).items():
        p = bd / name
        if not p.is_file():
            if role in optional_roles:
                continue  # movement heads are optional bundle members
            if allow_missing_required:
                missing_required.append(name)
                continue
            raise ArtifactVerificationError(
                "ARTIFACT_FILE_MISSING",
                f"cannot stamp integrity manifest: {name} missing in {bd}",
                identity={"ticker": t, "horizon": su, "artifact_role": role},
            )
        artifacts[name] = {
            "role": role,
            "sha256": file_sha256_hex(p),
            "bytes": p.stat().st_size,
        }
    if allow_missing_required and not artifacts:
        raise ArtifactVerificationError(
            "ARTIFACT_FILE_MISSING",
            f"cannot stamp integrity manifest: no governed artifacts present in {bd}",
            identity={"ticker": t, "horizon": su, "artifact_role": "*"},
        )

    src = source_run_manifest if isinstance(source_run_manifest, dict) else None
    lineage_keys = (
        "scheduler_cache_key",
        "feature_cache_key",
        "training_code_fingerprint",
        "trained_at",
        "feature_version",
        "feature_schema_version",
        "label_version",
        "label_config_version",
        "pipeline_version",
        "data_start",
        "data_end",
        "row_count",
    )
    source_lineage: dict[str, Any] = (
        {k: src.get(k) for k in lineage_keys if src.get(k) is not None}
        if src
        else {"source_manifest_absent": True}
    )

    manifest: dict[str, Any] = {
        "schema_version": BUNDLE_INTEGRITY_SCHEMA_VERSION,
        "ticker": t,
        "ml_horizon_slug": su,
        "bundle_key": f"{t}:{su}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "source_lineage": source_lineage,
    }
    if allow_missing_required and missing_required:
        # Visible record of the incompleteness: present files are pinned, the
        # bundle stays non-servable via the completeness contract.
        manifest["missing_required_artifacts"] = sorted(missing_required)
    bundle_integrity_manifest_path(bd).write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    return manifest


def refresh_bundle_integrity_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    """
    Re-stamp the integrity manifest after a governed in-place write to an active
    bundle (e.g. movement-head training tools). Identity (ticker/horizon) comes
    from the existing manifest; its source lineage is preserved. No-op (returns
    None) when the bundle has no integrity manifest — legacy bundles stay
    explicitly legacy rather than gaining a manifest that would launder
    unpromoted artifacts as verified.
    """
    bd = Path(bundle_dir)
    existing = load_bundle_integrity_manifest(bd)
    if existing is None:
        return None
    lineage = existing.get("source_lineage")
    provenance = existing.get("provenance")
    manifest = write_bundle_integrity_manifest(
        bd,
        existing["ticker"],
        existing["ml_horizon_slug"],
        allow_missing_required=bool(existing.get("missing_required_artifacts")),
    )
    rewrite = False
    if isinstance(lineage, dict):
        manifest["source_lineage"] = lineage
        rewrite = True
    if isinstance(provenance, dict):
        # Migration provenance (repromotion/reconstruction evidence) survives
        # governed in-place refreshes — it names how trust was established.
        manifest["provenance"] = provenance
        rewrite = True
    if rewrite:
        bundle_integrity_manifest_path(bd).write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
    return manifest


def load_bundle_integrity_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    """
    Strict integrity-manifest read: absent -> None (caller applies absence policy);
    unreadable / malformed / unsupported schema -> fail closed (never legacy).
    """
    p = bundle_integrity_manifest_path(bundle_dir)
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactVerificationError(
            "MANIFEST_UNREADABLE", f"{p}: {exc}", identity={"manifest_path": str(p)}
        ) from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactVerificationError(
            "MANIFEST_MALFORMED", f"{p}: invalid JSON ({exc})", identity={"manifest_path": str(p)}
        ) from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), dict):
        raise ArtifactVerificationError(
            "MANIFEST_MALFORMED",
            f"{p}: manifest must be an object with an 'artifacts' map",
            identity={"manifest_path": str(p)},
        )
    sv = manifest.get("schema_version")
    if sv != BUNDLE_INTEGRITY_SCHEMA_VERSION:
        raise ArtifactVerificationError(
            "MANIFEST_VERSION_UNSUPPORTED",
            f"{p}: schema_version={sv!r} (supported: {BUNDLE_INTEGRITY_SCHEMA_VERSION})",
            identity={"manifest_path": str(p)},
        )
    for key in ("ticker", "ml_horizon_slug", "bundle_key"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ArtifactVerificationError(
                "MANIFEST_MALFORMED",
                f"{p}: required identity field {key!r} missing or empty",
                identity={"manifest_path": str(p)},
            )
    return manifest


def verify_artifact_against_manifest(
    bundle_dir: Path,
    ticker: str,
    hz: str,
    artifact_role: str,
    artifact_filename: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Canonical pre-deserialization verification boundary (ML-PIPE Item 4).

    Verifies artifact bytes against the bundle integrity manifest in the SAME
    bundle directory (artifact and manifest cannot be selected through different
    paths) and enforces ticker/horizon/role/bundle identity coherence. Raises
    :class:`ArtifactVerificationError` (fail closed) on every governed failure;
    returns structured verification provenance on success.
    """
    from training_cache import file_sha256_hex

    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    bd = Path(bundle_dir)
    identity: dict[str, Any] = {
        "ticker": t,
        "horizon": su,
        "artifact_role": artifact_role,
        "artifact_filename": artifact_filename,
        "bundle_dir": str(bd),
    }

    expected_name = bundle_role_filenames(t, su, include_optional=True).get(artifact_role)
    if expected_name is None:
        raise ArtifactVerificationError(
            "ARTIFACT_ROLE_MISMATCH",
            f"unknown governed artifact role {artifact_role!r}",
            identity=identity,
        )
    if artifact_filename != expected_name:
        # Cross-ticker / cross-horizon / cross-model substitution at request level.
        reason = "MODEL_IDENTITY_MISMATCH"
        if f"_{t}_" not in artifact_filename:
            reason = "TICKER_IDENTITY_MISMATCH"
        elif f"_{su}." not in artifact_filename and f"_{su}_" not in artifact_filename:
            reason = "HORIZON_IDENTITY_MISMATCH"
        raise ArtifactVerificationError(
            reason,
            f"requested {artifact_role!r} for {t}/{su} must be {expected_name!r} (got {artifact_filename!r})",
            identity=identity,
        )

    resolved = _contained_artifact_path(bd, artifact_filename, identity)

    mf = manifest if manifest is not None else load_bundle_integrity_manifest(bd)
    if mf is None:
        raise ArtifactVerificationError(
            "MANIFEST_MISSING",
            f"no {BUNDLE_INTEGRITY_MANIFEST_FILENAME} in {bd}",
            identity=identity,
        )

    if mf.get("ticker") != t:
        raise ArtifactVerificationError(
            "TICKER_IDENTITY_MISMATCH",
            f"manifest ticker {mf.get('ticker')!r} != requested {t!r}",
            identity=identity,
        )
    if mf.get("ml_horizon_slug") != su:
        raise ArtifactVerificationError(
            "HORIZON_IDENTITY_MISMATCH",
            f"manifest horizon {mf.get('ml_horizon_slug')!r} != requested {su!r}",
            identity=identity,
        )
    if mf.get("bundle_key") != f"{t}:{su}":
        raise ArtifactVerificationError(
            "BUNDLE_IDENTITY_MISMATCH",
            f"manifest bundle_key {mf.get('bundle_key')!r} != {t}:{su}",
            identity=identity,
        )

    entry = mf["artifacts"].get(artifact_filename)
    if not isinstance(entry, dict):
        raise ArtifactVerificationError(
            "ARTIFACT_ENTRY_MISSING",
            f"{artifact_filename!r} has no entry in the bundle integrity manifest",
            identity=identity,
        )
    if entry.get("role") != artifact_role:
        raise ArtifactVerificationError(
            "ARTIFACT_ROLE_MISMATCH",
            f"manifest role {entry.get('role')!r} != requested {artifact_role!r}",
            identity=identity,
        )
    if not resolved.is_file():
        raise ArtifactVerificationError(
            "ARTIFACT_FILE_MISSING", f"{resolved} does not exist", identity=identity
        )
    expected_sha = str(entry.get("sha256") or "").strip().lower()
    if not _SHA256_HEX_RE.match(expected_sha):
        raise ArtifactVerificationError(
            "EXPECTED_HASH_INVALID",
            f"manifest sha256 for {artifact_filename!r} is not 64 lowercase hex chars",
            identity=identity,
        )
    try:
        st = resolved.stat()
        actual_sha = file_sha256_hex(resolved)
    except OSError as exc:
        raise ArtifactVerificationError(
            "ARTIFACT_UNREADABLE", f"{resolved}: {exc}", identity=identity
        ) from exc
    if actual_sha != expected_sha:
        raise ArtifactVerificationError(
            "ARTIFACT_HASH_MISMATCH",
            f"{artifact_filename}: expected {expected_sha} actual {actual_sha}",
            identity=identity,
        )

    manifest_path = bundle_integrity_manifest_path(bd)
    try:
        mstat = manifest_path.stat()
        manifest_sha = file_sha256_hex(manifest_path)
    except OSError as exc:
        raise ArtifactVerificationError(
            "MANIFEST_UNREADABLE", f"{manifest_path}: {exc}", identity=identity
        ) from exc

    lineage = mf.get("source_lineage") or {}
    return {
        "verified": True,
        "integrity_class": "VERIFIED_AGAINST_BUNDLE_MANIFEST",
        "reason_code": None,
        "ticker": t,
        "horizon": su,
        "artifact_role": artifact_role,
        "artifact_filename": artifact_filename,
        "artifact_path": str(resolved),
        "artifact_bytes": st.st_size,
        "artifact_mtime_ns": st.st_mtime_ns,
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "manifest_bytes": mstat.st_size,
        "manifest_mtime_ns": mstat.st_mtime_ns,
        "bundle_key": mf.get("bundle_key"),
        "trained_at": lineage.get("trained_at"),
        "feature_schema_version": lineage.get("feature_version") or lineage.get("feature_schema_version"),
        "training_cutoff": lineage.get("data_end"),
        "scheduler_cache_key": lineage.get("scheduler_cache_key"),
        "training_code_fingerprint": lineage.get("training_code_fingerprint"),
        "legacy": False,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def classify_legacy_absent_manifest(
    bundle_dir: Path,
    ticker: str,
    hz: str,
    artifact_role: str,
    artifact_filename: str,
) -> dict[str, Any]:
    """
    Explicit legacy classification for pre-Item-4 bundles with NO integrity manifest.

    Production authorization for these bundles remains the MODEL-04 strict serve
    gate (model_serve_policy.bundle_serve_eligibility, enforced upstream in
    ml_predict._model_dir_for_ticker). This function never invents permissive
    behavior: absence is recorded as MANIFEST_MISSING provenance, and the
    ED_ARTIFACT_INTEGRITY_STRICT=1 operator lever fails closed instead.
    """
    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    bd = Path(bundle_dir)
    identity = {
        "ticker": t,
        "horizon": su,
        "artifact_role": artifact_role,
        "artifact_filename": artifact_filename,
        "bundle_dir": str(bd),
    }
    if artifact_integrity_strict_absence():
        raise ArtifactVerificationError(
            "MANIFEST_MISSING",
            f"strict mode (committed policy or {ARTIFACT_INTEGRITY_STRICT_ENV}=1): "
            f"no {BUNDLE_INTEGRITY_MANIFEST_FILENAME} in {bd}",
            identity=identity,
        )
    resolved = _contained_artifact_path(bd, artifact_filename, identity)
    if not resolved.is_file():
        raise ArtifactVerificationError(
            "ARTIFACT_FILE_MISSING", f"{resolved} does not exist", identity=identity
        )
    from training_cache import file_sha256_hex

    try:
        st = resolved.stat()
        actual_sha = file_sha256_hex(resolved)
    except OSError as exc:
        raise ArtifactVerificationError(
            "ARTIFACT_UNREADABLE", f"{resolved}: {exc}", identity=identity
        ) from exc
    return {
        "verified": False,
        "integrity_class": "LEGACY_UNVERIFIED_NO_BUNDLE_MANIFEST",
        "reason_code": "MANIFEST_MISSING",
        "ticker": t,
        "horizon": su,
        "artifact_role": artifact_role,
        "artifact_filename": artifact_filename,
        "artifact_path": str(resolved),
        "artifact_bytes": st.st_size,
        "artifact_mtime_ns": st.st_mtime_ns,
        "expected_sha256": None,
        "actual_sha256": actual_sha,
        "manifest_path": str(bundle_integrity_manifest_path(bd)),
        "manifest_sha256": None,
        "manifest_bytes": None,
        "manifest_mtime_ns": None,
        "bundle_key": f"{t}:{su}",
        "trained_at": None,
        "feature_schema_version": None,
        "training_cutoff": None,
        "scheduler_cache_key": None,
        "training_code_fingerprint": None,
        "legacy": True,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def scheduler_active_root(models_dir: Path, ml_horizon_slug: str) -> Path:
    """Canonical production root for a horizon (P2-1). 1c → models/active; else models/active_{hz}."""
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return models_dir / "active"
    return models_dir / f"active_{su}"


def active_bundle_dir(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path:
    """Production active directory for (ticker, horizon) under the canonical root."""
    root = models_dir or MODELS_DIR
    return scheduler_active_root(root, hz) / artifact_ticker_key(ticker)  # RC-345/F25: one authority


def meta_stack_artifact_filename(ticker: str, hz: str) -> str:
    """Trained meta-learner on stacked base probabilities (Layer 2)."""
    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    return META_STACK_MODEL_PATTERN.format(ticker=t, hz=su)


def horizon_bundle_filenames(ticker: str, hz: str) -> tuple[str, ...]:
    """Seven filenames: model + meta × 3 bases + meta-stack pkl for one (ticker, horizon) bundle."""
    from training_cache import parallel_artifact_basenames

    return tuple(parallel_artifact_basenames(ticker, hz))


def bundle_artifact_paths(ticker: str, hz: str, bundle_dir: Path) -> list[tuple[str, Path, Path]]:
    """Return (kind, model_path, meta_path) for each artifact in the bundle."""
    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    out: list[tuple[str, Path, Path]] = []
    for kind, model_pat, meta_pat in BUNDLE_ARTIFACT_TRIPLE:
        out.append(
            (
                kind,
                bundle_dir / model_pat.format(ticker=t, hz=su),
                bundle_dir / meta_pat.format(ticker=t, hz=su),
            )
        )
    return out


def legacy_layout_source_dirs(
    ticker: str,
    hz: str,
    *,
    models_dir: Path | None = None,
) -> tuple[Path, ...]:
    """
    Legacy dirs that may hold misplaced horizon artifacts (split-brain migration).

    Non-1c horizons may have weights under models/active/{T}/ instead of active_{hz}/{T}/.
    """
    root = models_dir or MODELS_DIR
    t = artifact_ticker_key(ticker)  # RC-345/F25: one canonical ticker-identity authority
    su = normalize_ml_horizon_slug(hz)
    canonical = active_bundle_dir(ticker, hz, models_dir=root)
    legacy: list[Path] = []
    if su != DEFAULT_ML_HORIZON_SLUG:
        legacy.append(root / "active" / t)
    wrong_slug = root / f"active_{su}" / t
    if wrong_slug != canonical:
        legacy.append(wrong_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        legacy.append(root / "active_1c" / t)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in legacy:
        if d in seen or d == canonical:
            continue
        seen.add(d)
        ordered.append(d)
    return tuple(ordered)


def check_active_bundle_complete(
    ticker: str,
    hz: str,
    *,
    bundle_dir: Path | None = None,
    models_dir: Path | None = None,
    require_integrity_manifest: bool | None = None,
) -> dict[str, Any]:
    """
    Return completeness for one (ticker, horizon) active bundle.

    Keys: compliant (bool), bundle_dir, artifacts (dict), issues (list).

    ``require_integrity_manifest``: None (default) applies the Item-4 strict
    policy (``artifact_integrity_strict_absence``) — SERVING bundles without a
    manifest fail closed once strict mode is the repository default. Candidate
    completeness checks pass False explicitly: candidates are pre-promotion by
    definition and gain their manifest at the governed promotion stamp.
    """
    bd = bundle_dir or active_bundle_dir(ticker, hz, models_dir=models_dir)
    result: dict[str, Any] = {
        "ticker": artifact_ticker_key(ticker),  # RC-345/F25: one canonical ticker identity
        "horizon": normalize_ml_horizon_slug(hz),
        "bundle_dir": str(bd),
        "compliant": True,
        "artifacts": {},
        "issues": [],
    }
    if not bd.is_dir():
        result["compliant"] = False
        result["issues"].append(f"missing bundle dir: {bd}")
        return result

    # ML-PIPE Item 4: integrity verification BEFORE the deserialization probes
    # below (torch checkpoint inspection / meta_stack pickle probe). When the
    # bundle carries an integrity manifest, any hash/identity failure fails the
    # bundle closed here and no artifact byte is deserialized.
    try:
        integrity_manifest = load_bundle_integrity_manifest(bd)
    except ArtifactVerificationError as exc:
        result["compliant"] = False
        result["issues"].append(f"artifact integrity: {exc.reason_code}: {exc.detail}")
        return result
    manifest_required = (
        artifact_integrity_strict_absence()
        if require_integrity_manifest is None
        else require_integrity_manifest
    )
    if integrity_manifest is None and manifest_required:
        result["compliant"] = False
        result["issues"].append(
            "artifact integrity: MANIFEST_MISSING (strict mode — committed policy "
            f"or {ARTIFACT_INTEGRITY_STRICT_ENV}=1)"
        )
        return result
    if integrity_manifest is not None:
        for role, name in bundle_role_filenames(ticker, hz).items():
            if not (bd / name).is_file():
                continue  # presence failures reported by the completeness loop below
            try:
                verify_artifact_against_manifest(
                    bd, ticker, hz, role, name, manifest=integrity_manifest
                )
            except ArtifactVerificationError as exc:
                result["compliant"] = False
                result["issues"].append(
                    f"artifact integrity: {exc.reason_code}: {exc.detail}"
                )
        if result["issues"]:
            return result

    for kind, model_path, meta_path in bundle_artifact_paths(ticker, hz, bd):
        art = {"exists": model_path.is_file(), "meta_exists": meta_path.is_file(), "issues": []}
        if not model_path.is_file():
            art["issues"].append(f"{model_path.name} missing")
            result["compliant"] = False
        if not meta_path.is_file():
            art["issues"].append(f"{meta_path.name} missing")
            result["compliant"] = False
        elif model_path.is_file():
            try:
                from model_contract import validate_artifact_contract

                raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                ok, reason = validate_artifact_contract(raw_meta, kind)
                if not ok:
                    art["issues"].append(f"model contract incompatible: {reason}")
                    result["compliant"] = False
            except Exception as ex:
                art["issues"].append(f"contract check failed: {ex}")
                result["compliant"] = False
            if kind in ("lstm", "transformer"):
                from lstm_data import sequence_encoder_checkpoint_issues

                for msg in sequence_encoder_checkpoint_issues(model_path):
                    art["issues"].append(msg)
                    result["compliant"] = False
        result["artifacts"][kind] = art

    meta_pkl = bd / meta_stack_artifact_filename(ticker, hz)
    meta_art = {"exists": meta_pkl.is_file(), "meta_exists": False, "issues": []}
    if not meta_pkl.is_file():
        meta_art["issues"].append(f"{meta_pkl.name} missing")
        result["compliant"] = False
    else:
        try:
            import pickle

            with meta_pkl.open("rb") as fh:
                pickle.load(fh)
        except Exception as ex:
            meta_art["issues"].append(f"meta_stack unloadable: {type(ex).__name__}: {ex}")
            result["compliant"] = False
    result["artifacts"][META_STACK_KIND] = meta_art

    return result


def strict_active_bundle_dir_for_horizon(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path | None:
    """Canonical active dir for hz when the full bundle contract passes (P2-4: no tie-break)."""
    bd = active_bundle_dir(ticker, hz, models_dir=models_dir)
    if check_active_bundle_complete(ticker, hz, bundle_dir=bd, models_dir=models_dir)["compliant"]:
        return bd
    return None


def check_candidate_bundle_complete(
    ticker: str,
    hz: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    """Same 7-file contract as active bundles, applied to parallel/cascade candidate dirs.

    Candidates are explicitly exempt from the strict manifest-absence policy:
    they are pre-promotion by definition and receive their integrity manifest at
    the governed promotion stamp. A candidate that ALREADY carries a manifest is
    still fully hash-verified above.
    """
    return check_active_bundle_complete(
        ticker, hz, bundle_dir=candidate_dir, require_integrity_manifest=False
    )


def candidate_bundles_complete(
    ticker: str,
    hz: str,
    parallel_dir: Path,
    cascade_dir: Path,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    par = check_candidate_bundle_complete(ticker, hz, parallel_dir)
    cas = check_candidate_bundle_complete(ticker, hz, cascade_dir)
    return par["compliant"] and cas["compliant"], par, cas


def _validate_horizon_bundle_in_dir(src_dir: Path, ticker: str, hz: str) -> list[str]:
    missing: list[str] = []
    for name in horizon_bundle_filenames(ticker, hz):
        if not (src_dir / name).is_file():
            missing.append(name)
    return missing


def promote_horizon_bundle_from_candidate(
    src_dir: Path,
    *,
    ticker: str,
    hz: str,
    models_dir: Path | None = None,
) -> Path:
    """
    Copy the seven-file bundle for (ticker, hz) into the canonical active dir (P2-2).

    Uses atomic directory replace via manual_control._replace_active_dir_from_source.
    """
    missing = _validate_horizon_bundle_in_dir(src_dir, ticker, hz)
    if missing:
        raise FileNotFoundError(
            f"partial candidate bundle for {ticker} hz={hz}: missing {missing[:3]}"
            + ("…" if len(missing) > 3 else "")
        )
    active_ticker_dir = active_bundle_dir(ticker, hz, models_dir=models_dir)
    include = frozenset(horizon_bundle_filenames(ticker, hz))
    from arch_competition.manual_control import _replace_active_dir_from_source

    _replace_active_dir_from_source(src_dir, active_ticker_dir, include_names=include)
    # ML-PIPE Item 4 root cause: promotion copied artifact files and dropped the
    # run manifest, so nothing bound active-serving bytes to any manifest. Stamp
    # the bundle integrity manifest from the bytes just placed in the active dir
    # plus the candidate run-manifest lineage.
    from training_cache import load_run_manifest

    write_bundle_integrity_manifest(
        active_ticker_dir,
        ticker,
        hz,
        source_run_manifest=load_run_manifest(src_dir),
    )
    return active_ticker_dir


def consolidate_horizon_layout_plan(
    ticker: str,
    hz: str,
    *,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Plan moves from legacy dirs into canonical active_{hz}/{T}/ (dry-run helper)."""
    root = models_dir or MODELS_DIR
    canonical = active_bundle_dir(ticker, hz, models_dir=root)
    canonical.mkdir(parents=True, exist_ok=True)
    moves: list[dict[str, str]] = []
    for fname in horizon_bundle_filenames(ticker, hz):
        dest = canonical / fname
        if dest.is_file():
            continue
        for legacy in legacy_layout_source_dirs(ticker, hz, models_dir=root):
            src = legacy / fname
            if src.is_file():
                moves.append({"file": fname, "from": str(src), "to": str(dest)})
                break
    return {
        "ticker": artifact_ticker_key(ticker),  # RC-345/F25: one canonical ticker identity
        "horizon": normalize_ml_horizon_slug(hz),
        "canonical_dir": str(canonical),
        "moves": moves,
    }


def apply_consolidate_horizon_layout_plan(
    plan: dict[str, Any],
    *,
    remove_from_legacy: bool = False,
) -> list[str]:
    """Apply a plan from consolidate_horizon_layout_plan; returns copied filenames."""
    copied: list[str] = []
    for move in plan.get("moves") or []:
        if not isinstance(move, dict):
            continue
        src = Path(str(move.get("from") or ""))
        dest = Path(str(move.get("to") or ""))
        fname = str(move.get("file") or dest.name)
        if not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(fname)
        if remove_from_legacy and src.is_file():
            try:
                src.unlink()
            except OSError:
                pass
    return copied
