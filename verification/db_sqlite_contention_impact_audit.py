"""SQLite contention impact audit (read-only analysis + deterministic classification).

Proves or rejects operator-trust impact from DB lock waits — does not normalize
"eventually succeeded" as harmless.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PY = ROOT / "db.py"
SERVER_PY = ROOT / "server.py"
INDEX_HTML = ROOT / "static" / "index.html"
BASE_CAPTURE = ROOT / "base_money_path_capture.py"
NORM_SYNC = ROOT / "normalized_training_sync.py"
CAL_WRITER = ROOT / "calibration" / "writer.py"

CLASSIFICATION_TAGS = frozenset(
    {
        "NO_IMPACT_PROVEN",
        "LOCK_WAIT_ONLY_BUT_SUCCESSFUL",
        "LOCK_WAIT_CORRELATES_WITH_STALE",
        "LOCK_WAIT_CORRELATES_WITH_LOADING",
        "DATABASE_LOCKED_ERROR_PROVEN",
        "MISSED_WRITE_RISK",
        "DELAYED_NORMALIZATION_RISK",
        "TRANSPORT_FRESHNESS_RISK",
        "UI_DEGRADED_STATE_MISSING",
        "INSTRUMENTATION_GAP",
    }
)

_LOCK_WAIT_RE = re.compile(
    r"sqlite_tier1_lock_wait\s+op=(?P<op>\S+)\s+ticker=(?P<ticker>\S+)\s+"
    r"db_path=(?P<db_path>\S+)\s+wait_ms=(?P<wait_ms>[\d.]+).*?thread=(?P<thread>\S+)",
    re.IGNORECASE,
)
_BUSY_RETRY_RE = re.compile(
    r"sqlite_tier1_busy_retry\s+op=(?P<op>\S+)\s+ticker=(?P<ticker>\S+).*?thread=(?P<thread>\S+)",
    re.IGNORECASE,
)
_TIER1_FAIL_RE = re.compile(
    r"sqlite_tier1_fail\s+op=(?P<op>\S+)\s+ticker=(?P<ticker>\S+).*?thread=(?P<thread>\S+)",
    re.IGNORECASE,
)
_TIER1_OK_RE = re.compile(
    r"sqlite_tier1_ok\s+op=(?P<op>\S+)\s+ticker=(?P<ticker>\S+).*?"
    r"lock_wait_ms_total=(?P<lock_wait_ms>[\d.]+)",
    re.IGNORECASE,
)


@dataclass
class SqliteContentionMetrics:
    sqlite_lock_wait_count: int = 0
    sqlite_lock_wait_total_ms: float = 0.0
    sqlite_lock_wait_max_ms: float = 0.0
    sqlite_database_locked_count: int = 0
    sqlite_busy_retry_count: int = 0
    sqlite_tier1_fail_count: int = 0
    operations_affected: dict[str, int] = field(default_factory=dict)
    tickers_affected: dict[str, int] = field(default_factory=dict)
    threads_affected: dict[str, int] = field(default_factory=dict)
    db_paths_affected: dict[str, int] = field(default_factory=dict)
    read_operations: list[str] = field(default_factory=list)
    write_operations: list[str] = field(default_factory=list)
    snapshot_insert_failures: int = 0
    snapshot_insert_retries: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sqlite_lock_wait_count": self.sqlite_lock_wait_count,
            "sqlite_lock_wait_total_ms": round(self.sqlite_lock_wait_total_ms, 3),
            "sqlite_lock_wait_max_ms": round(self.sqlite_lock_wait_max_ms, 3),
            "sqlite_database_locked_count": self.sqlite_database_locked_count,
            "sqlite_busy_retry_count": self.sqlite_busy_retry_count,
            "sqlite_tier1_fail_count": self.sqlite_tier1_fail_count,
            "operations_affected": dict(self.operations_affected),
            "tickers_affected": dict(self.tickers_affected),
            "threads_affected": dict(self.threads_affected),
            "db_paths_affected": dict(self.db_paths_affected),
            "read_operations": list(self.read_operations),
            "write_operations": list(self.write_operations),
            "snapshot_insert_failures": self.snapshot_insert_failures,
            "snapshot_insert_retries": self.snapshot_insert_retries,
            "event_sample": self.events[:25],
        }


def _bump(counter: dict[str, int], key: str) -> None:
    if not key:
        return
    counter[key] = int(counter.get(key, 0)) + 1


def parse_sqlite_contention_log_text(text: str) -> SqliteContentionMetrics:
    """Parse server logs for tier-1 lock / busy / locked evidence."""
    m = SqliteContentionMetrics()
    if not text:
        return m

    generic_locked = len(re.findall(r"database is locked", text, flags=re.IGNORECASE))
    m.sqlite_database_locked_count = max(
        m.sqlite_database_locked_count,
        generic_locked,
        len(_TIER1_FAIL_RE.findall(text)),
    )
    m.sqlite_tier1_fail_count = len(_TIER1_FAIL_RE.findall(text))

    for match in _LOCK_WAIT_RE.finditer(text):
        wait_ms = float(match.group("wait_ms"))
        op = match.group("op")
        ticker = match.group("ticker")
        thread = match.group("thread")
        db_path = match.group("db_path")
        m.sqlite_lock_wait_count += 1
        m.sqlite_lock_wait_total_ms += wait_ms
        m.sqlite_lock_wait_max_ms = max(m.sqlite_lock_wait_max_ms, wait_ms)
        _bump(m.operations_affected, op)
        _bump(m.tickers_affected, ticker)
        _bump(m.threads_affected, thread)
        _bump(m.db_paths_affected, db_path)
        m.events.append(
            {
                "kind": "lock_wait",
                "op": op,
                "ticker": ticker,
                "thread": thread,
                "wait_ms": wait_ms,
                "db_path": db_path,
            }
        )

    for match in _BUSY_RETRY_RE.finditer(text):
        op = match.group("op")
        ticker = match.group("ticker")
        thread = match.group("thread")
        m.sqlite_busy_retry_count += 1
        m.snapshot_insert_retries += 1 if op == "insert_snapshot" else 0
        _bump(m.operations_affected, op)
        _bump(m.tickers_affected, ticker)
        _bump(m.threads_affected, thread)
        m.events.append(
            {"kind": "busy_retry", "op": op, "ticker": ticker, "thread": thread}
        )

    for match in _TIER1_FAIL_RE.finditer(text):
        op = match.group("op")
        ticker = match.group("ticker")
        thread = match.group("thread")
        m.snapshot_insert_failures += 1 if op == "insert_snapshot" else 0
        _bump(m.operations_affected, op)
        _bump(m.tickers_affected, ticker)
        _bump(m.threads_affected, thread)
        m.events.append(
            {"kind": "tier1_fail", "op": op, "ticker": ticker, "thread": thread}
        )

    for match in _TIER1_OK_RE.finditer(text):
        lock_wait_ms = float(match.group("lock_wait_ms"))
        if lock_wait_ms > 0:
            m.events.append(
                {
                    "kind": "tier1_ok_with_wait",
                    "op": match.group("op"),
                    "ticker": match.group("ticker"),
                    "lock_wait_ms_total": lock_wait_ms,
                }
            )

    m.write_operations = sorted(
        op
        for op in m.operations_affected
        if op in ("insert_snapshot", "upsert_1m_bars") or "insert" in op or "upsert" in op
    )
    if not m.write_operations and m.operations_affected:
        m.write_operations = sorted(m.operations_affected.keys())
    return m


def merge_runtime_metrics(
    metrics: SqliteContentionMetrics, runtime: Optional[dict[str, Any]]
) -> SqliteContentionMetrics:
    if not runtime:
        return metrics
    for key in (
        "sqlite_lock_wait_count",
        "sqlite_busy_retry_count",
        "sqlite_database_locked_count",
        "sqlite_tier1_fail_count",
    ):
        metrics_val = getattr(metrics, key)
        runtime_val = int(runtime.get(key, 0) or 0)
        setattr(metrics, key, max(int(metrics_val), runtime_val))
    metrics.sqlite_lock_wait_total_ms = max(
        metrics.sqlite_lock_wait_total_ms,
        float(runtime.get("sqlite_lock_wait_total_ms", 0) or 0),
    )
    metrics.sqlite_lock_wait_max_ms = max(
        metrics.sqlite_lock_wait_max_ms,
        float(runtime.get("sqlite_lock_wait_max_ms", 0) or 0),
    )
    for bucket, attr in (
        ("operations_affected", "operations_affected"),
        ("tickers_affected", "tickers_affected"),
        ("threads_affected", "threads_affected"),
    ):
        sub = runtime.get(bucket.replace("_affected", "s_affected")) or runtime.get(bucket) or {}
        if isinstance(sub, dict):
            target = getattr(metrics, attr)
            for k, v in sub.items():
                target[k] = max(int(target.get(k, 0)), int(v))
    for ev in runtime.get("recent_events") or []:
        if isinstance(ev, dict):
            metrics.events.append(ev)
    return metrics


DB_OPERATOR_STATES = frozenset({"OK", "DB_WAITING", "DB_DEGRADED", "DB_LOCKED"})

_DB_STATE_COPY: dict[str, tuple[str, str]] = {
    "OK": ("", ""),
    "DB_WAITING": ("DB WAITING", "snapshot writes delayed"),
    "DB_DEGRADED": ("DB DEGRADED", "cards may lag"),
    "DB_LOCKED": ("DB LOCKED", "analytics freshness at risk"),
}


def derive_db_contention_operator_status(
    metrics: dict[str, Any],
    *,
    now_utc: float | None = None,
    recent_window_sec: float = 120.0,
) -> dict[str, Any]:
    """
    Map tier-1 SQLite contention counters to operator-facing transport warning (not model verdict).

    DB_WAITING / DB_DEGRADED derive from the RECENT event window (default 120s) so the
    pill reports current transport health and recovers honestly once contention stops —
    process-lifetime counters previously pinned the pill degraded forever after 3 waits.
    Only MEANINGFUL waits classify: the tier-1 recorder emits a lock_wait event for every
    write (a sub-millisecond uncontended Lock.acquire still measures > 0), so raw event
    counts would flag normal per-minute trio writes as contention. Waits below the
    lock_wait_warn_ms threshold (default 100ms) are telemetry only.
    Lifetime counters stay in metrics_summary for diagnostics. DB_LOCKED stays strict:
    lifetime locked/tier1-fail counters OR recent locked events (never weakened — a
    proven locked/failed write is a hard flag for the process).
    """
    now = float(time.time() if now_utc is None else now_utc)
    recent = [
        e
        for e in (metrics.get("recent_events") or [])
        if isinstance(e, dict) and float(e.get("ts_utc") or 0) >= now - float(recent_window_sec)
    ]
    recent_kinds = {str(e.get("kind") or "") for e in recent}

    lock_wait_count = int(metrics.get("sqlite_lock_wait_count") or 0)
    lock_wait_max = float(metrics.get("sqlite_lock_wait_max_ms") or 0.0)
    busy_retry = int(metrics.get("sqlite_busy_retry_count") or 0)
    db_locked = int(metrics.get("sqlite_database_locked_count") or 0)
    tier1_fail = int(metrics.get("sqlite_tier1_fail_count") or 0)
    cfg = metrics.get("config") if isinstance(metrics.get("config"), dict) else {}
    warn_ms = float(cfg.get("lock_wait_warn_ms") or 100.0)  # fake-default-ok: config warn-threshold default; read-only audit tool

    recent_busy_retries = [e for e in recent if str(e.get("kind") or "") == "busy_retry"]
    recent_meaningful_waits = [
        e
        for e in recent
        if str(e.get("kind") or "") == "lock_wait"
        and float(e.get("wait_ms") or 0.0) >= warn_ms
    ]
    recent_wait_max = max(
        (float(e.get("wait_ms") or 0.0) for e in recent_meaningful_waits), default=0.0
    )

    state = "OK"
    if (
        db_locked > 0
        or tier1_fail > 0
        or "database_locked" in recent_kinds
        or "tier1_fail" in recent_kinds
    ):
        state = "DB_LOCKED"
    elif (
        recent_wait_max >= 500.0
        or len(recent_meaningful_waits) >= 3
        or len(recent_busy_retries) >= 2
    ):
        state = "DB_DEGRADED"
    elif recent_meaningful_waits or recent_busy_retries:
        state = "DB_WAITING"

    headline, detail = _DB_STATE_COPY[state]
    label = f"{headline} — {detail}" if headline and detail else headline
    last_ts = max((float(e.get("ts_utc") or 0) for e in recent), default=None)

    return {
        "state": state,
        "show": state != "OK",
        "label": label,
        "headline": headline,
        "detail": detail,
        "severity": (
            "bad" if state == "DB_LOCKED" else "warn" if state != "OK" else "none"
        ),
        "operator_message": (
            "Data/transport layer may be delayed — not a model verdict."
            if state != "OK"
            else ""
        ),
        "metrics_summary": {
            "sqlite_lock_wait_count": lock_wait_count,
            "sqlite_lock_wait_max_ms": round(lock_wait_max, 3),
            "sqlite_busy_retry_count": busy_retry,
            "sqlite_database_locked_count": db_locked,
            "sqlite_tier1_fail_count": tier1_fail,
        },
        "recent_window_summary": {
            "lock_wait_count": len(recent_meaningful_waits),
            "lock_wait_max_ms": round(recent_wait_max, 3),
            "busy_retry_count": len(recent_busy_retries),
            "lock_wait_warn_ms": warn_ms,
        },
        "last_event_ts_utc": last_ts,
        "recent_window_sec": float(recent_window_sec),
    }


def build_db_contention_operator_surface(metrics: dict[str, Any]) -> dict[str, Any]:
    """Full operator + diagnostics payload for API and Tier C attach."""
    status = derive_db_contention_operator_status(metrics)
    return {
        **status,
        "diagnostics_source": "/api/diagnostics/sqlite-contention",
        "operations_affected": dict(metrics.get("operations_affected") or {}),
        "tickers_affected": dict(metrics.get("tickers_affected") or {}),
        "threads_affected": dict(metrics.get("threads_affected") or {}),
        "recent_events_sample": list(metrics.get("recent_events") or [])[-10:],
    }


def lock_wait_is_harmless_classification(classifications: list[str]) -> bool:
    """Lock wait / locked errors must never be classified as harmless by default."""
    if not classifications:
        return True
    harmful = {
        "LOCK_WAIT_ONLY_BUT_SUCCESSFUL",
        "DATABASE_LOCKED_ERROR_PROVEN",
        "MISSED_WRITE_RISK",
        "TRANSPORT_FRESHNESS_RISK",
        "UI_DEGRADED_STATE_MISSING",
    }
    if harmful.intersection(classifications):
        return False
    if "NO_IMPACT_PROVEN" in classifications:
        return False
    return True


def classify_contention_findings(
    metrics: SqliteContentionMetrics,
    *,
    ui_surfaces: dict[str, Any],
    writer_map: dict[str, Any],
    correlation: dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    if metrics.sqlite_lock_wait_count > 0 or metrics.sqlite_busy_retry_count > 0:
        tags.append("LOCK_WAIT_ONLY_BUT_SUCCESSFUL")
    if metrics.sqlite_database_locked_count > 0 or metrics.sqlite_tier1_fail_count > 0:
        tags.append("DATABASE_LOCKED_ERROR_PROVEN")
        tags.append("MISSED_WRITE_RISK")
    if metrics.sqlite_tier1_fail_count > 0 or metrics.snapshot_insert_failures > 0:
        tags.append("MISSED_WRITE_RISK")
    if writer_map.get("normalization_materialize_contends"):
        tags.append("DELAYED_NORMALIZATION_RISK")
    if writer_map.get("tier_c_reads_db") or writer_map.get("tier1_serializes_hot_writes"):
        tags.append("TRANSPORT_FRESHNESS_RISK")
    if not ui_surfaces.get("operator_db_degraded_surface"):
        tags.append("UI_DEGRADED_STATE_MISSING")
    if correlation.get("stale_correlation_proven") is True:
        tags.append("LOCK_WAIT_CORRELATES_WITH_STALE")
    if correlation.get("loading_correlation_proven") is True:
        tags.append("LOCK_WAIT_CORRELATES_WITH_LOADING")
    if correlation.get("offline_correlation_gap"):
        tags.append("INSTRUMENTATION_GAP")
    if not tags:
        tags.append("INSTRUMENTATION_GAP")
    if "NO_IMPACT_PROVEN" in tags:
        tags.remove("NO_IMPACT_PROVEN")
    return sorted(set(tags))


def scan_db_configuration(db_path: Optional[Path]) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "wal_mode_enabled": None,
        "busy_timeout_ms": 30000,
        "journal_mode": None,
        "db_path": str(db_path) if db_path else None,
        "db_exists": bool(db_path and db_path.exists()),
    }
    try:
        from db import (
            SQLITE_BUSY_MAX_RETRIES,
        )

        cfg["busy_max_retries"] = SQLITE_BUSY_MAX_RETRIES
        cfg["configure_sqlite_connection_busy_timeout_ms"] = 30000
    except ImportError:
        cfg["busy_max_retries"] = 8
    if db_path and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path), timeout=2.0)
            try:
                jm = conn.execute("PRAGMA journal_mode").fetchone()
                cfg["journal_mode"] = str(jm[0]) if jm else None
                cfg["wal_mode_enabled"] = str(jm[0]).lower() == "wal" if jm else False
                bt = conn.execute("PRAGMA busy_timeout").fetchone()
                if bt:
                    cfg["busy_timeout_ms"] = int(bt[0])
            finally:
                conn.close()
        except sqlite3.Error as exc:
            cfg["pragma_error"] = str(exc)[:200]
    return cfg


def scan_writer_contention_surfaces() -> dict[str, Any]:
    db_text = DB_PY.read_text(encoding="utf-8", errors="replace")
    server_text = SERVER_PY.read_text(encoding="utf-8", errors="replace")
    norm_text = NORM_SYNC.read_text(encoding="utf-8", errors="replace")
    cal_text = CAL_WRITER.read_text(encoding="utf-8", errors="replace")
    base_text = BASE_CAPTURE.read_text(encoding="utf-8", errors="replace")
    return {
        "tier1_serializes_hot_writes": "_tier1_snapshot_write" in db_text
        and "_TIER1_SNAPSHOT_WRITE_LOCK" in db_text,
        "tier1_operations": ["insert_snapshot", "upsert_1m_bars"],
        "wal_on_connect": "PRAGMA journal_mode=WAL" in db_text,
        "busy_timeout_on_connect": "PRAGMA busy_timeout=" in db_text,
        "writes_one_row_snapshot": "insert_snapshot" in db_text,
        "base_capture_concurrent": "ThreadPoolExecutor" in base_text,
        "base_capture_thread": "ed-base-money-path-logger" in server_text
        or "base_money_path" in server_text,
        "normalization_materialize_contends": "cross_process_materialize_lock" in norm_text
        or "_materialize_lock" in norm_text,
        "calibration_writer_retries": "_sqlite_busy_or_locked" in cal_text,
        "tier_c_reads_db": "_fetch_state" in server_text and "EdDB" in server_text,
        "ui_sse_rest_snapshot_inserts": "insert_snapshot" in server_text,
        "background_logger": "_background_logger_loop" in server_text
        or "touch_background_log" in server_text,
        "competing_loops": [
            "base_money_path_logger (SPY/QQQ/IWM quote-only inserts)",
            "background_logger / UI-active ticker capture",
            "Tier C _fetch_state (DB reads + optional snapshot write)",
            "SSE / REST analytics cache refresh",
            "normalized_training_sync materialize (cross-process lock)",
            "calibration_decision_log append (when ED_CALIBRATION_LOG=1)",
        ],
        "errors_swallowed_paths": [
            "calibration writer: retries then skip row",
            "many server streaming catches log.debug only",
            "tier1_fail re-raises after log.error",
        ],
    }


def scan_ui_db_degraded_surfaces() -> dict[str, Any]:
    html = INDEX_HTML.read_text(encoding="utf-8", errors="replace")
    server = SERVER_PY.read_text(encoding="utf-8", errors="replace")
    operator_tokens = (
        "sqlite",
        "database is locked",
        "db_contention",
        "DB DEGRADED",
        "SQLITE",
    )
    html_hits = [t for t in operator_tokens if t.lower() in html.lower()]
    server_diag = "/api/diagnostics/sqlite-contention" in server
    operator_surface = bool(html_hits) or "ub-pill-db" in html or "dr-db-contention-chip" in html
    return {
        "operator_db_degraded_surface": operator_surface,
        "index_html_sqlite_tokens": html_hits,
        "server_sqlite_diagnostics_route": server_diag,
        "diagnostics_api_only_not_operator_surface": server_diag and not html_hits,
        "lane_stale_without_db_cause": "LANE STALE" in html and "sqlite" not in html.lower(),
        "loading_without_db_cause": "ANALYTICS" in html and "sqlite" not in html.lower(),
        "card_trust_contract_section": (ROOT / "docs" / "CARD_TRUST_CONTRACT.md").exists(),
    }


def answer_audit_questions(
    metrics: SqliteContentionMetrics,
    writer_map: dict[str, Any],
    db_cfg: dict[str, Any],
    ui: dict[str, Any],
    classifications: list[str],
) -> dict[str, str]:
    return {
        "1_lock_wait_producers": (
            "EdDB._tier1_snapshot_write threading lock + sqlite busy/locked retries on "
            "insert_snapshot and upsert_1m_bars"
        ),
        "2_database_locked_producers": (
            "sqlite3.OperationalError after SQLITE_BUSY_MAX_RETRIES exhausted; also "
            "calibration writer, normalized materialize, non-tier1 writers without tier1 lock"
        ),
        "3_read_vs_write": (
            f"writes: {metrics.write_operations or writer_map.get('tier1_operations')}; "
            "reads: Tier C similarity/history SELECTs, observability probes — fresh connection per call"
        ),
        "4_lock_wait_vs_stale": (
            "NOT PROVEN offline — lane STALE driven by quote-ahead / gen-behind / pending analytics; "
            "no timestamp join to sqlite_tier1_lock_wait in production buffers"
        ),
        "5_lock_wait_vs_loading": (
            "NOT PROVEN offline — LOADING/ANALYTICS… driven by Tier C pending; DB wait may extend "
            "duration but is not measured on client"
        ),
        "6_lock_wait_vs_ticker_switch": (
            "NOT PROVEN offline — switch diag lacks sqlite_lock_wait_ms field"
        ),
        "7_tier_c_delay": (
            "RISK: server comments + audit/ui-transport note Tier C _fetch_state blocked on DB; "
            "get_analytics_state offloads to thread pool but still waits on SQLite"
        ),
        "8_missed_snapshots": (
            "PROVEN only if sqlite_tier1_fail / database is locked in logs; retries may mask gaps"
        ),
        "9_delayed_normalization": (
            "RISK: normalized_training_sync cross-process lock + long materialize can lag snapshots"
        ),
        "10_calibration_gaps": (
            "RISK when ED_CALIBRATION_LOG=1 — writer retries busy/locked then may skip silently"
        ),
        "11_errors_swallowed": json.dumps(writer_map.get("errors_swallowed_paths", [])),
        "12_ui_surfaces_db": (
            f"operator_db_degraded_surface={ui.get('operator_db_degraded_surface')} — "
            "STALE/LOADING do not cite DB"
        ),
        "13_write_frequency": (
            "Base capture ~1/min/ticker concurrent; UI path throttled per-minute; Tier C writes on refresh"
        ),
        "14_shared_writer_contention": json.dumps(writer_map.get("competing_loops", [])),
        "15_wal_mode": str(db_cfg.get("wal_mode_enabled")),
        "16_busy_timeout": str(db_cfg.get("busy_timeout_ms")),
        "17_batching": "one-row insert_snapshot; upsert_1m_bars batched per bar batch",
        "18_long_read_transactions": "Reads use per-call connections; materialize may hold write lock longer",
        "19_background_connections": "ThreadPoolExecutor base capture + analytics executor + logger threads",
        "20_operator_should_see": (
            "Explicit DB DEGRADED / SQLITE SLOW chip + /api/diagnostics/sqlite-contention; "
            "not present on cards today"
        ),
        "classifications": ", ".join(classifications),
    }


def bugs_proven_and_unproven(
    metrics: SqliteContentionMetrics, classifications: list[str]
) -> dict[str, list[str]]:
    proven: list[str] = []
    not_proven: list[str] = []
    if metrics.sqlite_lock_wait_count > 0:
        proven.append(
            f"Tier-1 thread lock waits observed (count={metrics.sqlite_lock_wait_count}, "
            f"max_ms={metrics.sqlite_lock_wait_max_ms:.1f})"
        )
    if metrics.sqlite_database_locked_count > 0:
        proven.append(
            f"database is locked / tier1_fail signals (count={metrics.sqlite_database_locked_count})"
        )
    if "UI_DEGRADED_STATE_MISSING" in classifications:
        proven.append(
            "No operator-facing surface names SQLite/DB contention (STALE/LOADING are transport/analytics)"
        )
    if "TRANSPORT_FRESHNESS_RISK" in classifications:
        proven.append(
            "Code path: Tier C + snapshot writes share SQLite file — contention can delay analytics bundle"
        )
    not_proven.extend(
        [
            "Lock wait timestamps causally drive STALE pill (needs correlated RTH capture)",
            "Lock wait timestamps causally extend LOADING duration (needs switch diag + server metrics join)",
            "Missed snapshot rows from contention (needs insert outcome audit vs expected cadence)",
            "Calibration log gaps solely from SQLite (needs ED_CALIBRATION_LOG=1 window)",
        ]
    )
    if metrics.sqlite_lock_wait_count == 0 and metrics.sqlite_database_locked_count == 0:
        not_proven.append(
            "Any live contention in this offline audit run — log scrape may be empty"
        )
    return {"bugs_proven": proven, "bugs_not_proven": not_proven}


def recommended_fix_branches() -> list[dict[str, str]]:
    return [
        {
            "branch": "fix/db-sqlite-contention-surface",
            "reason": "Operator-visible DB degraded chip + payload field per Card Trust Contract §8",
        },
        {
            "branch": "fix/db-tier1-write-isolation",
            "reason": "Reduce tier-1 lock hold time / separate read replica if impact proven live",
        },
        {
            "branch": "fix/ui-transport-guest-switch-sla",
            "reason": "Guest switch SLA after DB contention measured on switch diag",
        },
        {
            "branch": "fix/card-price-conflict-explainability",
            "reason": "Reason classes — must not attribute STALE to fusion when DB is root cause",
        },
    ]


def live_rth_validation_steps() -> list[str]:
    return [
        "RTH: ED_SWITCH_TIMING=1 + scrape server log for sqlite_tier1_* while switching SPY→NVDA→SPY",
        "Correlate lane STALE chip timestamps with sqlite_contention_metrics_snapshot() deltas",
        "Measure Tier C _pipeline_ms p95 during concurrent base capture (SPY/QQQ/IWM)",
        "Compare snapshots/minute for SPY vs logger_stats during lock-wait bursts",
        "GET /api/diagnostics/sqlite-contention every 1s during stress — verify counters move",
        "If calibration enabled: row count/min vs decision_generation_id advance during lock events",
    ]


def build_contention_impact_report(
    *,
    audit_date: str,
    log_text: str,
    log_paths: list[str],
    db_path: Optional[Path],
    runtime_metrics: Optional[dict[str, Any]] = None,
    switch_events: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    metrics = parse_sqlite_contention_log_text(log_text)
    metrics = merge_runtime_metrics(metrics, runtime_metrics)
    db_cfg = scan_db_configuration(db_path)
    writer_map = scan_writer_contention_surfaces()
    ui = scan_ui_db_degraded_surfaces()
    correlation = {
        "stale_correlation_proven": False,
        "loading_correlation_proven": False,
        "offline_correlation_gap": True,
        "switch_diag_samples": len(switch_events or []),
    }
    classifications = classify_contention_findings(
        metrics, ui_surfaces=ui, writer_map=writer_map, correlation=correlation
    )
    questions = answer_audit_questions(metrics, writer_map, db_cfg, ui, classifications)
    bugs = bugs_proven_and_unproven(metrics, classifications)

    prior_observations = [
        "sqlite_tier1_lock_wait op=insert_snapshot ticker=SPY wait_ms=748.6 thread=ed-base-money-path-logger",
        "sqlite_tier1_ok op=insert_snapshot ticker=SPY attempts=1 exec_ms=33.5 lock_wait_ms_total=748.6",
        "sqlite3.OperationalError: database is locked",
        "STALE pills intermittent; LOADING sometimes long; ticker switch sometimes slow",
    ]

    return {
        "schema_version": 1,
        "classification": "Audit Report",
        "scope": "SQLite contention impact on UI/data freshness",
        "audit_date": audit_date,
        "branch": "audit/db-sqlite-contention-impact",
        "card_trust_contract": "docs/CARD_TRUST_CONTRACT.md §8 freshness; §13 must not imply STALE=model wrong",
        "metrics": metrics.to_dict(),
        "db_configuration": db_cfg,
        "writer_contention_surfaces": writer_map,
        "ui_degraded_surfaces": ui,
        "classifications": classifications,
        "audit_questions": questions,
        "prior_observations_not_proof": prior_observations,
        "operating_stance": (
            "SQLite locked but eventually recovered is NOT acceptable without measurement, "
            "operator surfacing, and reduction — per Card Trust Contract"
        ),
        "bugs": bugs,
        "instrumentation_gaps": [
            "No client join between STALE/LOADING and sqlite_lock_wait timestamps",
            "switch diag schema lacks db_lock_wait_ms",
            "Historical logs required for offline proof — empty scrape ≠ clean bill of health",
        ],
        "live_rth_validation_required": live_rth_validation_steps(),
        "recommended_fix_branches": recommended_fix_branches(),
        "log_scan": {"paths": log_paths, "bytes": len(log_text)},
        "runtime_metrics_source": "db.sqlite_contention_metrics_snapshot" if runtime_metrics else None,
    }


def format_contention_markdown(report: dict[str, Any]) -> str:
    m = report.get("metrics") or {}
    cls = report.get("classifications") or []
    bugs = report.get("bugs") or {}
    lines = [
        "> **Classification:** Audit Report | **Scope:** SQLite contention impact on UI/data freshness",
        "",
        f"**Branch:** `{report.get('branch', '')}`",
        f"**Date/session audited:** {report.get('audit_date', '')} (offline_static + log scrape)",
        "",
        "## Operating stance",
        "",
        report.get("operating_stance", ""),
        "",
        "## Lock wait evidence",
        "",
        f"- sqlite_lock_wait_count: **{m.get('sqlite_lock_wait_count')}**",
        f"- sqlite_lock_wait_total_ms: **{m.get('sqlite_lock_wait_total_ms')}**",
        f"- sqlite_lock_wait_max_ms: **{m.get('sqlite_lock_wait_max_ms')}**",
        f"- operations: `{m.get('operations_affected')}`",
        f"- tickers: `{m.get('tickers_affected')}`",
        f"- threads: `{m.get('threads_affected')}`",
        "",
        "## Database locked evidence",
        "",
        f"- sqlite_database_locked_count: **{m.get('sqlite_database_locked_count')}**",
        f"- sqlite_tier1_fail_count: **{m.get('sqlite_tier1_fail_count')}**",
        f"- sqlite_busy_retry_count: **{m.get('sqlite_busy_retry_count')}**",
        "",
        "## Classifications",
        "",
    ]
    for tag in cls:
        lines.append(f"- `{tag}`")
    lines.extend(["", "## Impact summary", ""])
    for k, v in (report.get("audit_questions") or {}).items():
        lines.append(f"**{k}:** {v}")
        lines.append("")
    lines.extend(["## Bugs proven", ""])
    for b in bugs.get("bugs_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Bugs not proven", ""])
    for b in bugs.get("bugs_not_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Instrumentation gaps", ""])
    for g in report.get("instrumentation_gaps") or []:
        lines.append(f"- {g}")
    lines.extend(["", "## Live RTH validation required", ""])
    for step in report.get("live_rth_validation_required") or []:
        lines.append(f"- {step}")
    lines.extend(["", "## Recommended fix branches", ""])
    for row in report.get("recommended_fix_branches") or []:
        lines.append(f"- `{row.get('branch')}` — {row.get('reason')}")
    lines.extend(
        [
            "",
            "## Card Trust Contract tie-back",
            "",
            report.get("card_trust_contract", ""),
            "",
            "## Prior observations (not standalone proof)",
            "",
        ]
    )
    for obs in report.get("prior_observations_not_proof") or []:
        lines.append(f"- {obs}")
    return "\n".join(lines)
