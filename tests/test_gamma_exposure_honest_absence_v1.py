"""A strike whose open interest Schwab did not report never shows its 0.0 accumulator as a
computed exposure; a strike whose open interest Schwab reported as 0 shows 0 (operator ruling
2026-09-27, take what Schwab sends -- superseding the 2026-09-14 rule that showed a reported 0 as
absent); a genuinely netted zero shows 0.
"""
from __future__ import annotations

import time

import server
from math_exposure_core import compute_exposures_by_strike, exposure_books
from server import project_gamma_surface
from terrain_engine import compute_terrain
from terrain_engine import _per_strike_rows


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
        assert body["rows"] == [], f"a chain with no reported OI yields no rows: {body['rows']}"
        # no rows is shown absent with its reason, the one rule for the vanna and charm panels
        assert body["available"] is False and body["reason"]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


# ---------------------------------------------------------- 2. a genuine zero still renders ----

def test_real_oi_that_nets_to_exactly_zero_terrain_row_is_zero_not_dropped():
    chain = [_ct(100.0, "CALL", 500, gamma=0.04, delta=0.5),
             _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5)]
    exposures, _diag = compute_exposures_by_strike(chain, spot=SPOT)
    rows = _per_strike_rows(exposures)
    assert len(rows) == 1 and rows[0][0] == 100.0 and rows[0][1] == 0.0


