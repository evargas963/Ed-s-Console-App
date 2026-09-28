"""ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 — canonical book microstructure contract.

Pins `order_flow_engine.compute_book_microstructure`: the single producer of the Order
Flow UI's book-state metrics. Deterministic synthetic book (best-first levels, a bid wall
at the touch). Asserts NATIVE/DERIVED values, ONE FAUCET (imbalance == the depth-total
ratio, i.e. the engine authority and the new totals agree), explicit classification of
every output, fail-closed on no book, and that temporal PROXY metrics are NOT produced.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.options.order_flow.engine as ofe
from app.options.order_flow.state import OrderFlowState

FIXTURE = ROOT / "tests" / "fixtures" / "real_options_stream_history_samples.json"


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
    return {"bid": 712.47, "ask": 712.49, "bid_size": 300, "ask_size": 500}


def _data() -> dict:
    return {"content": [_book_snapshot()], "top": _l1_top(), "exchange_quote_ts": 1787233769.0}


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
         "BOOK_TIME": 1}],
        "top": {"bid": 712.47, "ask": 712.49, "bid_size": 300, "ask_size": 500}}


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
    from level totals, and an invalid L1 size must not be published as a real top-of-book size.
    The L1 size is read where it is stored (OrderFlowState.push_option_top)."""
    l1 = OrderFlowState()
    l1.push_option_top("BADSIZE", {"BID_PRICE": 712.47, "ASK_PRICE": 712.49, "BID_SIZE": -5, "ASK_SIZE": 500})
    bad = {"content": [
        {"BIDS": [{"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
                  {"BID_PRICE": 712.46, "TOTAL_VOLUME": -40},          # negative -> dropped
                  {"BID_PRICE": 712.45, "TOTAL_VOLUME": float("inf")},  # non-finite -> dropped
                  {"BID_PRICE": 712.44, "TOTAL_VOLUME": 80}],
         "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}],
         "BOOK_TIME": 1}],
        "top": l1.option_top("BADSIZE")}
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
         "BOOK_TIME": 1}],
        "top": {"bid": 712.60, "ask": 712.49, "bid_size": 300, "ask_size": 500}}
    m = ofe.compute_book_microstructure(crossed, now_ts=2.0)
    assert m["crossed"] is True
    assert m["mid"] is None
    assert m["microprice"] is None
    assert m["classification"]["microprice"] == "DERIVED"   # still explicitly classified


def test_one_sided_book_fails_closed():
    """With one side of the book empty, depth imbalance cannot be computed and must be None
    (fail closed) rather than fabricated from the single populated side."""
    one = {"content": [
        {"BIDS": [], "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}], "BOOK_TIME": 1}],
        "top": {"ask": 712.49, "ask_size": 500}}
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
             "BOOK_TIME": BT}],
            "top": {"bid": bids[0][0], "ask": asks[0][0], "bid_size": 100, "ask_size": 100}}

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
# Top of book is carried, not resolved: the engine reads data["top"] (bid, ask, bid_size,
# ask_size, mark), supplied by the caller already judged live -- the equity row of
# live_market_plane under quote_is_fresh, or an option contract's OrderFlowState.option_top
# under feed_live_for. Per-field merge of Schwab's changed-fields-only ticks is the store's
# job (push_option_top below; live_market_plane for equities).
# ─────────────────────────────────────────────────────────────────────────────

def test_top_prices_and_sizes_are_carried_exactly():
    data = {"top": {"bid": 0.58, "ask": 0.59, "bid_size": 11, "ask_size": 23}}
    bid, ask, bid_leaf, ask_leaf = ofe._resolve_bid_ask_prices(data)
    assert (bid, ask) == (0.58, 0.59)
    assert (bid_leaf, ask_leaf) == ("streaming.BID_PRICE", "streaming.ASK_PRICE")
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream"
    assert pressure == (11 - 23) / (11 + 23)
    cb = ofe._extract_canonical_book(data)
    assert (cb["bid_size"], cb["ask_size"]) == (11, 23)


