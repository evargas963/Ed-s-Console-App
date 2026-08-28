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
    collection clock (logging_universe.last_background_log_ts_utc) is checked too. That clock
    ROTATES: the full-roster collector is a serial round-robin, so a ticker's obligation is to
    be revisited once per CYCLE, and the cycle is roster-size x fetch-cost — not a fixed number
    of seconds. It is therefore measured live from the roster's own ladder (rotation_allowance)
    instead of compared against STALE_LIMIT_SECS, which flagged 41 of 58 healthy rotating
    tickers. A never-collected (NULL) ticker is excluded — fresh enrollment or a quarantined
    non-collector is not a regression; a WAS-collecting-now-dark ticker is.
  * ROSTER-LOOP LIVENESS: because the per-ticker rule anchors on the newest roster clock, a
    UNIFORM stall (every clock ageing together) is caught separately — if even the newest
    per-ticker clock exceeds STALE_LIMIT_SECS while the aggregate looks fresh, the full-roster
    sweep itself has stopped.

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

#: AGGREGATE freshness only: the newest snapshot ACROSS the whole console. SPY/QQQ/IWM run on
#: their own dedicated ~60s loop (server.py::_base_money_path_logger_loop), so on a healthy
#: console this clock is never minutes old and a down/stalled console still trips in ten minutes.
#: This bound is deliberately UNCHANGED — it is the strong console-down signal.
#:
#: It is NOT a per-ticker bound. The full-roster collector (server.py::_logger_loop) is a SERIAL
#: round-robin: `time.sleep(STAGGER_SECS)` before each ticker, then a BLOCKING full-pipeline fetch,
#: then `wait = max(0, LOG_INTERVAL - elapsed)` — so LOG_INTERVAL is a sleep FLOOR, not a cap, and
#: one ticker's revisit period equals the WHOLE cycle. Applying 600s to that clock flagged 41 of 58
#: healthy rotating tickers as PARTIAL-DARK. See rotation_allowance() below.
STALE_LIMIT_SECS = 600
#: Per-ticker revisit tolerance expressed in COMPLETE ROTATIONS, not seconds — the obligation is
#: "you must be revisited once per cycle", and the cycle length is runtime data (roster size x
#: per-ticker fetch cost), so it is measured live rather than hard-coded. Two rotations of slack:
#: measured cycle-to-cycle jitter on the production roster was 1018s median against 1993s max
#: (ratio ~1.96), so a single long cycle is normal and two consecutive missed rotations is a
#: genuine skip.
ROTATIONS_ALLOWED = 2
#: Smallest roster whose ladder can be measured at all. DERIVED, not chosen: the p90 index is
#: int(n*0.9), which sits strictly below the maximum only when 0.1n > 1, i.e. n >= 11. Below that
#: the "90th percentile" IS the largest age and a single dark ticker would define the rotation
#: meant to catch it. Smaller rosters fall back to the flat aggregate bound.
MIN_LADDER_SAMPLE = 11
#: Window closes this many minutes after the session close (through 16:15 on a normal day,
#: 13:15 on an early-close day — session_close_mins_for_et_date handles the calendar).
WINDOW_END_PAD_MINS = 15
#: Snapshots newer than this feed the producer-liveness (mc_paths) check.
RECENT_MC_WINDOW_SECS = 900

LOG_PATH = REPO / "reports" / "console_liveness_run.log"


