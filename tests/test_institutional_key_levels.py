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
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 1 of the 17-20 block):
    was `assert cg is not None or pg is not None` -- presence-only, with an `or` that
    made a ONE-SIDED TOTAL FAILURE invisible. pick_gamma_wall_strikes resolves the call
    wall and the put wall through two INDEPENDENT _pick_strike_max_metric calls; if the
    put side returned None for every strike, `cg is not None` alone kept this green.
    That is not hypothetical: put_gex_1pct is stored NEGATIVE, and _pick_strike_max_metric
    skips any value <= 0, so dropping the abs() in bucket_metric_abs makes pg None for
    EVERY chain -- and the old assertion passed. Both picks are now pinned to the values
    this fixture actually produces (measured 745.0/745.0/745.0, the same numbers
    test_consensus_walls_bind_terrain_ssot... pins downstream through build_walls_rows)."""
    exposures, spot = _dollarized_exposures()
    hvl = pick_hvl_strike(exposures, sorted(exposures.keys()))
    assert hvl == 745.0, f"HVL moved off the fixture's known strike: {hvl}"
    (cg, _), (pg, _) = pick_gamma_wall_strikes(exposures, sorted(exposures.keys()))
    assert cg == 745.0, f"call gamma wall moved: {cg}"
    assert pg == 745.0, (
        f"put gamma wall moved: {pg} — a None here means the put side stopped resolving "
        f"entirely (the negative-metric/abs() regression), which the old `or` hid")


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
    from math_probabilities import compute_wall_score_components

    prox, _, audit = compute_wall_score_components(760.0, spot, "CALL", bound)
    levels_scored = [d["level"] for d in audit.get("proximity_detail", [])]
    assert bound[0].dom_delta_wall is None
    assert "call_delta_wall" in levels_scored
    assert "put_delta_wall" in levels_scored
    assert "dom_delta_wall" not in levels_scored
    assert prox > 0.0
    oe_src = inspect.getsource(compute_wall_score_components)
    assert '"call_delta_wall"' in oe_src
    assert '"put_delta_wall"' in oe_src
    # RC-434: dominance is not a third proximity/bias faucet.
    assert '"dom_gamma_wall"' not in oe_src
    assert '"dom_delta_wall"' not in oe_src
    assert "dom_gamma_call_confluence" not in oe_src
    assert "dom_gamma_put_confluence" not in oe_src
    # Bias bonuses are approach/support only (0.85 / 0.55) — no strength-gated alias bonus.
    assert "bias += 0.45" not in oe_src
    assert "bias +=0.45" not in oe_src


def test_oe_wall_score_drops_obsolete_dom_gamma_confluence():
    """RC-434: +0.45 dom_gamma_*_confluence is obsolete scoring, not a missing producer.

    `_dominant` aliases the stronger of call/put wall. After RC-420 bind withholds
    strengths, live dominance is permanently empty — silent inert decision logic.
    Even with fabricated strengths, scoring dom_gamma_wall again double-counts the
    same strike already scored as call/put. Remove from OE proximity and bias.

    OUT-OF-SCOPE: terrain stamping wall GEX$ for display-only dominance metadata;
    enrolled-universe live desk.
    """
    from dataclasses import replace

    from math_levels import build_walls_rows, consensus_walls_bind_terrain_ssot
    from math_probabilities import compute_wall_score_components

    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    bound = consensus_walls_bind_terrain_ssot(build_walls_rows(sel_ex, spot), terrain)
    assert bound[0].dom_gamma_side == ""
    assert bound[0].dom_gamma_wall is None
    # Live bound path: approach zone still works; confluence never appears.
    prox, bias, audit = compute_wall_score_components(760.0, spot, "CALL", bound)
    assert "strike_in_call_gamma_wall_approach_zone" in (audit.get("bias_notes") or [])
    assert bias == 0.85
    assert all("dom_gamma" not in n for n in (audit.get("bias_notes") or []))
    assert all(d["level"] != "dom_gamma_wall" for d in audit.get("proximity_detail", []))
    # Negative: even a fabricated dominant CALL wall at the call strike must NOT
    # revive +0.45 or a third proximity contrib (pre-fix did both).
    fake = replace(
        bound[0],
        call_gamma_strength=1_000.0,
        put_gamma_strength=100.0,
        dom_gamma_side="CALL",
        dom_gamma_wall=bound[0].call_gamma_wall,
        dom_gamma_strength=1_000.0,
    )
    prox2, bias2, audit2 = compute_wall_score_components(760.0, spot, "CALL", [fake])
    notes2 = audit2.get("bias_notes") or []
    levels2 = [d["level"] for d in audit2.get("proximity_detail", [])]
    assert "dom_gamma_call_confluence" not in notes2
    assert "dom_gamma_wall" not in levels2
    assert bias2 == 0.85  # approach only — not 0.85+0.45
    # Unbound selected-expiry row historically had dom PUT == put wall; proximity
    # must not list dom_gamma_wall beside put_gamma_wall.
    unbound = build_walls_rows(sel_ex, spot)
    assert unbound[0].dom_gamma_wall is not None
    _, _, audit3 = compute_wall_score_components(
        float(unbound[0].dom_gamma_wall), spot, "PUT", unbound
    )
    levels3 = [d["level"] for d in audit3.get("proximity_detail", [])]
    assert "dom_gamma_wall" not in levels3
    assert all("dom_gamma" not in n for n in (audit3.get("bias_notes") or []))


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
    dens_body = dens.split("_all_levels = {}", 1)[1]
    assert 'getattr(consensus_summary, "oi_center"' not in dens_body
    assert "'gamma_inflection'" not in dens_body
    assert "'call_oi_wall'" not in dens_body
    # RC-432: density must not use selected-expiry `_gamma_flip` or locals()._cgw lookups.
    # Assert on dens_body only — historical comments may still name the dead locals pattern.
    assert "if _gamma_flip:" not in dens_body
    assert "locals().get(" not in dens_body
    assert "_w0" in dens_body
    assert 'get("gamma_flip")' in dens_body
    ce = Path("call_engine.py").read_text(encoding="utf-8")
    rdy = ce.split("_nearest_dist = None", 1)[1].split("_level_prox =", 1)[0]
    assert "dist_gamma_inflection" not in rdy
    re_src = Path("rules_engine.py").read_text(encoding="utf-8")
    assert "regime flip zone" not in re_src
    assert "dist_gamma_inflection" not in re_src


def test_level_density_uses_terrain_bound_walls_not_dead_locals():
    """RC-432: pre-fix density used locals()._cgw (assigned ~700 lines later) so
    walls never entered; label could read 'clear' while a terrain put wall sat
    inside the radius. Density must count bound CONSENSUS walls.
    """
    from pathlib import Path

    from math_levels import (
        build_walls_rows,
        compute_level_density,
        consensus_walls_bind_terrain_ssot,
    )

    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = consensus_walls_bind_terrain_ssot(build_walls_rows(sel_ex, spot), terrain)
    assert walls[0].put_gamma_wall == 745.0
    # Negative: abs-gamma-only (pre-fix effective book) → clear. RC-292: the payload and
    # density key is absolute_gamma_strike.
    broken = compute_level_density(
        {"absolute_gamma_strike": float(terrain["absolute_gamma_strike"])}, spot)
    assert broken["density_label"] == "clear"
    assert broken["count"] == 0
    # Legitimate: terrain-bound walls enter density.
    ok = {
        "absolute_gamma_strike": float(terrain["absolute_gamma_strike"]),
        "call_gamma_wall": float(walls[0].call_gamma_wall),
        "put_gamma_wall": float(walls[0].put_gamma_wall),
    }
    if walls[0].call_delta_wall is not None:
        ok["call_delta_wall"] = float(walls[0].call_delta_wall)
    if walls[0].put_delta_wall is not None:
        ok["put_delta_wall"] = float(walls[0].put_delta_wall)
    fixed = compute_level_density(ok, spot)
    assert "put_gamma_wall" in (fixed["level_names"] or [])
    assert fixed["density_label"] == "light"
    assert fixed["count"] == 1
    src = Path("server.py").read_text(encoding="utf-8")
    dens = src.split("# Build levels dict for density check", 1)[1].split(
        "_level_density = compute_level_density", 1
    )[0]
    body = dens.split("_all_levels = {}", 1)[1]
    assert "locals().get(" not in body
    assert "if _gamma_flip:" not in body
    assert "_w0" in body
    assert 'get("gamma_flip")' in dens


def test_level_density_uses_terrain_iv_sigma_em_not_remaining_risk_em():
    """RC-433 / F06: density must count the same EM band KL paints (terrain
    IV_SIGMA_1D), not remaining-risk STRADDLE_IMPLIED / IV_MODEL `_em_up`.

    OUT-OF-SCOPE: enrolled-universe live desk; F10 retrain; F11 Schwab tick.
    """
    from pathlib import Path

    from math_levels import (
        build_walls_rows,
        compute_level_density,
        consensus_walls_bind_terrain_ssot,
    )

    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    walls = consensus_walls_bind_terrain_ssot(build_walls_rows(sel_ex, spot), terrain)
    base = {
        "absolute_gamma_strike": float(terrain["absolute_gamma_strike"]),
        "call_gamma_wall": float(walls[0].call_gamma_wall),
        "put_gamma_wall": float(walls[0].put_gamma_wall),
    }
    # Negative: remaining-risk EM inside the 3pt radius inflates congestion.
    broken = compute_level_density(
        {**base, "em_upper": spot + 2.0, "em_lower": spot - 2.0},
        spot,
    )
    assert broken["count"] == 3
    assert broken["density_label"] == "moderate"
    assert "em_upper" in (broken["level_names"] or [])
    # Legitimate: terrain IV_SIGMA_1D band (±11.6 on this fixture) matches KL and
    # stays outside the density radius — same count as walls-only.
    pts = float((terrain.get("implied_1d_move") or {})["points"])
    tsp = float(terrain["spot"])
    assert pts > 3.0
    ok = {
        **base,
        "em_upper": tsp + pts,
        "em_lower": tsp - pts,
    }
    fixed = compute_level_density(ok, spot)
    assert fixed["count"] == 1
    assert fixed["density_label"] == "light"
    assert "em_upper" not in (fixed["level_names"] or [])
    # Source lock: dens body binds implied_1d_move, not `_em_up`.
    dens = Path("server.py").read_text(encoding="utf-8").split(
        "# Build levels dict for density check", 1
    )[1].split("_level_density = compute_level_density", 1)[0]
    body = dens.split("_all_levels = {}", 1)[1]
    assert "implied_1d_move" in body
    assert "if _em_up:" not in body
    # Executable dens lines only — comments may name the retired remaining-risk binders.
    code_lines = [
        ln for ln in body.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "_em_up" not in code
    assert "_em_band_source" not in code
    assert 'em_upper"] = float(_em_spot) + float(_em_pts)' in code or (
        "em_upper" in code and "_em_pts" in code and "_em_spot" in code
    )


def test_withheld_oi_vanna_dist_remain_schema_slots_live_none():
    """F4 / RC-422: OI/vanna walls withheld live. dist_* stay in the feature
    contract so artifact widths do not break. Live producer is None.

    OUT-OF-SCOPE: dropping columns (would bump FEATURE_SCHEMA_VERSION and
    fail-close v7 bundles). Historical snapshot rows may still hold selected-expiry
    distances from before the withhold.
    """
    from pathlib import Path

    withheld = (
        "dist_call_oi_wall",
        "dist_put_oi_wall",
        "dist_call_vanna_wall",
        "dist_put_vanna_wall",
    )
    ml = Path("ml_train.py").read_text(encoding="utf-8")
    wall_block = ml.split("WALL_DISTANCE_COLS = [", 1)[1].split("]", 1)[0]
    for col in withheld:
        assert f'"{col}"' in wall_block
    pred = Path("prediction_engine.py").read_text(encoding="utf-8")
    lstm = Path("lstm_data.py").read_text(encoding="utf-8")
    assert '"dist_call_oi_wall": inp.dist_call_oi_wall' in pred
    assert '"dist_put_oi_wall": inp.dist_put_oi_wall' in pred
    assert "dist_call_oi_wall" in lstm
    assert "np.nan_to_num(X_5m, nan=0.0)" in lstm
    sel_ex, spot, terrain = _wide_vs_selected_wall_books()
    bound = consensus_walls_bind_terrain_ssot(build_walls_rows(sel_ex, spot), terrain)
    assert bound[0].call_oi_wall is None
    assert bound[0].put_oi_wall is None
    assert bound[0].call_vanna_wall is None
    assert bound[0].put_vanna_wall is None
    live_dist = None if bound[0].call_oi_wall is None else bound[0].call_oi_wall - spot
    assert live_dist is None


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


def test_rc435_abstain_disables_active_ml_fleet():
    """RC-436: RC-435 abstain is fleet-wide on live withheld OI/vanna — not a niche tick.

    Negative control: a feature list without withheld names must not gate.
    Retrain blocker: model_feature_wall_distance_cols excludes the four bases but
    is not yet the live WALL_DISTANCE_COLS contract (width/schema bump owed on host).
    """
    import json
    from pathlib import Path

    from lstm_data import (
        FEATURES_5M,
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_FEATURES_5M,
        checkpoint_encoder_schema_version,
    )
    from ml_train import (
        STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS,
        model_feature_wall_distance_cols,
        snapshot_missing_structurally_withheld_wall_distances,
    )

    withheld_pct = {
        "dist_call_oi_wall_pct",
        "dist_put_oi_wall_pct",
        "dist_call_vanna_wall_pct",
        "dist_put_vanna_wall_pct",
    }
    live = {
        "dist_call_oi_wall": None,
        "dist_put_oi_wall": None,
        "dist_call_vanna_wall": None,
        "dist_put_vanna_wall": None,
    }
    active = Path("models/active")
    xgb_tri = [
        p
        for p in sorted(active.rglob("xgb_*_meta.json"))
        if "_dir_" not in p.name and "_move_" not in p.name
    ]
    assert len(xgb_tri) >= 14  # enrolled-universe floor
    require = 0
    for p in xgb_tri:
        feats = json.loads(p.read_text(encoding="utf-8")).get("features") or []
        if set(feats) & withheld_pct:
            require += 1
        assert snapshot_missing_structurally_withheld_wall_distances(live, feats) is True
    assert require == len(xgb_tri)

    # Negative: gamma-only feature list does not trip the withheld gate.
    assert (
        snapshot_missing_structurally_withheld_wall_distances(
            live, ["dist_call_gamma_wall_pct", "dist_put_gamma_wall_pct"]
        )
        is False
    )

    import torch

    serveable = 0
    for pattern in ("lstm_*.pt", "transformer_*.pt"):
        for pt in sorted(active.rglob(pattern)):
            ck = torch.load(pt, map_location="cpu", weights_only=False)
            ver = checkpoint_encoder_schema_version(ck)
            if ver < LEGACY_ENCODER_SCHEMA_VERSION:
                continue
            serveable += 1
            feats = (
                LEGACY_V2_FEATURES_5M
                if ver == LEGACY_ENCODER_SCHEMA_VERSION
                else FEATURES_5M
            )
            assert snapshot_missing_structurally_withheld_wall_distances(live, feats) is True
    assert serveable >= 8  # 5 LSTM + 5 Transformer on current main fleet

    retired = model_feature_wall_distance_cols()
    for col in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS:
        assert col not in retired
        assert col + "_pct" not in retired
    assert "dist_call_gamma_wall" in retired
    assert "dist_put_delta_wall" in retired
    # Live encode contract still includes withheld bases (width lock until host retrain).
    from ml_train import WALL_DISTANCE_COLS

    for col in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS:
        assert col in WALL_DISTANCE_COLS


def test_radar_terrain_snapshots_derive_staleness_from_computed_ts():
    """RC-427: /api/terrain/radar reads _terrain_snapshots_for_radar, which must merge
    terrain_staleness like terrain_cache_get — not fail-open when levels_stale absent."""
    import time

    import server as srv

    tk = srv.ticker_storage_key("SPY")
    old_ts = time.time() - 99999.0
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": "SPY",
            "computed_ts_utc": old_ts,
            "call_wall": 760.0,
            "confidence": "TRUSTED",
            "spot": 755.0,
        }
    snaps = srv._terrain_snapshots_for_radar()
    spy = next((s for s in snaps if s.get("ticker") == "SPY"), None)
    assert spy is not None
    assert spy["levels_stale"] is True
    assert "levels_stale_reason" in spy
    fresh_ts = time.time()
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "ticker": "SPY",
            "computed_ts_utc": fresh_ts,
            "call_wall": 760.0,
            "confidence": "TRUSTED",
            "spot": 755.0,
        }
    fresh_snaps = srv._terrain_snapshots_for_radar()
    fresh_spy = next((s for s in fresh_snaps if s.get("ticker") == "SPY"), None)
    assert fresh_spy["levels_stale"] is False


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
        100.0: {"net_gex_1pct": 5_000_000.0, "call_gex_1pct": 5_000_000.0},
        105.0: {"net_gex_1pct": 9_000_000.0, "call_gex_1pct": 9_000_000.0},
    }
    hvp, lvp = pick_volatility_point_strikes(exposures, [100.0, 105.0])
    assert hvp is None      # no negative pocket anywhere
    assert lvp == 105.0     # most positive, signed — not magnitude
