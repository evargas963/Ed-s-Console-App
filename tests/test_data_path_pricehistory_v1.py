"""Schwab's price history, Schwab to the console's memory, through the real code.

The daemon's chain sweep asks /pricehistory for each ticker (tests/schwab_rest_standin.py, on the
real schwab-py client as the daemon builds it) as docs/schwab lists it -- 1-minute bars and two
years of daily, weekly and monthly candles, once per ET date, each request ending at the sweep's
clock -- and publishes each series as Schwab sent it on the daemon's bus; the console reads it
there and its bar writer takes it: the 1-minute bars every reader reads, and the daily, weekly
and monthly candles the ATR of each is computed from, today's daily candle the one Schwab pushes
on the stream.

Real data: SPY's and TSLA's /pricehistory answers of 2026-10-07 09:57 UTC
(tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json), SPY's, AMD's and TSLA's weekly and
monthly answers of 2026-11-12 (tests/fixtures/real_pricehistory_weekly_monthly_2026_11_12.json),
and SPY's pushed day fields and
daily candles of 2026-11-10 (tests/fixtures/real_spy_day_fields_and_daily_candles_2026_11_10.json).
Inputs, named: the clock.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from functools import partial
from pathlib import Path

import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import capture, live_push
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import PRICE_HISTORY, ChainSweep, price_history_message
from stream_spine import LATEST, LOG, CaptureWriter, HealthRegistry, MessageBus
from tests.page_on_socket import pages
from tests.schwab_rest_standin import HISTORY, PRICEHISTORY, LocalSchwab
from tests.shared_helpers import et_ts
from time_et import ET

_SERIES = {s: (kind, str(n)) for s, (_, _, kind, n) in PRICE_HISTORY.items()}


def _sweep(tmp_path, clock, publish):
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    return ChainSweep(
        tmp_path / "ed_console.db",
        ["SPY"],
        publish,
        clock=lambda: clock["now"],
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed=daemon.option_record,
    )


def test_the_daemon_asks_each_series_as_schwab_documents_it_and_publishes_it_as_sent(tmp_path):
    schwab = LocalSchwab()
    published: list = []
    clock = {"now": et_ts("2026-10-01 09:05")}  # Thursday, in the pre-market Schwab sent
    sweep = _sweep(tmp_path, clock, lambda topic, msg: published.append((topic, msg)))
    client = schwab.client(tmp_path)

    def due(at: str) -> list[str]:
        return sweep.candles_due("SPY", datetime.fromtimestamp(et_ts(at), ET))

    def ask(at: str) -> list[str]:
        before = len(schwab.asked(PRICEHISTORY))
        clock["now"] = et_ts(at)
        sweep.candles(lambda: client, {"SPY": due(at)}, threading.Event())
        return [q["frequencyType"] + q["frequency"] for q in schwab.asked(PRICEHISTORY)[before:]]

    try:
        assert due("2026-10-01 09:05") == list(PRICE_HISTORY), "never asked: every series"
        ask("2026-10-01 09:05")
        first = schwab.asked(PRICEHISTORY)
        later_today = [
            due(at)
            for at in (
                "2026-10-01 09:05:02",
                "2026-10-01 09:10",
                "2026-10-01 09:16",
                "2026-10-01 09:31",
                "2026-10-01 16:05",
            )
        ]
        after_close = ask("2026-10-01 16:05")
        session_end = ask("2026-10-01 20:01")
        closed = due("2026-10-01 20:31")
        next_day = ask("2026-10-02 06:00")  # before the pre-market: the minute series wait
    finally:
        schwab.close()

    assert [(q["periodType"], q["period"], q["frequencyType"], q["frequency"]) for q in first] == [
        ("day", "10", "minute", "1"),
        ("day", "10", "minute", "5"),
        ("day", "10", "minute", "15"),
        ("day", "10", "minute", "30"),
        ("year", "2", "daily", "1"),
        ("year", "2", "weekly", "1"),
        ("year", "2", "monthly", "1"),
    ]
    for q, (series, (period_type, period, frequency_type, frequency)) in zip(
        first, PRICE_HISTORY.items()
    ):
        assert (q["symbol"], q["periodType"], q["period"], q["frequencyType"], q["frequency"]) == (
            "SPY",
            period_type,
            str(period),
            frequency_type,
            str(frequency),
        ), series
        assert q["endDate"] == str(int(et_ts("2026-10-01 09:05") * 1000)), (
            "each request ends at the clock"
        )
        assert q["needExtendedHoursData"] == "true"
    assert later_today == [
        [],
        ["5m"],
        ["5m", "15m"],
        ["5m", "15m", "30m"],
        ["5m", "15m", "30m", "1d", "1w", "1mo"],
    ], "a minute series once a bar of its own completed; the candles again after the regular close"
    assert after_close == [
        "minute5",
        "minute15",
        "minute30",
        "daily1",
        "weekly1",
        "monthly1",
    ], "only the due series"
    assert session_end == ["minute5", "minute15", "minute30"], "the bars that end the session"
    assert closed == [], "closed then and now: nothing is asked"
    assert next_day == [
        "minute1",
        "daily1",
        "weekly1",
        "monthly1",
    ], "the next ET date, before any session opens"

    history = [(topic, msg) for topic, msg in published if topic.startswith("pricehistory.")]
    for series in PRICE_HISTORY:
        topic, msg = next((t, m) for t, m in history if t == f"pricehistory.SPY.{series}")
        sent = HISTORY[("SPY", *_SERIES[series])]["body"]
        assert msg["answer"] == sent and msg["src"] == "schwab_pricehistory", series
        assert msg == {  # the bus message is what the console receives: nothing else on it
            "src": "schwab_pricehistory",
            "symbol": "SPY",
            "series": series,
            "ts_recv": et_ts("2026-10-01 09:05"),
            "answer": sent,
        }, (topic, series)


def _wilder_atr(candles: list[dict]) -> float:
    """ATR(14) worked out here from Schwab's candles by Wilder's definition (Wilder 1978).

    The first ATR is the mean of the first 14 true ranges; each later one is
    (ATR_(t-1) * 13 + TR_t) / 14.
    """
    tr = [
        max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
        for p, c in zip(candles, candles[1:])
    ]
    atr = sum(tr[:14]) / 14
    for x in tr[14:]:
        atr = (atr * 13 + x) / 14
    return atr


#: Schwab's frequencyType of its weekly and of its monthly candles
_SENT = ("weekly", "monthly")


def _held(tk: str, series: str, now: datetime, candles: list | None = None) -> None:
    """Publish Schwab's captured `series` answer for `tk`, pushed and taken by the console.

    Its `candles` only, when given.
    """
    a = HISTORY[(tk, *_SERIES[series])]
    body = a["body"] if candles is None else dict(a["body"], candles=candles)
    topic, msg = price_history_message(tk, series, body, a["answered_utc"])
    assert live_push.is_forwarded(topic, msg)
    ofs._ingest_pushed(topic, msg)  # the bus message, as the console's _bus_loop hands it over
    server._write_streamed_bars([ofs.streamed_bars.get_nowait()], now)


def _told(tk: str, takes) -> list:
    """Return the panels the page showing every panel of `tk` is told changed after each take.

    `takes` are callables run in turn.
    """
    with pages() as served:
        page = served.open(tk, *server.PAGE_PANELS)
        told = []
        for take in takes:
            take()
            told.append(served.told(page, 0.5))
        return told


#: SPY on 2026-11-10 as production recorded it: each LEVELONE_EQUITIES message that moved the
#: day's open, high or low (the overnight reset to 0 first), the first and the newest that moved
#: only the regular session's last, and Schwab's /pricehistory daily answer after that close
_DAY = json.loads(
    (
        Path(__file__).parent / "fixtures" / "real_spy_day_fields_and_daily_candles_2026_11_10.json"
    ).read_text(encoding="utf-8")
)


def test_today_s_candle_is_the_one_schwab_pushes():
    """Today's daily candle is Schwab's pushed open, high, low and regular session's last.

    Before the regular session opens (Schwab holds 0 for the first three) and until its first
    trade there is none, and the ATR is Schwab's earlier candles'. After the close the pushed
    candle is the daily candle Schwab itself then sent for the day, so the ATR is that of
    Schwab's own series; the daily chart draws it until the series holds the day.
    """
    tk = "SPY"
    sent = _DAY["daily"]["candles"]
    before, schwabs = sent[:-1], sent[-1]
    opened = datetime(2026, 11, 10, 9, 30, tzinfo=ET)
    after = datetime(2026, 11, 10, 16, 30, tzinfo=ET)

    def pushed(until: datetime) -> None:
        for q in _DAY["quotes"]:
            if q["ts_recv"] <= until.timestamp():
                lmp.record_from_level_one_equity(tk, q["native"], received_ts=q["ts_recv"])

    def series(candles: list) -> None:
        topic, msg = price_history_message(
            tk, "1d", dict(_DAY["daily"], candles=candles), _DAY["daily_ts_recv"]
        )
        ofs._ingest_pushed(topic, msg)
        server._write_streamed_bars([ofs.streamed_bars.get_nowait()], after)

    server._series.pop((tk, "1d"), None)
    try:
        series(before)
        pushed(opened)  # the reset to 0 and the prior session's last: no regular trade yet
        early = datetime(2026, 11, 10, 8, 0, tzinfo=ET)
        assert server._todays_candles(tk, early) == [] == server._todays_candles(tk, opened)
        assert server._atr(tk, opened).daily == _wilder_atr(before)
        pushed(after)
        (today,) = server._todays_candles(tk, after)
        assert (today.open, today.high, today.low, today.close) == (
            schwabs["open"],
            schwabs["high"],
            schwabs["low"],
            schwabs["close"],
        )
        assert today.ts == opened.timestamp()
        assert server._atr(tk, after).daily == _wilder_atr(sent)
        drawn = server.chart_bars(tk, "D", [], after)[-1]
        assert (drawn["o"], drawn["h"], drawn["l"], drawn["c"]) == (
            today.open,
            today.high,
            today.low,
            today.close,
        )
        series(sent)
        assert server.chart_bars(tk, "D", [], after)[-1] == {
            "t": schwabs["datetime"] / 1000,
            "o": schwabs["open"],
            "h": schwabs["high"],
            "l": schwabs["low"],
            "c": schwabs["close"],
            "v": schwabs["volume"],
        }
    finally:
        server._series.pop((tk, "1d"), None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)


def test_the_atr_and_the_daily_chart_read_one_candle_for_today():
    """AMD on 2026-11-10: Schwab's two feeds differ on the day's low (495 pushed, 500.25 sent).

    Each is taken as sent, never altered. Until Schwab's series holds the day, the ATR and the
    daily chart both read the pushed candle; once it does, after the close, both read the
    series' candle.
    """
    tk = "AMD"
    day = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "real_amd_day_fields_and_daily_candles_2026_11_10.json"
        ).read_text(encoding="utf-8")
    )
    sent = day["daily"]["candles"]
    after = datetime(2026, 11, 10, 16, 30, tzinfo=ET)

    def series(candles: list) -> None:
        topic, msg = price_history_message(
            tk, "1d", dict(day["daily"], candles=candles), day["daily_ts_recv"]
        )
        ofs._ingest_pushed(topic, msg)
        server._write_streamed_bars([ofs.streamed_bars.get_nowait()], after)

    server._series.pop((tk, "1d"), None)
    try:
        for q in day["quotes"]:
            lmp.record_from_level_one_equity(tk, q["native"], received_ts=q["ts_recv"])
        series(sent[:-1])
        pushed = dict(sent[-1], low=495)
        assert server.chart_bars(tk, "D", [], after)[-1]["l"] == 495 != sent[-1]["low"]
        assert server._atr(tk, after).daily == _wilder_atr([*sent[:-1], pushed])
        series(sent)
        assert server.chart_bars(tk, "D", [], after)[-1]["l"] == sent[-1]["low"] == 500.25
        assert server._atr(tk, after).daily == _wilder_atr(sent)
    finally:
        server._series.pop((tk, "1d"), None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)


def test_the_console_takes_schwabs_bars_and_candles_from_the_push_and_computes_the_atr_from_them():
    """Each series published on the daemon's bus, read by the console as Schwab's, taken by it.

    Read by live_push.is_forwarded, the console's _bus_loop; taken (streaming._ingest_pushed ->
    the bar writer): the 1-minute bars every reader reads are Schwab's candles, each field as
    sent; the daily, weekly and monthly ATR are those of Schwab's daily, weekly and monthly
    candles (at the answer's time, before the session: no candle of today yet), and a ticker
    whose weekly and monthly candles have not arrived (TSLA here) has neither ATR.
    """
    bus = MessageBus()
    sub = bus.subscribe("pricehistory.", policy=LATEST)
    asked = [(tk, s) for tk in ("SPY", "TSLA") for s in ("1m", "1d")]
    asked += [(tk, s) for tk in ("SPY", "AMD") for s in ("1w", "1mo")]
    for tk, series in asked:
        a = HISTORY[(tk, *_SERIES[series])]
        bus.publish(*price_history_message(tk, series, a["body"], a["answered_utc"]))
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get_nowait()
    for tk, series in asked:
        server._bars.pop(tk, None)
        server._series.pop((tk, series), None)
    try:
        assert len(sub.changed) == 8, "each series asked, its current record on the bus"
        for key in list(sub.changed):
            topic, record = bus.current[key]
            assert live_push.is_forwarded(topic, record)
            ofs._ingest_pushed(topic, record)  # as the console's _bus_loop hands it over
        msgs = []
        while not ofs.streamed_bars.empty():
            msgs.append(ofs.streamed_bars.get_nowait())
        assert len(msgs) == 8
        answered = datetime.fromtimestamp(HISTORY[("SPY", "minute", "1")]["answered_utc"], ET)
        server._write_streamed_bars(msgs, answered)
        for tk in ("SPY", "TSLA"):
            minutes = HISTORY[(tk, "minute", "1")]["body"]["candles"]
            got = [
                (b.ts, b.open, b.high, b.low, b.close, b.volume)
                for b in server._bars_1m(tk, server.BARS_KEPT)
            ]
            assert got == [
                (c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
                for c in minutes
            ], tk
            daily = HISTORY[(tk, "daily", "1")]["body"]["candles"]
            assert server._atr(tk, answered).daily == _wilder_atr(daily), tk
        for tk in ("SPY", "AMD"):
            atr = server._atr(tk, answered)
            weekly, monthly = (HISTORY[(tk, kind, "1")]["body"]["candles"] for kind in _SENT)
            assert atr.weekly == _wilder_atr(weekly), tk
            assert atr.monthly == _wilder_atr(monthly), tk
        tsla = server._atr("TSLA", answered)
        assert (tsla.weekly, tsla.monthly) == (None, None), "not arrived: no ATR, none made up"
    finally:
        for tk, series in asked:
            server._bars.pop(tk, None)
            server._series.pop((tk, series), None)


def test_a_price_history_sent_again_with_every_minute_held_changes_nothing():
    """The daemon pushes a ticker's price history again.

    It asks once per ET date and again after its own restart: the console's bars stay Schwab's
    candles as first taken, and the ticker's open page is told of no change (no liquidity push,
    no levels rebuilt for it).
    """
    for tk in ("SPY", "TSLA"):
        now = datetime.fromtimestamp(HISTORY[(tk, "minute", "1")]["answered_utc"], ET)
        server._bars.pop(tk, None)
        try:
            first, again = _told(tk, [partial(_held, tk, "1m", now)] * 2)
            got = [
                (b.ts, b.open, b.high, b.low, b.close, b.volume)
                for b in server._bars_1m(tk, server.BARS_KEPT)
            ]
        finally:
            server._bars.pop(tk, None)
        assert "liquidity" in first, tk
        assert again == set(), (tk, again)
        assert got == [
            (c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
            for c in HISTORY[(tk, "minute", "1")]["body"]["candles"]
        ], tk


def test_a_price_history_that_brings_minutes_not_held_adds_exactly_those():
    """An earlier answer held without its newest session and without every seventh minute.

    The next answer brings them: the bars are Schwab's whole answer, each minute once, in time
    order, and the page is told the bars changed.
    """
    for tk in ("SPY", "TSLA"):
        sent = HISTORY[(tk, "minute", "1")]["body"]["candles"]
        earlier = [c for i, c in enumerate(sent[:-390]) if i % 7]
        now = datetime.fromtimestamp(HISTORY[(tk, "minute", "1")]["answered_utc"], ET)
        server._bars.pop(tk, None)
        try:
            _held(tk, "1m", now, earlier)
            (told,) = _told(tk, [partial(_held, tk, "1m", now)])
            got = [
                (b.ts, b.open, b.high, b.low, b.close, b.volume)
                for b in server._bars_1m(tk, server.BARS_KEPT)
            ]
        finally:
            server._bars.pop(tk, None)
        assert "liquidity" in told, tk
        assert got == [
            (c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
            for c in sent
        ], tk


def test_new_daily_candles_reach_the_open_page_and_the_same_candles_again_do_not():
    """The daily candles the ATR is computed from.

    An answer with a candle the console does not
    hold tells the open page (the trade desk re-reads its ATR); the same answer again tells it
    nothing.
    """
    for tk in ("SPY", "TSLA"):
        sent = HISTORY[(tk, "daily", "1")]["body"]["candles"]
        now = datetime.fromtimestamp(HISTORY[(tk, "daily", "1")]["answered_utc"], ET)
        server._series.pop((tk, "1d"), None)
        try:
            _held(tk, "1d", now, sent[:-1])
            newer, again = _told(tk, [partial(_held, tk, "1d", now)] * 2)
            held = [
                (c.ts, c.open, c.high, c.low, c.close, c.volume) for c in server._series[(tk, "1d")]
            ]
        finally:
            server._series.pop((tk, "1d"), None)
        assert "liquidity" in newer, tk
        assert again == set(), (tk, again)
        assert held == [
            (c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
            for c in sent
        ], tk


#: a console just started (a fresh interpreter): its first price history, SPY's and TSLA's
#: 1-minute series as Schwab answered them, taken by the bar writer; the modules loaded meanwhile
_FIRST_TAKE = (
    """
