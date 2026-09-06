"""CR-01 daemon contracts (offline): parser, handler seam into the REAL bus/writer."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from stream_spine import (
    COUNT_DROPS,
    CaptureWriter,
    CoverageWriteError,
    HealthRegistry,
    MessageBus,
    read_active_option_contract_signal,
    read_active_ticker_signal,
    write_active_option_contract_signal,
    write_active_ticker_signal,
)
from app.market_data.schwab.streaming.capture import (
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


@pytest.fixture(autouse=True)
def _isolated_desired_state_signals(tmp_path, monkeypatch):
    """Give every test in this file its OWN active-ticker / active-option-contract signal
    files, instead of the process-wide repo defaults.

    Those defaults are single repo-relative paths bound at import time
    (`ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT`, `ACTIVE_TICKER_SIGNAL_DEFAULT`). Four test
    files write them, 28 call sites in total, and protected CI runs pytest under xdist —
    so a test here would set the desired contract to B while a test on another worker set
    it to something else, and the daemon under test read the loser of that race. Measured
    on CI ([gw2]) and reproduced locally 3/3 under `-n 4`: the generation-1 tick saw
    `held == requested`, never issued the unsubscribe, never reached the parked seam, and
    `parked.wait()` timed out at 25s. The bound was never the problem; the daemon was
    reading another worker's desired state.

    Both halves are redirected: the WRITERS this module calls, and the READERS the daemon
    itself calls (`tools.run_stream_capture` looks these up as module globals at call
    time, so patching them there covers the poll loops and the recycle's reconnect read).
    Nothing about the ordering invariant changes — the daemon still reads a real signal
    file through its real seam; only the path stops being shared."""
    import sys as _sys

    import stream_spine as _spine
    import app.market_data.schwab.streaming.capture as _d

    option_sig = tmp_path / "stream_active_option_contract.json"
    ticker_sig = tmp_path / "stream_active_ticker.json"
    this_module = _sys.modules[__name__]

    # Bind the originals off stream_spine, NOT off this module's globals: the globals are
    # what is being replaced, so a lambda that looked them up would call itself.
    real_write_opt = _spine.write_active_option_contract_signal
    real_write_tkr = _spine.write_active_ticker_signal
    real_read_opt = _spine.read_active_option_contract_signal
    real_read_tkr = _spine.read_active_ticker_signal

    # `{"path": default, **kw}` — the per-test path is only a DEFAULT. A caller that
    # already passes an explicit `path=` (a test doing its own finer-grained isolation)
    # still wins; swallowing it would silently redirect that test's signal file.
    monkeypatch.setattr(this_module, "write_active_option_contract_signal",
                        lambda c, **kw: real_write_opt(c, **{"path": option_sig, **kw}))
    monkeypatch.setattr(this_module, "write_active_ticker_signal",
                        lambda t, **kw: real_write_tkr(t, **{"path": ticker_sig, **kw}))
    monkeypatch.setattr(_d, "read_active_option_contract_signal",
                        lambda **kw: real_read_opt(**{"path": option_sig, **kw}))
    monkeypatch.setattr(_d, "read_active_ticker_signal",
                        lambda **kw: real_read_tkr(**{"path": ticker_sig, **kw}))


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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_ticker_signal",
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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_ticker_signal", lambda: "SPY")
    stream = _FakeStream()

    async def go():
        new_cur = await _apply_active_ticker_book_subs(stream, "SPY")
        assert new_cur == "SPY"
        assert stream.calls == []
    asyncio.run(go())


def test_apply_active_ticker_book_subs_first_activation_has_no_unsub(monkeypatch):
    """No current ticker yet (daemon just started, no viewer active) -> subscribe only,
    never an unsub call for a symbol that was never subscribed."""
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_ticker_signal", lambda: "SPY")
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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_option_contract_signal",
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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FakeOptionStream()

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        new_state = await _apply_active_option_contract_subs(stream, state)
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        assert stream.calls == []
    asyncio.run(go())


def test_apply_active_option_contract_subs_first_activation_has_no_unsub(monkeypatch):
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_option_contract_signal",
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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_option_contract_signal",
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
    monkeypatch.setattr("app.market_data.schwab.streaming.capture.read_active_option_contract_signal",
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
    import app.market_data.schwab.streaming.capture as d

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
    import app.market_data.schwab.streaming.capture as d

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
    import app.market_data.schwab.streaming.capture as d

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
    import app.market_data.schwab.streaming.capture as d

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


#: DELETED: test_recycle_cancels_old_pump_before_reconnecting_structurally.
#: It indexed _run_streaming's SOURCE TEXT for "pump_task.cancel()" before
#: "_schwab_connect(" — a spelling pin that broke the moment the cancellation moved into
#: a named helper, and that never covered the real hazard anyway (the CONTROL TASKS, not
#: the pump, were what survived a generation). Replaced by the behavioural
#: test_recycle_retires_the_old_generation_before_the_replacement_is_built below, which
#: asserts the same ordering against recorded lifecycle events.


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
    from app.market_data.schwab.streaming.capture import alpaca_rfc3339_to_ms
    assert alpaca_rfc3339_to_ms("2026-07-22T20:22:23.626206217Z") == 1784751743626
    assert alpaca_rfc3339_to_ms("2026-07-22T20:22:23Z") == 1784751743000
    assert alpaca_rfc3339_to_ms(None) is None
    assert alpaca_rfc3339_to_ms("garbage") is None


def test_alpaca_items_flow_through_real_bus_and_writer_to_db(tmp_path):
    """CR-02 seam: Alpaca-shaped trade + NBBO items -> REAL bus -> REAL CaptureWriter
    -> rows readable back out of a REAL stream_capture db (src=alpaca_iex)."""
    import sqlite3
    from stream_spine import CaptureWriter, MessageBus
    from app.market_data.schwab.streaming.capture import alpaca_item_to_topic_msg

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
    from app.market_data.schwab.streaming.capture import alpaca_item_to_topic_msg
    assert alpaca_item_to_topic_msg({"T": "success", "msg": "authenticated"}) is None
    assert alpaca_item_to_topic_msg({"T": "subscription", "trades": ["SPY"]}) is None
    # bars deliberately excluded: canonical 1m stays Schwab's (sole-bar-authority law)
    assert alpaca_item_to_topic_msg({"T": "b", "S": "SPY", "o": 1, "c": 2}) is None
    assert alpaca_item_to_topic_msg({"T": "t", "p": 1.0}) is None  # no symbol -> skip


def test_alpaca_pump_skips_cleanly_without_keys(tmp_path, monkeypatch, capsys):
    """No keys is a SKIP with one printed line — Schwab capture must be unaffected."""
    import app.market_data.schwab.streaming.capture as d
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
    import app.market_data.schwab.streaming.capture as d

    db = tmp_path / "cap.db"
    lock = tmp_path / "stream_capture.lock"

    fake_cfg = types.SimpleNamespace(api_key="k", app_secret="s", token_path="t")
    monkeypatch.setitem(sys.modules, "config",
                        types.SimpleNamespace(build_config=lambda _r: fake_cfg))

    # Path 1: client init fails -> rc 2, lock gone
    monkeypatch.setitem(sys.modules, "schwab_client", types.SimpleNamespace(
        build_client_from_token=lambda **_k: types.SimpleNamespace(
            ok=False, client=None, message="nope")))
    rc = aio.run(d.run(["SPY"], 0.0, str(db)))
    assert rc == 2 and not lock.exists()

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
        aio.run(d.run(["SPY"], 0.0, str(db)))
    assert not lock.exists(), "lock leaked on login failure"


def test_second_owner_refused_while_lock_held(tmp_path, monkeypatch):
    import app.market_data.schwab.streaming.capture as d
    import pytest as _pt
    db = tmp_path / "cap.db"
    lock = tmp_path / "stream_capture.lock"
    fd, held = d.acquire_owner_lock(db)
    try:
        with _pt.raises(SystemExit):
            d.acquire_owner_lock(db)      # our own live pid holds it -> refuse
    finally:
        d.release_owner_lock(fd, held)
    assert not lock.exists()


# ── half-open-socket guard (2026-07-23, observed live: both feeds silent, no error) ──


def test_stream_needs_recycle_decision_boundaries():
    from app.market_data.schwab.streaming.capture import (
        RECONNECT_COOLDOWN_SEC,
        STREAM_STALE_RECONNECT_SEC,
        stream_needs_recycle,
    )

    ok_cool = RECONNECT_COOLDOWN_SEC + 1
    stale = STREAM_STALE_RECONNECT_SEC + 1
    assert stream_needs_recycle(stale, True, ok_cool, True) is True
    # overnight / closed-market silence is not a half-open socket
    assert stream_needs_recycle(stale, True, ok_cool, False) is False
    # never recycle: no age yet / never saw data (subscribe problem, not half-open)
    assert stream_needs_recycle(None, True, ok_cool, True) is False
    assert stream_needs_recycle(stale, False, ok_cool, True) is False
    # never login-spam: inside cooldown stays put even when stale
    assert stream_needs_recycle(stale, True, RECONNECT_COOLDOWN_SEC - 1, True) is False
    # fresh feed stays connected
    assert stream_needs_recycle(STREAM_STALE_RECONNECT_SEC - 1, True, ok_cool, True) is False


def test_alpaca_session_recycles_on_silent_socket(monkeypatch):
    """A half-open socket raises NOTHING — the session must return True (recycle)
    once quiet passes the bar, instead of spinning on timeouts forever."""
    import json as _json

    import app.market_data.schwab.streaming.capture as m

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

    import app.market_data.schwab.streaming.capture as m

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
    import app.market_data.schwab.streaming.capture as m

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


# ─────────────────────────────────────────────────────────────────────────────
# PR214 STREAM LIFECYCLE TRUTH — stream-generation ownership, session retirement,
# and the shutdown coverage boundary. Driven through the REAL _run_streaming /
# poll / recycle seams, with asyncio Events (never sleeps) as the ordering proof.
# ─────────────────────────────────────────────────────────────────────────────

_A_CONTRACT = "SPY   260820C00767000"
_B_CONTRACT = "QQQ   260820C00450000"


class _LifecycleStream:
    """StreamClient double instrumented at the REAL lifecycle seam.

    Counts logins/logouts and tracks live + max-live sessions, so "at most one LIVE,
    LOGGED-IN Schwab session" is a MEASURED runtime fact rather than a structural
    inference. `park_on` suspends one named vendor operation for one generation until an
    Event is released — that is exactly the seam where a poll tick gets caught by a
    recycle."""

    live = 0
    max_live = 0
    logins = 0
    logouts = 0
    retire_disabled = False      # mutation control for the one-live-session invariant
    generations: list = []
    events: list = []
    park_on: tuple = ()
    parked = None
    release = None

    #: The counters below are the shared LEDGER and are always resolved on
    #: _LifecycleStream itself, never on type(self): subclasses (see
    #: _FailingInitialConnectStream) would otherwise shadow them with their own
    #: attributes on first write, and every count would silently read zero.
    def __init__(self, client, account_id=None):
        _LifecycleStream.generations.append(self)
        self.gen = len(_LifecycleStream.generations)
        self.client = client
        self.logged_in = False
        sock = SimpleNamespace(closed=False)
        sock.close = lambda: setattr(sock, "closed", True)
        self._socket = sock

    def _log(self, label, detail=None):
        _LifecycleStream.events.append((label, self.gen, detail))

    def _noop(self, h):
        return None
    add_level_one_equity_handler = _noop
    add_chart_equity_handler = _noop
    add_nasdaq_book_handler = _noop
    add_nyse_book_handler = _noop
    add_level_one_option_handler = _noop
    add_options_book_handler = _noop

    async def login(self):
        cls = _LifecycleStream
        self.logged_in = True
        cls.live += 1
        cls.logins += 1
        cls.max_live = max(cls.max_live, cls.live)
        self._log("login")

    async def logout(self):
        cls = _LifecycleStream
        if cls.retire_disabled:
            # MUTATION CONTROL: the session is never actually retired.
            self._log("logout_suppressed")
            return
        if self.logged_in:
            self.logged_in = False
            cls.live -= 1
        cls.logouts += 1
        self._log("logout")

    async def _vendor(self, name, syms):
        cls = _LifecycleStream
        if cls.park_on == (self.gen, name):
            self._log(f"PARK ENTER {name}")
            cls.parked.set()
            await cls.release.wait()
            self._log(f"PARK RESUME {name}")
        self._log(f"VENDOR {name}", syms[0] if syms else None)

    async def level_one_equity_subs(self, syms): pass
    async def chart_equity_subs(self, syms): pass

    async def nasdaq_book_subs(self, syms):
        await self._vendor("nasdaq_book_subs", syms)

    async def nyse_book_subs(self, syms):
        await self._vendor("nyse_book_subs", syms)

    async def nasdaq_book_unsubs(self, syms):
        await self._vendor("nasdaq_book_unsubs", syms)

    async def nyse_book_unsubs(self, syms):
        await self._vendor("nyse_book_unsubs", syms)

    async def level_one_option_subs(self, syms):
        await self._vendor("level_one_option_subs", syms)

    async def options_book_subs(self, syms):
        await self._vendor("options_book_subs", syms)

    async def level_one_option_unsubs(self, syms):
        await self._vendor("level_one_option_unsubs", syms)

    async def options_book_unsubs(self, syms):
        await self._vendor("options_book_unsubs", syms)

    async def handle_message(self):
        await asyncio.sleep(3600)


def _reset_lifecycle(park_on=(), retire_disabled=False):
    cls = _LifecycleStream
    cls.live = cls.max_live = cls.logins = cls.logouts = 0
    cls.generations = []
    cls.events = []
    cls.park_on = park_on
    cls.retire_disabled = retire_disabled
    cls.parked = asyncio.Event()
    cls.release = asyncio.Event()
    return cls


def _install_lifecycle_stream(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "schwab.streaming",
                        types.SimpleNamespace(StreamClient=_LifecycleStream))


def _epoch_rows(db):
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT id, symbol, service, started_ts, ended_ts "
            "FROM stream_coverage_epochs ORDER BY id").fetchall()
    finally:
        con.close()


def _one_shot_recycle(gate: asyncio.Event):
    """Half-open decision replacement: fires exactly ONCE, when `gate` is set — so the
    recycle is triggered by a deterministic condition instead of elapsed time."""
    fired = {"x": False}

    def decide(age_sec, seen_data, since_last_reconnect, collect_session_live=True):
        if gate.is_set() and not fired["x"]:
            fired["x"] = True
            return True
        return False
    return decide


async def _await_event(pred, *, timeout=25.0, what="condition"):
    """Sequence the driver against the daemon's own recorded events. Used only to ORDER
    the driver's steps; every ordering ASSERTION is made against the event log itself."""
    import time as _t
    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


async def _drive_daemon(m, db, *, driver, symbols=("SPY",), probe=None,
                        state=None, state_factory=None):
    """Run the REAL _run_streaming with the lifecycle-instrumented StreamClient."""
    writer = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    bus = MessageBus()
    wsub = bus.subscribe("", policy=COUNT_DROPS)
    health, stats, stop = HealthRegistry(), CaptureStats(), asyncio.Event()
    # A real (quiet) beat so the watchdog branch formats a real age, exactly as live.
    health.beat("LEVELONE_EQUITIES")
    stats.per_service["LEVELONE_EQUITIES"] = 1

    drv = asyncio.create_task(driver(stop, writer))
    initial_state = state or SimpleNamespace(client=object())
    run = asyncio.create_task(
        m._run_streaming(list(symbols), 0.0, bus, health, stats, writer, wsub, stop,
                         initial_state, state_factory=state_factory))
    try:
        await asyncio.wait_for(drv, timeout=45)
        await asyncio.wait_for(run, timeout=45)
        if probe is not None:
            # Snapshot INSIDE the loop: asyncio.run() cancels whatever is still pending
            # on its way out, so anything read afterwards looks tidily cancelled.
            probe.at_return = probe.state()
    finally:
        for t in (drv, run):
            if not t.done():
                t.cancel()


def test_d1_a_stale_generation_tick_cannot_mutate_the_next_generation(tmp_path, monkeypatch):
    """DEFECT 1. A poll tick belonging to stream generation N, suspended inside a REAL
    vendor await when a recycle begins, must not resume into generation N+1's world.

    MEASURED BEFORE the per-generation control tasks existed, through these same seams:
    the parked generation-1 tick resumed after generation 2 was live and covered, then
    issued FIVE vendor operations on the retired stream (two of them SUBSCRIBING the
    current contract on a dead session), CLOSED generation 2's live OPTIONS_BOOK epoch
    (row id 4), opened a duplicate (row id 5), and replaced generation 2's epoch id in
    the shared state (book: 4 -> 5).

    Without this test that whole class returns silently: nothing else in the suite
    exercises a control operation that outlives the stream it was issued against."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle(park_on=(1, "level_one_option_unsubs"))
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_option_contract_signal(_A_CONTRACT)
    captured = {}

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs" and e[1] == 1
                        and e[2] == _A_CONTRACT for e in _LifecycleStream.events),
            what="generation 1 to subscribe A")
        write_active_option_contract_signal(_B_CONTRACT)
        await asyncio.wait_for(_LifecycleStream.parked.wait(), timeout=25)
        gate.set()                       # recycle WHILE the tick is parked in the vendor
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs" and e[1] == 2
                        for e in _LifecycleStream.events),
            what="generation 2 to subscribe B")
        await asyncio.sleep(0.15)        # let generation 2 finish opening its epochs
        captured["gen2_rows"] = _epoch_rows(db)
        captured["mark"] = len(_LifecycleStream.events)
        _LifecycleStream.release.set()   # release the stale generation-1 operation
        await asyncio.sleep(0.6)         # give stale work every chance to run
        captured["after_rows"] = _epoch_rows(db)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    labels = [(e[0], e[1]) for e in _LifecycleStream.events]
    assert ("logout", 1) in labels, "generation 1's session must be retired"
    assert labels.index(("logout", 1)) < labels.index(("login", 2)), (
        f"the old session must be retired before the replacement logs in: {labels}")

    stale_after = [e for e in _LifecycleStream.events[captured["mark"]:]
                   if e[1] == 1 and e[0].startswith("VENDOR")]
    assert stale_after == [], (
        f"generation 1 issued vendor operations on a retired stream: {stale_after}")

    assert captured["after_rows"] == captured["gen2_rows"], (
        "stale generation-1 work mutated generation 2's durable coverage\n"
        f"  before release: {captured['gen2_rows']}\n"
        f"  after  release: {captured['after_rows']}")
    open_rows = [r for r in captured["after_rows"] if r[4] is None]
    assert len(open_rows) == 2, f"one open epoch per option service; got {open_rows}"
    assert {r[1] for r in open_rows} == {_B_CONTRACT}, (
        f"generation 2's epochs must still be on B: {open_rows}")


def test_1c_a_stale_book_poll_tick_cannot_mutate_after_a_recycle(tmp_path, monkeypatch):
    """DEFECT 1C. _active_ticker_book_poll_loop is the option poll's direct sibling: it
    issues vendor subscribe/unsubscribe against whatever StreamClient is current, from a
    task that used to survive every recycle. It carries no coverage ledger, so it cannot
    corrupt durable rows — but it CAN issue book subscriptions on a retired session and
    write a stale ticker back over the new generation's state.

    ADJUDICATION: EQUIVALENT RACE, and FIXED by the same mechanism — the book poll is one
    of the per-generation control tasks, so _retire_stream_generation cancels AND awaits
    it before the replacement exists.

    Earns its existence by pinning the book loop INSIDE the generation boundary: an edit
    that hoisted it back out would restore the race with nothing else objecting."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle(park_on=(1, "nasdaq_book_unsubs"))
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_ticker_signal("SPY")
    write_active_option_contract_signal(_A_CONTRACT)
    captured = {}

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "VENDOR nasdaq_book_subs" and e[1] == 1
                        for e in _LifecycleStream.events),
            what="generation 1 to subscribe the SPY book")
        write_active_ticker_signal("QQQ")
        await asyncio.wait_for(_LifecycleStream.parked.wait(), timeout=25)
        gate.set()
        await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                           what="generation 2 to be constructed")
        await asyncio.sleep(0.15)
        captured["mark"] = len(_LifecycleStream.events)
        _LifecycleStream.release.set()
        await asyncio.sleep(0.6)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    stale_after = [e for e in _LifecycleStream.events[captured["mark"]:]
                   if e[1] == 1 and e[0].startswith("VENDOR")]
    assert stale_after == [], (
        f"the book poll issued vendor operations on a retired stream: {stale_after}")
    labels = [(e[0], e[1]) for e in _LifecycleStream.events]
    assert labels.index(("logout", 1)) < labels.index(("login", 2))


