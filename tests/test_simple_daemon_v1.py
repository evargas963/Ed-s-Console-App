"""The simple capture daemon: it publishes every Schwab message as sent, records every answer, and
runs as one daemon at a time (its log: tests/test_daemon_log_v1.py). Its subscriptions and its
connection's life are held by tests/test_data_path_one_watchlist_v1.py on the local Schwab
streamer."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import stream_spine as ss
from app.market_data.schwab.streaming import capture as cap
from tests.real_chains import TSLA
from time_et import option_close_product

ROOT = Path(__file__).resolve().parents[1]


def test_requests_are_split_under_schwabs_message_limit():
    syms = [f"SPY   2610{i:02d}C00{i:05d}000" for i in range(4000)]  # ~100 KB of keys
    chunks = cap.split_request(syms)
    assert sum(chunks, []) == syms
    assert len(chunks) > 1
    assert all(len(",".join(c)) <= cap.MAX_REQUEST_BYTES for c in chunks)


# ------------------------------------------------------------------ Schwab's messages


def test_every_service_is_published_verbatim_and_only_delivered_data_counts_as_alive():
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    sub = bus.subscribe("", policy=ss.LOG)
    item = {
        "key": "SPY",
        "BID_PRICE": 1.0,
        "LAST_PRICE": 2.0,
        "LAST_MIC_ID": "XADF",
        "TOTAL_VOLUME": 9,
    }
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
    w.insert(
        "sub.NYSE_BOOK",
        ss.subscription_msg(
            service="NYSE_BOOK", command="ADD", symbols=["SPY"], code=19, reason="limit"
        ),
    )
    con = sqlite3.connect(tmp_path / "s.db")
    assert json.loads(con.execute("SELECT native_json FROM stream_news_raw").fetchone()[0]) == {
        "4": "headline"
    }
    assert con.execute(
        "SELECT service, command, symbols_json, code FROM stream_subscriptions"
    ).fetchone() == ("NYSE_BOOK", "ADD", '["SPY"]', 19)


# ------------------------------------------------------------------ the console side


def test_one_live_rule_every_reader_agrees_and_all_fail_closed_at_one_limit():
    """One limit for "is it live", so one moment never reads live on one card and dead on the
    next: the daemon's
    heartbeat is under FEED_HEARTBEAT_MAX_AGE_SEC, its Schwab socket is open, and it holds the
    symbol on that service. A service quiet for 45 s on that feed is live (Schwab sends changes).
    Two of TSLA's captured 2026-10-07 contracts, judged by TSLA's own option market. STAND-IN
    (named): the daemon's status. Judged in regular hours (RTH_INSTANT)."""
    import live_market_plane as lmp
    from app.options.order_flow import streaming as ofs
    from tests.feed_live_helper import RTH_INSTANT

    a, b = TSLA.chain[0]["symbol"], TSLA.chain[1]["symbol"]
    product = option_close_product(TSLA.ticker)
    status = {
        "schwab_socket_open": True,
        "health": {"OPTIONS_BOOK": {"age_sec": 45.0}},
        "held": {"LEVELONE_EQUITIES": ["MU"], "LEVELONE_OPTIONS": [b, a], "OPTIONS_BOOK": [a]},
    }

    now = RTH_INSTANT

    def diag(sym):  # the served option-contract diagnostics for `sym`
        return ofs.get_option_contract_streaming_diagnostics(sym, now, product)

    def readers():
        return (
            lmp.feed_live_for("MU", "LEVELONE_EQUITIES", now),
            lmp.feed_live_for(a, "LEVELONE_OPTIONS", now, product),
            diag(a)["feed_health"]["book"]["state"],
            diag(b)["subscription_state"],
        )

    lmp.record_feed_down()
    try:
        down = readers()
        limit = lmp.FEED_HEARTBEAT_MAX_AGE_SEC
        lmp.record_feed_heartbeat({**status, "ts": now - limit + 0.5})
        live, book_age, b_book = (
            readers(),
            diag(a)["feed_health"]["book"]["age_sec"],
            lmp.feed_live_for(b, "OPTIONS_BOOK", now, product),
        )
        lmp.record_feed_heartbeat({**status, "ts": now - limit - 0.5})
        late = readers()
        lmp.record_feed_heartbeat({**status, "schwab_socket_open": False, "ts": now})
        schwab_down = readers()
    finally:
        lmp.record_feed_down()
    assert down == (False, False, "OFFLINE", "NOT STREAMED")
    assert late == (False, False, "OFFLINE", "SUBSCRIBED")
    assert live == (True, True, "LIVE", "SUBSCRIBED") and book_age == 45.0
    assert b_book is False  # B held on L1 only
    assert schwab_down == (False, False, "OFFLINE", "SUBSCRIBED")  # the daemon is up, Schwab is not


# ------------------------------------------------------------------ the process


def test_one_daemon_at_a_time_and_a_dead_owners_lock_is_reclaimed(tmp_path):
    db = tmp_path / "stream_capture.db"
    fd, lock = cap.acquire_owner_lock(db)
    try:
        with pytest.raises(SystemExit) as e:
            cap.acquire_owner_lock(db)
        assert e.value.code == cap.EXIT_OWNER_LOCK_HELD
    finally:
        cap.release_owner_lock(fd, lock)
    lock.write_text("999999999")  # a pid that is not running
    fd, lock = cap.acquire_owner_lock(db)
    cap.release_owner_lock(fd, lock)
    assert not lock.exists()


def test_a_checkout_that_may_not_run_live_refuses_before_opening_anything(tmp_path):
    """The daemon started, as launch.py starts it, with its runtime root another checkout (a
    directory holding `.git`): it refuses and exits 2, with no lock, no log and no stream database
    written there."""
    other = tmp_path / "other_checkout"
    (other / ".git").mkdir(parents=True)
    env = {**os.environ, "ED_RUNTIME_ROOT": str(other)}
    r = subprocess.run(
        [sys.executable, "-m", "app.market_data.schwab.streaming.capture_main"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CAPTURE DAEMON REFUSED" in r.stderr
    assert sorted(p.name for p in other.iterdir()) == [".git"], (
        "no lock, no log, no stream database"
    )
