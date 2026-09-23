"""1m bar collection loop: a cheap, always-on, viewport-independent sweep that banks 1m
bars for the WHOLE enrolled universe (mirrors the terrain loop's RC-1 design for levels),
its bounded worker pool, the bar persister, and start/stop. Extracted from server.py
(RC-REHAB-1, 2026-09-23, forty-fifth slice). `_bars_loop_running` / `_bars_loop_thread`
are REBOUND here; read them as `bars_loop.<name>`. Server-owned runtime (the logger roster,
the quote memo, the in-memory 1m candles) is read through a lazy `import server as _srv`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


#: RC-69 — BAR COLLECTION SERVICE. Collection is not a side-effect of display.
#: Bars used to be written only inside _fetch_state (the render path), so a ticker's chart
#: decayed to whenever it was last LOOKED AT. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar
#: lag 3.1 min vs QQQ 19.1 and IWM 19.1 (off screen) — while all three had ~1.0 min SNAPSHOT lag.
#: The quotes were current; the bars were not. 39.8% of all snapshots (122,795/308,796) carry
#: unfilled outcomes because fill_outcomes reads price_bars_1m for the forward price and the bars
#: were never written. This loop mirrors _terrain_loop (RC-1), which solved the identical problem
#: for levels: a cheap, always-on, viewport-independent path over the WHOLE enrolled universe.
BARS_REFRESH_SEC: float = 30.0


#: Quotes are far cheaper than chains; this pool is deliberately small so bar collection can never
#: contend with the operator card the way an unbounded sweep did at the open (TERRAIN_WORKERS=2).
#:
#: RC-243 (2026-08-04, PM GO executed post-RTH): sized DOWN 3 -> 2. The comment above reasons about
#: the API this loop READS FROM; the binding constraint is the seam it WRITES THROUGH. Every bar
#: upsert serializes on the single process-wide db._TIER1_SNAPSHOT_WRITE_LOCK, so workers past the
#: first cannot parallelise — they queue, and each extra contender lengthens the queue against a
#: file that reached 27.3 GB. MEASURED on the live console: threads ed_bars_0/1/2 took 426/407/405
#: lock waits (1,238 of them on upsert_1m_bars vs 449 on insert_snapshot), lifetime max wait
#: 180,340 ms, recent-window max 64,229 ms, with busy_retry_count 0 — the wait is on the Python
#: mutex, not SQLite's busy handler. Two workers keep the loop concurrent with the quote fetch
#: (which is the latency this pool exists to hide) while cutting write-seam contenders by a third.
BARS_WORKERS: int = 2


_bars_loop_running: bool = False


_bars_loop_thread: threading.Thread | None = None


def _persist_1m_bars(tk: str, bars) -> int:
    """THE single price_bars_1m writer in the console (RC-69 single-faucet contract).

    Both producers of banked 1m bars — the live quote->accumulator collection service and
    the RC-484 enrollment history seed — persist through here, so the console has exactly
    ONE place that writes the canonical bar table. A second write call site is how
    collection once drifted into the render path; the audit counts the literal db-write
    call, so the invariant is that this function is its only occurrence. ``bars`` may be
    Candle objects (accumulator) or vendor candle dicts (history seed) — the db writer
    accepts both shapes."""
    import server as _srv                      # runtime: get_db (monkeypatched by tests)

    return _srv.get_db().upsert_1m_bars(tk, bars)


def _bars_collect_one(tk: str) -> str:
    """Quote -> accumulator -> price_bars_1m for ONE ticker. Never raises."""
    import server as _srv

    try:
        client = _srv.get_client()
        q = _srv._memoized_quote_response(tk, client=client)   # RC-112/W3-C8: one vendor faucet
        if q is None or getattr(q, "status_code", None) != 200:
            return "error:quote_http"
        node = q.json().get(tk) or {}
        fields = _srv._parse_quote_node_session_fields(node)
        # RC-38 single source: a raw float() on a Schwab leaf silently admits NaN/inf, and a NaN
        # price would enter the bar series as a real value. One canonical reader; absence stays
        # absence.
        from numeric_contract import float_positive_or_none

        px = float_positive_or_none(fields.get("last"))
        if px is None:
            px = float_positive_or_none(fields.get("mark"))
        if px is None:
            return "skip:no_price"      # absence reads as absence — never a fabricated tick
        _srv._candles_1m.tick(tk, px, time.time(), total_volume=fields.get("total_volume"))
        bars = _srv._candles_1m.get_bars(tk)
        if not bars:
            return "ok:no_completed_bar"
        _persist_1m_bars(tk, bars)
        return "ok:persisted"
    except Exception as e:
        log.debug("bars collect %s: %s", tk, e)
        return f"error:{type(e).__name__}"


def _bars_loop() -> None:
    import server as _srv

    log.info("Bar collection loop started (quotes only, whole enrolled universe, viewport-independent)")
    while _bars_loop_running:
        cycle_start = time.monotonic()
        try:
            with _srv._logger_lock:
                tickers = list(_srv._logger_tickers)
        except Exception:
            tickers = list(_srv.CORE_TICKERS)
        # RC-48: only capturable sessions. A market-closed tick would persist a frozen bar.
        if tickers and _srv._is_loggable_session():
            try:
                with ThreadPoolExecutor(max_workers=BARS_WORKERS,
                                        thread_name_prefix="ed_bars") as pool:
                    list(pool.map(_bars_collect_one, tickers))
            except Exception as e:
                log.warning("bars loop cycle failed: %s", e)
        sleep_end = time.monotonic() + max(1.0, BARS_REFRESH_SEC - (time.monotonic() - cycle_start))
        while _bars_loop_running and time.monotonic() < sleep_end:
            time.sleep(0.5)


def start_bars_loop() -> None:
    """Start bar collection. Refuses under pytest for the same reason as the terrain loop:
    a production thread inside the test process mutates shared state no test controls (RC-5)."""
    global _bars_loop_running, _bars_loop_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        log.debug("bars loop not started: running under pytest")
        return
    if _bars_loop_running:
        return
    _bars_loop_running = True
    _bars_loop_thread = threading.Thread(target=_bars_loop, name="bars-loop", daemon=True)
    _bars_loop_thread.start()


def stop_bars_loop() -> None:
    global _bars_loop_running
    _bars_loop_running = False
