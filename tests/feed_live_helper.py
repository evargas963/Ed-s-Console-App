"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import StoredCapture
from db import LevelCrossEvent, StoredCross
from option_contract import read_chain
from state import bar_store, price_level_store
from stream_spine import CAPTURE_STORED, CaptureWriter, HealthRegistry, MessageBus

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def recorder(db_path: Path | str) -> CaptureWriter:
    """Bind the console to a daemon whose Recorder writes to `db_path`, as capture.run binds it.

    The Recorder's thread is not started, so each store is written at once on a connection of
    its own (CaptureWriter._write_alone).
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), [])
    daemon.writer = CaptureWriter(db_path)
    ofs.bind_daemon(daemon)
    return daemon.writer


def stored_crosses(writer: CaptureWriter, events: list[LevelCrossEvent]) -> list[StoredCross]:
    """Store `events` through the Recorder, as server._log_level_crosses stores a price's.

    Returns the rows as stored, each with its cross_id.
    """
    msg = {"ticker": events[0].ticker, "ts_utc": events[0].ts_utc}
    outcome, ids = writer.store_crosses({**msg, "crosses": [asdict(e) for e in events]}, 10.0)
    assert outcome == CAPTURE_STORED, outcome
    return [StoredCross(**asdict(e), cross_id=i) for e, i in zip(events, ids, strict=True)]


def daemon_status(now: float, **staged) -> dict:
    """Return a capture daemon's status at `now` as the daemon builds it.

    The daemon builds it in capture.Daemon.status: every key it sends, with the `staged` keys
    set: the socket, the symbols held, the watchlist.
    """
    return {**capture.Daemon(MessageBus(), HealthRegistry(), []).status(now), **staged}


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """Return the capture daemon's recorded receipts of Schwab's CHART_EQUITY bars.

    They are read from fixture `name` (tests/fixtures/real_daemon_bars_*.json), of `symbols`
    (every symbol when none is named).
    """
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def newest_bars(rows: list[dict], tk: str) -> list[dict]:
    """Schwab's newest receipt of each minute of `tk`, in time order."""
    out = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        if r["symbol"] == tk:
            out[r["bar_start_ms"]] = r
    return [out[ms] for ms in sorted(out)]


def forget_bars(*tickers: str) -> None:
    """No bar in memory or published level of `tickers` is left behind."""
    for tk in tickers:
        bar_store._bars.pop(tk, None)
        bar_store._series.pop((tk, "1d"), None)
        for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del price_level_store._MATERIALIZED_SNAPSHOTS[key]


def spy_minutes() -> list[dict]:
    """Return Schwab's SPY 1-minute bars of 2026-09-24 and 09-25, regular hours, oldest first.

    They are in the shape the console's roll-up takes. Schwab sent no volume for the last minute
    (09-25 15:59 ET).
    """
    bars = json.loads(
        (_FIXTURES / "real_spy_1m_bars_2026_09_24_25.json").read_text(encoding="utf-8")
    )["bars"]
    return [
        {
            "t": b["timestamp"] / 1000,
            "o": b["open"],
            "h": b["high"],
            "l": b["low"],
            "c": b["close"],
            "v": b["volume"],
        }
        for b in bars
    ]


def stream_daemon_bars(rows: list[dict]) -> None:
    """Push Schwab's bars as the capture daemon does.

    Each captured receipt goes, in the order the daemon received them, through the console's own
    streamed-bar writer (server._write_streamed_bar), so each minute holds Schwab's newest bar for
    it.
    """
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        server._write_streamed_bar(r)


def price_history(symbol: str, series: str) -> dict:
    """Schwab's captured /pricehistory answer for `symbol`'s `series` ("1m", "15m", "1d").

    Read from tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json: {params, status, date,
    sent_utc, answered_utc, body}.
    """
    fx = json.loads(
        (_FIXTURES / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8")
    )
    return next(a for a in fx["answers"] if a["symbol"] == symbol and a["series"] == series)


def hold_schwab_daily(symbol: str, under: str | None = None) -> None:
    """Push `symbol`'s daily candles as the daemon does.

    They go through the console's own writer (server._write_price_history), held under ticker
    `under` (default `symbol`): Schwab's recorded /pricehistory daily answer, SPY's and TSLA's of
    2026-10-07 (real_pricehistory_spy_tsla_2026_10_07.json), $SPX's of 2026-11-03
    (real_schwab_daily_spx_2026_10.json, 2024-11-04 through 2026-11-02). The caller pops
    state.bar_store's series when done, as it pops state.bar_store's bars.
    """
    if symbol == "$SPX":
        sent = json.loads(
            (_FIXTURES / "real_schwab_daily_spx_2026_10.json").read_text(encoding="utf-8")
        )["message"]
    else:
        sent = price_history(symbol, "1d")["body"]
    server._write_price_history({"symbol": under or symbol, "series": "1d", "answer": sent})


def schwab_daily(symbol: str) -> list:
    """`symbol`'s daily candles as the bar writer holds them (hold_schwab_daily), taken out."""
    hold_schwab_daily(symbol)
    try:
        return list(bar_store._series[(symbol, "1d")])
    finally:
        bar_store._series.pop((symbol, "1d"), None)


#: Wednesday 2026-09-30, 11:00 ET: regular hours in Schwab's /markets answer held for that date
#: (tests/conftest.py MARKETS_ANSWERS), the instant a live-feed test is judged at, whatever day it
#: runs
RTH_INSTANT = 1790780400.0


def clock_from(start: float):
    """Return a clock running from `start`, time still passing.

    It is what a test hands the code it calls as `now`.
    """
    began = time_et.elapsed()
    return lambda: start + time_et.elapsed() - began


#: a round of the watchlist's chains as the daemon's log of 2026-11-06 reports it (245 s): the round
#: a running daemon's heartbeat carries, which the levels are judged by
ROUND_SEC = 245.0


def mark_feed_live(*tickers: str, now: float | None = None) -> None:
    """Record the daemon's heartbeat stamped `now`, holding `tickers` on LEVELONE_EQUITIES.

    `now` is the wall clock when not given; the daemon reports its last round (ROUND_SEC).
    """
    lmp.record_feed_heartbeat(
        daemon_status(
            time_et.now() if now is None else now,
            schwab_socket_open=True,
            held={"LEVELONE_EQUITIES": list(tickers)},
            chain_round_sec=ROUND_SEC,
        )
    )


def mark_feed_down() -> None:
    lmp.record_feed_down()


def publish_capture(
    tk: str, chain: list, ts_utc: float, spot: float, et_date: str, now: datetime
) -> None:
    """`chain` published for `tk` as the stored capture it is, at the price Schwab sent in it."""
    server._publish_levels(
        tk,
        captures=[
            StoredCapture(
                contracts=read_chain(chain),
                ts_utc=ts_utc,
                spot=spot,
                et_date=et_date,
                basis=server.CAPTURE_BASIS,
                spot_ts=None,
            )
        ],
        now=now,
    )
