"""ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 — canonical book microstructure contract.

Pins `order_flow_engine.compute_book_microstructure`: the single producer of the Order
Flow UI's book-state metrics. Deterministic synthetic book (best-first levels, a bid wall
at the touch). Asserts NATIVE/DERIVED values, ONE FAUCET (imbalance == the depth-total
ratio, i.e. the engine authority and the new totals agree), explicit classification of
every output, fail-closed on no book, and that temporal PROXY metrics are NOT produced.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.options.order_flow.engine as ofe


def _book_snapshot() -> dict:
    return {
        "BIDS": [
            {"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
            {"BID_PRICE": 712.46, "TOTAL_VOLUME": 40},
            {"BID_PRICE": 712.45, "TOTAL_VOLUME": 40},
            {"BID_PRICE": 712.44, "TOTAL_VOLUME": 80},
            {"BID_PRICE": 712.43, "TOTAL_VOLUME": 200},
        ],
        "ASKS": [
            {"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960},
            {"ASK_PRICE": 712.51, "TOTAL_VOLUME": 710},
            {"ASK_PRICE": 712.53, "TOTAL_VOLUME": 320},
            {"ASK_PRICE": 712.75, "TOTAL_VOLUME": 40},
            {"ASK_PRICE": 713.00, "TOTAL_VOLUME": 400},
        ],
        "BOOK_TIME": 1787233769563,
    }


def _l1_top() -> dict:
    return {"BID_PRICE": 712.47, "ASK_PRICE": 712.49, "BID_SIZE": 300, "ASK_SIZE": 500}


def _data() -> dict:
    return {"content": [_book_snapshot(), _l1_top()], "exchange_quote_ts": 1787233769.0}


def test_top_of_book_is_native():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    assert m["status"] == "ok"
    tob = m["top_of_book"]
    assert tob == {"bid": 712.47, "ask": 712.49, "bid_size": 300, "ask_size": 500}
    for k in ("top_of_book.bid", "top_of_book.ask", "top_of_book.bid_size", "top_of_book.ask_size"):
        assert m["classification"][k] == "NATIVE"


def test_derived_scalars():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    assert m["mid"] == 712.48
    # microprice weights each price by the OPPOSITE size: (712.47*500 + 712.49*300)/800.
    assert abs(m["microprice"] - 712.4775) < 1e-6
    assert m["spread_pts"] == 0.02
    assert m["classification"]["microprice"] == "DERIVED"


def test_depth_totals_values():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    d1, d3, d5 = m["depth"]["1"], m["depth"]["3"], m["depth"]["5"]
    assert (d1["bid_total"], d1["ask_total"]) == (1000.0, 960.0)
    assert (d3["bid_total"], d3["ask_total"]) == (1080.0, 1990.0)
    assert (d5["bid_total"], d5["ask_total"]) == (1360.0, 2430.0)


def test_one_faucet_imbalance_equals_engine_authority():
    """The microstructure imbalance must equal the engine's _compute_book_imbalance for the
    SAME snapshot — same value because both call the same helper, not by coincidence."""
    data = _data()
    m = ofe.compute_book_microstructure(data, now_ts=1787233772.0)
    for n in (1, 3, 5):
        assert m["depth"][str(n)]["imbalance"] == ofe._compute_book_imbalance(data, n)


def test_one_faucet_is_structural_not_coincidental(monkeypatch):
    """Prove single authority STRUCTURALLY: perturb the ONE aggregation helper
    (_book_side_depth_total) and both the engine imbalance AND the published depth totals must
    move together. If they were separate computations, one would ignore the patch."""
    data = _data()
    real = ofe._book_side_depth_total
    monkeypatch.setattr(ofe, "_book_side_depth_total", lambda lv, d: (real(lv, d) or 0) + 5)
    m = ofe.compute_book_microstructure(data, now_ts=1787233772.0)
    # published totals reflect the patched aggregator...
    assert m["depth"]["1"]["bid_total"] == 1000.0 + 5
    assert m["depth"]["1"]["ask_total"] == 960.0 + 5
    # ...and the engine imbalance authority reflects the SAME patched aggregator.
    assert ofe._compute_book_imbalance(data, 1) == (1005 - 965) / (1005 + 965)
    assert m["depth"]["1"]["imbalance"] == ofe._compute_book_imbalance(data, 1)


def test_book_shape_metrics():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    # slope: 1360 shares over a 0.04 price span (712.47 -> 712.43) = 34000 shares/$.
    assert abs(m["book_slope"]["bid"] - 34000.0) < 1e-6
    # concentration: 1000 at the touch / 1360 top-5 = 0.7353.
    assert abs(m["liquidity_concentration"]["bid"] - (1000.0 / 1360.0)) < 1e-9
    # depth-pressure curve is cumulative, best-first.
    bid_curve = m["depth_pressure"]["bid"]
    assert [round(x["cum"], 1) for x in bid_curve] == [1000.0, 1040.0, 1080.0, 1160.0, 1360.0]


def test_wall_candidates_are_flagged_heuristic():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    # median top-5 bid size = 80; the 1000-share touch is 12.5x median -> a candidate. None on ask.
    bid_walls = [w for w in m["wall_candidates"] if w["side"] == "bid"]
    assert bid_walls == [{"side": "bid", "price": 712.47, "volume": 1000.0, "median_mult": 12.5}]
    # The API must NOT imply an objective wall: the field is 'wall_candidates', carries a
    # self-describing heuristic method, and is classified as a heuristic.
    assert "walls" not in m
    assert m["wall_method"]["heuristic"] is True
    assert m["wall_method"]["mult"] == ofe.OF_BOOK_WALL_MEDIAN_MULT
    assert "HEURISTIC" in m["classification"]["wall_candidates"].upper()


def test_microprice_fail_closes_on_crossed_and_invalid():
    ok = ofe._microprice(712.47, 712.49, 300, 500)
    assert abs(ok - 712.4775) < 1e-9
    assert ofe._microprice(712.50, 712.49, 300, 500) is None   # crossed (bid > ask)
    assert ofe._microprice(712.47, 712.49, 0, 0) is None       # zero total size
    assert ofe._microprice(None, 712.49, 300, 500) is None     # missing leg
    assert ofe._microprice(-1.0, 712.49, 300, 500) is None     # non-positive price
    assert ofe._microprice(712.47, 712.49, -5, 500) is None    # negative size
    # locked book (bid == ask, spread 0) is a valid input, returns the common price.
    assert ofe._microprice(712.49, 712.49, 300, 500) == 712.49


def test_slope_and_concentration_sparse_and_asymmetric():
    # Sparse: a single bid level -> slope None (no span), concentration 1.0 (all at touch).
    one = {"BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 50}],
           "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 40},
                    {"ASK_PRICE": 10.2, "TOTAL_VOLUME": 40}], "BOOK_TIME": 1}
    m = ofe.compute_book_microstructure({"content": [one]}, now_ts=1.0)
    assert m["book_slope"]["bid"] is None            # <2 bid levels -> no span
    assert m["liquidity_concentration"]["bid"] == 1.0
    # Asymmetric: ask side has 2 levels over a 0.1 span -> slope = 80/0.1 = 800 shares/$.
    assert abs(m["book_slope"]["ask"] - 800.0) < 1e-9
    assert abs(m["liquidity_concentration"]["ask"] - 0.5) < 1e-9


def test_ages_from_native_timestamps():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    assert m["ages"]["book_age_sec"] == round(1787233772.0 - 1787233769.563, 3)
    assert m["ages"]["quote_age_sec"] == 3.0
    assert m["provenance"]["book_time_ms"] == 1787233769563.0
    assert m["provenance"]["exchange_quote_ts"] == 1787233769.0


def test_fail_closed_no_book():
    m = ofe.compute_book_microstructure({"content": []}, now_ts=1787233772.0)
    assert m["status"] == "no_book"
    assert m["depth"]["5"]["imbalance"] is None
    assert m["wall_candidates"] == []
    assert m["provenance"]["book_source"] == "unavailable"


def test_no_temporal_proxy_claimed():
    """The static slice must not silently emit an aggressor/CVD/absorption field."""
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    for banned in ("aggressor_side", "cvd", "cum_delta", "absorption", "iceberg"):
        assert banned not in m
    # and it names what it defers, so the omission is explicit, not accidental.
    assert any("aggressor" in d for d in m["deferred"])


def test_every_emitted_metric_is_classified():
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 10): was a
    hardcoded 8-key list checked with `key in cls or f"{key}.*" in cls or
    any(c.startswith(key) for c in cls)`. Two defects:

      (a) the third arm SUBSUMES the first two (an exact `key` entry, and a
          `"{key}.*"` entry, both satisfy `startswith(key)`), and it is a BARE
          prefix match -- so deleting the real `mid` classification while any
          unrelated `mid*` key existed still passed. Measured negative control:
          drop "mid", add "mid_price" -> old assertion PASSES, this one FAILS.
      (b) the test's NAME claims EVERY emitted metric is classified, but it only
          ever checked 8 hand-listed keys out of the 13 real metric keys the
          payload emits -- a NEW emitted metric shipped with no classification
          entry could never be caught, which is the entire defect the name
          promises to guard.

    Now the metric set is DERIVED from the actual payload, and the family match
    requires a dotted boundary (`key + "."`), so a prefix collision cannot stand
    in for the real entry."""
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    cls = m["classification"]
    # Self-describing meta blocks, not emitted metrics: the classification map
    # itself, the explicit deferral list, the status flag, and wall_method (which
    # documents HOW wall_candidates is computed and carries no metric of its own).
    meta = {"classification", "deferred", "status", "wall_method"}
    unclassified = [
        key for key in m
        if key not in meta
        and key not in cls
        and not any(c.startswith(f"{key}.") for c in cls)
    ]
    assert unclassified == [], (
        f"emitted metric(s) with no classification entry: {unclassified}. Every metric "
        f"this producer emits must declare NATIVE/DERIVED/PROXY provenance.")


