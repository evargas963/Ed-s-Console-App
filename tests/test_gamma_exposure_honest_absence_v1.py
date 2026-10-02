"""A strike whose open interest Schwab did not report never shows its 0.0 accumulator as a
computed exposure; a strike whose open interest Schwab reported as 0 shows 0 (operator ruling
2026-09-27, take what Schwab sends -- superseding the 2026-09-14 rule that showed a reported 0 as
absent); a genuinely netted zero shows 0; a banked chain never stands in for the live surface.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import timedelta

import server
from math_exposure_core import bucket_metric, compute_exposures_by_strike, exposure_books
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


# ------------------------------------------- 1. reported 0 is 0; unreported is absent ----

def _crwd():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                      .read_text(encoding="utf-8"))


def test_real_chain_reported_zero_oi_shows_zero_and_unreported_shows_absent(pin_clock):
    """Real CRWD chain. Stand-in: open interest removed from every contract at one strike, as
    Schwab never omitted it in the captures."""
    import copy
    pin_clock(2026, 9, 2, 12, 0)   # the chain's capture
    fx = _crwd()
    chain = copy.deepcopy(fx["chain"])
    ois = {}
    for c in chain:
        ois.setdefault(c["strikePrice"], []).append(c["openInterest"])
    zero_k = next(k for k, v in ois.items() if all(o == 0 for o in v))
    gone_k = next(k for k, v in ois.items() if k != zero_k)
    for c in chain:
        if c["strikePrice"] == gone_k:
            del c["openInterest"]
    surface = project_gamma_surface(chain, exposure_books(chain, spot=fx["spot"]))
    cell = {r["strike"]: r for r in surface["cells"]}
    assert all(v == 0 for v in cell[zero_k]["gex"] if v is not None) and cell[zero_k]["gex"] != [None]
    assert cell[gone_k]["gex"] == [None]
    exposures, _ = compute_exposures_by_strike(chain, spot=fx["spot"])
    assert exposures[zero_k]["net_gex_1pct"] == 0 and exposures[gone_k]["oi_unreported"] > 0
    rows = {r[0] for r in _per_strike_rows(exposures)}
    assert zero_k in rows and gone_k not in rows


def test_vanna_by_strike_route_omits_unreported_oi_strikes(pin_clock):
    import copy
    import json
    pin_clock(2026, 9, 2, 12, 0)   # the chain's capture
    fx = _crwd()
    chain = copy.deepcopy(fx["chain"])
    for c in chain:
        del c["openInterest"]
    tk = server.ticker_storage_key("ZZTESTNOOI")
    snap = compute_terrain(tk, chain, fx["spot"])
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"ticker": tk, "spot": fx["spot"], "computed_ts_utc": time.time(),
                                     "_vanna_rows": server._vanna_rows(snap)}
    try:
        body = json.loads(server.get_vanna_by_strike(ticker="ZZTESTNOOI").body)
        assert body["available"] is True
        assert body["rows"] == [], f"a chain with no reported OI yields no rows: {body['rows']}"
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


# ---------------------------------------------------------- 2. a genuine zero still renders ----

def test_real_oi_that_nets_to_exactly_zero_reports_zero():
    """Equal call/put gamma exposure at real OI must still show as a real 0, not absence."""
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT)
    b = exposures[100.0]
    assert bucket_metric(b, "net_gex_1pct") == 0.0,"call and put gamma exposure must net to exactly zero"


def test_real_oi_that_nets_to_exactly_zero_surface_cell_is_zero_not_null():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    surface = project_gamma_surface(chain, exposure_books(chain, spot=SPOT))
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [0], f"a genuinely computed zero was suppressed as absence: {row}"


def test_real_oi_that_nets_to_exactly_zero_terrain_row_is_zero_not_dropped():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT)
    rows = _per_strike_rows(exposures)
    assert len(rows) == 1 and rows[0][0] == 100.0 and rows[0][1] == 0.0


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

    import live_market_plane as lmp
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,     # both on the board
                               "board": ["ZZTESTSTALE", "ZZTESTTODAY"]}, time.time())
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
            # the reason is the ticker's refresh state, never a banked source
            assert body["reason"] == server.terrain_staleness(None, tk)["levels_stale_reason"], name
        finally:
            _clear_gamma_surface(tk)


