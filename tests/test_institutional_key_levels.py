"""Institutional consistency: dollar GEX pickers and aggregates."""


from math_exposure_core import (
    bucket_metric_abs,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    net_gex_dollars_at_strike,
    pick_pin_and_strength,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
)


def _dollarized_exposures():
  # Real captured SPY 0DTE chain (tests/fixtures/) — level invariants must hold on real data.
  import json
  from pathlib import Path

  fx = json.loads(
      (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
  )
  contracts, spot = fx["chain"], float(fx["spot"])
  exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
  return exposures, spot


def test_exposures_are_dollarized():
    exposures, _ = _dollarized_exposures()
    assert exposures_have_dollar_gex(exposures)




def test_pin_fails_closed_without_dollarized_gex():
    """No dollarized book -> (None, None); a raw-gamma fallback would silently change basis."""
    # institutional-synthetic-ok: the refusal path needs an un-dollarized bucket on purpose.
    raw_only = {700.0: {"net_gamma": 5.0, "call_gamma": 3.0, "put_gamma": 2.0}}
    assert pick_pin_and_strength(raw_only, [700.0]) == (None, None)




def _three_way_split_exposures():
    # institutional-synthetic-ok: three-way split needs known buckets, not a captured chain.
    # 100 = max raw call_gamma; 101 = max |call GEX$|; 120 = max total GEX$ (pin).
    return {
        100.0: {
            "call_gamma": 1000.0, "put_gamma": 1.0,
            "call_gex_1pct": 1.0, "put_gex_1pct": -1.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "dollarized": True,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
        101.0: {
            "call_gamma": 10.0, "put_gamma": 1.0,
            "call_gex_1pct": 999.0, "put_gex_1pct": -1.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "dollarized": True,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
        120.0: {
            "call_gamma": 5.0, "put_gamma": 5.0,
            "call_gex_1pct": 50.0, "put_gex_1pct": -5000.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "dollarized": True,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
    }






def _wide_vs_selected_wall_books():
    """Live mixed-book construction: selected-expiry analytics vs wide-chain terrain.

    OUT-OF-SCOPE: enrolled-universe live desk. This is the RC-80/RC-420 chain-width
    split on the captured SPY 0DTE fixture plus one later-expiry CALL, not a
    complete operable-surface claim.
    """
    import json
    from pathlib import Path

    from math_exposure_core import compute_exposures_by_strike
    from terrain_engine import compute_terrain

    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(
            encoding="utf-8"
        )
    )
    chain, spot = fx["chain"], float(fx["spot"])
    src = next(
        c for c in chain
        if str(c.get("putCall", "")).upper() == "CALL"
        and float(c.get("strikePrice") or 0) == 773.0
    )
    extra = dict(src)
    extra["strikePrice"] = 790.0
    extra["daysToExpiration"] = int(src.get("daysToExpiration") or 0) + 30
    extra["expirationDate"] = "2026-10-22"
    extra["openInterest"] = 500_000
    extra["symbol"] = "SPY   261022C00790000"
    wide = chain + [extra]
    sel_ex, _ = compute_exposures_by_strike(chain, spot=spot, require_oi=True)
    terr = compute_terrain("SPY", wide, spot)
    return sel_ex, spot, terr.to_dict()










def test_terrain_cache_get_derives_staleness_from_computed_ts(monkeypatch):
    """RC-424: production cache stores computed_ts_utc, not levels_stale. terrain_cache_get
    must merge terrain_staleness so missing levels_stale cannot fail-open as fresh."""
    monkeypatch.setattr("server._is_loggable_session", lambda: True)   # an open-market test
    import time

    import server as srv

    tk = srv.ticker_storage_key("SPY")
    old_ts = time.time() - 99999.0
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "computed_ts_utc": old_ts,
            "call_wall": 760.0,
            "put_wall": 745.0,
        }
    got = srv.terrain_cache_get("SPY")
    assert got is not None
    assert got["call_wall"] == 760.0
    assert got["levels_stale"] is True
    assert "levels_stale_reason" in got
    fresh_ts = time.time()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {"computed_ts_utc": fresh_ts, "call_wall": 760.0}
    fresh = srv.terrain_cache_get("SPY")
    assert fresh["levels_stale"] is False












def test_serve_abstains_on_withheld_oi_vanna_wall_distances():
    """RC-435 / F4: serve must not median/zero-fill structurally withheld OI/vanna dists.

    Negative control: apply_xgb_imputation_matrix with SPY-like medians would invent
    finite proximities from an all-NaN withheld vector. Legitimate: gamma-wall NaN alone
    does not trip the withheld gate; finite OI/vanna values do not trip it.
    """
    import numpy as np

    from ml_train import (
        apply_xgb_imputation_matrix,
        engineered_features_missing_withheld_wall_distances,
        snapshot_missing_structurally_withheld_wall_distances,
        structurally_withheld_wall_distance_feature_names,
    )

    withheld_pct = [
        "dist_call_oi_wall_pct",
        "dist_put_oi_wall_pct",
        "dist_call_vanna_wall_pct",
        "dist_put_vanna_wall_pct",
    ]
    feats = withheld_pct + ["dist_call_gamma_wall_pct", "dist_put_gamma_wall_pct"]
    # Live engineered row: withheld NaN, gamma finite (or gamma NaN — still not withheld trip).
    x_live = np.array(
        [[np.nan, np.nan, np.nan, np.nan, 0.12, np.nan]], dtype=np.float64
    )
    assert engineered_features_missing_withheld_wall_distances(x_live[0], feats) is True
    med = {
        "dist_call_oi_wall_pct": 0.7529267869121369,
        "dist_put_oi_wall_pct": -0.8743320446674285,
        "dist_call_vanna_wall_pct": 0.12341299506538662,
        "dist_put_vanna_wall_pct": -0.20482876858755944,
        "dist_call_gamma_wall_pct": 0.12163768173631903,
        "dist_put_gamma_wall_pct": -0.1,
    }
    fabricated = apply_xgb_imputation_matrix(x_live, feats, med)[0]
    # Negative: without the gate, serve would assert these fabricated proximities.
    assert np.isfinite(fabricated[0]) and abs(fabricated[0] - med["dist_call_oi_wall_pct"]) < 1e-9
    assert np.isfinite(fabricated[2]) and abs(fabricated[2] - med["dist_call_vanna_wall_pct"]) < 1e-9

    # Legitimate: only gamma missing — withheld gate stays closed.
    x_gamma_only = np.array([[0.1, -0.2, 0.05, -0.05, np.nan, np.nan]], dtype=np.float64)
    assert engineered_features_missing_withheld_wall_distances(x_gamma_only[0], feats) is False

    # Snapshot gate: producer None on bases while model lists *_pct.
    assert snapshot_missing_structurally_withheld_wall_distances(
        {
            "dist_call_oi_wall": None,
            "dist_put_oi_wall": None,
            "dist_call_vanna_wall": None,
            "dist_put_vanna_wall": None,
            "dist_call_gamma_wall": 1.0,
        },
        feats,
    ) is True
    assert snapshot_missing_structurally_withheld_wall_distances(
        {
            "dist_call_oi_wall": 2.0,
            "dist_put_oi_wall": -3.0,
            "dist_call_vanna_wall": 1.0,
            "dist_put_vanna_wall": -1.0,
        },
        feats,
    ) is False
    # Model without withheld features never abstains on this gate.
    assert snapshot_missing_structurally_withheld_wall_distances(
        {"dist_call_oi_wall": None},
        ["dist_call_gamma_wall_pct"],
    ) is False

    names = structurally_withheld_wall_distance_feature_names()
    for col in (
        "dist_call_oi_wall",
        "dist_put_oi_wall",
        "dist_call_vanna_wall",
        "dist_put_vanna_wall",
    ):
        assert col in names and f"{col}_pct" in names

    # Serve entrypoints must gate before impute / nan_to_num.
    from pathlib import Path

    pred = Path("ml_predict.py").read_text(encoding="utf-8")
    assert "engineered_features_missing_withheld_wall_distances" in pred
    assert "snapshot_missing_structurally_withheld_wall_distances" in pred
    assert pred.count("structurally withheld OI/vanna wall distance missing") >= 2
    abl = Path("arch_competition/ablation_bundle_inference.py").read_text(encoding="utf-8")
    assert "snapshot_missing_structurally_withheld_wall_distances" in abl






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
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    snap = compute_terrain("SPY", fx["chain"], float(fx["spot"]))
    d = snap.to_dict()
    # v3 (RC-292): gamma_pin* renamed absolute_gamma_*; + pin_candidate(+blockers). The
    # v2 fields this test locks are all still carried.
    assert TERRAIN_SCHEMA_VERSION == 3 and d["schema_version"] == 3
    for fld in ("net_gex_at_spot", "key_delta_strike", "hvp", "lvp",
                "absolute_gamma_strike", "pin_candidate", "pin_candidate_blockers"):
        assert fld in d, fld + " missing from terrain payload"
    assert "gamma_pin" not in d, "the retired gamma_pin key returned to the terrain payload"
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
        100.0: {"net_gex_1pct": 5_000_000.0, "call_gex_1pct": 5_000_000.0, "dollarized": True},
        105.0: {"net_gex_1pct": 9_000_000.0, "call_gex_1pct": 9_000_000.0, "dollarized": True},
    }
    hvp, lvp = pick_volatility_point_strikes(exposures, [100.0, 105.0])
    assert hvp is None      # no negative pocket anywhere
    assert lvp == 105.0     # most positive, signed — not magnitude
