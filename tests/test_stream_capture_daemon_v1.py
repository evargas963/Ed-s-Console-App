"""CR-01 daemon contracts (offline): parser, handler seam into the REAL bus/writer."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from stream_spine import (
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    read_active_option_contract_signal,
    read_active_ticker_signal,
    write_active_option_contract_signal,
    write_active_ticker_signal,
)
from tools.run_stream_capture import (
    CHART_FIELDS,
    LEVELONE_FIELDS,
    CaptureStats,
    _apply_active_option_contract_subs,
    _apply_active_ticker_book_subs,
    make_book_handler,
    make_handler,
    make_options_quote_handler,
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


def test_quote_handler_carries_native_content_for_hydration():
    """The live-plane hydrator needs the raw content item verbatim (BID_TIME_MILLIS etc,
    fields the flattened quote_msg columns do not carry) — make_handler must pass it."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("quote.", policy=COUNT_DROPS)
        h = make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus,
                         HealthRegistry(), CaptureStats())
        native_item = {"key": "SPY", "BID_PRICE": 1.0, "BID_TIME_MILLIS": 42}
        h({"content": [native_item]})
        _topic, msg = await sub.get()
        assert msg["native"] == native_item
    asyncio.run(go())


def test_book_handler_publishes_content_verbatim():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("book.", policy=COUNT_DROPS)
        h = make_book_handler("NASDAQ_BOOK", bus, HealthRegistry(), CaptureStats())
        item = {"key": "SPY", "BIDS": [{"BID_PRICE": 1.0}], "ASKS": [{"ASK_PRICE": 1.1}]}
        h({"content": [item]})
        topic, msg = await sub.get()
        assert topic == "book.SPY"
        assert msg["service"] == "NASDAQ_BOOK" and msg["content"] == item
    asyncio.run(go())


def test_book_handler_ignores_items_with_no_symbol():
    async def go():
        bus = MessageBus()
        h = make_book_handler("NYSE_BOOK", bus, HealthRegistry(), CaptureStats())
        h({"content": [{"BIDS": []}]})   # no 'key' -> no symbol
        assert bus.published == 0
    asyncio.run(go())


class _FakeStream:
    """Records book (un)subscribe calls; never touches real Schwab."""
    def __init__(self):
        self.calls: list[tuple] = []

    async def nasdaq_book_subs(self, syms):
        self.calls.append(("nasdaq_sub", tuple(syms)))

    async def nyse_book_subs(self, syms):
        self.calls.append(("nyse_sub", tuple(syms)))

    async def nasdaq_book_unsubs(self, syms):
        self.calls.append(("nasdaq_unsub", tuple(syms)))

    async def nyse_book_unsubs(self, syms):
        self.calls.append(("nyse_unsub", tuple(syms)))


def test_apply_active_ticker_book_subs_switches_symbol(tmp_path, monkeypatch):
    """PHASE 4-G shape: the daemon must subscribe book depth for whatever ticker the
    server signals, and unsubscribe the one it replaces — never both at once."""
    p = tmp_path / "stream_active_ticker.json"
    write_active_ticker_signal("QQQ", path=p)
    monkeypatch.setattr("tools.run_stream_capture.read_active_ticker_signal",
                        lambda: read_active_ticker_signal(path=p))
    stream = _FakeStream()

    async def go():
        new_cur = await _apply_active_ticker_book_subs(stream, "SPY")
        assert new_cur == "QQQ"
        assert ("nasdaq_unsub", ("SPY",)) in stream.calls
        assert ("nyse_unsub", ("SPY",)) in stream.calls
        assert ("nasdaq_sub", ("QQQ",)) in stream.calls
        assert ("nyse_sub", ("QQQ",)) in stream.calls
    asyncio.run(go())


def test_apply_active_ticker_book_subs_no_change_is_a_no_op(monkeypatch):
    monkeypatch.setattr("tools.run_stream_capture.read_active_ticker_signal", lambda: "SPY")
    stream = _FakeStream()

    async def go():
        new_cur = await _apply_active_ticker_book_subs(stream, "SPY")
        assert new_cur == "SPY"
        assert stream.calls == []
    asyncio.run(go())


