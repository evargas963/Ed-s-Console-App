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


def test_bare_index_root_gets_index_protections_f1():
    """Cursor-audit F1: an index root typed/POSTed BARE ('SPX', no $) must get the same $-gated
    protections as '$SPX'. The analytics/state/warm entry points never canonicalized via
    ticker_storage_key, so a bare root took the equity path. The strike-width/date faucets were
    retired 2026-09-25 (every level fetch takes the full chain), so what remains to lock is the
    normalization itself."""
    from instrument_identity import ticker_storage_key

    for bare, dollar in (("SPX", "$SPX"), ("RUT", "$RUT"), ("VIX", "$VIX"), ("NDX", "$NDX")):
        assert ticker_storage_key(bare) == dollar


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


def test_logger_quarantines_permanently_refused_symbol_f4(monkeypatch):
    """Cursor-audit F4: the background logger re-requested a PERMANENTLY vendor-refused symbol
    (SATS returns 404) every cycle, burning one of the two scarce chain-gate slots the healthy book
    needs — the terrain loop had the quarantine protection, the logger did not. The logger now
    shares the per-symbol quarantine book: after TERRAIN_QUARANTINE_HARD_FAILS consecutive 4xx it
    returns 'skipped:quarantined' and issues NO vendor call. A 5xx (transient) must stay a soft
    backoff, never a permanent quarantine (fail-closed classification)."""
    import server as srv
    from fastapi import HTTPException
    from instrument_identity import ticker_storage_key

    sym = "ZZQTEST"
    tk = ticker_storage_key(sym)
    monkeypatch.setattr(srv, "_is_loggable_session", lambda: True)

    def _reset():
        srv._terrain_quarantine.pop(tk, None)
        srv._terrain_consecutive_fails.pop(tk, None)

    # 404 (permanent symbol refusal) -> hard -> quarantined after the threshold
    _reset()
    monkeypatch.setattr(srv, "_fetch_state",
                        lambda *a, **k: (_ for _ in ()).throw(
                            HTTPException(status_code=502, detail="Chain fetch failed [vendor_status=404]")))
    for _ in range(srv.TERRAIN_QUARANTINE_HARD_FAILS):
        assert srv._logger_fetch_and_log(sym).startswith("error:")
    assert srv._logger_fetch_and_log(sym) == "skipped:quarantined", "a 404 symbol must stop being requested"
    assert srv.terrain_quarantine_reason(sym).startswith("QUARANTINED")

    # 503 (transient venue error) -> soft -> backoff, NEVER a permanent quarantine
    _reset()
    monkeypatch.setattr(srv, "_fetch_state",
                        lambda *a, **k: (_ for _ in ()).throw(
                            HTTPException(status_code=502, detail="Chain fetch failed [vendor_status=503]")))
    for _ in range(srv.TERRAIN_QUARANTINE_HARD_FAILS):
        srv._logger_fetch_and_log(sym)
    assert not srv.terrain_quarantine_reason(sym).startswith("QUARANTINED"), (
        "a 5xx transient error must be a soft backoff, not a permanent quarantine")
    _reset()


def test_enrollment_probe_rejects_non_collectors_f5(monkeypatch):
    """Cursor-audit F5: enrollment must PROVE collectability (quote 200 + option chain 200 with
    >=1 contract), not merely validate string shape. A yield index with no chain ($TNX-like) and a
    vendor-refused symbol (SATS-like 404) are rejected; a real optionable symbol passes; and
    _add_logger_ticker refuses to enroll a probe-failing symbol (no commit)."""
    import server as srv

    class _Resp:
        def __init__(self, code, payload=None):
            self.status_code = code
            self._p = payload or {}

        def json(self):
            return self._p

    monkeypatch.setattr(srv, "get_client", lambda: object())
    # the probe reads the front listed expiry's full chain (_fetch_state_chain)
    from datetime import date as _date
    monkeypatch.setattr(srv, "_listed_expiries", lambda client, t: [_date(2030, 1, 18)])

    # SATS-like: the vendor refuses the symbol outright (quote 404)
    monkeypatch.setattr(srv, "_memoized_quote_response", lambda t, client=None: _Resp(404))
    ok, why = srv._enrollment_collectability_probe("SATS")
    assert ok is False and "quote" in why, why

    # $TNX-like: a quote exists, but there is NO option chain (200 with zero contracts)
    monkeypatch.setattr(srv, "_memoized_quote_response", lambda t, client=None: _Resp(200, {"x": 1}))
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_Resp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.0))
    ok, why = srv._enrollment_collectability_probe("$TNX")
    assert ok is False and ("chain" in why or "contract" in why), why

    # a real optionable symbol: quote 200 + chain 200 carrying a contract -> collectable
    # institutional-synthetic-ok: the probe is unit-tested with a mocked vendor; a minimal
    # single-contract chain proves the >=1-contract branch without a live Schwab fetch.
    good = {"callExpDateMap": {"2030-01-18:1200": {"100.0": [{"strikePrice": 100.0, "putCall": "CALL",
            "openInterest": 10, "multiplier": 100}]}}, "putExpDateMap": {}}
    monkeypatch.setattr(srv, "_gated_safe_get_chain", lambda *a, **k: (_Resp(200, good), 0.0, 0.0))
    ok, why = srv._enrollment_collectability_probe("AAPL")
    assert ok is True, why

    # integration: _add_logger_ticker refuses a probe-failing symbol before any commit
    monkeypatch.setattr(srv, "_enrollment_collectability_probe", lambda t: (False, "no option chain"))
    monkeypatch.setattr(srv, "_HAS_SIGNALS", False)
    assert srv._add_logger_ticker("NOCH", enrollment_source="test") is False
