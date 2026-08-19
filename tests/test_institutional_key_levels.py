"""Institutional consistency: dollar GEX pickers and aggregates."""

from math_exposure_core import (
    aggregate_net_gex,
    bucket_metric_abs,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    net_gex_dollars_at_strike,
    pick_net_gex_peak_strike,
    pick_pin_and_strength,
    pick_hvl_strike,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
)
from math_levels import build_summary_rows, pick_gamma_wall_strikes


def _dollarized_exposures():
  # Real captured SPY 0DTE chain (tests/fixtures/) — level invariants must hold on real data.
  import json
  from pathlib import Path

  fx = json.loads(
      (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
  )
  contracts, spot = fx["chain"], float(fx["spot"])
  exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
  return exposures, spot


def test_exposures_are_dollarized():
    exposures, _ = _dollarized_exposures()
    assert exposures_have_dollar_gex(exposures)


def test_net_gex_peak_uses_net_gex_when_dollarized():
    """RC-124/RC-417: the former 'pin' — the NET book's peak — under its honest name."""
    from dataclasses import asdict, fields
    from math_exposure_core import ExposureRow
    from levels import to_display_rows

    names = {f.name for f in fields(ExposureRow)}
    assert "gamma_pin" not in names
    assert "net_gex_peak" in names

    exposures, spot = _dollarized_exposures()
    peak = pick_net_gex_peak_strike(exposures, sorted(exposures.keys()))
    pin, _ = pick_pin_and_strength(exposures, sorted(exposures.keys()))
    assert peak is not None and pin is not None
    assert peak == 743.0 and pin == 745.0, (
        "this fixture's net-GEX peak and total-gamma pin must keep diverging — "
        f"got peak={peak} pin={pin}"
    )
    rows = build_summary_rows(exposures, spot, windows=[5])
    assert rows[0].net_gex_peak == peak
    assert not hasattr(rows[0], "gamma_pin")
    dumped = asdict(rows[0])
    assert "gamma_pin" not in dumped
    assert dumped["net_gex_peak"] == peak
    disp = to_display_rows(rows)
    assert not hasattr(disp[0], "gamma_pin")
    assert disp[0].net_gex_peak == f"{peak:.2f}"


def test_standard_pin_is_total_gamma_with_decisiveness():
    """RC-124: THE pin is max TOTAL gamma (SpotGamma Absolute Gamma / sticky pin) — it must
    equal HVL (same metric) and carry the leader's margin over the runner-up."""
    exposures, spot = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    pin, strength = pick_pin_and_strength(exposures, strikes)
    hvl = pick_hvl_strike(exposures, strikes)
    assert pin is not None and pin == hvl, (
        "the standard pin and HVL are the same measure — divergence means one changed basis"
    )
    assert strength is not None and 0.0 < strength <= 100.0
    # exactness on a known distribution: leader 300, runner-up 200 -> 33.3% lead
    # institutional-synthetic-ok: strength arithmetic needs known mass.
    synth = {
        700.0: {"call_gex_1pct": 200.0, "put_gex_1pct": -100.0},   # total 300
        705.0: {"call_gex_1pct": 120.0, "put_gex_1pct": -80.0},    # total 200
        710.0: {"call_gex_1pct": 30.0,  "put_gex_1pct": -20.0},    # total 50
    }
    p2, s2 = pick_pin_and_strength(synth, sorted(synth))
    assert p2 == 700.0 and s2 == round((300 - 200) / 300 * 100, 1)


def test_pin_fails_closed_without_dollarized_gex():
    """No dollarized book -> (None, None); a raw-gamma fallback would silently change basis."""
    # institutional-synthetic-ok: the refusal path needs an un-dollarized bucket on purpose.
    raw_only = {700.0: {"net_gamma": 5.0, "call_gamma": 3.0, "put_gamma": 2.0}}
    assert pick_pin_and_strength(raw_only, [700.0]) == (None, None)


def test_hvl_and_walls_still_pick():
    exposures, spot = _dollarized_exposures()
    hvl = pick_hvl_strike(exposures, sorted(exposures.keys()))
    assert hvl is not None
    (cg, _), (pg, _) = pick_gamma_wall_strikes(exposures, sorted(exposures.keys()))
    assert cg is not None or pg is not None


def test_consensus_net_gamma_equals_aggregate_net_gex():
    exposures, spot = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    agg = aggregate_net_gex(exposures, strikes)
    rows = build_summary_rows(exposures, spot, windows=[5])
    assert rows[0].net_gamma == agg


def test_key_delta_strike_is_the_total_dex_argmax_on_real_chain():
    exposures, _ = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    kds = pick_key_delta_strike(exposures, strikes)
    assert kds is not None
    # Independent recompute: no other strike may carry more total |DEX$|.
    def total_dex(s):
        b = exposures.get(s, {})
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        return (c or 0.0) + (p or 0.0)
    best = max(strikes, key=total_dex)
    assert kds == round(best, 2)


def test_key_delta_strike_fails_closed_without_dollarization():
    # OI-only buckets (no DEX$ fields) must return None, never a raw-unit rank.
    exposures = {100.0: {"call_oi": 500, "put_oi": 400}}
    assert pick_key_delta_strike(exposures, [100.0]) is None


def test_volatility_points_are_signed_extremes_on_real_chain():
    exposures, _ = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    hvp, lvp = pick_volatility_point_strikes(exposures, strikes)
    signed = {s: net_gex_dollars_at_strike(exposures.get(s, {})) for s in strikes}
    signed = {s: v for s, v in signed.items() if v is not None}
    negatives = {s: v for s, v in signed.items() if v < 0}
    positives = {s: v for s, v in signed.items() if v > 0}
    if negatives:
        assert hvp == round(min(negatives, key=negatives.get), 2)
    else:
        assert hvp is None
    if positives:
        assert lvp == round(max(positives, key=positives.get), 2)
    else:
        assert lvp is None
    # The real SPY chain has positive pockets — LVP must exist there.
    assert lvp is not None


def test_terrain_snapshot_v2_carries_net_gex_and_new_levels():
    """Real seam: compute_terrain (the /api/terrain producer) on the real SPY chain
    must serve schema v2 with net_gex_at_spot ≡ flip_diag.gamma_at_spot and the new
    levels agreeing with their pickers — the UI renders these fields directly."""
    import json
    from pathlib import Path

    from terrain_engine import TERRAIN_SCHEMA_VERSION, compute_terrain

    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
    )
    snap = compute_terrain("SPY", fx["chain"], float(fx["spot"]))
    d = snap.to_dict()
    assert TERRAIN_SCHEMA_VERSION == 2 and d["schema_version"] == 2
    for fld in ("net_gex_at_spot", "key_delta_strike", "hvp", "lvp"):
        assert fld in d, fld + " missing from terrain payload"
    assert d["net_gex_at_spot"] == (d["flip_diag"] or {}).get("gamma_at_spot")
    exposures, _ = compute_exposures_by_strike(fx["chain"], spot=float(fx["spot"]), require_oi=True)
    strikes = sorted(exposures.keys())
    # engine strike list is filtered; pickers must agree when run on the same inputs
    from math_exposure_core import key_level_strikes_with_gamma
    eng_strikes = key_level_strikes_with_gamma(exposures) or strikes
    assert d["key_delta_strike"] == pick_key_delta_strike(exposures, eng_strikes)
    assert (d["hvp"], d["lvp"]) == pick_volatility_point_strikes(exposures, eng_strikes)


def test_volatility_points_one_sided_chain_returns_none_side():
    exposures = {
        100.0: {"net_gex_1pct": 5_000_000.0, "call_gex_1pct": 5_000_000.0},
        105.0: {"net_gex_1pct": 9_000_000.0, "call_gex_1pct": 9_000_000.0},
    }
    hvp, lvp = pick_volatility_point_strikes(exposures, [100.0, 105.0])
    assert hvp is None      # no negative pocket anywhere
    assert lvp == 105.0     # most positive, signed — not magnitude
