"""RC-482/RC-483: the background roster includes panel_auto, and index books get a
budget-safe cold-start width so they can collect at all.

WHAT WAS MEASURED (production DB, 2026-08-25): 17 panel_auto tickers had ZERO snapshots
since 2026-05-27 — not because of the (already-neutered) filter, but because the roster
CONSTRUCTION loop only appended user_persisted/pinned, silently dropping panel_auto while
the docstring claimed full rotation. And $SPX (pinned index) went from 12,190 rows to zero
on 2026-07-26: at cold start its chain request (equity default width x ~98 expiries) blew
Schwab's 6,600-contract budget -> HTTP 502 -> geometry never learned -> permanent 502.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from db import EdDB  # noqa: E402


def test_panel_auto_enters_the_background_roster(monkeypatch, tmp_path):
    import server as srv

    edb = EdDB(tmp_path / "roster.db")
    now = time.time()
    edb.logging_universe_sync_core(["SPY"], now)
    edb.logging_universe_upsert_user_persisted("AUD1", "t", now + 1)
    edb.logging_universe_upsert_pinned("AUDP", "t", now + 2)
    edb.logging_universe_sync_panel_auto(["WMT", "FN"], now + 3)  # real valid panel symbols

    monkeypatch.setattr("db._db_instance", edb)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    # Keep the synthetic panel_auto rows: the real market_context sync would overwrite them
    # with the live panel (this test asserts roster INCLUSION of panel_auto, not its content).
    monkeypatch.setattr(srv, "_sync_market_context_panel_into_logging_universe",
                        lambda *a, **k: None)
    prev_core = list(srv.CORE_TICKERS)
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        roster = {t.upper() for t in srv._load_persisted_tickers()}
    finally:
        srv.CORE_TICKERS[:] = prev_core
    assert {"WMT", "FN"} <= roster, (
        "RC-483: panel_auto tickers must be in the background full-snapshot roster")
    assert {"SPY", "AUD1", "AUDP"} <= roster    # the pre-existing categories still present


def test_index_book_width_is_fixed_and_date_bounded_under_budget():
    """RC-494: index books get a FIXED width (deterministic — no geometry feedback loop) and
    a bounded DTE horizon (to_date), so width x 2 x (expiries in the window) stays under the
    vendor contract budget. This replaces the RC-491 cold-start width, which was still too
    wide for $SPX's full book (>100 expiries)."""
    import server as srv

    w = srv.resolve_chain_strike_count("$SPX")
    assert w == srv.INDEX_CHAIN_STRIKE_COUNT
    # The 45-day horizon bounds SPX to ~34 expiries; even a conservative 55 stays under budget.
    assert w * 2 * 55 <= srv.SCHWAB_CHAIN_CONTRACT_BUDGET, (
        f"index width {w} x 55 expiries blows the {srv.SCHWAB_CHAIN_CONTRACT_BUDGET} budget")
    # The index date bound is set; equities fetch the full book (None).
    assert srv._chain_to_date_for("$SPX") is not None
    assert srv._chain_to_date_for("$VIX") is not None
    # RC-494 robustness: an EXPLICIT far-dated index expiry extends the fetch to include it
    # (else the downstream single-expiry slice would be empty and error); the auto path stays
    # near-term.
    far = "2027-12-17"
    assert srv._chain_to_date_for("$SPX", far) == far
    assert srv._chain_to_date_for("$SPX", None) != far
    # A near expiry inside the horizon does NOT shorten the bound (still the 45-day horizon).
    assert srv._chain_to_date_for("$SPX", "2020-01-01") == srv._chain_to_date_for("$SPX")


def test_bare_index_root_gets_index_protections_f1():
    """Cursor-audit F1: an index root typed/POSTed BARE ('SPX', no $) must get the same $-gated
    protections as '$SPX'. The analytics/state/warm entry points never canonicalized via
    ticker_storage_key, so a bare root took the equity path — no width cap, no date bound — and
    requested the full multi-year book (the RC-491 502). The width/date faucets now normalize
    their own input, and _fetch_state normalizes at its single chokepoint."""
    import server as srv
    from instrument_identity import ticker_storage_key

    for bare, dollar in (("SPX", "$SPX"), ("RUT", "$RUT"), ("VIX", "$VIX"), ("NDX", "$NDX")):
        assert ticker_storage_key(bare) == dollar
        assert srv.resolve_chain_strike_count(bare) == srv.INDEX_CHAIN_STRIKE_COUNT, (
            f"bare {bare} bypassed the fixed index width")
        assert srv._chain_to_date_for(bare) is not None, f"bare {bare} bypassed the index date bound"
        assert srv._chain_to_date_for(bare) == srv._chain_to_date_for(dollar)
    # equities are untouched — full book (no date bound)
    assert srv._chain_to_date_for("AAPL") is None


def test_far_selected_index_expiry_is_single_expiry_window_f2():
    """Cursor-audit F2: extending to_date to a far selected expiry WITHOUT bounding from_date made
    Schwab return every expiry from today through that far date (60*2*~150 ≈ 18k contracts, over
    the 6,600 budget) even though _fetch_state then slices to that one expiry and discards the
    rest. from_date is now bounded to the same far date, so the window is [sel, sel] — a single
    expiry (60*2 = 120)."""
    import server as srv

    far = "2027-12-17"
    # far pick: BOTH ends bound to the selected expiry -> one expiry, trivially under budget
    assert srv._chain_to_date_for("$SPX", far) == far
    assert srv._chain_from_date_for("$SPX", far) == far
    assert srv.INDEX_CHAIN_STRIKE_COUNT * 2 * 1 <= srv.SCHWAB_CHAIN_CONTRACT_BUDGET
    # auto path / no expiry: open near end (Schwab defaults to today), bounded far end (horizon)
    assert srv._chain_from_date_for("$SPX", None) is None
    assert srv._chain_from_date_for("$SPX") is None
    # near pick (inside the 45-day window, already budget-safe): near edge stays open
    assert srv._chain_from_date_for("$SPX", "2020-01-01") is None
    # equities never get a near bound; bare index root is protected too (F1 composition)
    assert srv._chain_from_date_for("NVDA", far) is None
    assert srv._chain_from_date_for("SPX", far) == far


def test_equity_width_and_full_book_unchanged():
    import server as srv

    # A non-index symbol keeps the equity cold-start width and full-book fetch (no date bound).
    assert srv.resolve_chain_strike_count("NEVERSEEN_EQ") == srv.TERRAIN_STRIKE_COUNT_COLD_START
    assert srv._chain_to_date_for("NEVERSEEN_EQ") is None
    assert srv._chain_to_date_for("NVDA") is None


def test_tnx_is_yield_only_not_snapshot_enrolled():
    """RC-495: $TNX (10Y Treasury yield index) has NO options chain, so it can never produce a
    snapshot — enrolling it made a permanent non-collector against universal collection. It is
    excluded from the snapshot-enrollment panel; its yield still feeds the bond signal via the
    independent direct quote fetch."""
    import market_context as mc
    from market_context import market_context_panel_symbols_excluding_core

    panel = market_context_panel_symbols_excluding_core(frozenset(["SPY", "QQQ", "IWM"]))
    assert "$TNX" not in panel, "$TNX has no options chain — must not be snapshot-enrolled"
    assert "$VIX" in panel, "$VIX is optionable and stays enrolled"
    assert '_fetch("$TNX")' in open(mc.__file__, encoding="utf-8").read(), (
        "the yield/bond-signal fetch for $TNX must be preserved")