def rotation_allowance(ages_sorted: list[float]) -> tuple[float, float]:
    """(per-ticker allowance, measured rotation) derived from the collector's OWN rotation.

    A SERIAL round-robin puts the roster's success clocks on a uniform LADDER spanning exactly one
    cycle: the ticker just written sits at age ~0, the one due next sits at ~one cycle. So the
    ladder's SPREAD *is* the cycle length, measured live — it needs no constant and stays correct
    as the roster grows or the per-ticker fetch cost changes. Measured on the production roster:
    spread 983s against an independently measured 1018s median cycle.

    The spread is read to the 90th percentile so a genuinely dark ticker cannot inflate the very
    allowance meant to catch it (SATS sat at 8,045,959s while p90 was 10,411s).

    Anchored on the NEWEST clock, because a uniform offset — every clock ageing together once the
    collection window closes, or while the loop is wedged — must not by itself look like a
    per-ticker skip. That condition is caught by the roster-loop liveness check instead, so this
    function never has to distinguish "everyone is late" from "one ticker was skipped".

    Floored at STALE_LIMIT_SECS so the per-ticker rule is never STRICTER than the aggregate bound.

    SAMPLE-SIZE GUARD: the p90 index is ``int(n * 0.9)``, which is below the maximum only when
    ``int(n*0.9) < n-1`` — i.e. ``0.1n > 1``, so ``n >= 11``. With a smaller roster p90 IS the
    largest age, and the estimator would silently absorb the very ticker it exists to catch (a
    2-ticker roster with one 20-minute-dark ticker would infer a 20-minute "rotation"). Below that
    sample size there is no ladder to measure, so fall back to the flat aggregate bound — which is
    also correct on its own terms, because a handful of tickers sweeps in well under STALE_LIMIT_SECS.
    """
    n = len(ages_sorted)
    if not n:
        return float(STALE_LIMIT_SECS), 0.0
    newest = ages_sorted[0]
    if n < MIN_LADDER_SAMPLE:
        return float(STALE_LIMIT_SECS), 0.0
    p90 = ages_sorted[min(n - 1, int(n * 0.9))]
    rotation = max(0.0, p90 - newest)
    return newest + max(float(STALE_LIMIT_SECS), ROTATIONS_ALLOWED * rotation), rotation


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
            clocked = [(tk, now_ts - float(ts)) for tk, ts in roster if ts is not None]
            ages_sorted = sorted(a for _tk, a in clocked)
            # ROSTER-LOOP LIVENESS. The aggregate clock above is held fresh by the dedicated
            # SPY/QQQ/IWM loop alone, so it cannot see the full-roster sweep dying. In a healthy
            # sweep SOME ticker is written every stagger+fetch (~17s measured), so if the NEWEST
            # roster clock is itself older than the aggregate bound the sweep has stopped — this
            # is the "liveness green while the roster is dark" blind spot, and it is what lets the
            # per-ticker rule below anchor on the newest clock without being fooled by a uniform
            # stall.
            if ages_sorted and ages_sorted[0] > STALE_LIMIT_SECS:
                _emit("ALERT", f"ROSTER LOOP DARK: newest per-ticker collection is "
                               f"{ages_sorted[0]:.0f}s old (> {STALE_LIMIT_SECS}s) while overall "
                               f"collection looks live (newest snapshot {age:.0f}s) — the "
                               f"full-roster sweep has stopped, not just one ticker")
                return 1
            # PER-TICKER SKIP (Cursor-audit F6), measured against the collector's OWN rotation
            # rather than a fixed number of seconds. A ticker that has NEVER collected (NULL) stays
            # excluded: freshly enrolled, or a quarantined non-collector — neither is a regression.
            # Degrades to a silent skip (never a false ALERT) if the enrollment table is absent.
            allowance, rotation = rotation_allowance(ages_sorted)
            dark = [(tk, a) for tk, a in clocked if a > allowance]
            if dark:
                dark.sort(key=lambda x: -x[1])
                names = ", ".join(f"{tk}({a:.0f}s)" for tk, a in dark[:10])
                _emit("ALERT", f"PARTIAL-DARK (F6): {len(dark)} enrolled ticker(s) stopped "
                               f"collecting while overall collection is live (newest {age:.0f}s); "
                               f"allowance {allowance:.0f}s = {ROTATIONS_ALLOWED} x measured "
                               f"{rotation:.0f}s rotation: {names}")
                return 1
        _emit("OK", f"collecting (newest {age:.0f}s old), producer live "
                    f"({mc_live} mc_paths rows/{RECENT_MC_WINDOW_SECS//60}min), "
                    f"every enrolled ticker within its measured revisit obligation")
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
