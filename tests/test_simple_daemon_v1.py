"""The simple capture daemon (operator 2026-09-25: "simple, simple, simple"): it publishes every
Schwab message as sent, records every answer, and runs as one daemon at a time with its log on
disk. Its subscriptions and its connection's life are held by tests/test_data_path_one_watchlist_v1.py
on the local Schwab streamer."""
from __future__ import annotations

import json
import sqlite3
import sys
import time

import pytest

import push_changes
import stream_spine as ss
from app.market_data.schwab.streaming import capture as cap


def test_requests_are_split_under_schwabs_message_limit():
    syms = [f"SPY   2610{i:02d}C00{i:05d}000" for i in range(4000)]      # ~100 KB of keys
    chunks = cap.split_request(syms)
    assert sum(chunks, []) == syms
    assert len(chunks) > 1
    assert all(len(",".join(c)) <= cap.MAX_REQUEST_BYTES for c in chunks)


# ------------------------------------------------------------------ Schwab's messages

def test_every_service_is_published_verbatim_and_only_delivered_data_counts_as_alive():
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    sub = bus.subscribe("", policy=ss.LOG)
    item = {"key": "SPY", "BID_PRICE": 1.0, "LAST_PRICE": 2.0, "LAST_MIC_ID": "XADF", "TOTAL_VOLUME": 9}
    cap._publisher("LEVELONE_EQUITIES", bus, health)({"content": [item]})
    topic, q = sub.queue.get_nowait()
    assert topic == "quote.SPY" and q["bid"] == 1.0 and q["last"] == 2.0 and q["native"] == item
    book = {"key": "SPY", "BOOK_TIME": 1, "BIDS": [], "ASKS": []}
    cap._publisher("NYSE_BOOK", bus, health)({"content": [book, {"BIDS": []}]})
    topic, b = sub.queue.get_nowait()
    assert topic == "book.SPY" and b["content"] == book and b["service"] == "NYSE_BOOK"
    assert sub.queue.empty(), "an item with no symbol is skipped"
    news = {"key": "SPY", "4": "headline"}
    cap._publisher("NEWS_HEADLINE", bus, health)({"content": [news]})
    assert sub.queue.get_nowait()[1]["content"] == news
    cap._publisher("LEVELONE_OPTIONS", bus, health)({"content": [{"BIDS": []}]})
    assert health.last("LEVELONE_OPTIONS") is None, "a frame that delivered nothing is not data"
    assert health.last("NYSE_BOOK") is not None


# ------------------------------------------------------------------ the database

def test_news_and_every_subscription_answer_are_written(tmp_path):
    w = ss.CaptureWriter(tmp_path / "s.db")
    w.insert("news.SPY", ss.news_msg(symbol="SPY", content={"4": "headline"}, src="schwab_news"))
    w.insert("sub.NYSE_BOOK", ss.subscription_msg(service="NYSE_BOOK", command="ADD",
                                                   symbols=["SPY"], code=19, reason="limit"))
    con = sqlite3.connect(tmp_path / "s.db")
    assert json.loads(con.execute("SELECT native_json FROM stream_news_raw").fetchone()[0]) == {"4": "headline"}
    assert con.execute("SELECT service, command, symbols_json, code FROM stream_subscriptions").fetchone() \
        == ("NYSE_BOOK", "ADD", '["SPY"]', 19)


# ------------------------------------------------------------------ the console side

@pytest.fixture
def console(monkeypatch):
    from app.options.order_flow import streaming as ofs
    monkeypatch.setattr(push_changes, "_open", [])
    monkeypatch.setattr(ofs, "_active_option_contract", None)
    monkeypatch.setattr(ofs, "_active_option_contracts", [])
    import live_market_plane as lmp
    lmp.record_feed_down()
    return ofs


