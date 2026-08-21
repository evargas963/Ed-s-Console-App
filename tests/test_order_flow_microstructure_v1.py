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
    m = ofe.compute_book_microstructure(_data(), now_ts=1787233772.0)
    cls = m["classification"]
    for key in ("mid", "microprice", "spread_pts", "spread_frac",
                "depth_pressure", "book_slope", "liquidity_concentration", "wall_candidates"):
        assert key in cls or f"{key}.*" in cls or any(c.startswith(key) for c in cls)