def test_server_received_ts_is_classified_derived():
    """server_received_ts is the server wall clock stamped at serialization, not an
    exchange-native field — it must be labeled DERIVED, distinct from the NATIVE
    exchange_quote_ts."""
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    assert m["classification"]["provenance.server_received_ts"] == "DERIVED"
    assert m["classification"]["provenance.exchange_quote_ts"] == "NATIVE"
    assert m["provenance"]["server_received_ts"] == 1787233772.0


# ─── property tests: canonicalization, invalid input, crossed/one-sided, carry ───

def _unsorted_data() -> dict:
    # Same book as _book_snapshot's top-3 per side but levels supplied OUT OF ORDER.
    return {"content": [
        {"BIDS": [{"BID_PRICE": 712.43, "TOTAL_VOLUME": 200},
                  {"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
                  {"BID_PRICE": 712.45, "TOTAL_VOLUME": 40}],
         "ASKS": [{"ASK_PRICE": 712.53, "TOTAL_VOLUME": 320},
                  {"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960},
                  {"ASK_PRICE": 712.51, "TOTAL_VOLUME": 710}],
         "BOOK_TIME": 1},
        {"BID_PRICE": 712.47, "ASK_PRICE": 712.49, "BID_SIZE": 300, "ASK_SIZE": 500}]}


def test_unsorted_book_is_canonicalized_before_topn():
    """Levels arriving out of order must be sorted (bids desc, asks asc) BEFORE any Top-N
    semantics, so the touch and cumulative depth curve are correct regardless of input order."""
    m = ofe.compute_book_microstructure(_unsorted_data(), now_ts=2.0)
    assert m["top_of_book"]["bid"] == 712.47   # highest bid, not the 712.43 that arrived first
    assert m["top_of_book"]["ask"] == 712.49   # lowest ask, not the 712.53 that arrived first
    # depth-pressure is cumulative BEST-FIRST after sorting: 712.47(1000),712.45(40),712.43(200)
    assert [round(x["cum"], 1) for x in m["depth_pressure"]["bid"]] == [1000.0, 1040.0, 1240.0]
    # ask cumulative best-first: 712.49(960),712.51(710),712.53(320)
    assert [round(x["cum"], 1) for x in m["depth_pressure"]["ask"]] == [960.0, 1670.0, 1990.0]


def test_invalid_sizes_are_rejected():
    """Negative or non-finite displayed sizes are not real quantities — they must be dropped
    from level totals, and an invalid L1 size must not be published as a real top-of-book size."""
    bad = {"content": [
        {"BIDS": [{"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
                  {"BID_PRICE": 712.46, "TOTAL_VOLUME": -40},          # negative -> dropped
                  {"BID_PRICE": 712.45, "TOTAL_VOLUME": float("inf")},  # non-finite -> dropped
                  {"BID_PRICE": 712.44, "TOTAL_VOLUME": 80}],
         "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}],
         "BOOK_TIME": 1},
        {"BID_PRICE": 712.47, "ASK_PRICE": 712.49, "BID_SIZE": -5, "ASK_SIZE": 500}]}
    m = ofe.compute_book_microstructure(bad, now_ts=2.0)
    # only the two valid bid levels (1000 + 80) survive into the depth total
    assert m["depth"]["3"]["bid_total"] == 1080.0
    # a negative L1 bid size is withheld, not published as a real size
    assert m["top_of_book"]["bid_size"] is None
    assert m["top_of_book"]["ask_size"] == 500


def test_crossed_book_withholds_mid_and_microprice_in_full_payload():
    """A crossed book (bid > ask) is invalid microstructure — the FULL payload must withhold
    BOTH mid and microprice (not just the _microprice helper), flag crossed, and still classify."""
    crossed = {"content": [
        {"BIDS": [{"BID_PRICE": 712.60, "TOTAL_VOLUME": 1000}],
         "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}],
         "BOOK_TIME": 1},
        {"BID_PRICE": 712.60, "ASK_PRICE": 712.49, "BID_SIZE": 300, "ASK_SIZE": 500}]}
    m = ofe.compute_book_microstructure(crossed, now_ts=2.0)
    assert m["crossed"] is True
    assert m["mid"] is None
    assert m["microprice"] is None
    assert m["classification"]["microprice"] == "DERIVED"   # still explicitly classified


def test_one_sided_book_fails_closed():
    """With one side of the book empty, depth imbalance cannot be computed and must be None
    (fail closed) rather than fabricated from the single populated side."""
    one = {"content": [
        {"BIDS": [], "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}], "BOOK_TIME": 1},
        {"ASK_PRICE": 712.49, "ASK_SIZE": 500}]}
    m = ofe.compute_book_microstructure(one, now_ts=2.0)
    for n in ("1", "3", "5"):
        assert m["depth"][n]["imbalance"] is None


def test_route_serializes_carried_state_without_recomputing(monkeypatch):
    """The /api/order-flow/microstructure route and the engine call the SAME producer. Once the
    structural state is computed for (ticker, BOOK_TIME) it is memoized; a second serialization of
    the SAME unchanged book must carry that cached state, NOT re-run the structural computation."""
    ofe._MICRO_STRUCTURAL_CACHE.pop("CARRYTEST", None)
    data = _data()
    first = ofe.compute_book_microstructure(data, now_ts=100.0, ticker="CARRYTEST")

    # If the second call recomputed instead of carrying, this would raise.
    def _boom(_cb):
        raise AssertionError("structural recomputed instead of carried")
    monkeypatch.setattr(ofe, "_microstructure_structural", _boom)
    second = ofe.compute_book_microstructure(data, now_ts=200.0, ticker="CARRYTEST")

    # structural fields are identical (carried); only wall-clock ages/stamps advance.
    assert second["depth"] == first["depth"]
    assert second["top_of_book"] == first["top_of_book"]
    assert second["wall_candidates"] == first["wall_candidates"]
    assert second["ages"]["book_age_sec"] != first["ages"]["book_age_sec"]
    assert second["provenance"]["server_received_ts"] == 200.0
    ofe._MICRO_STRUCTURAL_CACHE.pop("CARRYTEST", None)


def test_changed_ladder_under_same_book_time_is_not_served_stale():
    """CACHE INVALIDATION: the carry cache must key on canonical book CONTENT, not BOOK_TIME
    alone. With the SAME ticker and the SAME BOOK_TIME but a MUTATED ladder, depth totals,
    imbalance, and wall_candidates must reflect the new book — never the prior cached state."""
    BT = 424242  # identical BOOK_TIME across both snapshots

    def _book(bids, asks) -> dict:
        return {"content": [
            {"BIDS": [{"BID_PRICE": p, "TOTAL_VOLUME": v} for p, v in bids],
             "ASKS": [{"ASK_PRICE": p, "TOTAL_VOLUME": v} for p, v in asks],
             "BOOK_TIME": BT},
            {"BID_PRICE": bids[0][0], "ASK_PRICE": asks[0][0], "BID_SIZE": 100, "ASK_SIZE": 100}]}

    # v1: heavy bid book with a bid-side size wall at the touch.
    v1 = _book(
        bids=[(712.47, 1000), (712.46, 40), (712.45, 40), (712.44, 80), (712.43, 200)],
        asks=[(712.49, 60), (712.51, 40), (712.53, 40), (712.75, 40), (713.00, 40)])
    # v2: SAME BOOK_TIME, but the book has flipped — heavy ask book with an ask-side wall.
    v2 = _book(
        bids=[(712.47, 60), (712.46, 40), (712.45, 40), (712.44, 40), (712.43, 40)],
        asks=[(712.49, 1000), (712.51, 40), (712.53, 40), (712.75, 80), (713.00, 200)])

    ofe._MICRO_STRUCTURAL_CACHE.pop("STALE", None)
    m1 = ofe.compute_book_microstructure(v1, ticker="STALE", now_ts=1.0)
    m2 = ofe.compute_book_microstructure(v2, ticker="STALE", now_ts=2.0)

    # Both snapshots genuinely carry the identical BOOK_TIME...
    assert m1["provenance"]["book_time_ms"] == m2["provenance"]["book_time_ms"] == float(BT)
    # ...yet the second read reflects the NEW ladder, not the cached first one.
    assert m1["depth"]["5"]["bid_total"] == 1360.0
    assert m2["depth"]["5"]["bid_total"] == 220.0                     # not the stale 1360
    assert m1["depth"]["1"]["imbalance"] != m2["depth"]["1"]["imbalance"]
    assert m2["depth"]["1"]["imbalance"] < 0                          # ask-heavy now
    # walls flip from the bid side to the ask side — proving walls are not served stale.
    assert [w["side"] for w in m1["wall_candidates"]] == ["bid"]
    assert [w["side"] for w in m2["wall_candidates"]] == ["ask"]

    # And an unchanged re-read of v2 (same ticker, same content) still carries without recompute.
    def _boom(_cb):
        raise AssertionError("recomputed despite identical canonical book")
    import unittest.mock as _um
    with _um.patch.object(ofe, "_microstructure_structural", _boom):
        m2b = ofe.compute_book_microstructure(v2, ticker="STALE", now_ts=3.0)
    assert m2b["depth"] == m2["depth"]
    ofe._MICRO_STRUCTURAL_CACHE.pop("STALE", None)


def test_engine_and_route_read_the_same_canonical_state():
    """OrderFlowEngine.compute carries the SAME book_microstructure the route serializes, and its
    book_imbalance_1/3/5 ARE that state's depth imbalances — one faucet, not two producers."""
    from app.options.order_flow.engine import OrderFlowEngine
    ofe._MICRO_STRUCTURAL_CACHE.pop("SAME", None)
    data = _data()
    out = OrderFlowEngine().compute(data, ticker="SAME")
    route = ofe.compute_book_microstructure(data, ticker="SAME")
    assert out["book_microstructure"]["depth"] == route["depth"]
    assert out["book_imbalance_1"] == route["depth"]["1"]["imbalance"]
    assert out["book_imbalance_3"] == route["depth"]["3"]["imbalance"]
    assert out["book_imbalance_5"] == route["depth"]["5"]["imbalance"]
    ofe._MICRO_STRUCTURAL_CACHE.pop("SAME", None)


# ─────────────────────────────────────────────────────────────────────────────
# PR214_RTH_DEFECT_REMEDIATION_V1 (2026-08-31) — Schwab LEVELONE_OPTIONS/EQUITIES
# sends partial/delta ticks (live RTH proof, TSLA 260831C00367500, ~14:00 CDT: a
# size-only tick carrying only ASK_SIZE silently masked a valid, seconds-old
# BID_PRICE/ASK_PRICE). Each top-of-book leaf (BID_PRICE, ASK_PRICE, BID_SIZE,
# ASK_SIZE) must resolve INDEPENDENTLY from the newest tick that actually carries
# it, through the ONE canonical `_latest_content_field` resolver both
# `_resolve_bid_ask_prices` and `_compute_top_book_pressure` delegate to.
# ─────────────────────────────────────────────────────────────────────────────

def test_delta_a_full_tick_resolves_all_four_fields_exactly():
    items = [{"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23}]
    data = {"content": items}
    bid, ask, bid_leaf, ask_leaf = ofe._resolve_bid_ask_prices(data)
    assert (bid, ask) == (0.58, 0.59)
    assert (bid_leaf, ask_leaf) == ("streaming.BID_PRICE", "streaming.ASK_PRICE")
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream"
    assert pressure == (11 - 23) / (11 + 23)


def test_delta_b_size_only_tick_keeps_last_known_prices_and_updates_sizes():
    items = [
        {"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23},
        {"BID_SIZE": 8, "ASK_SIZE": 35},  # real live shape: size-only delta, no price keys at all
    ]
    data = {"content": items}
    bid, ask, _, _ = ofe._resolve_bid_ask_prices(data)
    assert (bid, ask) == (0.58, 0.59), "prices must survive a size-only delta"
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream"
    assert pressure == (8 - 35) / (8 + 35), "sizes must update to the delta's own values"


def test_delta_c_bid_size_only_delta_leaves_ask_size_at_its_last_value():
    items = [
        {"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23},
        {"BID_SIZE": 6},  # bid-size-only delta
    ]
    data = {"content": items}
    bid, ask, _, _ = ofe._resolve_bid_ask_prices(data)
    assert (bid, ask) == (0.58, 0.59)
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream"
    assert pressure == (6 - 23) / (6 + 23), "ask size must retain its last known value (23)"


def test_delta_d_price_only_delta_updates_changed_leg_keeps_the_other():
    items = [
        {"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23},
        {"ASK_PRICE": 0.60},  # price-only delta on one leg
    ]
    data = {"content": items}
    bid, ask, _, _ = ofe._resolve_bid_ask_prices(data)
    assert bid == 0.58, "the unaffected leg must keep its last known value"
    assert ask == 0.60, "the changed leg must update"


def test_delta_e_zero_size_is_a_real_value_not_a_fallback_trigger():
    items = [{"BID_PRICE": 0.10, "ASK_PRICE": 0.12, "BID_SIZE": 0, "ASK_SIZE": 5}]
    data = {"content": items}
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream", "a real BID_SIZE=0 must not be treated as missing"
    assert pressure == (0 - 5) / (0 + 5)


def test_delta_f_no_valid_field_anywhere_resolves_to_none():
    items = [{"LAST_PRICE": 0.55, "LAST_SIZE": 3}]  # tape print only, no top-of-book fields
    data = {"content": items}
    assert ofe._resolve_bid_ask_prices(data) == (None, None, None, None)
    assert ofe._compute_top_book_pressure(data) == (None, "unavailable")


def test_delta_g_contract_isolation_no_bleed_across_symbols():
    """Storage-layer isolation through the REAL production path (order_flow_live_state),
    not a hand-built items list."""
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_TEST_CONTRACT_A")
    ofls.clear_symbol("RTH_TEST_CONTRACT_B")
    try:
        ofls.push_level_one("RTH_TEST_CONTRACT_A",
                            {"BID_PRICE": 9.99, "ASK_PRICE": 10.01, "BID_SIZE": 4, "ASK_SIZE": 4})
        ofls.push_level_one("RTH_TEST_CONTRACT_B", {"BID_SIZE": 2})  # never had a price of its own
        bid_a, ask_a, _, _ = ofe._resolve_bid_ask_prices(
            {"content": ofls.get_content_for_symbol("RTH_TEST_CONTRACT_A")})
        assert (bid_a, ask_a) == (9.99, 10.01)
        bid_b, ask_b, _, _ = ofe._resolve_bid_ask_prices(
            {"content": ofls.get_content_for_symbol("RTH_TEST_CONTRACT_B")})
        assert (bid_b, ask_b) == (None, None), "contract B must never see contract A's price"
    finally:
        ofls.clear_symbol("RTH_TEST_CONTRACT_A")
        ofls.clear_symbol("RTH_TEST_CONTRACT_B")


def test_storage_layer_merges_partial_ticks_not_overwrites():
    """push_level_one itself — the actual RTH-observed defect location, one layer below
    order_flow_engine's resolver: a size-only tick must not wipe a previously-stored
    price out of order_flow_live_state._top[sym]."""
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_TEST_MUTTEST")
    try:
        ofls.push_level_one("RTH_TEST_MUTTEST",
                            {"BID_PRICE": 1.23, "ASK_PRICE": 1.25, "BID_SIZE": 10, "ASK_SIZE": 10})
        ofls.push_level_one("RTH_TEST_MUTTEST", {"ASK_SIZE": 75})  # exact live shape, 2026-08-31
        data = {"content": ofls.get_content_for_symbol("RTH_TEST_MUTTEST")}
        bid, ask, _, _ = ofe._resolve_bid_ask_prices(data)
        assert (bid, ask) == (1.23, 1.25), "a size-only tick must not erase the stored price"
        pressure, tier = ofe._compute_top_book_pressure(data)
        assert tier == "schwab_stream"
        assert pressure == (10 - 75) / (10 + 75)
    finally:
        ofls.clear_symbol("RTH_TEST_MUTTEST")


def test_mutation_control_single_snapshot_selection_loses_the_price():
    """MUTATION/FAULT CONTROL: the RETIRED single-snapshot-item approach
    (`_latest_quote_snapshot`, still used by `_resolve_quote_mark` for MARK only) reads
    BOTH price and size from ONE item. Proves it gets the wrong answer on the exact
    delta sequence test B uses — the per-field fix is load-bearing, not coincidental.
    If `_resolve_bid_ask_prices`/`_compute_top_book_pressure` ever regress back to
    this shape, test B/C/D above fail; this test independently pins WHY."""
    items = [
        {"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23},
        {"BID_SIZE": 8, "ASK_SIZE": 35},
    ]
    old_snapshot = ofe._latest_quote_snapshot(items)
    assert old_snapshot is items[-1], "sanity: the retired selector picks the newest item"
    assert old_snapshot.get("BID_PRICE") is None and old_snapshot.get("ASK_PRICE") is None, (
        "the retired single-snapshot approach loses the price on this exact live-observed "
        "delta shape — this is the regression the fix must not reintroduce")
    bid, ask, _, _ = ofe._resolve_bid_ask_prices({"content": items})
    assert (bid, ask) == (0.58, 0.59), "the FIXED resolver must not reproduce the loss above"


# ─────────────────────────────────────────────────────────────────────────────
# PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS — Gap 1: the per-field resolver above has NO
# freshness bound -- it could combine a fresh BID_SIZE with an arbitrarily old BID_PRICE.
# A carried-forward field is valid only within OF_TOP_OF_BOOK_FIELD_STALE_SEC (== the
# EXISTING order_flow_streaming.STREAMING_STALE_MS canonical staleness policy, not an
# invented number) of its own observation. These tests drive the REAL production path
# (order_flow_live_state.push_level_one, which stamps a "{field}_TS_RECV" sibling per
# field) with explicit `ts_recv`/`now_ts` so freshness is deterministic, not wall-clock.
# ─────────────────────────────────────────────────────────────────────────────

def test_groundedness_freshness_bound_matches_existing_streaming_stale_ms():
    """The Gap-1 bound must be THE existing canonical stream-health threshold, not a
    second, independently-invented number that could silently drift from it."""
    import app.options.order_flow.streaming as ofs
    assert ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC * 1000.0 == ofs.STREAMING_STALE_MS


def test_freshness_a_full_tick_then_immediate_size_only_delta_preserves_price():
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_A")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_A",
                            {"BID_PRICE": 0.58, "ASK_PRICE": 0.59, "BID_SIZE": 11, "ASK_SIZE": 23},
                            ts_recv=t0)
        ofls.push_level_one("RTH_FRESH_A", {"BID_SIZE": 8, "ASK_SIZE": 35}, ts_recv=t0 + 0.2)
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_A")}
        bid, ask, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=t0 + 0.2)
        assert (bid, ask) == (0.58, 0.59), "price a fraction of a second old must survive"
    finally:
        ofls.clear_symbol("RTH_FRESH_A")


def test_freshness_b_several_fresh_deltas_keep_prior_price_usable():
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_B")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_B",
                            {"BID_PRICE": 12.30, "ASK_PRICE": 12.35, "BID_SIZE": 5, "ASK_SIZE": 5},
                            ts_recv=t0)
        for i in range(1, 6):  # five more size-only deltas, each a few seconds apart
            ofls.push_level_one("RTH_FRESH_B", {"BID_SIZE": 5 + i, "ASK_SIZE": 5 + i},
                                ts_recv=t0 + i * 3.0)
        now = t0 + 5 * 3.0 + 1.0  # 16s after the price tick -- inside the 25s bound
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_B")}
        bid, ask, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=now)
        assert (bid, ask) == (12.30, 12.35), "prior price must remain usable across several fresh deltas"
    finally:
        ofls.clear_symbol("RTH_FRESH_B")


def test_freshness_c_price_older_than_boundary_becomes_unavailable():
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_C")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_C",
                            {"BID_PRICE": 7.77, "ASK_PRICE": 7.79, "BID_SIZE": 9, "ASK_SIZE": 9},
                            ts_recv=t0)
        now_just_inside = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC - 0.01
        now_just_outside = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC + 0.01
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_C")}
        bid_in, ask_in, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=now_just_inside)
        assert (bid_in, ask_in) == (7.77, 7.79), "still within the freshness boundary"
        bid_out, ask_out, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=now_just_outside)
        assert (bid_out, ask_out) == (None, None), (
            "a price older than the freshness boundary must resolve to unavailable, "
            "not be carried forward indefinitely")
    finally:
        ofls.clear_symbol("RTH_FRESH_C")


def test_freshness_d_previous_epoch_price_never_carries_forward_even_if_technically_fresh():
    """Item D, freshness-aware: a still-within-window price from a PRIOR contract must
    never appear for a NEW contract on the same symbol slot after a switch -- epoch
    isolation (clear_symbol) takes precedence over recency."""
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_D")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_D",
                            {"BID_PRICE": 3.10, "ASK_PRICE": 3.15, "BID_SIZE": 4, "ASK_SIZE": 4},
                            ts_recv=t0)
        # Contract switch: the prior contract's state is cleared before the new one is pushed.
        ofls.clear_symbol("RTH_FRESH_D")
        ofls.push_level_one("RTH_FRESH_D", {"BID_SIZE": 6}, ts_recv=t0 + 1.0)
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_D")}
        # now_ts is only 1s after the OLD price's ts_recv -- well within the freshness window --
        # proving the absence is from epoch isolation, not from staleness rejection.
        bid, ask, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=t0 + 1.0)
        assert (bid, ask) == (None, None), "a fresh-looking price from the PRIOR epoch must never carry forward"
    finally:
        ofls.clear_symbol("RTH_FRESH_D")


def test_freshness_e_fresh_bid_but_stale_ask_does_not_publish_a_falsely_complete_pair():
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_E")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_E",
                            {"BID_PRICE": 20.00, "ASK_PRICE": 20.10, "BID_SIZE": 3, "ASK_SIZE": 3},
                            ts_recv=t0)
        # Only BID_PRICE refreshes; ASK_PRICE's TS_RECV stays pinned at t0.
        t_bid_refresh = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC - 1.0
        ofls.push_level_one("RTH_FRESH_E", {"BID_PRICE": 20.05}, ts_recv=t_bid_refresh)
        now = t_bid_refresh + 2.0  # ask is now (now - t0) > bound old; bid is fresh
        assert (now - t0) > ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC
        assert (now - t_bid_refresh) <= ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_E")}
        bid, ask, _, _ = ofe._resolve_bid_ask_prices(data, now_ts=now)
        assert bid == 20.05, "the freshly-updated leg must still resolve"
        assert ask is None, "a stale leg must not be paired with a fresh one as a falsely-complete top of book"
    finally:
        ofls.clear_symbol("RTH_FRESH_E")