def test_recycle_retires_the_old_generation_before_the_replacement_is_built(tmp_path,
                                                                            monkeypatch):
    """REPLACES a source-text test that asserted `pump_task.cancel()` appeared before
    `_schwab_connect(` in _run_streaming's source. That pinned a spelling rather than a
    behaviour, and it could not see the actual defect: the CONTROL TASKS, not the pump,
    were what outlived a generation. This is the same contract as a behavioural ordering
    proof over the daemon's own recorded lifecycle events."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_option_contract_signal(_A_CONTRACT)

    async def driver(stop, writer):
        await _await_event(lambda: any(e[0] == "login" for e in _LifecycleStream.events),
                           what="generation 1 login")
        gate.set()
        await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                           what="generation 2")
        await asyncio.sleep(0.2)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    labels = [(e[0], e[1]) for e in _LifecycleStream.events]
    assert labels.index(("logout", 1)) < labels.index(("login", 2)), (
        f"generation 1 must be logged out before generation 2 logs in: {labels}")
    assert _LifecycleStream.max_live <= 1, (
        f"two sessions were live at once (max {_LifecycleStream.max_live})")


def test_each_stream_generation_closes_its_rest_transport_after_login(tmp_path,
                                                                       monkeypatch):
    """The websocket generation must not retain its one-shot preferences REST socket."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_option_contract_signal(_A_CONTRACT)
    sessions = []

    class _RestSession:
        def __init__(self):
            self.close_count = 0

        def close(self):
            self.close_count += 1

    def state_factory():
        session = _RestSession()
        sessions.append(session)
        return SimpleNamespace(
            ok=True,
            message="ok",
            client=SimpleNamespace(session=session),
        )

    initial_state = state_factory()

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "login" and e[1] == 1 for e in _LifecycleStream.events),
            what="generation 1 login",
        )
        gate.set()
        await _await_event(
            lambda: any(e[0] == "login" and e[1] == 2 for e in _LifecycleStream.events),
            what="generation 2 login",
        )
        stop.set()

    asyncio.run(_drive_daemon(
        m,
        db,
        driver=driver,
        state=initial_state,
        state_factory=state_factory,
    ))

    assert len(sessions) == 2, "initial connect and one recycle need distinct REST clients"
    assert [session.close_count for session in sessions] == [1, 1]


