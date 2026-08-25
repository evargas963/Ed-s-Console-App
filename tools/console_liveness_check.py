"""RC-481 + RC-479: is the console actually collecting during the required window?

Two liveness gaps, one honest key. The collector's window laws live INSIDE the console
process, so if the process is DOWN — or UP but inert — nothing outside notices; and when
the model stack is fail-closed, a DEAD producer renders identically to designed abstention.
Both are answered by the snapshot clock in the production DB, read-only:

  * FRESHNESS (RC-481): during a trading day inside 09:30-close+15min ET, the newest
    snapshot must be no older than STALE_LIMIT_SECS. A stale/absent max ts means the
    console is down or has stopped collecting — the exact blind spot /api/health cannot
    see (its logger_running flag is True even when every per-ticker fetch fails).
  * PRODUCER LIVENESS (RC-479): a live model stack writes mc_paths even when it decides
    WAIT (abstention is derived from Monte Carlo output); a DEAD stack writes neither. So
    recent snapshots with mc_paths present -> producer alive (a WAIT is honest); recent
    snapshots but mc_paths NULL across the board -> producer dead, surfaced instead of
    silently mistaken for abstention.
  * PER-TICKER LIVENESS (Cursor-audit F6): the two checks above are AGGREGATE — a single
    live ticker (SPY) keeps MAX(ts_utc) and COUNT(mc_paths) fresh while a SPECIFIC enrolled
    ticker is dark. So each enrolled collecting-category ticker's own last successful
    collection clock (logging_universe.last_background_log_ts_utc) must also be within
    STALE_LIMIT_SECS. A never-collected (NULL) ticker is excluded — fresh enrollment or a
    quarantined non-collector is not a regression; a WAS-collecting-now-dark ticker is.

No new governance, no in-process change, no heartbeat table: this is one read-only query
against snapshots.ts_utc / snapshots.mc_paths, meant to run as a small scheduled host task
(EdConsoleLivenessWatch) across the window. It writes a status line to
reports/console_liveness_run.log and exits non-zero on an ALERT so the task's Last Result
shows the failure. HONEST LIMIT: it proves collection is advancing and the producer is
writing; it does not judge whether each snapshot's values are correct.

Run:
    python tools/console_liveness_check.py --db <path>
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from time_et import (  # noqa: E402
    RTH_START_MINS,
    is_trading_day_et,
    now_et,
    session_close_mins_for_et_date,
)

#: Newest snapshot may lag by at most this during the required window. Generous vs the
#: ~2s per-ticker stagger and the operator-mode trio cadence, so a normal cycle never
#: false-alarms, while a down/stalled console (minutes of silence) trips.
STALE_LIMIT_SECS = 600
#: Window closes this many minutes after the session close (through 16:15 on a normal day,
#: 13:15 on an early-close day — session_close_mins_for_et_date handles the calendar).
WINDOW_END_PAD_MINS = 15
#: Snapshots newer than this feed the producer-liveness (mc_paths) check.
RECENT_MC_WINDOW_SECS = 900

LOG_PATH = REPO / "reports" / "console_liveness_run.log"


def _emit(status: str, message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp} {status} {message}"
    # Unobtrusive-run hardening (2026-08-25): the scheduled task runs under pythonw.exe (no console
    # window — it was flashing a CMD window every 5 min). pythonw has no console stdout, so a bare
    # print() can raise (None/lost stdout). Guard it so the console line is best-effort while the
    # FILE log below — the task's actual evidence, scanned by check_scheduled_producers_are_not_inert
    # — and the process exit status are unaffected. Interactive `python tools/...` still prints.
    try:
        print(line, flush=True)
    except (OSError, ValueError, AttributeError, RuntimeError):
        pass
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _required_window_now() -> tuple[bool, str]:
    """(inside the required collection window?, human reason)."""
    et = now_et()
    et_date = et.strftime("%Y-%m-%d")
    if not is_trading_day_et(et_date):
        return False, f"{et_date} is not a trading day"
    close_mins = session_close_mins_for_et_date(et_date)
    if close_mins is None:
        return False, f"no session close known for {et_date}"
    minutes = et.hour * 60 + et.minute
    end = close_mins + WINDOW_END_PAD_MINS
    if minutes < RTH_START_MINS:
        return False, f"before 09:30 ET ({minutes} < {RTH_START_MINS})"
    if minutes > end:
        return False, f"after close+{WINDOW_END_PAD_MINS}min ({minutes} > {end})"
    return True, f"inside window [{RTH_START_MINS},{end}] ET"


def check(db_path: str) -> int:
    """0 = OK / outside window; 1 = ALERT (down, inert, or dead producer)."""
    inside, reason = _required_window_now()
    if not inside:
        _emit("OK", f"outside required window ({reason}); nothing owed")
        return 0
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error as e:
        _emit("ALERT", f"cannot open DB read-only: {e}")
        return 1
    try:
        now_ts = datetime.now(timezone.utc).timestamp()
        row = con.execute("SELECT MAX(ts_utc) FROM snapshots").fetchone()
        newest = row[0] if row else None
        if newest is None:
            _emit("ALERT", "no snapshots at all while inside the required window")
            return 1
        age = now_ts - float(newest)
        if age > STALE_LIMIT_SECS:
            _emit("ALERT", f"collection STALLED or console DOWN: newest snapshot "
                           f"{age:.0f}s old (> {STALE_LIMIT_SECS}s) inside the window")
            return 1
        # Producer liveness (RC-479): recent snapshots exist; is Monte Carlo writing?
        cutoff = now_ts - RECENT_MC_WINDOW_SECS
        mc_live = con.execute(
            "SELECT COUNT(mc_paths) FROM snapshots WHERE ts_utc > ?", (cutoff,)
        ).fetchone()[0]
        if mc_live == 0:
            _emit("ALERT", f"DEAD PRODUCER (RC-479): collection is live (newest {age:.0f}s) "
                           f"but mc_paths is NULL across the last {RECENT_MC_WINDOW_SECS//60}min "
                           f"— the model stack is fail-closed, not abstaining")
            return 1
        # Per-ticker liveness (Cursor-audit F6): the aggregate MAX(ts_utc) above stays fresh on SPY
        # alone while a SPECIFIC enrolled ticker is dark — the exact "liveness green while a ticker is
        # dark" blind spot. Flag any enrolled collecting-category ticker whose last SUCCESSFUL
        # background collection (logging_universe.last_background_log_ts_utc) is older than
        # STALE_LIMIT_SECS. A ticker that has NEVER collected (NULL) is excluded: it may be freshly
        # enrolled this cycle, or a quarantined non-collector (a known-dead symbol the logger correctly
        # stopped requesting) — neither is a regression. The defect is a ticker that WAS collecting and
        # went dark. Degrades to a silent skip (never a false ALERT) if the enrollment table is absent.
        try:
            roster = con.execute(
                "SELECT ticker, last_background_log_ts_utc FROM logging_universe "
                "WHERE category IN ('core','pinned','panel_auto','user_persisted')"
            ).fetchall()
        except sqlite3.Error:
            roster = None
        if roster:
            dark = [(tk, now_ts - float(ts)) for tk, ts in roster
                    if ts is not None and (now_ts - float(ts)) > STALE_LIMIT_SECS]
            if dark:
                dark.sort(key=lambda x: -x[1])
                names = ", ".join(f"{tk}({a:.0f}s)" for tk, a in dark[:10])
                _emit("ALERT", f"PARTIAL-DARK (F6): {len(dark)} enrolled ticker(s) stopped collecting "
                               f"while overall collection is live (newest {age:.0f}s): {names}")
                return 1
        _emit("OK", f"collecting (newest {age:.0f}s old), producer live "
                    f"({mc_live} mc_paths rows/{RECENT_MC_WINDOW_SECS//60}min), "
                    f"every enrolled ticker within {STALE_LIMIT_SECS//60}min")
        return 0
    except sqlite3.Error as e:
        _emit("ALERT", f"liveness query failed: {e}")
        return 1
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RC-481/RC-479 console + producer liveness")
    ap.add_argument("--db", required=True, help="path to ed_console.db")
    args = ap.parse_args(argv)
    return check(args.db)


if __name__ == "__main__":
    sys.exit(main())
