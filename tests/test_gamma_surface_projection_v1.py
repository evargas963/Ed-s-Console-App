"""RC-UI-1 — proof that the Options/Gamma strike×expiry surface is a PROJECTION of the one
canonical exposure faucet (math_exposure_core.compute_exposures_by_strike), not a second GEX
producer. Covers the operator's required invariants A/B/C/D/F/G/H on a REAL vendor chain
(MRVL's capture of 2026-10-07 10:31 ET, tests/real_chains.py: native ISO ``expirationDate``
stamps, zero-OI rows), so the projection is proven on the field shapes production actually feeds
it (flatten_chain_contracts passes Schwab rows through verbatim). D/E colour+format are proven at
the frontend formatter (heatmap view module).

Two expiries: MRVL's first two, 2026-10-09 and 2026-10-16, from the one capture, valued at its
capture instant (`now`, an input: every computation below prices at the same instant, so each
identity is exact).
"""
import json

from server import project_gamma_surface
from math_exposure_core import (bucket_metric, compute_exposures_by_strike, exposure_books,
                                strike_oi_legs, strike_volume_legs)
from tests.real_chains import MRVL

NOW = MRVL.now
SPOT = MRVL.spot


def _exp_key(ct: dict) -> str:
    """The projection's own column key rule: the native expirationDate's first 10 chars."""
    return str(ct.get("expirationDate") or "")[:10]


E1, E2 = sorted({_exp_key(ct) for ct in MRVL.chain})[:2]      # 2026-10-09, 2026-10-16


def _chain() -> list[dict]:
    return [dict(ct) for ct in MRVL.chain if _exp_key(ct) in (E1, E2)]


def _slice(chain: list[dict], exp: str) -> list[dict]:
    return [ct for ct in chain if _exp_key(ct) == exp]


def _surface(chain: list[dict], spot: float) -> dict:
    """The grid as _publish_levels builds it: shaped from the chain's exposure_books."""
    return project_gamma_surface(chain, exposure_books(chain, spot=spot, now=NOW))


def _cell(surface, strike, expiry):
    try:
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == expiry][0]
        row = [r for r in surface["cells"] if r["strike"] == strike][0]
    except IndexError:
        return None
    return row["gex"][col]


def test_fixture_preconditions_are_real_two_expiry_input():
    """Two distinct native expirations with OI-bearing rows on both."""
    chain = _chain()
    assert (E1, E2) == ("2026-10-09", "2026-10-16")
    assert sum(1 for ct in _slice(chain, E1) if (ct.get("openInterest") or 0) > 0) > 0
    assert sum(1 for ct in _slice(chain, E2) if (ct.get("openInterest") or 0) > 0) > 0
    # the native stamp is the ISO form production feeds the projection, not a bare date
    assert "T" in str(chain[0]["expirationDate"])


# A. EXACT CELL EQUALITY — a surface cell equals the canonical faucet on that expiry's slice.
def test_A_cell_equals_canonical_faucet_per_expiry_slice():
    chain = _chain()
    surface = _surface(chain, SPOT)
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    checked = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)
        assert exposures_e, f"the real {exp} slice must yield OI-bearing strikes"
        for k, bucket in exposures_e.items():
            # every listed strike's cell is the book's own value, unrounded: 0 where its
            # contracts have open interest 0, None only where a term Schwab did not send is
            # missing (bucket_metric, the one reader)
            assert _cell(surface, float(k), exp) == bucket_metric(bucket, "net_gex_1pct")
            checked += 1
    assert checked > 20   # a real book, not a handful of strikes


# B. ADDITIVITY / RECONCILIATION — per-expiry cells sum to the canonical full-book value.
def test_B_per_expiry_sum_reconciles_to_full_book():
    chain = _chain()
    full, _ = compute_exposures_by_strike(chain, spot=SPOT, now=NOW)
    surface = _surface(chain, SPOT)
    per = {exp: compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)[0]
           for exp in (E1, E2)}
    for k, bucket in full.items():
        # exact math additivity on the unrounded faucet output (the real proof)
        per_sum = sum(float(per[exp][float(k)]["net_gex_1pct"]) for exp in (E1, E2) if float(k) in per[exp])
        assert abs(per_sum - float(bucket["net_gex_1pct"])) < 1e-6
        # the unrounded cells reconcile to the full book's known net
        cells = [_cell(surface, float(k), E1), _cell(surface, float(k), E2)]
        if bucket_metric(bucket, "net_gex_1pct") is not None:
            assert abs(sum(v for v in cells if v is not None) - bucket_metric(bucket, "net_gex_1pct")) < 1e-6