def test_d2_shutdown_ended_ts_is_the_surrender_instant_not_the_drain_completion(
        tmp_path, monkeypatch):
    """DEFECT 2. Clean shutdown must not claim coverage across the writer drain.

    Order is: producers quiesced (T1) -> writer drains (T2, bounded at 60s) -> durable
    epoch close. Capture is impossible from T1, but ended_ts used to be stamped when the
    close finally ran, at T2 or later. That converts "our capture had already stopped"
    into "we stayed subscribed and the vendor went silent" — the same false-positive
    class as the transition-interval defect, at the other end of the session.

    MEASURED here with a deliberately SLOW writer drain: the recorded ended_ts must be
    the surrender boundary, never the drain completion. Persistence may be late; the
    RECORDED TIME may not move."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(m, "stream_needs_recycle", lambda *a: False)
    write_active_option_contract_signal(_A_CONTRACT)

    marks = {}
    real_run = CaptureWriter.run

    async def slow_run(self, sub, stop=None):
        try:
            return await real_run(self, sub, stop=stop)
        finally:
            # The drain itself takes real time; capture has been impossible since the
            # producers were cancelled, well before this returns.
            marks["drain_start"] = time.time()
            await asyncio.sleep(0.75)
            marks["drain_done"] = time.time()
    monkeypatch.setattr(CaptureWriter, "run", slow_run)

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs" for e in _LifecycleStream.events),
            what="the contract to be subscribed")
        await asyncio.sleep(0.1)
        marks["stop_requested"] = time.time()
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    rows = _epoch_rows(db)
    assert rows, "the shutdown must have produced coverage rows"
    assert all(r[4] is not None for r in rows), f"every epoch must be closed: {rows}"
    ended = max(r[4] for r in rows)

    assert marks["drain_done"] > marks["drain_start"], "the drain must have taken time"
    over_claim = ended - marks["stop_requested"]
    assert ended <= marks["drain_start"], (
        f"ended_ts ({ended}) must not be stamped at or after the drain "
        f"({marks['drain_start']}) — that claims coverage across a window in which "
        f"capture was already impossible; over-claim was {over_claim:.3f}s")
    assert ended < marks["drain_done"], (
        f"ended_ts ({ended}) must precede drain completion ({marks['drain_done']})")
    # Conservative direction: the boundary is at or BEFORE the stop request.
    assert ended <= marks["stop_requested"] + 0.05, (
        f"ended_ts ({ended}) must be the surrender boundary, not a later instant; "
        f"stop was requested at {marks['stop_requested']}")


def test_d2_a_failed_shutdown_close_still_records_the_surrender_instant(tmp_path,
                                                                        monkeypatch):
    """DEFECT 2, repair path. If the shutdown close itself fails and is only repaired
    later, the ORIGINAL shutdown surrender timestamp must survive — exactly as the
    pending-close map already preserves other surrender times. Otherwise the repair
    re-introduces the over-claim it was meant to avoid."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_A_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        surrendered = 500.0

        def _boom(*a, **k):
            raise CoverageWriteError("db unavailable during shutdown")
        real_close = w.close_coverage_epoch
        monkeypatch.setattr(w, "close_coverage_epoch", _boom)
        m._close_coverage_epoch_tracked(w, epoch_state, "l1", reason="shutdown",
                                        surrendered_ts=surrendered)
        assert set(epoch_state.get("l1_pending_close") or {}) == {eid}

        # Repaired much later, by a later lifetime's retry pass.
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        m._retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")

        rows = _epoch_rows(db)
        assert rows[0][4] == surrendered, (
            f"the repair must replay the ORIGINAL shutdown surrender instant "
            f"({surrendered}); got {rows[0][4]}")
    finally:
        w.close()


