"""The browser tests' panels of a ticker's real two days are the server's own answers.

Real data, read-only from production on 2026-11-12, for AMZN (10:39:18 ET, the Gamma tests') and
SPY (10:30:41 ET, the Trade Desk's): the ticker's last complete capture of 2026-11-11 (the close)
and its complete capture of that instant, every expiry and every row as stored, each with the
chain's spot; its LEVELONE_EQUITIES message the daemon received last before that capture; and
Schwab's /markets answers for the two days. The two captures are stored by the daemon's writer,
read back by the server's reader (last_capture_per_day) and published by the one producer as a
start does, with the quote as the live price: the levels LIVE, a heatmap of every expiry, the
day-over-day migration and the level moves against the prior day's close.

The Trade Desk's panels of the same instant come from the ticker's book messages of the 60 s
before it, its CHART_EQUITY bars of the day and Schwab's newest /pricehistory answers
(tests/fixtures/real_<ticker>_desk_rows_2026_11_12.json.gz), each through the console's own
intake: the book, the liquidity zones, the session's price levels and the forces.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import server
import time_et
from app.options.order_flow import history
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import last_capture_per_day
from stream_spine import book_msg
from tests.capture_store import store_capture
from tests.feed_live_helper import daemon_status
from tests.test_order_flow_book_payload_v1 import _same

_FX = Path(__file__).resolve().parent / "fixtures"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures"
#: Schwab's /markets answers for the two days, as stored
_MARKETS = [
    json.loads((_FX / f"real_schwab_markets_{day}.json").read_text(encoding="utf-8"))["body"]
    for day in ("2026_11_11", "2026_11_12")
]
#: the window a page asks: Auto, following the price
AUTO = {"scope": "auto", "centre": None, "shift": 0}
#: a date Schwab lists no expiry on in those chains (a Saturday)
MISSING_EXPIRY = "2026-11-14"
#: the Trade Desk's timeframe
TF = "30"


@dataclass(frozen=True)
class RealSet:
    """One ticker's captured two days, quote and desk rows, and the browser tests' file of them."""

    ticker: str
    captures: list
    quote: dict
    #: the book messages, the day's bars and the price-history answers, each row as stored
    desk: dict
    panels: Path

    @property
    def venues(self) -> list[str]:
        """The books Schwab streamed for the ticker, the desk's default first."""
        return sorted({row["service"] for row in self.desk["book"]})


def _load(name: str) -> RealSet:
    def gz(part: str) -> dict:
        return json.loads(
            gzip.decompress((_FX / f"real_{name}_{part}_2026_11_12.json.gz").read_bytes())
        )

    two_days = gz("two_day_captures")
    return RealSet(
        server.ticker_storage_key(two_days["ticker"]),
        two_days["captures"],
        json.loads((_FX / f"real_{name}_quote_2026_11_12.json").read_text(encoding="utf-8")),
        gz("desk_rows"),
        _E2E / f"panels_{name}_two_day.json",
    )


AMZN = _load("amzn")
SPY = _load("spy")
SETS = pytest.mark.parametrize("real", [AMZN, SPY], ids=lambda real: real.ticker)