import json, sys
sys.path.insert(0, sys.argv[1])
from datetime import datetime
import server
from tests.schwab_rest_standin import HISTORY
from time_et import ET
msgs = [{"src": "schwab_pricehistory", "symbol": tk, "series": "1m", """
    """"ts_recv": a["answered_utc"], "answer": a["body"]}
        for tk, a in ((tk, HISTORY[(tk, "minute", "1")]) for tk in ("SPY", "TSLA"))]
now = datetime.fromtimestamp(msgs[0]["ts_recv"], ET)
before = set(sys.modules)
server._write_streamed_bars(msgs, now)
print(json.dumps({"loaded": sorted(set(sys.modules) - before),
                  "bars": [len(server._bars_1m(tk, server.BARS_KEPT)) for tk in ("SPY", "TSLA")],
                  "levels": [server.canonical_price_level_snapshot(tk, now) is not None """
    """for tk in ("SPY", "TSLA")]}))
"""
)


def test_a_console_just_started_takes_its_first_price_history_without_loading_a_module():
    """The first price history after the console starts reaches its bars and price levels.

    With nothing loaded on the way (a module loaded there holds up the first answer beside the
    pricing thread).
    """
    done = subprocess.run(
        [
            sys.executable,
            "-W",
            "ignore",
            "-c",
            _FIRST_TAKE,
            str(Path(__file__).resolve().parent.parent),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["loaded"] == [] and all(got["bars"]) and got["levels"] == [True, True], got


def test_before_schwab_sends_the_candles_the_atr_is_absent():
    """No daily candles: each ATR is None. The producer does not attach a sentence."""
    atr = server._atr("ZZNOCANDLES", datetime(2026, 10, 7, 10, 0, tzinfo=ET))
    assert (atr.daily, atr.weekly, atr.monthly) == (None, None, None)
    assert not hasattr(atr, "daily_reason")


def test_the_daemons_writer_records_every_answer_as_schwab_sent_it(tmp_path):
    """Schwab's /pricehistory answers are recorded like every stream message.

    docs/DATA_FLOW.md §2 D4: the daemon's chain sweep (capture.run_chains, on its thread)
    publishes each series on the daemon's bus, and the one writer (CaptureWriter, the bus's LOG
    reader) writes each answer whole, as sent, into stream_pricehistory_raw: SPY's 1-, 5-, 15-
    and 30-minute and daily answers.
    """
    db = tmp_path / "stream_capture.db"
    schwab = LocalSchwab()
    client = schwab.client(tmp_path)

    def rows():
        if not db.exists():
            return []
        con = sqlite3.connect(db)
        try:
            if not con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='stream_pricehistory_raw'"
            ).fetchone():
                return []
            return con.execute(
                "SELECT symbol, series, native_json, src FROM stream_pricehistory_raw "
                "ORDER BY rowid"
            ).fetchall()
        finally:
            con.close()

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health, ["SPY"])
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        written = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        sweep = asyncio.create_task(
            capture.run_chains(
                daemon, tmp_path / "ed_console.db", lambda: client, stop, failures=writer
            )
        )
        deadline = asyncio.get_running_loop().time() + 30
        while len(rows()) < 5 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        stop.set()
        await asyncio.gather(written, sweep)

    try:
        asyncio.run(go())
    finally:
        schwab.close()
    recorded = rows()[:5]
    assert [(symbol, series, src) for symbol, series, _n, src in recorded] == [
        ("SPY", "1m", "schwab_pricehistory"),
        ("SPY", "5m", "schwab_pricehistory"),
        ("SPY", "15m", "schwab_pricehistory"),
        ("SPY", "30m", "schwab_pricehistory"),
        ("SPY", "1d", "schwab_pricehistory"),
    ]
    for _s, series, native, _src in recorded:
        assert json.loads(native) == HISTORY[("SPY", *_SERIES[series])]["body"], (
            f"{series}: recorded as sent"
        )