def test_d3d_at_most_one_live_logged_in_session_across_the_whole_lifecycle(tmp_path,
                                                                           monkeypatch):
    """DEFECT 3D. The RUNTIME complement to the static one-constructor gate, which cannot
    see an abandoned-but-still-logged-in session.

    Exercises A initial connect, B watchdog recycle, C replacement connect, D second
    recycle, E clean shutdown — asserting at every observable boundary that at most one
    session is live, and that ZERO remain at exit."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gates = [asyncio.Event(), asyncio.Event()]
    fired = {"n": 0}

    def decide(age_sec, seen_data, since_last_reconnect, collect_session_live=True):
        if fired["n"] < len(gates) and gates[fired["n"]].is_set():
            fired["n"] += 1
            return True
        return False
    monkeypatch.setattr(m, "stream_needs_recycle", decide)
    write_active_option_contract_signal(_A_CONTRACT)
    observed = []

    async def driver(stop, writer):
        async def watch():
            while not stop.is_set():
                observed.append(_LifecycleStream.live)
                await asyncio.sleep(0.005)
        w = asyncio.create_task(watch())
        try:
            await _await_event(lambda: len(_LifecycleStream.generations) >= 1,
                               what="A: initial connect")
            gates[0].set()                                       # B: watchdog recycle
            await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                               what="C: replacement connect")
            gates[1].set()                                       # D: second recycle
            await _await_event(lambda: len(_LifecycleStream.generations) >= 3,
                               what="third generation")
            await asyncio.sleep(0.2)
            stop.set()                                           # E: clean shutdown
        finally:
            w.cancel()
            try:
                await w
            except asyncio.CancelledError:
                pass

    asyncio.run(_drive_daemon(m, db, driver=driver))

    assert len(_LifecycleStream.generations) >= 3, "A-D must have built three generations"
    assert _LifecycleStream.max_live <= 1, (
        f"LIVE_LOGGED_IN_STREAMCLIENT_COUNT exceeded 1 (max "
        f"{_LifecycleStream.max_live}); observed samples: {sorted(set(observed))}")
    assert max(observed) <= 1, f"sampled live count exceeded 1: {sorted(set(observed))}"
    assert _LifecycleStream.live == 0, (
        f"clean shutdown must leave ZERO live sessions; {_LifecycleStream.live} remain")
    assert _LifecycleStream.logouts == _LifecycleStream.logins, (
        f"every session must be retired: {_LifecycleStream.logins} logins vs "
        f"{_LifecycleStream.logouts} logouts")
    assert all(g._socket.closed for g in _LifecycleStream.generations), (
        "logout() does not close the websocket in schwab-py 1.5.1 — the transport must "
        "be closed explicitly for every retired generation")


def test_d3d_mutation_control_without_retirement_the_invariant_fails(tmp_path, monkeypatch):
    """DEFECT 3D negative control. With retirement suppressed, the lifecycle assertions
    above MUST fail — otherwise they prove nothing and would pass on a daemon that leaks
    a logged-in session on every recycle."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle(retire_disabled=True)
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_option_contract_signal(_A_CONTRACT)

    async def driver(stop, writer):
        await _await_event(lambda: len(_LifecycleStream.generations) >= 1, what="connect")
        gate.set()
        await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                           what="replacement")
        await asyncio.sleep(0.2)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    assert _LifecycleStream.max_live > 1, (
        "MUTATION CONTROL FAILED TO BITE: with retirement suppressed two sessions must "
        f"have been live at once, but max_live was {_LifecycleStream.max_live} — the "
        "one-live-session assertions above would then be vacuous")
    assert _LifecycleStream.live > 0, (
        "MUTATION CONTROL FAILED TO BITE: a suppressed retirement must leave a live "
        "session at exit")


def test_d3c_a_partial_connect_failure_after_login_retires_the_session(tmp_path,
                                                                       monkeypatch):
    """DEFECT 3C. _schwab_connect can log in successfully and then raise before it ever
    returns a pump — a failed resubscribe, or an OptionCoverageCompensationError out of
    the reconciliation. That used to abandon a LIVE, LOGGED-IN session with nothing
    reading it and nothing logging it out, on an account that permits one.

    Proves the partial session is explicitly retired, its live count returns to zero, no
    pump exists for it, and the failure still propagates unchanged."""
    import app.market_data.schwab.streaming.capture as m

    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)

    boom = m.OptionCoverageCompensationError("forced coverage escalation during connect")

    async def _raise_after_login(*a, **k):
        raise boom
    monkeypatch.setattr(m, "_schwab_connect_after_login", _raise_after_login)

    async def go():
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        with pytest.raises(m.OptionCoverageCompensationError) as exc:
            await m._schwab_connect(SimpleNamespace(client=object()), ["SPY"],
                                    bus, health, stats, stop,
                                    active_option_contract=_A_CONTRACT)
        return exc.value
    raised = asyncio.run(go())

    assert raised is boom, "retirement is cleanup, never a verdict: re-raise unchanged"
    assert _LifecycleStream.logins == 1, "the session did log in"
    assert _LifecycleStream.live == 0, (
        "a partially-built session must not stay logged in after the failure")
    assert _LifecycleStream.logouts == 1, "it must be retired through the canonical seam"
    assert _LifecycleStream.generations[0]._socket.closed, (
        "the transport must be closed too — logout() leaves it open in schwab-py 1.5.1")


