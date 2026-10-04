"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on the REAL captured SPY chain, never a hand-built one, so the numbers are
whatever the actual data produces.
"""

from __future__ import annotations

import pytest

import json
from pathlib import Path

from math_levels import GAMMA_FLIP_TRUSTED
from terrain_engine import TERRAIN_SCHEMA_VERSION, compute_terrain

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json"



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """real_spy_0dte_chain.json was captured 2026-09-22 12:46 ET."""
    return pin_clock(2026, 9, 22, 12, 46)

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

    for name in ("call_wall", "put_wall", "absolute_gamma_strike", "pin_candidate",
                 "call_charm_wall", "put_charm_wall"):
        value = getattr(snap, name)
        assert value is None or value in strikes, f"{name}={value} is not a chain strike"
    # RC-134: dead total-gamma twin removed — absolute_gamma_strike is the sole terrain
    # total-gamma level.
    assert "hvl" not in snap.to_dict(), (
        "terrain must not ship hvl (it equals absolute_gamma_strike by construction)"
    )


def test_narrow_0dte_slice_fails_closed_gate_retained() -> None:
    """RC-33: locking terrain to the full/wide chain must NOT weaken the
    narrow-chain protection. This real 40-contract 0DTE fixture spans only
    ~±1.3% (< the ±5% trust floor), so compute_terrain must fail closed to
    STAND_ASIDE — exactly the state the removed /api/analytics/state duplicate
    produced. One terrain source of truth keeps this fail-closed backstop.
    """
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    assert snap.profile, "the chain must price, so the NARROW gate (not an expiry) is tested"
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


def test_an_atm_contract_with_no_iv_is_never_replaced_by_the_next_strikes() -> None:
    """The ATM call's IV is Schwab's -999 (no value): that leg has no IV, and the expiry's ATM IV
    is None -- the 705 call's IV used to stand in for it, labelled ATM (operator 2026-10-01: "we
    use what schwab gives us and we display it")."""
    from terrain_engine import atm_sigma_by_expiry
    # institutional-synthetic-ok: the rule needs a known ATM contract with no IV beside a priced one
    chain = [
        {"putCall": "CALL", "strikePrice": 700.0, "volatility": -999.0, "daysToExpiration": 1, "expirationDate": "2026-10-02"},
        {"putCall": "CALL", "strikePrice": 705.0, "volatility": 30.0, "daysToExpiration": 1, "expirationDate": "2026-10-02"},
        {"putCall": "PUT", "strikePrice": 700.0, "volatility": 24.0, "daysToExpiration": 1, "expirationDate": "2026-10-02"},
    ]
    assert atm_sigma_by_expiry(chain, 700.0) == {("2026-10-02", 1): None}


def test_real_chain_carries_the_sigma_band(pin_clock) -> None:
    """The 1-day band uses the first expiry at least a day out (2026-09-27): a same-day-only
    chain has none; the CRWD chain (16 days out, valued at its capture) has one."""
    chain, spot = _real_chain()
    assert compute_terrain("SPY", chain, spot).implied_1d_move is None
    pin_clock(2026, 9, 2, 10, 5)
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                    .read_text(encoding="utf-8"))
    snap = compute_terrain("CRWD", fx["chain"], float(fx["spot"]))
    em = snap.implied_1d_move
    assert em is not None, "the CRWD chain must yield a band (its ATM IV is present)"
    s = float(fx["spot"])
    # a one-day sigma is points, not pennies and not tens of percent of spot
    assert 0.0005 * s < em["points"] < 0.15 * s, em
    assert "implied_1d_move" in snap.to_dict(), "the payload must carry the band to the chart"