def test_freshness_f_zero_remains_a_valid_value_under_the_freshness_bound():
    import order_flow_live_state as ofls
    ofls.clear_symbol("RTH_FRESH_F")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("RTH_FRESH_F",
                            {"BID_PRICE": 5.00, "ASK_PRICE": 5.02, "BID_SIZE": 0, "ASK_SIZE": 7},
                            ts_recv=t0)
        data = {"content": ofls.get_content_for_symbol("RTH_FRESH_F")}
        pressure, tier = ofe._compute_top_book_pressure(data, now_ts=t0 + 1.0)
        assert tier == "schwab_stream", "a real BID_SIZE=0 must not be treated as missing under freshness bounding"
        assert pressure == (0 - 7) / (0 + 7)
    finally:
        ofls.clear_symbol("RTH_FRESH_F")


# ─────────────────────────────────────────────────────────────────────────────
# PR214_TOP_OF_BOOK_SIZE_FRESHNESS_FINAL — the SAME defect class, one remaining path:
# _extract_canonical_book's published bid_size/ask_size used to come from
# _latest_quote_snapshot (a single "latest" content item), not the freshness-aware
# per-field resolver Gap 1 already wired for BID_PRICE/ASK_PRICE/top_book_pressure.
# Now bid_size/ask_size resolve through the SAME _latest_content_field authority, the
# SAME now_ts, the SAME OF_TOP_OF_BOOK_FIELD_STALE_SEC boundary. These tests drive the
# REAL production path (order_flow_live_state.push_level_one, explicit ts_recv) so
# freshness is deterministic, matching the Gap 1 freshness tests above.
# ─────────────────────────────────────────────────────────────────────────────