def test_apply_active_ticker_book_subs_first_activation_has_no_unsub(monkeypatch):
    """No current ticker yet (daemon just started, no viewer active) -> subscribe only,
    never an unsub call for a symbol that was never subscribed."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_ticker_signal", lambda: "SPY")
    stream = _FakeStream()

    async def go():
        new_cur = await _apply_active_ticker_book_subs(stream, None)
        assert new_cur == "SPY"
        assert all(c[0] not in ("nasdaq_unsub", "nyse_unsub") for c in stream.calls)
    asyncio.run(go())


class _FakeOptionStream:
    """Records options (un)subscribe calls; never touches real Schwab."""
    def __init__(self):
        self.calls: list[tuple] = []

    async def level_one_option_subs(self, syms):
        self.calls.append(("l1_option_sub", tuple(syms)))

    async def options_book_subs(self, syms):
        self.calls.append(("options_book_sub", tuple(syms)))

    async def level_one_option_unsubs(self, syms):
        self.calls.append(("l1_option_unsub", tuple(syms)))

    async def options_book_unsubs(self, syms):
        self.calls.append(("options_book_unsub", tuple(syms)))


_SPY_CONTRACT = "SPY   260820C00767000"
_QQQ_CONTRACT = "QQQ   260820C00450000"


def test_apply_active_option_contract_subs_switches_contract(tmp_path, monkeypatch):
    """Mirrors the equity-book diff test: subscribe the new contract, unsubscribe the
    one it replaces, never both live at once. contract_state is per-service: both
    services start held=SPY, both switch to held=QQQ."""
    p = tmp_path / "stream_active_option_contract.json"
    write_active_option_contract_signal(_QQQ_CONTRACT, path=p)
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: read_active_option_contract_signal(path=p))
    stream = _FakeOptionStream()

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        new_state = await _apply_active_option_contract_subs(stream, state)
        assert new_state == {"l1": _QQQ_CONTRACT, "book": _QQQ_CONTRACT}
        assert ("l1_option_unsub", (_SPY_CONTRACT,)) in stream.calls
        assert ("options_book_unsub", (_SPY_CONTRACT,)) in stream.calls
        assert ("l1_option_sub", (_QQQ_CONTRACT,)) in stream.calls
        assert ("options_book_sub", (_QQQ_CONTRACT,)) in stream.calls
    asyncio.run(go())


def test_apply_active_option_contract_subs_no_change_is_a_no_op(monkeypatch):
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FakeOptionStream()

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        new_state = await _apply_active_option_contract_subs(stream, state)
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        assert stream.calls == []
    asyncio.run(go())


def test_apply_active_option_contract_subs_first_activation_has_no_unsub(monkeypatch):
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FakeOptionStream()

    async def go():
        state = {"l1": None, "book": None}
        new_state = await _apply_active_option_contract_subs(stream, state)
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        assert all(c[0] not in ("l1_option_unsub", "options_book_unsub")
                   for c in stream.calls)
    asyncio.run(go())


def test_apply_active_option_contract_subs_opens_coverage_epochs_on_activation(tmp_path, monkeypatch):
    """First activation (no prior contract) must OPEN durable epochs for both services —
    a reader must be able to tell 'not yet subscribed' from 'subscribed, silent'."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FakeOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    epoch_state = {"l1": None, "book": None}

    async def go():
        state = {"l1": None, "book": None}
        new_state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        assert epoch_state["l1"] is not None and epoch_state["book"] is not None
    asyncio.run(go())
    import sqlite3
    con = sqlite3.connect(tmp_path / "cap.db")
    rows = con.execute(
        "SELECT symbol, service, ended_ts FROM stream_coverage_epochs ORDER BY id").fetchall()
    writer.close()
    assert rows == [(_SPY_CONTRACT, "LEVELONE_OPTIONS", None),
                    (_SPY_CONTRACT, "OPTIONS_BOOK", None)]


