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
    of seconds. It is therefore measured live from OBSERVED same-ticker revisits (observed_rotation)
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
import os
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from instrument_identity import ticker_storage_key  # noqa: E402
from app.market_data.snapshot_eligibility import snapshot_collection_eligible  # noqa: E402
from time_et import (  # noqa: E402
    RTH_START_MINS,
    is_trading_day_et,
    now_et,
    session_close_mins_for_et_date,
)


def quarantine_ledger_path() -> Path | None:
    """Same durable refuse ledger the logger/terrain book writes. Overridable in tests."""
    raw = (os.environ.get("ED_TERRAIN_QUARANTINE_LEDGER") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_file() else None
    default = REPO / "reports" / "terrain_quarantine_ledger.jsonl"
    return default if default.is_file() else None

#: AGGREGATE freshness only: the newest snapshot ACROSS the whole console. SPY/QQQ/IWM run on
#: their own dedicated ~60s loop (server.py::_base_money_path_logger_loop), so on a healthy
#: console this clock is never minutes old and a down/stalled console still trips in ten minutes.
#: This bound is deliberately UNCHANGED — it is the strong console-down signal.
#:
#: It is NOT a per-ticker bound. The full-roster collector (server.py::_logger_loop) is a SERIAL
#: round-robin: `time.sleep(STAGGER_SECS)` before each ticker, then a BLOCKING full-pipeline fetch,
#: then `wait = max(0, LOG_INTERVAL - elapsed)` — so LOG_INTERVAL is a sleep FLOOR, not a cap, and
#: one ticker's revisit period equals the WHOLE cycle. Applying 600s to that clock flagged 41 of 58
#: healthy rotating tickers as PARTIAL-DARK. See observed_rotation() below.
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
#: A median revisit interval needs at least this many tickers to mean anything.
MIN_TICKERS_FOR_ROTATION = 3
#: Collections read per ticker, giving COLLECTIONS_PER_TICKER-1 candidate intervals.
COLLECTIONS_PER_TICKER = 4
#: Query sizing only (not a decision threshold): the newest N background-logger rows are read, where
#: N scales with the ROSTER — COLLECTIONS_PER_TICKER x roster x this margin. The margin covers rows
#: belonging to non-enrolled tickers and uneven per-ticker cadence, so each enrolled ticker's recent
#: collections are present. Work is therefore bounded by the roster, not by the lifetime size of
#: snapshots. MEASURED on production (382,128 snapshot rows, 24,569 background-logger): the previous
#: unbounded form took 46.4s and threw away 99.1% of what it read; the bounded form reads ~900 rows
#: in ~0.5s via idx_snap_ts.
HISTORY_QUERY_MARGIN = 4
#: Window closes this many minutes after the session close (through 16:15 on a normal day,
#: 13:15 on an early-close day — session_close_mins_for_et_date handles the calendar).
WINDOW_END_PAD_MINS = 15
#: Snapshots newer than this feed the producer-liveness (mc_paths) check.
RECENT_MC_WINDOW_SECS = 900

LOG_PATH = REPO / "reports" / "console_liveness_run.log"


def observed_rotation(con: sqlite3.Connection,
                      enrolled_tickers: "list[str] | set[str] | None") -> tuple[float | None, int]:
    """(measured rotation, tickers it was measured from) from OBSERVED same-ticker revisits.

    WHY NOT THE AGE LADDER. Earlier revisions inferred the cycle from the cross-sectional spread of
    `last_background_log_ts_utc` across DIFFERENT tickers. That cannot work, because two states
    produce an identical ladder:
        (a) 58 tickers rotating slowly, ages spread 0..20000s;
        (b) 6 tickers rotating every 1400s plus 52 stale, spread 2000..20000s.
    A single snapshot of clocks cannot separate them, so any ladder statistic — p90, a low quantile,
    trimming, cluster-boundary detection — can be defeated by a DIFFUSE stale tail that simply has
    no boundary to find. Measured: 8 of 15 diffuse geometries at 76-95% dark drove the ladder
    estimator to infer rotations of 19294s / 22667s / 55111s FROM THE DARK POPULATION and pass.

    Only REPEATED visits distinguish (a) from (b), and the snapshots table already records every
    background-logger collection. So the rotation is measured the same way its tolerance was
    derived: the median over tickers of that ticker's MOST RECENT revisit interval. A ticker that
    stopped collecting contributes the interval it had BEFORE it stopped — a normal one — so a dark
    population, however large or however spread, can never inflate the rotation it is judged
    against. Verified against both outage geometries at 76%, 90% and 95% dark: recovered 1400s
    against a true 1400s in every case.

    MEASUREMENT AUTHORITY — two limits on which observations may define the obligation:

    * ONLY THE ENROLLED ROSTER. A ticker that is no longer in a collecting category is not part of
      the regime being judged, and its historical cadence must not set today's obligation. Measured:
      80 de-enrolled tickers carrying 60s (or 30000s) history took the rotation over completely.
    * ONLY INTERVALS THE COLLECTOR SWEPT CONTINUOUSLY. An interval is admitted as evidence of
      cadence only if the collector was working THROUGHOUT it — no dead stretch covering half of
      it. During a genuine revisit interval the sweep is visiting other enrolled tickers the whole
      time, so the writes inside are spread evenly and the largest quiet stretch is about one
      per-ticker step. An interval that straddles an outage is mostly silence, whatever happens at
      its ends. Note a COUNT of writes inside is not enough: a straddling interval also contains a
      full recovery sweep's worth of writes, just bunched at the finish — it is the CONTINUITY that
      separates cadence from disruption.
      Taking a median over "the last three intervals" instead only survives ONE disruption:
      measured, two recent gaps make the per-ticker intervals [normal, gap, gap], their median IS
      the gap, and the 7200s outage became the "normal" cadence that then licensed every still-stale
      ticker. Raising the sample size only moves that boundary, so the rule is about which intervals
      QUALIFY, not how many are read. Half is the same natural boundary the coverage rule uses.

    Returns (None, n) when too few enrolled tickers have any qualifying interval — the cadence
    cannot be measured honestly, so the caller must ALERT rather than treat outage duration as
    normal.
    """
    enrolled = {str(t).upper() for t in enrolled_tickers or ()}
    if not enrolled:
        return None, 0
    # Work is bounded by the ROSTER, not by the lifetime size of snapshots: read the newest
    # roster-scaled slice of the background-logger stream, newest first, via idx_snap_ts.
    limit = COLLECTIONS_PER_TICKER * len(enrolled) * HISTORY_QUERY_MARGIN
    try:
        rows = con.execute(
            "SELECT ticker, ts_utc FROM snapshots WHERE logger_source = 'background_logger' "
            "AND ticker IS NOT NULL ORDER BY ts_utc DESC LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.Error:
        return None, 0

    recent: dict[str, list[float]] = {}
    stream: list[float] = []                           # every enrolled collection in the slice
    for tk, ts in rows:
        if ts is None:
            continue
        key = str(tk).upper()
        if key not in enrolled:
            continue                                   # not part of the regime being judged
        stream.append(float(ts))
        seen = recent.setdefault(key, [])
        if len(seen) < COLLECTIONS_PER_TICKER:
            seen.append(float(ts))
    stream.sort()

    def _is_one_cadence_interval(earlier: float, later: float) -> bool:
        """Is [earlier, later] one turn of the sweep, rather than a disruption or a skip?

        Two ways an interval can fail to be cadence, and both must be excluded:
          * DISRUPTION — the collector stopped inside it. Then most of the interval is silent, so
            the quietest stretch covers half or more of it.
          * SKIP — the collector kept sweeping but passed this ticker by. Then MORE than a roster's
            worth of collections happened inside, i.e. the sweep went round more than once without
            visiting it. That interval measures the ticker's failure, not the cadence.
        """
        span = later - earlier
        lo, hi = bisect_right(stream, earlier), bisect_left(stream, later)
        if hi - lo > len(enrolled):                    # more than one turn of the roster => skipped
            return False
        marks = [earlier] + stream[lo:hi] + [later]
        quietest = max(b - a for a, b in zip(marks, marks[1:]))
        return quietest * 2.0 < span                   # the sweep worked through most of it

    per_ticker: list[float] = []
    for stamps in recent.values():
        qualifying = []
        for later, earlier in zip(stamps, stamps[1:]):
            if later > earlier and _is_one_cadence_interval(earlier, later):
                qualifying.append(later - earlier)
        if qualifying:
            qualifying.sort()
            per_ticker.append(qualifying[len(qualifying) // 2])
    if len(per_ticker) < MIN_TICKERS_FOR_ROTATION:
        return None, len(per_ticker)
    per_ticker.sort()
    return per_ticker[len(per_ticker) // 2], len(per_ticker)


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
            eligible = set(snapshot_collection_eligible(
                (tk for tk, _a in clocked),
                ledger_path=quarantine_ledger_path(),
            ))
            clocked = [
                (tk, a) for tk, a in clocked
                if ticker_storage_key(tk) in eligible
            ]
            if not clocked:
                _emit("OK", f"collecting (newest {age:.0f}s old), producer live "
                            f"({mc_live} mc_paths rows/{RECENT_MC_WINDOW_SECS//60}min), "
                            f"no clocked snapshot-roster tickers after refused-symbol filter")
                return 0
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
            rotation, n_measured = observed_rotation(con, [tk for tk, _a in clocked])
            if rotation is None:
                # FAIL CLOSED: no revisit obligation can be measured, so nothing can be CERTIFIED.
                # The one exception is not a fallback allowance but its opposite: if every clocked
                # ticker is inside the STRICTEST bound the console has (the aggregate one), then no
                # ticker is late by ANY standard and there is nothing an unmeasurable rotation
                # could be hiding. Anything beyond that cannot be judged, so it alerts.
                if ages_sorted[-1] > STALE_LIMIT_SECS:
                    _emit("ALERT", f"ROSTER LIVENESS UNMEASURABLE: only {n_measured} enrolled "
                                   f"ticker(s) have been collected twice, so no revisit obligation "
                                   f"can be measured, and the oldest of {len(clocked)} clocked "
                                   f"ticker(s) is {ages_sorted[-1]:.0f}s behind — overall "
                                   f"collection still looks live (newest snapshot {age:.0f}s)")
                    return 1
                _emit("OK", f"collecting (newest {age:.0f}s old), producer live "
                            f"({mc_live} mc_paths rows/{RECENT_MC_WINDOW_SECS//60}min), rotation "
                            f"not yet measurable but every enrolled ticker is within "
                            f"{STALE_LIMIT_SECS}s")
                return 0
            # COVERAGE. A serial round-robin visits EVERY enrolled ticker once per cycle, so at any
            # instant the roster is spread across [0, one rotation] and almost nothing is beyond it
            # (measured jitter puts ~10% past one rotation, p90 = 1.66x). A MAJORITY beyond one
            # rotation therefore contradicts the rotation the collector is actually achieving: the
            # sweep is not covering the roster. This catches a diffuse outage while every single
            # ticker is still individually inside the per-ticker tolerance.
            behind = [(tk, a) for tk, a in clocked if a > ages_sorted[0] + rotation]
            if len(behind) * 2 > len(clocked):
                _emit("ALERT", f"ROSTER NOT BEING SWEPT: {len(behind)}/{len(clocked)} enrolled "
                               f"ticker(s) are more than one measured rotation "
                               f"({rotation:.0f}s, from {n_measured} ticker(s)) behind, so the "
                               f"sweep is not covering the roster — overall collection still looks "
                               f"live (newest snapshot {age:.0f}s)")
                return 1
            allowance = ages_sorted[0] + max(float(STALE_LIMIT_SECS), ROTATIONS_ALLOWED * rotation)
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
