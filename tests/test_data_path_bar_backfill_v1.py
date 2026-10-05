"""The bar backfill (capture.run_backfill): at its start the capture daemon finds in its record the
spans it was not recording Schwab's 1-minute bars (its once-a-minute CHART_EQUITY feed-status rows
missing, or saying the socket was closed), and asks Schwab's price history for each symbol's minutes
in those spans that have no bar, in the current and previous session, one request at a time, paced,
on its one client, only when the chain sweep's refusal pause allows. Each returned candle of such a
minute goes to its one writer as a row labelled `schwab_pricehistory`, Schwab's candle as sent; a
minute the stream recorded is never written again and its streamed bar always wins on the screen
(server._load_bars). A 403 or 429 stops the backfill with no retry and pauses the sweep; the record,
the daemon's status and the chart's line (/api/bars1m `backfill`) say so.

Real data: SPY's CHART_EQUITY bars as the daemon recorded them on 2026-10-05 and its CHART_EQUITY
feed-status rows that day (the recorder was not recording from 09:16:10 to 10:50:12 CT: no bar
from 09:17 to 10:47 CT), Schwab's
price-history reply for SPY that day (captured 2026-10-05 11:17 CT; Schwab sent the whole day up to
that minute, 06:00 to 11:17 CT, for a 09:00-11:00 CT request), and Schwab's edge's 403 page as it
answered on 2026-10-03. Stand-ins, named: the local server playing Schwab's host; its answer for a
session the captured reply does not cover (Schwab's reply with no candle, in the captured reply's
keys); its 429 answer (no 429 of Schwab's is captured: the status with Schwab's documented error
body); and `now`, the capture's send time.

The file imports on main, which has no backfill, so each test fails there on what it checks."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from schwab.client import Client

import live_market_plane as lmp
import server
import stream_spine
from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import ChainSweep
from db_authority import canonical_stream_db_path
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, bar_msg
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from time_et import CT, ET

FX = Path(__file__).resolve().parent / "fixtures"
#: the label of a backfilled row (operator 2026-10-05: each backfilled minute is a labelled entry)
BACKFILL_SRC = "schwab_pricehistory"
STREAMED = daemon_bars("real_daemon_bars_spy_2026_10_05.json")
FEED = json.loads((FX / "real_feed_status_chart_equity_2026_10_05.json").read_text(encoding="utf-8"))["rows"]
_PH = json.loads((FX / "real_spy_pricehistory_2026_10_05_0900_1100ct.json").read_text(encoding="utf-8"))
CANDLES = {c["datetime"]: c for c in _PH["reply"]["candles"]}
_AKAMAI_403 = json.loads((FX / "real_schwab_akamai_403_2026_10_03.json").read_text(encoding="utf-8"))
#: stand-in: the clock is the captured reply's send time
NOW = datetime.fromisoformat(_PH["provenance"]["sent_at_utc"]).timestamp()
DAY_LO = int(datetime(2026, 10, 5, 4, 0, tzinfo=ET).timestamp() * 1000)
DAY_HI = int(datetime(2026, 10, 5, 20, 0, tzinfo=ET).timestamp() * 1000)
#: the minutes the recorder missed: 09:17 to 10:47 CT
GAP = range(int(datetime(2026, 10, 5, 9, 17, tzinfo=CT).timestamp() * 1000),
            int(datetime(2026, 10, 5, 10, 48, tzinfo=CT).timestamp() * 1000), 60_000)


class _LocalSchwab:
    """Schwab's host, played by a local server. `answer`: "replay" (the captured SPY reply for a
    request starting on 2026-10-05 ET, a reply with no candle otherwise), 429, or 403 (the captured
    page). Every request is recorded: (monotonic time, path, query)."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, content_type, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                outer.requests.append((time.monotonic(), url.path, query))
                if outer.answer == 403:
                    return self._send(403, "text/html", _AKAMAI_403["body"].encode())
                if outer.answer == 429:
                    return self._send(429, "application/json", json.dumps({"errors": [{
                        "status": "429", "title": "Too Many Requests"}]}).encode())
                if DAY_LO <= int(query["startDate"]) < DAY_HI:
                    return self._send(200, "application/json", json.dumps(_PH["reply"]).encode())
                self._send(200, "application/json", json.dumps(
                    {"candles": [], "symbol": query["symbol"], "empty": True}).encode())

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]

        class ToLocal(httpx.BaseTransport):
            def __init__(self):
                self.inner = httpx.HTTPTransport()

            def handle_request(self, request):
                request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=port)
                return self.inner.handle_request(request)

        self.client = Client("k", httpx.Client(transport=ToLocal()), enforce_enums=False)   # as the daemon's

    def close(self):
        self.server.shutdown()


