"""RC-UI-1 — proof that the Options/Gamma strike×expiry surface is a PROJECTION of the one
canonical exposure faucet (math_exposure_core.compute_exposures_by_strike), not a second GEX
producer. Covers the operator's required invariants A/B/C/D/F/G/H/I on REAL vendor chains
(tests/fixtures: complete Schwab captures with native ISO ``expirationDate`` stamps, zero-OI
rows and -999 greeks), so the projection is proven on the field shapes production actually
feeds it (flatten_chain_contracts passes Schwab rows through verbatim). D/E colour+format are
proven at the frontend formatter (heatmap view module).

Two-expiry input: no single real capture in tests/fixtures spans two expirations, so the
multi-expiry invariants use the UNION of two real complete captures (CRWD 2026-09-18 and
CDE 2026-09-04) at the CRWD capture's own spot. The projection partitions strictly by native
expirationDate, so which underlying a slice came from is immaterial to the identities under
test (cell == faucet on the slice; per-expiry additivity; expiry isolation); nothing about the
rows is invented.
"""
import inspect
import json
from pathlib import Path

from server import project_gamma_surface
from math_exposure_core import compute_exposures_by_strike

_FX = Path(__file__).resolve().parent / "fixtures"


def _real(name: str) -> dict:
    return json.loads((_FX / name).read_text(encoding="utf-8"))


CRWD = _real("real_crwd_complete_chain_quarter.json")
CDE = _real("real_cde_complete_chain_half_dollar.json")
SPOT = float(CRWD["spot"])


def _exp_key(ct: dict) -> str:
    """The projection's own column key rule: the native expirationDate's first 10 chars."""
    return str(ct.get("expirationDate") or "")[:10]


E1 = _exp_key(CRWD["chain"][0])   # 2026-09-18 (native '2026-09-18T20:00:00.000+00:00')
E2 = _exp_key(CDE["chain"][0])    # 2026-09-04


def _chain() -> list[dict]:
    return [dict(ct) for ct in CRWD["chain"]] + [dict(ct) for ct in CDE["chain"]]


def _slice(chain: list[dict], exp: str) -> list[dict]:
    return [ct for ct in chain if _exp_key(ct) == exp]


def _cell(surface, strike, expiry):
    try:
        col = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == expiry][0]
        row = [r for r in surface["cells"] if r["strike"] == strike][0]
    except IndexError:
        return None
    return row["gex"][col]


def test_fixture_preconditions_are_real_two_expiry_input():
    """The union really is two distinct native expirations with OI-bearing rows on both."""
    assert E1 != E2 and len(E1) == 10 and len(E2) == 10
    assert all(_exp_key(ct) == E1 for ct in CRWD["chain"])
    assert all(_exp_key(ct) == E2 for ct in CDE["chain"])
    assert sum(1 for ct in CRWD["chain"] if (ct.get("openInterest") or 0) > 0) > 0
    assert sum(1 for ct in CDE["chain"] if (ct.get("openInterest") or 0) > 0) > 0
    # the native stamp is the ISO form production feeds the projection, not a bare date
    assert "T" in str(CRWD["chain"][0]["expirationDate"])


# A. EXACT CELL EQUALITY — a surface cell equals the canonical faucet on that expiry's slice.
def test_A_cell_equals_canonical_faucet_per_expiry_slice():
    chain = _chain()
    surface = project_gamma_surface(chain, SPOT)
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    checked = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, require_oi=True)
        assert exposures_e, f"the real {exp} slice must yield OI-bearing strikes"
        for k, bucket in exposures_e.items():
            assert _cell(surface, float(k), exp) == round(float(bucket["net_gex_1pct"]))
            checked += 1
    assert checked > 20   # a real book, not a handful of strikes