def test_size_a_fresh_bid_and_ask_size_resolve_exactly():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_A")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_A",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 17, "ASK_SIZE": 29},
                            ts_recv=t0)
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_A")}
        cb = ofe._extract_canonical_book(data, now_ts=t0 + 1.0)
        assert (cb["bid_size"], cb["ask_size"]) == (17, 29)
        # end-to-end: the full microstructure payload's top_of_book carries the same values.
        m = ofe.compute_book_microstructure(data, now_ts=t0 + 1.0)
        assert m["top_of_book"]["bid_size"] == 17
        assert m["top_of_book"]["ask_size"] == 29
    finally:
        ofls.clear_symbol("SIZE_FRESH_A")


def test_size_b_fresh_price_but_stale_bid_size_is_unavailable():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_B")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_B",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 17, "ASK_SIZE": 29},
                            ts_recv=t0)
        # Refresh price on both legs and ASK_SIZE; BID_SIZE's ts_recv stays pinned at t0.
        t_refresh = t0 + 1.0
        ofls.push_level_one("SIZE_FRESH_B",
                            {"BID_PRICE": 4.11, "ASK_PRICE": 4.13, "ASK_SIZE": 30},
                            ts_recv=t_refresh)
        now = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC + 1.0  # BID_SIZE now stale; price/ASK_SIZE fresh
        assert (now - t_refresh) <= ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_B")}
        cb = ofe._extract_canonical_book(data, now_ts=now)
        assert (cb["bid"], cb["ask"]) == (4.11, 4.13), "the refreshed price must resolve"
        assert cb["bid_size"] is None, "a stale BID_SIZE must not be published as a real size"
        assert cb["ask_size"] == 30, "the refreshed ASK_SIZE must still resolve"
    finally:
        ofls.clear_symbol("SIZE_FRESH_B")