# C. EXPIRY ISOLATION — changing the E2 slice must not alter any E1 cell (shared spot is the
#    only link). The mutation is a REAL subset: every other E2 row removed.
def test_C_expiry_isolation():
    chain = _chain()
    base = _surface(chain, SPOT)
    kept_e2 = _slice(chain, E2)[::2]
    after = _surface(_slice(chain, E1) + kept_e2, SPOT)
    e1_strikes = [k for k in base["strikes"] if _cell(base, k, E1) is not None]
    assert e1_strikes
    for k in e1_strikes:
        assert _cell(base, k, E1) == _cell(after, k, E1)
    # the mutation was material to E2 (otherwise isolation would be proven vacuously)
    assert any(_cell(base, k, E2) != _cell(after, k, E2) for k in base["strikes"])


# F. INPUT-PROJECTION COVERAGE — every OI-bearing expiry/strike IN THE SUPPLIED CHAIN is projected.
def test_F_input_projection_coverage():
    chain = _chain()
    surface = _surface(chain, SPOT)
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    expected_strikes = set()
    for exp in (E1, E2):
        expected_strikes |= {float(k) for k in compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)[0]}
    assert set(surface["strikes"]) == expected_strikes
    # native DTE carried onto the column header, not inferred
    native_dte = {exp: next(int(ct["daysToExpiration"]) for ct in _slice(chain, exp) if ct.get("daysToExpiration") is not None)
                  for exp in (E1, E2)}
    assert {e["expiry"]: e["dte"] for e in surface["expirations"]} == native_dte
    assert surface["contracts_total"] == len(chain)
    assert surface["contracts_used"] == len(chain)


# G. MALFORMED / MISSING EXPIRY — excluded and counted, never reassigned to a column. The malformed
#    rows are REAL rows with their native expirationDate broken (the only field under test).
def test_G_malformed_expiry_excluded_not_reassigned():
    clean_chain = _chain()
    probe = max(_slice(clean_chain, E1), key=lambda ct: ct.get("openInterest") or 0)   # the heaviest real row
    chain = clean_chain + [dict(probe, expirationDate=None), dict(probe, expirationDate="bad")]
    surface = _surface(chain, SPOT)
    assert surface["contracts_excluded_malformed_expiry"] == 2
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    # the malformed OI must not have inflated the legitimate cells at that strike
    clean = _surface(clean_chain, SPOT)
    k = float(probe["strikePrice"])
    assert _cell(surface, k, E1) == _cell(clean, k, E1)
    assert _cell(surface, k, E2) == _cell(clean, k, E2)


# H. SPX / SPXW — canonical underlying->option-chain identity is unchanged; no UI translation.
def test_H_spx_identity_unchanged():
    from server import ticker_storage_key
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    # an SPXW-rooted contract projects without any symbol rewriting: a REAL vendor row re-rooted
    # to an SPXW symbol and strike, which is the only thing this identity check reads.
    probe = max(_slice(_chain(), E1), key=lambda ct: ct.get("openInterest") or 0)
    spxw = [dict(probe, symbol="SPXW  261009C07690000", strikePrice=7690)]
    surface = _surface(spxw, 7690.0)
    assert surface["expirations"] and surface["strikes"] == [7690.0]