def _sweep(tmp_path: Path) -> ChainSweep:
    """The daemon's chain sweep (no worker started): the one owner of when Schwab may be asked."""
    return ChainSweep(tmp_path / "ed_console.db", [], lambda topic, msg: None)


def _record_feed(record: Path) -> None:
    """The daemon's feed-status rows of 2026-10-05, as captured, through its own writer."""
    writer = CaptureWriter(record)
    with sqlite3.connect(str(writer.db_path), timeout=30.0) as con:
        for r in FEED:
            writer.insert("feedstatus.CHART_EQUITY", r, conn=con)


def _run_backfill(schwab: _LocalSchwab, sweep: ChainSweep, board: "list[str]", record: Path,
                  stop_after: "float | None" = None) -> capture.Daemon:
    """The daemon's backfill at NOW, through its bus and its one writer into `record`; the daemon
    stops after `stop_after` seconds when given."""
    async def run():
        bus = MessageBus()
        writer = CaptureWriter(record)
        daemon = capture.Daemon(bus, HealthRegistry(), board=board)
        daemon.chains = sweep
        stop = asyncio.Event()
        written = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        if stop_after is not None:
            asyncio.get_running_loop().call_later(stop_after, stop.set)
        await capture.run_backfill(daemon, lambda: schwab.client, writer.db_path, NOW, stop)
        stop.set()
        await written
        return daemon
    return asyncio.run(run())


def _rows(record: Path, sql: str, *args) -> list:
    with sqlite3.connect(str(record)) as con:
        return con.execute(sql, args).fetchall()


def _forget(record: Path) -> None:
    """What these tests wrote to this run's stream_capture.db, removed (a test leaves nothing)."""
    forget_daemon_bars(STREAMED)
    with sqlite3.connect(str(record), timeout=30.0) as con:
        con.execute("DELETE FROM stream_bars_raw WHERE src=?", (BACKFILL_SRC,))
        con.execute("DELETE FROM stream_subscriptions WHERE service='PRICEHISTORY'")
        con.executemany("DELETE FROM stream_feed_status WHERE service='CHART_EQUITY' AND ts=?", [(r["ts"],) for r in FEED])
    server._bars.pop("SPY", None)


def test_the_minutes_the_recorder_missed_are_filled_from_schwabs_price_history_labelled_and_reach_the_chart(tmp_path):
    record = canonical_stream_db_path()
    record_daemon_bars(STREAMED)
    _record_feed(record)
    schwab = _LocalSchwab("replay")
    try:
        daemon = _run_backfill(schwab, _sweep(tmp_path), ["SPY"], record)
        written = _rows(record, "SELECT bar_start_ms, open, high, low, close, volume, native_json FROM "
                                "stream_bars_raw WHERE symbol='SPY' AND src=? ORDER BY bar_start_ms", BACKFILL_SRC)
        streamed_after = _rows(record, "SELECT COUNT(*) FROM stream_bars_raw WHERE symbol='SPY' AND src='schwab_chart' "
                                       "AND bar_start_ms>=? AND bar_start_ms<?", DAY_LO, DAY_HI)[0][0]
        answers = _rows(record, "SELECT symbols_json, code FROM stream_subscriptions WHERE service='PRICEHISTORY'")
        asked = len(schwab.requests)
        again = _run_backfill(schwab, _sweep(tmp_path), ["SPY"], record)      # the daemon's next start
        server._load_bars()
        served = {round(b["t"] * 1000): b for b in
                  TestClient(server.app).get("/api/bars1m?ticker=SPY").json()["bars"]
                  if DAY_LO <= b["t"] * 1000 < DAY_HI}
    finally:
        schwab.close()
        _forget(record)
    # exactly the minutes the recorder missed while it was not recording, labelled, as Schwab sent
    # them; 11:15 CT (no streamed bar, but recorded while recording) is not one
    assert [(ms, o, h, lo, c, v, json.loads(n)) for ms, o, h, lo, c, v, n in written] == [
        (ms, CANDLES[ms]["open"], CANDLES[ms]["high"], CANDLES[ms]["low"], CANDLES[ms]["close"],
         CANDLES[ms]["volume"], CANDLES[ms]) for ms in GAP]
    # a minute the stream recorded is never written again, and its rows stand as they were
    assert streamed_after == len(STREAMED)
    # 2026-10-05 and 2026-10-02 (the record holds no feed-status row that day), paced
    assert [(path, q["symbol"], q["frequencyType"], q["frequency"], q["needExtendedHoursData"])
            for _t, path, q in schwab.requests] == [("/marketdata/v1/pricehistory", "SPY", "minute", "1", "true")] * 2
    # Schwab answered for those spans: the next start asks nothing
    assert (asked, again.status()["backfill"]["planned"]) == (2, 0)
    assert schwab.requests[1][0] - schwab.requests[0][0] >= capture.BACKFILL_PACE_SEC
    assert [(json.loads(s), code) for s, code in answers] == [(["SPY"], 200)] * 2
    status = daemon.status()["backfill"]
    assert (status["state"], status["planned"], status["requests"], status["written"], status["stopped_by"]) == \
        (stream_spine.BACKFILL_DONE, 2, 2, len(GAP), None)
    # Schwab -> screen: the chart serves Schwab's candles in the gap
    for ms in GAP:
        c = CANDLES[ms]
        assert (served[ms]["o"], served[ms]["h"], served[ms]["l"], served[ms]["c"], served[ms]["v"]) == \
            (c["open"], c["high"], c["low"], c["close"], c["volume"]), datetime.fromtimestamp(ms / 1000, CT)


