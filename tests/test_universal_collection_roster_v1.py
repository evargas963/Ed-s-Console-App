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


def test_index_book_cold_start_is_budget_safe():
    import server as srv

    # A $-prefixed index with NO learned geometry (cold start). The width must keep the first
    # chain request under the vendor contract budget for a many-expiry book.
    width = srv.resolve_chain_strike_count("$NEVERSEEN_IDX")
    contracts_at_100_expiries = width * 2 * srv.INDEX_COLD_START_ASSUMED_EXPIRIES
    assert contracts_at_100_expiries <= srv.SCHWAB_CHAIN_CONTRACT_BUDGET, (
        f"index cold start {width} blows the {srv.SCHWAB_CHAIN_CONTRACT_BUDGET} budget")
    # $SPX's real ~98-expiry book must also fit at this cold-start width.
    assert width * 2 * 98 <= srv.SCHWAB_CHAIN_CONTRACT_BUDGET


def test_equity_cold_start_is_unchanged():
    import server as srv

    # A non-index symbol with no geometry still gets the equity cold-start default (not the
    # narrower index width) — the fix is scoped to index books only.
    assert srv.resolve_chain_strike_count("NEVERSEEN_EQ") == srv.TERRAIN_STRIKE_COUNT_COLD_START
