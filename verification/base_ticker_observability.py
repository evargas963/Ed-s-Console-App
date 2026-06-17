"""RTH observability metrics and status for base money-path tickers."""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any, Optional

from money_path_ticker_tiers import observability_thresholds

PASS_BASE_OBSERVABILITY = "PASS_BASE_OBSERVABILITY"
FAIL_SPARSE_SNAPSHOTS = "FAIL_SPARSE_SNAPSHOTS"
FAIL_MISSING_CAL_LOG = "FAIL_MISSING_CAL_LOG"
FAIL_MISSING_NORMALIZED = "FAIL_MISSING_NORMALIZED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

ET = datetime.timezone(datetime.timedelta(hours=-4))


def rth_window_utc(day: datetime.date) -> tuple[float, float]:
    start_et = datetime.datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    end_et = datetime.datetime(day.year, day.month, day.day, 16, 0, tzinfo=ET)
    return start_et.timestamp(), end_et.timestamp()


def ts_et_label(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).astimezone(ET).strftime(
        "%Y-%m-%d %H:%M:%S ET"
    )


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _gap_stats(ts_list: list[float]) -> tuple[Optional[float], Optional[float]]:
    if len(ts_list) < 2:
        return None, None
    gaps = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
    return sorted(gaps)[len(gaps) // 2], max(gaps)


def evaluate_ticker_observability(
    conn: sqlite3.Connection,
    ticker: str,
    rth_start: float,
    rth_end: float,
    *,
    thresholds: Optional[dict[str, Any]] = None,
    require_calibration_log: bool = True,
) -> dict[str, Any]:
    t = ticker.upper()
    thr = thresholds or observability_thresholds()
    min_snap = int(thr.get("min_snapshot_rows_rth", 300))
    min_norm = int(thr.get("min_normalized_rows_rth", 300))
    max_med = float(thr.get("max_median_gap_seconds", 90))
    max_gap_thr = float(thr.get("max_gap_seconds", 300))

    snap = conn.execute(
        "SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM snapshots WHERE ticker=? AND ts_utc BETWEEN ? AND ?",
        (t, rth_start, rth_end),
    ).fetchone()
    norm_count = 0
    norm_min = norm_max = None
    has_norm = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
        ).fetchone()
    )
    if has_norm:
        norm = conn.execute(
            "SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM snapshots_1m_normalized WHERE ticker=? AND ts_utc BETWEEN ? AND ?",
            (t, rth_start, rth_end),
        ).fetchone()
        norm_count = int(norm[0] or 0)
        norm_min, norm_max = norm[1], norm[2]

    cal_count = 0
    has_cal = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calibration_decision_log'"
        ).fetchone()
    )
    if has_cal:
        cal_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM calibration_decision_log WHERE ticker=? AND decision_ts_utc BETWEEN ? AND ?",
                (t, rth_start, rth_end),
            ).fetchone()[0]
        )

    snap_count = int(snap[0] or 0)
    ts_list = [
        float(r[0])
        for r in conn.execute(
            "SELECT ts_utc FROM snapshots WHERE ticker=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
            (t, rth_start, rth_end),
        ).fetchall()
    ]
    median_gap, max_gap_obs = _gap_stats(ts_list)

    reasons: list[str] = []
    status = PASS_BASE_OBSERVABILITY

    if not has_norm:
        status = FAIL_MISSING_NORMALIZED
        reasons.append("snapshots_1m_normalized table absent")
    elif norm_count == 0 and snap_count == 0:
        status = INSUFFICIENT_EVIDENCE
        reasons.append("no RTH snapshot or normalized rows for date window")
    elif norm_count == 0:
        status = FAIL_MISSING_NORMALIZED
        reasons.append("zero normalized rows in RTH window")
    elif snap_count < min_snap or norm_count < min_norm:
        status = FAIL_SPARSE_SNAPSHOTS
        reasons.append(
            f"snapshot_rows_rth={snap_count} normalized_rows_rth={norm_count} below minimum {min_snap}"
        )

    if median_gap is not None and median_gap > max_med:
        if status == PASS_BASE_OBSERVABILITY:
            status = FAIL_SPARSE_SNAPSHOTS
        reasons.append(f"median_gap_seconds={median_gap:.1f} exceeds {max_med}")
    if max_gap_obs is not None and max_gap_obs > max_gap_thr:
        if status == PASS_BASE_OBSERVABILITY:
            status = FAIL_SPARSE_SNAPSHOTS
        reasons.append(f"max_gap_seconds={max_gap_obs:.1f} exceeds {max_gap_thr}")

    if require_calibration_log and has_cal and cal_count == 0 and snap_count > 0:
        if status == PASS_BASE_OBSERVABILITY:
            status = FAIL_MISSING_CAL_LOG
        reasons.append("snapshots present but zero calibration_decision_log rows in RTH window")

    first_ts = norm_min or snap[1]
    last_ts = norm_max or snap[2]

    return {
        "ticker": t,
        "snapshot_count_rth": snap_count,
        "normalized_count_rth": norm_count,
        "calibration_decision_count_rth": cal_count,
        "first_ts_utc": float(first_ts) if first_ts is not None else None,
        "last_ts_utc": float(last_ts) if last_ts is not None else None,
        "first_ts_et": ts_et_label(float(first_ts)) if first_ts is not None else None,
        "last_ts_et": ts_et_label(float(last_ts)) if last_ts is not None else None,
        "median_gap_seconds": round(median_gap, 3) if median_gap is not None else None,
        "max_gap_seconds": round(max_gap_obs, 3) if max_gap_obs is not None else None,
        "coverage_status": status,
        "reason": "; ".join(reasons) if reasons else "meets base RTH observability thresholds",
        "thresholds_applied": {
            "min_snapshot_rows_rth": min_snap,
            "min_normalized_rows_rth": min_norm,
            "max_median_gap_seconds": max_med,
            "max_gap_seconds": max_gap_thr,
        },
    }