def test_size_c_fresh_bid_size_but_stale_ask_size_is_unavailable():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_C")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_C",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 17, "ASK_SIZE": 29},
                            ts_recv=t0)
        # Refresh price on both legs and BID_SIZE; ASK_SIZE's ts_recv stays pinned at t0.
        t_refresh = t0 + 1.0
        ofls.push_level_one("SIZE_FRESH_C",
                            {"BID_PRICE": 4.11, "ASK_PRICE": 4.13, "BID_SIZE": 18},
                            ts_recv=t_refresh)
        now = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC + 1.0  # ASK_SIZE now stale; price/BID_SIZE fresh
        assert (now - t_refresh) <= ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_C")}
        cb = ofe._extract_canonical_book(data, now_ts=now)
        assert cb["bid_size"] == 18, "the refreshed BID_SIZE must still resolve"
        assert cb["ask_size"] is None, (
            "a stale ASK_SIZE must not be published alongside a fresh BID_SIZE as a falsely-complete pair")
    finally:
        ofls.clear_symbol("SIZE_FRESH_C")


def test_size_d_size_only_partial_delta_inside_window_survives():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_D")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_D",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 17, "ASK_SIZE": 29},
                            ts_recv=t0)
        ofls.push_level_one("SIZE_FRESH_D", {"BID_SIZE": 40, "ASK_SIZE": 41}, ts_recv=t0 + 2.0)
        now = t0 + 2.5  # well inside the freshness window of the size-only delta
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_D")}
        cb = ofe._extract_canonical_book(data, now_ts=now)
        assert (cb["bid_size"], cb["ask_size"]) == (40, 41), "the new delta sizes must survive, not the stale originals"
        assert (cb["bid"], cb["ask"]) == (4.10, 4.12), "price must survive the size-only delta unchanged"
    finally:
        ofls.clear_symbol("SIZE_FRESH_D")


