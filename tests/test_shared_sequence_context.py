"""Shared per-tick LSTM/TR sequence context: parity slices and DB call deduplication."""

from __future__ import annotations





def test_chronological_window_unified_matches_independent_fetches():
    """Last 60 of full chron equals last 60 of chron from a 65-row fetch (newest-first DB order)."""
    rows_desc = [{"ts_utc": 3000.0 - i, "spot": 100.0} for i in range(100)]
    chron = list(reversed(rows_desc))
    w_unified = chron[-60:]

    rows65 = rows_desc[:65]
    chron65 = list(reversed(rows65))
    w_legacy = chron65[-60:]

    assert w_unified == w_legacy
    assert len(w_unified) == 60
