def test_apply_active_option_contract_subs_closes_old_opens_new_on_switch(tmp_path, monkeypatch):
    p = tmp_path / "signal.json"
    write_active_option_contract_signal(_QQQ_CONTRACT, path=p)
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: read_active_option_contract_signal(path=p))
    stream = _FakeOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    epoch_state = {"l1": 1, "book": 2}
    # Seed the "old" epochs a real activation would have opened.
    writer._conn.execute(
        "INSERT INTO stream_coverage_epochs(id,symbol,service,started_ts,reason) "
        "VALUES(1,?,?,0,?),(2,?,?,0,?)",
        (_SPY_CONTRACT, "LEVELONE_OPTIONS", "seed", _SPY_CONTRACT, "OPTIONS_BOOK", "seed"))
    writer._conn.commit()

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        new_state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
        assert new_state == {"l1": _QQQ_CONTRACT, "book": _QQQ_CONTRACT}
    asyncio.run(go())
    import sqlite3
    con = sqlite3.connect(tmp_path / "cap.db")
    old_rows = con.execute(
        "SELECT ended_ts FROM stream_coverage_epochs WHERE id IN (1,2)").fetchall()
    new_rows = con.execute(
        "SELECT symbol, ended_ts FROM stream_coverage_epochs WHERE symbol=?",
        (_QQQ_CONTRACT,)).fetchall()
    writer.close()
    assert all(r[0] is not None for r in old_rows), "switching away must CLOSE the old epochs"
    assert len(new_rows) == 2 and all(r[1] is None for r in new_rows)


def test_options_quote_handler_publishes_native_content_verbatim():
    """The real live-captured shape (reports/of_capability_probe/options_20260820T1354Z/)
    — 57 native fields, greeks/OI/IV included — must reach the bus untouched."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("optquote.", policy=COUNT_DROPS)
        h = make_options_quote_handler(bus, HealthRegistry(), CaptureStats())
        item = {"key": _SPY_CONTRACT, "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
               "DELTA": 0.45644607, "OPEN_INTEREST": 2097, "CONTRACT_TYPE": "C"}
        h({"content": [item]})
        topic, msg = await sub.get()
        assert topic == f"optquote.{_SPY_CONTRACT}"
        assert msg["content"] == item and msg["src"] == "schwab_options_l1"
    asyncio.run(go())


def test_options_book_handler_reuses_the_generic_book_handler():
    """OPTIONS_BOOK needs no new handler — make_book_handler is already
    service-parametrized; _schwab_connect wires it with service='OPTIONS_BOOK'."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("book.", policy=COUNT_DROPS)
        h = make_book_handler("OPTIONS_BOOK", bus, HealthRegistry(), CaptureStats())
        item = {"key": _SPY_CONTRACT, "BIDS": [{"BID_PRICE": 1.28}], "ASKS": [{"ASK_PRICE": 1.3}]}
        h({"content": [item]})
        topic, msg = await sub.get()
        assert topic == f"book.{_SPY_CONTRACT}"
        assert msg["service"] == "OPTIONS_BOOK" and msg["content"] == item
    asyncio.run(go())


class _FakeSchwabStreamClient:
    """Records handler registrations + subscribe/unsubscribe calls; never touches real
    Schwab. Models exactly the subset of schwab-py's StreamClient surface _schwab_connect
    actually calls."""
    def __init__(self, client, account_id=None):
        self.client = client
        self.account_id = account_id
        self.handlers: dict[str, object] = {}
        self.calls: list[tuple] = []

    def add_level_one_equity_handler(self, h):
        self.handlers["l1"] = h

    def add_chart_equity_handler(self, h):
        self.handlers["chart"] = h

    def add_nasdaq_book_handler(self, h):
        self.handlers["nasdaq_book"] = h

    def add_nyse_book_handler(self, h):
        self.handlers["nyse_book"] = h

    def add_level_one_option_handler(self, h):
        self.handlers["l1_option"] = h

    def add_options_book_handler(self, h):
        self.handlers["options_book"] = h

    async def login(self):
        self.calls.append(("login",))

    async def level_one_equity_subs(self, syms):
        self.calls.append(("l1_sub", tuple(syms)))

    async def chart_equity_subs(self, syms):
        self.calls.append(("chart_sub", tuple(syms)))

    async def nasdaq_book_subs(self, syms):
        self.calls.append(("nasdaq_sub", tuple(syms)))

    async def nyse_book_subs(self, syms):
        self.calls.append(("nyse_sub", tuple(syms)))

    async def level_one_option_subs(self, syms):
        self.calls.append(("l1_option_sub", tuple(syms)))

    async def options_book_subs(self, syms):
        self.calls.append(("options_book_sub", tuple(syms)))

    async def level_one_option_unsubs(self, syms):
        self.calls.append(("l1_option_unsub", tuple(syms)))

    async def options_book_unsubs(self, syms):
        self.calls.append(("options_book_unsub", tuple(syms)))

    async def handle_message(self):
        await asyncio.sleep(3600)   # never resolves in a test; only cancellation ends it


def _install_fake_schwab_streaming(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "schwab.streaming",
                        types.SimpleNamespace(StreamClient=_FakeSchwabStreamClient))