# B. ADDITIVITY / RECONCILIATION — per-expiry cells sum to the canonical full-book value.
def test_B_per_expiry_sum_reconciles_to_full_book():
    chain = _chain()
    full, _ = compute_exposures_by_strike(chain, spot=SPOT, require_oi=True)
    surface = project_gamma_surface(chain, SPOT)
    per = {exp: compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, require_oi=True)[0]
           for exp in (E1, E2)}
    for k, bucket in full.items():
        # exact math additivity on the unrounded faucet output (the real proof)
        per_sum = sum(float(per[exp][float(k)]["net_gex_1pct"]) for exp in (E1, E2) if float(k) in per[exp])
        assert abs(per_sum - float(bucket["net_gex_1pct"])) < 1e-6
        # rounded display cells reconcile within rounding tolerance
        cell_sum = sum(v for v in [_cell(surface, float(k), E1), _cell(surface, float(k), E2)] if v is not None)
        assert abs(cell_sum - round(float(bucket["net_gex_1pct"]))) <= 2


# C. EXPIRY ISOLATION — changing the E2 slice must not alter any E1 cell (shared spot is the
#    only link). The mutation is a REAL subset: every other E2 row removed.
def test_C_expiry_isolation():
    chain = _chain()
    base = project_gamma_surface(chain, SPOT)
    e2_rows = _slice(chain, E2)
    kept_e2 = e2_rows[::2]
    mutated = _slice(chain, E1) + kept_e2
    after = project_gamma_surface(mutated, SPOT)
    e1_strikes = [k for k in base["strikes"] if _cell(base, k, E1) is not None]
    assert e1_strikes
    for k in e1_strikes:
        assert _cell(base, k, E1) == _cell(after, k, E1)
    # the mutation was material to E2 (otherwise isolation would be proven vacuously)
    assert any(_cell(base, k, E2) != _cell(after, k, E2) for k in base["strikes"])


# D. SIGN — the faucet's sign at every strike survives the projection (no inversion), including
#    the put-heavy (net-short-gamma) strikes the real captures contain.
def test_D_sign_preserved():
    chain = _chain()
    surface = project_gamma_surface(chain, SPOT)
    negatives = 0
    for exp in (E1, E2):
        exposures_e, _ = compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, require_oi=True)
        for k, bucket in exposures_e.items():
            v = float(bucket["net_gex_1pct"])
            if abs(v) < 1:          # rounds to 0 either way; no sign to preserve
                continue
            cell = _cell(surface, float(k), exp)
            assert (cell < 0) == (v < 0), (exp, k, v, cell)
            negatives += 1 if v < 0 else 0
    assert negatives > 0, "the real captures must contain at least one put-heavy strike"


# F. INPUT-PROJECTION COVERAGE — every OI-bearing expiry/strike IN THE SUPPLIED CHAIN is projected.
#    NOTE: this is input-projection coverage, NOT vendor strike_range=ALL chain completeness — the
#    live terrain chain is strike_count-bounded and the API discloses complete=false/coverage.
def test_F_input_projection_coverage():
    chain = _chain()
    surface = project_gamma_surface(chain, SPOT)
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    expected_strikes = set()
    for exp in (E1, E2):
        expected_strikes |= {float(k) for k in compute_exposures_by_strike(_slice(chain, exp), spot=SPOT, require_oi=True)[0]}
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
    probe = max(CRWD["chain"], key=lambda ct: ct.get("openInterest") or 0)   # the heaviest real row
    chain = clean_chain + [dict(probe, expirationDate=None), dict(probe, expirationDate="bad")]
    surface = project_gamma_surface(chain, SPOT)
    assert surface["contracts_excluded_malformed_expiry"] == 2
    assert {e["expiry"] for e in surface["expirations"]} == {E1, E2}
    # the malformed OI must not have inflated the legitimate cells at that strike
    clean = project_gamma_surface(clean_chain, SPOT)
    k = float(probe["strikePrice"])
    assert _cell(surface, k, E1) == _cell(clean, k, E1)
    assert _cell(surface, k, E2) == _cell(clean, k, E2)


