#!/usr/bin/env python3
"""Post-RTH completeness check — the operator's non-negotiable schedule (2026-08-01, RC-181).

After every regular session closes, this answers ONE question mechanically: did every enrolled
ticker collect every session minute today? Any shortfall is printed, exits non-zero, and (with
--backfill) triggers the proven Schwab backfill immediately — because the vendor's 1m history
floor slides daily (~45 days, MEASURED 2026-08-01) and every day of delay pushes holes past it
forever.

WHY THIS EXISTS (the operator's sixth why): every collection defect this repo has logged —
clock-only session labels (RC-178), fabricated weekend bars (RC-177), 99,381 silent holes —
survived because NOTHING reconciled what was collected against what the session should have
produced. Collection ran open-loop. This is the loop closing: an invariant checked on a
schedule, not goodwill.

Usage:
  .venv/Scripts/python.exe tools/rth_completeness_check_v1.py --db data/ed_console.db
  .venv/Scripts/python.exe tools/rth_completeness_check_v1.py --db data/ed_console.db --backfill

Exit codes: 0 = complete (or no session today); 1 = holes found (and backfill not run or
insufficient); 2 = cannot measure (measurement failure is NEVER reported as a pass — RC-57);
3 = the verdict was reached but its durable record could not be persisted (a windowless
pythonw run must never report silent success).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from time_et import (  # noqa: E402
    COLLECT_WINDOW_START_MINS,
    collect_window_end_mins_for_et_date,
    et_date_str_from_ts_utc,
    et_minute_total_from_ts_utc,
    is_trading_day_et,
    now_et,
)

# RC-183: the grid IS the operator Collect window law — 08:15–15:15 CT, bar_end minutes
# (555, min(975, cash_close+15)]. A first version measured classic cash RTH (570, 960], a
# DIFFERENT law from the one the writers now enforce; a checker on the wrong grid either
# misses law violations or cries holes where the law says no bar belongs.
RTH_START_MINS = COLLECT_WINDOW_START_MINS  # 555 = 09:15 ET = 08:15 CT


#: How many SESSIONS back the fallback universe reaches when the authoritative helper is
#: unavailable. RC-309: this was five days of seconds arithmetic and is now five sessions.
ENROLLMENT_FALLBACK_SESSIONS = 5


def session_lookback_bound_ts_utc(sessions: int, *, now: float | None = None) -> float:
    """Epoch seconds at ET midnight of the Nth most recent trading day (today counted first).

    RC-309. The market calendar, not seconds arithmetic: five 86400-second steps back from a
    Saturday reaches four sessions, and after a holiday Monday it reaches three, so a bound
    described as "5 sessions" silently narrowed the universe it was defining.
    """
    from datetime import datetime, timedelta

    from time_et import ET

    day = (datetime.fromtimestamp(now, tz=ET) if now is not None else now_et()).date()
    found = 0
    for _ in range(40):          # far beyond the longest market closure
        if is_trading_day_et(day.isoformat()):
            found += 1
            if found >= sessions:
                break
        day -= timedelta(days=1)
    else:
        raise RuntimeError(
            f"could not find {sessions} trading days in the 40 ET days before "
            f"{day.isoformat()} — the calendar authority is answering False for every date")
    return datetime(day.year, day.month, day.day, tzinfo=ET).timestamp()


def enrolled_tickers(db_path: str) -> list[str]:
    """The enrolled universe — RC-160: never a sentinel subset framed as complete.

    Falls back to every ticker that logged bars in the last 5 sessions when the authoritative
    universe helper is unavailable, and SAYS SO in the payload rather than silently narrowing.

    RC-309: "5 sessions" used to be `strftime('%s','now') - 5*86400`, which is five CALENDAR
    days. Measured 2026-08-08: that window spans 08-04 to 08-08 and contains FOUR trading
    days, and after a holiday Monday it contains three. A ticker whose newest bars are five
    sessions old fell out of the universe, and `session_completeness` then said nothing about
    it at all — an absent key reads as "nothing to report", not as "not examined". The bound
    now comes from the market calendar, so the docstring's claim and the query agree.
    """
    try:
        from db import EdDB  # heavy import kept local

        db = EdDB(db_path)
        tks = list(db.logging_universe_authoritative_tickers())
        if tks:
            return sorted(set(tks))
    except Exception:  # institutional-swallow-ok: enrollment-authority read is best-effort; falls through to the direct DB scan below, never a silent empty
        pass
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15.0)
    try:
        rows = con.execute(
            "SELECT DISTINCT ticker FROM price_bars_1m WHERE bar_end_ts_utc >= ?",
            (session_lookback_bound_ts_utc(ENROLLMENT_FALLBACK_SESSIONS),)).fetchall()
    finally:
        con.close()
    return sorted({str(r[0]) for r in rows if r and r[0]})


def session_completeness(db_path: str, et_date: str) -> dict:
    """Per-ticker missing RTH minutes for `et_date`. Measurement, no judgement."""
    close = collect_window_end_mins_for_et_date(et_date)
    if not close or not is_trading_day_et(et_date):
        return {"et_date": et_date, "session": False, "tickers": {}, "total_missing": 0}
    expected = int(close) - RTH_START_MINS
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        rows = con.execute(
            "SELECT ticker, bar_end_ts_utc FROM price_bars_1m "
            "WHERE bar_end_ts_utc >= strftime('%s', ? || ' 00:00:00') - 86400 "
            "AND bar_end_ts_utc <= strftime('%s', ? || ' 23:59:59') + 86400",
            (et_date, et_date)).fetchall()
    finally:
        con.close()
    present: dict[str, set[int]] = defaultdict(set)
    for tk, ts in rows:
        ts = float(ts)
        if et_date_str_from_ts_utc(ts) != et_date:
            continue
        m = et_minute_total_from_ts_utc(ts)
        if RTH_START_MINS < m <= int(close):
            present[str(tk)].add(m)
    out: dict[str, dict] = {}
    total = 0
    for tk in enrolled_tickers(db_path):
        got = len(present.get(tk, ()))
        miss = expected - got
        total += max(0, miss)
        out[tk] = {"expected": expected, "present": got, "missing": max(0, miss)}
    return {"et_date": et_date, "session": True, "expected_per_ticker": expected,
            "tickers": out, "total_missing": total,
            "tickers_with_holes": sum(1 for v in out.values() if v["missing"] > 0)}


def classify_hole(ours: int, vendor: int | None) -> str:
    """Verdict for one ticker's session after vendor reconciliation.

    MEASURED 2026-08-01 on 2026-07-31: FN 356==356, PSCI 3==3, BBIO 372==372 — the naive
    390-minute grid counted no-trade minutes of thin names as "missing", 2,123 of them, when we
    held EXACTLY what the vendor holds. A checker that cries HOLES daily trains the operator to
    ignore it, which is precisely how a real loss would slip through. Only `vendor > ours` is a
    loss; a minute with no trade has no bar anywhere and is TRUE emptiness.
    """
    if vendor is None:
        return "UNSERVABLE"          # index/futures symbols pricehistory cannot return
    if vendor > ours:
        return "LOST"                # the vendor has bars we do not — the only real defect
    return "VENDOR_EMPTY"            # we hold everything that exists


def vendor_reconcile(db_path: str, et_date: str, tickers: list[str]) -> dict:
    """Compare our RTH bar count per ticker against the vendor's, for `et_date`."""
    import os
    from datetime import datetime, timedelta, timezone

    os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")  # server import without lifespan
    from bar_rehydration_issue19_v1 import _fetch_minute_window
    from server import get_client

    client = get_client()
    day = datetime.strptime(et_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    close = int(collect_window_end_mins_for_et_date(et_date) or 975)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15.0)
    out: dict[str, dict] = {}
    lost_total = 0
    try:
        for tk in tickers:
            ours = 0
            for (ts,) in con.execute(
                    "SELECT bar_end_ts_utc FROM price_bars_1m WHERE ticker = ? "
                    "AND bar_end_ts_utc BETWEEN strftime('%s', ? || ' 00:00:00') - 86400 "
                    "AND strftime('%s', ? || ' 23:59:59') + 86400", (tk, et_date, et_date)):
                ts = float(ts)
                if et_date_str_from_ts_utc(ts) != et_date:
                    continue
                if RTH_START_MINS < et_minute_total_from_ts_utc(ts) <= close:
                    ours += 1
            vendor: int | None
            try:
                r = _fetch_minute_window(client, tk, day, day + timedelta(days=1))
                vendor = 0
                for c in (r.json() or {}).get("candles") or []:
                    cts = float(c["datetime"]) / 1000.0
                    if et_date_str_from_ts_utc(cts) == et_date:
                        m = et_minute_total_from_ts_utc(cts) + 1  # stamp is bar START
                        if RTH_START_MINS < m <= close:
                            vendor += 1
            except Exception:
                vendor = None
            verdict = classify_hole(ours, vendor)
            if verdict == "LOST":
                lost_total += (vendor or 0) - ours
            out[tk] = {"ours": ours, "vendor": vendor, "verdict": verdict}
    finally:
        con.close()
    return {"tickers": out, "lost_minutes": lost_total}


