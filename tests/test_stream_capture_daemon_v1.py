"""CR-01 daemon contracts (offline): parser, handler seam into the REAL bus/writer."""

from __future__ import annotations

import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

from stream_spine import COUNT_DROPS, HealthRegistry, MessageBus  # noqa: E402
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


def test_the_canonical_daemon_has_no_alpaca_producer_and_cannot_write_alpaca():
    """NEGATIVE CONTROL #1: the canonical Schwab Collect daemon cannot start or write Alpaca. The
    Alpaca leg was MOVED to the isolated alpaca_iex_capture.py, so the daemon module has no Alpaca
    producer, no alpaca_* function, and does not import the spine's print builder — nothing in it
    can publish a print/alpaca frame onto the bus."""
    import ast

    src = (REPO / "tools" / "run_stream_capture.py").read_text(encoding="utf-8")
    import tools.run_stream_capture as d
    # No Alpaca producer/functions/constants survive in the daemon.
    for banned in ("alpaca_pump", "alpaca_handle_frame", "_alpaca_session",
                   "alpaca_item_to_topic_msg", "ALPACA_SRC", "ALPACA_WS_URL", "print_msg"):
        assert not hasattr(d, banned), f"canonical daemon still exposes {banned}"
    # No print/alpaca topic is ever published, and no alpaca task is created, in the daemon source.
    tree = ast.parse(src)
    publishes = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "publish"]
    for call in publishes:
        first = call.args[0] if call.args else None
        lit = getattr(first, "value", "") if isinstance(first, ast.Constant) else ""
        assert not (isinstance(lit, str) and lit.startswith("print.")), (
            "the daemon publishes a print topic — Alpaca prints must not originate here")
    assert "alpaca_pump" not in src and "extra_producers=(alpaca_task" not in src, (
        "the daemon still wires an Alpaca producer task")


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


# ── half-open-socket guard (2026-07-23, observed live: both feeds silent, no error) ──


def test_stream_needs_recycle_decision_boundaries():
    from tools.run_stream_capture import (
        RECONNECT_COOLDOWN_SEC,
        STREAM_STALE_RECONNECT_SEC,
        stream_needs_recycle,
    )

    ok_cool = RECONNECT_COOLDOWN_SEC + 1
    stale = STREAM_STALE_RECONNECT_SEC + 1
    assert stream_needs_recycle(stale, True, ok_cool) is True
    # never recycle: no age yet / never saw data (subscribe problem, not half-open)
    assert stream_needs_recycle(None, True, ok_cool) is False
    assert stream_needs_recycle(stale, False, ok_cool) is False
    # never login-spam: inside cooldown stays put even when stale
    assert stream_needs_recycle(stale, True, RECONNECT_COOLDOWN_SEC - 1) is False
    # fresh feed stays connected
    assert stream_needs_recycle(STREAM_STALE_RECONNECT_SEC - 1, True, ok_cool) is False
