"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on the REAL captured SPY chain, never a hand-built one, so the numbers are
whatever the actual data produces.
"""

from __future__ import annotations

import json
from pathlib import Path

from math_levels import GAMMA_FLIP_TRUSTED
from terrain_engine import TERRAIN_SCHEMA_VERSION, compute_terrain

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_fails_closed_on_every_missing_input() -> None:
    """No ticker, no chain, no spot -> a stand-aside payload, never a partial one."""
    for ticker, chain, spot in (
        ("", None, None),
        ("SPY", None, 743.0),
        ("SPY", [], 743.0),
        ("SPY", [{"strikePrice": 740}], None),
        ("SPY", [{"strikePrice": 740}], 0.0),
    ):
        snap = compute_terrain(ticker, chain, spot)
        assert snap.regime == "UNAVAILABLE"
        assert snap.posture == "STAND_ASIDE"
        assert snap.gamma_flip is None
        assert snap.call_wall is None and snap.put_wall is None
        assert snap.error, "a refusal must state its reason"


def test_real_chain_produces_a_complete_payload() -> None:
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)

    assert snap.ticker == "SPY"
    assert snap.spot == spot
    assert snap.schema_version == TERRAIN_SCHEMA_VERSION
    assert snap.contracts_used > 0
    assert snap.strikes_used > 0
    assert snap.headline, "the operator always gets a sentence"
    assert isinstance(snap.lines, list)


def test_levels_are_real_strikes_or_absent() -> None:
    """A level must be a strike that exists in the chain — never interpolated or invented.

    The gamma flip is the one exception: it is interpolated between strikes by design.
    """
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    strikes = {float(c["strikePrice"]) for c in chain if c.get("strikePrice") is not None}

    for name in ("call_wall", "put_wall", "gamma_pin", "hvl",
                 "call_charm_wall", "put_charm_wall"):
        value = getattr(snap, name)
        assert value is None or value in strikes, f"{name}={value} is not a chain strike"


def test_posture_is_never_issued_without_trusted_levels() -> None:
    """The core safety property: no trading posture on levels we do not trust."""
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    if snap.confidence != GAMMA_FLIP_TRUSTED:
        assert snap.posture == "STAND_ASIDE"
        assert snap.regime == "UNAVAILABLE"


def test_narrow_0dte_slice_fails_closed_gate_retained() -> None:
    """RC-33: locking terrain to the full/wide chain must NOT weaken the
    narrow-chain protection. This real 40-contract 0DTE fixture spans only
    ~±1.3% (< the ±5% trust floor), so compute_terrain must fail closed to
    STAND_ASIDE — exactly the state the removed /api/analytics/state duplicate
    produced. One terrain source of truth keeps this fail-closed backstop.
    """
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    assert snap.confidence != GAMMA_FLIP_TRUSTED
    assert snap.regime == "UNAVAILABLE"
    assert snap.posture == "STAND_ASIDE"


def test_payload_is_json_serialisable() -> None:
    """It is served over HTTP; a non-serialisable field breaks the tab silently."""
    chain, spot = _real_chain()
    payload = compute_terrain("SPY", chain, spot).to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["ticker"] == "SPY"
    assert "spot" in round_tripped and "confidence" in round_tripped
    assert "flip_diag" in round_tripped


def test_is_deterministic() -> None:
    """Same chain, same spot, same payload — or nothing on the card is reproducible."""
    chain, spot = _real_chain()
    a = compute_terrain("SPY", chain, spot).to_dict()
    b = compute_terrain("SPY", chain, spot).to_dict()
    # RC-114: computed_ts_utc is the capture WALL CLOCK — nondeterministic BY DESIGN (RC-68:
    # every consumer must render an age). Comparing it made this test pass or fail on timer
    # resolution luck (proven failing at HEAD with no code change, same flake family as the
    # date-frozen RC-109). Determinism is about the LEVELS, so the stamp is excluded.
    a.pop("computed_ts_utc"), b.pop("computed_ts_utc")
    assert a == b


# ── RC-113: the institutional sigma band (SpotGamma-on-Bloomberg standard) ───────────────────

def test_implied_one_day_move_matches_the_named_formula() -> None:
    """EM = S x sigma_ATM x sqrt(1/252). The chain here is hand-built ON PURPOSE — a formula
    verification needs known inputs (the real-chain test below covers the live shape)."""
    from terrain_engine import compute_implied_one_day_move
    spot = 700.0
    # institutional-synthetic-ok: formula verification REQUIRES known inputs — the exactness
    # assertion below is meaningless on a live chain; the real-chain test covers the live shape.
    chain = [
        {"putCall": "CALL", "strikePrice": 700.0, "volatility": 20.0, "daysToExpiration": 1},
        {"putCall": "PUT",  "strikePrice": 700.0, "volatility": 24.0, "daysToExpiration": 1},
        # a farther expiry with wild IV must be IGNORED — front expiry only
        {"putCall": "CALL", "strikePrice": 700.0, "volatility": 80.0, "daysToExpiration": 30},
        # far-from-money same-expiry must lose to the ATM pair
        {"putCall": "PUT",  "strikePrice": 650.0, "volatility": 99.0, "daysToExpiration": 1},
    ]
    em = compute_implied_one_day_move(chain, spot)
    assert em is not None
    sigma = (0.20 + 0.24) / 2.0
    assert abs(em["points"] - spot * sigma * (1.0 / 252.0) ** 0.5) < 1e-4
    assert em["iv_pct_atm"] == 22.0, "sigma must be the ATM call/put mean, Schwab percent /100"
    assert em["dte_used"] == 1
    assert "sqrt(1/252)" in em["method"], "the method label is part of the contract"


def test_implied_move_fails_closed_without_usable_iv() -> None:
    """No usable ATM IV -> None. A fabricated sigma is worse than no sigma."""
    from terrain_engine import compute_implied_one_day_move
    # institutional-synthetic-ok: fail-closed tests MUST feed malformed contracts on purpose.
    assert compute_implied_one_day_move([], 700.0) is None
    assert compute_implied_one_day_move(None, 700.0) is None
    assert compute_implied_one_day_move(
        [{"putCall": "CALL", "strikePrice": 700.0, "volatility": -5.0,
          "daysToExpiration": 1}], 700.0) is None, "negative IV must not produce a band"
    assert compute_implied_one_day_move(
        [{"putCall": "CALL", "strikePrice": 700.0, "volatility": 20.0,
          "daysToExpiration": 1}], None) is None


def test_real_chain_carries_the_sigma_band() -> None:
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    em = snap.implied_1d_move
    assert em is not None, "the real chain must yield a band (its ATM IV is present)"
    assert em["points"] > 0
    # a one-day sigma on SPY is points, not pennies and not tens of percent of spot
    assert 0.0005 * spot < em["points"] < 0.15 * spot, em
    assert "implied_1d_move" in snap.to_dict(), "the payload must carry the band to the chart"
