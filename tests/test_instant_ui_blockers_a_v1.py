"""Audit of #280, blockers fixed in PR A -- behavioural tests on the real daemon/server code.

- a service is marked alive only by a frame that parsed and published (it beat BEFORE parsing,
  so a frame shape failing on every message kept LEVELONE "RUNNING" with nothing delivered);
- a sustained run of skipped frames ends the pump (-> the watchdog recycles), while isolated
  bad frames between good ones do not.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import live_market_plane as lmp
import live_price_rows
import schwab_client as sc
import server as srv
import time_et
from tests.feed_live_helper import RTH_INSTANT, mark_feed_live
from tests.page_on_socket import Pages

# ── PR B: drop counts per consumer; atomic token refresh ─────────────────────────────────


def _token_file(tmp_path):
    """Write a token file in schwab-py's shape, valid for an hour.

    It is the stand-in for schwab_token.json.
    """
    tok = tmp_path / "schwab_token.json"
    tok.write_text(
        json.dumps(
            {
                "creation_timestamp": int(time_et.now()),
                "token": {
                    "access_token": "a",
                    "refresh_token": "r",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "expires_at": int(time_et.now()) + 3600,
                },
            }
        )
    )
    return tok


def test_every_token_refresh_writes_atomically(tmp_path):
    """The client we build refreshes through OUR writer (temp + replace), never open(path, 'w').

    Never in place (audit of #280: the atomic helper had no production caller). A replace puts a new
    file at the path (its file id changes); a write in place keeps the same file.
    """
    tok = _token_file(tmp_path)
    client = sc.client_from_token_file_atomic(str(tok), "k", "s")
    assert client.session.token["access_token"] == "a"
    before = os.stat(tok).st_ino
    client.session.update_token({"access_token": "b", "refresh_token": "r"})  # a refresh
    assert json.loads(tok.read_text())["token"]["access_token"] == "b"
    assert os.stat(tok).st_ino != before, "the refresh must land via os.replace"


def test_the_client_sends_one_request_at_a_time_on_one_connection(tmp_path):
    """Operator 2026-10-06: chains and quotes one request at a time on one connection.

    The client the daemon builds, asked for 20 requests at once from 20 threads, sends them one at a
    time (the server never holds two) over one connection (one client port).
    """
    n = 20
    lock = threading.Lock()
    seen = {"open": 0, "most": 0, "ports": set()}

    class Held(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            with lock:
                seen["open"] += 1
                seen["most"] = max(seen["most"], seen["open"])
                seen["ports"].add(self.client_address[1])
            time.sleep(0.02)
            with lock:
                seen["open"] -= 1
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Held)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        client = sc.client_from_token_file_atomic(str(_token_file(tmp_path)), "k", "s")
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        with ThreadPoolExecutor(max_workers=n) as pool:
            codes = list(pool.map(lambda _: client.session.get(url).status_code, range(n)))
    finally:
        httpd.shutdown()
    assert codes == [200] * n
    assert seen["most"] == 1, f"{seen['most']} requests at once"
    assert len(seen["ports"]) == 1, f"{len(seen['ports'])} connections"


# ── PR C: server-side bar roll-up; quote_tick carries the screen's numbers; heatmap demand ──


def test_bars_roll_up_server_side_and_unknown_volume_stays_unknown():
    t0 = 1_700_000_100.0  # a 5-minute boundary: 1_700_000_100 % 300 == 100? use floor
    base = t0 - (t0 % 300)
    m = [
        {"t": base + 60 * i, "o": 10 + i, "h": 11 + i, "l": 9 + i, "c": 10.5 + i, "v": 100}
        for i in range(7)
    ]
    m[6]["v"] = None  # one minute with no reported volume
    out = srv.aggregate_bars(m, "5")
    assert [b["t"] for b in out] == [base, base + 300]
    first, second = out
    assert (first["o"], first["h"], first["l"], first["c"], first["v"]) == (10, 15, 9, 14.5, 500)
    assert (second["o"], second["h"], second["l"], second["c"]) == (15, 17, 14, 16.5)
    assert second["v"] is None, (
        "a bucket with an unreported minute has unknown volume, not a partial sum"
    )
    assert srv.aggregate_bars(m, "1") == m


def test_daily_roll_up_is_keyed_on_the_et_trading_date():
    # 2026-09-24 19:59 ET and 20:01 ET are the same ET date; 00:01 ET next day is not
    d1a, d1b, d2 = 1_790_294_340.0, 1_790_294_460.0, 1_790_308_860.0
    out = srv.aggregate_bars(
        [
            {"t": d1a, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1},
            {"t": d1b, "o": 1.5, "h": 3, "l": 1, "c": 2, "v": 1},
            {"t": d2, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},
        ],
        "D",
    )
    assert len(out) == 2 and out[0]["h"] == 3 and out[0]["v"] == 2


def test_the_price_row_carries_feed_state_and_trade_age_and_no_bar():
    now = RTH_INSTANT  # regular hours: the market trades
    mark_feed_live("ZZQF", now=now)
    lmp.record_from_level_one_equity(
        "ZZQF", {"LAST_PRICE": 42.0, "TRADE_TIME_MILLIS": int((now - 7) * 1000)}, received_ts=now
    )
    ev = live_price_rows.price_row("ZZQF", now)
    assert (
        ev["feed_live"] is True
        and ev["spot"] == 42.0
        and ev["spot_source"] == srv.SPOT_SOURCE_PLANE
    )
    assert ev["trade_age_text"] == "7s"  # the trade 7 s before `now`, by the one age formatter
    assert "forming_1m" not in ev
    held_no_trade = live_price_rows.price_row("ZZNOTRADE", now)
    assert held_no_trade["spot"] is None


def test_a_tick_queues_a_reprice_for_its_ticker_viewed_or_not():
    """Every ticker's levels follow what Schwab pushes, not only the one on screen.

    A tick queues a reprice of its ticker, whether a page shows it or not
    (a page open on one, the pricing thread held while the ticks arrive, the queue read as it
    stands).
    """
    served = Pages()
    served.open("ZZVIEW")
    gate = threading.Event()
    srv._chain_pricing.submit(gate.wait, 10)
    try:
        srv._on_stream_tick("ZZNOTVIEWED")
        srv._on_stream_tick("ZZVIEW")
        with srv._chains_waiting_lock:
            waiting = dict(srv._chains_waiting)
    finally:
        gate.set()
        srv._chain_pricing.submit(lambda: None).result(timeout=10)
        served.stop()
    assert waiting == {
        "ZZNOTVIEWED": (srv.REPRICE, None, None, None),
        "ZZVIEW": (srv.REPRICE, None, None, None),
    }
