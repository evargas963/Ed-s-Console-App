"""OPTIONS FLOW — the ingestion path that keeps persistence OFF the shared stream loop.

WHY THIS EXISTS, mechanically. order_flow_streaming owns ONE StreamClient and one asyncio
message loop. Its service handlers are SYNCHRONOUS callbacks invoked inline from that loop:

    def _level_one_handler(msg: dict) -> None:   # runs ON the loop thread
        ...

Whatever a handler does, the loop is not reading the socket while it does it. The existing
equity handlers are safe because they only touch memory (push_level_one, live_market_plane).
The raw options writer is NOT that: calibration.options_stream_frames.persist_frame opens a
SQLite connection, INSERTs, and COMMITs PER FRAME against a 38.9 GB WAL database. Calling it
from a handler would put disk I/O and fsync on the same thread that services
LEVELONE_EQUITIES, NASDAQ_BOOK and NYSE_BOOK — so an options write stall becomes an equity
stall. That is the failure this module exists to make impossible, before contract volume
makes it likely rather than merely possible.

THE SHAPE. Handler -> bounded in-memory queue -> dedicated WRITER THREAD -> batched commits.

  * A THREAD, not another asyncio task. A task would still run on the loop and a blocking
    sqlite call inside it would stall the loop just the same; only a separate thread lets the
    loop keep reading the socket while sqlite3 (which releases the GIL around its C calls)
    does disk work.
  * BOUNDED, and the producer NEVER BLOCKS. offer() uses put_nowait and, on a full queue,
    DROPS. It must never call put() — blocking the producer to protect memory would convert
    a storage problem into the exact stream stall this module prevents.
  * DROPS ARE COUNTED AND DURABLE, never silent. A dropped frame is a real hole in history,
    and a hole nobody can see later is worse than one that is measured: it would read as "the
    vendor sent nothing". Counters are flushed to options_stream_ingest_health so the gap
    remains provable after the process exits.
  * BATCHED COMMITS. One transaction per drained batch instead of per frame — the per-frame
    commit is where the fsync cost lives.

WHAT THIS DOES NOT DO. It does not decide what to subscribe (options_stream_subscription), it
does not project or interpret frames, and it infers nothing about dealer ownership, inventory
sign, aggressor side or opening/closing intent. It moves bytes from a callback to a table
without standing in the stream's way. Nothing here feeds Decide.
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

#: Queue ceiling. Sized to absorb a burst without unbounded memory: each item is one decoded
#: frame, so this is a memory bound expressed in frames rather than bytes. It is a STARTING
#: BOUND to be measured against, not a proven capacity — measure_ingest_capacity reports the
#: high-water mark so this can be set from evidence instead of taste.
DEFAULT_MAX_QUEUE = 20_000

#: Frames per transaction. Larger batches amortise fsync; too large delays durability and
#: lengthens the write lock others may wait on.
DEFAULT_BATCH_MAX = 500

#: Seconds the writer waits for a partial batch before committing what it has, so a quiet
#: period cannot leave frames sitting unwritten in memory indefinitely.
DEFAULT_BATCH_LINGER_S = 0.25

HEALTH_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS options_stream_ingest_health (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start_ms INTEGER NOT NULL,
    window_end_ms   INTEGER NOT NULL,
    offered         INTEGER NOT NULL,
    written         INTEGER NOT NULL,
    dropped         INTEGER NOT NULL,
    write_errors    INTEGER NOT NULL,
    max_queue_depth INTEGER NOT NULL,
    max_ingest_lag_ms INTEGER,
    batches         INTEGER NOT NULL,
    write_ms_total  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osih_window ON options_stream_ingest_health(window_start_ms);
"""


def ensure_ingest_health_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(HEALTH_TABLE_SQL)
    conn.commit()


