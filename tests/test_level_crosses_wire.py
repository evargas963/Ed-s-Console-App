"""Level crosses: found at the live price on each streamed equity quote (server._on_stream_tick,
terrain_read.crossed), stored by EdDB.record_level_crosses, read back by get_recent_crosses.

Real data: SPY's 2026-10-22 close capture published at the price Schwab sent in it (764.04), then
SPY's LEVELONE_EQUITIES prints after it as the daemon received them -- 764.27 at 18:00 ET, and
773.1269, a strike away (tests/real_chains.py).
"""

from __future__ import annotations

import time
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import server
from app.options.order_flow import streaming as ofs
from db import EdDB
from terrain_read import CROSSED_DOWN, CROSSED_UP, crossed
from tests.real_chains import SPY_AFTER_HOURS_PRINT, SPY_CLOSE, SPY_PRINT_A_STRIKE_AWAY

PUBLISHED = SPY_CLOSE.spot
AFTER_HOURS = SPY_AFTER_HOURS_PRINT["native"]["LAST_PRICE"]
STRIKE_AWAY = SPY_PRINT_A_STRIKE_AWAY["native"]["LAST_PRICE"]


def _print(msg: dict) -> None:
    """One SPY LEVELONE_EQUITIES message as the daemon received it, and the price row it pushes;
    then the quote's tick reaches the console."""
    lmp.record_from_level_one_equity("SPY", msg["native"], received_ts=msg["ts_recv"])
    ofs._price_rows["SPY"] = live_price_rows.price_row("SPY", time.time())
    server._on_stream_tick("SPY")
    server._chain_pricing.submit(lambda: None).result()      # the store runs on the pricing thread


def test_a_cross_is_found_at_the_live_price_not_at_the_publication():
    """The levels are the close capture's, published at 764.04. The 18:00 print (764.27) crosses
    none of them. The print a strike away (773.1269) crosses, upward, each level between the two
    prints -- the call wall 765, the gamma flip 770.77, max pain 771 and the put delta wall 772 --
    though no chain was published in between."""
    server._publish_levels("SPY", captures=[{
        "contracts": [dict(c) for c in SPY_CLOSE.chain], "ts_utc": SPY_CLOSE.now.timestamp(),
        "spot": PUBLISHED, "et_date": SPY_CLOSE.now.date().isoformat(), "basis": server.CAPTURE_BASIS,
        "spot_ts": None, "spot_from_chain": False}], now=SPY_CLOSE.now)
    with server._terrain_cache_lock:
        levels = {name: server._terrain_cache["SPY"][k] for k, name in server.CROSS_LEVELS}
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": ["SPY"]}})
    with server._crosses_lock:
        before = len(server._crosses.get("SPY", []))
    try:
        _print(SPY_AFTER_HOURS_PRINT)
        with server._crosses_lock:
            assert len(server._crosses.get("SPY", [])) == before
        _print(SPY_PRINT_A_STRIKE_AWAY)
        with server._crosses_lock:
            new = server._crosses.get("SPY", [])[before:]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
        server._cross_check_spot.pop("SPY", None)
        ofs._price_rows.pop("SPY", None)
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {}})
        lmp.record_feed_down()
    want = {name for name, v in levels.items() if v is not None and AFTER_HOURS < v <= STRIKE_AWAY}
    assert want == {"Call g-Wall", "Gamma Flip", "Max Pain", "Put d-Wall"}
    assert {c["level_name"] for c in new} == want
    assert all(c["direction"] == CROSSED_UP and c["spot_at_cross"] == STRIKE_AWAY for c in new)
    assert {c["level_name"]: c["level_value"] for c in new} == {n: levels[n] for n in want}


def test_reaching_a_level_crosses_it_once():
    """The price that reaches a level crosses it; the next price beyond it does not cross again.
    The call wall 765 of the close capture, from the 18:00 print."""
    wall = 765.0
    assert crossed(wall, AFTER_HOURS, wall) == CROSSED_UP
    assert crossed(wall, wall, STRIKE_AWAY) is None
    assert crossed(wall, STRIKE_AWAY, wall) == CROSSED_DOWN
    assert crossed(wall, wall, AFTER_HOURS) is None
    assert crossed(wall, None, STRIKE_AWAY) is None and crossed(None, AFTER_HOURS, STRIKE_AWAY) is None


WALL = (765.0, "Call g-Wall")


def test_a_stored_cross_is_the_row_read_back(tmp_path: Path) -> None:
    edb = EdDB(tmp_path / "level_crosses.db")
    stored = edb.record_level_crosses(ticker="SPY", spot=STRIKE_AWAY, crosses=[(*WALL, CROSSED_UP)],
                                      ts_utc=SPY_PRINT_A_STRIKE_AWAY["ts_recv"], ts_et="2026-10-22 16:39:03 ET")
    assert [(c["level_name"], c["level_value"], c["direction"], c["spot_at_cross"]) for c in stored] == [
        ("Call g-Wall", 765.0, CROSSED_UP, STRIKE_AWAY)]
    # a cross recorded live and the same cross loaded at startup are the same row, cross_id included
    assert edb.get_recent_crosses("SPY", n=10) == stored


def test_the_same_cross_within_a_minute_is_stored_once_and_a_reversal_at_once() -> None:
    """The hold-back reads the crosses the console holds, not the database."""
    tk = "ZZCROSSHOLD"
    t = SPY_PRINT_A_STRIKE_AWAY["ts_recv"]

    def store(direction, at):
        server._log_level_crosses(tk, STRIKE_AWAY, [(*WALL, direction)], at, "ET")
        with server._crosses_lock:
            return [(c["direction"], c["ts_utc"]) for c in server._crosses.get(tk, [])]
    try:
        store(CROSSED_UP, t)
        assert store(CROSSED_UP, t + 10.0) == [(CROSSED_UP, t)]
        assert store(CROSSED_DOWN, t + 10.0)[-1] == (CROSSED_DOWN, t + 10.0)         # a reversal
        assert store(CROSSED_UP, t + 10.0 + server.LEVEL_CROSS_HOLD_S)[-1] == (
            CROSSED_UP, t + 10.0 + server.LEVEL_CROSS_HOLD_S)                        # past the minute
    finally:
        with server._crosses_lock:
            server._crosses.pop(tk, None)


def test_levels_crossed_together_are_one_event_naming_every_level(monkeypatch) -> None:
    """RC-88: one price crossing a strike where several levels sit is stored as one row per level.
    The one reader (server._merged_recent_crosses) serves one event per (time, value, direction)
    that names every level. Real SPY rows, tests/fixtures/real_spy_level_crosses.json: 400 rows,
    243 events, up to 6 levels on one event, loaded as the console's start loads them."""
    import json

    rows = json.loads((Path(__file__).parent / "fixtures" / "real_spy_level_crosses.json")
                      .read_text(encoding="utf-8"))["rows"]

    class _Stored:                                   # stand-in: the stored rows, as the DB returns them
        def get_recent_crosses(self, ticker, n):
            return rows[:n]

    assert len(rows) == 400
    monkeypatch.setattr(server, "get_db", lambda: _Stored())
    monkeypatch.setattr(server, "_crosses", {})
    server._load_crosses(["SPY"])
    events = server._merged_recent_crosses("SPY", 400)
    assert len(events) == 243
    assert max(len(e["level_names"]) for e in events) == 6
