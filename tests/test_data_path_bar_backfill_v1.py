"""The bar backfill (capture.run_backfill): at its start the capture daemon asks Schwab's price
history for the 1-minute bars its record (stream_capture.db stream_bars_raw) lacks, for each board
ticker in the current and previous session, one request at a time, paced, on its one client. Each
returned candle of a missing minute goes to its one writer as a row labelled BAR_BACKFILL_SRC,
Schwab's candle as sent; a minute the stream recorded is never written again and its streamed bar
always wins on the screen (server._load_bars); a 403 or 429 stops the backfill with no retry, in
the record and on the daemon's status.

Real data: SPY's CHART_EQUITY bars as the daemon recorded them on 2026-10-05 (the recorder wrote
nothing from 09:17 to 10:47 CT), Schwab's price-history reply for SPY that day (captured 2026-10-05
11:17 CT; Schwab sent the whole day up to that minute, 06:00 to 11:17 CT, for a 09:00-11:00 CT
request), and Schwab's edge's 403 page as it answered on 2026-10-03. Stand-ins, named: the local
server playing Schwab's host; its answer for a session the captured reply does not cover (Schwab's
reply with no candle, in the captured reply's keys); its 429 answer (no 429 of Schwab's is captured:
the status with Schwab's documented error body); and `now`, the capture's send time."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from schwab.client import Client

import server
from app.market_data.schwab.streaming import capture
from db_authority import canonical_stream_db_path
from stream_spine import BAR_BACKFILL_SRC, LOG, CaptureWriter, HealthRegistry, MessageBus, bar_msg
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from time_et import CT, ET

FX = Path(__file__).resolve().parent / "fixtures"
STREAMED = daemon_bars("real_daemon_bars_spy_2026_10_05.json")
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


def _run_backfill(schwab: _LocalSchwab, board: "list[str]", record: Path) -> capture.Daemon:
    """The daemon's backfill at NOW, through its bus and its one writer into `record`."""
    async def run():
        bus = MessageBus()
        writer = CaptureWriter(record)
        daemon = capture.Daemon(bus, HealthRegistry(), board=board)
        stop = asyncio.Event()
        written = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
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
        con.execute("DELETE FROM stream_bars_raw WHERE src=?", (BAR_BACKFILL_SRC,))
        con.execute("DELETE FROM stream_subscriptions WHERE service='PRICEHISTORY'")
    server._bars.pop("SPY", None)


def test_the_minutes_the_stream_missed_are_filled_from_schwabs_price_history_labelled_and_reach_the_chart():
    record = canonical_stream_db_path()
    record_daemon_bars(STREAMED)
    schwab = _LocalSchwab("replay")
    try:
        daemon = _run_backfill(schwab, ["SPY"], record)
        written = _rows(record, "SELECT bar_start_ms, open, high, low, close, volume, native_json FROM "
                                "stream_bars_raw WHERE symbol='SPY' AND src=? ORDER BY bar_start_ms",
                        BAR_BACKFILL_SRC)
        streamed_after = _rows(record, "SELECT COUNT(*) FROM stream_bars_raw WHERE symbol='SPY' AND src='schwab_chart' "
                                       "AND bar_start_ms>=? AND bar_start_ms<?", DAY_LO, DAY_HI)[0][0]
        answers = _rows(record, "SELECT symbols_json, code FROM stream_subscriptions WHERE service='PRICEHISTORY'")
        server._load_bars()
        served = {round(b["t"] * 1000): b for b in
                  TestClient(server.app).get("/api/bars1m?ticker=SPY").json()["bars"]
                  if DAY_LO <= b["t"] * 1000 < DAY_HI}
    finally:
        schwab.close()
        _forget(record)
    streamed = {r["bar_start_ms"] for r in STREAMED}
    minute_now = int(NOW // 60) * 60_000
    missed = {ms: c for ms, c in CANDLES.items() if ms not in streamed and DAY_LO <= ms < minute_now}
    assert set(GAP) <= set(missed), "the recorder's gap is in Schwab's price history"
    # every missed minute Schwab sent is written, labelled, as Schwab sent it; nothing else is
    assert [(ms, o, h, lo, c, v, json.loads(n)) for ms, o, h, lo, c, v, n in written] == [
        (ms, c["open"], c["high"], c["low"], c["close"], c["volume"], c) for ms, c in sorted(missed.items())]
    # a minute the stream recorded is never written again, and its rows stand as they were
    assert streamed_after == len(STREAMED)
    # one request per session with a missing minute (2026-10-05 and 2026-10-02), paced
    assert [(path, q["symbol"], q["frequencyType"], q["frequency"], q["needExtendedHoursData"])
            for _t, path, q in schwab.requests] == [("/marketdata/v1/pricehistory", "SPY", "minute", "1", "true")] * 2
    assert schwab.requests[1][0] - schwab.requests[0][0] >= capture.BACKFILL_PACE_SEC
    assert [(json.loads(s), code) for s, code in answers] == [(["SPY"], 200)] * 2
    assert daemon.status()["backfill"] == {"state": capture.BACKFILL_DONE, "requests": 2,
                                           "written": len(missed), "stopped_by": None}
    # Schwab -> screen: the chart serves the streamed bars and, in the gap, Schwab's candles
    for ms in GAP:
        c = CANDLES[ms]
        assert (served[ms]["o"], served[ms]["h"], served[ms]["l"], served[ms]["c"], served[ms]["v"]) == \
            (c["open"], c["high"], c["low"], c["close"], c["volume"]), datetime.fromtimestamp(ms / 1000, CT)


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
                                        src=BAR_BACKFILL_SRC, native=candle, ts_recv=bar["ts_recv"] + 3600))
    try:
        server._load_bars()
        (kept,) = [b for b in server._bars_1m("SPY", server.BARS_KEPT) if b.ts * 1000 == minute]
    finally:
        _forget(record)
    assert kept.volume == bar["volume"]


@pytest.mark.parametrize("refusal", [429, 403])
def test_a_429_or_403_stops_the_backfill_with_no_retry_in_the_record_and_on_the_status(tmp_path, refusal):
    record = tmp_path / "stream_capture.db"
    schwab = _LocalSchwab(refusal)
    try:
        daemon = _run_backfill(schwab, ["SPY", "QQQ"], record)
    finally:
        schwab.close()
    assert len(schwab.requests) == 1, f"{len(schwab.requests)} requests after a {refusal}"
    assert _rows(record, "SELECT COUNT(*) FROM stream_bars_raw")[0][0] == 0
    ((symbols, code, reason),) = _rows(record, "SELECT symbols_json, code, reason FROM stream_subscriptions "
                                               "WHERE service='PRICEHISTORY'")
    assert (json.loads(symbols), code) == (["SPY"], refusal) and f"HTTP {refusal}" in reason
    status = daemon.status()["backfill"]
    assert (status["state"], status["requests"], status["written"]) == (capture.BACKFILL_REFUSED, 1, 0)
    assert status["stopped_by"].startswith(f"SPY: HTTP {refusal}")