def test_d3c_a_coverage_escalation_during_reconnect_is_not_downgraded(tmp_path, monkeypatch):
    """DEFECT 3C. A coverage escalation raised out of the reconnect must not be silently
    absorbed by the watchdog's generic `except Exception: reconnect FAILED` handler.

    That handler leaves recovery to the half-open heuristic, which this condition never
    trips (the socket is not stale — there is no socket), and option_recycle_request was
    already cleared, so the rebuild could stall indefinitely. The escalation must re-arm
    the forced rebuild instead."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))
    write_active_option_contract_signal(_A_CONTRACT)

    real_after_login = m._schwab_connect_after_login
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:      # the RECONNECT attempt, not the initial connect
            raise m.OptionCoverageCompensationError("escalation during reconnect")
        return await real_after_login(*a, **k)
    monkeypatch.setattr(m, "_schwab_connect_after_login", flaky)

    async def driver(stop, writer):
        await _await_event(lambda: len(_LifecycleStream.generations) >= 1, what="connect")
        gate.set()
        # Generation 2 logs in, then its reconnect raises. Recovery must be re-armed, so
        # a THIRD generation is built without any further half-open trigger.
        await _await_event(lambda: len(_LifecycleStream.generations) >= 3,
                           what="the re-armed rebuild to produce a third generation")
        await asyncio.sleep(0.2)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    assert calls["n"] >= 3, "the rebuild must have been retried after the escalation"
    assert _LifecycleStream.max_live <= 1, (
        f"the failed generation leaked a live session (max {_LifecycleStream.max_live})")
    assert _LifecycleStream.live == 0, "shutdown must leave zero live sessions"


# ─────────────────────────────────────────────────────────────────────────────
# PR214 INITIALIZATION LIFECYCLE — a failure DURING startup must retire exactly
# what startup had already acquired. Every created task has one owner, and every
# exit path quiesces that task before its resources are closed.
# ─────────────────────────────────────────────────────────────────────────────


class _StartupProbe:
    """Observes the REAL writer task's lifecycle and the writer-close ordering.

    The writer task is captured from inside writer.run() via asyncio.current_task(), so
    the object under observation is the daemon's own task, not a stand-in. close() is
    wrapped to record whether that task was already TERMINAL at the moment the writer's
    resources were released — the ordering law this family exists to protect."""

    def __init__(self, monkeypatch):
        self.task = None
        self.entered = False
        self.exited = False
        self.at_return = None          # snapshot taken inside the loop, before cleanup
        self.close_calls = []          # (task_done, task_cancelled) per close()
        real_run = CaptureWriter.run
        real_close = CaptureWriter.close

        async def run(inner_self, sub, stop=None):
            self.task = asyncio.current_task()
            self.entered = True
            try:
                return await real_run(inner_self, sub, stop=stop)
            finally:
                self.exited = True

        def close(inner_self):
            self.close_calls.append(
                (self.task.done() if self.task else None,
                 self.task.cancelled() if self.task else None))
            return real_close(inner_self)

        monkeypatch.setattr(CaptureWriter, "run", run)
        monkeypatch.setattr(CaptureWriter, "close", close)

    def state(self) -> dict:
        """Snapshot of the writer task, taken INSIDE the running loop.

        It has to be a snapshot: asyncio.run() cancels whatever is still pending on its
        way out, so anything inspected after it returns looks tidily cancelled whether or
        not the daemon ever owned it."""
        return {"entered": self.entered, "exited": self.exited,
                "done": self.task.done() if self.task else None,
                "cancelled": self.task.cancelled() if self.task else None}

    def assert_writer_retired(self):
        snap = self.at_return
        assert snap is not None, "no snapshot was taken inside the loop"
        assert snap["entered"], "the writer task must actually have started"
        assert snap["done"] is True, (
            "the writer task was still running when _run_streaming returned — it is "
            "orphaned: nothing set stop, nothing awaited it, and the caller's "
            f"writer.close() then runs against a live writer.run() (snapshot={snap})")
        assert snap["exited"], "writer.run() must have unwound"

    def assert_close_ordering(self):
        """Every writer.close() must find the writer task already TERMINAL.

        `done is None` (the task had not even begun) counts as a violation too, not a
        pass: a scheduled-but-unstarted writer.run() is exactly as capable of waking up
        against a closed database as a running one."""
        assert self.close_calls, "the writer must have been closed"
        for done, _cancelled in self.close_calls:
            assert done is True, (
                "writer.close() ran while the writer task was NOT terminal — "
                "writer.run() would then operate on a closed database "
                f"(observed close_calls={self.close_calls}, where None means the task "
                "had not started yet)")


async def _run_streaming_expecting_failure(m, db, probe, *, symbols=("SPY",)):
    """Drive the REAL _run_streaming through a startup failure and return the state
    needed to judge ownership: the raised exception, surviving daemon tasks, and a
    snapshot of the writer task taken INSIDE the loop (see _StartupProbe.state)."""
    writer = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    bus = MessageBus()
    wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)
    health, stats, stop = HealthRegistry(), CaptureStats(), asyncio.Event()
    health.beat("LEVELONE_EQUITIES")

    before = set(asyncio.all_tasks())
    raised = None
    try:
        await m._run_streaming(list(symbols), 0.0, bus, health, stats, writer, wsub,
                               stop, SimpleNamespace(client=object()))
    except BaseException as exc:       # noqa: BLE001 — the point is to inspect it
        raised = exc
    await asyncio.sleep(0.05)          # let the loop settle, as before teardown
    probe.at_return = probe.state()
    survivor_names = [t.get_coro().__qualname__ for t in asyncio.all_tasks()
                      if t not in before and t is not asyncio.current_task()
                      and not t.done()]
    survivors = [t for t in asyncio.all_tasks()
                 if t not in before and t is not asyncio.current_task() and not t.done()]
    # The caller (_run_locked) always closes the writer on the way out. Anything the
    # daemon left running would now be operating against a closed database.
    writer.close()
    for i in range(5):                 # real traffic, to expose a live orphan writer
        bus.publish("quote.SPY", {"symbol": "SPY", "bid": 1.0 + i, "ts": 1.0,
                                  "src": "probe"})
    await asyncio.sleep(0.3)
    for t in survivors:                # never leak out of the test itself
        t.cancel()
    return SimpleNamespace(raised=raised, survivors=survivor_names, writer=writer,
                           bus=bus, stop=stop, stop_set=stop.is_set())


class _FailingInitialConnectStream(_LifecycleStream):
    """Logs in, then fails the very first subscribe — a real initial-connect failure."""

    async def level_one_equity_subs(self, syms):
        raise RuntimeError("INITIAL CONNECT FAILED: equity subscribe rejected")


def test_init_a_initial_connect_failure_leaves_no_orphan_writer_task(tmp_path, monkeypatch):
    """CASE A. The initial _schwab_connect() raises before returning a stream.

    MEASURED BEFORE, through this same seam: writer.run() had entered and never exited,
    the task was done()=False cancelled()=False, `stop` was never set, one orphan daemon
    task remained live — and once the caller's `finally: writer.close()` ran, that
    orphan consumed five real bus messages and failed every insert against the closed
    database (insert_errors=5, rows_written=0). The writer task was created before the
    lifecycle try/finally, so an initialization failure bypassed retirement entirely.

    Without this test that whole class returns the moment anyone moves a resource
    acquisition back above the try."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    monkeypatch.setitem(__import__("sys").modules, "schwab.streaming",
                        __import__("types").SimpleNamespace(
                            StreamClient=_FailingInitialConnectStream))
    probe = _StartupProbe(monkeypatch)

    out = asyncio.run(_run_streaming_expecting_failure(m, db, probe))

    assert isinstance(out.raised, RuntimeError), (
        f"the original startup exception must propagate, got {out.raised!r}")
    assert "INITIAL CONNECT FAILED" in str(out.raised), (
        f"the original failure must not be masked by cleanup: {out.raised}")
    probe.assert_writer_retired()
    assert probe.at_return["cancelled"] is False, (
        "the writer must be DRAINED via stop, not cancelled — cancelling would discard "
        "whatever was already queued instead of writing it")
    assert out.stop_set, "the lifecycle boundary must have signalled the writer"
    assert out.survivors == [], (
        f"orphan daemon tasks survived a startup failure: {out.survivors}")
    # The session that DID log in must not outlive the failure either.
    assert _LifecycleStream.live == 0, "a logged-in session leaked on the failure path"
    assert _LifecycleStream.logouts == _LifecycleStream.logins == 1
    probe.assert_close_ordering()
    assert out.writer.insert_errors == 0, (
        f"nothing may write after close: insert_errors={out.writer.insert_errors}")


