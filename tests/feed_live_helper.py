"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import live_push
from calibration.complete_chain_capture import ensure_schema, persist_complete_chain_capture
from db import get_db
from instrument_identity import ticker_storage_key
from stream_spine import LATEST, MessageBus
from time_et import ET

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_rows(name: str) -> list[dict]:
    """The `rows` of tests/fixtures/`name` (a fixture captured with a provenance block)."""
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]


def schwab_rth_bars(rows: list[dict], symbol: str, day: date) -> list[dict]:
    """Of the daemon's recorded CHART_EQUITY receipts `rows`, Schwab's newest bar for each
    regular-session minute (09:30-16:00 ET) of `day`, in time order."""
    newest = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        if r["symbol"] == symbol:
            newest[r["bar_start_ms"]] = r
    out = []
    for ms, r in sorted(newest.items()):
        t = datetime.fromtimestamp(ms / 1000, ET)
        if t.date() == day and (9, 30) <= (t.hour, t.minute) < (16, 0):
            out.append(r)
    return out


def vwap_by_definition(bars: list[dict]) -> list[list]:
    """Session VWAP after each bar, [bar start (s), vwap, +1sd, -1sd, +2sd, -2sd]. VWAP =
    cumulative(typical price x volume) / cumulative(volume), typical price = (high + low + close) / 3
    (TradingView, "Volume Weighted Average Price (VWAP)", support article 43000502018, its five
    calculation steps). The bands: VWAP +- k x the volume-weighted standard deviation of the typical
    price about the VWAP, sqrt(cumulative(tp^2 x v) / cumulative(v) - VWAP^2) (the form is
    NOT_PROVEN against a primary source). A bar with no volume adds nothing and makes no point."""
    out, tpv, v, tp2v = [], 0.0, 0.0, 0.0
    for b in bars:
        if b["volume"] is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        tpv, v, tp2v = tpv + tp * b["volume"], v + b["volume"], tp2v + tp * tp * b["volume"]
        if v > 0:
            w = tpv / v
            sd = max(0.0, tp2v / v - w * w) ** 0.5
            out.append([b["bar_start_ms"] / 1000, w, w + sd, w - sd, w + 2 * sd, w - 2 * sd])
    return out


def store_chain_capture(row: dict) -> None:
    """One captured chain row (complete_chain_captures, as fixtured) into this run's console
    database, through the chain sweep's own writer."""
    assert persist_complete_chain_capture(
        get_db().db_path, ticker=row["ticker"], expiry=row["expiry"], contracts=row["chain"],
        spot=row["spot"], completeness_basis=row["completeness_basis"], ts_utc=row["ts_utc"],
        source=row["source"])["status"] == "written"


def forget_chain_captures(rows: list[dict]) -> None:
    """Remove exactly those captures from this run's console database, and each ticker's published
    levels (a test leaves nothing)."""
    with sqlite3.connect(str(get_db().db_path)) as con:
        ensure_schema(con)
        con.executemany("DELETE FROM complete_chain_captures WHERE ticker=? AND ts_utc=?",
                        [(r["ticker"], r["ts_utc"]) for r in rows])
    with server._terrain_cache_lock:
        for r in rows:
            server._terrain_cache.pop(ticker_storage_key(r["ticker"]), None)


async def _through_push(msgs: list[tuple[str, dict]]) -> list[dict]:
    bus = MessageBus()
    sub = bus.subscribe("", policy=LATEST)
    frames = []
    for topic, msg in msgs:
        bus.publish(topic, msg)
        while sub.changed:
            t, record = await sub.get()
            if live_push.is_forwarded(t, record):
                frames.extend(json.loads(f) for f in live_push.frames(t, record))
    return frames


def deliver_through_push(msgs: list[tuple[str, dict]]) -> None:
    """The daemon's messages `msgs` ((topic, message), built by stream_spine's builders) published on
    the daemon's bus, each record its LATEST reader hands the push sent as the push's wire frames
    (live_push.frames), and each frame taken by the console's intake (streaming._ingest_pushed)."""
    for frame in asyncio.run(_through_push(msgs)):
        ofs._ingest_pushed(frame["topic"], frame["msg"])


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """The capture daemon's recorded receipts of Schwab's CHART_EQUITY bars in fixture `name`
    (tests/fixtures/real_daemon_bars_*.json), of `symbols` (every symbol when none is named)."""
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def record_daemon_bars(rows: list[dict]) -> None:
    """What the capture daemon records of Schwab's bars: each captured receipt, as captured,
    through the daemon's own writer (stream_spine.CaptureWriter) into this run's stream_capture.db."""
    from stream_spine import CaptureWriter, bar_msg
    writer = CaptureWriter()
    with sqlite3.connect(str(writer.db_path), timeout=30.0) as con:
        for r in rows:
            writer.insert(f"bar1m.{r['symbol']}", bar_msg(
                symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"], native=r["native"],
                schwab_ts=r["schwab_ts"]), conn=con)


def forget_daemon_bars(rows: list[dict]) -> None:
    """Remove exactly those receipts from this run's stream_capture.db (a test leaves nothing)."""
    from db_authority import canonical_stream_db_path
    path = canonical_stream_db_path()
    if not path.exists():
        return
    with sqlite3.connect(str(path), timeout=30.0) as con:
        con.executemany("DELETE FROM stream_bars_raw WHERE symbol=? AND bar_start_ms=? AND ts_recv=?",
                        [(r["symbol"], r["bar_start_ms"], r["ts_recv"]) for r in rows])


def mark_feed_live(*tickers: str) -> None:
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": list(tickers)}})


def mark_feed_down() -> None:
    lmp.record_feed_down()


def publish_daemon_rows(*tickers: str) -> None:
    """What the daemon's price push hands the console: its price row per ticker, built by the
    daemon's own function from the daemon's plane (the test's live_market_plane stands in for
    the daemon's)."""
    import live_price_rows
    from app.options.order_flow import streaming as ofs
    for tk in tickers:
        row = live_price_rows.price_row(tk)
        ofs._price_rows[row["ticker"]] = row


def feed_live_during(monkeypatch, *tickers: str) -> None:
    """For route tests that start the app (TestClient): the app's own push feed loop cannot
    reach a daemon in CI and marks the feed down on every retry, racing the test. Hold the
    feed live for this test by stubbing that mark-down; the feed loop's own behaviour is
    covered end-to-end in tests/test_live_push_channel_v1.py."""
    mark_feed_live(*tickers)
    monkeypatch.setattr(lmp, "record_feed_down", lambda: None)
    # importing/starting the app can take longer than the 3 s heartbeat bound on a loaded CI
    # worker; heartbeat AGE is not what these tests exercise (it has its own tests)
    monkeypatch.setattr(lmp, "FEED_HEARTBEAT_MAX_AGE_SEC", 3600.0)