def test_every_expiry_carries_its_atm_iv_by_the_one_rule(pin_clock) -> None:
    """The Trade Desk's Volatility card draws ATM IV by expiry (2026-09-28). The ATM rule was
    applied to the front expiry only (the implied move); it is one function for every expiry, and
    the implied move reads its front entry. Real MRVL full chain, 21 expiries, valued at its
    capture (tests/fixtures/real_mrvl_full_chain_vs_strike_window.json)."""
    import time_et
    from datetime import datetime
    from schwab_client import flatten_chain_contracts
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_mrvl_full_chain_vs_strike_window.json")
                    .read_text(encoding="utf-8"))
    at = datetime.fromtimestamp(fx["captured_utc"], time_et.ET)
    pin_clock(at.year, at.month, at.day, at.hour, at.minute)
    chain, spot = flatten_chain_contracts(fx["full"]), float(fx["full"]["underlying"]["last"])
    snap = compute_terrain("MRVL", chain, spot)
    by_exp = snap.atm_iv_pct_by_expiry
    assert list(by_exp) == sorted({c["expirationDate"][:10] for c in chain})
    assert list(snap.pcr_by_expiry) == list(by_exp), "both card lines run nearest expiry first"
    assert all(v is None or 0 < v < 1000 for v in by_exp.values())
    em = snap.implied_1d_move
    front = min(c["daysToExpiration"] for c in chain if c["daysToExpiration"] >= 1)
    front_exp = {c["expirationDate"][:10] for c in chain if c["daysToExpiration"] == front}.pop()
    assert em is not None and by_exp[front_exp] == em["iv_pct_atm"]


# ── RC-130: wall geometry state — the support/resistance claim is CONDITIONAL ────────────────
# Live SPY 2026-07-29: put wall 740.0 sat ABOVE spot 735.13 while every surface said
# "dealer support". Institutional standard (SpotGamma stats, GEXBoard): the picker stays at
# the concentration max — unconstrained by spot — and a breach is a DISTINCT reported state,
# not a moved strike. These tests pin the state function and its carriage.

def test_wall_geometry_state_truth_table() -> None:
    from terrain_engine import wall_geometry_state
    # the live defect, exactly: put wall above spot is NOT support
    assert wall_geometry_state(735.13, 740.0, "put") == "breached"
    assert wall_geometry_state(735.13, 730.0, "put") == "contains"
    assert wall_geometry_state(735.13, 750.0, "call") == "contains"
    assert wall_geometry_state(735.13, 730.0, "call") == "breached"
    # equality: a wall AT spot contains nothing
    assert wall_geometry_state(740.0, 740.0, "put") == "breached"
    assert wall_geometry_state(740.0, 740.0, "call") == "breached"
    # absence stays absence — never a guessed state
    assert wall_geometry_state(None, 740.0, "put") is None
    assert wall_geometry_state(735.0, None, "call") is None


def test_wall_geometry_state_rejects_unknown_side() -> None:
    from terrain_engine import wall_geometry_state
    import pytest
    with pytest.raises(ValueError):
        wall_geometry_state(735.0, 740.0, "steel")


def test_real_chain_carries_wall_states_in_payload() -> None:
    """The states ship beside the walls they qualify, and agree with the geometry."""
    from terrain_engine import wall_geometry_state
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    d = snap.to_dict()
    assert d["call_wall_state"] == wall_geometry_state(spot, snap.call_wall, "call")
    assert d["put_wall_state"] == wall_geometry_state(spot, snap.put_wall, "put")
    assert d["call_wall_state"] in ("contains", "breached")
    assert d["put_wall_state"] in ("contains", "breached")


def _bucket_for_pin(exposures: dict, pin: float) -> dict | None:
    for k, v in exposures.items():
        try:
            if float(k) == float(pin):
                return v
        except (TypeError, ValueError):
            continue
    return None


def _book_oi(exposures: dict) -> float | None:
    total = None
    for v in exposures.values():
        if not isinstance(v, dict):
            continue
        co, po = v.get("call_oi"), v.get("put_oi")
        if co is None and po is None:
            continue
        add = (float(co) if co is not None else 0.0) + (float(po) if po is not None else 0.0)
        total = (total or 0.0) + add
    return total


