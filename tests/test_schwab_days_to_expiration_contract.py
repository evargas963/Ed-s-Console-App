from __future__ import annotations

from market_state import _build_contract_context_ms, _schwab_days_to_expiration_for_contract
from math_exposure_core import compute_net_charm
from math_levels import parity_f_minus_spot_from_contracts


class _MarketStateStub:
    ticker = "SPY"
    selected_exp = "2099-05-05"
    call_option_expiry = "2099-05-05"
    rec_strike = 500.0
    call_option_right = "CALL"
    rec_side = "CALL"
    call_signal = "long"
    is_no_trade = False
    spot = 499.5


def _contract(**overrides) -> dict:
    # institutional-synthetic-ok: DTE/mark field-handling + fail-closed tests set/remove
    # specific Schwab fields (daysToExpiration, mark) to prove exact behavior; controlled input.
    base = {
        "putCall": "CALL",
        "strikePrice": 500.0,
        "daysToExpiration": 0,
        "expirationDate": "2099-05-05",
        "bid": 1.2,
        "ask": 1.3,
        "mark": 1.25,
        "gamma": 0.08,
        "delta": 0.52,
        "volatility": 22.0,
        "openInterest": 100,
        "multiplier": 100,
    }
    base.update(overrides)
    return base


def test_market_state_contract_context_uses_schwab_days_to_expiration():
    contracts = [_contract(daysToExpiration=3)]

    # RC-345 / F41: selected expiry is mandatory — supply it explicitly.
    assert _schwab_days_to_expiration_for_contract(
        contracts, 500.0, "CALL", expiry="2099-05-05") == 3
    # Mutation: empty/missing expiry must FAIL CLOSED (governed absence), never search-all.
    assert _schwab_days_to_expiration_for_contract(contracts, 500.0, "CALL") is None
    assert _schwab_days_to_expiration_for_contract(
        contracts, 500.0, "CALL", expiry="") is None
    assert "3DTE" in _build_contract_context_ms(_MarketStateStub(), contracts)


def test_market_state_contract_context_mid_prefers_schwab_mark_over_bid_ask_mid():
    contracts = [_contract(mark=1.22, bid=1.2, ask=1.3)]
    ctx = _build_contract_context_ms(_MarketStateStub(), contracts)
    assert "mid≈1.22" in ctx


def test_market_state_contract_context_does_not_derive_dte_when_schwab_field_missing():
    contract = _contract()
    contract.pop("daysToExpiration")

    context = _build_contract_context_ms(_MarketStateStub(), [contract])

    assert "DTE" not in context


def test_parity_filter_skips_missing_schwab_days_to_expiration():
    """Both contracts are filtered out, so there is NO residual to report.

    RC-301: this asserted `== 0.0`, which was asserting the fabricated value rather than
    the intent. Zero is the specific market claim that the forward equals spot and there
    is no basis; "every contract was filtered out" is absence. The filter behaviour under
    test is unchanged — what changes is that the function now says which one it means.
    """
    missing_dte_call = _contract(putCall="CALL", daysToExpiration=None)
    missing_dte_put = _contract(putCall="PUT", daysToExpiration=None)

    assert parity_f_minus_spot_from_contracts(
        [missing_dte_call, missing_dte_put],
        spot=500.0,
        dte_max=0,
    ) is None


def test_parity_still_returns_a_number_when_the_chain_supports_one():
    """Negative control: absence handling must not blank out real residuals."""
    call = _contract(putCall="CALL", daysToExpiration=0, mark=12.0)
    put = _contract(putCall="PUT", daysToExpiration=0, mark=10.0)

    resid = parity_f_minus_spot_from_contracts([call, put], spot=500.0, dte_max=0)
    assert resid is not None, "a priceable pair produced no residual"
    assert isinstance(resid, float)


def test_charm_filter_skips_missing_schwab_days_to_expiration_when_expiry_date_absent():
    contract = _contract(expirationDate=None)
    contract.pop("daysToExpiration")

    result = compute_net_charm([contract], 500.0, "2099-05-05")

    assert result["contracts_used"] == 0
