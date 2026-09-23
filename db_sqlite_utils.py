"""SQLite connection tuning + tier-1 contention diagnostics for the console DB.

Extracted from db.py (RC-REHAB-1, 2026-09-22): these are pure module-level
functions operating on module-level state (a bounded ring buffer + running
totals dict), with zero EdDB instance coupling. `configure_sqlite_connection`
has ~70 external callers across calibration/, tools/, tests/, and core
production modules (ml_data_common.py, normalized_training_sync.py,
snapshot_normalizer.py) that already treat it as a standalone utility, not an
EdDB-specific method -- this extraction makes that already-true shape explicit.

`EdDB._connect` / `EdDB._tier1_snapshot_write` (db.py) stay the sole internal
consumers of this module's retry/config surface. They keep referencing these
names as bare globals (via db.py's own top-level re-export import below), NOT
via `db_sqlite_utils.NAME` lazy access -- `_tier1_snapshot_write` itself never
moved, so bare-name resolution inside it still hits db.py's own module
namespace, which is exactly what `tests/test_db_sqlite_tier1_retry.py`'s
`monkeypatch.setattr("db.SQLITE_BUSY_MAX_RETRIES", ...)` /
`"db.SQLITE_LOCK_WAIT_WARN_MS"` / `"db.SQLITE_LOCK_WAIT_DISTRESS_MS"` patch.

MONKEYPATCH SAFETY: `configure_sqlite_connection` is the only name here with a
verified hazard -- `tests/test_canonical_enforcement.py` does
`monkeypatch.delattr(db, "configure_sqlite_connection", raising=False)` to
simulate it being absent (testing calibration/canonical_enforcement.py's
import-fallback warning). This is attribute-EXISTENCE based, not value-
replacement based, so a normal top-level re-export in db.py satisfies it.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time as _wall_time
from collections import deque
from typing import Any

log = logging.getLogger(__name__)

# caps-ok (all os.environ.get(...) below): genuinely optional operator env vars; the
# string literal is the correct unset default, not a masked required value.
SQLITE_BUSY_MAX_RETRIES = max(1, int(os.environ.get("ED_SQLITE_BUSY_RETRIES", "8")))  # caps-ok: optional operator env var
SQLITE_BUSY_BASE_SLEEP_SEC = float(os.environ.get("ED_SQLITE_BUSY_BASE_SLEEP_SEC", "0.02"))  # caps-ok: optional operator env var
SQLITE_BUSY_MAX_SLEEP_SEC = float(os.environ.get("ED_SQLITE_BUSY_MAX_SLEEP_SEC", "0.4"))  # caps-ok: optional operator env var
SQLITE_LOCK_WAIT_WARN_MS = float(os.environ.get("ED_SQLITE_LOCK_WAIT_WARN_MS", "100"))  # caps-ok: optional operator env var
# RC-236: the distress bar separating routine absorbed waits (INFO) from real contention
# (WARNING). 2s ~ 5x the retry ladder's max sleep; attempt 4+ means the ladder is failing.
SQLITE_LOCK_WAIT_DISTRESS_MS = float(os.environ.get("ED_SQLITE_LOCK_WAIT_DISTRESS_MS", "2000"))  # caps-ok: optional operator env var
SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT = int(os.environ.get("ED_SQLITE_LOCK_WAIT_DISTRESS_ATTEMPT", "4"))  # caps-ok: optional operator env var
SQLITE_WRITE_SLOW_MS = float(os.environ.get("ED_SQLITE_WRITE_SLOW_MS", "500"))  # caps-ok: optional operator env var

# In-process tier-1 contention counters (audit/diagnostics; does not change retry policy).
_SQLITE_CONTENTION_METRICS_LOCK = threading.Lock()
_SQLITE_CONTENTION_RECENT_MAX = 500
_sqlite_contention_recent: deque[dict[str, Any]] = deque(maxlen=_SQLITE_CONTENTION_RECENT_MAX)
_sqlite_contention_totals: dict[str, Any] = {
    "sqlite_lock_wait_count": 0,
    "sqlite_lock_wait_total_ms": 0.0,
    "sqlite_lock_wait_max_ms": 0.0,
    "sqlite_busy_retry_count": 0,
    "sqlite_database_locked_count": 0,
    "sqlite_tier1_fail_count": 0,
    "operations": {},
    "tickers": {},
    "threads": {},
}


def record_sqlite_contention_event(
    *,
    kind: str,
    op: str,
    ticker: str | None,
    thread: str,
    wait_ms: float = 0.0,
    attempt: int = 0,
    db_path: str = "",
    error: str = "",
) -> None:
    """Record tier-1 SQLite contention for diagnostics (thread-safe, bounded ring)."""
    ts = float(_wall_time.time())
    row = {
        "kind": kind,
        "op": op,
        "ticker": ticker,
        "thread": thread,
        "wait_ms": round(float(wait_ms), 3),
        "attempt": int(attempt),
        "ts_utc": ts,
        "db_path": db_path,
        "error": (error or "")[:200],
    }
    with _SQLITE_CONTENTION_METRICS_LOCK:
        _sqlite_contention_recent.append(row)
        totals = _sqlite_contention_totals
        if kind == "lock_wait":
            totals["sqlite_lock_wait_count"] = int(totals["sqlite_lock_wait_count"]) + 1
            totals["sqlite_lock_wait_total_ms"] = float(totals["sqlite_lock_wait_total_ms"]) + float(
                wait_ms
            )
            totals["sqlite_lock_wait_max_ms"] = max(
                float(totals["sqlite_lock_wait_max_ms"]), float(wait_ms)
            )
        elif kind == "busy_retry":
            totals["sqlite_busy_retry_count"] = int(totals["sqlite_busy_retry_count"]) + 1
        elif kind in ("database_locked", "tier1_fail"):
            totals["sqlite_database_locked_count"] = int(
                totals["sqlite_database_locked_count"]
            ) + 1
            totals["sqlite_tier1_fail_count"] = int(totals["sqlite_tier1_fail_count"]) + 1
        for bucket, key in (("operations", op), ("tickers", ticker or ""), ("threads", thread)):
            if not key:
                continue
            sub = totals[bucket]
            sub[key] = int(sub.get(key, 0)) + 1


def sqlite_contention_metrics_snapshot() -> dict[str, Any]:
    """Process-local tier-1 contention totals + recent events (for /api/diagnostics)."""
    with _SQLITE_CONTENTION_METRICS_LOCK:
        recent = list(_sqlite_contention_recent)[-50:]
        totals = {
            k: v
            for k, v in _sqlite_contention_totals.items()
            if k not in ("operations", "tickers", "threads")
        }
        # caps-ok (all 9 below): totals/_sqlite_contention_totals is the module-level dict
        # literal defined above with these exact 9 keys always present; it is a singleton,
        # mutated in place, never reconstructed -- a missing key here cannot happen.
        return {
            "sqlite_lock_wait_count": int(totals["sqlite_lock_wait_count"]),
            "sqlite_lock_wait_total_ms": round(float(totals["sqlite_lock_wait_total_ms"]), 3),
            "sqlite_lock_wait_max_ms": round(float(totals["sqlite_lock_wait_max_ms"]), 3),
            "sqlite_busy_retry_count": int(totals["sqlite_busy_retry_count"]),
            "sqlite_database_locked_count": int(totals["sqlite_database_locked_count"]),
            "sqlite_tier1_fail_count": int(totals["sqlite_tier1_fail_count"]),
            "operations_affected": dict(_sqlite_contention_totals["operations"]),
            "tickers_affected": dict(_sqlite_contention_totals["tickers"]),
            "threads_affected": dict(_sqlite_contention_totals["threads"]),
            "recent_events": recent,
            "config": {
                "busy_timeout_ms": 30000,
                "journal_mode": "WAL",
                "busy_max_retries": SQLITE_BUSY_MAX_RETRIES,
                "lock_wait_warn_ms": SQLITE_LOCK_WAIT_WARN_MS,
            },
        }


def _sqlite_busy_or_locked(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


#: RC-50 SQLite access tuning (read-side accelerants for the ~30 GB WAL DB).
#: mmap_size is a memory-mapped window over the DB file, backed by the shared OS page
#: cache (NOT per-connection heap), so a large value is cheap; 2 GiB covers the hot
#: index/recent-rows working set. cache_size is per-connection page cache — SQLite reads
#: a NEGATIVE value as KiB, so -131072 == 128 MiB (vs the ~2 MiB / -2000 default).
SQLITE_MMAP_SIZE_BYTES = 2 * 1024 ** 3   # 2 GiB
SQLITE_CACHE_SIZE_KIB = -131072          # 128 MiB (negative = KiB in SQLite's PRAGMA convention)


def configure_sqlite_connection(
    conn: sqlite3.Connection, *, busy_timeout_ms: int = 30000
) -> None:
    """
    Production pragmas for any sqlite3 connection touching the console DB.

    Safe to call on every new connection (WAL is idempotent once enabled on the file).

    PRAGMA failures are rare (each pragma is well-formed) but possible if the DB file
    is locked by a separate WAL-mode-incompatible client or filesystem permissions
    block fsync. Log at debug so operators can spot pragmas silently degrading
    (e.g. journal_mode falls back to DELETE under read-only mounts) instead of
    inheriting whatever default the connection had.
    """
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        f"PRAGMA busy_timeout={int(busy_timeout_ms)}",
        "PRAGMA foreign_keys=ON",
        # RC-50 access tuning for a ~30 GB DB: the defaults (2 MB page cache, no
        # memory-mapping) re-fault every read from disk through a tiny per-connection
        # cache. mmap_size maps the hot working set (shared via the OS page cache — not
        # per-connection RAM), and a 128 MB page cache holds hot index/data pages across
        # a query. Both are read-side accelerants; neither changes durability (WAL +
        # synchronous=NORMAL unchanged). Measured: wide-row read 8.55 -> 6.59 ms; the
        # larger win is cold-start / concurrency, which the 2 MB default starved.
        f"PRAGMA mmap_size={SQLITE_MMAP_SIZE_BYTES}",
        f"PRAGMA cache_size={SQLITE_CACHE_SIZE_KIB}",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error as e:
            log.debug("configure_sqlite_connection: %s failed: %s", pragma, e)