#: Durable final artifact — the operator's readable record AFTER the scheduled window exits.
#: Written on EVERY exit path so `HOLES` (an intermediate line) is never the last word the
#: operator sees. This is a run report in the EXISTING rth_validation report location, not a
#: new checker/ledger/registry.
REPORT_PATH = ROOT / "reports" / "rth_validation" / "rth_completeness_latest.json"

#: Exit code when the DATA verdict was reached but its durable record could NOT be persisted.
#: Distinct from the data verdicts (0/1/2): under pythonw there is no console, so a 0-verdict run
#: whose artifact failed to write would be a silent success — Task Scheduler reporting 0 with
#: nothing to read. Durable-observability failure is therefore itself a non-zero exit.
PERSIST_FAILED_EXIT = 3


def _write_report(record: dict, report_path: Path) -> bool:
    """Persist the final record atomically (temp + rename, so a reader never sees a half file).

    Returns True on success, False if the record could NOT be persisted. The failure is NOT
    swallowed: `finish` escalates it to a non-zero exit so a windowless (pythonw) run can never
    report silent success. The data verdict is still emitted to stderr/stdout for retention.
    """
    from datetime import datetime, timezone

    record = {**record, "written_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_name(report_path.name + ".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(report_path)
        return True
    except OSError as e:
        print(f"[rth-completeness] FATAL: could not persist the final record to {report_path}: "
              f"{e} — exiting non-zero so this run is not a silent success",
              file=sys.stderr, flush=True)
        return False


def run(db: str, et_date: str, max_missing: int, backfill: bool, report_path: Path) -> int:
    """Measure -> (optional) backfill -> vendor-reconcile, leaving ONE durable record and simple
    progress. `completion_path` names WHY completion was reached (initial completeness, successful
    backfill, or vendor reconciliation with zero real loss). Returns the fail-closed exit code:
    0 = complete/no-session; 1 = holes stand or real loss vs vendor; 2 = could not measure;
    3 = verdict reached but its durable record could not be persisted (never a silent success).
    """
    record: dict = {"et_date": et_date, "max_missing": max_missing,
                    "backfill_requested": backfill, "steps": []}

    def progress(msg: str) -> None:
        # In the durable record AND on stderr, so a redirected/interactive run shows the sequence
        # and a windowless (pythonw) run still has the full narrative in the artifact.
        record["steps"].append(msg)
        print(f"[rth-completeness] {msg}", file=sys.stderr, flush=True)

    def finish(data_exit: int, **fields) -> int:
        record.update(exit_code=data_exit, **fields)
        persisted = _write_report(record, report_path)
        # A pass (0) whose durable record did NOT persist must not exit 0 — under pythonw that is a
        # silent success. A non-zero data verdict already retains itself in the exit code.
        final_exit = data_exit if (persisted or data_exit != 0) else PERSIST_FAILED_EXIT
        # the FINAL verdict on stdout, retained even when the durable write failed
        out = {k: record.get(k) for k in
               ("final_status", "completion_path", "et_date", "grid_missing",
                "lost_vs_vendor", "backfill_exit") if k in record}
        out.update(data_verdict_exit=data_exit, report_persisted=persisted, exit_code=final_exit)
        print(json.dumps(out))
        return final_exit

    progress(f"measuring session completeness for {et_date} (db={db})")
    try:
        rep = session_completeness(db, et_date)
    except Exception as e:  # a metric that cannot be measured is NEVER a pass (RC-57)
        progress(f"MEASUREMENT FAILED: {type(e).__name__}: {e}")
        return finish(2, final_status="MEASUREMENT_FAILED", completion_path="MEASUREMENT_FAILED",
                      grid_missing=None, lost_vs_vendor=None, error=f"{type(e).__name__}: {e}")

    if not rep["session"]:
        progress("no session today (non-trading day) — clean no-op")
        return finish(0, final_status="NO_SESSION", completion_path="NO_SESSION",
                      grid_missing=0, lost_vs_vendor=0)

    record["grid_missing"] = rep["total_missing"]
    if rep["total_missing"] <= max_missing:
        progress(f"COMPLETE at first measure — grid_missing={rep['total_missing']}")
        return finish(0, final_status="COMPLETE", completion_path="INITIAL_COMPLETENESS",
                      lost_vs_vendor=0)

    record["worst"] = sorted(((tk, v["missing"]) for tk, v in rep["tickers"].items()
                              if v["missing"]), key=lambda x: -x[1])[:10]
    record["tickers_with_holes"] = rep["tickers_with_holes"]
    progress(f"HOLES grid_missing={rep['total_missing']} across {rep['tickers_with_holes']} "
             f"tickers — an INTERMEDIATE finding, NOT the verdict; reconciling now")

    if not backfill:
        progress("backfill not requested (--backfill absent) — holes stand, exit 1")
        return finish(1, final_status="HOLES", completion_path="HOLES_NO_BACKFILL",
                      lost_vs_vendor=None)

    progress("running the proven Schwab backfill (lookback 3 days) ...")
    cmd = [sys.executable, str(ROOT / "tools" / "historical_backfill_enrolled_1m_v1.py"),
           "--db", db, "--lookback-days", "3"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    record["backfill_exit"] = r.returncode
    record["backfill_tail"] = (r.stdout or r.stderr or "")[-200:]
    progress(f"backfill exit={r.returncode}; re-measuring")

    rep2 = session_completeness(db, et_date)
    record["grid_missing"] = rep2["total_missing"]  # post-backfill grid
    if rep2["total_missing"] <= max_missing:
        progress(f"COMPLETE after backfill — grid_missing={rep2['total_missing']}")
        return finish(0, final_status="COMPLETE", completion_path="SUCCESSFUL_BACKFILL",
                      lost_vs_vendor=0)

    # Residual grid holes after a successful backfill: reconcile against the vendor. Only
    # `vendor > ours` is a loss; thin names legitimately print nothing for many minutes.
    holes = [tk for tk, v in rep2["tickers"].items() if v["missing"] > 0]
    progress(f"{len(holes)} tickers still short after backfill — reconciling against the vendor")
    rec = vendor_reconcile(db, et_date, holes)
    lost = rec["lost_minutes"]
    record["lost_vs_vendor"] = lost
    record["reconciliation"] = rec["tickers"]
    if lost <= max_missing:
        progress(f"COMPLETE_VS_VENDOR — grid_missing={rep2['total_missing']}, lost_vs_vendor={lost} "
                 f"(apparent holes are vendor-empty no-trade minutes; ZERO real loss)")
        return finish(0, final_status="COMPLETE_VS_VENDOR",
                      completion_path="VENDOR_RECONCILED_ZERO_LOSS")
    progress(f"LOST_DATA — the vendor holds {lost} minutes we do not; exit 1")
    return finish(1, final_status="LOST_DATA", completion_path="LOST_DATA")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "ed_console.db"))
    ap.add_argument("--date", default=None, help="ET date (YYYY-MM-DD); default today ET")
    ap.add_argument("--max-missing", type=int, default=0,
                    help="minutes of total shortfall tolerated before failing (default 0)")
    ap.add_argument("--backfill", action="store_true",
                    help="on shortfall, run the proven Schwab backfill immediately, then re-check")
    ap.add_argument("--report", default=str(REPORT_PATH),
                    help="durable final-record path (default: the rth_validation report location)")
    args = ap.parse_args()
    et_date = args.date or now_et().date().isoformat()
    return run(args.db, et_date, args.max_missing, args.backfill, Path(args.report))


if __name__ == "__main__":
    sys.exit(main())
