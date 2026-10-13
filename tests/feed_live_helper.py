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


def daemon_holds(at: float, held: dict, *, socket_open: bool = True) -> None:
    """The daemon's heartbeat stamped `at`, holding `held` ({Schwab service: [symbols]}), as the
    console's feed loop applies it (streaming._apply_heartbeat)."""
    from app.options.order_flow import streaming as ofs
    ofs._apply_heartbeat({"ts": at, "schwab_socket_open": socket_open, "held": held})


def through_the_daemons_bus(bus, sym: str, ticks: list, ts: "list[float] | None" = None) -> None:
    """Each LEVELONE_OPTIONS tick of `sym` (received at `ts`, else 1000 s on) published on the
    daemon's bus (stream_spine.MessageBus), and its current record (every field Schwab has sent,
    the last of each: Streamer API §1.1, Change) pushed to the console as the daemon pushes it."""
    from app.options.order_flow import streaming as ofs
    from stream_spine import current_key, options_quote_msg
    for i, tick in enumerate(ticks):
        topic, msg = f"optquote.{sym}", options_quote_msg(
            symbol=sym, content={"key": sym, **tick}, src="schwab_options_l1",
            ts_recv=ts[i] if ts is not None else 1000.0 + i)
        bus.publish(topic, msg)
        ofs._ingest_pushed(topic, bus.current[current_key(topic, msg)][1])


def no_daemon() -> None:
    """No daemon: it holds nothing (every contract it held released) and nothing is live."""
    daemon_holds(0.0, {})
    lmp.record_feed_down()


def publish_daemon_rows(*tickers: str) -> None:
    """What the daemon's price push hands the console: its price row per ticker, built by the
    daemon's own function from the daemon's plane (the test's live_market_plane stands in for
    the daemon's)."""
    import live_price_rows
    from app.options.order_flow import streaming as ofs
    for tk in tickers:
        row = live_price_rows.price_row(tk, time.time())
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