def test_one_live_rule_every_reader_agrees_and_all_fail_closed_at_one_limit(console):
    """ONE-15 (2026-09-28 audit): "is it live" had four limits -- 3 s (price), 5 s (daemon
    status), 10 s (option greeks), 25 s (book) -- plus the daemon's 5 s/30 s message-age states,
    so one moment could read live on one card and dead on the next. One rule now: the daemon's
    heartbeat is under FEED_HEARTBEAT_MAX_AGE_SEC, its Schwab socket is open, and it holds the
    symbol on that service. A service quiet for 45 s on that feed is live (Schwab sends changes)."""
    import live_market_plane as lmp
    ofs = console
    status = {"schwab_socket_open": True,
              "health": {"OPTIONS_BOOK": {"age_sec": 45.0}},
              "held": {"LEVELONE_EQUITIES": ["MU"], "LEVELONE_OPTIONS": ["B", "A"], "OPTIONS_BOOK": ["A"]},
              "refused": {"LEVELONE_OPTIONS": {"C": "code 19"}}}

    def diag(sym):     # the served option-contract diagnostics for `sym`
        return ofs.get_option_contract_streaming_diagnostics(sym)

    def readers():
        return (lmp.feed_live_for("MU", "LEVELONE_EQUITIES"), lmp.feed_live_for("A", "LEVELONE_OPTIONS"),
                diag("A")["feed_health"]["book"]["state"], ofs.is_option_producer_daemon_available())

    def held(sym):
        return diag(sym)["producer_l1_contract"], diag(sym)["producer_book_contract"]

    assert readers() == (False, False, "NOT LIVE", False)
    limit = lmp.FEED_HEARTBEAT_MAX_AGE_SEC
    lmp.record_feed_heartbeat({**status, "ts": time.time() - limit + 0.5})
    assert readers() == (True, True, "LIVE", True)
    assert diag("A")["feed_health"]["book"]["age_sec"] == 45.0
    assert not lmp.feed_live_for("B", "OPTIONS_BOOK")               # held on L1 only
    assert held("B") == ("B", "A")                                  # B held on L1, the book holds A
    assert ofs.read_producer_rejected_option_contracts() == {"C": "code 19"}
    lmp.record_feed_heartbeat({**status, "ts": time.time() - limit - 0.5})
    assert readers() == (False, False, "NOT LIVE", False)
    assert held("B") == (None, None)
    lmp.record_feed_heartbeat({**status, "schwab_socket_open": False, "ts": time.time()})
    assert readers() == (False, False, "NOT LIVE", True)             # the daemon is up, Schwab is not


# ------------------------------------------------------------------ the process

def test_one_daemon_at_a_time_and_a_dead_owners_lock_is_reclaimed(tmp_path, monkeypatch):
    db = tmp_path / "stream_capture.db"
    fd, lock = cap.acquire_owner_lock(db)
    try:
        with pytest.raises(SystemExit) as e:
            cap.acquire_owner_lock(db)
        assert e.value.code == cap.EXIT_OWNER_LOCK_HELD
    finally:
        cap.release_owner_lock(fd, lock)
    lock.write_text("999999999")                       # a pid that is not running
    fd, lock = cap.acquire_owner_lock(db)
    cap.release_owner_lock(fd, lock)
    assert not lock.exists()


def test_a_checkout_that_may_not_run_live_refuses_before_opening_anything(monkeypatch):
    import runtime_layout
    monkeypatch.setattr(runtime_layout, "live_binding_error", lambda *a, **k: "bound elsewhere")
    ran = []
    monkeypatch.setattr(cap, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(sys, "argv", ["capture"])
    assert cap.main() == 2
    assert ran == [], "no lock, no Schwab socket, no stream database"


def test_the_daemons_log_is_kept_on_disk_with_times(monkeypatch, tmp_path):
    """Under pythonw there is no console: every line must reach logs/stream_capture.log with
    its wall time (2026-09-23: 42 socket deaths, not one reason on disk)."""
    import logging

    import runtime_layout
    monkeypatch.setattr(runtime_layout, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stderr", None)
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    try:
        cap._start_log()
        cap.log.warning("schwab: connection ended (socket closed)")
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "stream_capture.log").read_text(encoding="utf-8")
        assert "connection ended" in text and text[:4].isdigit()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers = saved
