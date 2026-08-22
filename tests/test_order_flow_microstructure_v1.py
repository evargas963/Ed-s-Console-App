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

import order_flow_engine as ofe


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


def test_displayed_depth_anomaly_candidates_are_flagged_heuristic():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    # median top-5 bid size = 80; the 1000-share touch is 12.5x median -> a candidate. None on ask.
    bid_walls = [w for w in m["displayed_depth_anomaly_candidates"] if w["side"] == "bid"]
    assert bid_walls == [{"side": "bid", "price": 712.47, "volume": 1000.0, "median_mult": 12.5}]
    # The API must NOT imply an objective wall: the field is 'displayed_depth_anomaly_candidates', carries a
    # self-describing heuristic method, and is classified as a heuristic.
    assert "walls" not in m
    assert m["displayed_depth_anomaly_method"]["heuristic"] is True
    assert m["displayed_depth_anomaly_method"]["mult"] == ofe.OF_BOOK_WALL_MEDIAN_MULT
    assert "HEURISTIC" in m["classification"]["displayed_depth_anomaly_candidates"].upper()
    assert "wall_candidates" not in m


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
    assert m["displayed_depth_anomaly_candidates"] == []
    assert m["provenance"]["book_source"] == "unavailable"


def test_no_temporal_proxy_claimed():
    """The static slice must not silently emit an aggressor/CVD/absorption field."""
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    for banned in ("aggressor_side", "cvd", "cum_delta", "absorption", "iceberg"):
        assert banned not in m
    # and it names what it defers, so the omission is explicit, not accidental.
    assert any("aggressor" in d for d in m["deferred"])


def test_every_emitted_metric_is_classified():
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    cls = m["classification"]
    for key in ("mid", "microprice", "spread_pts", "spread_frac",
                "depth_pressure", "book_slope", "liquidity_concentration", "displayed_depth_anomaly_candidates"):
        assert key in cls or f"{key}.*" in cls or any(c.startswith(key) for c in cls)


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
    assert second["displayed_depth_anomaly_candidates"] == first["displayed_depth_anomaly_candidates"]
    assert second["ages"]["book_age_sec"] != first["ages"]["book_age_sec"]
    assert second["provenance"]["server_received_ts"] == 200.0
    ofe._MICRO_STRUCTURAL_CACHE.pop("CARRYTEST", None)


def test_changed_ladder_under_same_book_time_is_not_served_stale():
    """CACHE INVALIDATION: the carry cache must key on canonical book CONTENT, not BOOK_TIME
    alone. With the SAME ticker and the SAME BOOK_TIME but a MUTATED ladder, depth totals,
    imbalance, and displayed_depth_anomaly_candidates must reflect the new book — never the prior cached state."""
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
    assert [w["side"] for w in m1["displayed_depth_anomaly_candidates"]] == ["bid"]
    assert [w["side"] for w in m2["displayed_depth_anomaly_candidates"]] == ["ask"]

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
    from order_flow_engine import OrderFlowEngine
    ofe._MICRO_STRUCTURAL_CACHE.pop("SAME", None)
    data = _data()
    out = OrderFlowEngine().compute(data, ticker="SAME")
    route = ofe.compute_book_microstructure(data, ticker="SAME")
    assert out["book_microstructure"]["depth"] == route["depth"]
    assert out["book_imbalance_1"] == route["depth"]["1"]["imbalance"]
    assert out["book_imbalance_3"] == route["depth"]["3"]["imbalance"]
    assert out["book_imbalance_5"] == route["depth"]["5"]["imbalance"]
    ofe._MICRO_STRUCTURAL_CACHE.pop("SAME", None)