def test_zero_size_is_a_real_value_not_a_fallback_trigger():
    data = {"content": [_book_snapshot()], "top": {"bid": 0.10, "ask": 0.12, "bid_size": 0, "ask_size": 5}}
    pressure, tier = ofe._compute_top_book_pressure(data)
    assert tier == "schwab_stream", "a real BID_SIZE=0 must not be treated as missing"
    assert pressure == (0 - 5) / (0 + 5)
    assert ofe._extract_canonical_book(data)["bid_size"] == 0
    assert ofe.compute_book_microstructure(data, now_ts=1787233772.0)["top_of_book"]["bid_size"] == 0


def test_no_top_resolves_to_none():
    data = {"content": [{"LAST_PRICE": 0.55, "LAST_SIZE": 3}], "top": None}  # tape print only
    assert ofe._resolve_bid_ask_prices(data) == (None, None, None, None)
    assert ofe._compute_top_book_pressure(data) == (None, "unavailable")


def test_push_option_top_merges_real_partial_ticks_per_field():
    """Real LEVELONE_OPTIONS ticks (tests/fixtures, TSLA 260831C00367500): Schwab sends
    changed fields only -- the 4th tick carries BID_SIZE/ASK_SIZE and no price. The prices from
    earlier ticks stand, the sizes update. Stand-ins (named): the BID_SIZE 0 and ASK_PRICE -999
    ticks are edits of the real tick, to pin a reported 0 kept and a not-a-number clearing."""
    samples = json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]
    tsla = next(c for c in samples if c["symbol"] == "TSLA  260831C00367500")
    qqq = next(c for c in samples if c["symbol"] == "QQQ   260904C00712500")
    tsla_l1 = [e["content"] for e in tsla["events"] if e["kind"] == "l1"]
    st = OrderFlowState()
    for tick in tsla_l1[:4]:
        st.push_option_top(tsla["symbol"], tick)
    assert "BID_PRICE" not in tsla_l1[3] and "ASK_PRICE" not in tsla_l1[3]
    assert st.option_top(tsla["symbol"]) == {
        "bid": 0.56, "ask": 0.59, "bid_size": 83, "ask_size": 57, "mark": 0.575}

    st.push_option_top(tsla["symbol"], dict(tsla_l1[3], BID_SIZE=0))
    assert st.option_top(tsla["symbol"])["bid_size"] == 0

    st.push_option_top(tsla["symbol"], {"key": tsla["symbol"], "ASK_PRICE": -999})
    top = st.option_top(tsla["symbol"])
    assert "ask" not in top and top["bid"] == 0.56

    qqq_first = next(e["content"] for e in qqq["events"] if e["kind"] == "l1")
    st.push_option_top(qqq["symbol"], qqq_first)
    assert st.option_top(qqq["symbol"]) == {"bid_size": 272, "ask_size": 29}
    assert st.option_top(tsla["symbol"])["bid"] == 0.56


def test_an_equity_l1_quote_is_not_stored_a_second_time_in_order_flow_state():
    """O-01: an equity's Level-1 quote lives in live_market_plane only. push_level_one no longer
    writes a top-of-book item beside the book and tape. Stand-in (named): a hand-built
    LEVELONE_EQUITIES tick."""
    import app.options.order_flow.state as ofls
    ofls.clear_symbol("O01EQ")
    try:
        ofls.push_level_one("O01EQ", {"key": "O01EQ", "BID_PRICE": 100.0, "ASK_PRICE": 100.02,
                                      "BID_SIZE": 3, "ASK_SIZE": 4, "MARK": 100.01}, ts_recv=1_000.0)
        content = ofls.get_content_for_symbol("O01EQ")
        assert not any("BID_PRICE" in row or "ASK_PRICE" in row for row in content)
        assert ofls.option_top("O01EQ") is None
    finally:
        ofls.clear_symbol("O01EQ")


