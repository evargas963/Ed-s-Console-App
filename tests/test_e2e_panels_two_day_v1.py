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
intake: the book, the liquidity zones and the session's price levels.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from dataclasses import dataclass, fields
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
from db import StoredCross
from push import bars as push_bars
from push import book as push_book
from push import chain as push_chain
from push import desk as push_desk
from push import levels as push_levels
from push import liquidity as push_liquidity
from push import strikes as push_strikes
from push import surface as push_surface
from push import tape as push_tape
from push import terrain as push_terrain
from state import bar_store, cross_store, level_store, price_level_store
from stream_spine import book_msg
from tests.capture_store import store_capture
from tests.feed_live_helper import ROUND_SEC, daemon_status
from tests.test_order_flow_book_payload_v1 import _same

_FX = Path(__file__).resolve().parent / "fixtures"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures"
#: Schwab's /markets answers for the two days, as stored
_MARKETS = [
    json.loads((_FX / f"real_schwab_markets_{day}.json").read_text(encoding="utf-8"))["body"]
    for day in ("2026_11_11", "2026_11_12")
]
#: the window a page asks: Auto, following the price, at All Expirations
AUTO = {"scope": "auto", "centre": None, "shift": 0, "expiry": None}
#: a date Schwab lists no expiry on in those chains (a Saturday)
MISSING_EXPIRY = "2026-11-14"
#: the timeframes the browser tests' charts draw (the Gamma chart opens at 1 minute, the desk and
#: the liquidity map at 5; the tests switch to 15), each with the bars a chart asks for at it
#: (static/js/ed-tv-chart.js BARS_LIMIT), and the flow card's ask (ed-trade-desk-map.js FLOW_BARS)
CHART_TFS = {"1": 1200, "5": 3000, "15": 6000}
#: the desk's own two: its queue is asked at the chart's timeframe
DESK_TFS = ("5", "15")
FLOW_BARS = {"tf": "1", "limit": 60}
#: a chart span shorter than the desk's 15-minute window: the newest hour of 1-minute bars
NEWEST_HOUR = 60


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
    with level_store._lock:
        level_store._levels.pop(tk, None)
    server._gamma_surface_seq.pop(tk, None)
    with bar_store._lock:
        bar_store._bars.pop(tk, None)
        for key in [k for k in bar_store._series if k[0] == tk]:
            del bar_store._series[key]
    for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
        del price_level_store._MATERIALIZED_SNAPSHOTS[key]
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_down()
    ofls.clear_all_live_state()
    history.LEAN.forget(tk)
    with cross_store._lock:
        cross_store._crosses.pop(tk, None)


