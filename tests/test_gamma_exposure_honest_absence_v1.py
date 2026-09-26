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
  1. Missing/unusable OI reads as ABSENT (has_oi=False, gamma_available=False, cells None) --
     never a fabricated numeric zero.
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
from math_exposure_core import exposure_books
from server import get_options_gamma_surface, project_gamma_surface, ticker_storage_key
from terrain_engine import compute_terrain
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

def test_zero_oi_everywhere_yields_has_oi_false_not_a_fabricated_zero():
    """The exact live-SPX shape: every contract reports openInterest=0."""
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    assert exposures, "buckets must still exist (created before the OI gate runs)"
    for k, b in exposures.items():
        assert b["has_oi"] is False, f"strike {k} cleared has_oi with zero OI everywhere"
        assert b["net_gex_1pct"] == 0.0, "the raw accumulator is still its pre-init 0.0"


def test_zero_oi_everywhere_surface_reports_gamma_unavailable_and_null_cells():
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    surface = project_gamma_surface(chain, exposure_books(chain, spot=SPOT))
    assert surface["gamma_available"] is False
    assert surface["gamma_unavailable_reason"] is not None
    assert "no usable open interest" in surface["gamma_unavailable_reason"]
    assert surface["cells"], "the strike axis is still built from the raw buckets"
    for row in surface["cells"]:
        assert row["gex"] == [None]
        assert row["dex"] == [None]
        assert row["vanna"] == [None]


def test_zero_oi_everywhere_terrain_per_strike_rows_draws_no_bars():
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    rows = _per_strike_rows(exposures, chain)
    assert rows == [], f"drew a fabricated $0 bar for a no-OI strike: {rows}"


def test_vanna_by_strike_route_omits_no_oi_strikes_instead_of_a_fabricated_zero():
    tk = server.ticker_storage_key("ZZTESTNOOI")
    chain = [_ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),
             _ct(100.0, "CALL", 0), _ct(100.0, "PUT", 0)]
    with server._terrain_cache_lock:
        server._terrain_snapshots[tk] = compute_terrain(tk, chain, SPOT)
    try:
        import json
        body = json.loads(server.get_vanna_by_strike(ticker="ZZTESTNOOI").body)
        assert body["available"] is True
        assert body["rows"] == [], f"a no-OI chain must yield zero rows, not fabricated ones: {body['rows']}"
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
            server._terrain_snapshots.pop(tk, None)


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
    surface = project_gamma_surface(chain, exposure_books(chain, spot=SPOT))
    assert surface["gamma_available"] is True
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [0], f"a genuinely computed zero was suppressed as absence: {row}"


def test_real_oi_that_nets_to_exactly_zero_terrain_row_is_zero_not_dropped():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    rows = _per_strike_rows(exposures, chain)
    assert len(rows) == 1 and rows[0][0] == 100.0 and rows[0][1] == 0.0


def test_a_mixed_chain_keeps_the_no_oi_strike_absent_beside_the_real_zero_strike():
    """Negative + positive control in one chain: absence and a real zero must coexist correctly."""
    chain = [
        _ct(95.0, "CALL", 0), _ct(95.0, "PUT", 0),                     # no OI -> absent
        _ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
        _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5),                # real OI, nets to 0
    ]
    surface = project_gamma_surface(chain, exposure_books(chain, spot=SPOT))
    assert surface["gamma_available"] is True, "one real strike is enough to make the surface available"
    row95 = [r for r in surface["cells"] if r["strike"] == 95.0][0]
    row100 = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row95["gex"] == [None]
    assert row100["gex"] == [0]


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


def test_a_banked_chain_from_any_session_is_never_served_in_place_of_the_live_surface(tmp_path, monkeypatch):
    """Operator rule 2026-09-23 (no fallbacks): with no live surface the answer is
    unavailable -- a banked wide chain, even TODAY's, never stands in for it."""
    import json

    for name, et_date in (("ZZTESTSTALE", None), ("ZZTESTTODAY", now_et().strftime("%Y-%m-%d"))):
        tk = ticker_storage_key(name)
        _clear_gamma_surface(tk)
        db = tmp_path / f"{name}.db"
        if et_date is None:
            d = now_et() - timedelta(days=1)
            while not is_trading_day_et(d.strftime("%Y-%m-%d")):
                d -= timedelta(days=1)
            et_date = d.strftime("%Y-%m-%d")
        _seed_morning_full(db, name, et_date, time.time() - 1800.0, 100.0)
        monkeypatch.setattr(server, "get_db", lambda db=db: _FakeDB(db))
        try:
            body = json.loads(get_options_gamma_surface(ticker=name).body)
            assert body["available"] is False and body["source"] == "unavailable", name
            assert body["live"] is False
            assert "no live gamma surface" in body["reason"].lower()
        finally:
            _clear_gamma_surface(tk)


