"""Institutional consistency: dollar GEX pickers and aggregates."""

import inspect

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
from math_levels import (
    build_summary_rows,
    build_walls_rows,
    compute_pin_width_pts,
    consensus_walls_bind_terrain_ssot,
    pick_gamma_wall_strikes,
    WallsRow,
)


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


def _three_way_split_exposures():
    # institutional-synthetic-ok: three-way split needs known buckets, not a captured chain.
    # 100 = max raw call_gamma; 101 = max |call GEX$|; 120 = max total GEX$ (pin).
    return {
        100.0: {
            "call_gamma": 1000.0, "put_gamma": 1.0,
            "call_gex_1pct": 1.0, "put_gex_1pct": -1.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
        101.0: {
            "call_gamma": 10.0, "put_gamma": 1.0,
            "call_gex_1pct": 999.0, "put_gex_1pct": -1.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
        120.0: {
            "call_gamma": 5.0, "put_gamma": 5.0,
            "call_gex_1pct": 50.0, "put_gex_1pct": -5000.0,
            "call_delta": 1.0, "put_delta": 1.0,
            "call_oi": 1.0, "put_oi": 1.0,
            "call_dex_dollars": 1.0, "put_dex_dollars": 1.0,
        },
    }


def test_walls_row_does_not_ship_near_spot_raw_gamma_as_a_pin():
    """RC-418: call/put_gamma_pin was max abs raw call_gamma/put_gamma in ±5 of spot —
    not the terrain total-gamma pin and not the dollarized wall. Live /api/state asdict
    shipped the pin name anyway. The quantity had no painter; delete the authority."""
    from dataclasses import asdict, fields

    names = {f.name for f in fields(WallsRow)}
    for n in (
        "call_gamma_pin", "put_gamma_pin",
        "call_gamma_pin_strength", "put_gamma_pin_strength",
        "call_delta_pin", "put_delta_pin",
        "call_oi_pin", "put_oi_pin",
    ):
        assert n not in names
    assert not any("pin" in n for n in names)

    synth = _three_way_split_exposures()
    pin, _ = pick_pin_and_strength(synth, sorted(synth))
    (cg, _), _pg = pick_gamma_wall_strikes(synth, sorted(synth))
    assert pin == 120.0 and cg == 101.0
    walls = build_walls_rows(synth, 100.5)
    dumped = asdict(walls[0])
    assert "call_gamma_pin" not in dumped and "put_gamma_pin" not in dumped
    assert walls[0].call_gamma_wall == 101.0
    assert walls[0].put_gamma_wall == 120.0
    # Pre-fix _pick_pin would have set call_gamma_pin=100.0 on this book.
    assert 100.0 not in (walls[0].call_gamma_wall, walls[0].put_gamma_wall, pin)


def test_walls_rows_are_consensus_only_not_strike_windows():
    """RC-421: plus-minus-N WallsRow reused call_gamma_wall on the same walls[]
    list as CONSENSUS. After RC-420 CONSENSUS is terrain SSOT while those rows
    stayed selected-expiry strike-index windows — same field, two books.
    Key-level policy is CONSENSUS not ATM plus-minus-N; scoped strike-window
    analytics stay on summary_rows / totals_rows (aggregates). This builder
    emits one CONSENSUS row. OUT-OF-SCOPE: enrolled-universe live desk."""
    synth = _three_way_split_exposures()
    walls = build_walls_rows(synth, 100.5)
    assert len(walls) == 1
    assert walls[0].label == "CONSENSUS" and walls[0].window is None
    assert walls[0].call_gamma_wall == 101.0
    assert walls[0].call_gamma_strength == 999.0
    assert all(w.label == "CONSENSUS" for w in walls)
    src = inspect.getsource(build_walls_rows)
    assert "strikes_for" not in src
    assert "EXPOSURE_WINDOWS" not in src
    assert "_pick_wall_pos" not in src
    assert "_pick_wall_abs" not in src


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
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(
            encoding="utf-8"
        )
    )
    chain, spot = fx["chain"], float(fx["spot"])
    src = next(
        c for c in chain
        if str(c.get("putCall", "")).upper() == "CALL"
        and float(c.get("strikePrice") or 0) == 745.0
    )
    extra = dict(src)
    extra["strikePrice"] = 760.0
    extra["daysToExpiration"] = int(src.get("daysToExpiration") or 0) + 30
    extra["expirationDate"] = "2026-08-16"
    extra["openInterest"] = 500_000
    extra["symbol"] = "SPY   260816C00760000"
    wide = chain + [extra]
    sel_ex, _ = compute_exposures_by_strike(chain, spot=spot, require_oi=True)
    terr = compute_terrain("SPY", wide, spot)
    return sel_ex, spot, terr.to_dict()


def test_consensus_walls_bind_terrain_ssot_rewrites_mixed_book_gamma_delta():
    """RC-420: CONSENSUS gamma/delta walls follow terrain, not selected-expiry analytics.

    Live path: _fetch_state builds walls on contracts_use (selected expiry) while
    _terrain_kl_overlay paints kl_call_gamma_wall from the wide-chain cache.
    On this book the two disagree 745 vs 760 / pin_width 0.0 vs 15.0.
    """
    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = build_walls_rows(sel_ex, spot)
    assert walls[0].label == "CONSENSUS"
    assert walls[0].call_gamma_wall == 745.0
    assert walls[0].put_gamma_wall == 745.0
    assert compute_pin_width_pts(walls[0].call_gamma_wall, walls[0].put_gamma_wall) == 0.0
    assert terrain["call_wall"] == 760.0
    assert terrain["put_wall"] == 745.0
    bound = consensus_walls_bind_terrain_ssot(walls, terrain)
    assert bound[0].call_gamma_wall == 760.0
    assert bound[0].put_gamma_wall == 745.0
    assert compute_pin_width_pts(bound[0].call_gamma_wall, bound[0].put_gamma_wall) == 15.0
    assert bound[0].call_delta_wall == terrain["call_delta_wall"]
    assert bound[0].put_delta_wall == terrain["put_delta_wall"]
    assert bound[0].call_gamma_strength is None
    assert bound[0].put_gamma_strength is None
    assert bound[0].call_delta_strength is None
    assert bound[0].put_delta_strength is None
    assert bound[0].dom_gamma_side == ""
    assert bound[0].call_oi_wall is None
    assert bound[0].put_oi_wall is None
    assert bound[0].call_vanna_wall is None
    assert bound[0].put_vanna_wall is None
    assert walls[0].call_oi_wall is None
    assert len(bound) == 1 and bound[0].label == "CONSENSUS"
    assert walls[0].call_gamma_wall == 745.0


def test_consensus_walls_bind_terrain_ssot_withholds_when_stale():
    """RC-420: stale or absent terrain withholds CONSENSUS gamma/delta, never a substitute."""
    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = build_walls_rows(sel_ex, spot)
    stale = dict(terrain)
    stale["levels_stale"] = True
    withheld = consensus_walls_bind_terrain_ssot(walls, stale)
    assert withheld[0].call_gamma_wall is None
    assert withheld[0].put_gamma_wall is None
    assert withheld[0].call_delta_wall is None
    assert withheld[0].put_delta_wall is None
    assert withheld[0].call_oi_wall is None
    assert withheld[0].call_vanna_wall is None
    empty = consensus_walls_bind_terrain_ssot(walls, {})
    assert empty[0].call_gamma_wall is None
    assert empty[0].call_delta_wall is None
    assert walls[0].call_gamma_wall == 745.0


def test_consensus_oi_vanna_walls_withheld_not_selected_expiry():
    """RC-422: CONSENSUS OI/vanna walls were selected-expiry max OI / abs vanna
    while overlay blanks kl_* (terrain does not compute them). Same wall
    fields fed SignalInput, nearest, snapshot, A2 structural_levels, and OE
    wall_score. Withhold — not a second book.

    OUT-OF-SCOPE: enrolled-universe live desk. This is the RC-80/RC-422
    selected-expiry vs withheld-SSOT split on the captured SPY 0DTE fixture
    plus one later-expiry CALL, not a complete operable-surface claim.
    """
    from pathlib import Path

    from math_probabilities import compute_wall_score_components
    from v2_decision.a2_lifecycle_sidecar import _structural_levels

    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = build_walls_rows(sel_ex, spot)
    assert walls[0].label == "CONSENSUS"
    assert walls[0].call_oi_wall is None
    assert walls[0].put_oi_wall is None
    assert walls[0].call_vanna_wall is None
    assert walls[0].put_vanna_wall is None
    assert walls[0].dom_oi_wall is None
    assert walls[0].call_oi_strength is None
    assert walls[0].put_oi_strength is None
    assert walls[0].call_vanna_strength is None
    assert walls[0].put_vanna_strength is None
    assert walls[0].dom_oi_side == ""
    # Pre-fix selected-expiry pickers on this book: call/put OI 750, vanna 734
    # with strength 0.0. Wide-chain max call OI would be 760 (500000).
    bound = consensus_walls_bind_terrain_ssot(walls, terrain)
    assert bound[0].call_oi_wall is None
    assert bound[0].put_oi_wall is None
    assert bound[0].call_vanna_wall is None
    assert bound[0].put_vanna_wall is None
    assert bound[0].dom_oi_wall is None
    assert bound[0].call_gamma_wall == 760.0
    assert bound[0].put_gamma_wall == 745.0
    src = inspect.getsource(build_walls_rows)
    assert "_pick_wall_pos" not in src
    assert "_pick_wall_abs" not in src
    assert "call_oi_wall=None" in src
    bind_src = inspect.getsource(consensus_walls_bind_terrain_ssot)
    assert "call_oi_wall=None" in bind_src
    assert "call_vanna_wall=None" in bind_src
    a2_src = inspect.getsource(_structural_levels)
    assert "call_oi_wall" not in a2_src
    assert "put_oi_wall" not in a2_src
    oe_src = inspect.getsource(compute_wall_score_components)
    assert "dom_oi_wall" not in oe_src
    ms_src = Path("market_state.py").read_text(encoding="utf-8")
    assert '(_coi, "Call OI Wall")' not in ms_src
    assert '(_poi, "Put OI Wall")' not in ms_src


def test_terrain_cache_get_derives_staleness_from_computed_ts():
    """RC-424: production cache stores computed_ts_utc, not levels_stale. terrain_cache_get
    must merge terrain_staleness so missing levels_stale cannot fail-open as fresh."""
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


def test_consensus_walls_withhold_when_cache_stale_via_computed_ts():
    """RC-424: consensus_walls_bind_terrain_ssot must withhold when terrain_cache_get
    marks the snapshot stale — not treat absent levels_stale as fresh."""
    import time

    import server as srv

    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = build_walls_rows(sel_ex, spot)
    tk = srv.ticker_storage_key("SPY")
    stale_entry = dict(terrain)
    stale_entry["computed_ts_utc"] = time.time() - 99999.0
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = stale_entry
    merged = srv.terrain_cache_get("SPY")
    assert merged["levels_stale"] is True
    bound = consensus_walls_bind_terrain_ssot(walls, merged)
    assert bound[0].call_gamma_wall is None
    assert bound[0].put_gamma_wall is None
    assert bound[0].call_delta_wall is None
    assert bound[0].put_delta_wall is None
    fresh_entry = dict(terrain)
    fresh_entry["computed_ts_utc"] = time.time()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = fresh_entry
    merged_fresh = srv.terrain_cache_get("SPY")
    assert merged_fresh["levels_stale"] is False
    bound_fresh = consensus_walls_bind_terrain_ssot(walls, merged_fresh)
    assert bound_fresh[0].call_gamma_wall == 760.0
    assert bound_fresh[0].put_gamma_wall == 745.0


def test_inflections_and_oi_center_stay_analytics_not_structural_levels():
    """RC-423: selected-expiry inflections / oi_center are real analytics on
    summary_rows. Terrain does not compute them; overlay blanks kl_*.
    Nearest-level and level-density must not treat them as structural walls.

    OUT-OF-SCOPE: enrolled-universe live desk.
    """
    from pathlib import Path

    from math_levels import build_summary_rows

    sel_ex, spot, _terrain = _wide_vs_selected_wall_books()
    rows = build_summary_rows(sel_ex, spot, windows=[5])
    assert rows[0].label == "CONSENSUS"
    assert rows[0].gamma_inflection == 734.0
    assert rows[0].delta_inflection == 743.0
    assert rows[0].oi_center == 750.0
    ms_src = Path("market_state.py").read_text(encoding="utf-8")
    nearest = ms_src.split("# Nearest above/below", 1)[1].split("for _lv, _ln in _all_lvls", 1)[0]
    assert "g-Inflection" not in nearest
    assert "D-Inflection" not in nearest
    assert "Call OI Wall" not in nearest
    srv = Path("server.py").read_text(encoding="utf-8")
    dens = srv.split("# Build levels dict for density check", 1)[1].split("_level_density", 1)[0]
    assert 'getattr(consensus_summary, "oi_center"' not in dens
    assert "'gamma_inflection'" not in dens
    assert "'call_oi_wall'" not in dens


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