def test_init_b_post_connect_pre_loop_failure_retires_everything(tmp_path, monkeypatch):
    """CASE B. Initial connect SUCCEEDS, then a later initialization step raises before
    the steady-state loop owns anything.

    The failure is injected at a real startup seam — building the option control task —
    which lands AFTER the stream, pump, writer task and Alpaca task exist and AFTER the
    book-poll control task has already been created. So it also exercises partially
    constructed control tasks, whose first member the caller has no reference to.

    This is what stops the fix from simply moving the orphan one line later."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    probe = _StartupProbe(monkeypatch)
    write_active_option_contract_signal(_A_CONTRACT)

    def _explode(*a, **k):
        raise RuntimeError("STARTUP FAILED: option control task could not be built")
    monkeypatch.setattr(m, "_active_option_contract_poll_loop", _explode)

    out = asyncio.run(_run_streaming_expecting_failure(m, db, probe))

    assert isinstance(out.raised, RuntimeError) and "STARTUP FAILED" in str(out.raised), (
        f"the original startup exception must propagate, got {out.raised!r}")
    assert _LifecycleStream.logins == 1, "the stream did connect before the failure"
    assert _LifecycleStream.live == 0, (
        "the successfully logged-in StreamClient must be retired on a startup failure")
    assert _LifecycleStream.generations[0]._socket.closed, "transport must be closed too"
    probe.assert_writer_retired()
    assert out.stop_set
    assert out.survivors == [], (
        "the pump, the Alpaca producer and the already-created book-poll control task "
        f"must all be terminal; survivors: {out.survivors}")
    probe.assert_close_ordering()
    assert out.writer.insert_errors == 0


def test_init_writer_close_never_precedes_a_terminal_writer_task(tmp_path, monkeypatch):
    """WRITER CLOSE ORDER, on the NORMAL managed exit as well as the failure paths.

    Required order: producers quiesced -> writer drained -> writer task terminal ->
    writer.close(). The two startup-failure tests above assert the same ordering on their
    paths; this one pins it for an ordinary run so the law is not only a failure-path
    property."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    probe = _StartupProbe(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(m, "stream_needs_recycle", lambda *a: False)
    write_active_option_contract_signal(_A_CONTRACT)

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs"
                        for e in _LifecycleStream.events),
            what="the contract to be subscribed")
        await asyncio.sleep(0.1)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver, probe=probe))

    probe.assert_writer_retired()
    probe.assert_close_ordering()
    assert _LifecycleStream.live == 0, "normal shutdown must leave zero live sessions"


def test_init_mutation_control_bypassing_writer_retirement_breaks_the_law(tmp_path,
                                                                          monkeypatch):
    """NEGATIVE CONTROL. With the startup writer-task retirement bypassed, the ownership
    assertions above MUST fail — otherwise they would pass on a daemon that orphans its
    writer, which is exactly the state this mission was opened to fix.

    Bypass is applied at the retirement seam itself (a _shutdown_sequence that quiesces
    producers but never signals or awaits the writer), so the control exercises the real
    ordering law rather than a stand-in."""
    import app.market_data.schwab.streaming.capture as m

    db = tmp_path / "cap.db"
    _reset_lifecycle()
    monkeypatch.setitem(__import__("sys").modules, "schwab.streaming",
                        __import__("types").SimpleNamespace(
                            StreamClient=_FailingInitialConnectStream))
    probe = _StartupProbe(monkeypatch)

    async def _shutdown_without_writer_retirement(pump_task, writer_task, stop, wsub,
                                                  extra_producers=()):
        await m._cancel_and_await((pump_task, *extra_producers), what="mutation control")
        # deliberately NOT: stop.set(); await writer_task

    monkeypatch.setattr(m, "_shutdown_sequence", _shutdown_without_writer_retirement)

    out = asyncio.run(_run_streaming_expecting_failure(m, db, probe))

    assert probe.entered, "the writer task must have started for this control to mean anything"
    assert probe.at_return["done"] is False, (
        "MUTATION CONTROL FAILED TO BITE: with writer retirement bypassed the writer task "
        f"must still be running when _run_streaming returns; snapshot={probe.at_return}")
    assert out.survivors, (
        "MUTATION CONTROL FAILED TO BITE: the orphaned writer task must show up as a "
        "surviving daemon task")
    assert any(done is not True for done, _c in probe.close_calls), (
        "MUTATION CONTROL FAILED TO BITE: writer.close() must have run while the writer "
        f"task was not yet terminal; observed {probe.close_calls}")
    with pytest.raises(AssertionError):
        probe.assert_writer_retired()
    with pytest.raises(AssertionError):
        probe.assert_close_ordering()


class _LoginRejectedStream(_LifecycleStream):
    """Models installed schwab-py 1.5.1: login() establishes the websocket in
    _init_from_preferences() and only THEN sends ADMIN/LOGIN and awaits the reply, which
    raises on a rejected login — leaving the socket it just opened wide open."""

    async def login(self):
        _LifecycleStream.logins += 1          # the transport was acquired
        self._log("login_attempt")
        raise RuntimeError("UnexpectedResponseCode: LOGIN error 3 'token invalid'")


def test_login_failure_after_transport_acquisition_retires_the_transport(monkeypatch):
    """A login that acquires a transport and THEN raises must not escape retirement.

    _schwab_connect's ownership boundary used to open after `await stream.login()`, so
    this exact failure — the realistic one for an expired or rejected token — left an open
    websocket that nothing referenced, logged out, or closed. Measured at that shape:
    1 socket opened, 0 closed, while the identical failure one step later was retired
    cleanly. Every watchdog retry during a token outage repeated it.

    Distinct from test_d3c_a_partial_connect_failure_after_login_retires_the_session:
    that one covers failures AFTER login succeeds. This covers the login call itself, and
    only this one fails if the boundary is moved back below login()."""
    import app.market_data.schwab.streaming.capture as m

    _reset_lifecycle()
    monkeypatch.setitem(__import__("sys").modules, "schwab.streaming",
                        __import__("types").SimpleNamespace(StreamClient=_LoginRejectedStream))

    async def go():
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        with pytest.raises(RuntimeError) as exc:
            await m._schwab_connect(SimpleNamespace(client=object()), ["SPY"],
                                    bus, health, stats, stop)
        return exc.value

    raised = asyncio.run(go())

    assert "LOGIN error 3" in str(raised), (
        f"the original login error must be preserved, not masked by cleanup: {raised}")
    assert len(_LifecycleStream.generations) == 1
    assert _LifecycleStream.generations[0]._socket.closed is True, (
        "the transport acquired by the failed login must be closed by the canonical "
        "retirement path")


def test_login_failure_retries_cannot_accumulate_live_sessions(monkeypatch):
    """Ownership must hold across REPEATED failures: the watchdog retries a rejected login
    on its cooldown, and each attempt acquires its own transport. None may accumulate."""
    import app.market_data.schwab.streaming.capture as m

    _reset_lifecycle()
    monkeypatch.setitem(__import__("sys").modules, "schwab.streaming",
                        __import__("types").SimpleNamespace(StreamClient=_LoginRejectedStream))

    async def go():
        bus, health, stats, stop = MessageBus(), HealthRegistry(), CaptureStats(), asyncio.Event()
        for _ in range(4):
            with pytest.raises(RuntimeError):
                await m._schwab_connect(SimpleNamespace(client=object()), ["SPY"],
                                        bus, health, stats, stop)

    asyncio.run(go())

    assert len(_LifecycleStream.generations) == 4, "four attempts, four transports"
    unclosed = [g.gen for g in _LifecycleStream.generations if not g._socket.closed]
    assert unclosed == [], f"failed-login retries leaked transports: {unclosed}"
    assert _LifecycleStream.live == 0, "no attempt may leave a live session behind"