def test_size_e_zero_bid_size_resolves_as_a_real_value():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_E")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_E",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 0, "ASK_SIZE": 5},
                            ts_recv=t0)
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_E")}
        cb = ofe._extract_canonical_book(data, now_ts=t0 + 1.0)
        assert cb["bid_size"] == 0, "a real BID_SIZE=0 must resolve as 0, not None"
        m = ofe.compute_book_microstructure(data, now_ts=t0 + 1.0)
        assert m["top_of_book"]["bid_size"] == 0
    finally:
        ofls.clear_symbol("SIZE_FRESH_E")


def test_size_f_stale_price_and_stale_sizes_yield_no_falsely_complete_top_of_book():
    import order_flow_live_state as ofls
    ofls.clear_symbol("SIZE_FRESH_F")
    try:
        t0 = 1_000_000.0
        ofls.push_level_one("SIZE_FRESH_F",
                            {"BID_PRICE": 4.10, "ASK_PRICE": 4.12, "BID_SIZE": 17, "ASK_SIZE": 29},
                            ts_recv=t0)
        now = t0 + ofe.OF_TOP_OF_BOOK_FIELD_STALE_SEC + 1.0  # nothing refreshed -- everything stale
        data = {"content": ofls.get_content_for_symbol("SIZE_FRESH_F")}
        cb = ofe._extract_canonical_book(data, now_ts=now)
        assert (cb["bid"], cb["ask"], cb["bid_size"], cb["ask_size"]) == (None, None, None, None), (
            "stale price AND stale sizes must never be published as a falsely-complete top of book")
    finally:
        ofls.clear_symbol("SIZE_FRESH_F")


