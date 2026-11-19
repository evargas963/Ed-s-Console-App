"""Bars come from Schwab: its 1-minute price history and its streamed CHART_EQUITY 1-minute bars.

The price history is /pricehistory, which the capture daemon asks for each ET date; the streamed
bars the daemon records (stream_capture.db stream_bars_raw) and forwards. The console keeps them
in memory (state.bar_store: the history, each pushed bar on top); every live reader reads memory.
Only completed bars are served. A minute Schwab sent neither way stays missing.

Real data: SPY's CHART_EQUITY bars as the daemon received them on 2026-10-01, from 06:00 CT
(tests/fixtures/real_daemon_bars_spy_tsla_2026_10_01_02.json), each under the stand-in ticker
ZZBARS so no other test's SPY is touched. INDUCED CONDITIONS, each named where it is set: a field
missing, not a number, or a reported 0.
"""

from __future__ import annotations

import threading
from datetime import datetime

import pytest

import app.options.order_flow.streaming as ofs
import server
import time_et
from app.market_data.schwab.streaming.live_push import is_forwarded
from push import bars as push_bars
from state import bar_store
from tests.feed_live_helper import daemon_bars, newest_bars, price_history
from time_et import ET, ct_label

TK = "ZZBARS"
_SPY = newest_bars(daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY"), "SPY")
#: the first minute: 06:00 CT on 2026-10-01; the next minutes follow it, each Schwab's
T0 = _SPY[0]["bar_start_ms"] / 1000


def _bar(start: float, **induced) -> dict:
    """SPY's bar for the minute at `start` as the daemon received it, under TK; `induced` set."""
    sent = next(b for b in _SPY if b["bar_start_ms"] == int(start * 1000))
    return {**sent, "symbol": TK, **induced}


def _clear():
    bar_store._bars.pop(TK, None)


def setup_function(_fn):
    _clear()


def teardown_function(_fn):
    _clear()


def test_the_daemon_forwards_streamed_bars_to_the_console():
    assert is_forwarded(f"bar1m.{TK}", _bar(T0))
    assert not is_forwarded(f"bar1m.{TK}", dict(_bar(T0), src="something_else"))


def test_the_feed_hands_each_streamed_bar_to_the_writer():
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get_nowait()
    ofs._ingest_pushed(f"bar1m.{TK}", _bar(T0))
    assert ofs.streamed_bars.get_nowait()["bar_start_ms"] == int(T0 * 1000)


def test_a_streamed_bar_is_written_and_read_back_exactly():
    assert server._write_streamed_bar(_bar(T0))
    (b,) = bar_store.bars_1m(TK)
    # Schwab's 06:00 CT bar: 765.635 / 765.71 / 765.44 / 765.45, 4,629 shares
    assert (b.ts, b.open, b.high, b.low, b.close, b.volume) == (
        T0,
        765.635,
        765.71,
        765.44,
        765.45,
        4629,
    )


def test_a_bar_missing_a_field_is_not_written():
    assert not server._write_streamed_bar(_bar(T0, close=None))  # INDUCED: no close sent
    assert bar_store.bars_1m(TK) == []


def test_a_bar_without_its_volume_is_written_with_its_volume_absent():
    """A missing volume is absent, never 0; the price levels take the bar as written."""
    assert server._write_streamed_bar(_bar(T0, volume=None))  # INDUCED: no volume sent
    (b,) = bar_store.bars_1m(TK)
    assert b.volume is None and (b.open, b.close) == (765.635, 765.45)


def test_a_price_that_is_not_a_number_is_not_written():
    """AGENTS.md rule 2: -999, text, NaN and infinity are not numbers."""
    for bad in (-999, "765.44", float("nan"), float("inf")):  # INDUCED: each as the low
        assert not server._write_streamed_bar(_bar(T0, low=bad)), bad
    assert bar_store.bars_1m(TK) == []


def test_a_reported_zero_is_written_as_sent():
    """Operator ruling 2026-09-27: take what Schwab sends; a 0 price or volume is 0."""
    assert server._write_streamed_bar(_bar(T0, low=0.0, volume=0.0))  # INDUCED: 0 reported
    (b,) = bar_store.bars_1m(TK)
    assert (b.low, b.volume) == (0.0, 0.0)


def test_a_minute_the_stream_did_not_deliver_stays_missing():
    for m in (0, 1, 3):  # minute 2 never arrived
        server._write_streamed_bar(_bar(T0 + 60 * m))
    assert [b.ts for b in bar_store.bars_1m(TK)] == [T0, T0 + 60, T0 + 180]


@pytest.mark.alone
def test_the_price_history_is_taken_promptly_and_exactly_while_options_are_priced_alongside():
    """The console prices option chains in the interpreter that takes and serves the bars.

    Schwab's SPY and TSLA 1-minute price history as /pricehistory answered it at 2026-10-07
    09:57 UTC (10 days, extended hours: ~11,000 candles each), taken by the bar writer
    (server._write_streamed_bars, as the daemon pushes it): each minute is Schwab's candle with
    every field as sent, the pre-market and after-hours minutes included. Prompt by two measures
    no other program on the machine can move: the writer's own work (its thread's CPU time)
    under a second in every write, and beside a busy pure-Python thread at most 4 times its time
    alone (a writer that waits on the other thread, as one that hashed its whole input piecemeal
    did 27 s, fails it; sharing the interpreter fairly is about 2 times). Five writes alone and
    five beside the thread, taken in turn, each compared at its fastest: another program only
    ever lengthens a write, so the fastest is the one it left alone (Python's `timeit` docs).
    """
    answers = {tk: price_history(tk, "1m") for tk in ("SPY", "TSLA")}

    def take() -> tuple[float, float, dict]:
        """(seconds taken, seconds of the writer's own CPU, the bars read) of one write."""
        for tk in answers:
            bar_store._bars.pop(tk, None)
        t0, w0 = time_et.elapsed(), time_et.worked()
        server._write_streamed_bars(
            [
                {
                    "src": "schwab_pricehistory",
                    "symbol": tk,
                    "series": "1m",
                    "ts_recv": a["answered_utc"],
                    "answer": a["body"],
                }
                for tk, a in answers.items()
            ],
            datetime.fromtimestamp(answers["SPY"]["answered_utc"], ET),
        )
        read = {tk: bar_store.bars_1m(tk, bar_store.BARS_KEPT) for tk in answers}
        return time_et.elapsed() - t0, time_et.worked() - w0, read

    def beside_busy() -> tuple[float, float, dict]:
        busy = threading.Event()

        def price_options():
            x = 0
            while not busy.is_set():
                for i in range(1000):
                    x += i * i

        t = threading.Thread(target=price_options, daemon=True)
        t.start()
        try:
            return take()
        finally:
            busy.set()
            t.join()

    try:
        pairs = [(take(), beside_busy()) for _ in range(5)]
    finally:
        for tk in answers:
            bar_store._bars.pop(tk, None)
    samples = [s for pair in pairs for s in pair]
    for _took, _work, read in samples:
        for tk, a in answers.items():
            got = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in read[tk]]
            want = [
                (c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
                for c in a["body"]["candles"]
            ]
            assert got == want, tk
            assert any(datetime.fromtimestamp(ts, ET).hour < 9 for ts, *_ in got), (
                f"{tk}: no pre-market minute kept"
            )
            assert any(datetime.fromtimestamp(ts, ET).hour >= 17 for ts, *_ in got), (
                f"{tk}: no after-hours minute kept"
            )
    candles = sum(len(v) for v in samples[0][2].values())
    work = max(w for _t, w, _r in samples)
    assert work < 1.0, f"{candles} candles cost the writer {work:.2f} s of its own CPU"
    # each time at its fastest, the others lengthened by whatever else the machine ran then
    alone = min(a[0] for a, _b in pairs)
    took = min(b[0] for _a, b in pairs)
    assert took < 4 * alone, (
        f"{candles} candles took {took:.2f} s beside a busy thread, {alone:.2f} s alone"
    )


def test_the_bars_endpoint_serves_completed_schwab_bars_and_the_last_bars_minute():
    for m in (0, 1):
        server._write_streamed_bar(_bar(T0 + 60 * m))
    body = push_bars.bars(TK, T0 + 120.0, {"tf": "1", "limit": 1500})
    assert [b["t"] for b in body["bars"]] == [T0, T0 + 60]
    # each bar's start as the chart's readout shows it, served
    assert [b["time_ct"] for b in body["bars"]] == [
        "Thu 10/01 06:00 AM CT",
        "Thu 10/01 06:01 AM CT",
    ]
    # and as the chart's time axis marks it: year, month, day, time of day (Central Time)
    assert [b["ticks"] for b in body["bars"]] == [
        ["2026", "Oct", "Oct 1", "06:00"],
        ["2026", "Oct", "Oct 1", "06:01"],
    ]
    assert not any("forming" in b for b in body["bars"])
    assert body["last_bar"] == {"t": T0 + 60, "label": ct_label(T0 + 60)}
