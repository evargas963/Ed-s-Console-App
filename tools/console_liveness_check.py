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
#: MEASURED from 524 same-ticker background-logger revisit INTERVALS (consecutive collections of
#: the SAME ticker across one trading day, with the Schwab-auth outage hours excluded because the
#: watchdog must ALERT on those, not be tuned to tolerate them):
#:     p50 1391s | p90 2311s (1.66x) | p95 2656s (1.91x) | p99 2723s (1.96x) | max 6893s (4.95x)
#: The distribution has a clear GAP: the bulk ends at 1.96x and the next observation is 4.95x (a
#: 1.9-hour RTH gap — a genuine hiccup that should alert). The threshold belongs inside that gap.
#: Two rotations is the arithmetic minimum (ceil(1.96)) but lands ON p99 with no margin, which at
#: ~58 tickers x ~15 revisits/day would false-alarm about nine times a day. Three rotations covers
#: the entire measured bulk with ~48% headroom and still flags the 4.95x outlier.
#: NOTE: an earlier revision justified this from min/p50/max of the cross-sectional AGE LADDER.
#: That was wrong — those are positions within ONE rotation (half-cycle vs full-cycle, hence the
#: spurious "1.96x jitter"), not repeated revisit intervals. That justification is withdrawn.
ROTATIONS_ALLOWED = 3
#: Quantile used to read the ladder. age(q) = q * cycle on a uniform ladder, so cycle =
#: (age_q - newest) / q recovers the cycle exactly and is offset-invariant. A LOW quantile is what
#: makes this survive a CLUSTERED outage: the estimate is only contaminated once the dark group
#: reaches DOWN to q. p90 (the previous choice) broke at 6 dark tickers of 58 — 10% — after which
#: the inferred rotation jumped to the dark group's own age and the outage hid itself completely.
LADDER_QUANTILE = 0.25
#: Trim passes: tickers beyond the current allowance cannot be part of the rotation that defines
#: it, so they are dropped and the rotation is re-measured from the survivors until the set stops
#: shrinking. Ordinary robust (sigma-clipping style) estimation, not a second alarm.
MAX_TRIM_PASSES = 5
#: FAIL-CLOSED: a cluster boundary at or below the quantile read point means the read is inside a
#: dark group and no honest rotation can be measured. Detected as an anomalous STEP in the ladder.
#: MEASURED on the live 57-ticker healthy roster: steps median 17.0s, max 67.9s — natural
#: unevenness tops out at 4.0x the median. The real dark ticker (SATS) creates a step 472,810x the
#: median. Ten sits between them with margin on both sides; it is a ladder-SHAPE ratio, not a
#: seconds constant, and it is never used to judge lateness — only whether the ladder is readable.
CLUSTER_STEP_RATIO = 10.0
#: A median step needs at least this many steps to be meaningful.
MIN_STEPS_FOR_SHAPE = 3
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

    It is read at a LOW quantile (age(q) = q * cycle, so cycle = (age_q - newest) / q) and then
    ITERATIVELY TRIMMED, because a CLUSTERED outage — many tickers going dark together — otherwise
    contaminates the very estimate meant to catch it. Measured breakdown on a 58-ticker roster with
    a dark group at 8000s: the previous p90 reading failed at 6 dark tickers (10%), and past that
    point the inferred rotation simply became the dark group's own age, so the outage hid itself at
    any size. Reading at q=0.25 and re-measuring from the survivors holds to roughly 35 of 58 (60%)
    dark, and to ~40 of 58 (69%) when the group is further behind.

    HONEST LIMIT: beyond roughly two thirds of the roster dark SIMULTANEOUSLY at a moderate age,
    the ladder no longer contains enough healthy structure to measure and the group can still mask
    itself. That is an extreme partial outage; a full stop is caught by the roster-loop check.

    Anchored on the NEWEST clock, because a uniform offset — every clock ageing together once the
    collection window closes, or while the loop is wedged — must not by itself look like a
    per-ticker skip. That condition is caught by the roster-loop liveness check instead, so this
    function never has to distinguish "everyone is late" from "one ticker was skipped".

    Floored at STALE_LIMIT_SECS so the per-ticker rule is never STRICTER than the aggregate bound.
    Small rosters need no special case: on a handful of tickers the q=0.25 index sits at the newest
    clock, the measured rotation collapses to 0, and the flat floor applies.
    """
    if not ages_sorted:
        return float(STALE_LIMIT_SECS), 0.0, True

    def _read_index(ages):
        return min(len(ages) - 1, int(len(ages) * LADDER_QUANTILE))

    def _measure(ages):
        return max(0.0, (ages[_read_index(ages)] - ages[0]) / LADDER_QUANTILE)

    # FAIL-CLOSED MEASURABILITY. Past the estimator's breakdown point the quantile read point sits
    # INSIDE the dark group, and the rotation it returns is the dark group's own age — which
    # silently licenses the outage instead of reporting it. Detect that directly: walk the ladder
    # steps up to the read point and look for a cluster boundary. A boundary at or below the read
    # point means everything from there up is a separate population, so there is not enough healthy
    # ladder left to measure and the caller must ALERT rather than trust a fabricated number.
    steps = [b - a for a, b in zip(ages_sorted, ages_sorted[1:_read_index(ages_sorted) + 1])]
    if len(steps) >= MIN_STEPS_FOR_SHAPE:
        ordered = sorted(steps)
        median_step = ordered[len(ordered) // 2]
        if max(steps) > CLUSTER_STEP_RATIO * max(median_step, 1e-9):
            return None, None, False

    # MEMBERSHIP is a tighter question than the VERDICT. A ticker more than ONE full rotation
    # behind the newest is by definition not part of the rotation currently being measured, so the
    # trim cuts at one rotation; ROTATIONS_ALLOWED then decides how late is too late. Using the
    # generous verdict multiplier to trim leaves a contaminated seed uncut — measured: a 50% dark
    # group at 8000s stayed hidden because nothing ever fell outside its own inflated allowance.
    work = list(ages_sorted)
    rotation = _measure(work)
    for _ in range(MAX_TRIM_PASSES):
        cut = work[0] + max(float(STALE_LIMIT_SECS), rotation)
        keep = [a for a in work if a <= cut]
        if len(keep) < 3 or len(keep) == len(work):
            break
        work = keep
        rotation = _measure(work)
    allowance = ages_sorted[0] + max(float(STALE_LIMIT_SECS), ROTATIONS_ALLOWED * rotation)
    return allowance, rotation, True


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
            allowance, rotation, measurable = rotation_allowance(ages_sorted)
            if not measurable:
                # FAIL CLOSED: the ladder no longer has enough healthy structure to measure a
                # revisit obligation. Never report OK on an unmeasurable roster, and never fall
                # back to the flat aggregate bound as if it were a per-ticker rule.
                _emit("ALERT", f"ROSTER LIVENESS UNMEASURABLE: the per-ticker ladder is dominated "
                               f"by a dark group, so no revisit obligation can be measured "
                               f"({len(clocked)} clocked ticker(s), newest {ages_sorted[0]:.0f}s, "
                               f"oldest {ages_sorted[-1]:.0f}s) — overall collection still looks "
                               f"live (newest snapshot {age:.0f}s)")
                return 1
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
