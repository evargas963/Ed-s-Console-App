"""/api/levels and /api/terrain/strikes: what the level routes serve."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime as _dt
from pathlib import Path

import live_market_plane as lmp
import push_changes
import server as srv
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from micro_structure import Candle
from time_et import ET, now_et

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json"


def _forget(*tickers: str) -> None:
    """A stand-in ticker leaves no stored row, bar in memory or published level behind."""
    con = sqlite3.connect(srv.get_db().db_path)
    try:
        con.executemany("DELETE FROM price_bars_1m WHERE ticker=?", [(tk,) for tk in tickers])
        con.commit()
    finally:
        con.close()
    for tk in tickers:
        srv._bars.pop(tk, None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del _MATERIALIZED_SNAPSHOTS[key]


def _candle(b: dict) -> Candle:
    return Candle(ts=b["timestamp"] / 1000.0, open=b["open"], high=b["high"], low=b["low"],
                  close=b["close"], volume=b["volume"])


def _rth_high(bars: list[dict], day: str) -> float:
    at = [(_dt.fromtimestamp(b["timestamp"] / 1000.0, ET), b) for b in bars]
    return max(b["high"] for d, b in at if d.date().isoformat() == day and 570 <= d.hour * 60 + d.minute < 960)

# ── RC-213 B1: /api/levels read-adapter contract (mission levels-faucet-v1) ──────────


def test_api_levels_b1_contract_single_session_prior_day():
    """The B1 read-adapter serves the prior_day family from the RC-153 single-session
    authority, with per-level provenance naming the window, unique ids, honest
    families_absent — and never the multi-session union values (the RC-213 defect). A tape of
    tiny sessions tests window selection (their prior day is stamped degraded, and still
    served); stand-in: ticker ZZB1."""
    tk = "ZZB1"

    def _bar(y, mo, d, h, mi, o, hi, lo, c):
        return {"timestamp": int(_dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
                "open": o, "high": hi, "low": lo, "close": c, "volume": 1000.0}

    tape = [
        _bar(2026, 7, 30, 10, 0, 100, 110, 90, 100),   # older prior session: both extremes
        _bar(2026, 7, 30, 14, 0, 100, 101, 99, 100),
        _bar(2026, 7, 31, 10, 0, 96, 105, 95, 97),     # most recent prior session
        _bar(2026, 7, 31, 15, 59, 101, 103, 100, 102),
        _bar(2026, 8, 3, 9, 35, 103, 104, 102, 103),   # today inside ORB window
        _bar(2026, 8, 3, 9, 45, 103, 104, 102, 103),   # today post-ORB
    ]
    now = _dt(2026, 8, 3, 10, 0, tzinfo=ET)
    _forget(tk)
    try:
        for b in tape:
            srv._keep_bar(tk, _candle(b))
        srv._publish_price_levels(tk, now)            # as the bar writer does
        payload = srv.levels_payload(tk, "1", now)
    finally:
        _forget(tk)

    assert payload["schema_version"] == 1
    assert payload["spot"] is None, "Schwab has sent the stand-in no price: absent, never a stand-in value"

    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload (RC-88)"
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95, (
        "prior_day must be the SINGLE most recent prior RTH session"
    )
    assert by_id["PDC"]["price"] == 102
    for lv in payload["levels"]:
        assert lv["price"] not in (110, 90), "multi-session union value served — RC-213 reopened"
        assert "as_of_ts_utc" in lv["staleness"] and "age_sec" in lv["staleness"]
        if lv["family"] == "prior_day":
            assert lv["provenance"]["session_scope"] == "RTH"
            assert "2026-07-31" in lv["provenance"]["window"], (
                "provenance.window must name the literal session used (RC-153)"
            )

    fams = {f["family"] for f in payload["families_absent"]}
    # 2026-09-27: the gamma family is CARRIED from the terrain (one ranked list of levels for the
    # Trade Desk chart), never computed by Tier-B: every gamma row says so in its provenance.
    for lv in payload["levels"]:
        if lv["family"] == "gamma":
            assert lv["provenance"] == {"producer": "terrain_engine.compute_terrain", "carried": True}
    # Tier-B (levels-tierb-session-collapse-v1): session families are served from the engine
    # when today bars exist — not left as soft B1-absent placeholders.
    assert "VWAP" in by_id and by_id["VWAP"]["family"] == "vwap"
    assert "ORB_HIGH" in by_id and by_id["ORB_HIGH"]["family"] == "opening_range"
    assert "TODAY_POC" in by_id and by_id["TODAY_POC"]["family"] == "value_area"
    assert all(f.get("reason") for f in payload["families_absent"])
    assert "vwap" not in fams, "vwap must be served by Tier-B, not declared absent when bars exist"


# ── RC-227: one-faucet closeout locks (mission one-faucet-closeout-v1) ────────────────


def test_strikes_payload_carries_server_side_sums(monkeypatch):
    """STRIP server half: /api/terrain/strikes serves today_side_sums computed against the
    payload's own spot — the one aggregator."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "terrain_cache_get", lambda tk: {
        "_per_strike": {"all": [[95.0, 10.0, 100], [105.0, -4.0, 50]],
                        "near": [], "far": []},
        "spot": 100.0, "computed_ts_utc": 1.0,
    })
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **kw: (100.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(srv, "last_capture_per_day", lambda *a, **k: [])   # no prior day
    resp = srv.get_terrain_strikes(ticker="SPY")
    payload = json.loads(bytes(resp.body))
    ss = payload["today_side_sums"]
    assert ss["gex_below"] == 10.0 and ss["gex_above"] == -4.0
    assert ss["vol_below"] == 100 and ss["vol_above"] == 50
    assert ss["spot_basis"] == 100.0, "sums must be computed against the payload's own spot"


def test_api_levels_prior_day_low_is_the_full_session_min_of_price_bars_1m():
    """t12 (RC-227 residual): the PDL must be the min of the WHOLE prior session. Measured
    live: a truncated in-memory tape served PDL 756.84 vs the true 749.59 while PDH/PDC
    matched. price_bars_1m (written only from Schwab's streamed bars) is the one bar history,
    loaded into the console's memory at startup (server._load_bars), so the full prior session
    there must set every prior-day level. Stand-in: ticker ZZPDL."""
    tk = "ZZPDL"
    # The FULL prior session (390 bars) with the true low 749.59 mid-session.
    t0 = _dt(2026, 8, 3, 9, 30, tzinfo=ET).timestamp()
    session = [Candle(ts=t0 + i * 60, open=756, high=758.58 if i == 200 else 757,
                      low=749.59 if i == 100 else 755.0, close=757.67 if i == 389 else 756, volume=100.0)
               for i in range(390)]
    now = _dt(2026, 8, 4, 10, 0, tzinfo=ET)
    _forget(tk)
    try:
        srv.get_db().upsert_1m_bars(tk, session)
        srv._load_bars()                              # the console's start
        srv._publish_price_levels(tk, now)            # as the bar writer does
        payload = srv.levels_payload(tk, "1", now)
    finally:
        _forget(tk)
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, "PDL is not the full prior session's min"
    assert by_id["PDH"]["price"] == 758.58
    assert by_id["PDC"]["price"] == 757.67
    assert "price_bars_1m" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the one bar source"
    )


