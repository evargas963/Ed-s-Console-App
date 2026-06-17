"""Machine-verifiable release object (I-25) — stamped on every production decision.

Release is built once per process at startup and referenced by release_id on each decision.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
RELEASE_SCHEMA_VERSION = "release_object_v1"

# Env vars that materially affect live decision semantics (subset — documented in schema).
_DECISION_CONFIG_ENV_KEYS: tuple[str, ...] = (
    "ED_MH_EMPIRICAL_SUPPORT",
    "ED_SIGNAL_LAYER_FUSION_BLEND",
    "ED_XGB_STRICT_ACTIVE_ONLY",
    "ED_CONSOLE_ALLOW_PRED_OVERRIDE",
    "ED_CALIBRATION_LOG",
    "ED_BUILD_GENERATION",
)

_cached_release: Optional[dict[str, Any]] = None


def _git_head_sha() -> Optional[str]:
    env = os.environ.get("ED_BUILD_GENERATION", "").strip()
    if env:
        return env
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=3.0,
        )
        sha = (proc.stdout or "").strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_model_hashes(models_root: Path) -> list[str]:
    out: list[str] = []
    if not models_root.is_dir():
        return out
    for path in sorted(models_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in (".pkl", ".pt", ".json"):
            continue
        if path.name.endswith("_meta.json"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            out.append(f"sha256:{_sha256_file(path)}@{rel}")
    return out


def _config_hash() -> str:
    payload = {k: os.environ.get(k, "") for k in _DECISION_CONFIG_ENV_KEYS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_release_object(
    *,
    models_dir: Optional[Path] = None,
    git_sha: Optional[str] = None,
    rollback_target: Optional[str] = None,
    approval_record: Optional[str] = None,
) -> dict[str, Any]:
    """Build a machine-verifiable release object. Raises ValueError if git_sha missing."""
    sha = git_sha or _git_head_sha()
    if not sha:
        raise ValueError("release_object: git_sha unavailable — set ED_BUILD_GENERATION or run from git repo")

    models_root = models_dir or (REPO_ROOT / "models" / "active")
    model_hashes = _collect_model_hashes(models_root)
    cfg_hash = _config_hash()
    created = time.time()

    body = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "git_sha": sha,
        "build_generation": sha,
        "model_hashes": model_hashes,
        "config_hash": cfg_hash,
        "migration_version": "production_decision_records_v1",
        "approval_record": approval_record or os.environ.get("ED_RELEASE_APPROVAL_RECORD", "").strip() or None,
        "rollback_target": rollback_target or os.environ.get("ED_RELEASE_ROLLBACK_TARGET", "").strip() or None,
        "created_at_utc": created,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    release_id = "rel-" + hashlib.sha256(canonical).hexdigest()[:24]
    body["release_id"] = release_id
    return body


def initialize_release_at_startup(force: bool = False) -> dict[str, Any]:
    """Cache release object for process lifetime."""
    global _cached_release
    if _cached_release is not None and not force:
        return _cached_release
    _cached_release = build_release_object()
    log.info("release_object initialized release_id=%s git_sha=%s", _cached_release["release_id"], _cached_release["git_sha"])
    return _cached_release


def get_current_release(*, required: bool = True) -> Optional[dict[str, Any]]:
    global _cached_release
    if _cached_release is None:
        try:
            initialize_release_at_startup()
        except ValueError as exc:
            if required:
                raise
            log.warning("release_object unavailable: %s", exc)
            return None
    return _cached_release


def validate_release_for_emission(release: Optional[dict[str, Any]]) -> tuple[bool, str]:
    if not release or not isinstance(release, dict):
        return False, "missing_release_object"
    rid = str(release.get("release_id") or "").strip()
    if not rid.startswith("rel-"):
        return False, "invalid_release_id"
    if not str(release.get("git_sha") or "").strip():
        return False, "missing_git_sha"
    if release.get("schema_version") != RELEASE_SCHEMA_VERSION:
        return False, "schema_version_mismatch"
    return True, ""