def base_ticker_observability_report(
    *,
    day: datetime.date,
    tickers: list[str],
    db_path: Path,
    require_calibration_log: bool = True,
) -> dict[str, Any]:
    rth_start, rth_end = rth_window_utc(day)
    conn = _connect_ro(db_path)
    rows = [
        evaluate_ticker_observability(
            conn, t, rth_start, rth_end, require_calibration_log=require_calibration_log
        )
        for t in tickers
    ]
    conn.close()
    all_pass = all(r["coverage_status"] == PASS_BASE_OBSERVABILITY for r in rows)
    return {
        "meta": {
            "date": day.isoformat(),
            "rth_et": "09:30-16:00 ET",
            "db_path": str(db_path.resolve()),
            "base_universe_ready": all_pass,
            "contract": "governance/artifacts/base_ticker_money_path_contract.json",
        },
        "tickers": rows,
        "summary": {
            "pass_count": sum(1 for r in rows if r["coverage_status"] == PASS_BASE_OBSERVABILITY),
            "fail_count": len(rows)
            - sum(1 for r in rows if r["coverage_status"] == PASS_BASE_OBSERVABILITY),
        },
    }


def format_observability_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Base ticker observability — {report['meta']['date']}",
        "",
        f"Universe ready: **{report['meta']['base_universe_ready']}**",
        "",
        "| Ticker | Snap RTH | Norm RTH | Cal RTH | Median gap | Max gap | Status | Reason |",
        "|--------|----------|----------|---------|------------|---------|--------|--------|",
    ]
    for r in report["tickers"]:
        reason = str(r["reason"])[:80]
        lines.append(
            f"| {r['ticker']} | {r['snapshot_count_rth']} | {r['normalized_count_rth']} | "
            f"{r['calibration_decision_count_rth']} | {r.get('median_gap_seconds') or '—'} | "
            f"{r.get('max_gap_seconds') or '—'} | {r['coverage_status']} | {reason} |"
        )
    return "\n".join(lines)
