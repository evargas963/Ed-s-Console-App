"""STACK-VERIFY-CAND-LOAD-TICKERS-RETURN-TYPE: typed return contract guard.

`load_user_scheduler_tickers` now returns `Optional[list[str]]` — None on DB
failure, distinct from empty list ("DB OK but nobody enrolled"). Legacy callers
that want the pre-fix `list[str]` semantic call `load_user_scheduler_tickers_or_empty()`.

This file pins:
- The typed function's None branch on DB failure.
- The convenience wrapper returns [] on DB failure.
- Every existing production caller uses the `_or_empty` wrapper (no caller
  accidentally feeds None into list-comprehension or filter_valid_tickers).
"""

from __future__ import annotations


def test_board_validity_is_the_symbols_form_never_a_list_of_names():
    """TICK-04 (2026-09-28 audit): SP, IW and NV were refused by name (and pruned from the board
    at every start), whatever Schwab says about them. A well-formed symbol is valid for any
    instrument type; whether it is real is Schwab's answer to its chain request."""
    from production_universe import filter_valid_tickers, is_valid_production_ticker
    assert all(is_valid_production_ticker(s) for s in ("SP", "IW", "NV", "SPY", "MU", "SPX", "$VIX", "$SP"))
    assert not any(is_valid_production_ticker(s) for s in ("", "$", "TOOLONGX"))
    assert filter_valid_tickers(["nv", "NV", "spx", None]) == ["NV", "$SPX"]


def test_the_console_and_the_daemon_hold_one_board(tmp_path, monkeypatch):
    """ONE-13 (2026-09-28 audit): the console built its roster by merging an (empty) built-in
    list with the table's rows by category and a pass-through filter; the daemon read the table
    with board_tickers. The console now reads the board with that same reader: every enrolled
    row, whatever its category (user, index, ETF, panel symbol), in one order."""
    import json

    import server
    from calibration.complete_chain_capture import board_tickers
    from db import EdDB
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(["mu", "SPY"]), encoding="utf-8")
    edb = EdDB(tmp_path / "board.db")
    edb.logging_universe_migrate_legacy_json_file(primary_path=legacy, archive_path=tmp_path / "a.json",
                                                  core_tickers=[])
    edb.logging_universe_sync_panel_auto(["QQQ", "TLT"], 1.0)
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_market_context_panel_auto_candidates", lambda: ["QQQ", "TLT"])
    monkeypatch.setattr(server, "_logger_tickers", [])
    server._hydrate_logger_tickers_from_db()
    assert server._logger_tickers == board_tickers(edb.db_path)
    assert {"MU", "SPY", "QQQ", "TLT"} <= set(server._logger_tickers)


def test_retired_chg_map_cannot_alias_goog_onto_googl():
    """The GOOG/GOOGL alias lived in the retired weighted-push map. Absence is the pin."""
    import market_context as mc

    assert not hasattr(mc, "SYMBOL_TO_SNAPSHOT_CHG_COL")
    assert not hasattr(mc, "snapshot_row_chg_map")


def test_no_stored_percent_change_patches_a_live_confluence_value():
    """Audit P0 (2026-09-23): a missing live confluence value was patched from the latest
    stored %-change with no age limit. That path is gone -- missing stays missing."""
    import db as db_mod
    import market_context
    assert not hasattr(market_context, "patch_context_confluence_from_quote_ticks")
    assert not hasattr(db_mod.EdDB, "fetch_latest_confluence_quote_chg")