def test_the_bar_writer_publishes_the_levels_and_the_route_only_serves_them():
    """The bar writer publishes a ticker's price levels after each of its bars -- every ticker,
    viewed or not, so a page switching to it finds them current; a new session is built by the
    levels loop; the route serves what was published and reads no bar. Real Schwab SPY bars,
    2026-09-24/25, valued on Friday the 25th at 15:00 ET. Stand-ins: ticker ZZWRITE carries the
    SPY bars, ZZWRITE2 (no page views it) one SPY bar."""
    tk, other = "ZZWRITE", "ZZWRITE2"
    now = _dt(2026, 9, 25, 15, 0, tzinfo=ET)
    raw = [b for b in json.loads(_FIXTURE.read_text(encoding="utf-8"))["bars"] if b["timestamp"] / 1000.0 < now.timestamp() - 120]
    last = raw[-1]
    _forget(tk, other)
    try:
        srv.get_db().upsert_1m_bars(tk, [_candle(b) for b in raw[:-1]])
        srv._load_bars()                                                   # the console's start

        # nothing published yet: the levels are absent with their reason
        none_yet = srv.levels_payload(tk, "1", now)
        assert none_yet["generation"] is None
        assert {"family": "price_levels", "reason": srv.NO_PRICE_LEVELS_REASON} in none_yet["families_absent"]

        # a minute's bars arrive together (ZZWRITE, and ZZWRITE2): every bar is written first
        # (each write is pushed as `liquidity`), then each ticker's levels are published from its
        # bars (pushed as `levels`). The order is read from the push itself: its own listener,
        # on a running event loop, with a page open on each ticker.
        changes = []

        def record(t, kind):
            if t in (tk, other):
                changes.append((kind, t))
        loop = asyncio.new_event_loop()
        runner = threading.Thread(target=loop.run_forever, daemon=True)
        runner.start()
        push_changes.bind(loop)
        push_changes.on_change(record)
        pages = [(t, push_changes.subscribe(t)) for t in (tk, other)]
        try:
            srv._write_streamed_bars([
                {"symbol": t, "bar_start_ms": last["timestamp"], "open": last["open"], "high": last["high"],
                 "low": last["low"], "close": last["close"], "volume": last["volume"]} for t in (tk, other)], now)
            drained = threading.Event()
            loop.call_soon_threadsafe(drained.set)
            assert drained.wait(5)
        finally:
            for t, page in pages:
                push_changes.unsubscribe(t, page)
            del push_changes._change_listeners[f"{record.__module__}.{record.__qualname__}"]
            push_changes.bind(None)
            loop.call_soon_threadsafe(loop.stop)
            runner.join(5)
            loop.close()
        assert changes == [("liquidity", tk), ("liquidity", other), ("levels", tk), ("levels", other)]
        served = srv.levels_payload(tk, "1", now)
        assert served["generation"] is not None
        assert served["snapshot_as_of_ts_utc"] == last["timestamp"] / 1000.0
        assert srv.canonical_price_level_snapshot(other, now).as_of_ts_utc == last["timestamp"] / 1000.0
        # the route reads no bar: with the ticker's bars gone from memory it serves the same levels
        srv._bars.pop(tk)
        again = srv.levels_payload(tk, "15", now)
        assert again["generation"] == served["generation"]
        assert [(r["id"], r["price"]) for r in again["levels"]] == [(r["id"], r["price"]) for r in served["levels"]]

        # a new session: the levels loop builds its levels (09-25's bars are its prior day)
        srv.get_db().upsert_1m_bars(tk, [_candle(last)])
        srv._load_bars()
        monday = _dt(2026, 9, 28, 9, 0, tzinfo=ET)
        srv._publish_missing_price_levels([tk], monday)
        nextday = srv.levels_payload(tk, "1", monday)
        assert {lv["id"]: lv["price"] for lv in nextday["levels"]}["PDH"] == _rth_high(raw, "2026-09-25")
    finally:
        _forget(tk, other)


