#!/usr/bin/env python3
"""
Historical canonical 1m backfill for persistently enrolled tickers.

Universe: EdDB.logging_universe_authoritative_tickers() (core + pinned + user_persisted).

Writes: Schwab minute price history -> market_data_adapter.schwab_candles_to_bars -> EdDB.upsert_1m_bars
        (same path as live server; ON CONFLICT upsert; governed outcomes refreshed inside upsert).

Post: EdDB.refresh_all_governed_bar_anchor_outcomes_v1()

Usage:
  python tools/historical_backfill_enrolled_1m_v1.py --db data/ed_console.db --dry-run
  python tools/historical_backfill_enrolled_1m_v1.py --db data/ed_console.db --lookback-days 21
  python tools/historical_backfill_enrolled_1m_v1.py --db data/ed_console.db --tickers AAPL --lookback-days 7

Exit semantics (for wrappers / CI): process exit code 0 only when ``final_status`` is a success
variant **and** ``persistence_success`` is true. A successful Schwab HTTP fetch with zero rows
upserted (when candles were returned) is **failure** (exit 1). ``print(json.dumps(...))`` alone
must not be treated as success — check ``final_status``, ``persistence_success``, and exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bar_rehydration_issue19_v1 import _fetch_minute_window  # noqa: E402
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target  # noqa: E402
from calibration.paths import DEFAULT_DB  # noqa: E402
from db import EdDB  # noqa: E402
from market_data_adapter import schwab_candles_to_bars  # noqa: E402


def _sqlite_busy_or_locked(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        em = str(exc).lower()
        return "locked" in em or "busy" in em
    return False


def probe_exclusive_sqlite_write(db_path: Path, *, timeout_s: float = 2.0) -> tuple[bool, str | None]:
    """
    Try to acquire a reserved write lock (BEGIN IMMEDIATE). Fails fast if another connection
    holds the DB busy/locked beyond timeout — without calling Schwab.
    """
    db_path = Path(db_path).resolve()
    try:
        conn = sqlite3.connect(str(db_path), timeout=float(timeout_s))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("COMMIT")
        finally:
            conn.close()
        return True, None
    except sqlite3.OperationalError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def gather_likely_db_writer_hints(db_path: Path, *, current_pid: int | None = None) -> dict:
    """
    Best-effort identification of processes that may be writing the SQLite file.
    On Windows, uses CIM Win32_Process (CommandLine may be unavailable without privileges).
    """
    db_path = Path(db_path).resolve()
    db_s = str(db_path)
    db_tail = db_path.name
    out: dict = {
        "platform": sys.platform,
        "db_path": db_s,
        "python_candidates": [],
        "likely_ed_server_pids": [],
        "operator_actions": [],
    }
    if sys.platform != "win32":
        out["operator_actions"].append(
            "Inspect processes with this DB open (e.g. `lsof` / `fuser` on the DB path). "
            "Stop the Ed web console or any job using EdDB against this file before backfill."
        )
        return out

    ps_cmd = (
        "$r = @(); "
        "$r += Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue; "
        "$r += Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" -ErrorAction SilentlyContinue; "
        "if (-not $r) { '[]' } else { "
        "$r | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 4 }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        raw = (r.stdout or "").strip()
        if r.returncode != 0:
            out["powershell_error"] = (r.stderr or raw or f"exit {r.returncode}")[:400]
            out["operator_actions"].append(
                "Could not list Python processes via PowerShell/CIM. "
                "Use Task Manager → Details → sort by Command line, or Sysinternals Handle on the .db file."
            )
            return out
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            out["powershell_parse_error"] = raw[:400]
            return out
        rows = parsed if isinstance(parsed, list) else [parsed]
        uvicorn_hits: list[int] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = row.get("ProcessId")
            cmd = row.get("CommandLine")
            cmd_s = str(cmd) if cmd is not None else ""
            try:
                pid_i = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                pid_i = None
            entry = {
                "pid": pid,
                "name": row.get("Name"),
                "command_line_preview": cmd_s[:360],
                "is_current_process": bool(current_pid is not None and pid_i == current_pid),
            }
            out["python_candidates"].append(entry)
            cl = cmd_s.lower()
            if "uvicorn" in cl and ("server:" in cl or "ed_console" in cl or db_tail.lower() in cl):
                try:
                    uvicorn_hits.append(int(pid))
                except (TypeError, ValueError):
                    pass
        out["likely_ed_server_pids"] = sorted(set(uvicorn_hits))
        out["historical_backfill_pids"] = sorted(
            {
                int(e["pid"])
                for e in out["python_candidates"]
                if isinstance(e.get("pid"), int)
                and "historical_backfill_enrolled_1m_v1" in (e.get("command_line_preview") or "")
                and not e.get("is_current_process")
            }
        )
        if out["likely_ed_server_pids"]:
            pids = ", ".join(str(x) for x in out["likely_ed_server_pids"])
            out["operator_actions"].append(
                f"Likely Ed HTTP server (uvicorn) PIDs: {pids}. "
                "Stop it with Ctrl+C in the terminal where it runs, or after confirming identity: "
                f"`taskkill /PID <pid>` (no `/F` first — prefer graceful shutdown)."
            )
        else:
            msg = (
                "No uvicorn+server match in Python command lines. "
                "Check Task Manager for other python.exe holding this DB, or another tool with the file open."
            )
            if out.get("historical_backfill_pids"):
                msg += (
                    " Other historical_backfill_enrolled_1m_v1.py PIDs (stop these first): "
                    + ", ".join(str(x) for x in out["historical_backfill_pids"])
                    + "."
                )
            out["operator_actions"].append(msg)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        out["hint_collection_error"] = str(e)[:400]
        out["operator_actions"].append(
            "Hint collection failed. Close the Ed console app / training jobs using this DB, then retry once."
        )
    return out


def _apply_backfill_outcome_summary(audit: dict) -> None:
    """Populate candles_fetched, bars_upsert_count, db_locked, persistence_success, final_status."""
    windows: list[dict] = list(audit.get("windows") or [])
    dry = bool(audit.get("dry_run"))
    candles_fetched = sum(int(w.get("n_candles") or 0) for w in windows)
    bars_upsert_count = sum(int(w.get("bars_upsert_count") or 0) for w in windows)
    audit["candles_fetched"] = candles_fetched
    audit["bars_upsert_count"] = bars_upsert_count

    we = list(audit.get("window_errors") or [])
    audit["window_errors"] = we

    win_db_locked = any(
        bool(w.get("db_locked")) or _sqlite_busy_or_locked_str(w.get("error"))
        for w in windows
    )
    audit["db_locked"] = (
        bool(audit.get("db_locked_preflight"))
        or win_db_locked
        or bool(audit.get("governed_refresh_db_locked"))
    )

    top_err = audit.get("error")
    http_fail = any(w.get("http_status") not in (None, 200) for w in windows)
    governed_err = bool(audit.get("governed_refresh_error"))

    # Schwab returned candles but nothing was written for that window (includes adapter drop + lock path).
    for w in windows:
        if w.get("http_status") != 200:
            continue
        nc = int(w.get("n_candles") or 0)
        bu = int(w.get("bars_upsert_count") or 0)
        if nc > 0 and bu == 0 and not w.get("error"):
            msg = {
                "phase": "persistence",
                "ticker": w.get("ticker"),
                "window_start": w.get("window_start_utc"),
                "detail": "http 200 and n_candles>0 but bars_upsert_count==0 (no error recorded)",
            }
            if msg not in we:
                we.append(msg)
    audit["window_errors"] = we

    if dry:
        audit["persistence_success"] = True
        audit["final_status"] = "DRY_RUN"
        return

    if top_err:
        audit["persistence_success"] = False
        if audit.get("db_locked_preflight"):
            audit["final_status"] = "FAILED_DB_LOCKED_PREFLIGHT"
        elif "tickers" in str(top_err).lower() or "no matching" in str(top_err).lower():
            audit["final_status"] = "FAILED_NO_TICKERS"
        elif "import" in str(top_err).lower():
            audit["final_status"] = "FAILED_IMPORT"
        else:
            audit["final_status"] = "FAILED_OTHER"
        return

    if governed_err:
        audit["persistence_success"] = False
        audit["final_status"] = "FAILED_GOVERNED_REFRESH"
        return

    persist_synth_only = bool(we) and not audit.get("aborted_after_db_lock") and all(
        isinstance(x, dict) and x.get("phase") == "persistence" for x in we
    )
    err_db_locked = any(
        bool(e.get("db_locked")) or _sqlite_busy_or_locked_str(e.get("error")) for e in we
    )

    if we or audit.get("aborted_after_db_lock"):
        audit["persistence_success"] = False
        if audit.get("aborted_after_db_lock") or err_db_locked:
            audit["final_status"] = "FAILED_DB_LOCKED_RUNTIME"
        elif persist_synth_only:
            audit["final_status"] = "FAILED_PERSISTENCE_ZERO_UPSERT"
        elif http_fail:
            audit["final_status"] = "FAILED_SCHWAB"
        else:
            audit["final_status"] = "FAILED_OTHER"
        return

    needs_rows = any(
        w.get("http_status") == 200 and int(w.get("n_candles") or 0) > 0 for w in windows
    )
    if needs_rows:
        ok = bars_upsert_count > 0
        audit["persistence_success"] = bool(ok)
        audit["final_status"] = "SUCCESS" if ok else "FAILED_PERSISTENCE_ZERO_UPSERT"
        return

    # No Schwab candles in any window (all empty or no windows) — nothing required to persist.
    if http_fail:
        audit["persistence_success"] = False
        audit["final_status"] = "FAILED_SCHWAB"
        return
    audit["persistence_success"] = True
    audit["final_status"] = "VACUOUS_SUCCESS"


def _sqlite_busy_or_locked_str(err: object | None) -> bool:
    if err is None:
        return False
    return _sqlite_busy_or_locked(Exception(str(err)))


def _symbol_schwab_plausible(sym: str) -> bool:
    """Exclude corrupted logging_universe fragments (e.g. '$', '$SP', 'IW')."""
    t = (sym or "").strip().upper()
    if len(t) < 2 or len(t) > 12:
        return False
    if t.startswith("$"):
        return len(t) >= 4 and t[1:].replace("^", "").isalnum()
    return all(c.isalnum() or c in ". -" for c in t)


def _enrolled_tickers_with_data(db: EdDB) -> list[str]:
    """Authoritative enrolled symbols that actually appear in snapshots or price_bars_1m."""
    auth = [x.upper().strip() for x in db.logging_universe_authoritative_tickers()]
    with db._connect() as conn:
        snap = {r[0].upper() for r in conn.execute("SELECT DISTINCT ticker FROM snapshots WHERE timeframe='1m'")}
        bars = {r[0].upper() for r in conn.execute("SELECT DISTINCT ticker FROM price_bars_1m")}
    used = snap | bars
    out = [t for t in auth if t in used and _symbol_schwab_plausible(t)]
    return sorted(set(out))


def _per_ticker_bar_stats(db: EdDB, tickers: list[str]) -> list[dict]:
    out = []
    with db._connect() as conn:
        for t in tickers:
            r = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       MIN(bar_start_ts_utc) AS mn,
                       MAX(bar_start_ts_utc) AS mx
                FROM price_bars_1m WHERE ticker = ?
                """,
                (t,),
            ).fetchone()
            days = conn.execute(
                """
                SELECT COUNT(DISTINCT strftime('%Y-%m-%d', bar_start_ts_utc, 'unixepoch'))
                FROM price_bars_1m WHERE ticker = ?
                """,
                (t,),
            ).fetchone()[0]
            sn = conn.execute(
                """
                SELECT COUNT(*) AS n, MIN(ts_utc) AS mn, MAX(ts_utc) AS mx
                FROM snapshots WHERE timeframe = '1m' AND ticker = ?
                """,
                (t,),
            ).fetchone()
            out.append(
                {
                    "ticker": t,
                    "price_bars_1m_count": int(r["n"] or 0),
                    "bar_start_min": r["mn"],
                    "bar_start_max": r["mx"],
                    "distinct_bar_utc_days": int(days or 0),
                    "snapshots_1m_count": int(sn["n"] or 0),
                    "snapshot_ts_min": sn["mn"],
                    "snapshot_ts_max": sn["mx"],
                }
            )
    return out