def test_size_g_production_replay_seams_thread_ts_recv_into_push_level_one():
    """Direct source proof of the two known production replay seams (not a repo-wide
    audit): order_flow_streaming._replay_new_rows (equity LEVELONE_EQUITIES) and
    _replay_option_contract_rows (LEVELONE_OPTIONS) must both call push_level_one with
    the real stream_capture.db row's own ts_recv threaded through -- so the live PR #214
    streaming path cannot silently fall back to an unbounded/approximated timestamp and
    bypass the freshness boundary this file proves above."""
    import inspect
    import app.options.order_flow.streaming as ofs
    equity_src = inspect.getsource(ofs._replay_new_rows)
    assert "push_level_one(ticker, item, ts_recv=ts_recv)" in equity_src, (
        "equity replay seam must thread the real row ts_recv into push_level_one")
    options_src = inspect.getsource(ofs._replay_option_contract_rows)
    assert "push_level_one(contract_symbol, item, ts_recv=ts_recv)" in options_src, (
        "options replay seam must thread the real row ts_recv into push_level_one")


def test_book_top_fills_bid_ask_when_l1_has_no_price():
    """OPTIONS_BOOK / NASDAQ_BOOK already in content is the live top when L1 is size-only.
    # universal-scope-ok: book shape fixture, not a SPY-only product claim.
    """
    items = [{
        "BIDS": [{"BID_PRICE": 0.02, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 0.03, "TOTAL_VOLUME": 12}],
        "BOOK_TIME": 1,
    }, {"ASK_SIZE": 12}]
    bid, ask, bid_leaf, ask_leaf = ofe._resolve_bid_ask_prices({"content": items})
    assert bid == 0.02
    assert ask == 0.03
    assert bid_leaf == "streaming.BOOK.BID_PRICE"
    assert ask_leaf == "streaming.BOOK.ASK_PRICE"
