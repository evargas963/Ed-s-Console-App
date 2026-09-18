"""SPX honest-display fix (operator directive, 2026-09-14): a strike/expiry bucket that never
cleared the open-interest gate must never present its pre-initialized 0.0 accumulator as a
computed exposure value, and a persisted fallback chain must never be presented as today's data
when it is not.

Live-reproduced defect: Schwab's SPX chain feed returned openInterest=0 (a stuck vendor
snapshot) for every contract while SPY/QQQ were unaffected through the identical code path at
the same instant. `math_exposure_core.compute_exposures_by_strike` creates a strike bucket (via
`_strike_bucket`) BEFORE its own `require_oi` filter runs, so every accumulator on that bucket
(net_gex_1pct, net_dex_dollars, call_vanna/put_vanna...) stayed at its pre-initialized 0.0 --
indistinguishable, to a reader of the raw field, from a strike genuinely measured at flat
exposure. `has_oi` is the fix: set exactly when a contract actually clears the OI gate, checked
by every consumer before treating a bucket's numeric fields as real.

This file proves three things with synthetic (never live-vendor) chain data:
  1. Authoritative OI == 0 is ZERO OI and computed GEX $0. Missing OI is OI UNAVAILABLE.
     Null GEX is never read as NO OI.
  2. A genuinely computed zero (real OI on both sides, net exposure nets to exactly 0.0) still
     renders as a real 0 -- absence-detection must not swallow real measurements.
  3. The banked "morning reference" gamma-surface fallback may only populate a ticker's data
     from a chain captured on TODAY's ET session date, discloses a real elapsed-seconds age
     (never a bare boolean `stale`), and is never labelled live.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import timedelta

import server
from math_exposure_core import compute_exposures_by_strike
from server import get_options_gamma_surface, project_gamma_surface, ticker_storage_key
from terrain_engine import _per_strike_rows
from time_et import is_trading_day_et, now_et


def _ct(strike: float, side: str, oi, *, gamma=0.04, delta=0.5, iv=20.0, dte=5,
        exp="2026-09-18T20:00:00.000+00:00", vol=0):
    # institutional-synthetic-ok: honest-absence regression needs fully controlled OI/gamma
    # per leg to prove exact zero-vs-absent boundaries; no real capture can guarantee that.
    return {
        "strikePrice": strike, "putCall": side, "openInterest": oi, "multiplier": 100,
        "delta": delta if side == "CALL" else -abs(delta), "gamma": gamma,
        "volatility": iv, "totalVolume": vol, "bidSize": 1, "askSize": 1,
        "daysToExpiration": dte, "expirationDate": exp,
        "symbol": f"TEST  260918{'C' if side == 'CALL' else 'P'}{int(strike * 1000):08d}",
    }


SPOT = 100.0


# ---------------------------------------------------------------- 1. missing OI is absent ----

def test_zero_oi_everywhere_yields_has_oi_true_and_authoritative_zero():
    """Listed contracts reporting openInterest=0 are a measured zero, not absence."""
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    assert exposures, "buckets must still exist (created before the OI gate runs)"
    for k, b in exposures.items():
        assert b["has_oi"] is True, f"strike {k} must treat authoritative OI=0 as present"
        assert b["call_oi"] == 0.0
        assert b["put_oi"] == 0.0
        assert b["net_gex_1pct"] == 0.0


def test_zero_oi_everywhere_surface_reports_zero_gex_not_null_cells():
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    surface = project_gamma_surface(chain, SPOT)
    assert surface["gamma_available"] is True
    assert surface["cells"], "the strike axis is still built from the raw buckets"
    for row in surface["cells"]:
        assert row["gex"] == [0]
        assert row["dex"] == [0]
        assert row["value_states"] == ["zero_oi"]


def test_zero_oi_everywhere_terrain_per_strike_rows_draws_computed_zero_bars():
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    rows = _per_strike_rows(exposures, chain)
    assert len(rows) == 1 and rows[0][0] == 95.0 and rows[0][1] == 0.0


def test_vanna_by_strike_route_keeps_zero_oi_strikes_as_computed_zero():
    tk = server.ticker_storage_key("ZZTESTNOOI")
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_contracts_rest": chain, "_contracts_rest_spot": SPOT}
    try:
        import json
        body = json.loads(server.get_vanna_by_strike(ticker="ZZTESTNOOI").body)
        assert body["available"] is True
        strikes = {r[0] for r in body["rows"]}
        assert strikes == {95.0, 100.0}
        assert all(r[1] == 0.0 for r in body["rows"])
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


# ---------------------------------------------------------- 2. a genuine zero still renders ----

def test_real_oi_that_nets_to_exactly_zero_still_has_oi_true_and_reports_zero():
    """Equal call/put gamma exposure at real OI must still show as a real 0, not absence."""
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    b = exposures[100.0]
    assert b["has_oi"] is True
    assert b["net_gex_1pct"] == 0.0, "call and put gamma exposure must net to exactly zero"


def test_real_oi_that_nets_to_exactly_zero_surface_cell_is_zero_not_null():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    surface = project_gamma_surface(chain, SPOT)
    assert surface["gamma_available"] is True
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [0], f"a genuinely computed zero was suppressed as absence: {row}"


def test_real_oi_that_nets_to_exactly_zero_terrain_row_is_zero_not_dropped():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    rows = _per_strike_rows(exposures, chain)
    assert len(rows) == 1 and rows[0][0] == 100.0 and rows[0][1] == 0.0


def test_missing_oi_is_unavailable_not_zero():
    chain = [_ct(95.0, "CALL", None), _ct(95.0, "PUT", None)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    b = exposures[95.0]
    assert b["has_oi"] is False
    assert b["oi_absent"] is True
    surface = project_gamma_surface(chain, SPOT)
    row = [r for r in surface["cells"] if r["strike"] == 95.0][0]
    assert row["gex"] == [None]
    assert row["value_states"] == ["oi_unavailable"]


def test_a_mixed_chain_keeps_zero_oi_beside_the_netted_zero_strike():
    """Zero-OI listed contracts stay $0; real OI that nets to 0 stays a computed 0."""
    chain = [
        _ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
        _ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
        _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5),
    ]
    surface = project_gamma_surface(chain, SPOT)
    assert surface["gamma_available"] is True
    row95 = [r for r in surface["cells"] if r["strike"] == 95.0][0]
    row100 = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row95["gex"] == [0]
    assert row95["value_states"] == ["zero_oi"]
    assert row100["gex"] == [0]
    assert row100["value_states"] == ["computed"]


# ------------------------------------------ 3. persisted SPX fallback: date match + real age ----

class _FakeDB:
    def __init__(self, path):
        self.db_path = str(path)


def _seed_morning_full(path, ticker: str, et_date: str, ts_utc: float, spot: float,
                        chain_json: str = "[]"):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS option_chain_morning_full ("
        "ticker TEXT, et_date TEXT, ts_utc REAL, spot REAL, n_contracts INT, "
        "n_expiries INT, max_dte REAL, chain_json TEXT, source TEXT)"
    )
    con.execute(
        "INSERT INTO option_chain_morning_full "
        "(ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ticker, et_date, ts_utc, spot, 0, 0, None, chain_json, "test"),
    )
    con.commit()
    con.close()


def _clear_gamma_surface(tk):
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_a_prior_session_banked_chain_is_not_served_as_a_morning_reference(tmp_path, monkeypatch):
    """The exact hardening this fallback needed: reaching back past today's session is not a
    morning reference, it is an unlabeled multi-day-old snapshot -- must fall through to the
    explicit unavailable payload instead."""
    tk = ticker_storage_key("ZZTESTSTALE")
    _clear_gamma_surface(tk)
    db = tmp_path / "stale.db"
    # Walk back to a GENUINE prior trading day (weekday-only would still land on a market
    # holiday and make the test flaky against the real calendar).
    d = now_et() - timedelta(days=1)
    while not is_trading_day_et(d.strftime("%Y-%m-%d")):
        d -= timedelta(days=1)
    stale_et_date = d.strftime("%Y-%m-%d")
    _seed_morning_full(db, "ZZTESTSTALE", stale_et_date, time.time() - 90000, 100.0)
    monkeypatch.setattr(server, "get_db", lambda: _FakeDB(db))
    try:
        body = get_options_gamma_surface(ticker="ZZTESTSTALE")
        import json
        d = json.loads(body.body)
        assert d["available"] is False
        assert d["source"] != "banked_morning_reference"
        assert d["live"] is False
        assert "prior session" in d["reason"].lower()
    finally:
        _clear_gamma_surface(tk)


def test_a_same_session_banked_chain_is_served_with_a_real_disclosed_age(tmp_path, monkeypatch):
    """The positive control: today's own banked capture IS a legitimate morning reference, and
    must disclose a real elapsed-seconds age rather than a bare boolean stale/None."""
    tk = ticker_storage_key("ZZTESTTODAY")
    _clear_gamma_surface(tk)
    db = tmp_path / "today.db"
    today_et = now_et().strftime("%Y-%m-%d")
    captured_ts = time.time() - 1800.0   # captured 30 minutes ago
    _seed_morning_full(db, "ZZTESTTODAY", today_et, captured_ts, 101.5)
    monkeypatch.setattr(server, "get_db", lambda: _FakeDB(db))
    try:
        import json
        d = json.loads(get_options_gamma_surface(ticker="ZZTESTTODAY").body)
        assert d["available"] is False
        assert d["source"] == "unavailable"
        assert d["live"] is False
        assert d.get("historical_morning_available") is True
        assert d.get("historical_morning_et_date") == today_et
        assert "history" in (d.get("reason") or "").lower()
        assert d.get("cells") in (None, [])
    finally:
        _clear_gamma_surface(tk)
