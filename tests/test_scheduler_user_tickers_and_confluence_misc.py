"""The ticker board: which symbols are valid, and the one reader both processes use."""

from __future__ import annotations


def test_board_validity_is_the_symbols_form_never_a_list_of_names():
    """TICK-04 (2026-09-28 audit): SP, IW and NV were refused by name (and pruned from the board
    at every start), whatever Schwab says about them. A well-formed symbol is valid for any
    instrument type; whether it is real is Schwab's answer to its chain request."""
    from production_universe import is_valid_production_ticker
    assert all(is_valid_production_ticker(s) for s in ("SP", "IW", "NV", "SPY", "MU", "SPX", "$VIX", "$SP"))
    assert not any(is_valid_production_ticker(s) for s in ("", "$", "TOOLONGX"))


def _daemon_reading(db):
    """The capture daemon as it starts: the board read from the table, carried on its heartbeat
    to the console."""
    import live_market_plane as lmp
    from app.market_data.schwab.streaming import capture
    from calibration.complete_chain_capture import board_tickers
    from stream_spine import HealthRegistry, MessageBus
    d = capture.Daemon(MessageBus(), HealthRegistry(), board=board_tickers(db))
    lmp.record_feed_heartbeat(d.status())
    return d


def test_the_console_and_the_daemon_hold_one_board(tmp_path):
    """ONE-13 (2026-09-28 audit), and one list (2026-10-01): the console kept its own copy of the
    board, read at its startup. The daemon reads the table once; the console carries the
    daemon's board from its heartbeat: every enrolled row, whatever its category (user, index,
    ETF, panel symbol), in one order."""
    import sqlite3

    import server
    from db import EdDB
    edb = EdDB(tmp_path / "board.db")
    with sqlite3.connect(edb.db_path) as conn:
        conn.executemany("INSERT INTO logging_universe (ticker, category, enrolled_ts_utc, last_seen_ts_utc) "
                         "VALUES (?, ?, 1, 1)", [("MU", "user_persisted"), ("SPY", "core"),
                                                 ("$SPX", "pinned"), ("$VIX", "panel_auto")])
    d = _daemon_reading(edb.db_path)
    assert d.board == server._board() == ["$SPX", "$VIX", "MU", "SPY"]


def test_a_first_run_with_no_database_starts_with_an_empty_board(tmp_path):
    """2026-10-01 audit: the daemon read the board read-only before the console had created the
    database, so on a first run it died before its Schwab connection."""
    from calibration.complete_chain_capture import board_tickers
    assert board_tickers(tmp_path / "not_created_yet.db") == []


def test_a_row_that_is_not_a_symbol_is_not_on_the_board(tmp_path):
    """2026-10-01 audit: with the start-up prune gone, a malformed row ("$") was streamed."""
    import sqlite3

    from calibration.complete_chain_capture import board_tickers
    from db import EdDB
    edb = EdDB(tmp_path / "board.db")
    with sqlite3.connect(edb.db_path) as conn:
        conn.executemany("INSERT INTO logging_universe (ticker, category, enrolled_ts_utc, last_seen_ts_utc) "
                         "VALUES (?, 'user_persisted', 1, 1)", [("$",), ("SPY",)])
    assert board_tickers(edb.db_path) == ["SPY"]


def test_a_heartbeat_with_no_board_is_an_unknown_board_never_an_empty_one():
    """2026-10-01 audit: a daemon that sends no board (one from before this change) read as an
    empty board, and the console dropped every ticker's levels each second."""
    import time

    import live_market_plane as lmp
    import server
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True})
    assert server._board() is None


def test_a_row_stored_in_another_form_is_its_key(tmp_path):
    """2026-10-01 audit: with the start-up prune gone, a row stored as bare "SPX" would have been
    streamed as "SPX"."""
    import sqlite3

    from db import EdDB
    edb = EdDB(tmp_path / "board.db")
    with sqlite3.connect(edb.db_path) as conn:
        conn.executemany("INSERT INTO logging_universe (ticker, category, enrolled_ts_utc, last_seen_ts_utc) "
                         "VALUES (?, 'user_persisted', 1, 1)", [("SPX",), ("spy",)])
    d = _daemon_reading(edb.db_path)
    assert d.board == ["$SPX", "SPY"]


def test_the_board_is_what_the_table_holds_no_symbol_list_adds_to_it(tmp_path):
    """2026-09-28 audit: the console enrolled $VIX at every start from a hand-kept list
    (market_context.py) beside the streamed context list. Reading the board writes no row: an
    empty table is an empty board, for every instrument type."""
    import server
    from db import EdDB
    edb = EdDB(tmp_path / "empty.db")
    _daemon_reading(edb.db_path)
    assert server._board() == []


def test_the_console_status_line_counts_live_prices_across_the_board(monkeypatch):
    """2026-09-28 audit: the console's status line judged the live price by SPY alone. It now
    counts every board ticker's price row (an index, an ETF, a single name, an arbitrary one)."""
    import time

    import live_market_plane as lmp
    import server
    live = {"$SPX": 7690.19, "QQQ": None, "MU": 161.2, "ZZQX": None}
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "board": list(live)})
    monkeypatch.setattr(server, "resolve_spot", lambda tk: (live[tk], "plane", None))
    assert "live prices: 2 of 4 board tickers" in server._status_line()