def test_the_console_serves_while_the_levels_loop_waits_for_the_stored_bars():
    """2026-09-28, operator: the console window's start was "slow as molasses": the stored-levels
    load ran before the app served its first request. The levels loop runs on its own thread and
    builds nothing until the bar writer has loaded the stored bars; the console serves
    meanwhile, and once the bars are loaded the loop publishes the board's levels. The real loop
    and the real bar writer, on Schwab's SPY bars of 2026-09-24/25. The loop is started as
    start_terrain_loop starts it (its run flag set, then its thread; start_terrain_loop itself
    refuses to start under pytest) and stopped by stop_terrain_loop. Stand-in: board ticker
    ZZBOARD carries the SPY bars."""
    tk = "ZZBOARD"
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))["bars"]
    _forget(tk)
    srv._bars_loaded.clear()
    srv.get_db().upsert_1m_bars(tk, [_candle(b) for b in raw])
    srv._terrain_loop_running = True
    loop = threading.Thread(target=srv._terrain_loop, daemon=True)
    writer = threading.Thread(target=srv._bar_writer, daemon=True)
    try:
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "board": [tk]})
        loop.start()
        time.sleep(0.6)
        served = srv.levels_payload(tk, "1", now_et())       # the console serves while the loop waits
        assert loop.is_alive() and served["generation"] is None
        writer.start()                                       # the bars load; the loop goes on
        deadline = time.monotonic() + 10
        while srv.canonical_price_level_snapshot(tk, now_et()) is None and time.monotonic() < deadline:
            lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "board": [tk]})
            time.sleep(0.1)
        snap = srv.canonical_price_level_snapshot(tk, now_et())
        assert snap is not None and snap.levels["PDH"].price == _rth_high(raw, "2026-09-25")
    finally:
        srv.stop_terrain_loop()
        if writer.is_alive():
            srv.stop_bar_writer(writer)
        loop.join(5)
        _forget(tk)