def test_size_g_the_live_push_seam_threads_each_messages_receive_time_into_push_level_one(monkeypatch):
    """The production seam (order_flow_streaming._ingest_pushed, fed by the daemon's live
    push) must hand push_level_one the MESSAGE's own ts_recv for both equity
    (LEVELONE_EQUITIES) and option (LEVELONE_OPTIONS) messages -- never the time the console
    processed it."""
    import app.options.order_flow.streaming as ofs
    from stream_spine import options_quote_msg, quote_msg

    seen = []
    monkeypatch.setattr(ofs, "push_level_one",
                        lambda sym, item, *, ts_recv: seen.append((sym, ts_recv)))
    monkeypatch.setattr(ofs._lmp, "record_from_level_one_equity", lambda *a, **k: False)
    ofs._ingest_pushed("quote.SIZEG", quote_msg(
        symbol="SIZEG", src="schwab_l1", ts_recv=1234.5, native={"LAST_PRICE": 1.0}))
    ofs._ingest_pushed("optquote.SIZEG  260918C00001000", options_quote_msg(
        symbol="SIZEG  260918C00001000", content={"BID_PRICE": 1.0}, src="schwab_options_l1",
        ts_recv=2345.5))
    assert seen == [("SIZEG", 1234.5), ("SIZEG  260918C00001000", 2345.5)]


def test_book_top_never_stands_in_for_a_missing_l1_price():
    """2026-09-24 (no fallbacks): the book's top level is a DIFFERENT feed (one venue's
    depth) and no longer stands in when L1 carries no price -- bid/ask stay absent.
    # universal-scope-ok: book shape fixture, not a SPY-only product claim.
    """
    items = [{
        "BIDS": [{"BID_PRICE": 0.02, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 0.03, "TOTAL_VOLUME": 12}],
        "BOOK_TIME": 1,
    }]
    bid, ask, bid_leaf, ask_leaf = ofe._resolve_bid_ask_prices({"content": items, "top": {"ask_size": 12}})
    assert (bid, ask, bid_leaf, ask_leaf) == (None, None, None, None)


def test_an_option_contracts_top_is_read_only_while_the_daemon_holds_it():
    """O-01: the option top of book is the engine's input only while the one live rule
    (live_market_plane.feed_live_for) holds for the contract; the daemon heartbeat now carries
    LEVELONE_OPTIONS holdings. Real TSLA 260831C00367500 ticks (tests/fixtures)."""
    import time
    import live_market_plane as lmp
    from app.options.order_flow import state
    from app.options.order_flow.live_payload import options_live_payload
    c = json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"][0]
    sym = c["symbol"]
    for ev in c["events"][:4]:
        if ev["kind"] == "l1":
            state.push_option_top(sym, ev["content"])
    try:
        lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_OPTIONS": [sym]}}, time.time())
        assert lmp.feed_live_for(sym)
        assert options_live_payload(sym)["flow"]["top_book_pressure"] is not None
        lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_OPTIONS": []}}, time.time())
        assert options_live_payload(sym)["flow"]["top_book_pressure"] is None
    finally:
        state.clear_all_live_state()


def test_the_equity_book_reads_the_one_l1_store_under_its_live_rule():
    """O-01: /api/order-flow/microstructure takes the equity top of book from live_market_plane
    while quote_is_fresh holds, and has none when the feed is down. Stand-in quote (named): bid
    10.00 x 3, ask 10.02 x 5."""
    import time
    import live_market_plane as lmp
    import server
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live("ZZTB")
    lmp.record_from_level_one_equity("ZZTB", {"LAST_PRICE": 10.01, "BID_PRICE": 10.0, "ASK_PRICE": 10.02,
                                              "BID_SIZE": 3, "ASK_SIZE": 5, "MARK": 10.01}, received_ts=time.time())
    body = json.loads(server.api_order_flow_microstructure(ticker="ZZTB").body)
    assert body["flow"]["top_book_pressure"] == (3 - 5) / 8
    lmp.record_feed_down()
    body = json.loads(server.api_order_flow_microstructure(ticker="ZZTB").body)
    assert body["flow"]["top_book_pressure"] is None
