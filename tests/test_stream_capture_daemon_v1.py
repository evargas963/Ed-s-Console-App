"""CR-01 daemon contracts (offline): parser, handler seam into the REAL bus/writer."""

from __future__ import annotations

import asyncio

from stream_spine import COUNT_DROPS, HealthRegistry, MessageBus
from tools.run_stream_capture import (
    CHART_FIELDS,
    LEVELONE_FIELDS,
    CaptureStats,
    make_handler,
    parse_stream_item,
)


def test_parse_stream_item_maps_numeric_keys_and_symbol():
    item = {"key": "spy", "BID_PRICE": 747.6, "ASK_PRICE": 747.62, "LAST_PRICE": 747.61,
            "BID_SIZE": 12, "ASK_SIZE": 9, "TOTAL_VOLUME": 1000000, "LAST_SIZE": 100,
            "QUOTE_TIME_MILLIS": 123, "TRADE_TIME_MILLIS": 456, "UNMAPPED_X": "ignored"}
    p = parse_stream_item(item, LEVELONE_FIELDS)
    assert p["symbol"] == "SPY" and p["bid"] == 747.6 and p["ask"] == 747.62
    assert p["total_volume"] == 1000000 and p["quote_time_ms"] == 123
    assert "UNMAPPED_X" not in p


def test_handler_publishes_through_real_bus_and_beats_health():
    """Real seam: the schwab-py-shaped message drives the ACTUAL bus + health objects."""
    async def go():
        bus = MessageBus()
        health = HealthRegistry()
        stats = CaptureStats()
        sub = bus.subscribe("quote.", policy=COUNT_DROPS)
        h = make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus, health, stats)
        h({"service": "LEVELONE_EQUITIES",
           "content": [{"key": "SPY", "BID_PRICE": 1.0, "LAST_PRICE": 1.5},
                       {"key": "QQQ", "BID_PRICE": 2.0}]})
        t0, m0 = await sub.get()
        t1, m1 = await sub.get()
        assert {t0, t1} == {"quote.SPY", "quote.QQQ"}
        assert m0["src"] == "schwab_l1" and "ts_recv" in m0
        assert bus.cache["quote.SPY"]["last"] == 1.5
        assert health.state("LEVELONE_EQUITIES") == "RUNNING"
        assert stats.per_service["LEVELONE_EQUITIES"] == 1
        assert stats.raw_sampled == {"LEVELONE_EQUITIES"}
    asyncio.run(go())


def test_chart_handler_builds_bar_messages():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("bar1m.", policy=COUNT_DROPS)
        h = make_handler("CHART_EQUITY", CHART_FIELDS, "bar1m", bus,
                         HealthRegistry(), CaptureStats())
        h({"content": [{"key": "IWM", "OPEN_PRICE": 10, "HIGH_PRICE": 11, "LOW_PRICE": 9,
                        "CLOSE_PRICE": 10.5, "VOLUME": 5000, "CHART_TIME_MILLIS": 1784650000000}]})
        topic, msg = await sub.get()
        assert topic == "bar1m.IWM"
        assert msg["open"] == 10 and msg["close"] == 10.5
        assert msg["bar_start_ms"] == 1784650000000 and msg["src"] == "schwab_chart"
    asyncio.run(go())


def test_empty_or_keyless_content_is_skipped_not_crashed():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("quote.", policy=COUNT_DROPS)
        h = make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus,
                         HealthRegistry(), CaptureStats())
        h({"content": [{"BID_PRICE": 5.0}]})   # no 'key' -> skipped
        h({})                          # no content -> no-op
        assert sub.queue.empty() and bus.published == 0
    asyncio.run(go())


def test_capture_stats_p_safe_with_zero_or_one_sample():
    """Bugbot MEDIUM: quantiles needs n>=2; quiet first heartbeat must not raise."""
    s = CaptureStats()
    assert s.p(50) is None
    s.record("LEVELONE_EQUITIES", 1.25)
    assert s.p(50) == 1.25
    assert s.p(99) == 1.25


def test_owner_lock_released_on_every_exit_path(tmp_path, monkeypatch):
    """Cursor round-2 HIGH: login/subscribe failures must not leak the lock."""
    import sys, types, asyncio as aio
    import tools.run_stream_capture as d

    monkeypatch.setattr(d, "OWNER_LOCK", tmp_path / "own.lock")

    fake_cfg = types.SimpleNamespace(api_key="k", app_secret="s", token_path="t")
    monkeypatch.setitem(sys.modules, "config",
                        types.SimpleNamespace(build_config=lambda _r: fake_cfg))

    # Path 1: client init fails -> rc 2, lock gone
    monkeypatch.setitem(sys.modules, "schwab_client", types.SimpleNamespace(
        build_client_from_token=lambda **_k: types.SimpleNamespace(
            ok=False, client=None, message="nope")))
    rc = aio.run(d.run(["SPY"], 0.0, str(tmp_path / "cap.db")))
    assert rc == 2 and not (tmp_path / "own.lock").exists()

    # Path 2: streamer login RAISES -> exception propagates, lock STILL gone
    class _Boom:
        def __init__(self, _c): pass
        async def login(self): raise RuntimeError("login exploded")
    monkeypatch.setitem(sys.modules, "schwab_client", types.SimpleNamespace(
        build_client_from_token=lambda **_k: types.SimpleNamespace(
            ok=True, client=object(), message="ok")))
    monkeypatch.setitem(sys.modules, "schwab.streaming",
                        types.SimpleNamespace(StreamClient=_Boom))
    import pytest as _pt
    with _pt.raises(RuntimeError):
        aio.run(d.run(["SPY"], 0.0, str(tmp_path / "cap.db")))
    assert not (tmp_path / "own.lock").exists(), "lock leaked on login failure"


def test_second_owner_refused_while_lock_held(tmp_path, monkeypatch):
    import tools.run_stream_capture as d
    import pytest as _pt
    monkeypatch.setattr(d, "OWNER_LOCK", tmp_path / "own.lock")
    fd = d.acquire_owner_lock()
    try:
        with _pt.raises(SystemExit):
            d.acquire_owner_lock()      # our own live pid holds it -> refuse
    finally:
        d.release_owner_lock(fd)
    assert not (tmp_path / "own.lock").exists()
