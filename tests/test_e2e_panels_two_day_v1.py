"""The browser tests' panels of AMZN's real two days are the server's own answers.

Real data, read-only from production on 2026-11-12: AMZN's last complete capture of 2026-11-11
(the close, 16:17:36 ET) and its complete capture of 2026-11-12 10:39:18 ET, every expiry (24)
and every row as stored, each with the chain's spot; AMZN's LEVELONE_EQUITIES message the
daemon received last before that capture (LAST_PRICE 269.425); and Schwab's /markets answers
for the two days. The two captures are stored by the daemon's writer, read back by the server's
reader (last_capture_per_day) and published by the one producer as a start does, with the quote
as the live price: the levels LIVE, a heatmap of 24 expiries, the day-over-day migration and the
level moves against the prior day's close.

The Trade Desk's panels of the same instant come from AMZN's NASDAQ_BOOK messages of the 60 s
before it, its CHART_EQUITY bars of the day and Schwab's newest /pricehistory answers
(tests/fixtures/real_amzn_desk_rows_2026_11_12.json.gz), each through the console's own intake:
the book, the liquidity zones, the session's price levels and the forces.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from datetime import datetime
from pathlib import Path

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

_FX = Path(__file__).resolve().parent / "fixtures"
#: the book messages, the day's bars and the price-history answers, each row as stored
_DESK = json.loads(gzip.decompress((_FX / "real_amzn_desk_rows_2026_11_12.json.gz").read_bytes()))
#: the one book Schwab streams for AMZN, a Nasdaq listing
VENUE = "NASDAQ_BOOK"
#: the Trade Desk's timeframe
TF = "30"
_SET = json.loads(
    gzip.decompress((_FX / "real_amzn_two_day_captures_2026_11_12.json.gz").read_bytes())
)
_QUOTE = json.loads((_FX / "real_amzn_quote_2026_11_12.json").read_text(encoding="utf-8"))
#: Schwab's /markets answers for the two days, as stored
_MARKETS = [
    json.loads((_FX / f"real_schwab_markets_{day}.json").read_text(encoding="utf-8"))["body"]
    for day in ("2026_11_11", "2026_11_12")
]
TK = server.ticker_storage_key(_SET["ticker"])
#: the window a page asks: Auto, following the price
AUTO = {"scope": "auto", "centre": None, "shift": 0}
#: a date Schwab lists no AMZN expiry on in that chain (a Saturday)
MISSING_EXPIRY = "2026-11-14"
E2E_PANELS = Path(__file__).resolve().parent / "e2e" / "fixtures" / "panels_amzn_two_day.json"


def _clear():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    server._gamma_surface_seq.pop(TK, None)
    with server._bars_lock:
        server._bars.pop(TK, None)
        for key in [k for k in server._series if k[0] == TK]:
            del server._series[key]
    for key in [k for k in server._MATERIALIZED_SNAPSHOTS if k[0] == TK]:
        del server._MATERIALIZED_SNAPSHOTS[key]
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_down()
    ofls.clear_all_live_state()
    history.LEAN.forget(TK)


def build_e2e_panels(folder: Path) -> dict:
    """Return the panels of AMZN's real two days as the page's socket sends them.

    `folder` holds the database the two captures are stored in. At the newer capture's instant:
    the strikes in the Auto and Wider windows, the levels (terrain), the heatmap (surface, Auto,
    every column and expiry; and asked for an expiry the chain does not list), the front
    expiry's chain, and the Trade Desk's book, liquidity zones, price levels, attention queue
    and forces. Regenerate the browser tests' file with write_e2e_panels.
    """
    db = folder / "ed_console.db"
    for capture in _SET["captures"]:
        for row in capture["rows"]:
            store_capture(
                db,
                ticker=TK,
                expiry=row["expiry"],
                contracts=row["contracts"],
                spot=row["spot"],
                completeness_basis=capture["completeness_basis"],
                ts_utc=capture["ts_utc"],
                source=capture["source"],
                chain_spot=capture["chain_spot"],
                chain_spot_ts=capture["chain_spot_ts"],
            )
    captures = last_capture_per_day(db, TK, 2)
    # one instant for every reader, the newer capture's (a datetime keeps microseconds)
    now = datetime.fromtimestamp(captures[0]["ts_utc"], time_et.ET)
    at = now.timestamp()
    held = time_et._sessions
    time_et._sessions = {}  # the two days' own answers, whatever else a test run holds
    _clear()
    try:
        for answer in _MARKETS:
            time_et.record_markets(answer)
        lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
        lmp.record_feed_heartbeat(
            daemon_status(
                at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [TK], VENUE: [TK]}
            )
        )
        for row in _DESK["book"]:
            ofs._ingest_pushed(
                f"book.{TK}",
                book_msg(
                    symbol=TK,
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
                    "symbol": TK,
                    "series": row["series"],
                    "ts_recv": row["ts_recv"],
                    "answer": row["native"],
                }
                for row in _DESK["pricehistory"]
            ]
            + _DESK["bars"],
            now,
        )
        server._publish_levels(TK, captures=captures, now=now)
        return json.loads(
            json.dumps(
                {
                    "strikes": server.strikes(TK, at, AUTO),
                    "strikes_wider": server.strikes(TK, at, {**AUTO, "scope": "wider"}),
                    "terrain": server.terrain(TK, at),
                    "surface": server.gamma_surface(TK, at, {**AUTO, "cols": None, "expiry": None}),
                    "surface_missing_expiry": server.gamma_surface(
                        TK, at, {**AUTO, "cols": None, "expiry": MISSING_EXPIRY}
                    ),
                    "chain": server.chain(TK, at, {"expiry": None}),
                    "book": server.book(TK, at, {"venue": VENUE}),
                    "liquidity": server.liquidity_snapshot(TK, now),
                    "levels": server.levels_payload(TK, TF, now),
                    "desk": server.desk_events_payload(TK, VENUE, TF, now),
                    "forces": server.forces(TK),
                }
            )
        )
    finally:
        _clear()
        time_et._sessions = held


def write_e2e_panels() -> None:
    """Regeneration utility (never called by a test).

    python -c "import tests.conftest, tests.test_e2e_panels_two_day_v1 as t; t.write_e2e_panels()"
    """
    with tempfile.TemporaryDirectory() as folder:
        E2E_PANELS.write_text(
            json.dumps(build_e2e_panels(Path(folder)), indent=1), encoding="utf-8"
        )


def test_the_browser_tests_two_day_panels_are_the_producers_own(tmp_path):
    panels = build_e2e_panels(tmp_path)
    assert json.loads(E2E_PANELS.read_text(encoding="utf-8")) == panels
    # what the set is for: a live screen, several expiries, a prior day compared
    gamma = ("strikes", "strikes_wider", "terrain", "surface", "surface_missing_expiry", "chain")
    assert {panels[name]["levels_state"] for name in gamma} == {"LIVE"}
    # the desk: Schwab's book at the price, zones and session levels built from its bars
    assert panels["book"]["status"] == "ok"
    assert panels["liquidity"]["zones"]
    assert panels["levels"]["generation"] is not None
    assert panels["forces"]["older_et_date"] == "2026-11-11"
    assert panels["surface_missing_expiry"]["view"]["missing_expiry"] == MISSING_EXPIRY
    assert len(panels["surface"]["expirations"]) == len(_SET["captures"][1]["rows"])
    assert panels["strikes"]["migration"]["all"]["compared"] is True
    assert panels["terrain"]["spot"] == _QUOTE["native"]["LAST_PRICE"]