def run(
    db_path: Path,
    *,
    lookback_days: int,
    window_days: int,
    dry_run: bool,
    only_under_covered: bool,
    under_covered_max_bars: int,
    tickers_filter: list[str] | None = None,
    skip_governed_outcome_refresh: bool = False,
) -> dict:
    db_path = db_path.resolve()
    if not dry_run:
        ok_probe, probe_err = probe_exclusive_sqlite_write(db_path)
        if not ok_probe:
            hints = gather_likely_db_writer_hints(db_path, current_pid=os.getpid())
            audit = {
                "schema": "historical_backfill_enrolled_1m_v1",
                "db_path": str(db_path),
                "lookback_days": lookback_days,
                "window_days": window_days,
                "dry_run": dry_run,
                "windows": [],
                "tickers_targeted": [],
                "n_tickers": 0,
                "db_locked_preflight": True,
                "lock_probe_error": probe_err,
                "likely_db_writers": hints,
                "error": (
                    f"SQLite write lock probe failed (refusing Schwab fetch): {probe_err}. "
                    f"Hints: {len(hints.get('python_candidates') or [])} python processes enumerated."
                ),
                "aborted_before_schwab": True,
            }
            _apply_backfill_outcome_summary(audit)
            return audit

    db = EdDB(db_path)
    tickers = _enrolled_tickers_with_data(db)
    excluded = sorted(
        set(x.upper().strip() for x in db.logging_universe_authoritative_tickers()) - set(tickers)
    )
    if only_under_covered:
        filt: list[str] = []
        for row in _per_ticker_bar_stats(db, tickers):
            if int(row["price_bars_1m_count"] or 0) < under_covered_max_bars:
                filt.append(row["ticker"])
        tickers = filt
    tickers = sorted(set(tickers))

    want: set[str] | None = None
    if tickers_filter:
        want = {(t or "").strip().upper() for t in tickers_filter if (t or "").strip()}
        before_u = {t.upper() for t in tickers}
        tickers = [t for t in tickers if t.upper() in want]
        missing = sorted(want - before_u)
        if not tickers:
            audit = {
                "schema": "historical_backfill_enrolled_1m_v1",
                "db_path": str(db_path),
                "error": (
                    "no matching tickers after --tickers filter "
                    f"(must appear in logging_universe authoritative set AND snapshots or price_bars_1m): {missing}"
                ),
                "tickers_requested": sorted(want),
                "tickers_enrolled_with_data_sample": _enrolled_tickers_with_data(db)[:40],
                "windows": [],
            }
            _apply_backfill_outcome_summary(audit)
            return audit

    end_dt = datetime.now(timezone.utc) - timedelta(seconds=90)
    start_dt = end_dt - timedelta(days=max(1, lookback_days))

    audit: dict = {
        "schema": "historical_backfill_enrolled_1m_v1",
        "db_path": str(db_path),
        "lookback_days": lookback_days,
        "window_days": window_days,
        "window_start_utc": start_dt.isoformat(),
        "window_end_utc": end_dt.isoformat(),
        "tickers_targeted": tickers,
        "n_tickers": len(tickers),
        "tickers_excluded_malformed_or_unused": excluded,
        "tickers_filter": sorted(want) if want else None,
        "dry_run": dry_run,
        "per_ticker_before": _per_ticker_bar_stats(db, tickers),
        "windows": [],
    }

    if dry_run:
        audit["status"] = "dry_run"
        _apply_backfill_outcome_summary(audit)
        return audit

    try:
        from server import get_client
    except Exception as e:
        audit["error"] = f"get_client import failed: {e}"
        _apply_backfill_outcome_summary(audit)
        return audit

    try:
        client = get_client()
    except Exception as e:
        audit["error"] = f"Schwab client init failed: {e}"
        _apply_backfill_outcome_summary(audit)
        return audit

    counts_before_bulk: dict[str, int] = {}
    from db_authority import is_canonical_db_path
    from db_safety import (
        assert_critical_row_counts_no_drop,
        backup_console_database,
        critical_table_row_counts,
        skip_automatic_backup,
    )
    if is_canonical_db_path(db_path):
        with db._connect() as _cbc:
            counts_before_bulk = critical_table_row_counts(_cbc)
        if not skip_automatic_backup():
            bp, mp, mf = backup_console_database(
                db_path,
                operation_name="historical_backfill_enrolled_1m_v1",
            )
            audit["preflight_backup_db"] = str(bp)
            audit["preflight_backup_manifest"] = str(mp)
            audit["preflight_backup_sha256"] = mf.get("sha256")

    windows_log: list[dict] = []
    total_written = 0
    abort_all = False
    for sym in tickers:
        if abort_all:
            break
        cursor = start_dt
        sym_upper = (sym or "").strip()
        if not sym_upper:
            continue
        while cursor < end_dt:
            if abort_all:
                break
            w_end = min(cursor + timedelta(days=window_days), end_dt)
            if w_end <= cursor:
                break
            wl: dict = {
                "ticker": sym_upper,
                "window_start_utc": cursor.isoformat(),
                "window_end_utc": w_end.isoformat(),
                "http_status": None,
                "n_candles": 0,
                "n_bars_parsed": 0,
                "bars_upsert_count": 0,
                "error": None,
                "db_locked": False,
            }
            try:
                resp = _fetch_minute_window(client, sym_upper, cursor, w_end)
                wl["http_status"] = resp.status_code
                data = resp.json()
                candles = data.get("candles") or []
                wl["n_candles"] = len(candles)
                bars = schwab_candles_to_bars(candles)
                wl["n_bars_parsed"] = len(bars)
                n = db.upsert_1m_bars(
                    sym_upper,
                    bars,
                    refresh_governed_outcomes=False,
                )
                wl["bars_upsert_count"] = n
                total_written += n
            except Exception as e:
                wl["error"] = str(e)[:500]
                is_lock = _sqlite_busy_or_locked(e)
                wl["db_locked"] = is_lock
                windows_log.append(wl)
                audit.setdefault("window_errors", []).append(
                    {
                        "ticker": sym_upper,
                        "window_start": wl["window_start_utc"],
                        "error": wl["error"],
                        "db_locked": is_lock,
                    }
                )
                if is_lock:
                    audit["aborted_after_db_lock"] = True
                    hints = gather_likely_db_writer_hints(db_path, current_pid=os.getpid())
                    audit["likely_db_writers_runtime"] = hints
                    abort_all = True
                    break
                cursor = w_end
                time.sleep(0.35)
                continue
            windows_log.append(wl)
            cursor = w_end
            time.sleep(0.35)
        if not abort_all:
            time.sleep(0.35)

    audit["windows"] = windows_log
    audit["total_bar_rows_passed_to_upsert"] = total_written

    if counts_before_bulk:
        with db._connect() as _cbc2:
            counts_after_bulk = critical_table_row_counts(_cbc2)
        assert_critical_row_counts_no_drop(counts_before_bulk, counts_after_bulk)
        audit["critical_row_counts_before"] = counts_before_bulk
        audit["critical_row_counts_after"] = counts_after_bulk

    audit["per_ticker_after"] = _per_ticker_bar_stats(db, tickers)

    if skip_governed_outcome_refresh:
        audit["refresh_all_governed_bar_anchor_outcomes_v1"] = "skipped_by_flag"
    else:
        try:
            ref = db.refresh_all_governed_bar_anchor_outcomes_v1()
            audit["refresh_all_governed_bar_anchor_outcomes_v1"] = ref
        except Exception as e:
            audit["governed_refresh_error"] = str(e)[:500]
            if _sqlite_busy_or_locked(e):
                audit["governed_refresh_db_locked"] = True
                hints = gather_likely_db_writer_hints(db_path, current_pid=os.getpid())
                audit["likely_db_writers_governed_refresh"] = hints

    _apply_backfill_outcome_summary(audit)
    return audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--lookback-days", type=int, default=21, help="Calendar days of history to request (UTC window end = now).")
    ap.add_argument("--window-days", type=int, default=7, help="Max days per Schwab request chunk.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--only-under-covered",
        action="store_true",
        help="Only tickers with price_bars_1m count < --under-covered-max-bars.",
    )
    ap.add_argument("--under-covered-max-bars", type=int, default=4000)
    ap.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        metavar="SYM",
        help="Restrict to these symbols (intersection with enrolled tickers that have snapshot or bar data).",
    )
    ap.add_argument(
        "--skip-governed-outcome-refresh",
        action="store_true",
        help="Skip EdDB.refresh_all_governed_bar_anchor_outcomes_v1() after bar upserts (faster scoped runs; run refresh separately in ops).",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="historical_backfill_enrolled_1m_v1", write_capable=not args.dry_run)

    out = run(
        args.db,
        lookback_days=args.lookback_days,
        window_days=args.window_days,
        dry_run=args.dry_run,
        only_under_covered=args.only_under_covered,
        under_covered_max_bars=args.under_covered_max_bars,
        tickers_filter=list(args.tickers) if args.tickers else None,
        skip_governed_outcome_refresh=bool(args.skip_governed_outcome_refresh),
    )
    print(json.dumps(out, indent=2, default=str))
    if "error" in out:
        return 1
    if out.get("window_errors"):
        return 1
    if not out.get("persistence_success", False):
        return 1
    fs = out.get("final_status")
    if fs not in ("SUCCESS", "VACUOUS_SUCCESS", "DRY_RUN"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
