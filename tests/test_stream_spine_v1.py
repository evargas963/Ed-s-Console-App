"""CR-01 spine contracts: cache-then-publish, bounded queues, RC-6 guard, health states."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from stream_spine import (
    COALESCE,
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    bar_msg,
    print_msg,
    quote_msg,
)


def test_cache_written_before_subscribers_and_snapshot_hydrates():
    async def go():
        bus = MessageBus()
        seen_at_delivery = {}

        sub = bus.subscribe("quote.", policy=COUNT_DROPS)
        bus.publish("quote.SPY", {"last": 747.63})
        # cache-then-publish: by the time the message is readable, the cache has it
        topic, msg = await sub.get()
        seen_at_delivery["cache"] = bus.cache.get("quote.SPY")
        assert topic == "quote.SPY" and msg["last"] == 747.63
        assert seen_at_delivery["cache"] == {"last": 747.63}
        # a late consumer hydrates from snapshot without any poll
        assert bus.snapshot("quote.")["quote.SPY"]["last"] == 747.63
    asyncio.run(go())


def test_coalesce_keeps_newest_only_and_counts_nothing_lost_as_drops():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("quote.", policy=COALESCE, maxsize=4)
        for px in (1.0, 2.0, 3.0):
            bus.publish("quote.SPY", {"last": px})
        topic, msg = await sub.get()
        assert msg["last"] == 3.0, "coalesce must deliver the NEWEST pending quote"
        assert sub.queue.empty(), "one topic key, not three"
        assert sub.dropped == 0, "coalescing is not a drop"
    asyncio.run(go())


def test_prints_never_coalesce_and_overflow_counts_loudly():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("print.", policy=COUNT_DROPS, maxsize=2)
        for i in range(5):
            bus.publish("print.SPY", {"size": i})
        # first two kept in order, three counted dropped — never silently merged
        t0, m0 = await sub.get()
        t1, m1 = await sub.get()
        assert (m0["size"], m1["size"]) == (0, 1)
        assert sub.dropped == 3
        assert bus.drop_counts() == {"print.": 3}
    asyncio.run(go())


def test_writer_refuses_operational_db():
    with pytest.raises(ValueError):
        CaptureWriter("data/ed_console.db")


def test_writer_batches_into_stream_capture_db(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=2, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1, ask=2, last=1.5, bid_size=10,
                                    ask_size=20, last_size=1, total_volume=100,
                                    quote_time_ms=5, trade_time_ms=6, src="t", ts_recv=1.0))
    w.insert("print.SPY", print_msg(symbol="SPY", price=1.5, size=100, exchange="IEX",
                                    conditions="@", trade_ts_ms=7, src="t", ts_recv=1.1))
    w.insert("bar1m.SPY", bar_msg(symbol="SPY", bar_start_ms=0, open=1, high=2, low=0.5,
                                  close=1.5, volume=999, src="t", ts_recv=2.0))
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM stream_bars_raw").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_health_states_progress_running_degraded_stale():
    h = HealthRegistry()
    assert h.state("schwab_l1") == "DOWN"          # never seen != quiet market
    h.beat("schwab_l1", ts=1000.0)
    assert h.state("schwab_l1", now=1002.0) == "RUNNING"
    assert h.state("schwab_l1", now=1010.0) == "DEGRADED"
    assert h.state("schwab_l1", now=1031.0) == "STALE"
    assert h.any_stale(now=1031.0) is True         # the CR-07 suppression hook
    rep = h.report(now=1010.0)
    assert rep["schwab_l1"]["state"] == "DEGRADED" and rep["schwab_l1"]["age_sec"] == 10.0


def test_writer_drains_full_queue_on_stop(tmp_path):
    """Cursor review HIGH: stop must not vaporize buffered rows."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        for i in range(50):
            bus.publish("print.SPY", print_msg(symbol="SPY", price=1.0, size=i, src="t"))
        stop = asyncio.Event()
        stop.set()                      # stop BEFORE the writer ever runs
        await w.run(sub, stop=stop)
        w.close()
        con = sqlite3.connect(tmp_path / "s.db")
        n = con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0]
        assert n == 50, f"drain lost rows: {n}/50"
        assert w.insert_errors == 0
    asyncio.run(go())


def test_insert_failure_is_counted_never_kills_writer(tmp_path):
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        bus.publish("print.SPY", object())      # not a dict -> insert raises inside
        bus.publish("print.SPY", print_msg(symbol="SPY", price=2.0, size=1, src="t"))
        stop = asyncio.Event(); stop.set()
        await w.run(sub, stop=stop)
        w.close()
        assert w.insert_errors == 1
        con = sqlite3.connect(tmp_path / "s.db")
        assert con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0] == 1
    asyncio.run(go())


def test_rc6_guard_survives_path_tricks():
    """Cursor review MEDIUM: `data/x/../ed_console.db` must not slip past the guard."""
    with pytest.raises(ValueError):
        CaptureWriter("data/nosuchdir/../ed_console.db")


def test_writer_close_is_idempotent(tmp_path):
    w = CaptureWriter(tmp_path / "s.db")
    w.close()
    w.close()  # second call must not raise
    assert w._closed is True


def test_writer_init_closes_conn_if_schema_setup_fails(tmp_path, monkeypatch):
    """Bugbot HIGH: connect-then-fail must not leak the SQLite handle."""
    real_connect = __import__("sqlite3").connect
    closed = {"n": 0}

    class TrackingConn:
        def __init__(self, inner):
            self._inner = inner

        def executescript(self, *_a, **_k):
            raise RuntimeError("schema boom")

        def commit(self):
            return self._inner.commit()

        def close(self):
            closed["n"] += 1
            return self._inner.close()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def wrap(path, *a, **k):
        return TrackingConn(real_connect(path, *a, **k))

    monkeypatch.setattr("stream_spine.sqlite3.connect", wrap)
    with pytest.raises(RuntimeError, match="schema boom"):
        CaptureWriter(tmp_path / "s.db")
    assert closed["n"] == 1
