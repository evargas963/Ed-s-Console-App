"""app.options.order_flow.history.tape_rows_for_symbol (operator field-inventory audit,
2026-09-13): discrete TRADE prints for the future Options Flow tape, built from the native
LEVELONE_OPTIONS capture already retained in stream_options_quotes_raw -- no new capture, no
second computation. Locked to the operator's own required schema: Time/Symbol/Expiry/Type/
Strike/Bid x Size/Ask x Size/Trade/Size/Premium/Volume/OI/IV/Delta/provenance, with Trade/
Size/Time/Bid/Ask/BidSize/AskSize/Volume/OI/IV/Delta read verbatim (never derived) and
Premium = Trade x Size x native Multiplier. No aggressor-side (buy/sell) classification is
ever produced -- `classification` states only the mechanical fact of where a print landed
relative to that SAME tick's own bid/ask."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.options.order_flow.history import tape_rows_for_symbol
from stream_spine import STREAM_SCHEMA_SQL

SYM = "SPY   260918C00600000"


def _write_ticks(path: Path, rows: list[tuple[float, dict]]) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(STREAM_SCHEMA_SQL)
        for ts_recv, content in rows:
            con.execute(
                "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) "
                "VALUES(?,?,?,?)",
                (ts_recv, SYM, json.dumps(content), "schwab_options_l1"),
            )
        con.commit()
    finally:
        con.close()


def _full_context(**overrides) -> dict:
    base = {
        "key": SYM, "STRIKE_TYPE": 600, "CONTRACT_TYPE": "C",
        "EXPIRATION_YEAR": 2026, "EXPIRATION_MONTH": 9, "EXPIRATION_DAY": 18,
        "MULTIPLIER": 100, "UNDERLYING": "SPY",
    }
    base.update(overrides)
    return base


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                                BID_PRICE=1.17, BID_SIZE=187, ASK_PRICE=1.19, ASK_SIZE=180,
                                TOTAL_VOLUME=70984, OPEN_INTEREST=901, VOLATILITY=7.16, DELTA=0.357)),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == SYM and r["underlying"] == "SPY"
    assert r["expiry"] == "2026-09-18" and r["type"] == "CALL" and r["strike"] == 600
    assert r["bid"] == 1.17 and r["bid_size"] == 187
    assert r["ask"] == 1.19 and r["ask_size"] == 180
    assert r["trade"] == 1.18 and r["size"] == 1
    assert r["premium"] == 1.18 * 1 * 100
    assert r["volume"] == 70984 and r["oi"] == 901 and r["iv"] == 7.16 and r["delta"] == 0.357
    assert r["classification"] == "inside_spread"


def test_a_re_emitted_duplicate_of_the_same_trade_is_not_counted_twice(tmp_path):
    """The vendor re-sends the SAME (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) trade
    alongside an unrelated field update (e.g. a fresh Greek recompute) -- this must collapse
    to ONE tape row, not one per re-emission."""
    db = tmp_path / "stream_capture.db"
    tick = _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                         BID_PRICE=1.17, ASK_PRICE=1.19, TOTAL_VOLUME=70984)
    _write_ticks(db, [
        (1000.0, tick),
        (1005.0, dict(tick, DELTA=0.360)),   # same trade, only a Greek changed
        (1010.0, dict(tick, VOLATILITY=7.2)),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    assert len(rows) == 1


def test_a_partial_update_with_size_but_no_price_never_produces_a_null_trade_row(tmp_path):
    """A SEVENTH independent review (2026-09-13), REPRODUCED against real captured Friday
    data (SPY 260909C00767000): a partial LEVELONE_OPTIONS tick can carry a fresh LAST_SIZE
    with NO LAST_PRICE on the same packet (a size-only field bumping TOTAL_VOLUME on its
    own) -- the naive de-dup key (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) treated this as
    a "new" trade because the tuple differed, emitting a tape row with trade=None and a
    stray size. A trade print requires its OWN price AND its OWN trade timestamp on the
    SAME tick; this reproduces the exact real-world shape and proves it is now excluded."""
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=0.01, LAST_SIZE=1,
                                BID_PRICE=0.0, ASK_PRICE=0.01, TOTAL_VOLUME=108925)),
        # partial: LAST_SIZE bumped, no LAST_PRICE, no TRADE_TIME_MILLIS at all
        (1002.0, {"key": SYM, "LAST_SIZE": 2, "TOTAL_VOLUME": 108926}),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    assert len(rows) == 1, "the size-only partial must not be counted as a second trade print"
    assert all(r["trade"] is not None for r in rows), "no row may ever report trade=None"


def test_context_is_carried_forward_from_the_most_recent_full_tick(tmp_path):
    """The vendor does not repeat expiry/strike/type/multiplier on every partial update --
    a LATER genuine trade print that arrives on a tick carrying ONLY price/size/bid/ask
    must still resolve its own contract identity from the most recent tick that reported
    it, not read as if that identity were unknown."""
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                                BID_PRICE=1.17, ASK_PRICE=1.19)),
        # a later genuine trade with NO strike/type/expiry/multiplier fields on this tick
        (2000.0, {"key": SYM, "TRADE_TIME_MILLIS": 1999000, "LAST_PRICE": 1.25, "LAST_SIZE": 3,
                  "BID_PRICE": 1.24, "ASK_PRICE": 1.26}),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    assert len(rows) == 2
    newest = rows[0]   # newest-first
    assert newest["trade"] == 1.25 and newest["size"] == 3
    assert newest["expiry"] == "2026-09-18" and newest["type"] == "CALL" and newest["strike"] == 600


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (1000.0, _full_context(TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1001.0, _full_context(TRADE_TIME_MILLIS=1001, LAST_PRICE=1.19, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1002.0, _full_context(TRADE_TIME_MILLIS=1002, LAST_PRICE=1.20, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1003.0, _full_context(TRADE_TIME_MILLIS=1003, LAST_PRICE=1.10, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    by_trade = {r["trade"]: r["classification"] for r in rows}
    assert by_trade[1.17] == "at_bid"
    assert by_trade[1.19] == "at_ask"
    assert by_trade[1.20] == "outside_spread_high"
    assert by_trade[1.10] == "outside_spread_low"


def test_newest_first_ordering_and_limit_bound(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (float(1000 + i), _full_context(TRADE_TIME_MILLIS=1000 + i, LAST_PRICE=1.0 + i * 0.01, LAST_SIZE=1,
                                        BID_PRICE=1.0, ASK_PRICE=2.0))
        for i in range(5)
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=3)
    assert len(rows) == 3
    assert [r["ts_recv"] for r in rows] == sorted((r["ts_recv"] for r in rows), reverse=True)
    assert rows[0]["trade"] == 1.04   # the LAST (newest) genuine trade written


def test_fails_closed_to_empty_when_the_db_file_does_not_exist(tmp_path):
    assert tape_rows_for_symbol(SYM, since_ts=0, db_path=tmp_path / "no_such.db", limit=50) == []


def test_fails_closed_to_empty_for_a_blank_symbol():
    assert tape_rows_for_symbol("", since_ts=0, db_path="anything.db", limit=50) == []
