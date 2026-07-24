"""RC-7 smoke seams for the greeks backfill P0/P1 machinery (pure functions)."""
from __future__ import annotations

from tools.backfill_greeks_from_chain_archive_v1 import (
    PARITY_GATE,
    census_from_chain,
    parity_match,
    recompute_net_gamma,
)


def _contract(**kw):
    # institutional-synthetic-ok: convention-scale and sanitizer-rejection edge
    # tests MUST feed constructed contracts — the -91965 poisoned-gamma fixture
    # (gamma-flip audit Finding 0) cannot exist in a real sanitized chain, and
    # the dollar-GEX scale lock needs exact hand-computable inputs.
    base = {
        "putCall": "CALL",
        "strikePrice": 680.0,
        "daysToExpiration": 0,
        "openInterest": 100,
        "gamma": 0.05,
        "delta": 0.5,
        "multiplier": 100,
        "quoteTimeInLong": 1_784_900_000_000,
    }
    base.update(kw)
    return base


def test_recompute_uses_stored_dollar_gex_convention():
    """stored convention = gamma*OI*S^2 (call minus put) — the P1-discovered scale."""
    chain = [_contract()]
    spot = 680.0
    out = recompute_net_gamma(chain, spot)
    assert out is not None
    expected = 0.05 * 100 * spot * spot  # gamma * OI * S^2
    assert abs(out - expected) / expected < 1e-9
    put = _contract(putCall="PUT", strikePrice=675.0, delta=-0.5)
    both = recompute_net_gamma([_contract(), put], spot)
    assert abs(both) < 1e-6  # symmetric call/put cancels under call-minus-put


def test_recompute_fails_closed_without_spot():
    assert recompute_net_gamma([_contract()], None) is None
    assert recompute_net_gamma([_contract()], 0.0) is None


def test_census_counts_strikes_expiries_and_sanitizer_rejections():
    chain = [
        _contract(),
        _contract(strikePrice=681.0, daysToExpiration=2),
        _contract(strikePrice=682.0, gamma=-91965.237, delta=-1.0, openInterest=21605),
    ]
    c = census_from_chain(chain, 680.0)
    assert c.parse_ok and c.n_contracts == 3 and c.n_distinct_strikes == 3
    assert c.expiry_mix == [0, 2]
    assert c.n_gamma_plausible == 2            # the -91965 fixture is rejected
    assert c.oi_gamma_rejected == 21605.0
    assert c.span_pct is not None and c.span_pct > 0


def test_parity_match_is_relative_and_gate_is_99pct():
    assert parity_match(1_000_000.0, 1_000_500.0, rel_tol=1e-3) is True
    assert parity_match(1_000_000.0, 1_002_000.0, rel_tol=1e-3) is False
    assert PARITY_GATE == 0.99