# J. LIVE-HEATMAP CONTRACT IDENTITY (state-authority review, 2026-09-12) — every cell must carry
#    the vendor OSI symbol(s) that produced it, verbatim. Never invented: read straight off the
#    same real contract rows compute_exposures_by_strike already aggregates for this cell.
def test_J_cell_carries_the_real_vendor_symbols_for_its_strike_and_expiry():
    chain = _chain()
    surface = _surface(chain, SPOT)
    col1 = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == E1][0]
    row = [r for r in surface["cells"] if r["strike"] == 280.0][0]
    assert row["contracts"][col1] == {"call": "MRVL  261009C00280000", "put": "MRVL  261009P00280000"}


def test_J_a_side_with_no_real_contract_reports_null_not_a_fabricated_symbol():
    """The ABSENT-side case, from ONE real row re-struck at a strike no other row in the chain
    uses, so only ITS OWN presence/absence is under test.
    # institutional-synthetic-ok: a single real CALL row, re-struck to an otherwise-unused
    # strike so no PUT row exists there -- the minimal input this identity check needs.
    """
    chain = _chain()
    probe = dict(max(_slice(chain, E1), key=lambda ct: ct.get("openInterest") or 0))
    lonely_strike = max(ct["strikePrice"] for ct in chain) + 1000.0
    probe["strikePrice"] = lonely_strike
    probe["symbol"] = "MRVL  261009C" + str(int(lonely_strike * 1000)).zfill(8)
    probe["putCall"] = "CALL"
    surface = _surface([probe], SPOT)
    row = [r for r in surface["cells"] if r["strike"] == lonely_strike][0]
    assert row["contracts"][0]["call"] == probe["symbol"]
    assert row["contracts"][0]["put"] is None


def test_J_negative_control_a_missing_symbol_field_reports_null_not_a_stale_or_wrong_value():
    """A contract missing its own `symbol` field must never silently borrow a strike-mate's
    symbol or fall back to a stale cached value -- it must report None."""
    probe = max(_slice(_chain(), E1), key=lambda ct: ct.get("openInterest") or 0)
    no_symbol = dict(probe)
    no_symbol.pop("symbol", None)
    surface = _surface([no_symbol], SPOT)
    k = float(probe["strikePrice"])
    row = [r for r in surface["cells"] if r["strike"] == k][0]
    side = "call" if probe["putCall"] == "CALL" else "put"
    assert row["contracts"][0][side] is None


# K. DEX/VANNA/OI/VOLUME — each cell field equals the SAME canonical faucet bucket test_A
# anchors net_gex_1pct against.
def test_K_dex_cell_equals_the_same_canonical_faucet_net_dex_dollars():
    chain = _chain()
    surface = _surface(chain, SPOT)
    checked = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == exp][0]
        for k, bucket in exposures_e.items():
            row = [r for r in surface["cells"] if r["strike"] == float(k)][0]
            assert row["dex"][col] == bucket_metric(bucket, "net_dex_dollars")   # unrounded
            checked += 1
    assert checked > 20


def test_K_vanna_cell_equals_call_vanna_minus_put_vanna_the_same_dealer_convention_as_net_gex():
    chain = _chain()
    surface = _surface(chain, SPOT)
    checked = nonzero = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == exp][0]
        for k, bucket in exposures_e.items():
            row = [r for r in surface["cells"] if r["strike"] == float(k)][0]
            if bucket_metric(bucket, "net_vanna") is None:     # a leg's vanna input not sent
                assert row["vanna"][col] is None
                continue
            expected = bucket["call_vanna"] - bucket["put_vanna"]
            assert row["vanna"][col] == bucket_metric(bucket, "net_vanna")      # same instant: exact
            assert abs(row["vanna"][col] - expected) < 1e-9
            checked += 1
            nonzero += expected != 0
    assert checked > 20
    assert nonzero > 10, "vanna must be real values, not zero against zero"


def test_K_oi_and_volume_cells_equal_the_same_canonical_faucets_call_and_put_totals():
    chain = _chain()
    surface = _surface(chain, SPOT)
    checked = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, now=NOW)
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == exp][0]
        for k, bucket in exposures_e.items():
            row = [r for r in surface["cells"] if r["strike"] == float(k)][0]
            # the cell carries the one readers' answers: Schwab's values as sent, 0 a real zero
            for key, legs in (("oi", strike_oi_legs(bucket)), ("volume", strike_volume_legs(bucket))):
                exp_cell = ({"call": None, "put": None, "total": None} if legs is None else
                            {"call": round(legs[0]), "put": round(legs[1]), "total": round(legs[0] + legs[1])})
                assert row[key][col] == exp_cell
            checked += 1
    assert checked > 20