def test_schwab_connect_registers_book_handlers_every_time():
    """PHASE 4-E: canonical one-owner startup must wire book handlers on connect — not
    only after the first UI viewer ever requests a ticker (a later signal write must not
    race an unregistered handler)."""
    import tools.run_stream_capture as d

    async def go(monkeypatch):
        _install_fake_schwab_streaming(monkeypatch)
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        stream, task, _cs = await d._schwab_connect(SimpleNamespace(client=object()), ["SPY"], bus, health, stats, stop)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert "nasdaq_book" in stream.handlers and "nyse_book" in stream.handlers
        assert ("login",) in stream.calls
        assert ("l1_sub", ("SPY",)) in stream.calls

    import pytest as _pt
    mp = _pt.MonkeyPatch()
    try:
        asyncio.run(go(mp))
    finally:
        mp.undo()


def test_schwab_connect_reapplies_active_book_ticker_after_reconnect():
    """PHASE 4-F: a fresh StreamClient (post half-open recycle) carries NO subscriptions
    — the active UI viewer's book depth must be re-applied on THIS connect, not wait for
    the next 1s poll tick to notice an unchanged signal file and do nothing."""
    import tools.run_stream_capture as d

    async def go(monkeypatch):
        _install_fake_schwab_streaming(monkeypatch)
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        stream, task, _cs = await d._schwab_connect(SimpleNamespace(client=object()), ["SPY"], bus, health, stats, stop,
                                                    active_book_ticker="QQQ")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert ("nasdaq_sub", ("QQQ",)) in stream.calls
        assert ("nyse_sub", ("QQQ",)) in stream.calls

    import pytest as _pt
    mp = _pt.MonkeyPatch()
    try:
        asyncio.run(go(mp))
    finally:
        mp.undo()


def test_schwab_connect_reapplies_active_option_contract_after_reconnect():
    """Same reconnect-survives shape as the book ticker, for the options contract."""
    import tools.run_stream_capture as d

    async def go(monkeypatch):
        _install_fake_schwab_streaming(monkeypatch)
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        stream, task, contract_state = await d._schwab_connect(
            SimpleNamespace(client=object()), ["SPY"], bus, health, stats, stop,
            active_option_contract=_SPY_CONTRACT)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert "l1_option" in stream.handlers and "options_book" in stream.handlers
        assert ("l1_option_sub", (_SPY_CONTRACT,)) in stream.calls
        assert ("options_book_sub", (_SPY_CONTRACT,)) in stream.calls
        assert contract_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}

    import pytest as _pt
    mp = _pt.MonkeyPatch()
    try:
        asyncio.run(go(mp))
    finally:
        mp.undo()


def test_reconnect_replaces_stream_not_both_at_once():
    """PHASE 4-F: two sequential connects must yield two DISTINCT StreamClient instances
    — never a leaked reference to the old one that would leave two concurrent Schwab
    sessions on one account."""
    import tools.run_stream_capture as d

    async def go(monkeypatch):
        _install_fake_schwab_streaming(monkeypatch)
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        stream1, task1, _cs1 = await d._schwab_connect(SimpleNamespace(client=object()), ["SPY"], bus, health, stats, stop)
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
        stream2, task2, _cs2 = await d._schwab_connect(SimpleNamespace(client=object()), ["SPY"], bus, health, stats, stop,
                                                       active_book_ticker="SPY")
        task2.cancel()
        try:
            await task2
        except asyncio.CancelledError:
            pass
        assert stream1 is not stream2
        assert task1.done() and task1.cancelled()

    import pytest as _pt
    mp = _pt.MonkeyPatch()
    try:
        asyncio.run(go(mp))
    finally:
        mp.undo()


def test_recycle_cancels_old_pump_before_reconnecting_structurally():
    """Structural corroboration of the behavioral tests above: the watchdog branch in
    _run_streaming must cancel+await the OLD pump task before calling _schwab_connect
    again — sequential code, but pinned so a future edit cannot silently reorder it into
    a `create_task` race between old and new streams."""
    import inspect
    import tools.run_stream_capture as d

    src = inspect.getsource(d._run_streaming)
    cancel_at = src.index("pump_task.cancel()")
    await_at = src.index("await pump_task", cancel_at)
    reconnect_at = src.index("_schwab_connect(", await_at)
    assert cancel_at < await_at < reconnect_at


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


