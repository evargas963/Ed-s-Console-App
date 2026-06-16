"""Shared in-process index for ablation static-lock checks (PERF2-1).

Both ``check_ablation_seven_model_four_horizon_grid`` and
``check_ablation_equal_layer_consumers`` materialize the same manifest load,
DB-enriched row sample, and whole-stack feature cell specs. Build once per
process; no disk cache; invalidates naturally on process exit.
"""
from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "ed_console.db"

_lock = threading.Lock()
_index: AblationStaticLockIndex | None = None
_build_count = 0


@dataclass(frozen=True)
class AblationStaticLockIndex:
    """Materialized ablation inputs shared by static-lock checks in one process."""

    manifest_path: Path
    db_path: Path | None
    gate_import_error: str | None
    manifest: dict[str, Any] | None
    manifest_load_error: str | None
    enriched: list[dict[str, Any]] | None
    specs: list[dict[str, Any]]
    spec_build_error: str | None
    build_count: int = field(default=1)


def reset_ablation_static_lock_index_for_tests() -> None:
    """Clear the module singleton (tests only)."""
    global _index, _build_count
    with _lock:
        _index = None
        _build_count = 0


def get_ablation_static_lock_index_build_count() -> int:
    """How many times the expensive index body has run in this process."""
    with _lock:
        return _build_count


def get_ablation_static_lock_index(
    *,
    repo_root: Path | None = None,
    manifest_path: Path | None = None,
    db_path: Path | None = None,
) -> AblationStaticLockIndex:
    """Return the process-wide ablation spec index, building it on first use."""
    global _index, _build_count
    with _lock:
        if _index is not None:
            return _index
        _build_count += 1
        built = _build_index(
            repo_root=repo_root or REPO_ROOT,
            manifest_path=manifest_path,
            db_path=db_path,
            build_count=_build_count,
        )
        _index = built
        return built


def _build_index(
    *,
    repo_root: Path,
    manifest_path: Path | None,
    db_path: Path | None,
    build_count: int,
) -> AblationStaticLockIndex:
    mpath = manifest_path or (repo_root / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json")
    dbp = db_path if db_path is not None else (repo_root / "data" / "ed_console.db")
    db_exists = dbp.is_file() if dbp is not None else False
    db_resolved = dbp if db_exists else None

    gate_import_error: str | None = None
    manifest: dict[str, Any] | None = None
    manifest_load_error: str | None = None
    enriched: list[dict[str, Any]] | None = None
    specs: list[dict[str, Any]] = []
    spec_build_error: str | None = None

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        from tools.feature_curation_gate import (
            ablation_whole_stack_feature_cell_specs,
            build_ablation_enriched_row_sample,
            load_ablation_manifest,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return AblationStaticLockIndex(
            manifest_path=mpath,
            db_path=db_resolved,
            gate_import_error=str(exc),
            manifest=None,
            manifest_load_error=None,
            enriched=None,
            specs=[],
            spec_build_error=None,
            build_count=build_count,
        )

    if not mpath.is_file():
        return AblationStaticLockIndex(
            manifest_path=mpath,
            db_path=db_resolved,
            gate_import_error=None,
            manifest=None,
            manifest_load_error=f"missing {mpath}",
            enriched=None,
            specs=[],
            spec_build_error=None,
            build_count=build_count,
        )

    try:
        manifest = load_ablation_manifest(mpath)
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        return AblationStaticLockIndex(
            manifest_path=mpath,
            db_path=db_resolved,
            gate_import_error=None,
            manifest=None,
            manifest_load_error=str(exc),
            enriched=None,
            specs=[],
            spec_build_error=None,
            build_count=build_count,
        )

    if db_resolved is not None:
        try:
            enriched = build_ablation_enriched_row_sample(
                db_path=str(db_resolved),
                manifest=manifest,
            )
        except Exception as exc:  # pragma: no cover - defensive
            spec_build_error = f"build_ablation_enriched_row_sample: {exc}"

    if spec_build_error is None:
        try:
            specs = ablation_whole_stack_feature_cell_specs(
                manifest,
                enriched_rows=enriched or None,
            )
        except Exception as exc:  # pragma: no cover - defensive
            spec_build_error = str(exc)
            specs = []

    return AblationStaticLockIndex(
        manifest_path=mpath,
        db_path=db_resolved,
        gate_import_error=None,
        manifest=manifest,
        manifest_load_error=None,
        enriched=enriched,
        specs=specs,
        spec_build_error=spec_build_error,
        build_count=build_count,
    )
