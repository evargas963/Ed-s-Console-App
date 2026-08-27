#!/usr/bin/env python3
"""CR-01 capture daemon: Schwab Streamer -> bus -> stream_capture.db. CAPTURE-ONLY.

Consensus plan v1.2: this process owns the ONLY Schwab stream (single-streamer-owner
rule) and writes ONLY stream_capture.db. No UI consumes anything until CR-CAP.

Acceptance instrumentation built in (measured, not asserted):
  - JSON-handle latency p50/p99, per-service message counts, bus drop counters,
    max writer-queue depth, rows/commits — printed at exit and written every 10s to
    reports/stream_capture_status.json (the operator-visible heartbeat).
  - First raw message per service saved to reports/stream_raw_sample_<svc>.json.
    Field maps are NAMED-KEY, verified live 2026-07-21 against those samples (the
    original numeric maps parsed all-None and were caught by this exact mechanism).

Usage:
    python tools/run_stream_capture.py --symbols SPY,QQQ,IWM --duration-min 390
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stream_spine import (  # noqa: E402
    COALESCE,
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    bar_msg,
    quote_msg,
)

STATUS_PATH = ROOT / "reports" / "stream_capture_status.json"
OWNER_LOCK = ROOT / "data" / "stream_capture.lock"


def acquire_owner_lock() -> int:
    """ENFORCE the single-streamer-owner rule (Cursor review HIGH: it was prose only).

    Exclusive pidfile: a second daemon refuses to start; a stale lock (dead pid) is
    reclaimed. NOTE the known remaining conflict: server.py's start_order_flow_stream
    can open its own Schwab stream — registered CR-01 follow-up is to route it through
    this daemon's bus at CR-03; until then do not run both stream surfaces at once.
    """
    import os
    for attempt in (1, 2):
        try:
            fd = os.open(str(OWNER_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            try:
                pid = int(OWNER_LOCK.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            alive = False
            if pid:
                try:
                    import psutil
                    alive = psutil.pid_exists(pid)
                except ImportError:
                    alive = True   # can't verify -> fail closed, require manual removal
            if alive:
                raise SystemExit(
                    f"FATAL: another stream-capture owner holds {OWNER_LOCK} (pid {pid}). "
                    "Single-streamer-owner rule: stop it first, or remove a stale lock."
                ) from None
            if attempt == 1:
                OWNER_LOCK.unlink(missing_ok=True)   # stale (dead pid): reclaim once
    raise SystemExit(f"FATAL: could not acquire {OWNER_LOCK}")


def release_owner_lock(fd: int) -> None:
    import os
    try:
        os.close(fd)
    finally:
        OWNER_LOCK.unlink(missing_ok=True)

#: VERIFIED live 2026-07-21 against reports/stream_raw_sample_levelone_equities.json:
#: this schwab-py install labels fields by NAME (numeric map parsed all-None — caught by
#: the raw-sample check on first connection, as designed).
LEVELONE_FIELDS = {"BID_PRICE": "bid", "ASK_PRICE": "ask", "LAST_PRICE": "last",
                   "BID_SIZE": "bid_size", "ASK_SIZE": "ask_size",
                   "TOTAL_VOLUME": "total_volume", "LAST_SIZE": "last_size",
                   "QUOTE_TIME_MILLIS": "quote_time_ms", "TRADE_TIME_MILLIS": "trade_time_ms"}
CHART_FIELDS = {"OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low",
                "CLOSE_PRICE": "close", "VOLUME": "volume", "CHART_TIME_MILLIS": "bar_start_ms"}


def parse_stream_item(item: dict, field_map: dict[str, str]) -> dict:
    """Numeric-keyed streamer item -> named dict; 'key' carries the symbol."""
    out: dict = {"symbol": str(item.get("key") or "").upper()}
    for k, name in field_map.items():
        if k in item:
            out[name] = item[k]
    return out


# ── ALPACA MOVED OUT (isolated research collector) ───────────────────────────
# The CR-02 Alpaca IEX prints/NBBO leg used to live HERE, co-producing onto this daemon's
# bus/writer and its shared tables (stream_quotes_raw/stream_prints_raw). It was an UNPROVEN
# research feed with no consumer, so it now lives in the ISOLATED, unscheduled collector
# alpaca_iex_capture.py, which writes its OWN alpaca_capture.db and can never write this db.
# This daemon is canonical SCHWAB Collect only — no cross-vendor producer on its bus/writer.

# ── half-open-socket guard (2026-07-23, observed live) ───────────────────────
# A network blip left the Schwab websocket half-open: connected on paper, silent in practice.
# No error ever fires on a half-open TCP socket, so error-driven reconnect logic never
# triggers — the feed sat STALE for minutes while the process looked healthy (py-spy: event
# loop idle at _poll). Staleness itself must therefore force the reconnect.
STREAM_STALE_RECONNECT_SEC = 90.0    #: LEVELONE quiet this long -> recycle stream
RECONNECT_COOLDOWN_SEC = 180.0       #: never login-spam Schwab on quiet tape


def stream_needs_recycle(age_sec: float | None, seen_data: bool,
                         since_last_reconnect: float) -> bool:
    """Half-open-guard decision (pure; unit-tested). Recycle ONLY when:
    data has flowed before (a never-beat service is a subscribe problem, not a
    half-open socket), the feed has been quiet past the stale bar, and the
    cooldown has passed (quiet after-hours tape must not cycle logins)."""
    if age_sec is None or not seen_data:
        return False
    return (age_sec > STREAM_STALE_RECONNECT_SEC
            and since_last_reconnect > RECONNECT_COOLDOWN_SEC)


class CaptureStats:
    def __init__(self, sample_dir: Path | None = None) -> None:
        #: None (tests' default) = record which services were seen, write NO files.
        #: The daemon passes reports/ so live raw samples land for field-map verification.
        self.sample_dir = sample_dir
        self.handle_ms: list[float] = []
        self.per_service: dict[str, int] = {}
        self.raw_sampled: set[str] = set()

    def record(self, service: str, dur_ms: float) -> None:
        self.per_service[service] = self.per_service.get(service, 0) + 1
        if len(self.handle_ms) < 500_000:
            self.handle_ms.append(dur_ms)

    def p(self, q: float) -> float | None:
        # statistics.quantiles requires n>=2; a quiet first heartbeat must not
        # abort the capture loop (Bugbot 2026-07-21 MEDIUM).
        n = len(self.handle_ms)
        if n == 0:
            return None
        if n == 1:
            return round(self.handle_ms[0], 3)
        return round(statistics.quantiles(self.handle_ms, n=100)[int(q) - 1], 3)


def save_raw_sample(service: str, msg: dict, stats: CaptureStats) -> None:
    if service in stats.raw_sampled:
        return
    stats.raw_sampled.add(service)
    if stats.sample_dir is None:
        return
    p = stats.sample_dir / f"stream_raw_sample_{service.lower()}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(msg, indent=2, default=str), encoding="utf-8")


def make_handler(service: str, field_map: dict, topic_kind: str, bus: MessageBus,
                 health: HealthRegistry, stats: CaptureStats):
    def handler(msg: dict) -> None:
        t0 = time.perf_counter()
        save_raw_sample(service, msg, stats)
        health.beat(service)
        for item in msg.get("content") or []:
            parsed = parse_stream_item(item, field_map)
            sym = parsed.get("symbol")
            if not sym:
                continue
            if topic_kind == "quote":
                out = quote_msg(symbol=sym, bid=parsed.get("bid"), ask=parsed.get("ask"),
                                last=parsed.get("last"), bid_size=parsed.get("bid_size"),
                                ask_size=parsed.get("ask_size"),
                                last_size=parsed.get("last_size"),
                                total_volume=parsed.get("total_volume"),
                                quote_time_ms=parsed.get("quote_time_ms"),
                                trade_time_ms=parsed.get("trade_time_ms"), src="schwab_l1")
            else:
                out = bar_msg(symbol=sym, bar_start_ms=parsed.get("bar_start_ms"),
                              open=parsed.get("open"), high=parsed.get("high"),
                              low=parsed.get("low"), close=parsed.get("close"),
                              volume=parsed.get("volume"), src="schwab_chart")
            bus.publish(f"{topic_kind}.{sym}", out)
        stats.record(service, (time.perf_counter() - t0) * 1000.0)
    return handler


def write_status(bus: MessageBus, health: HealthRegistry, writer: CaptureWriter,
                 stats: CaptureStats, max_qdepth: int) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "ts": time.time(), "health": health.report(),
        "published": bus.published, "drops": bus.drop_counts(),
        "rows_written": writer.rows_written, "commits": writer.commits,
        "insert_errors": writer.insert_errors,
        "max_writer_queue_depth": max_qdepth,
        "per_service": stats.per_service,
        "handle_ms_p50": stats.p(50), "handle_ms_p99": stats.p(99),
    }, indent=2), encoding="utf-8")


async def run(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    lock_fd = acquire_owner_lock()
    try:
        return await _run_locked(symbols, duration_min, db_path)
    finally:
        # The lock's lifetime is the WHOLE session — login/subscribe failures and
        # KeyboardInterrupt included (Cursor round-2 HIGH: it leaked on init paths).
        release_owner_lock(lock_fd)


async def _shutdown_sequence(pump_task, writer_task, stop, wsub,
                             extra_producers: tuple = ()) -> None:
    """SHUTDOWN ORDER IS THE CONTRACT (Cursor round-2 HIGHs).

    1) Quiesce the PRODUCER first — after this await nothing can publish, so the
       writer's drain sees a queue that only shrinks (closes the in-flight
       pump→bus→queue loss window).
    2) THEN stop the writer and AWAIT it to completion — never cancel it. `CaptureWriter.run`
       self-bounds its drain (drain_deadline_s) and always finishes the flush it started, so it
       returns with NO worker thread touching the connection; cancelling it with a timeout would
       instead leave a to_thread worker mid-write and race the subsequent close() on the same
       sqlite handle. Undrained rows past the deadline are counted (writer.drain_lost), not hidden.
    """
    # ALL producers quiesce before the writer drains. `extra_producers` is kept as a general
    # parameter (now empty — the Schwab pump is the sole producer), so any producer must be dead
    # before the drain starts (same law).
    for task in (pump_task, *extra_producers):
        task.cancel()
    for task in (pump_task, *extra_producers):
        try:
            await task
        except asyncio.CancelledError:
            pass  # expected: we cancelled it
        except Exception as exc:  # noqa: BLE001 — bounded shutdown; report, never hang
            print(f"shutdown: producer ended with {type(exc).__name__}: {exc}")
    stop.set()
    try:
        await writer_task
    except Exception as exc:  # noqa: BLE001
        print(f"shutdown: writer ended with {type(exc).__name__}: {exc}")


async def _run_locked(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    from config import build_config
    from schwab_client import build_client_from_token

    cfg = build_config(str(ROOT))
    state = build_client_from_token(api_key=cfg.api_key, app_secret=cfg.app_secret,
                                    token_path=cfg.token_path)
    if not state.ok or state.client is None:
        print(f"FATAL: Schwab client init failed: {state.message}")
        return 2

    bus = MessageBus()
    health = HealthRegistry()
    stats = CaptureStats(sample_dir=ROOT / "reports")
    writer = CaptureWriter(db_path) if db_path else CaptureWriter()
    # OPTIONS PERSISTENCE RIDES THIS ONE WRITER. The options collector publishes option frames onto
    # the SAME bus; the writer persists them through its OWN connection via the registered
    # persister — never a second connection to stream_capture.db (the "competing writers" defect).
    # Additive and soft: a persister that will not import must not stop equity capture.
    try:
        from options_stream_collect import make_capture_topic_writer, reset_options_ingest_counters
        _opt_persist = make_capture_topic_writer()
        writer.register_topic_writer("optionchain", _opt_persist)
        writer.register_topic_writer("optionbook", _opt_persist)
        # Reset the drop-accounting window ONCE for the whole daemon run (not per watchdog recycle),
        # so `offered` and the writer's cumulative option_rows describe the same interval.
        reset_options_ingest_counters()
    except Exception as exc:  # noqa: BLE001 — options persistence is additive
        print(f"options persister not registered (equity capture unaffected): "
              f"{type(exc).__name__}: {exc}")
    wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)   # writer sees everything
    _ui_future = bus.subscribe("quote.", policy=COALESCE)        # proves coalesce path live
    stop = asyncio.Event()

    try:
        return await _run_streaming(symbols, duration_min, bus, health, stats,
                                    writer, wsub, stop, state)
    finally:
        writer.close()   # every exit path incl. login/subscribe failure (round-3 MEDIUM)


async def _schwab_connect(state, symbols, bus, health, stats, stop):
    """Fresh Schwab stream: login + handlers + subs -> running pump task.
    Used at start AND by the half-open watchdog (a recycle is a clean rebuild —
    never an attempt to resuscitate a dead StreamClient)."""
    from schwab.streaming import StreamClient

    stream = StreamClient(state.client)
    await stream.login()
    stream.add_level_one_equity_handler(
        make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus, health, stats))
    stream.add_chart_equity_handler(
        make_handler("CHART_EQUITY", CHART_FIELDS, "bar1m", bus, health, stats))
    await stream.level_one_equity_subs(symbols)
    await stream.chart_equity_subs(symbols)
    print(f"subscribed {len(symbols)} symbols x2 services (key accounting: "
          f"{len(symbols) * 2} keys used)")

    # OPTIONS COLLECTION rides THIS daemon's single stream — the one Collect authority. It was
    # first built onto the server's UI stream, a second Schwab surface with its own key
    # accounting and persistence; it belongs here. A recycle is a CLEAN REBUILD (the same law the
    # equity pump follows), so stop any prior options state, then re-establish on the new stream.
    # equity_key_services=2 because THIS stream holds two equity services (LEVELONE_EQUITIES +
    # CHART_EQUITY) — the budget is sized against the stream actually held, not a hardcoded 3.
    try:
        from options_stream_collect import (
            register_options_handlers, _options_frame_handler,
            start_options_collection, stop_options_collection,
        )
        # A recycle means the OLD socket is dead — await the prior teardown (no vendor unsubscribe,
        # nothing to unsubscribe on a dead socket), then re-establish on the new stream and bus.
        await stop_options_collection("stream_recycle")
        register_options_handlers(stream, _options_frame_handler)
        await start_options_collection(stream, bus=bus, equity_symbols=len(symbols),
                                       equity_key_services=2)
    except Exception as exc:  # noqa: BLE001 — options is additive; equity capture is unaffected
        print(f"options collection did not start (equity capture unaffected): "
              f"{type(exc).__name__}: {exc}")

    async def pump() -> None:
        while not stop.is_set():
            await stream.handle_message()

    return asyncio.create_task(pump())


async def _run_streaming(symbols, duration_min, bus, health, stats,
                         writer, wsub, stop, state) -> int:
    max_qdepth = 0
    writer_task = asyncio.create_task(writer.run(wsub, stop=stop))
    pump_task = await _schwab_connect(state, symbols, bus, health, stats, stop)
    # SCHWAB-ONLY: the Schwab pump is the sole producer on this bus. The Alpaca IEX leg was
    # removed and isolated to alpaca_iex_capture.py (its own db) — no cross-vendor co-producer here.
    deadline = time.monotonic() + duration_min * 60 if duration_min > 0 else None
    last_reconnect = time.monotonic()
    try:
        while not stop.is_set():
            await asyncio.sleep(10)
            max_qdepth = max(max_qdepth, wsub.queue.qsize())
            write_status(bus, health, writer, stats, max_qdepth)
            # half-open watchdog: quiet LEVELONE past the bar -> rebuild stream
            age = (health.report().get("LEVELONE_EQUITIES") or {}).get("age_sec")
            seen = stats.per_service.get("LEVELONE_EQUITIES", 0) > 0
            if stream_needs_recycle(age, seen, time.monotonic() - last_reconnect):
                print(f"watchdog: LEVELONE_EQUITIES quiet {age:.0f}s — recycling "
                      f"Schwab stream (half-open guard)")
                last_reconnect = time.monotonic()
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001 — recycle path; reported
                    print(f"watchdog: old pump ended with {type(exc).__name__}: {exc}")
                try:
                    pump_task = await _schwab_connect(state, symbols, bus, health,
                                                      stats, stop)
                except Exception as exc:  # noqa: BLE001 — retry next tick, loudly
                    print(f"watchdog: reconnect FAILED ({type(exc).__name__}: {exc}) "
                          f"— retrying after cooldown")
                    pump_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
            if deadline and time.monotonic() > deadline:
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        # Close options coverage epochs and drain the options writer BEFORE the equity shutdown
        # sequence, so a clean daemon exit leaves no epoch claiming observation past this instant.
        try:
            # PHASE ONE, while the Schwab stream is still LIVE: cancel+await the rotation and
            # unsubscribe the vendor (release option keys). This does NOT close coverage yet —
            # frames just unsubscribed may still be in flight through the pump and writer.
            from options_stream_collect import quiesce_options_collection
            await quiesce_options_collection("daemon_shutdown", unsubscribe=True)
        except Exception as exc:  # noqa: BLE001
            print(f"options quiesce: {type(exc).__name__}: {exc}")
        # Quiesce the pump (no more frames can arrive) and DRAIN the writer (persist in-flight
        # option frames) BEFORE closing coverage. Guarded so a failure here still runs the coverage
        # close and the writer close below (an epoch left open self-heals at the next start's
        # reconcile, but the writer handle must not leak).
        try:
            await _shutdown_sequence(pump_task, writer_task, stop, wsub)
        except Exception as exc:  # noqa: BLE001
            print(f"shutdown sequence: {type(exc).__name__}: {exc}")
        if getattr(writer, "drain_lost", 0):
            print(f"shutdown: WRITER DRAIN DEADLINE — {writer.drain_lost} queued rows lost "
                  "(counted, not hidden)")
        # Flush the options drop-accounting ONCE, now that the writer is JOINED: `offered` (loop
        # counter) and the writer's own option_rows describe the whole daemon run, read with no
        # worker thread live — no cross-thread counter, no mid-flight reset.
        try:
            from options_stream_collect import flush_options_ingest_health, options_ingest_window
            _offered, _win_start = options_ingest_window()
            if _offered or getattr(writer, "option_rows", 0):
                flush_options_ingest_health(writer.db_path, offered=_offered,
                                            written=getattr(writer, "option_rows", 0),
                                            started_ms=_win_start)
        except Exception as exc:  # noqa: BLE001
            print(f"options health flush: {type(exc).__name__}: {exc}")
        try:
            # PHASE TWO, now that no option frame can arrive: close the coverage record. Ordered
            # after the drain so an epoch is never closed while an observation is still coming.
            from options_stream_collect import close_options_coverage
            close_options_coverage("daemon_shutdown")
        except Exception as exc:  # noqa: BLE001
            print(f"options coverage close: {type(exc).__name__}: {exc}")
        writer.close()
        write_status(bus, health, writer, stats, max_qdepth)
        print(json.dumps({
            "rows_written": writer.rows_written, "commits": writer.commits,
            "published": bus.published, "drops": bus.drop_counts(),
            "insert_errors": writer.insert_errors,
            "max_writer_queue_depth": max_qdepth,
            "handle_ms_p50": stats.p(50), "handle_ms_p99": stats.p(99),
            "per_service": stats.per_service, "db": str(writer.db_path),
        }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--duration-min", type=float, default=0.0, help="0 = until Ctrl+C")
    ap.add_argument("--db", default=None, help="override stream_capture.db path (tests)")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    return asyncio.run(run(syms, a.duration_min, a.db))


if __name__ == "__main__":
    raise SystemExit(main())