def test_alpaca_rfc3339_nanoseconds_to_ms():
    """Alpaca stamps carry 9-digit fractions; fromisoformat takes 6 — trim must hold."""
    from tools.run_stream_capture import alpaca_rfc3339_to_ms
    assert alpaca_rfc3339_to_ms("2026-07-22T20:22:23.626206217Z") == 1784751743626
    assert alpaca_rfc3339_to_ms("2026-07-22T20:22:23Z") == 1784751743000
    assert alpaca_rfc3339_to_ms(None) is None
    assert alpaca_rfc3339_to_ms("garbage") is None


def test_alpaca_items_flow_through_real_bus_and_writer_to_db(tmp_path):
    """CR-02 seam: Alpaca-shaped trade + NBBO items -> REAL bus -> REAL CaptureWriter
    -> rows readable back out of a REAL stream_capture db (src=alpaca_iex)."""
    import sqlite3
    from stream_spine import CaptureWriter, MessageBus
    from tools.run_stream_capture import alpaca_item_to_topic_msg

    async def go():
        bus = MessageBus()
        writer = CaptureWriter(tmp_path / "cap.db", batch_sec=0.05)
        wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=64)
        stop = asyncio.Event()
        for item in (
            {"T": "t", "S": "SPY", "i": 52983945511779, "x": "V", "p": 748.6, "s": 40,
             "c": [" ", "T"], "t": "2026-07-22T20:22:23.626206217Z", "z": "B"},
            {"T": "q", "S": "SPY", "bx": "V", "bp": 748.37, "bs": 80, "ax": "V",
             "ap": 748.99, "as": 80, "c": ["R"], "t": "2026-07-22T20:31:07.643443439Z",
             "z": "B"},
        ):
            topic, msg = alpaca_item_to_topic_msg(item)
            bus.publish(topic, msg)
        task = asyncio.create_task(writer.run(wsub, stop=stop))
        await asyncio.sleep(0.15)
        stop.set()
        await task
        writer.close()

    asyncio.run(go())
    con = sqlite3.connect(tmp_path / "cap.db")
    p = con.execute("SELECT symbol, price, size, exchange, conditions, trade_ts_ms, src "
                    "FROM stream_prints_raw").fetchall()
    q = con.execute("SELECT symbol, bid, ask, bid_size, ask_size, src "
                    "FROM stream_quotes_raw").fetchall()
    con.close()
    assert p == [("SPY", 748.6, 40, "V", " ,T", 1784751743626, "alpaca_iex")]
    assert q == [("SPY", 748.37, 748.99, 80, 80, "alpaca_iex")]


def test_alpaca_control_and_bar_frames_are_not_captured():
    from tools.run_stream_capture import alpaca_item_to_topic_msg
    assert alpaca_item_to_topic_msg({"T": "success", "msg": "authenticated"}) is None
    assert alpaca_item_to_topic_msg({"T": "subscription", "trades": ["SPY"]}) is None
    # bars deliberately excluded: canonical 1m stays Schwab's (sole-bar-authority law)
    assert alpaca_item_to_topic_msg({"T": "b", "S": "SPY", "o": 1, "c": 2}) is None
    assert alpaca_item_to_topic_msg({"T": "t", "p": 1.0}) is None  # no symbol -> skip


def test_alpaca_pump_skips_cleanly_without_keys(tmp_path, monkeypatch, capsys):
    """No keys is a SKIP with one printed line — Schwab capture must be unaffected."""
    import tools.run_stream_capture as d
    monkeypatch.setattr(d, "ALPACA_ENV_PATH", tmp_path / "missing.env")
    for var in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    from stream_spine import HealthRegistry, MessageBus

    async def go():
        stop = asyncio.Event()
        await d.alpaca_pump(["SPY"], MessageBus(), HealthRegistry(), d.CaptureStats(), stop)

    asyncio.run(go())
    assert "prints leg skipped" in capsys.readouterr().out


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


