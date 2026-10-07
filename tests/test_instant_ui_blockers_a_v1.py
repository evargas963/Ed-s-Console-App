"""Audit of #280, blockers fixed in PR A -- behavioural tests on the real daemon/server code.

- a service is marked alive only by a frame that parsed and published (it beat BEFORE parsing,
  so a frame shape failing on every message kept LEVELONE "RUNNING" with nothing delivered);
- a sustained run of skipped frames ends the pump (-> the watchdog recycles), while isolated
  bad frames between good ones do not.
"""
from __future__ import annotations








# ── PR B: drop counts per consumer; atomic token refresh ─────────────────────────────────



def _token_file(tmp_path):
    """A token file in schwab-py's shape (the stand-in for schwab_token.json), valid for an hour."""
    import json
    import time
    tok = tmp_path / "schwab_token.json"
    tok.write_text(json.dumps({"creation_timestamp": int(time.time()), "token": {
        "access_token": "a", "refresh_token": "r", "token_type": "Bearer",
        "expires_in": 3600, "expires_at": int(time.time()) + 3600}}))
    return tok


def test_every_token_refresh_writes_atomically(monkeypatch, tmp_path):
    """The client we build refreshes through OUR writer (temp + replace), never open(path, 'w')
    in place (audit of #280: the atomic helper had no production caller)."""
    import json
    import os as _os
    import schwab_client as sc

    tok = _token_file(tmp_path)
    replaced = []
    real_replace = _os.replace
    monkeypatch.setattr(_os, "replace", lambda a, b: (replaced.append((a, b)), real_replace(a, b))[1])
    client = sc.client_from_token_file_atomic(str(tok), "k", "s")
    assert client.session.token["access_token"] == "a"
    client.session.update_token({"access_token": "b", "refresh_token": "r"})   # a refresh
    assert json.loads(tok.read_text())["token"]["access_token"] == "b"
    assert replaced and str(replaced[0][1]) == str(tok), "the refresh must land via os.replace"


def test_the_client_sends_one_request_at_a_time_on_one_connection(tmp_path):
    """Operator 2026-10-06: chains and quotes one request at a time on one connection. The
    client the daemon builds, asked for 20 requests at once from 20 threads, sends them one at a
    time (the server never holds two) over one connection (one client port)."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import schwab_client as sc
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
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Held)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = sc.client_from_token_file_atomic(str(_token_file(tmp_path)), "k", "s")
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        with ThreadPoolExecutor(max_workers=n) as pool:
            codes = list(pool.map(lambda _: client.session.get(url).status_code, range(n)))
    finally:
        srv.shutdown()
    assert codes == [200] * n
    assert seen["most"] == 1, f"{seen['most']} requests at once"
    assert len(seen["ports"]) == 1, f"{len(seen['ports'])} connections"




# ── PR C: server-side bar roll-up; quote_tick carries the screen's numbers; heatmap demand ──

def test_bars_roll_up_server_side_and_unknown_volume_stays_unknown():
    import server as srv
    t0 = 1_700_000_100.0                                    # a 5-minute boundary: 1_700_000_100 % 300 == 100? use floor
    base = t0 - (t0 % 300)
    m = [{"t": base + 60 * i, "o": 10 + i, "h": 11 + i, "l": 9 + i, "c": 10.5 + i, "v": 100} for i in range(7)]
    m[6]["v"] = None                                        # one minute with no reported volume
    out = srv.aggregate_bars(m, "5")
    assert [b["t"] for b in out] == [base, base + 300]
    first, second = out
    assert (first["o"], first["h"], first["l"], first["c"], first["v"]) == (10, 15, 9, 14.5, 500)
    assert (second["o"], second["h"], second["l"], second["c"]) == (15, 17, 14, 16.5)
    assert second["v"] is None, "a bucket with an unreported minute has unknown volume, not a partial sum"
    assert srv.aggregate_bars(m, "1") == m


def test_daily_roll_up_is_keyed_on_the_et_trading_date():
    import server as srv
    # 2026-09-24 19:59 ET and 20:01 ET are the same ET date; 00:01 ET next day is not
    d1a, d1b, d2 = 1_790_294_340.0, 1_790_294_460.0, 1_790_308_860.0
    out = srv.aggregate_bars([{"t": d1a, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1},
                              {"t": d1b, "o": 1.5, "h": 3, "l": 1, "c": 2, "v": 1},
                              {"t": d2, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1}], "D")
    assert len(out) == 2 and out[0]["h"] == 3 and out[0]["v"] == 2


def test_the_price_row_carries_feed_state_and_trade_age_and_no_bar(monkeypatch):
    import time as _t

    import live_market_plane as lmp
    import live_price_rows
    import server as srv
    from tests.feed_live_helper import mark_feed_live

    mark_feed_live("ZZQF")
    now = _t.time()
    lmp.record_from_level_one_equity("ZZQF", {"LAST_PRICE": 42.0, "TRADE_TIME_MILLIS": int((now - 7) * 1000)},
                                     received_ts=now)
    ev = live_price_rows.price_row("ZZQF")
    assert ev["feed_live"] is True and ev["spot"] == 42.0 and ev["spot_source"] == srv.SPOT_SOURCE_PLANE
    assert 6.0 <= ev["trade_age_sec"] <= 9.0
    assert "forming_1m" not in ev
    held_no_trade = live_price_rows.price_row("ZZNOTRADE")
    assert held_no_trade["spot"] is None


def test_spot_gamma_reprice_runs_only_for_a_viewed_heatmap(monkeypatch, view):
    import server as srv
    ran = []
    monkeypatch.setattr(srv, "_price_chain", lambda tk, what, c, ts: ran.append((tk, what)))
    view("ZZVIEW")
    srv._on_stream_tick("ZZNOTVIEWED")
    srv._on_stream_tick("ZZVIEW")
    srv._chain_pricing.submit(lambda: None).result(timeout=10)
    assert ran == [("ZZVIEW", srv.REPRICE)]
