"""app.options.order_flow.history.book_heatmap_for_ticker (operator field-inventory audit,
2026-09-13: "we don't have an order flow heatmap"). Bins the SAME persisted NASDAQ_BOOK/
NYSE_BOOK rows the live /api/order-flow/microstructure ladder already reads into a time x
price grid -- the historical, time-dimensioned counterpart a single live snapshot cannot show.
No interpolation: every cell traces to a real captured tick's own native BID_PRICE/ASK_PRICE/
TOTAL_VOLUME."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.options.order_flow.history import book_heatmap_for_ticker
from stream_spine import STREAM_SCHEMA_SQL

SYM = "SPY"


def _write_book_rows(path: Path, rows: list[tuple[float, str, dict]]) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(STREAM_SCHEMA_SQL)
        for ts_recv, service, content in rows:
            con.execute(
                "INSERT INTO stream_book_raw(ts_recv,service,symbol,native_json,src) "
                "VALUES(?,?,?,?,?)",
                (ts_recv, service, SYM, json.dumps(content), "schwab_book"),
            )
        con.commit()
    finally:
        con.close()


def _book(bid_price, bid_vol, ask_price, ask_vol, book_time_ms=0):
    return {
        "key": SYM, "BOOK_TIME": book_time_ms,
        "BIDS": [{"BID_PRICE": bid_price, "TOTAL_VOLUME": bid_vol, "NUM_BIDS": 1}] if bid_price is not None else [],
        "ASKS": [{"ASK_PRICE": ask_price, "TOTAL_VOLUME": ask_vol, "NUM_ASKS": 1}] if ask_price is not None else [],
    }


def test_repeated_unchanged_levels_do_not_inflate_the_cell(tmp_path):
    """Operator-reproduced defect (2026-09-14): NASDAQ_BOOK/NYSE_BOOK messages are full-book
    snapshots, not deltas -- an UNCHANGED 100-share level re-transmitted 10 times must still
    read as 100, never as 1,000. The cell holds the LAST observed size in the bucket, not a
    sum across every retransmission of the same resting size."""
    db = tmp_path / "stream_capture.db"
    _write_book_rows(db, [
        (1000.0, "NASDAQ_BOOK", _book(100.00, 100, 100.05, 30)),
        (1000.1, "NASDAQ_BOOK", _book(100.00, 100, 100.05, 30)),
        (1000.2, "NASDAQ_BOOK", _book(100.00, 100, 100.05, 30)),
    ])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is True
    assert d["rows_scanned"] == 3
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert cells[(0, 100.00)]["bid"] == 100.0   # not 300.0
    assert cells[(0, 100.05)]["ask"] == 30.0    # not 90.0


def test_a_changed_level_in_the_same_bucket_reads_as_its_latest_observed_size(tmp_path):
    db = tmp_path / "stream_capture.db"
    # A sub-1s gap lands both rows in the SAME bucket: bucket_sec floors at 1.0s (n_buckets=90
    # would otherwise make it a fraction of a second), and (1000.4-1000.0)/1.0 floors to 0.
    _write_book_rows(db, [
        (1000.0, "NASDAQ_BOOK", _book(100.00, 50, 100.05, 30)),
        (1000.4, "NASDAQ_BOOK", _book(100.00, 20, 100.05, 10)),  # same bucket, same price -> latest wins
    ])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is True
    assert d["rows_scanned"] == 2
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert (0, 100.00) in cells and cells[(0, 100.00)]["bid"] == 20.0 and cells[(0, 100.00)]["ask"] == 0.0
    assert (0, 100.05) in cells and cells[(0, 100.05)]["ask"] == 10.0 and cells[(0, 100.05)]["bid"] == 0.0


def test_both_venues_are_merged_not_one_silently_picked(tmp_path):
    """Same ts_recv for both venues: sqlite has no guaranteed row order for ties, so this
    asserts the LAST-observed value is one of the two real per-venue sizes, never their sum
    (300.00 -> {50,25} or {25,50} depending on read order, but never 75)."""
    db = tmp_path / "stream_capture.db"
    _write_book_rows(db, [
        (1000.0, "NASDAQ_BOOK", _book(100.00, 50, 100.05, 30)),
        (1000.0, "NYSE_BOOK", _book(100.00, 25, 100.05, 15)),
    ])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is True and d["rows_scanned"] == 2
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert cells[(0, 100.00)]["bid"] in (50.0, 25.0)
    assert cells[(0, 100.05)]["ask"] in (30.0, 15.0)


def test_window_anchors_to_the_datas_own_latest_row_never_wallclock_now(tmp_path):
    """A real prior session (all rows far in the past) must still render honestly outside
    RTH -- the window is [latest_captured_ts - minutes*60, latest_captured_ts], never
    [now - minutes*60, now], or every weekend/after-hours request would show an empty grid
    despite real historical data existing a few hours earlier."""
    db = tmp_path / "stream_capture.db"
    old_ts = 500_000.0   # far from any real wall-clock "now" in a test run
    _write_book_rows(db, [(old_ts, "NASDAQ_BOOK", _book(50.00, 10, 50.05, 10))])
    d = book_heatmap_for_ticker(SYM, minutes=5, db_path=db)
    assert d["available"] is True
    assert d["latest_captured_ts"] == old_ts
    assert d["since_ts"] <= old_ts <= d["until_ts"]


def test_rows_outside_the_minutes_window_are_excluded(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_book_rows(db, [
        (50_000.0, "NASDAQ_BOOK", _book(50.00, 999, 50.05, 999)),    # far outside a 5-min window
        (100_290.0, "NASDAQ_BOOK", _book(60.00, 10, 60.05, 10)),     # within 5 min of the latest row
        (100_300.0, "NASDAQ_BOOK", _book(60.10, 5, 60.15, 5)),       # latest row
    ])
    d = book_heatmap_for_ticker(SYM, minutes=5, db_path=db)
    assert d["available"] is True
    prices = {c["price"] for c in d["cells"]}
    assert 50.00 not in prices and 50.05 not in prices
    assert 60.00 in prices and 60.10 in prices


def test_no_book_history_at_all_fails_closed_with_a_plain_reason(tmp_path):
    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(db)
    con.executescript(STREAM_SCHEMA_SQL)
    con.close()
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is False
    assert d["reason"] == "no book history captured for this ticker"


def test_rows_present_but_every_level_array_empty_fails_closed_not_a_fabricated_grid(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_book_rows(db, [(1000.0, "NASDAQ_BOOK", _book(None, None, None, None))])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is False
    assert "no populated price levels" in d["reason"]


def test_options_book_rows_for_a_contract_never_leak_into_the_underlyings_heatmap(tmp_path):
    """service='OPTIONS_BOOK' rows live in the SAME table (stream_book_raw) but describe a
    contract's own book, not the underlying's -- this must never be counted here."""
    db = tmp_path / "stream_capture.db"
    _write_book_rows(db, [
        (1000.0, "OPTIONS_BOOK", _book(1.00, 5000, 1.05, 5000)),
    ])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is False
    assert d["reason"] == "no book history captured for this ticker"


def test_nested_list_levels_are_no_longer_silently_dropped(tmp_path):
    """RC-REHAB-1 (Phase 2) mutation test: this loop used to reimplement its own BIDS/ASKS
    parser independently of engine.py's canonical _iter_bids_levels/_iter_asks_levels, and its
    own version silently dropped a level that was itself a nested list of sub-dicts (a real
    vendor shape those canonical functions already handle -- engine.py:158-171,183-195).
    Consolidating onto the canonical parser fixes this as a side effect; this proves it."""
    db = tmp_path / "stream_capture.db"
    nested_book = {
        "key": SYM, "BOOK_TIME": 0,
        "BIDS": [[{"BID_PRICE": 100.00, "TOTAL_VOLUME": 77, "NUM_BIDS": 1}]],
        "ASKS": [[{"ASK_PRICE": 100.05, "TOTAL_VOLUME": 55, "NUM_ASKS": 1}]],
    }
    _write_book_rows(db, [(1000.0, "NASDAQ_BOOK", nested_book)])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is True, "a nested-list level must not make the whole row look empty"
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert cells[(0, 100.00)]["bid"] == 77.0
    assert cells[(0, 100.05)]["ask"] == 55.0


def test_non_positive_price_or_negative_volume_levels_are_now_rejected(tmp_path):
    """RC-REHAB-1 (Phase 2) mutation test: the old loop only checked for None, so a malformed
    zero/negative price or a negative volume was silently bucketed as real data. Consolidating
    onto _sorted_valid_levels' `p > 0 and v >= 0` filter now excludes it instead."""
    db = tmp_path / "stream_capture.db"
    malformed_book = {
        "key": SYM, "BOOK_TIME": 0,
        "BIDS": [
            {"BID_PRICE": 0.0, "TOTAL_VOLUME": 999, "NUM_BIDS": 1},
            {"BID_PRICE": 100.00, "TOTAL_VOLUME": -5, "NUM_BIDS": 1},
            {"BID_PRICE": 99.50, "TOTAL_VOLUME": 40, "NUM_BIDS": 1},
        ],
        "ASKS": [{"ASK_PRICE": 100.05, "TOTAL_VOLUME": 30, "NUM_ASKS": 1}],
    }
    _write_book_rows(db, [(1000.0, "NASDAQ_BOOK", malformed_book)])
    d = book_heatmap_for_ticker(SYM, minutes=60, db_path=db)
    assert d["available"] is True
    cells = {(c["t"], c["price"]): c for c in d["cells"]}
    assert (0, 0.0) not in cells, "a non-positive price must not become a real cell"
    assert (0, 100.00) not in cells, "a negative volume at this price must not become a real cell"
    assert cells[(0, 99.50)]["bid"] == 40.0, "a genuinely valid level in the same row must still resolve"
