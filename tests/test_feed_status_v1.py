"""Once a minute the daemon records per feed: checked at X, socket open, when Schwab last sent
anything, subscribed symbols, and when the feed last carried data -- a quiet feed and a dead one
read differently in the database (operator question 2026-09-27)."""
from __future__ import annotations

import asyncio
import sqlite3

from app.market_data.schwab.streaming import capture
from stream_spine import CaptureWriter, HealthRegistry, MessageBus


class _Stream:
    last_frame_ts = 1000.0


def test_every_feed_gets_one_row_with_the_same_checked_at(tmp_path, monkeypatch):
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db)
    bus, health = MessageBus(), HealthRegistry()
    health.beat("NEWS_HEADLINE", 990.0)
    daemon = capture.Daemon(bus, health, tmp_path / "wanted.json")
    daemon.stream = _Stream()
    got = []
    monkeypatch.setattr(bus, "publish", lambda topic, msg: got.append((topic, msg)))

    async def go():
        stop = asyncio.Event()
        stop.set()                                   # one round, then stop
        await capture.record_feed_status(daemon, stop)
    asyncio.run(go())

    for topic, msg in got:
        writer.insert(topic, msg)
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT ts, service, schwab_last_frame_ts, last_data_ts "
                         "FROM stream_feed_status ORDER BY service").fetchall()
    assert {r[1] for r in rows} == set(capture.SERVICES)
    assert len({r[0] for r in rows}) == 1, "every feed is checked at the same X"
    assert all(r[2] == 1000.0 for r in rows)
    news = [r for r in rows if r[1] == "NEWS_HEADLINE"][0]
    assert news[3] == 990.0
    assert all(r[3] is None for r in rows if r[1] != "NEWS_HEADLINE"), "no data is None, not a time"


def test_an_expired_option_contract_is_never_streamed():
    """Measured 2026-09-27: a weekend heatmap subscribed 200 DELL contracts that expired Friday --
    the ranking put the earliest expiry first, and an expired one is the earliest."""
    from stream_spine import rank_option_contracts
    from time_et import now_et
    from datetime import timedelta
    yesterday = (now_et().date() - timedelta(days=1)).isoformat()
    tomorrow = (now_et().date() + timedelta(days=1)).isoformat()
    inputs = {"OLD": {"expirationDate": yesterday, "strikePrice": 100.0, "spot": 100.0},
              "NEW": {"expirationDate": tomorrow, "strikePrice": 100.0, "spot": 100.0}}
    admitted, not_admitted = rank_option_contracts(["OLD", "NEW"], inputs)
    assert admitted == ["NEW"]
    assert not_admitted["OLD"] == f"not admitted: expired {yesterday}"