@dataclass
class IngestStats:
    """Counters describing what the path actually did — the basis for every claim made about it.

    ``dropped`` is the load-bearing one. offered == written + dropped + in-flight must hold, so
    a shortfall in retained history is always attributable rather than mysterious.
    """
    offered: int = 0
    written: int = 0
    dropped: int = 0
    write_errors: int = 0
    batches: int = 0
    max_queue_depth: int = 0
    max_ingest_lag_ms: int = 0
    write_ms_total: float = 0.0
    started_ms: int = 0
    last_error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "offered": self.offered, "written": self.written, "dropped": self.dropped,
                "write_errors": self.write_errors, "batches": self.batches,
                "max_queue_depth": self.max_queue_depth,
                "max_ingest_lag_ms": self.max_ingest_lag_ms,
                "write_ms_total": round(self.write_ms_total, 3),
                "started_ms": self.started_ms, "last_error": self.last_error,
                "accounted": self.written + self.dropped,
            }


class OptionsFrameIngest:
    """Bounded, non-blocking, drop-counting ingestion of raw options frames.

    Lifecycle: ``start()`` spawns the writer thread; ``offer()`` is called from the stream
    handler (loop thread) and returns immediately; ``stop()`` drains and joins.
    """

    _SENTINEL = object()

    def __init__(self, db_path: str | None = None, *, max_queue: int = DEFAULT_MAX_QUEUE,
                 batch_max: int = DEFAULT_BATCH_MAX,
                 batch_linger_s: float = DEFAULT_BATCH_LINGER_S,
                 persist_batch: Callable[[sqlite3.Connection, list], int] | None = None) -> None:
        # RC-6 LAW, enforced at construction rather than by convention: raw streams NEVER
        # touch the operational database (governance/CONSOLE_REBUILD_PLAN_CR_V1.md S4, marked
        # BLOCKING). Options frames are raw stream data and are no exception — at the canary
        # size alone they would add ~10.4 GB per RTH day to a file already at 38.9 GB.
        # The check resolves the path first, because a basename-only guard is bypassable via
        # `data/x/../ed_console.db`, symlinks or junctions — the same hole CaptureWriter had.
        from pathlib import Path as _P
        if db_path is None:
            from stream_spine import STREAM_DB_DEFAULT
            db_path = STREAM_DB_DEFAULT
        p = _P(db_path).resolve()
        if p.name == "ed_console.db":
            raise ValueError(
                "options ingest must never write the operational DB (RC-6 law): raw stream "
                f"capture belongs in stream_capture.db, got {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(p)
        self.batch_max = int(batch_max)
        self.batch_linger_s = float(batch_linger_s)
        self._q: queue.Queue = queue.Queue(maxsize=int(max_queue))
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        #: Set when the writer thread has exited (cleanly or because storage would not open).
        #: Frames still queued behind a dead writer are UNWRITTEN, and stop() counts them as
        #: dropped rather than letting them evaporate — see _account_for_undrained.
        self._writer_dead = threading.Event()
        self.stats = IngestStats()
        self._persist_batch = persist_batch or _default_persist_batch

    # ---- producer side: runs on the STREAM LOOP THREAD, must stay O(1) and never block ----
    def offer(self, service: str, frame: dict, received_ts_ms: int | None = None) -> bool:
        """Hand a frame to the writer. Returns False if it was DROPPED (queue full).

        Deliberately non-blocking. A full queue means the writer cannot keep up; the correct
        response is to shed this frame and record that we did, not to hold the stream loop
        hostage until storage recovers.
        """
        rx = int(received_ts_ms if received_ts_ms is not None else time.time() * 1000.0)
        with self.stats._lock:
            self.stats.offered += 1
        try:
            self._q.put_nowait((str(service), frame, rx))
        except queue.Full:
            with self.stats._lock:
                self.stats.dropped += 1
            # Rate-limited: under sustained overload this would otherwise become its own
            # I/O problem on the loop thread.
            if self.stats.dropped % 500 == 1:
                log.warning("options ingest DROPPED %d frame(s): writer behind, queue full "
                            "(history will have a measured hole)", self.stats.dropped)
            return False
        depth = self._q.qsize()
        if depth > self.stats.max_queue_depth:
            with self.stats._lock:
                self.stats.max_queue_depth = depth
        return True

    # ---- consumer side: dedicated thread ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self.stats.started_ms = int(time.time() * 1000.0)
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="options_frame_writer", daemon=True)
        self._thread.start()
        log.info("options ingest writer started (queue<=%d, batch<=%d)",
                 self._q.maxsize, self.batch_max)

    def _drain_batch(self) -> list:
        """Block briefly for the first item, then take everything already waiting."""
        batch: list = []
        try:
            first = self._q.get(timeout=self.batch_linger_s)
        except queue.Empty:
            return batch
        if first is self._SENTINEL:
            self._stopping.set()
            return batch
        batch.append(first)
        while len(batch) < self.batch_max:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is self._SENTINEL:
                self._stopping.set()
                break
            batch.append(item)
        return batch

    def _run(self) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=60.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            ensure_ingest_health_schema(conn)
            from calibration.options_stream_frames import ensure_options_stream_schema
            ensure_options_stream_schema(conn)
        except Exception as e:                          # noqa: BLE001
            # A writer that cannot open storage must not take the stream with it. Every
            # subsequent offer() still succeeds and is counted, then dropped on a full queue.
            with self.stats._lock:
                self.stats.write_errors += 1
                self.stats.last_error = f"open: {e}"
            self._writer_dead.set()
            log.error("options ingest writer could not open storage: %s — frames will be "
                      "counted as DROPPED, not silently discarded: %s", e, self.db_path)
            if conn is not None:
                conn.close()
            return

        try:
            while not (self._stopping.is_set() and self._q.empty()):
                batch = self._drain_batch()
                if not batch:
                    continue
                t0 = time.perf_counter()
                try:
                    n = self._persist_batch(conn, batch)
                    # Compute the batch's worst lag BEFORE taking the lock. The first version
                    # looped over all 500 frames while HOLDING stats._lock, and offer() needs
                    # that same lock on the stream-loop thread — measured as a 28 ms worst-case
                    # offer(), i.e. a 28 ms stall of the shared equity/book stream. The lock is
                    # now held for O(1) work only. This is the whole point of the module, so it
                    # is asserted by test_producer_is_never_stalled_by_the_writer.
                    batch_lag = 0
                    for _svc, fr, rx in batch:
                        lag = _frame_lag_ms(fr, rx)
                        if lag is not None and lag > batch_lag:
                            batch_lag = lag
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    with self.stats._lock:
                        self.stats.written += int(n)
                        self.stats.batches += 1
                        self.stats.write_ms_total += elapsed_ms
                        if batch_lag > self.stats.max_ingest_lag_ms:
                            self.stats.max_ingest_lag_ms = batch_lag
                except Exception as e:                  # noqa: BLE001
                    # One bad batch must not end the writer. Count it, keep going: a stopped
                    # writer silently converts every later frame into a drop.
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                    with self.stats._lock:
                        self.stats.write_errors += 1
                        self.stats.last_error = str(e)[:300]
                    log.warning("options ingest batch failed (%d frames): %s", len(batch), e)
        finally:
            try:
                self._flush_health(conn)
            except Exception as e:                      # noqa: BLE001
                log.debug("ingest health flush: %s", e)
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def _flush_health(self, conn: sqlite3.Connection) -> None:
        s = self.stats.snapshot()
        conn.execute(
            "INSERT INTO options_stream_ingest_health (window_start_ms, window_end_ms, offered,"
            " written, dropped, write_errors, max_queue_depth, max_ingest_lag_ms, batches,"
            " write_ms_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s["started_ms"], int(time.time() * 1000.0), s["offered"], s["written"],
             s["dropped"], s["write_errors"], s["max_queue_depth"], s["max_ingest_lag_ms"],
             s["batches"], s["write_ms_total"]))
        conn.commit()

    def _account_for_undrained(self) -> int:
        """Count anything still queued as DROPPED, and say how many.

        Without this the invariant offered == written + dropped silently fails whenever the
        writer dies: a queue full of frames behind a dead writer is neither written nor
        counted, so history has a hole that the counters claim does not exist. That was a real
        defect — the capacity harness measured offered=2000, written=0, dropped=1000, leaving
        1000 frames unaccounted — and it is exactly the class of silent loss this module was
        built to prevent, so it is fixed rather than documented.
        """
        n = 0
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is not self._SENTINEL:
                n += 1
        if n:
            with self.stats._lock:
                self.stats.dropped += n
            log.warning("options ingest: %d frame(s) left unwritten at shutdown — counted as "
                        "DROPPED so the gap in history stays visible", n)
        return n

    def stop(self, timeout: float = 30.0) -> dict[str, Any]:
        """Signal shutdown, let the writer drain, and return the final counters.

        Guarantees on return: offered == written + dropped. Frames that never reached storage
        are attributed, never lost from the accounting.
        """
        if self._thread is None:
            self._account_for_undrained()
            return self.stats.snapshot()
        try:
            self._q.put_nowait(self._SENTINEL)
        except queue.Full:
            self._stopping.set()
        self._thread.join(timeout=timeout)
        alive = self._thread.is_alive()
        self._thread = None
        # Whatever the writer did not drain — because it died, could not open storage, or ran
        # out of join timeout — is a real hole in history and is counted as such.
        undrained = self._account_for_undrained()
        out = self.stats.snapshot()
        out["clean_shutdown"] = not alive
        out["undrained_at_stop"] = undrained
        out["writer_died_early"] = self._writer_dead.is_set()
        out["accounting_complete"] = (out["offered"] == out["written"] + out["dropped"])
        return out

    def queue_depth(self) -> int:
        return self._q.qsize()


