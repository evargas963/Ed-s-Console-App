"""Level crosses: found at the live price on each streamed equity quote (server._on_stream_tick,
terrain_read.crossed), stored by EdDB.record_level_crosses, read back by get_recent_crosses.

Real data: SPY's 2026-10-22 close capture published at the price Schwab sent in it (764.04), then
SPY's LEVELONE_EQUITIES prints after it, in the order the daemon received them: 764.00 at
16:33:27 ET, 773.1269 at 16:39:03 and 764.27 at 18:00 (tests/real_chains.py).
"""

from __future__ import annotations

import time
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import server
from app.options.order_flow import streaming as ofs
from db import EdDB, LevelCrossEvent
from terrain_read import CROSSED_DOWN, CROSSED_UP, LEVEL_AT, crossed
from tests.real_chains import SPY_AFTER_HOURS_PRINT, SPY_CLOSE, SPY_PRINT_A_STRIKE_AWAY, SPY_PRINT_ON_A_STRIKE

ON_A_STRIKE = SPY_PRINT_ON_A_STRIKE["native"]["LAST_PRICE"]
STRIKE_AWAY = SPY_PRINT_A_STRIKE_AWAY["native"]["LAST_PRICE"]
AFTER_HOURS = SPY_AFTER_HOURS_PRINT["native"]["LAST_PRICE"]
#: the levels between 764.00 and 773.1269: the call wall 765, the gamma flip 770.77, max pain 771
#: and the put delta wall 772 (the put wall and the net-gamma peak are at 764.00 itself)
BETWEEN = {"Call g-Wall", "Gamma Flip", "Max Pain", "Put d-Wall"}


def _publish_close(tk: str = "SPY") -> dict:
    server._publish_levels(tk, captures=[{
        "contracts": [dict(c) for c in SPY_CLOSE.chain], "ts_utc": SPY_CLOSE.now.timestamp(),
        "spot": SPY_CLOSE.spot, "et_date": SPY_CLOSE.now.date().isoformat(), "basis": server.CAPTURE_BASIS,
        "spot_ts": None, "spot_from_chain": False}], now=SPY_CLOSE.now)
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}})
    with server._terrain_cache_lock:
        return {name: server._terrain_cache[tk][k] for k, name in server.CROSS_LEVELS}


def _stored(tk: str) -> list:
    return server.get_db().get_recent_crosses(tk, n=server.CROSSES_KEPT)


def _print(msg: dict, tk: str = "SPY") -> list:
    """One SPY LEVELONE_EQUITIES message as the daemon received it and the price row it pushes;
    the quote's tick reaches the console. Returns the crosses it stored (on the pricing thread)."""
    lmp.record_from_level_one_equity(tk, msg["native"], received_ts=msg["ts_recv"])
    ofs._price_rows[tk] = live_price_rows.price_row(tk, time.time())
    before = {c["cross_id"] for c in _stored(tk)}
    server._on_stream_tick(tk)
    server._chain_pricing.submit(lambda: None).result()
    return [c for c in _stored(tk) if c["cross_id"] not in before]


def _forget(tk: str = "SPY") -> None:
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    with server._crosses_lock:
        server._crosses.pop(tk, None)
    server._last_tick_spot.pop(tk, None)
    ofs._price_rows.pop(tk, None)
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {}})
    lmp.record_feed_down()


def _named(rows: list) -> dict:
    return {c["level_name"]: (c["direction"], c["level_value"], c["spot_at_cross"]) for c in rows}


def test_each_cross_is_found_at_the_live_price_in_the_order_schwab_sent_the_prints():
    """The levels are the close capture's, published at 764.04. The 16:33 print (764.00) sits on
    the put wall and the net-gamma peak and crosses nothing. The 16:39 print (773.1269) crosses
    upward each level between the two prints; the 18:00 print (764.27) crosses each of them back
    down, a reversal stored at once. No chain was published in between."""
    _forget()
    levels = _publish_close()
    try:
        at_strike = _print(SPY_PRINT_ON_A_STRIKE)
        up = _print(SPY_PRINT_A_STRIKE_AWAY)
        down = _print(SPY_AFTER_HOURS_PRINT)
        with server._crosses_lock:
            held = list(server._crosses["SPY"])
    finally:
        _forget()
    assert {n for n, v in levels.items() if v is not None and ON_A_STRIKE < v <= STRIKE_AWAY} == BETWEEN
    assert at_strike == []
    assert _named(up) == {n: (CROSSED_UP, levels[n], STRIKE_AWAY) for n in BETWEEN}
    assert _named(down) == {n: (CROSSED_DOWN, levels[n], AFTER_HOURS) for n in BETWEEN}
    # each stored cross is held for the live readers, newest last
    assert sorted(c["cross_id"] for c in held[-8:]) == sorted(c["cross_id"] for c in up + down)