def test_a_session_the_recorder_recorded_throughout_costs_no_request(tmp_path):
    """2026-10-05 up to 09:16 CT: the feed-status rows are a minute apart and the socket open, so
    nothing is asked, though most minutes before 07:00 ET have no bar (Schwab sends none)."""
    record = tmp_path / "stream_capture.db"
    _record_feed(record)
    for r in STREAMED:
        CaptureWriter(record).insert("bar1m.SPY", bar_msg(**{k: r[k] for k in (
            "symbol", "bar_start_ms", "open", "high", "low", "close", "volume", "src", "ts_recv", "native", "schwab_ts")}))
    now = datetime(2026, 10, 5, 9, 16, tzinfo=CT).timestamp()
    with sqlite3.connect(f"file:{record.as_posix()}?mode=ro", uri=True) as con:
        assert capture.day_gaps(con, ["SPY", "QQQ"], date(2026, 10, 5), now) == []
        # and by the same record, the gap that followed is found
        later = [(g.symbol, len(g.missing)) for g in capture.day_gaps(con, ["SPY"], date(2026, 10, 5), NOW)]
    assert later == [("SPY", len(GAP))]


def test_an_answer_counts_only_for_the_spans_it_asked_about(tmp_path):
    """The reviewer's case (scratchpad probe induce_answered_other_day.py): Schwab answered SPY's
    2026-10-05 request, then a 429 stopped the run before SPY's 2026-10-02 request. At the next
    start the 2026-10-02 gap (the record holds no feed-status row that day) is still asked for.
    (That the answered spans are not asked again is the first test's second start.)"""
    record = tmp_path / "stream_capture.db"
    _record_feed(record)
    with sqlite3.connect(f"file:{record.as_posix()}?mode=ro", uri=True) as con:
        before = len(capture.day_gaps(con, ["SPY"], date(2026, 10, 2), NOW))
    CaptureWriter(record).insert("sub.PRICEHISTORY", stream_spine.subscription_msg(
        service="PRICEHISTORY", command="GET", symbols=["SPY"], code=200,
        reason="91 minute(s) missing from 2026-10-05 10:16 to 11:46 ET; 91 written", ts=NOW + 1))
    with sqlite3.connect(f"file:{record.as_posix()}?mode=ro", uri=True) as con:
        after = len(capture.day_gaps(con, ["SPY"], date(2026, 10, 2), NOW))
    assert (before, after) == (1, 1), "SPY's 2026-10-02 gap was dropped by an answer for 2026-10-05"


def test_a_bar_stall_on_an_open_socket_in_the_regular_session_is_not_recording(tmp_path):
    """2026-10-02 12:00 to 12:18 ET the record's feed-status rows said the socket open while
    CHART_EQUITY's last bar was 126 to 157 s old (measured in production's record). Stand-in: six
    such rows a minute apart, the 12:03 ET one with its last bar 135 s old, the others 5 s."""
    record = tmp_path / "stream_capture.db"
    writer = CaptureWriter(record)
    base = datetime(2026, 10, 2, 12, 0, tzinfo=ET).timestamp()
    for i in range(6):
        ts = base + 60 * i
        writer.insert("feedstatus.CHART_EQUITY", {"ts": ts, "service": "CHART_EQUITY", "socket_open": True,
                                                  "schwab_last_frame_ts": ts, "held": 40,
                                                  "last_data_ts": ts - (135 if i == 3 else 5)})
    with sqlite3.connect(f"file:{record.as_posix()}?mode=ro", uri=True) as con:
        assert capture.not_recording(con, base, base + 300) == [(base + 120, base + 240)]