def _frame_lag_ms(frame: dict, received_ts_ms: int) -> int | None:
    """received - vendor frame timestamp, in ms. None when the vendor stamp is unusable."""
    if not isinstance(frame, dict):
        return None
    ts = frame.get("timestamp")
    try:
        return int(received_ts_ms) - int(ts)
    except (TypeError, ValueError):
        return None


def _default_persist_batch(conn: sqlite3.Connection, batch: list) -> int:
    """Write a whole batch in ONE transaction. Returns frames written.

    Reuses the row shape of calibration.options_stream_frames so the batched path and the
    single-frame path produce identical rows — two writers with different row shapes would be
    a second source of truth for the same table.
    """
    from calibration.options_stream_frames import frame_row_values, frame_symbol_rows

    written = 0
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        for service, frame, rx in batch:
            vals = frame_row_values(service, frame, rx)
            if vals is None:
                continue
            cur.execute(
                "INSERT INTO options_stream_frames (service, frame_ts_ms, received_ts_ms,"
                " ingest_lag_ms, n_contracts, payload_json) VALUES (?,?,?,?,?,?)", vals)
            fid = cur.lastrowid
            rows = frame_symbol_rows(fid, frame)
            if rows:
                cur.executemany(
                    "INSERT OR REPLACE INTO options_stream_frame_symbols (frame_id, symbol_key,"
                    " content_idx) VALUES (?,?,?)", rows)
            written += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


