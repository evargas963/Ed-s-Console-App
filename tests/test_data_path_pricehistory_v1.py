"""Schwab's price history, Schwab to the console's memory, through the real code: the daemon's
chain sweep asks /pricehistory for each ticker (tests/schwab_rest_standin.py, on the real schwab-py
client as the daemon builds it) as docs/schwab lists it -- 1-minute bars once per ET date, 15-minute
and daily candles in every rotation, each request ending at the sweep's clock -- and publishes each
series as Schwab sent it; the daemon's push forwards it (live_push) and the console's bar writer
takes it: the 1-minute bars every reader reads, and the daily and 15-minute candles the ATR is
computed from.

Real data: SPY's and TSLA's /pricehistory answers of 2026-10-07 09:57 UTC
(tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json). Inputs, named: the clock.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

import server
from app.market_data.schwab.streaming import capture, live_push
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import PRICE_HISTORY, ChainSweep
from stream_spine import LATEST, CaptureWriter, HealthRegistry, MessageBus
from tests.schwab_rest_standin import HISTORY, PRICEHISTORY, LocalSchwab
from time_et import ET

_SERIES = {"1m": ("minute", "1"), "15m": ("minute", "15"), "1d": ("daily", "1")}


def _et(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _sweep(tmp_path, clock, publish):
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), board=["SPY"])
    return ChainSweep(tmp_path / "ed_console.db", ["SPY"], publish, clock=lambda: clock["now"],
                      failures=CaptureWriter(tmp_path / "stream_capture.db"), streamed=daemon.option_record)


def test_the_daemon_asks_each_series_as_schwab_documents_it_and_publishes_it_as_sent(tmp_path):
    schwab = LocalSchwab()
    published: list = []
    clock = {"now": _et("2026-08-28 09:05")}
    sweep = _sweep(tmp_path, clock, lambda topic, msg: published.append((topic, msg)))
    client = schwab.client(tmp_path)
    try:
        sweep.rotation(lambda: client, ["SPY"], threading.Event())
        first = schwab.asked(PRICEHISTORY)
        clock["now"] += 600                                        # the next rotation, the same ET date
        sweep.rotation(lambda: client, ["SPY"], threading.Event())
        same_day = schwab.asked(PRICEHISTORY)[len(first):]
        clock["now"] = _et("2026-08-31 09:05")                     # the next market day
        sweep.rotation(lambda: client, ["SPY"], threading.Event())
        next_day = schwab.asked(PRICEHISTORY)[len(first) + len(same_day):]
    finally:
        schwab.close()

    assert [q["frequencyType"] + q["frequency"] for q in first] == ["minute1", "minute15", "daily1"]
    for q, (series, (period_type, period, frequency_type, frequency)) in zip(first, PRICE_HISTORY.items()):
        assert (q["symbol"], q["periodType"], q["period"], q["frequencyType"], q["frequency"]) == (
            "SPY", period_type, str(period), frequency_type, str(frequency)), series
        assert q["endDate"] == str(int(_et("2026-08-28 09:05") * 1000)), "each request ends at the clock"
        assert q["needExtendedHoursData"] == "true"
    assert [q["frequencyType"] + q["frequency"] for q in same_day] == ["minute15", "daily1"], \
        "the 1-minute bars once per ET date"
    assert [q["frequencyType"] + q["frequency"] for q in next_day] == ["minute1", "minute15", "daily1"]

    history = [(topic, msg) for topic, msg in published if topic.startswith("pricehistory.")]
    for series in ("1m", "15m", "1d"):
        topic, msg = next((t, m) for t, m in history if t == f"pricehistory.SPY.{series}")
        sent = HISTORY[("SPY", *_SERIES[series])]["body"]["candles"]
        assert msg["candles"] == sent and msg["src"] == "schwab_pricehistory", series
        assert json.loads(msg["frame"]) == {"topic": topic, "msg": {k: v for k, v in msg.items() if k != "frame"}}


def _true_range_mean(candles: list[dict]) -> float:
    """ATR(14) worked out here from Schwab's candles: the mean of the last 14 true ranges."""
    tr = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
          for p, c in zip(candles, candles[1:])]
    return sum(tr[-14:]) / 14


def test_the_console_takes_schwabs_bars_and_candles_from_the_push_and_computes_the_atr_from_them():
    """Each series published on the daemon's bus, forwarded by its push (live_push: the frame the
    console receives) and taken by the console (streaming._ingest_pushed -> the bar writer): the
    1-minute bars every reader reads are Schwab's candles, each field as sent; the daily and
    15-minute ATR are those of Schwab's daily and 15-minute candles."""
    from calibration.complete_chain_capture import price_history_message
    bus = MessageBus()
    sub = bus.subscribe("pricehistory.", policy=LATEST)
    for tk in ("SPY", "TSLA"):
        for series, key in _SERIES.items():
            a = HISTORY[(tk, *key)]
            bus.publish(*price_history_message(tk, series, a["body"]["candles"], a["answered_utc"]))
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get_nowait()
    for tk in ("SPY", "TSLA"):
        server._bars.pop(tk, None)
        for held in server._candles.values():
            held.pop(tk, None)
    try:
        assert len(sub.changed) == 6, "each ticker's three series, its current record on the bus"
        for key in list(sub.changed):
            topic, record = bus.current[key]
            assert live_push.is_forwarded(topic, record)
            (frame,) = live_push.frames(topic, record)
            wire = json.loads(frame)
            ofs._ingest_pushed(wire["topic"], wire["msg"])               # as the console receives it
        msgs = []
        while not ofs.streamed_bars.empty():
            msgs.append(ofs.streamed_bars.get_nowait())
        assert len(msgs) == 6
        server._write_streamed_bars(msgs, datetime.fromtimestamp(HISTORY[("SPY", "minute", "1")]["answered_utc"], ET))
        for tk in ("SPY", "TSLA"):
            minutes = HISTORY[(tk, "minute", "1")]["body"]["candles"]
            got = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in server._bars_1m(tk, server.BARS_KEPT)]
            assert got == [(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
                           for c in minutes], tk
            atr = server._atr_pair(tk)
            assert atr.daily == _true_range_mean(HISTORY[(tk, "daily", "1")]["body"]["candles"]), tk
            assert atr.m15 == _true_range_mean(HISTORY[(tk, "minute", "15")]["body"]["candles"]), tk
            assert (atr.daily_reason, atr.m15_reason) == (None, None), tk
    finally:
        for tk in ("SPY", "TSLA"):
            server._bars.pop(tk, None)
            for held in server._candles.values():
                held.pop(tk, None)


def test_before_schwab_sends_the_candles_the_atr_is_absent_with_why():
    tk = "ZZNOCANDLES"
    atr = server._atr_pair(tk)
    assert (atr.daily, atr.m15) == (None, None)
    assert (atr.daily_reason, atr.m15_reason) == (
        "0 trading days of Schwab's daily candles; ATR(14) needs 15",
        "0 15-minute periods of Schwab's 15-minute candles; ATR(14) needs 15")