# H. SPX / SPXW — canonical underlying->option-chain identity is unchanged; no UI translation.
def test_H_spx_identity_unchanged():
    from server import ticker_storage_key
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    # an SPXW-rooted contract projects without any symbol rewriting. No real SPX capture exists
    # in tests/fixtures; the row is a REAL vendor row re-rooted to the SPXW symbol/strike, which
    # is the only thing this identity check reads.
    probe = max(CRWD["chain"], key=lambda ct: ct.get("openInterest") or 0)
    spxw = [dict(probe, symbol="SPXW  260918C07690000", strikePrice=7690)]
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


# J. LIVE-HEATMAP CONTRACT IDENTITY (state-authority review, 2026-09-12) — every cell must carry
#    the vendor OSI symbol(s) that produced it, verbatim, so the browser can ask the streaming
#    layer to keep exactly its VISIBLE cells fresh instead of only whatever one strike a
#    different panel happened to have separately selected. Never invented: read straight off the
#    same real contract rows compute_exposures_by_strike already aggregates for this cell.
def test_J_cell_carries_the_real_vendor_symbols_for_its_strike_and_expiry():
    chain = _chain()
    surface = project_gamma_surface(chain, SPOT)
    col1 = [i for i, e in enumerate(surface["expirations"]) if e["expiry"] == E1][0]
    row95 = [r for r in surface["cells"] if r["strike"] == 95.0][0]
    contracts95 = row95["contracts"][col1]
    real_call = next(ct["symbol"] for ct in CRWD["chain"]
                      if ct["strikePrice"] == 95.0 and ct["putCall"] == "CALL")
    real_put = next(ct["symbol"] for ct in CRWD["chain"]
                     if ct["strikePrice"] == 95.0 and ct["putCall"] == "PUT")
    assert contracts95 == {"call": real_call, "put": real_put}
    assert contracts95["call"] == "CRWD  260918C00095000"
    assert contracts95["put"] == "CRWD  260918P00095000"


def test_J_a_side_with_no_real_contract_reports_null_not_a_fabricated_symbol():
    """The complete-chain fixture happens to carry both sides at every real strike (a
    genuinely one-sided real strike is not available in tests/fixtures) -- this constructs
    the ABSENT-side case directly from ONE real row plus its exact synthetic mirror struck
    at a strike no other row in the chain uses, so only ITS OWN presence/absence is under
    test, nothing about its neighbours.
    # institutional-synthetic-ok: a single real CALL row, re-struck to an otherwise-unused
    # strike so no PUT row exists there -- the minimal input this specific absent-side
    # identity check needs.
    """
    probe = dict(max(CRWD["chain"], key=lambda ct: ct.get("openInterest") or 0))
    lonely_strike = max(ct["strikePrice"] for ct in CRWD["chain"]) + 1000.0
    probe["strikePrice"] = lonely_strike
    probe["symbol"] = "CRWD  260918C" + str(int(lonely_strike * 1000)).zfill(8)
    probe["putCall"] = "CALL"
    surface = project_gamma_surface([probe], SPOT)
    row = [r for r in surface["cells"] if r["strike"] == lonely_strike][0]
    assert row["contracts"][0]["call"] == probe["symbol"]
    assert row["contracts"][0]["put"] is None


def test_J_negative_control_a_missing_symbol_field_reports_null_not_a_stale_or_wrong_value():
    """Independent-review finding (2026-09-12, state-authority review), REPRODUCED against the
    pre-fix project_gamma_surface (no `contracts` field existed at all -- confirmed by direct
    reversion to HEAD a25de5e5 and re-running this exact test, which raised KeyError on
    `row["contracts"]`, restored afterward). A contract missing its own `symbol` field must
    never silently borrow a strike-mate's symbol or fall back to a stale cached value -- it must
    report None, the same fail-closed rule the rest of this file already proves for missing OI/
    expiry."""
    probe = max(CRWD["chain"], key=lambda ct: ct.get("openInterest") or 0)
    no_symbol = dict(probe)
    no_symbol.pop("symbol", None)
    chain = [no_symbol]
    surface = project_gamma_surface(chain, SPOT)
    k = float(probe["strikePrice"])
    row = [r for r in surface["cells"] if r["strike"] == k][0]
    side = "call" if probe["putCall"] == "CALL" else "put"
    assert row["contracts"][0][side] is None
