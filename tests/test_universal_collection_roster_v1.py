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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))





def test_bare_index_root_gets_index_protections_f1():
    """Cursor-audit F1: an index root typed/POSTed BARE ('SPX', no $) must get the same $-gated
    protections as '$SPX'. The analytics/state/warm entry points never canonicalized via
    ticker_storage_key, so a bare root took the equity path. The strike-width/date faucets were
    retired 2026-09-25 (every level fetch takes the full chain), so what remains to lock is the
    normalization itself."""
    from instrument_identity import ticker_storage_key

    for bare, dollar in (("SPX", "$SPX"), ("RUT", "$RUT"), ("VIX", "$VIX"), ("NDX", "$NDX")):
        assert ticker_storage_key(bare) == dollar






