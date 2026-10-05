"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import live_market_plane as lmp

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


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
