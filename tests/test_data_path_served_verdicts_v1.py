"""Schwab -> the levels, the chain and every option contract: one served verdict each, judged by the
ticker's own option market (docs/DATA_FLOW.md §2 D5, operator 2026-10-25).

Real data: TSLA's (stock options, whose market Schwab's /markets answer closes at 16:00 ET) and SPY's
0DTE (index-close options, 16:15 ET) chains captured 2026-10-07, a date the held /markets answers
cover (tests/conftest.py). STAND-IN (named): each chain published as if the daemon delivered it at
the instant a test names (`computed_ts_utc`), and the daemon's status typed in its shape.
"""
from __future__ import annotations

from datetime import datetime

import pytest

import live_market_plane as lmp
import server
from terrain_engine import compute_terrain
from tests.real_chains import SPY_0DTE, TSLA
from time_et import EQUITY_OPTIONS, ET, INDEX_OPTIONS


def _et(hh: int, mm: int = 0, day: str = "2026-10-07") -> datetime:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET)


def _publish(tk: str, chain, delivered: datetime) -> None:
    """`chain`'s levels in the console's cache as if the daemon delivered it at `delivered`."""
    published = compute_terrain(tk, [dict(c) for c in chain.chain], chain.spot, now=chain.now).to_dict()
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = published | {"computed_ts_utc": delivered.timestamp()}


@pytest.fixture
def published():
    yield _publish
    with server._terrain_cache_lock:
        for tk in ("TSLA", "SPY"):
            server._terrain_cache.pop(tk, None)


@pytest.mark.parametrize("tk, chain, delivered, at, state", [
    ("TSLA", TSLA, _et(11, 0), _et(11, 1), "LIVE"),       # its options open, the chain current
    ("TSLA", TSLA, _et(11, 0), _et(11, 30), "STALE"),     # its options open, no chain for 30 minutes
    ("TSLA", TSLA, _et(16, 1), _et(16, 5), "CLOSE"),      # fetched after its own 16:00 close
    ("TSLA", TSLA, _et(15, 59), _et(16, 5), "STALE"),     # its close values never fetched
    ("SPY", SPY_0DTE, _et(16, 4), _et(16, 5), "LIVE"),    # its options still open until 16:15
    ("SPY", SPY_0DTE, _et(16, 4), _et(16, 20), "STALE"),  # fetched before its own 16:15 close
    ("SPY", SPY_0DTE, _et(16, 16), _et(16, 20), "CLOSE"),
    ("SPY", SPY_0DTE, _et(16, 16, "2026-10-09"), _et(12, 0, "2026-10-10"), "CLOSE"),  # Saturday: Friday's close
    ("SPY", SPY_0DTE, _et(16, 16), _et(12, 0, "2026-10-10"), "STALE"),   # Saturday: Wednesday's, not Friday's
])
def test_the_levels_are_judged_by_the_tickers_own_option_market(published, tk, chain, delivered, at, state):
    """The levels' one served word: LIVE while the ticker's own option market is open and its
    chain current, STALE when the chain is overdue or the close values were never fetched, CLOSE
    once its own market has closed and a chain fetched after that close stands."""
    published(tk, chain, delivered)
    body = server.terrain_answer(tk, at)
    assert body["levels_state"] == state
    assert body["levels_stale"] is (state == "STALE")
    assert body["levels_age_sec"] == pytest.approx(at.timestamp() - delivered.timestamp())
    assert body["levels_time_ct"] is not None


def test_levels_with_no_markets_answer_held_are_not_live(published):
    """2026-09-20: no /markets answer held for that date, so the levels are not live."""
    published("TSLA", TSLA, _et(11, 0, "2026-09-20"))
    body = server.terrain_answer("TSLA", _et(11, 1, "2026-09-20"))
    assert (body["levels_state"], body["levels_stale_reason"]) == ("NOT LIVE", "the market session is unknown")


@pytest.mark.parametrize("product, at, state, why", [
    (EQUITY_OPTIONS, _et(15, 59), "LIVE", None),
    (EQUITY_OPTIONS, _et(16, 5), "NOT LIVE", "outside Schwab's option market hours"),
    (INDEX_OPTIONS, _et(16, 5), "LIVE", None),
    (INDEX_OPTIONS, _et(16, 20), "NOT LIVE", "outside Schwab's option market hours"),
    (None, _et(11, 0), "NOT LIVE", "the contract's option market is not known"),
])
def test_an_option_contract_is_live_only_while_its_own_option_market_is_open(product, at, state, why):
    """A contract held on LEVELONE_OPTIONS and OPTIONS_BOOK, the feed up: live by its own option
    market's window in Schwab's /markets answer (a stock option closes at 16:00 ET, an index-close
    option at 16:15), and not live when its market is not known."""
    sym = TSLA.chain[0]["symbol"]
    lmp.record_feed_heartbeat({"ts": at.timestamp(), "schwab_socket_open": True,
                               "held": {"LEVELONE_OPTIONS": [sym], "OPTIONS_BOOK": [sym]}})
    for service in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
        assert lmp.live_state(sym, service, at.timestamp(), product) == (state, why)
