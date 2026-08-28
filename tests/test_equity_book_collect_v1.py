"""finding-#1 Section 1: the canonical Collect daemon OWNS equity book-depth and persists it
through the daemon's ONE CaptureWriter connection — never a second handle to stream_capture.db.

Every test CALLS the subject (handler / persister / schema / CaptureWriter) and asserts on the
result — a book collector proven by driving book frames, not by matching source text.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import equity_book_collect as ebc  # noqa: E402
from calibration.equity_book_frames import (  # noqa: E402
    frame_row_values,
    frame_symbol_rows,
)


def _real_book_frame() -> dict:
    """A real captured NASDAQ_BOOK frame if present (nested price levels + per-exchange depth), else
    a minimal frame with the identical shape."""
    p = (REPO / "reports" / "of_capability_probe" / "20260820T130550Z" / "frames"
         / "NASDAQ_BOOK_QQQ_0001_decoded.json")
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"service": "NASDAQ_BOOK", "timestamp": 1787231152513,
            "content": [{"key": "QQQ", "BOOK_TIME": 1787231152213,
                         "BIDS": [{"BID_PRICE": 712.46, "TOTAL_VOLUME": 40, "NUM_BIDS": 1,
                                   "BIDS": [{"EXCHANGE": "arcx", "BID_VOLUME": 40,
                                             "SEQUENCE": 32752150}]}],
                         "ASKS": []}]}


def test_row_shape_and_clock_contract():
    frame = _real_book_frame()
    vals = frame_row_values("NASDAQ_BOOK", frame, received_ts_ms=frame["timestamp"] + 250)
    assert vals is not None
    service, frame_ts, recv_ts, lag, n_syms, payload = vals
    assert service == "NASDAQ_BOOK"
    assert frame_ts == frame["timestamp"]        # vendor epoch-ms verbatim
    assert recv_ts == frame["timestamp"] + 250
    assert lag == 250                            # unit-correct ms lag, not a seconds/ms mix
    assert n_syms == len(frame["content"])
    back = json.loads(payload)                   # payload is the WHOLE nested frame, not a projection
    assert back["content"][0]["BIDS"][0]["BIDS"][0]["EXCHANGE"], "nested per-exchange depth was lost"


def test_malformed_frame_is_rejected_not_raised():
    assert frame_row_values("NASDAQ_BOOK", {"content": []}, 1) is None   # no timestamp
    assert frame_row_values("NOT_A_BOOK", {"timestamp": 1}, 1) is None   # unsupported service
    assert frame_row_values("NASDAQ_BOOK", "not a dict", 1) is None
    assert frame_symbol_rows(7, {"content": "nope"}) == []


def test_handler_publishes_raw_frame_to_the_bus_only():
    published: list = []

    class _Bus:
        def publish(self, topic, msg):
            published.append((topic, msg))

    frame = _real_book_frame()
    beats: list = []
    h = ebc.make_equity_book_frame_handler(_Bus(), "NASDAQ_BOOK", on_beat=beats.append)
    h(frame)

    assert beats == ["NASDAQ_BOOK"]
    assert len(published) == 1
    topic, msg = published[0]
    assert topic == "equitybook.QQQ"
    assert msg["service"] == "NASDAQ_BOOK"
    assert msg["frame"] is frame                 # the RAW frame — no reshaping on the receive loop
    assert isinstance(msg["received_ts_ms"], int)


def test_handler_never_raises_into_the_equity_loop():
    class _Raising:
        def publish(self, *_a):
            raise RuntimeError("bus down")

    ebc.make_equity_book_frame_handler(_Raising(), "NYSE_BOOK")(_real_book_frame())  # must not raise


def test_persister_writes_frame_plus_symbol_index():
    conn = sqlite3.connect(":memory:")
    try:
        persist = ebc.make_equity_book_topic_writer()
        frame = _real_book_frame()
        msg = {"service": "NASDAQ_BOOK", "frame": frame, "received_ts_ms": frame["timestamp"] + 100}
        assert persist(conn, "equitybook.QQQ", msg) == 1
        row = conn.execute("SELECT service, n_symbols FROM equity_book_frames").fetchone()
        assert row == ("NASDAQ_BOOK", len(frame["content"]))
        assert ("QQQ", 0) in conn.execute(
            "SELECT symbol_key, content_idx FROM equity_book_frame_symbols").fetchall()
        # a rejected frame writes nothing and never raises
        assert persist(conn, "equitybook.", {"service": "NASDAQ_BOOK", "frame": {},
                                              "received_ts_ms": 1}) == 0
    finally:
        conn.close()


def test_rides_the_single_capturewriter_no_second_connection(tmp_path):
    """The finding-#1 invariant: book frames persist through the daemon's ONE CaptureWriter
    connection via register_topic_writer('equitybook', ...) — not a second sqlite handle."""
    from stream_spine import CaptureWriter

    w = CaptureWriter(tmp_path / "stream_capture.db")
    try:
        w.register_topic_writer("equitybook", ebc.make_equity_book_topic_writer())
        frame = _real_book_frame()
        w.insert("equitybook.QQQ", {"service": "NASDAQ_BOOK", "frame": frame,
                                    "received_ts_ms": frame["timestamp"] + 10})
        assert w.rows_written == 1, "the single writer did not count the book row"
        got = w._conn.execute("SELECT COUNT(*) FROM equity_book_frames").fetchone()[0]
        assert got == 1, "the book row did not land on the writer's OWN connection"
    finally:
        w.close()


def test_capture_gate_defaults_off_and_reads_the_env(monkeypatch):
    monkeypatch.delenv(ebc.ED_EQUITY_BOOK_CAPTURE_ENV, raising=False)
    assert ebc.equity_book_capture_enabled() is False   # deploying this section is inert by default
    monkeypatch.setenv(ebc.ED_EQUITY_BOOK_CAPTURE_ENV, "1")
    assert ebc.equity_book_capture_enabled() is True
    monkeypatch.setenv(ebc.ED_EQUITY_BOOK_CAPTURE_ENV, "off")
    assert ebc.equity_book_capture_enabled() is False


def test_register_and_subscribe_use_the_two_book_vendor_methods():
    class _Client:
        def __init__(self):
            self.registered: list = []
            self.subscribed: dict = {}

        def add_nasdaq_book_handler(self, fn):
            self.registered.append(("NASDAQ_BOOK", fn))

        def add_nyse_book_handler(self, fn):
            self.registered.append(("NYSE_BOOK", fn))

        async def nasdaq_book_subs(self, syms):
            self.subscribed["NASDAQ_BOOK"] = list(syms)

        async def nyse_book_subs(self, syms):
            self.subscribed["NYSE_BOOK"] = list(syms)

    c = _Client()
    ebc.register_equity_book_handlers(c, bus=None)          # inert: registers, does not subscribe
    assert {s for s, _ in c.registered} == set(ebc.SERVICES)
    assert c.subscribed == {}, "registration must not subscribe"

    done = asyncio.run(ebc.subscribe_equity_books(c, ["SPY", "QQQ", "IWM"]))
    assert set(done) == set(ebc.SERVICES)
    assert c.subscribed == {"NASDAQ_BOOK": ["SPY", "QQQ", "IWM"],
                            "NYSE_BOOK": ["SPY", "QQQ", "IWM"]}


def test_equitybook_rows_do_not_contaminate_options_drop_accounting(tmp_path):
    """Cross-coupling defect 1: CaptureWriter.option_rows must count ONLY the option topic kinds,
    so equitybook persistence on the SAME single writer can never inflate options `written` (the
    authority for frames actually persisted) and mask a real option drop."""
    from stream_spine import CaptureWriter

    def _opt_writer(conn, _topic, _msg):   # a trivial options persister: 1 row per frame
        conn.execute("CREATE TABLE IF NOT EXISTS _opt(x)")
        conn.execute("INSERT INTO _opt VALUES (1)")
        return 1

    w = CaptureWriter(tmp_path / "stream_capture.db")
    try:
        w.register_topic_writer("optionchain", _opt_writer)
        w.register_topic_writer("optionbook", _opt_writer)
        w.register_topic_writer("equitybook", ebc.make_equity_book_topic_writer())

        w.insert("optionchain.SPY", {"any": 1})
        w.insert("optionchain.QQQ", {"any": 1})
        w.insert("optionbook.SPY", {"any": 1})            # 3 option rows
        frame = _real_book_frame()
        for _ in range(5):                                # 5 equitybook rows on the SAME writer
            w.insert("equitybook.QQQ", {"service": "NASDAQ_BOOK", "frame": frame,
                                        "received_ts_ms": frame["timestamp"] + 1})

        assert w.option_rows == 3, "options `written` was inflated by equitybook rows"
        assert w.topic_rows.get("equitybook") == 5, "equitybook rows are counted in their own bucket"
        assert w.rows_written == 8, "the total is options + equitybook, kept separate"
    finally:
        w.close()


def test_option_budget_reflects_the_book_enabled_stream_load(monkeypatch):
    """Cross-coupling defect 2: the options key budget must size against the equity services the ONE
    stream ACTUALLY holds — 4 with equity book-depth on (L1 + chart + NASDAQ_BOOK + NYSE_BOOK), 2 off
    — or options could over-subscribe past the shared per-account streamer key limit."""
    import sys as _sys
    _sys.path.insert(0, str(REPO / "tools"))
    from run_stream_capture import equity_services_for_budget
    from options_stream_subscription import contract_budget_from_key_limit

    assert equity_services_for_budget(False) == 2
    assert equity_services_for_budget(True) == 4

    # composes with the default-off gate: env on -> 4 services budgeted; unset -> 2
    monkeypatch.setenv(ebc.ED_EQUITY_BOOK_CAPTURE_ENV, "1")
    assert equity_services_for_budget(ebc.equity_book_capture_enabled()) == 4
    monkeypatch.delenv(ebc.ED_EQUITY_BOOK_CAPTURE_ENV, raising=False)
    assert equity_services_for_budget(ebc.equity_book_capture_enabled()) == 2

    # and the budget HONORS the count: books on reserves DOUBLE the equity keys, leaving strictly
    # fewer option contracts — the actual mechanism that stops over-subscription.
    n = 3
    off = contract_budget_from_key_limit(equity_symbols=n,
                                         equity_key_services=equity_services_for_budget(False))
    on = contract_budget_from_key_limit(equity_symbols=n,
                                        equity_key_services=equity_services_for_budget(True))
    assert off["equity_keys_held"] == n * 2
    assert on["equity_keys_held"] == n * 4
    assert on["contracts_allowed"] < off["contracts_allowed"], (
        "book keys did not shrink the option contract budget")