def _clear(tk: str) -> None:
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._gamma_surface_seq.pop(tk, None)
    with server._bars_lock:
        server._bars.pop(tk, None)
        for key in [k for k in server._series if k[0] == tk]:
            del server._series[key]
    for key in [k for k in server._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
        del server._MATERIALIZED_SNAPSHOTS[key]
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_down()
    ofls.clear_all_live_state()
    history.LEAN.forget(tk)


def build_e2e_panels(real: RealSet, folder: Path) -> dict:
    """Return the panels of the ticker's real two days as the page's socket sends them.

    `folder` holds the database the two captures are stored in. At the newer capture's instant:
    the strikes in the Auto and Wider windows, the levels (terrain), the heatmap (surface, Auto,
    every column and expiry; and asked for an expiry the chain does not list), the front
    expiry's chain, and the Trade Desk's book of each venue, liquidity zones, price levels,
    attention queue and forces. Regenerate the browser tests' files with write_e2e_panels.
    """
    tk = real.ticker
    db = folder / "ed_console.db"
    for capture in real.captures:
        for row in capture["rows"]:
            store_capture(
                db,
                ticker=tk,
                expiry=row["expiry"],
                contracts=row["contracts"],
                spot=row["spot"],
                completeness_basis=capture["completeness_basis"],
                ts_utc=capture["ts_utc"],
                source=capture["source"],
                chain_spot=capture["chain_spot"],
                chain_spot_ts=capture["chain_spot_ts"],
            )
    captures = last_capture_per_day(db, tk, 2)
    # one instant for every reader, the newer capture's (a datetime keeps microseconds)
    now = datetime.fromtimestamp(captures[0]["ts_utc"], time_et.ET)
    at = now.timestamp()
    held = time_et._sessions
    time_et._sessions = {}  # the two days' own answers, whatever else a test run holds
    _clear(tk)
    try:
        for answer in _MARKETS:
            time_et.record_markets(answer)
        lmp.record_from_level_one_equity(
            tk, real.quote["native"], received_ts=real.quote["ts_recv"]
        )
        lmp.record_feed_heartbeat(
            daemon_status(
                at,
                schwab_socket_open=True,
                held={"LEVELONE_EQUITIES": [tk], **{venue: [tk] for venue in real.venues}},
            )
        )
        for row in real.desk["book"]:
            ofs._ingest_pushed(
                f"book.{tk}",
                book_msg(
                    symbol=tk,
                    service=row["service"],
                    content=row["native"],
                    src=row["src"],
                    ts_recv=row["ts_recv"],
                ),
            )
        # the bar writer's own entry: Schwab's price histories, then the day's streamed bars
        server._write_streamed_bars(
            [
                {
                    "src": row["src"],
                    "symbol": tk,
                    "series": row["series"],
                    "ts_recv": row["ts_recv"],
                    "answer": row["native"],
                }
                for row in real.desk["pricehistory"]
            ]
            + real.desk["bars"],
            now,
        )
        server._publish_levels(tk, captures=captures, now=now)
        return json.loads(
            json.dumps(
                {
                    "strikes": server.strikes(tk, at, AUTO),
                    "strikes_wider": server.strikes(tk, at, {**AUTO, "scope": "wider"}),
                    "terrain": server.terrain(tk, at),
                    "surface": server.gamma_surface(tk, at, {**AUTO, "cols": None, "expiry": None}),
                    "surface_missing_expiry": server.gamma_surface(
                        tk, at, {**AUTO, "cols": None, "expiry": MISSING_EXPIRY}
                    ),
                    "chain": server.chain(tk, at, {"expiry": None}),
                    "book": {venue: server.book(tk, at, {"venue": venue}) for venue in real.venues},
                    "liquidity": server.liquidity_snapshot(tk, now),
                    "levels": server.levels_payload(tk, TF, now),
                    "desk": server.desk_events_payload(tk, real.venues[0], TF, now),
                    "forces": server.forces(tk),
                }
            )
        )
    finally:
        _clear(tk)
        time_et._sessions = held


def write_e2e_panels() -> None:
    """Regeneration utility (never called by a test).

    python -c "import tests.conftest, tests.test_e2e_panels_two_day_v1 as t; t.write_e2e_panels()"
    """
    for real in (AMZN, SPY):
        with tempfile.TemporaryDirectory() as folder:
            real.panels.write_text(
                json.dumps(build_e2e_panels(real, Path(folder)), indent=1), encoding="utf-8"
            )


@SETS
def test_the_browser_tests_two_day_panels_are_the_producers_own(real, tmp_path):
    panels = build_e2e_panels(real, tmp_path)
    # every key and value; a float to 1e-9 relative (a sum over 13,000 contracts differs in its
    # last digit between Windows, where the file is written, and Linux)
    assert _same(json.loads(real.panels.read_text(encoding="utf-8")), panels), (
        "the browser tests' file drifted from the server; regenerate with write_e2e_panels()"
    )
    # what the set is for: a live screen, several expiries, a prior day compared
    gamma = ("strikes", "strikes_wider", "terrain", "surface", "surface_missing_expiry", "chain")
    assert {panels[name]["levels_state"] for name in gamma} == {"LIVE"}
    assert panels["surface_missing_expiry"]["view"]["missing_expiry"] == MISSING_EXPIRY
    assert len(panels["surface"]["expirations"]) == len(real.captures[1]["rows"])
    assert panels["strikes"]["migration"]["all"]["compared"] is True
    assert panels["terrain"]["spot"] == real.quote["native"]["LAST_PRICE"]
    # the desk: Schwab's books at the price, zones and session levels built from its bars
    assert {book["status"] for book in panels["book"].values()} == {"ok"}
    assert panels["liquidity"]["zones"]
    assert panels["levels"]["generation"] is not None
    assert panels["forces"]["older_et_date"] == "2026-11-11"