def test_pin_score_stamps_match_the_same_exposures_book_as_the_pin() -> None:
    """RC-413: absolute_gamma_gex_dollars / absolute_gamma_oi / book_oi_total are the same
    compute_exposures_by_strike map pick_pin_and_strength used (RC-292 renamed the fields).
    """
    from math_exposure_core import compute_exposures_by_strike, total_gex_dollars_at_strike

    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    exposures, _ = compute_exposures_by_strike(chain, spot=spot)
    pin = snap.absolute_gamma_strike
    assert pin is not None
    bkt = _bucket_for_pin(exposures, pin)
    assert bkt is not None
    assert snap.absolute_gamma_gex_dollars == total_gex_dollars_at_strike(bkt)
    co, po = bkt.get("call_oi"), bkt.get("put_oi")
    assert snap.absolute_gamma_oi == (float(co) if co is not None else 0.0) + (
        float(po) if po is not None else 0.0
    )
    assert snap.book_oi_total == _book_oi(exposures)
    payload = snap.to_dict()
    assert payload["absolute_gamma_gex_dollars"] == snap.absolute_gamma_gex_dollars
    assert payload["absolute_gamma_oi"] == snap.absolute_gamma_oi
    assert payload["book_oi_total"] == snap.book_oi_total


def test_pin_score_inputs_follow_the_wide_terrain_book_not_selected_expiry() -> None:
    """RC-413 mixed-book proof: extra later-expiry mass at the pin changes terrain
    GEX/OI and therefore pin_score; the selected-expiry (analytics-style) book does not.
    """
    from math_exposure_core import compute_exposures_by_strike, total_gex_dollars_at_strike
    from math_probabilities import compute_pin_score

    chain, spot = _real_chain()
    pin = compute_terrain("SPY", chain, spot).absolute_gamma_strike
    assert pin is not None
    extra = []
    for c in chain:
        try:
            if float(c.get("strikePrice") or 0) != float(pin):
                continue
        except (TypeError, ValueError):
            continue
        d = dict(c)
        d["daysToExpiration"] = int(c.get("daysToExpiration") or 0) + 30
        d["expirationDate"] = "2026-08-16"
        d["openInterest"] = float(c.get("openInterest") or 0) + 50_000
        extra.append(d)
    assert extra, "the pin strike must exist on the captured chain"
    wide = chain + extra
    terrain = compute_terrain("SPY", wide, spot)
    wide_ex, _ = compute_exposures_by_strike(wide, spot=spot)
    sel_ex, _ = compute_exposures_by_strike(chain, spot=spot)
    assert terrain.absolute_gamma_strike == pin
    wb = _bucket_for_pin(wide_ex, pin)
    sb = _bucket_for_pin(sel_ex, pin)
    assert wb is not None and sb is not None
    wide_gex = total_gex_dollars_at_strike(wb)
    sel_gex = total_gex_dollars_at_strike(sb)
    assert wide_gex != sel_gex
    assert terrain.absolute_gamma_gex_dollars == wide_gex
    assert terrain.absolute_gamma_oi != (
        (float(sb.get("call_oi") or 0) + float(sb.get("put_oi") or 0))
    )
    wide_score = compute_pin_score(
        terrain.absolute_gamma_gex_dollars,
        (terrain.absolute_gamma_oi / terrain.book_oi_total)
        if terrain.absolute_gamma_oi is not None and terrain.book_oi_total
        else None,
    )
    sel_score = compute_pin_score(
        sel_gex,
        (
            (float(sb.get("call_oi") or 0) + float(sb.get("put_oi") or 0))
            / _book_oi(sel_ex)
        )
        if _book_oi(sel_ex)
        else None,
    )
    assert wide_score["normalized"] != sel_score["normalized"]


def test_unavailable_terrain_does_not_fabricate_pin_score_stamps() -> None:
    snap = compute_terrain("SPY", None, 743.0)
    assert snap.absolute_gamma_strike is None
    assert snap.absolute_gamma_gex_dollars is None
    assert snap.absolute_gamma_oi is None
    assert snap.book_oi_total is None
    assert snap.pin_candidate is None, "no chain must never yield a pin claim"
    assert snap.pin_candidate_blockers == [], (
        "the unavailable path carries no gate evaluation — blockers stay empty, the whole "
        "snapshot is the absence")
