"""Cross-process session cache for deterministic governance-gate subchecks
(GOVERNANCE_GATE_PERFORMANCE_AND_TEST_OWNERSHIP_V1, Phase 4).

Measured cause: ``check_ablation_seven_model_four_horizon_grid`` is ~205s of the
~212s fix-everything gate, and the gate executes in up to five cold processes
per commit cycle (explicit enforce-all, upfront-gate, commit-msg hook, staged
hook, Stop hook). The in-process singleton (ablation_static_lock_index) cannot
help across processes.

Correctness rules (binding):
- SUCCESSFUL results only are cached; error results are NEVER cached.
- The key covers every correctness-relevant identity listed in ``build_key``;
  any uncertainty about dependency completeness must be resolved by ADDING the
  dependency to the key, never by reusing.
- Live-DB dependencies are keyed by exact (mtime_ns, size) of the .db/.db-wal/
  .db-shm triple: any write invalidates; worst case is a miss, never staleness.
- Corrupt or unreadable cache entries fail closed (miss).
- ``ED_GATE_CACHE_DISABLE=1`` forces no-cache verification mode.
- Entries record full provenance (key inputs, created_at, tool version).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "governance" / "artifacts" / ".gate_cache"
GATE_CACHE_VERSION = "1"
_DISABLE_ENV = "ED_GATE_CACHE_DISABLE"


def gate_cache_enabled() -> bool:
    return os.environ.get(_DISABLE_ENV, "").strip() not in ("1", "true", "yes", "on")


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _file_content_identity(p: Path) -> str:
    """Content hash for source/config dependencies (small files)."""
    try:
        return _hash_bytes(p.read_bytes())
    except OSError:
        return f"ABSENT:{p.name}"


def _file_stat_identity(p: Path) -> str:
    """Exact stat identity for large mutable stores (live sqlite + WAL/SHM)."""
    try:
        st = p.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return f"ABSENT:{p.name}"


def db_triple_identity(db_path: Path) -> list[str]:
    """WAL-mode sqlite identity: main file alone is insufficient (writes land in
    -wal first) — all three siblings participate in the key."""
    out = []
    for suffix in ("", "-wal", "-shm"):
        out.append(_file_stat_identity(Path(str(db_path) + suffix)))
    return out


def build_key(
    *,
    check_name: str,
    source_deps: list[Path],
    db_deps: list[Path],
    invocation: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Compose the full-identity cache key. Returns (key_hex, provenance)."""
    parts: dict[str, Any] = {
        "cache_version": GATE_CACHE_VERSION,
        "check_name": check_name,
        "repo_root": str(REPO_ROOT),
        "python": sys.version.split()[0],
        "invocation": {k: invocation[k] for k in sorted(invocation)},
        "env": {
            _DISABLE_ENV: os.environ.get(_DISABLE_ENV, ""),
        },
        "source_deps": {
            str(p.relative_to(REPO_ROOT)) if str(p).startswith(str(REPO_ROOT)) else str(p):
            _file_content_identity(p)
            for p in sorted(source_deps, key=str)
        },
        "db_deps": {
            str(p): db_triple_identity(p) for p in sorted(db_deps, key=str)
        },
    }
    blob = json.dumps(parts, sort_keys=True).encode("utf-8")
    return _hash_bytes(blob), parts


def cached_check(
    *,
    check_name: str,
    source_deps: list[Path],
    db_deps: list[Path],
    invocation: dict[str, Any],
    compute: Callable[[], list[str]],
) -> tuple[list[str], dict[str, Any]]:
    """Run ``compute`` (a subcheck returning an error list) through the cache.

    Returns (errors, cache_provenance). Only SUCCESSFUL (empty-error) results
    are stored — a failing gate always recomputes, so a fix is observed the
    moment it lands and a failure can never be served stale.
    """
    prov: dict[str, Any] = {"check": check_name, "cache": "disabled"}
    if not gate_cache_enabled():
        return compute(), prov

    key, key_parts = build_key(
        check_name=check_name,
        source_deps=source_deps,
        db_deps=db_deps,
        invocation=invocation,
    )
    entry_path = CACHE_DIR / f"{check_name}.{key[:32]}.json"
    prov = {"check": check_name, "cache": "miss", "key": key[:16], "entry": entry_path.name}

    if entry_path.is_file():
        try:
            doc = json.loads(entry_path.read_text(encoding="utf-8"))
            if (
                isinstance(doc, dict)
                and doc.get("key") == key
                and doc.get("status") == "success"
                and isinstance(doc.get("errors"), list)
                and doc.get("cache_version") == GATE_CACHE_VERSION
            ):
                prov["cache"] = "hit"
                prov["created_at"] = doc.get("created_at")
                return list(doc["errors"]), prov
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            prov["cache"] = "corrupt_entry_recompute"

    errors = compute()
    if not errors:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = entry_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "cache_version": GATE_CACHE_VERSION,
                        "key": key,
                        "key_parts": key_parts,
                        "status": "success",
                        "errors": [],
                        "created_at": time.time(),
                    },
                    indent=1,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(entry_path)
            prov["stored"] = True
        except OSError:
            prov["stored"] = False
    else:
        prov["stored"] = False  # failures are never cached
    return errors, prov