def test_a_streamed_minute_wins_over_a_backfilled_candle_of_the_same_minute():
    """08:44 CT: Schwab streamed volume 118573.208601, its price history says 118573. A candle
    recorded for that minute after the streamed bar (the stream's bar landing after the backfill
    read the record) never replaces the streamed bar on the screen."""
    record = canonical_stream_db_path()
    minute = int(datetime(2026, 10, 5, 8, 44, tzinfo=CT).timestamp() * 1000)
    (bar,) = [r for r in STREAMED if r["bar_start_ms"] == minute]
    candle = CANDLES[minute]
    assert bar["volume"] != candle["volume"]
    record_daemon_bars(STREAMED)
    writer = CaptureWriter(record)
    writer.insert("bar1m.SPY", bar_msg(symbol="SPY", bar_start_ms=minute, open=candle["open"], high=candle["high"],
                                       low=candle["low"], close=candle["close"], volume=candle["volume"],
                                       src=BACKFILL_SRC, native=candle, ts_recv=bar["ts_recv"] + 3600))
    try:
        server._load_bars()
        (kept,) = [b for b in server._bars_1m("SPY", server.BARS_KEPT) if b.ts * 1000 == minute]
    finally:
        _forget(record)
    assert kept.volume == bar["volume"]


@pytest.mark.parametrize("refusal", [429, 403])
def test_a_429_or_403_stops_the_backfill_pauses_the_sweep_and_the_chart_says_so(tmp_path, refusal):
    record = tmp_path / "stream_capture.db"
    sweep = _sweep(tmp_path)
    schwab = _LocalSchwab(refusal)
    try:
        daemon = _run_backfill(schwab, sweep, ["SPY", "QQQ"], record)
    finally:
        schwab.close()
    assert len(schwab.requests) == 1, f"{len(schwab.requests)} requests after a {refusal}"
    assert _rows(record, "SELECT COUNT(*) FROM stream_bars_raw")[0][0] == 0
    ((symbols, code, reason),) = _rows(record, "SELECT symbols_json, code, reason FROM stream_subscriptions "
                                               "WHERE service='PRICEHISTORY'")
    assert (json.loads(symbols), code) == (["QQQ"], refusal) and f"HTTP {refusal}" in reason
    status = daemon.status()["backfill"]
    assert (status["state"], status["requests"], status["written"], status["stopped_by"]) == \
        (stream_spine.BACKFILL_REFUSED, 1, 0, f"QQQ: HTTP {refusal}")
    # the one owner of when Schwab may be asked: the chain sweep is paused too
    halt = threading.Event()
    threading.Timer(0.3, halt.set).start()
    assert not sweep.clear_to_ask(halt), "the sweep was not paused by the backfill's refusal"
    # the console serves the daemon's heartbeat as the chart's line, its time in Central Time
    lmp.record_feed_heartbeat(daemon.status())
    try:
        line = TestClient(server.app).get("/api/bars1m?ticker=QQQ").json()["backfill"]
    finally:
        lmp.record_feed_down()
    assert line == (f"BAR BACKFILL STOPPED {server.ct_label(status['ended_ts'])}: Schwab refused (QQQ: HTTP {refusal}), "
                    f"no retry; 1 of {status['planned']} price-history requests sent, 0 bars written")
    assert server.ct_label(status["ended_ts"]).endswith(" CT")


def test_while_the_sweep_is_paused_after_schwabs_refusal_the_backfill_asks_nothing(tmp_path):
    """The chain sweep had a 403 (its pause: FAILED_PAUSE_SEC); the daemon stops 0.5 s later. The
    backfill, with minutes to ask for, sent nothing in that time."""
    sweep = _sweep(tmp_path)
    sweep.schwab_answered(403, time.time())
    schwab = _LocalSchwab("replay")
    try:
        daemon = _run_backfill(schwab, sweep, ["SPY"], tmp_path / "stream_capture.db", stop_after=0.5)
    finally:
        schwab.close()
    assert schwab.requests == []
    assert daemon.status()["backfill"]["requests"] == 0


def test_the_browser_tests_bars_answer_is_what_the_console_serves_for_its_heartbeat():
    """tests/e2e/bar-backfill-line.spec.js draws a captured /api/bars1m answer; its line is what
    server.backfill_line gives for the captured heartbeat, so the browser test's wording cannot
    drift from the console's."""
    fx = json.loads((FX.parent / "e2e" / "fixtures" / "bars1m_backfill_refused.json").read_text(encoding="utf-8"))
    assert server.backfill_line(fx["heartbeat"]) == fx["response"]["backfill"]
    assert fx["response"]["backfill"].startswith("BAR BACKFILL STOPPED ")
