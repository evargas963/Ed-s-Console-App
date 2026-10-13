"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import json
import time
from pathlib import Path

import live_market_plane as lmp

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """The capture daemon's recorded receipts of Schwab's CHART_EQUITY bars in fixture `name`
    (tests/fixtures/real_daemon_bars_*.json), of `symbols` (every symbol when none is named)."""
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def stream_daemon_bars(rows: list[dict]) -> None:
    """What the capture daemon pushes of Schwab's bars: each captured receipt, in the order the
    daemon received them, through the console's own streamed-bar writer (server._write_streamed_bar),
    so each minute holds Schwab's newest bar for it."""
    import server
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        server._write_streamed_bar(r)


def price_history(symbol: str, series: str) -> dict:
    """Schwab's captured /pricehistory answer for `symbol`'s `series` ("1m", "15m", "1d")
    (tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json): {params, status, date, sent_utc,
    answered_utc, body}."""
    fx = json.loads((_FIXTURES / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8"))
    return next(a for a in fx["answers"] if a["symbol"] == symbol and a["series"] == series)


def mark_feed_live(*tickers: str) -> None:
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": list(tickers)}})


def mark_feed_down() -> None:
    lmp.record_feed_down()


def price_sent(ticker: str, price: float, trade_ts: float) -> None:
    """The LEVELONE_EQUITIES fields the daemon's Schwab push hands the console for `ticker` (its
    last trade and trade time), taken into the console's price record as _rows_loop takes them.
    STAND-IN: the price and trade time are the test's."""
    lmp.record_from_level_one_equity(ticker, {"LAST_PRICE": price, "TRADE_TIME_MILLIS": int(trade_ts * 1000)},
                                     received_ts=trade_ts)


def forget_price(ticker: str) -> None:
    """The console holds no price for `ticker`."""
    lmp._by_ticker.pop(ticker, None)
    lmp._fields_by_ticker.pop(ticker, None)


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
