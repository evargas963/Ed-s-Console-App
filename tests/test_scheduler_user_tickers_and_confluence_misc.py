"""The ticker board: which symbols are valid, and the one reader both processes use."""

from __future__ import annotations


def test_board_validity_is_the_symbols_form_never_a_list_of_names():
    """TICK-04 (2026-09-28 audit): SP, IW and NV were refused by name (and pruned from the board
    at every start), whatever Schwab says about them. A well-formed symbol is valid for any
    instrument type; whether it is real is Schwab's answer to its chain request."""
    from production_universe import is_valid_production_ticker
    assert all(is_valid_production_ticker(s) for s in ("SP", "IW", "NV", "SPY", "MU", "SPX", "$VIX", "$SP"))
    assert not any(is_valid_production_ticker(s) for s in ("", "$", "TOOLONGX"))


def test_the_console_and_the_daemon_hold_one_board(tmp_path, monkeypatch):
    """ONE-13 (2026-09-28 audit): the console built its roster by merging an (empty) built-in
    list with the table's rows by category and a pass-through filter; the daemon read the table
    with board_tickers. The console now reads the board with that same reader: every enrolled
    row, whatever its category (user, index, ETF, panel symbol), in one order."""
    import sqlite3

    import server
    from calibration.complete_chain_capture import board_tickers
    from db import EdDB
    edb = EdDB(tmp_path / "board.db")
    with sqlite3.connect(edb.db_path) as conn:
        conn.executemany("INSERT INTO logging_universe (ticker, category, enrolled_ts_utc, last_seen_ts_utc) "
                         "VALUES (?, ?, 1, 1)", [("MU", "user_persisted"), ("SPY", "core"),
                                                 ("$SPX", "pinned"), ("$VIX", "panel_auto")])
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_logger_tickers", [])
    server._hydrate_logger_tickers_from_db()
    assert server._logger_tickers == board_tickers(edb.db_path) == ["$SPX", "$VIX", "MU", "SPY"]


def test_the_board_is_what_the_table_holds_no_symbol_list_adds_to_it(tmp_path, monkeypatch):
    """2026-09-28 audit: the console enrolled $VIX at every start from a hand-kept list
    (market_context.py) beside the streamed context list (MARKET_CONTEXT_SYMBOLS). Reading the
    board writes no row: an empty table is an empty board, for every instrument type."""
    import server
    from db import EdDB
    edb = EdDB(tmp_path / "empty.db")
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_logger_tickers", ["STALE"])
    server._hydrate_logger_tickers_from_db()
    assert server._logger_tickers == []


def test_the_console_status_line_counts_live_prices_across_the_board(monkeypatch):
    """2026-09-28 audit: the console's status line judged the live price by SPY alone. It now
    counts every board ticker's price row (an index, an ETF, a single name, an arbitrary one)."""
    import server
    live = {"$SPX": 7690.19, "QQQ": None, "MU": 161.2, "ZZQX": None}
    monkeypatch.setattr(server, "_logger_tickers", list(live))
    monkeypatch.setattr(server, "resolve_spot", lambda tk: (live[tk], "plane", None))
    assert "live prices: 2 of 4 board tickers" in server._status_line(0.0)   # no daemon heartbeat at t=0