# ─────────────────────────────────────────────────────────────────────────────
# PR214 FORCED-SURRENDER CLAIM BARRIER — a CONTROLLED surrender (watchdog recycle,
# clean shutdown) picks its own moment, so when the claim retraction cannot be
# written it can WAIT behind the claim's own lease instead of tearing down while a
# positive claim is still able to confirm the contract.
# ─────────────────────────────────────────────────────────────────────────────


def _claim_barrier_env(tmp_path, monkeypatch, ttl=1.5):
    """A live producer holding A on both option services, with a SHORT shared lease.

    Both sides read one constant in production, so the test shrinks both together —
    shrinking only one would measure a mismatch that cannot occur."""
    import app.options.order_flow.streaming as ofs
    import app.market_data.schwab.streaming.capture as d
    from stream_spine import CaptureWriter, CoverageWriteError

    monkeypatch.setattr(d, "PRODUCER_CLAIM_TTL_SEC", ttl)
    monkeypatch.setattr(ofs, "STREAM_PRODUCER_HEARTBEAT_STALE_SEC", ttl)
    monkeypatch.setattr(d, "CLAIM_BARRIER_RETRY_SEC", 0.05)

    db = tmp_path / "barrier.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    epoch_state = {"l1": None, "book": None}
    for key, service in d.COVERAGE_CLAIM_SERVICES.items():
        d._open_coverage_epoch_tracked(w, epoch_state, key,
                                       ofs.ticker_storage_key(_A_CONTRACT), service,
                                       reason="active_contract_set")
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _reset_option_plane_for_barrier(ofs)

    def unwritable():
        def _boom(*a, **k):
            raise CoverageWriteError("sqlite unwritable")
        monkeypatch.setattr(w, "close_coverage_epoch", _boom)
        monkeypatch.setattr(w, "write_heartbeat", _boom)

    return SimpleNamespace(db=db, w=w, epoch_state=epoch_state, ofs=ofs, d=d,
                           ttl=ttl, unwritable=unwritable, CoverageWriteError=CoverageWriteError)


def _reset_option_plane_for_barrier(ofs):
    ofs._feed_running = True
    ofs._active_option_contract = ofs.ticker_storage_key(_A_CONTRACT)
    ofs._option_streaming_last_update_ts = time.time()
    ofs._option_last_subscribe_completed_ts = time.time()


def _confirms(env):
    return env.ofs.get_option_contract_streaming_diagnostics(
        for_contract=_A_CONTRACT)["contract_match"] is True


def test_forced_surrender_waits_out_a_claim_it_cannot_retract(tmp_path, monkeypatch):
    """A controlled surrender must never happen while a standing positive claim can still
    confirm the coverage it is giving up.

    MEASURED before the barrier: the recycle tore the stream down with the retraction
    unwritten, and the consumer reported contract_match=true for the surrendered contract
    until the claim aged out — a false positive for the whole remaining lease.

    The consumer is sampled CONTINUOUSLY across the entire surrender, so the assertion is
    "no instant", not "not at the end"."""
    env = _claim_barrier_env(tmp_path, monkeypatch)
    try:
        assert _confirms(env), "precondition: the live claim confirms while genuinely held"
        env.unwritable()

        held = {"vendor": True}
        violations = []
        samples = {"n": 0}

        async def sampler(stop):
            while not stop.is_set():
                samples["n"] += 1
                if _confirms(env) and not held["vendor"]:
                    violations.append(time.monotonic())
                await asyncio.sleep(0.02)

        async def go():
            stop = asyncio.Event()
            s = asyncio.create_task(sampler(stop))
            try:
                waited = await env.d._surrender_claim_or_wait_out_lease(
                    env.w, reason="stream_recycle")
                held["vendor"] = False          # the surrender happens HERE
                for key in ("l1", "book"):
                    env.d._close_coverage_epoch_tracked(
                        env.w, env.epoch_state, key, reason="stream_recycle",
                        surrendered_ts=200.0)
                await asyncio.sleep(0.2)        # keep sampling past the surrender
                return waited
            finally:
                stop.set()
                await s

        waited = asyncio.run(go())

        assert waited >= env.ttl * 0.8, (
            f"the barrier must have held for roughly the standing lease; waited {waited}")
        assert samples["n"] > 10, "the sampler must actually have run across the barrier"
        assert violations == [], (
            f"{len(violations)} instant(s) where the surrendered contract was still "
            f"producer-confirmed")
        assert not _confirms(env), (
            "after a controlled surrender nothing may confirm the contract")
    finally:
        env.w.close()


def test_forced_surrender_is_immediate_when_the_retraction_lands(tmp_path, monkeypatch):
    """The barrier is exceptional, not the normal cost. With writes working, a controlled
    surrender must retract and proceed with NO added latency — otherwise every recycle and
    every clean exit would pay the lease."""
    env = _claim_barrier_env(tmp_path, monkeypatch)
    try:
        waited = asyncio.run(
            env.d._surrender_claim_or_wait_out_lease(env.w, reason="shutdown"))
        assert waited == 0.0, f"no wait may be imposed on the healthy path; got {waited}"
        assert not _confirms(env), "the retraction must have landed"
    finally:
        env.w.close()


def test_forced_surrender_barrier_releases_early_when_writes_recover(tmp_path, monkeypatch):
    """The barrier is a bound, not a fixed delay: the moment the retraction can actually
    be written it must publish and release, rather than sitting out the full lease."""
    env = _claim_barrier_env(tmp_path, monkeypatch, ttl=6.0)
    try:
        real_hb = CaptureWriter.write_heartbeat
        state = {"broken": True}

        def flaky(self, **kw):
            if state["broken"]:
                raise env.CoverageWriteError("sqlite unwritable")
            return real_hb(self, **kw)
        monkeypatch.setattr(CaptureWriter, "write_heartbeat", flaky)

        async def go():
            async def heal():
                await asyncio.sleep(0.4)
                state["broken"] = False
            h = asyncio.create_task(heal())
            waited = await env.d._surrender_claim_or_wait_out_lease(
                env.w, reason="stream_recycle")
            await h
            return waited

        waited = asyncio.run(go())
        assert 0.0 < waited < env.ttl * 0.6, (
            f"the barrier must release as soon as the retraction lands, well inside the "
            f"{env.ttl}s lease; waited {waited}")
        assert not _confirms(env), "the retraction must have been published on release"
    finally:
        env.w.close()