def build_e2e_panels(real: RealSet, folder: Path) -> dict:
    """Return the panels of the ticker's real two days as the page's socket sends them.

    `folder` holds the database the two captures are stored in. At the newer capture's instant:
    the strikes in the Auto and Wider windows, the levels (terrain), the heatmap (surface, Auto,
    every column and expiry; and asked for an expiry the chain does not list), the front and
    the second expiry's chains, and the Trade Desk's book of each venue and liquidity zones,
    and at each of its timeframes the bars, the price levels and the attention queue
    (the day's level crosses held as a start loads them). Regenerate the browser tests' files with
    write_e2e_panels.
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
                chain_spot=capture["chain_spot"],
                chain_spot_ts=capture["chain_spot_ts"],
            )
    captures = last_capture_per_day(db, tk, 2)
    # one instant for every reader, the newer capture's (a datetime keeps microseconds)
    now = datetime.fromtimestamp(captures[0].ts_utc, time_et.ET)
    at = now.timestamp()
    held = time_et.HELD.sessions
    time_et.HELD.sessions = {}  # the two days' own answers, whatever else a test run holds
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
                chain_round_sec=ROUND_SEC,
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
        # the day's level crosses as recorded, oldest first, as cross_store.load holds them: each
        # row as get_recent_crosses reads it
        stored = {f.name for f in fields(StoredCross)}
        with cross_store._lock:
            cross_store._crosses[tk] = [
                StoredCross(**{k: v for k, v in r.items() if k in stored})
                for r in real.desk["crosses"]
            ]
        server._publish_levels(tk, captures=captures, now=now)
        return json.loads(
            json.dumps(
                {
                    "strikes": push_strikes.strikes(tk, at, AUTO),
                    "strikes_wider": push_strikes.strikes(tk, at, {**AUTO, "scope": "wider"}),
                    # the strikes at the chain's second expiry chosen, and at one it does not list
                    "strikes_second_expiry": push_strikes.strikes(
                        tk, at, {**AUTO, "expiry": real.captures[1]["rows"][1]["expiry"]}
                    ),
                    "strikes_missing_expiry": push_strikes.strikes(
                        tk, at, {**AUTO, "expiry": MISSING_EXPIRY}
                    ),
                    "terrain": push_terrain.terrain(tk, at),
                    "surface": push_surface.gamma_surface(
                        tk, at, {**AUTO, "cols": None, "expiry": None}, requested=False
                    ),
                    "surface_missing_expiry": push_surface.gamma_surface(
                        tk, at, {**AUTO, "cols": None, "expiry": MISSING_EXPIRY}, requested=False
                    ),
                    # filtered to the chain's second expiry
                    "surface_second_expiry": push_surface.gamma_surface(
                        tk,
                        at,
                        {**AUTO, "cols": None, "expiry": real.captures[1]["rows"][1]["expiry"]},
                        requested=False,
                    ),
                    # the All window, every strike, for the Gamma tests' ticker (AMZN's 88 strikes
                    # by 24 expiries; SPY's is 491 by 34, 3.5 MB)
                    **(
                        {
                            "surface_all": push_surface.gamma_surface(
                                tk,
                                at,
                                {**AUTO, "scope": "all", "cols": None, "expiry": None},
                                requested=False,
                            )
                        }
                        if real is AMZN
                        else {}
                    ),
                    "chain": push_chain.chain(tk, at, {"expiry": None}),
                    # the Chain tests' expiry switch: the chain's second expiry
                    "chain_second_expiry": push_chain.chain(
                        tk, at, {"expiry": real.captures[1]["rows"][1]["expiry"]}
                    ),
                    "book": {
                        venue: push_book.book(tk, at, {"venue": venue}) for venue in real.venues
                    },
                    "liquidity": push_liquidity.liquidity_snapshot(tk, now),
                    # the levels at each chart's timeframe (Right Now and the maps ask 1 minute)
                    "levels": {tf: push_levels.levels_payload(tk, tf, now) for tf in CHART_TFS},
                    "desk": {
                        tf: push_desk.desk_events_payload(tk, tf, now, CHART_TFS[tf])
                        for tf in DESK_TFS
                    },
                    "bars": {
                        tf: push_bars.bars(tk, at, {"tf": tf, "limit": limit})
                        for tf, limit in CHART_TFS.items()
                    },
                    # the 15-minute desk with its chart spanning the newest hour of minutes: the
                    # queue's older markers have no bar
                    "desk_newest_hour": push_desk.desk_events_payload(tk, "15", now, NEWEST_HOUR),
                    "bars_newest_hour": push_bars.bars(tk, at, {"tf": "15", "limit": NEWEST_HOUR}),
                    "bars_flow": push_bars.bars(tk, at, FLOW_BARS),
                    # the option tape: the daemon streams none of these contracts, and says so
                    "tape": push_tape.tape(tk, at),
                }
            )
        )
    finally:
        _clear(tk)
        time_et.HELD.sessions = held


def write_e2e_panels() -> None:
    """Regeneration utility (never called by a test).

    python -c "import tests.conftest, tests.test_e2e_panels_two_day_v1 as t; t.write_e2e_panels()"
    """
    for real in (AMZN, SPY):
        with tempfile.TemporaryDirectory() as folder:
            real.panels.write_text(
                json.dumps(build_e2e_panels(real, Path(folder)), indent=2) + "\n",  # as Prettier
                encoding="utf-8",
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
    # two expiries, each its own contracts
    second = panels["chain_second_expiry"]
    assert second["status"] == "ok" and second["expiry"] != panels["chain"]["expiry"]
    assert second["ladder"][0]["call"]["symbol"] != panels["chain"]["ladder"][0]["call"]["symbol"]
    assert panels["surface_missing_expiry"]["view"]["missing_expiry"] == MISSING_EXPIRY
    assert len(panels["surface"]["expirations"]) == len(real.captures[1]["rows"])
    assert panels["strikes"]["migration"]["compared"] is True
    # the strikes follow the expiry chosen; one not listed is said, never another's rows
    chosen = real.captures[1]["rows"][1]["expiry"]
    assert panels["strikes_second_expiry"]["expiry"] == chosen
    assert panels["strikes_second_expiry"]["migration"]["compared"] is True
    assert panels["strikes_missing_expiry"] == {
        **panels["strikes_missing_expiry"],
        "available": False,
        "reason": f"the chain lists no contracts for {MISSING_EXPIRY}",
    }
    assert "today" not in panels["strikes_missing_expiry"]
    assert panels["terrain"]["spot"] == real.quote["native"]["LAST_PRICE"]
    # the regime as the screen says it, served beside it: in short, and its name in words (AMZN's
    # dealer gamma at the price is positive that morning, SPY's negative)
    terrain = panels["terrain"]
    assert terrain["regime"] == {"AMZN": "LONG_GAMMA_CHOP", "SPY": "SHORT_GAMMA_TREND"}[real.ticker]
    assert (terrain["regime_text"], terrain["regime_name"]) == {
        "LONG_GAMMA_CHOP": ("Dealer Γ +", "LONG GAMMA CHOP"),
        "SHORT_GAMMA_TREND": ("Dealer Γ −", "SHORT GAMMA TREND"),
    }[terrain["regime"]]
    # the desk: Schwab's books at the price, zones and session levels built from its bars
    assert {book["status"] for book in panels["book"].values()} == {"ok"}
    assert panels["liquidity"]["zones"]
    assert panels["liquidity"]["no_zones_text"] is None  # a list with a zone has no words for none
    assert all(levels["levels"] for levels in panels["levels"].values())
    # each level says whether the liquidity map draws it as a reference line: the prior day's six
    # and the overnight's two, at every timeframe; the session's own levels and the terrain's
    # carried beside them are not (the page holds no list of families)
    prior_day = {"PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL"}
    overnight = {"OVERNIGHT_HIGH", "OVERNIGHT_LOW"}
    for levels in panels["levels"].values():
        drawn = {row["id"] for row in levels["levels"] if row["reference_line"]}
        assert drawn == prior_day | overnight
        assert {row["family"] for row in levels["levels"] if not row["reference_line"]} == {
            "vwap",
            "opening_range",
            "value_area",
            "gamma",
        }
    assert all(bars["bars"] for bars in panels["bars"].values()) and panels["bars_flow"]["bars"]
    # the queue's crosses are the day's recorded ones, inside the timeframe's window
    recorded = {f"x{row['cross_id']}" for row in real.desk["crosses"]}
    for queue in panels["desk"].values():
        crossed = {item["key"] for item in queue["items"] if item["src"] == "level_crosses"}
        assert crossed and crossed <= recorded
    # every marker of the full charts has a bar; the newest hour's chart leaves the older out
    assert {queue["markers_off_chart"] for queue in panels["desk"].values()} == {0}
    first = panels["bars_newest_hour"]["bars"][0]["t"]
    marked = [it for it in panels["desk_newest_hour"]["items"] if it.get("marker")]
    off = [it for it in marked if it["ts"] < first]
    assert panels["desk_newest_hour"]["markers_off_chart"] == len(off) > 0
