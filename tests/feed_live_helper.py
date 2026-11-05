"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""

from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import time_et

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """The capture daemon's recorded receipts of Schwab's CHART_EQUITY bars in fixture `name`
    (tests/fixtures/real_daemon_bars_*.json), of `symbols` (every symbol when none is named)."""
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def stream_daemon_bars(rows: list[dict]) -> None:
    """What the capture daemon pushes of Schwab's bars: each captured receipt, in the order the
    daemon received them, through the console's own streamed-bar writer
    (server._write_streamed_bar), so each minute holds Schwab's newest bar for it."""
    import server

    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        server._write_streamed_bar(r)


def price_history(symbol: str, series: str) -> dict:
    """Schwab's captured /pricehistory answer for `symbol`'s `series` ("1m", "15m", "1d")
    (tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json): {params, status, date, sent_utc,
    answered_utc, body}."""
    fx = json.loads(
        (_FIXTURES / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8")
    )
    return next(a for a in fx["answers"] if a["symbol"] == symbol and a["series"] == series)


#: Wednesday 2026-09-30, 11:00 ET: regular hours in Schwab's /markets answer held for that date
#: (tests/conftest.py MARKETS_ANSWERS), the instant a live-feed test is judged at, whatever day it
#: runs
RTH_INSTANT = 1790780400.0


def clock_from(start: float):
    """A clock running from `start`, time still passing: what a test hands the code it calls as
    `now`."""
    began = time_et.elapsed()
    return lambda: start + time_et.elapsed() - began


def mark_feed_live(*tickers: str, now: float | None = None) -> None:
    """The daemon's heartbeat stamped `now` (the wall clock when not given), holding `tickers` on
    LEVELONE_EQUITIES."""
    lmp.record_feed_heartbeat(
        {
            "ts": time_et.now() if now is None else now,
            "schwab_socket_open": True,
            "held": {"LEVELONE_EQUITIES": list(tickers)},
        }
    )


def mark_feed_down() -> None:
    lmp.record_feed_down()


def feed_live_during(monkeypatch, *tickers: str) -> None:
    """For route tests that start the app (TestClient): the daemon's heartbeat holding `tickers`
    for the whole test."""
    mark_feed_live(*tickers)
    # importing/starting the app can take longer than the 3 s heartbeat bound on a loaded CI
    # worker; heartbeat AGE is not what these tests exercise (it has its own tests)
    monkeypatch.setattr(lmp, "FEED_HEARTBEAT_MAX_AGE_SEC", 3600.0)