def test_alpaca_session_recycles_on_silent_socket(monkeypatch):
    """A half-open socket raises NOTHING — the session must return True (recycle)
    once quiet passes the bar, instead of spinning on timeouts forever."""
    import json as _json

    import tools.run_stream_capture as m

    monkeypatch.setattr(m, "ALPACA_STALE_RECONNECT_SEC", 0.05)

    class FakeWS:
        def __init__(self):
            self.frames = [
                _json.dumps([{"T": "success", "msg": "connected"}]),
                _json.dumps([{"T": "success", "msg": "authenticated"}]),
            ]
            self.sent = []

        async def recv(self):
            if self.frames:
                return self.frames.pop(0)
            await asyncio.sleep(3600)   # half-open: silent forever, no exception
            return None                 # unreachable in test; satisfies RET503

        async def send(self, data):
            self.sent.append(data)

    async def _run():
        bus = MessageBus()
        health = HealthRegistry()
        stats = CaptureStats()
        stop = asyncio.Event()
        return await asyncio.wait_for(
            m._alpaca_session(FakeWS(), ["SPY"], "k", "s", bus, health, stats, stop),
            timeout=10)

    assert asyncio.run(_run()) is True, "silent socket must signal recycle, not hang"


# ─────────────────────────────────────────────────────────────────────────────
# PR214 premerge gap 3 — ORPHAN RECONCILIATION MUST PRECEDE SCHWAB AUTH.
# _run_locked used to build the Schwab client FIRST and return 2 on auth failure, so a
# prior hard death plus an expired/broken token meant reconciliation never ran and that
# dead lifetime's epochs stayed falsely open -- indefinitely subscribed while no daemon
# was running -- for as long as the token stayed broken. Reconciliation depends on the
# owner lock and the canonical DB, NOT on the vendor.
# ─────────────────────────────────────────────────────────────────────────────

def test_gap3_orphans_are_reconciled_even_when_schwab_auth_fails(tmp_path, monkeypatch):
    import sqlite3

    import tools.run_stream_capture as m

    db = tmp_path / "stream_capture.db"
    A = "SPY   260820C00767000"

    # ── prior daemon lifetime died HARD: two epochs left open, never closed ──
    seed = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    seed.open_coverage_epoch(A, "LEVELONE_OPTIONS", reason="active_contract_set", ts=100.0)
    seed.open_coverage_epoch(A, "OPTIONS_BOOK", reason="active_contract_set", ts=100.0)
    seed.close()

    # ── this lifetime: Schwab auth is BROKEN ──
    monkeypatch.setattr("config.build_config",
                        lambda _root: SimpleNamespace(api_key="k", app_secret="s",
                                                      token_path="tok"))
    monkeypatch.setattr("schwab_client.build_client_from_token",
                        lambda **kw: SimpleNamespace(ok=False, client=None,
                                                     message="refresh token expired"))
    streamed = {"ran": False}

    async def _never(*a, **k):
        streamed["ran"] = True
        return 0
    monkeypatch.setattr(m, "_run_streaming", _never)

    rc = asyncio.run(m._run_locked(["SPY"], 0.0, str(db)))

    assert rc == 2, "a broken Schwab token must still fail the daemon startup"
    assert streamed["ran"] is False, "the daemon must not pretend streaming started"

    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT started_ts, ended_ts, reason FROM stream_coverage_epochs ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) == 2, "no NEW live epoch may be created on the auth-failure path"
    assert all(r[1] is not None for r in rows), (
        "the prior lifetime's orphan epochs must be reconciled BEFORE the vendor "
        "dependency is taken -- a broken token must not leave them falsely open")
    assert all(r[2] == CaptureWriter.COVERAGE_ORPHAN_REASON for r in rows)
    assert all(r[0] == 100.0 for r in rows), "history closed, never rewritten"


def test_gap3_writer_is_closed_on_the_auth_failure_path(tmp_path, monkeypatch):
    """The writer opened for reconciliation must be cleaned up on the auth-failure exit,
    not leaked -- the reconciliation commit is already durable by then."""
    import tools.run_stream_capture as m

    db = tmp_path / "stream_capture.db"
    closed = {"n": 0}
    real_close = m.CaptureWriter.close

    def _tracking_close(self):
        closed["n"] += 1
        return real_close(self)
    monkeypatch.setattr(m.CaptureWriter, "close", _tracking_close)
    monkeypatch.setattr("config.build_config",
                        lambda _root: SimpleNamespace(api_key="k", app_secret="s",
                                                      token_path="tok"))
    monkeypatch.setattr("schwab_client.build_client_from_token",
                        lambda **kw: SimpleNamespace(ok=False, client=None, message="nope"))

    rc = asyncio.run(m._run_locked(["SPY"], 0.0, str(db)))
    assert rc == 2
    assert closed["n"] >= 1, "the CaptureWriter must be closed on the auth-failure path"