def test_K_a_strike_absent_from_one_expirys_own_slice_reports_null_there_not_zero():
    """A strike in E2's real book with no contract in E1's slice reports None for
    dex/vanna/oi/volume in the E1 column -- never a silent 0.0, which would read as "genuinely
    zero dealer DEX/vanna/OI/volume at this strike", a real, different fact."""
    chain = _chain()
    surface = _surface(chain, SPOT)
    e1_col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == E1][0]
    e1_strikes = {float(ct["strikePrice"]) for ct in _slice(chain, E1)}
    e2_only_strikes = [k for k in surface["strikes"] if k not in e1_strikes]
    assert e2_only_strikes, "the two real expiries must not share every strike, or this proves nothing"
    row = [r for r in surface["cells"] if r["strike"] == e2_only_strikes[0]][0]
    assert row["gex"][e1_col] is None
    assert row["dex"][e1_col] is None
    assert row["vanna"][e1_col] is None
    assert row["oi"][e1_col] == {"call": None, "put": None, "total": None}
    assert row["volume"][e1_col] == {"call": None, "put": None, "total": None}


# ---- the exposure books every view is shaped from merge back to the one full book ----

def test_per_expiry_exposures_additively_merge_to_the_full_recompute():
    """The identity the heatmap, per-strike rows and levels rely on: partitioning the two-expiry
    chain by expiry and merging the per-expiry exposures must reproduce
    compute_exposures_by_strike's own single-call result over the WHOLE chain, strike for
    strike, field for field, at the same valuation instant."""
    from math_exposure_core import merge_exposure_books
    chain = _chain()
    full, _diag = compute_exposures_by_strike(chain, spot=SPOT, now=NOW)
    by_expiry = exposure_books(chain, spot=SPOT, now=NOW)
    assert {exp for exp, _dte in by_expiry} == {E1, E2}
    merged, merged_diag = merge_exposure_books(by_expiry.values())
    assert (merged_diag.contracts_total, merged_diag.contracts_used) == (_diag.contracts_total, _diag.contracts_used)
    assert set(merged.keys()) == set(full.keys())
    for strike, bucket in full.items():
        assert merged[strike] == bucket, (
            f"merged per-expiry exposures at strike {strike} must equal the full single-call "
            f"recompute exactly: {merged[strike]} != {bucket}")


def test_the_chart_draws_the_heatmaps_own_dex_and_oi_per_strike():
    """Operator 2026-09-29: the Delta / DEX and Open Interest Chart views were blank. The chart's
    DEX and OI profiles (/api/terrain/strikes `measures`, from the terrain publication) are the
    heatmap's own cells summed across expiries -- one computation, two views."""
    import time

    import server
    from terrain_engine import compute_terrain

    chain = _chain()
    snap = compute_terrain("MRVL", chain, SPOT, now=NOW)
    surface = project_gamma_surface(chain, snap.books)
    with server._terrain_cache_lock:
        server._terrain_cache["MRVL"] = {"ticker": "MRVL", "spot": snap.spot, "computed_ts_utc": time.time(),
                                         "_per_strike": snap.per_strike}
    try:
        measures = json.loads(server.get_terrain_strikes(ticker="MRVL", scope="all").body)["measures"]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("MRVL", None)
    assert measures["dex"]["rows"] and measures["oi"]["rows"]
    cols = len(surface["expirations"])
    for m, cell_value in (("dex", lambda c: c), ("oi", lambda c: c["total"])):
        for strike, value in measures[m]["rows"]:
            row = [r for r in surface["cells"] if r["strike"] == strike][0]
            cells = [cell_value(c) for c in row[m] if c is not None and cell_value(c) is not None]
            assert cells and abs(sum(cells) - value) <= 0.5 * cols + 0.1, (m, strike, value, cells)