def test_a_restart_holds_back_the_cross_its_last_minute_stored():
    """Induced condition: the console restarts (its held crosses and last price forgotten) a moment
    after storing the 16:39 crosses, and the same prints arrive again. The crosses stored in the
    last minute are read from the database before the hold-back decides, so none is stored twice.
    The ticker ZZRESTART carries SPY's chain and prints, so no other test's SPY rows count."""
    tk = "ZZRESTART"
    _forget(tk)
    _publish_close(tk)
    try:
        _print(SPY_PRINT_ON_A_STRIKE, tk)
        first = _print(SPY_PRINT_A_STRIKE_AWAY, tk)
        with server._crosses_lock:
            server._crosses.pop(tk, None)
        server._last_tick_spot.pop(tk, None)
        _print(SPY_PRINT_ON_A_STRIKE, tk)
        again = _print(SPY_PRINT_A_STRIKE_AWAY, tk)
        with server._crosses_lock:
            held = {c["cross_id"] for c in server._crosses[tk]}
    finally:
        _forget(tk)
    assert set(_named(first)) == BETWEEN and again == []
    assert {c["cross_id"] for c in first} <= held                    # read back after the restart


def test_a_price_that_reaches_a_level_crosses_it_and_one_that_leaves_it_does_not():
    """The call wall 765 and the put wall 764 of the close capture, between the three prints."""
    assert crossed(765.0, ON_A_STRIKE, STRIKE_AWAY) == CROSSED_UP
    assert crossed(765.0, STRIKE_AWAY, AFTER_HOURS) == CROSSED_DOWN
    assert crossed(764.0, ON_A_STRIKE, STRIKE_AWAY) is None          # it was at the wall, then left it
    assert crossed(764.0, None, ON_A_STRIKE) is None and crossed(None, ON_A_STRIKE, STRIKE_AWAY) is None


def test_the_levels_side_of_a_print_on_a_level_is_at():
    """/api/levels at the 16:33 print (764.00): the put wall 764 is AT the price, exactly."""
    _forget()
    _publish_close()
    lmp.record_from_level_one_equity("SPY", SPY_PRINT_ON_A_STRIKE["native"], received_ts=SPY_PRINT_ON_A_STRIKE["ts_recv"])
    ofs._price_rows["SPY"] = live_price_rows.price_row("SPY", time.time())
    try:
        body = server.levels_payload("SPY", "1", SPY_CLOSE.now)
    finally:
        _forget()
    put = next(r for r in body["levels"] if r["id"] == "put_wall")
    assert (put["price"], put["distance"], put["side"]) == (ON_A_STRIKE, 0.0, LEVEL_AT)


def test_a_stored_cross_is_the_row_read_back(tmp_path: Path) -> None:
    edb = EdDB(tmp_path / "level_crosses.db")
    event = LevelCrossEvent(ticker="SPY", ts_utc=SPY_PRINT_A_STRIKE_AWAY["ts_recv"], ts_et="2026-10-22 16:39:03 ET",
                            level_name="Call g-Wall", level_value=765.0, direction=CROSSED_UP,
                            spot_at_cross=STRIKE_AWAY, zone_before=None, zone_after=None, timeframe="1m")
    stored = edb.record_level_crosses([event])
    assert [(c["level_name"], c["level_value"], c["direction"], c["spot_at_cross"]) for c in stored] == [
        ("Call g-Wall", 765.0, CROSSED_UP, STRIKE_AWAY)]
    # a cross recorded live and the same cross loaded at startup are the same row, cross_id included
    assert edb.get_recent_crosses("SPY", n=10) == stored


def test_levels_crossed_together_are_one_event_naming_every_level() -> None:
    """RC-88: one price crossing a strike where several levels sit is stored as one row per level.
    The one reader (server._merged_recent_crosses) serves one event per (time, value, direction)
    that names every level. Real SPY rows, tests/fixtures/real_spy_level_crosses.json (newest
    first, as the database returns them): 400 rows, 243 events, up to 6 levels on one event, held
    oldest first as the console's start holds them."""
    import json

    rows = json.loads((Path(__file__).parent / "fixtures" / "real_spy_level_crosses.json")
                      .read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 400
    tk = "ZZRC88"
    with server._crosses_lock:
        server._crosses[tk] = rows[::-1]
    try:
        events = server._merged_recent_crosses(tk, 400)
    finally:
        with server._crosses_lock:
            server._crosses.pop(tk, None)
    assert len(events) == 243
    assert max(len(e["level_names"]) for e in events) == 6
