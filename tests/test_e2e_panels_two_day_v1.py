"""The browser tests' panels of AMZN's real two days are the server's own answers.

Real data, read-only from production on 2026-11-12: AMZN's last complete capture of 2026-11-11
(the close, 16:17:36 ET) and its complete capture of 2026-11-12 10:39:18 ET, every expiry (24)
and every row as stored, each with the chain's spot; AMZN's LEVELONE_EQUITIES message the
daemon received last before that capture (LAST_PRICE 269.425); and Schwab's /markets answers
for the two days. The two captures are stored by the daemon's writer, read back by the server's
reader (last_capture_per_day) and published by the one producer as a start does, with the quote
as the live price: the levels LIVE, a heatmap of 24 expiries, the day-over-day migration and the
level moves against the prior day's close.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import server
import time_et
from calibration.complete_chain_capture import last_capture_per_day
from tests.capture_store import store_capture
from tests.feed_live_helper import mark_feed_live

_FX = Path(__file__).resolve().parent / "fixtures"
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
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_down()


def build_e2e_panels(folder: Path) -> dict:
    """Return the panels of AMZN's real two days as the page's socket sends them.

    `folder` holds the database the two captures are stored in. At the newer capture's instant:
    the strikes in the Auto and Wider windows, the levels (terrain), the heatmap (surface, Auto,
    every column and expiry; and asked for an expiry the chain does not list) and the front
    expiry's chain. Regenerate the browser tests' file
    with write_e2e_panels.
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
    at = captures[0]["ts_utc"]
    held = time_et._sessions
    time_et._sessions = {}  # the two days' own answers, whatever else a test run holds
    _clear()
    try:
        for answer in _MARKETS:
            time_et.record_markets(answer)
        lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
        mark_feed_live(TK, now=at)
        server._publish_levels(TK, captures=captures, now=datetime.fromtimestamp(at, time_et.ET))
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
    assert {panels[name]["levels_state"] for name in panels} == {"LIVE"}
    assert panels["surface_missing_expiry"]["view"]["missing_expiry"] == MISSING_EXPIRY
    assert len(panels["surface"]["expirations"]) == len(_SET["captures"][1]["rows"])
    assert panels["strikes"]["migration"]["all"]["compared"] is True
    assert panels["terrain"]["spot"] == _QUOTE["native"]["LAST_PRICE"]
