"""RC-43 / RC-53: the flip-vs-IV measurement and the OI census are locked by construction.

These drive the REAL functions. The OI census tests use a chain whose concentration is KNOWN by
construction (near-ATM strikes fat, wing strikes thin, many more wing strikes) — the exact shape
that fooled the original unequal-bucket analysis — so the fair-method contract is proven, not
asserted: per-strike OI must show the near-ATM concentration even though the wings win on
share-of-total by strike count alone.
"""
from __future__ import annotations

import pytest

from tools.flip_iv_sensitivity_v1 import (
    counterfactual,
    load_wide_chains,
    oi_by_moneyness,
    shift_stats,
    usable_contracts,
)

SPOT = 100.0


def _chain():
    """Near-ATM: 5 strikes x 1000 OI. Wings: 40 strikes x 100 OI.

    Per strike the near-ATM is 10x fatter, but the wings hold MORE total OI (4000 vs 5000 -> the
    wings' many strikes make their share large). This is the RC-53 artifact in miniature.
    """
    # institutional-synthetic-ok: the OI distribution is the variable under test — this chain is
    # constructed so per-strike OI and share-of-total point in OPPOSITE directions (fat near-ATM
    # strikes, many thin wing strikes). A real captured chain cannot prove the fair-method
    # contract, because it has whatever distribution it has; only a known-by-construction shape
    # can show that per-strike normalisation reports the true concentration where share-of-total
    # misleads. This is the exact artifact that produced the false RC-53 claim.
    cts = []
    for i, k in enumerate([98.0, 99.0, 100.0, 101.0, 102.0]):       # |moneyness| <= 2%
        cts.append({"strikePrice": k, "openInterest": 1000, "multiplier": 100, "putCall": "CALL",
                    "volatility": 20.0 + i, "expirationDate": "2026-08-21", "daysToExpiration": 20})
    for j in range(40):                                              # |moneyness| >= 5%
        k = 105.0 + j if j % 2 == 0 else 95.0 - j
        cts.append({"strikePrice": float(k), "openInterest": 100, "multiplier": 100, "putCall": "PUT",
                    "volatility": 40.0 + j, "expirationDate": "2026-08-21", "daysToExpiration": 20})
    return cts


def test_oi_census_reports_per_strike_not_just_share():
    rows = oi_by_moneyness([(SPOT, _chain())])
    by = {r["bin"]: r for r in rows}
    near = by["0-1%"]["oi_per_strike"]          # the 100.0 strike
    wing = by["10%+"]["oi_per_strike"]
    assert near == 1000 and wing == 100
    # RC-53 CONTRACT: per-strike shows the true concentration (near ATM), which is the OPPOSITE of
    # what share-of-total suggests once the wing bins carry many more strikes.
    assert near > wing * 5
    assert by["10%+"]["n_strikes"] > by["0-1%"]["n_strikes"]


def test_oi_census_bins_are_equal_width_and_expose_strike_counts():
    rows = oi_by_moneyness([(SPOT, _chain())])
    assert [r["bin"] for r in rows][:3] == ["0-1%", "1-2%", "2-3%"]   # equal 1% bins, not buckets
    assert all("n_strikes" in r and "oi_per_strike" in r for r in rows), (
        "every bin must expose n_strikes + oi_per_strike so a share-of-total artifact is visible"
    )


def test_counterfactual_modes_change_only_their_target_region():
    cts = _chain()
    wings = counterfactual(cts, SPOT, "WINGS_ONLY", wing_pct=0.03)
    near = counterfactual(cts, SPOT, "NEAR_ONLY", wing_pct=0.03)
    atm_iv = 20.0 + 2                                   # the 100.0 strike's IV
    for src, w, n in zip(cts, wings, near, strict=True):
        m = abs(float(src["strikePrice"]) / SPOT - 1.0)
        if m > 0.03:
            assert w["volatility"] == atm_iv            # wing flattened
            assert n["volatility"] == src["volatility"]  # near-only left it alone
        else:
            assert w["volatility"] == src["volatility"]
            assert n["volatility"] == atm_iv
    flat = counterfactual(cts, SPOT, "FLAT_ALL")
    assert {c["volatility"] for c in flat} == {atm_iv}   # one IV everywhere


def test_counterfactual_rejects_unknown_mode():
    with pytest.raises(ValueError):
        counterfactual(_chain(), SPOT, "NOT_A_MODE")


def test_usable_contracts_normalises_iso_expiry_and_filters():
    raw = [
        {"strikePrice": 100.0, "openInterest": 5, "daysToExpiration": 20,
         "expirationDate": "2026-08-21T20:00:00.000+00:00"},
        {"strikePrice": 100.0, "openInterest": 0, "daysToExpiration": 20,       # no OI
         "expirationDate": "2026-08-21T20:00:00.000+00:00"},
        {"strikePrice": 100.0, "openInterest": 5, "daysToExpiration": 0,        # 0DTE excluded
         "expirationDate": "2026-07-26T20:00:00.000+00:00"},
    ]
    out = usable_contracts(raw)
    assert len(out) == 1
    assert out[0]["expirationDate"] == "2026-08-21"   # time_to_expiry_years needs YYYY-MM-DD


def test_load_wide_chains_excludes_non_trading_days(tmp_path):
    """RC-54/RC-57 (audit finding A7): the decontamination line had NO test — deleting it left the
    suite green. This drives the real loader against a DB holding one trading day and two
    market-closed days; only the trading day may survive."""
    import json
    import sqlite3

    db = tmp_path / "w.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE option_chain_morning_full (ticker TEXT, et_date TEXT, ts_utc REAL, "
              "spot REAL, chain_json TEXT)")
    # institutional-synthetic-ok: the variable under test is the ET DATE of each capture, not the
    # chain's market content — the same identical chain is attached to a Friday, a Saturday and a
    # holiday so the ONLY difference between rows is the calendar. A real chain would vary in
    # content and confound exactly the thing being proven.
    chain = json.dumps([
        {"strikePrice": 100.0 + i, "openInterest": 50, "multiplier": 100, "putCall": "CALL",
         "volatility": 20.0, "expirationDate": "2026-08-21", "daysToExpiration": 20}
        for i in range(10)
    ])
    for et_date, ts in (("2026-07-24", 1.0),      # Friday        -> KEEP
                        ("2026-07-25", 2.0),      # Saturday      -> DROP
                        ("2026-05-25", 3.0)):     # Memorial Day  -> DROP
        c.execute("INSERT INTO option_chain_morning_full VALUES (?,?,?,?,?)",
                  ("SPY", et_date, ts, 100.0, chain))
    c.commit()
    c.close()

    loaded = load_wide_chains(str(db))
    assert len(loaded) == 1, "market-closed captures must never enter a measurement"
    assert loaded[0][1] == 1.0   # the Friday row


def test_shift_stats_reports_distribution_not_just_a_headline():
    st = shift_stats([0.05, 0.2, 0.4, 1.0])
    assert st["n"] == 4
    assert st["median_pct_of_spot"] == 0.3
    assert st["max_pct_of_spot"] == 1.0
    assert st["within_0_1pct_share"] == 25.0
    assert shift_stats([]) == {"n": 0}