def _barrier_boundary_case(tmp_path, monkeypatch, *, path, ttl=1.5):
    """Drive the REAL _run_streaming through a CONTROLLED surrender whose claim retraction
    is unwritable, so the lease barrier engages, and report where the recorded coverage
    boundary sits relative to the ACTUAL surrender.

    Only write_heartbeat is broken. close_coverage_epoch keeps working, which is what
    isolates the timestamp: the epoch really does close, so ended_ts is a recorded value
    rather than a deferred one, and it can be compared against the moment the subscription
    was actually given up.

    `path` is "recycle" or "shutdown"; returns (ended_ts, actual_surrender_ts, waited)."""
    import app.options.order_flow.streaming as ofs
    import app.market_data.schwab.streaming.capture as m
    from stream_spine import CoverageWriteError

    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(m, "PRODUCER_CLAIM_TTL_SEC", ttl)
    monkeypatch.setattr(ofs, "STREAM_PRODUCER_HEARTBEAT_STALE_SEC", ttl)
    monkeypatch.setattr(m, "CLAIM_BARRIER_RETRY_SEC", 0.05)
    write_active_option_contract_signal(_A_CONTRACT)

    gate = asyncio.Event()
    monkeypatch.setattr(m, "stream_needs_recycle", _one_shot_recycle(gate))

    marks = {}
    real_retire = m._retire_stream_generation
    real_shutdown = m._shutdown_sequence

    async def timed_retire(*a, **k):
        marks.setdefault("surrender_ts", time.time())    # the subscription dies HERE
        return await real_retire(*a, **k)

    async def timed_shutdown(*a, **k):
        marks.setdefault("surrender_ts", time.time())
        return await real_shutdown(*a, **k)
    monkeypatch.setattr(m, "_retire_stream_generation", timed_retire)
    monkeypatch.setattr(m, "_shutdown_sequence", timed_shutdown)

    real_barrier = m._surrender_claim_or_wait_out_lease

    async def timed_barrier(writer, *, reason):
        marks.setdefault("barrier_start", time.time())
        waited = await real_barrier(writer, reason=reason)
        # setdefault: a recycle run also passes through the LATER shutdown barrier, and
        # that second pass must not overwrite the surrender under test.
        marks.setdefault("waited", waited)
        return waited
    monkeypatch.setattr(m, "_surrender_claim_or_wait_out_lease", timed_barrier)

    db = tmp_path / f"boundary_{path}.db"

    async def driver(stop, writer):
        # let the daemon genuinely subscribe and publish a POSITIVE claim first
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs"
                        for e in _LifecycleStream.events),
            what="the contract to be subscribed")
        await asyncio.sleep(0.1)
        assert writer.positive_claim_published_ts is not None, (
            "a positive claim must be standing before the barrier can mean anything")

        def _boom(*a, **k):
            raise CoverageWriteError("claim unwritable")
        monkeypatch.setattr(writer, "write_heartbeat", _boom)

        if path == "recycle":
            gate.set()
            await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                               what="the replacement generation")
            await asyncio.sleep(0.1)
        stop.set()

    asyncio.run(_drive_daemon(m, db, driver=driver))

    rows = _epoch_rows(db)
    closed = [r for r in rows if r[4] is not None]      # ordered by id
    assert closed, f"the surrender must have recorded a closed epoch; got {rows}"
    # Pair the FIRST closed epoch with the FIRST observed surrender: on a recycle run the
    # later shutdown closes generation 2's epochs too, and comparing those against
    # generation 1's teardown would measure nothing.
    return closed[0][4], marks.get("surrender_ts"), marks.get("waited", 0.0)


def test_barrier_boundary_recycle_records_the_post_barrier_surrender(tmp_path, monkeypatch):
    """Under the lease barrier, ended_ts must be the ACTUAL surrender boundary.

    The barrier deliberately KEEPS THE OLD SUBSCRIPTION ALIVE while it waits, so a
    timestamp captured before it is no longer the moment coverage ended — it precedes the
    real surrender by up to the whole lease. That is an UNDER-claim, and under-claiming is
    not automatically safe here: quotes really are still being captured during the wait,
    so those rows would fall outside every coverage epoch, and a gap inside that window
    would read as "not subscribed" when the daemon was in fact subscribed and the vendor
    silent — the exact confusion the ledger exists to prevent, in the other direction."""
    ended_ts, surrender_ts, waited = _barrier_boundary_case(
        tmp_path, monkeypatch, path="recycle", ttl=1.5)

    assert waited >= 1.5 * 0.6, f"the barrier must actually have engaged; waited {waited}"
    assert surrender_ts is not None, "the teardown must have been observed"
    skew = surrender_ts - ended_ts
    assert skew < 1.5 * 0.5, (
        f"ended_ts precedes the real surrender by {skew:.2f}s — it was captured before a "
        f"{waited:.2f}s barrier during which the subscription was still live and still "
        f"capturing")
    assert ended_ts <= surrender_ts + 0.5, (
        f"ended_ts ({ended_ts}) must not be stamped after the teardown began "
        f"({surrender_ts}) — that would over-claim across a window the socket was down")


def test_barrier_boundary_shutdown_records_the_post_barrier_surrender(tmp_path, monkeypatch):
    """Same boundary law on the clean-shutdown path."""
    ended_ts, surrender_ts, waited = _barrier_boundary_case(
        tmp_path, monkeypatch, path="shutdown", ttl=1.5)

    assert waited >= 1.5 * 0.6, f"the barrier must actually have engaged; waited {waited}"
    skew = surrender_ts - ended_ts
    assert skew < 1.5 * 0.5, (
        f"ended_ts precedes the real surrender by {skew:.2f}s across a {waited:.2f}s "
        f"barrier in which capture was still live")
    assert ended_ts <= surrender_ts + 0.5


def test_barrier_wait_is_not_counted_against_the_reconnect_cooldown(tmp_path, monkeypatch):
    """ADJUDICATION of `last_reconnect` under the lease barrier.

    RECONNECT_COOLDOWN_SEC exists to stop login-spam, and stream_needs_recycle measures it
    as `time.monotonic() - last_reconnect`. Time spent HELD AT THE BARRIER is not time
    spent connected — the daemon is deliberately waiting before it even tears down — so
    counting it shortens the next effective cooldown by up to a full lease, precisely
    while durable writes are failing and recycles are most likely to repeat.

    Measured through the real seam: the first cooldown reading after a barrier-delayed
    recycle must reflect the time since the RECONNECT, not since the recycle decision."""
    import app.options.order_flow.streaming as ofs
    import app.market_data.schwab.streaming.capture as m
    from stream_spine import CoverageWriteError

    ttl = 1.5
    _reset_lifecycle()
    _install_lifecycle_stream(monkeypatch)
    monkeypatch.setattr(m, "STATUS_LOOP_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(m, "PRODUCER_CLAIM_TTL_SEC", ttl)
    monkeypatch.setattr(ofs, "STREAM_PRODUCER_HEARTBEAT_STALE_SEC", ttl)
    monkeypatch.setattr(m, "CLAIM_BARRIER_RETRY_SEC", 0.05)
    write_active_option_contract_signal(_A_CONTRACT)

    gate = asyncio.Event()
    seen: list = []
    fired = {"x": False}

    def decide(age_sec, seen_data, since_last_reconnect, collect_session_live=True):
        seen.append((len(_LifecycleStream.generations), since_last_reconnect))
        if gate.is_set() and not fired["x"]:
            fired["x"] = True
            return True
        return False
    monkeypatch.setattr(m, "stream_needs_recycle", decide)

    async def driver(stop, writer):
        await _await_event(
            lambda: any(e[0] == "VENDOR level_one_option_subs"
                        for e in _LifecycleStream.events),
            what="the contract to be subscribed")
        await asyncio.sleep(0.1)

        def _boom(*a, **k):
            raise CoverageWriteError("claim unwritable")
        monkeypatch.setattr(writer, "write_heartbeat", _boom)
        gate.set()
        await _await_event(lambda: len(_LifecycleStream.generations) >= 2,
                           what="the replacement generation")
        await asyncio.sleep(0.15)     # let a few post-recycle ticks be sampled
        stop.set()

    asyncio.run(_drive_daemon(m, db=tmp_path / "cooldown.db", driver=driver))

    after = [s for gen, s in seen if gen >= 2]
    assert after, "the watchdog must have evaluated at least once after the reconnect"
    first = min(after)
    assert first < ttl * 0.5, (
        f"the first post-reconnect cooldown reading was {first:.2f}s, which includes the "
        f"~{ttl}s barrier wait — the cooldown would then expire that much early, allowing "
        f"a faster re-login exactly while writes are failing")


def test_forced_surrender_mutation_control_without_the_barrier(tmp_path, monkeypatch):
    """NEGATIVE CONTROL. Surrender WITHOUT waiting out the standing claim, and the false
    positive must reappear — otherwise the assertions above prove nothing."""
    env = _claim_barrier_env(tmp_path, monkeypatch)
    try:
        env.unwritable()
        # surrender immediately, skipping the barrier entirely
        for key in ("l1", "book"):
            env.d._close_coverage_epoch_tracked(env.w, env.epoch_state, key,
                                                reason="stream_recycle",
                                                surrendered_ts=200.0)
        assert env.epoch_state["l1"] is None, "the daemon has knowingly surrendered"
        assert _confirms(env), (
            "MUTATION CONTROL FAILED TO BITE: surrendering without the barrier must leave "
            "the standing claim still confirming the contract")
    finally:
        env.w.close()
