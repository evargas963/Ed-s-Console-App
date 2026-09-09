"""RC-UI-1 — proof that the Options/Gamma strike×expiry surface is a PROJECTION of the one
canonical exposure faucet (math_exposure_core.compute_exposures_by_strike), not a second GEX
producer. Covers the operator's required invariants A/B/C/D/F/G/H/I. D/E colour+format are
proven at the frontend formatter (heatmap view module); here we prove the data-level sign and
that the surface never recomputes GEX itself."""
import inspect

from server import project_gamma_surface
from math_exposure_core import compute_exposures_by_strike


def _c(strike, side, *, exp, dte, gamma=0.02, delta=0.5, oi=1000, vol=100, iv=20.0):
    return {
        "strikePrice": strike, "putCall": side, "expirationDate": exp,
        "daysToExpiration": dte, "openInterest": oi, "multiplier": 100,
        "totalVolume": vol, "bidSize": 10, "askSize": 10,
        "delta": delta if side == "CALL" else -abs(delta),
        "gamma": gamma, "volatility": iv,
    }


E1 = "2026-09-11"
E2 = "2026-09-18"
SPOT = 100.0


def _chain():
    return [
        _c(100, "CALL", exp=E1, dte=2, gamma=0.020, oi=1000),
        _c(100, "PUT",  exp=E1, dte=2, gamma=0.020, oi=500),
        _c(105, "CALL", exp=E1, dte=2, gamma=0.015, oi=300),
        _c(100, "CALL", exp=E2, dte=9, gamma=0.010, oi=800),
        _c(105, "CALL", exp=E2, dte=9, gamma=0.012, oi=400),
        _c(95,  "PUT",  exp=E2, dte=9, gamma=0.011, oi=600),
    ]


def _cell(surface, strike, expiry):
    try:
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == expiry][0]
        row = [r for r in surface["cells"] if r["strike"] == strike][0]
    except IndexError:
        return None
    return row["gex"][col]


# A. EXACT CELL EQUALITY — a surface cell equals the canonical faucet on that expiry's slice.
def test_A_cell_equals_canonical_faucet_per_expiry_slice():
    chain = _chain()
    surface = project_gamma_surface(chain, SPOT)
    for exp in (E1, E2):
        slice_e = [ct for ct in chain if ct["expirationDate"] == exp]
        exposures_e, _ = compute_exposures_by_strike(slice_e, spot=SPOT, require_oi=True)
        for k, bucket in exposures_e.items():
            assert _cell(surface, float(k), exp) == round(float(bucket["net_gex_1pct"]))


# B. ADDITIVITY / RECONCILIATION — per-expiry cells sum to the canonical full-book value.
def test_B_per_expiry_sum_reconciles_to_full_book():
    chain = _chain()
    full, _ = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    surface = project_gamma_surface(chain, SPOT)
    for k, bucket in full.items():
        # exact math additivity on the unrounded faucet output (the real proof)
        per_sum = 0.0
        for exp in (E1, E2):
            slice_e = [ct for ct in chain if ct["expirationDate"] == exp]
            ex_e, _ = compute_exposures_by_strike(slice_e, spot=SPOT, require_oi=True)
            if float(k) in ex_e:
                per_sum += float(ex_e[float(k)]["net_gex_1pct"])
        assert abs(per_sum - float(bucket["net_gex_1pct"])) < 1e-6
        # rounded display cells reconcile within rounding tolerance
        cell_sum = sum(v for v in [_cell(surface, float(k), E1), _cell(surface, float(k), E2)] if v is not None)
        assert abs(cell_sum - round(float(bucket["net_gex_1pct"]))) <= 2


# C. EXPIRY ISOLATION — changing E2 must not alter any E1 cell (shared spot is the only link).
def test_C_expiry_isolation():
    base = project_gamma_surface(_chain(), SPOT)
    mutated = _chain() + [_c(110, "CALL", exp=E2, dte=9, gamma=0.03, oi=5000)]
    after = project_gamma_surface(mutated, SPOT)
    for k in (95.0, 100.0, 105.0):
        assert _cell(base, k, E1) == _cell(after, k, E1)


# D. SIGN — a net-short-gamma strike stays negative through the projection (no inversion).
def test_D_sign_preserved():
    # put-heavy strike -> negative net_gex_1pct must survive as a negative cell
    chain = [
        _c(100, "CALL", exp=E1, dte=2, gamma=0.005, oi=100),
        _c(100, "PUT",  exp=E1, dte=2, gamma=0.05, oi=5000),
    ]
    surface = project_gamma_surface(chain, SPOT)
    cell = _cell(surface, 100.0, E1)
    full, _ = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    assert cell < 0
    assert (cell < 0) == (float(full[100.0]["net_gex_1pct"]) < 0)


# F. COMPLETENESS — every OI-bearing expiry and strike in the chain is represented.
def test_F_completeness():
    surface = project_gamma_surface(_chain(), SPOT)
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    assert set(surface["strikes"]) == {95.0, 100.0, 105.0}
    # native DTE carried onto the column header, not inferred
    dte = {e["expiry"]: e["dte"] for e in surface["expirations"]}
    assert dte == {E1: 2, E2: 9}


# G. MALFORMED / MISSING EXPIRY — excluded and counted, never reassigned to a column.
def test_G_malformed_expiry_excluded_not_reassigned():
    chain = _chain() + [
        _c(100, "CALL", exp=None, dte=2, gamma=0.02, oi=9999),
        _c(100, "CALL", exp="bad", dte=2, gamma=0.02, oi=9999),
    ]
    surface = project_gamma_surface(chain, SPOT)
    assert surface["contracts_excluded_malformed_expiry"] == 2
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    # the malformed OI (9999) must not have inflated the legitimate E1/E2 100-strike cells
    clean = project_gamma_surface(_chain(), SPOT)
    assert _cell(surface, 100.0, E1) == _cell(clean, 100.0, E1)
    assert _cell(surface, 100.0, E2) == _cell(clean, 100.0, E2)


# H. SPX / SPXW — canonical underlying->option-chain identity is unchanged; no UI translation.
def test_H_spx_identity_unchanged():
    from server import ticker_storage_key
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    # a SPXW-rooted synthetic chain projects without any symbol rewriting
    spxw = [
        {"strikePrice": 7690, "putCall": "CALL", "expirationDate": E1, "daysToExpiration": 1,
         "openInterest": 1000, "multiplier": 100, "totalVolume": 50, "delta": 0.5,
         "gamma": 0.002, "volatility": 12.0, "symbol": "SPXW  260911C07690000"},
    ]
    surface = project_gamma_surface(spxw, 7690.0)
    assert surface["expirations"] and surface["strikes"] == [7690.0]


# I. NO DUPLICATE PRODUCER — the surface code contains no GEX dollarization; it only reads the
#    faucet's net_gex_1pct output and calls compute_exposures_by_strike.
def test_I_no_second_gex_computation():
    src = inspect.getsource(project_gamma_surface)
    # the canonical dollarization ( gamma * oi * mult * spot*spot * 0.01 ) must NOT appear here
    assert "spot * spot" not in src and "spot*spot" not in src
    assert "* 0.01" not in src
    # the only exposure computation is the shared faucet
    assert "compute_exposures_by_strike" in src
    assert src.count("net_gex_1pct") >= 1  # read-only consumption of the faucet field