def measure_ingest_capacity(db_path: str, frames: list[tuple[str, dict]], *,
                            max_queue: int = DEFAULT_MAX_QUEUE,
                            batch_max: int = DEFAULT_BATCH_MAX) -> dict[str, Any]:
    """Push frames through the real path and report what it actually sustained.

    Returns measured throughput, drops, queue high-water and per-offer producer cost. The
    producer cost is the number that matters for the stream: it is the time the loop thread
    spends inside offer(), and therefore the time it is NOT reading the socket.
    """
    ing = OptionsFrameIngest(db_path, max_queue=max_queue, batch_max=batch_max)
    ing.start()
    t0 = time.perf_counter()
    offer_ns_total = 0
    worst_offer_ns = 0
    for service, fr in frames:
        a = time.perf_counter_ns()
        ing.offer(service, fr)
        d = time.perf_counter_ns() - a
        offer_ns_total += d
        worst_offer_ns = max(worst_offer_ns, d)
    offered_s = time.perf_counter() - t0
    final = ing.stop(timeout=120.0)
    total_s = time.perf_counter() - t0
    n = max(1, len(frames))
    final.update({
        "frames_offered": len(frames),
        "offer_wall_s": round(offered_s, 4),
        "total_wall_s": round(total_s, 4),
        "mean_offer_us": round(offer_ns_total / n / 1000.0, 3),
        "worst_offer_us": round(worst_offer_ns / 1000.0, 3),
        "offer_rate_per_s": round(len(frames) / offered_s, 1) if offered_s > 0 else None,
        "write_rate_per_s": round(final["written"] / total_s, 1) if total_s > 0 else None,
    })
    return final
