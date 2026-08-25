"""RC-483: the idle standing producer keeps ONLY enrolled cards warm.

WHAT WAS MEASURED (production DB, 2026-08-25): CRM and DKS wrote ~130 snapshots each with
logger_source NULL (the idle_key_refresh fingerprint) despite never being enrolled — a
viewed-once card, never evicted from _state_cache, was resurrected every idle cycle for the
rest of the process. This pins the fix: _select_idle_stale_keys returns a stale ENROLLED
card and skips an equally-stale UN-ENROLLED one.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import server as srv  # noqa: E402


def test_idle_producer_selects_enrolled_and_skips_unenrolled(monkeypatch):
    stale_ts = time.time() - 1_000_000.0   # far past any stale budget
    enrolled_key = ("ENRLD_T", "2099-01-01")
    orphan_key = ("ORPHN_T", "2099-01-01")

    cache_snapshot = dict(srv._state_cache)
    try:
        srv._state_cache.clear()
        srv._state_cache[enrolled_key] = {"ms_dict": {"ticker": "ENRLD_T"}, "ts": stale_ts}
        srv._state_cache[orphan_key] = {"ms_dict": {"ticker": "ORPHN_T"}, "ts": stale_ts}
        # Only ENRLD_T is in the enrolled-universe mirror.
        with srv._logger_lock:
            monkeypatch.setattr(srv, "_logger_tickers", ["ENRLD_T"], raising=False)
        selected = srv._select_idle_stale_keys(owned_keys=set(), max_keys=10)
        assert enrolled_key in selected, "an enrolled stale card must stay warm"
        assert orphan_key not in selected, (
            "RC-483: an un-enrolled viewed card must age out, not be resurrected")
    finally:
        srv._state_cache.clear()
        srv._state_cache.update(cache_snapshot)


def test_idle_producer_still_excludes_owned_enrolled_ticker(monkeypatch):
    """The pre-existing single-owner rule survives: a live-viewed ticker is still excluded
    even when enrolled (the viewer owns its refresh)."""
    stale_ts = time.time() - 1_000_000.0
    key = ("ENRLD_T", "2099-01-01")
    cache_snapshot = dict(srv._state_cache)
    try:
        srv._state_cache.clear()
        srv._state_cache[key] = {"ms_dict": {"ticker": "ENRLD_T"}, "ts": stale_ts}
        monkeypatch.setattr(srv, "_logger_tickers", ["ENRLD_T"], raising=False)
        owned = {("ENRLD_T", "2099-01-01")}
        assert srv._select_idle_stale_keys(owned_keys=owned, max_keys=10) == []
    finally:
        srv._state_cache.clear()
        srv._state_cache.update(cache_snapshot)
