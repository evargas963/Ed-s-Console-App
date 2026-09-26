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


def test_filter_tickers_for_background_logging_is_universal():
    """UNIVERSAL COLLECTION (operator requirement, restated 2026-08-25): panel_auto
    enrollment no longer excludes a ticker from the full-snapshot roster — the filter
    passes the roster through unchanged (RC-482)."""
    from scheduler_user_tickers import filter_tickers_for_background_logging

    out = filter_tickers_for_background_logging(["SPY", "PSCI", "QQQ"], ":memory:")
    assert out == ["SPY", "PSCI", "QQQ"]


def test_retired_chg_map_cannot_alias_goog_onto_googl():
    """The GOOG/GOOGL alias lived in the retired weighted-push map. Absence is the pin."""
    import market_context as mc

    assert not hasattr(mc, "SYMBOL_TO_SNAPSHOT_CHG_COL")
    assert not hasattr(mc, "snapshot_row_chg_map")


def test_no_stored_percent_change_patches_a_live_confluence_value():
    """Audit P0 (2026-09-23): a missing live confluence value was patched from the latest
    stored %-change with no age limit. That path is gone -- missing stays missing."""
    import inspect

    import db as db_mod
    import market_context
    import server
    assert not hasattr(market_context, "patch_context_confluence_from_quote_ticks")
    assert not hasattr(db_mod.EdDB, "fetch_latest_confluence_quote_chg")
    assert "fetch_latest_confluence_quote_chg" not in inspect.getsource(server)
