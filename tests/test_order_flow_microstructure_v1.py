"""ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 — canonical book microstructure contract.

Pins `order_flow_engine.compute_book_microstructure`: the single producer of the Order
Flow UI's book-state metrics. Deterministic synthetic book (best-first levels, a bid wall
at the touch). Asserts NATIVE/DERIVED values, ONE FAUCET (imbalance == the depth-total
ratio, i.e. the engine authority and the depth totals agree), explicit classification of
every output, fail-closed on no book, and that temporal PROXY metrics are NOT produced.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.options.order_flow.live_payload import options_live_payload
from app.options.order_flow.state import OrderFlowState, streamed_record
from calc import order_flow as ofe
from calc.order_flow import OrderFlowEngine
from option_contract import NO_TOP, StreamedTop
from push import book as push_book
from stream_spine import MessageBus, held_key
from tests.feed_live_helper import (
    RTH_INSTANT,
    apply_record,
    daemon_status,
    mark_feed_live,
    on_the_bus,
)

EQ, OPT = "LEVELONE_EQUITIES", "LEVELONE_OPTIONS"

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_options_stream_history_samples.json"


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


def _is_book(c) -> bool:
    return isinstance(c, ofe.Book) or "BIDS" in c or "ASKS" in c


def _read(data: dict) -> ofe.FlowInput:
    """Return the engine's input for `data`'s Schwab messages, as the live state holds them.

    Its newest book, read by State's one reader (read_book, a NASDAQ_BOOK; a book the state
    already read stays), its prints in the order given, and `data`'s other fields as given.
    """
    items = data["content"]
    books = [
        b
        for b in (
            c if isinstance(c, ofe.Book) else ofls.read_book(c, "NASDAQ_BOOK")
            for c in items
            if _is_book(c)
        )
        if b is not None
    ]
    return ofe.FlowInput(
        book=books[-1] if books else None,
        prints=[c for c in items if not _is_book(c)],
        **{k: v for k, v in data.items() if k != "content"},
    )


def _micro(data: dict, **kw) -> dict:
    """engine.compute_book_microstructure of `data` as the live state holds it (_read)."""
    return ofe.compute_book_microstructure(_read(data), **kw)


def _l1_top() -> StreamedTop:
    return StreamedTop(bid=712.47, ask=712.49, bid_size=300, ask_size=500)


def _data() -> dict:
    return {"content": [_book_snapshot()], "top": _l1_top(), "exchange_quote_ts": 1787233769.0}


def test_top_of_book_is_native():
    m = _micro(_data(), now_ts=1787233772.0)
    assert m["status"] == "ok"
    tob = m["top_of_book"]
    assert tob == {
        "bid": 712.47,
        "ask": 712.49,
        "bid_size": 300,
        "ask_size": 500,
        "bid_size_text": "300",
        "ask_size_text": "500",
        "bid_text": "712.47",
        "ask_text": "712.49",
    }
    for k in ("top_of_book.bid", "top_of_book.ask", "top_of_book.bid_size", "top_of_book.ask_size"):
        assert m["classification"][k] == "NATIVE"


def test_derived_scalars():
    m = _micro(_data(), now_ts=1787233772.0)
    # the mark is Schwab's MARK as the top holds it (none here: "-"), never computed from bid/ask
    assert "mid" not in m and m["mark"] is None and m["classification"]["mark"] == "NATIVE"
    # microprice weights each price by the OPPOSITE size: (712.47*500 + 712.49*300)/800.
    assert abs(m["microprice"] - 712.4775) < 1e-6
    assert m["spread_pts"] == 712.49 - 712.47  # exact, unrounded
    assert m["classification"]["microprice"] == "DERIVED"


def test_a_mark_of_zero_schwab_sent_is_zero():
    """A reported 0 is 0 (AGENTS.md rule 2): the MARK is served as 0, never "-"."""
    m = _micro({**_data(), "top": replace(_l1_top(), mark=0.0)}, now_ts=1787233772.0)
    assert m["mark"] == 0.0


def test_depth_totals_values():
    m = _micro(_data(), now_ts=1787233772.0)
    d1, d3, d5 = m["depth"]["1"], m["depth"]["3"], m["depth"]["5"]
    assert (d1["bid_total"], d1["ask_total"]) == (1000.0, 960.0)
    assert (d3["bid_total"], d3["ask_total"]) == (1080.0, 1990.0)
    assert (d5["bid_total"], d5["ask_total"]) == (1360.0, 2430.0)


def test_the_depth_pressure_curve_is_cumulative_best_first():
    m = _micro(_data(), now_ts=1787233772.0)
    bid_curve = m["depth_pressure"]["bid"]
    assert [round(x["cum"], 1) for x in bid_curve] == [1000.0, 1040.0, 1080.0, 1160.0, 1360.0]


def test_microprice_is_computed_from_every_quote_schwab_sent():
    """A crossed book's quotes are Schwab's and compute (the book says it is crossed).

    "we use what schwab gives us and we display it". Absent only with a leg Schwab did not send,
    or no size to weight.
    """
    ok = ofe._microprice(712.47, 712.49, 300, 500)
    assert abs(ok - 712.4775) < 1e-9
    assert (
        ofe._microprice(712.50, 712.49, 300, 500) == (712.50 * 500 + 712.49 * 300) / 800
    )  # crossed
    assert ofe._microprice(712.47, 712.49, 0, 0) is None  # zero total size: nothing to weight
    assert ofe._microprice(None, 712.49, 300, 500) is None  # missing leg
    # locked book (bid == ask, spread 0) is a valid input, returns the common price.
    assert ofe._microprice(712.49, 712.49, 300, 500) == 712.49


def test_ages_from_native_timestamps():
    m = _micro(_data(), now_ts=1787233772.0)
    assert m["ages"]["book_age_sec"] == 1787233772.0 - 1787233769563.0 / 1000.0  # in full
    assert m["ages"]["quote_age_sec"] == 3.0
    assert m["provenance"]["book_time_ms"] == 1787233769563.0
    assert m["provenance"]["exchange_quote_ts"] == 1787233769.0


def test_fail_closed_no_book():
    m = _micro({"content": []}, now_ts=1787233772.0)
    assert m["status"] == "no_book"
    assert m["depth"]["5"]["imbalance"] is None
    assert m["provenance"]["book_source"] == "unavailable"


def test_every_emitted_metric_is_classified():
    """The metric set is taken from the actual payload.

    So a newly emitted metric with no classification entry fails. A family match requires a
    dotted boundary (`key + "."`), so a bare prefix collision (an unrelated `mark_price` entry)
    cannot stand in for the real `mark` entry.
    """
    m = _micro(_data(), now_ts=1787233772.0)
    cls = m["classification"]
    # Self-describing meta blocks, not emitted metrics: the classification map
    # itself, the explicit deferral list and the status flag.
    # A metric's text (`<metric>_text`, as the screen shows it) is that metric: it is classified
    # by the metric's entry, which must exist.
    meta = {"classification", "deferred", "status"}
    metrics = {key.removesuffix("_text") for key in m}
    assert {f"{k}_text" for k in ("mark", "microprice", "spread_pts")} <= set(m)
    unclassified = [
        key
        for key in metrics
        if key not in meta and key not in cls and not any(c.startswith(f"{key}.") for c in cls)
    ]
    assert unclassified == [], (
        f"emitted metric(s) with no classification entry: {unclassified}. Every metric "
        f"this producer emits must declare NATIVE/DERIVED/PROXY provenance."
    )


def test_server_received_ts_is_classified_derived():
    """server_received_ts is the server wall clock stamped at serialization.

    It is not an exchange-native field — it must be labeled DERIVED, distinct from the NATIVE
    exchange_quote_ts.
    """
    m = _micro(_data(), now_ts=1787233772.0)
    assert m["classification"]["provenance.server_received_ts"] == "DERIVED"
    assert m["classification"]["provenance.exchange_quote_ts"] == "NATIVE"
    assert m["provenance"]["server_received_ts"] == 1787233772.0


# ─── property tests: canonicalization, invalid input, crossed/one-sided, carry ───


def _unsorted_data() -> dict:
    # Same book as _book_snapshot's top-3 per side but levels supplied OUT OF ORDER.
    return {
        "content": [
            {
                "BIDS": [
                    {"BID_PRICE": 712.43, "TOTAL_VOLUME": 200},
                    {"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
                    {"BID_PRICE": 712.45, "TOTAL_VOLUME": 40},
                ],
                "ASKS": [
                    {"ASK_PRICE": 712.53, "TOTAL_VOLUME": 320},
                    {"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960},
                    {"ASK_PRICE": 712.51, "TOTAL_VOLUME": 710},
                ],
                "BOOK_TIME": 1,
            }
        ],
        "top": StreamedTop(bid=712.47, ask=712.49, bid_size=300, ask_size=500),
    }


def test_unsorted_book_is_canonicalized_before_topn():
    """Levels arriving out of order must be sorted (bids desc, asks asc) BEFORE any Top-N.

    Sorted before any Top-N semantics, so the touch and cumulative depth curve are correct
    regardless of input order.
    """
    m = _micro(_unsorted_data(), now_ts=2.0)
    assert m["top_of_book"]["bid"] == 712.47  # highest bid, not the 712.43 that arrived first
    assert m["top_of_book"]["ask"] == 712.49  # lowest ask, not the 712.53 that arrived first
    # depth-pressure is cumulative BEST-FIRST after sorting: 712.47(1000),712.45(40),712.43(200)
    assert [round(x["cum"], 1) for x in m["depth_pressure"]["bid"]] == [1000.0, 1040.0, 1240.0]
    # ask cumulative best-first: 712.49(960),712.51(710),712.53(320)
    assert [round(x["cum"], 1) for x in m["depth_pressure"]["ask"]] == [960.0, 1670.0, 1990.0]
    # the ladder's served scale: the largest size of the levels drawn, either side
    assert m["depth_pressure"]["max_volume"] == 1000.0


def test_invalid_sizes_are_rejected():
    """Negative or non-finite displayed sizes are not real quantities.

    They must be dropped from level totals, and an invalid L1 size must not be published as a
    real top-of-book size. The L1 size is read from the contract's record on the bus
    (state.streamed_record).
    """
    sent = {"key": "BADSIZE", "BID_PRICE": 712.47, "ASK_PRICE": 712.49}
    record = on_the_bus(MessageBus(), OPT, {**sent, "BID_SIZE": -5, "ASK_SIZE": 500}, 1.0)
    bad = {
        "content": [
            {
                "BIDS": [
                    {"BID_PRICE": 712.47, "TOTAL_VOLUME": 1000},
                    {"BID_PRICE": 712.46, "TOTAL_VOLUME": -40},  # negative -> dropped
                    {"BID_PRICE": 712.45, "TOTAL_VOLUME": float("inf")},  # non-finite -> dropped
                    {"BID_PRICE": 712.44, "TOTAL_VOLUME": 80},
                ],
                "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}],
                "BOOK_TIME": 1,
            }
        ],
        "top": streamed_record(record).top,
    }
    m = _micro(bad, now_ts=2.0)
    # only the two valid bid levels (1000 + 80) survive into the depth total
    assert m["depth"]["3"]["bid_total"] == 1080.0
    # a negative L1 bid size is withheld, not published as a real size
    assert m["top_of_book"]["bid_size"] is None
    assert m["top_of_book"]["ask_size"] == 500


def test_a_crossed_book_computes_microprice_and_says_it_is_crossed():
    """A crossed book (bid > ask): Schwab sent both quotes, so the microprice is computed.

    Computed from them and the payload flags crossed ("we use what schwab gives us and we
    display it").
    """
    crossed = {
        "content": [
            {
                "BIDS": [{"BID_PRICE": 712.60, "TOTAL_VOLUME": 1000}],
                "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}],
                "BOOK_TIME": 1,
            }
        ],
        "top": StreamedTop(bid=712.60, ask=712.49, bid_size=300, ask_size=500),
    }
    m = _micro(crossed, now_ts=2.0)
    assert m["crossed"] is True
    assert m["mark"] is None, "Schwab's MARK as sent; none in this top"
    assert m["microprice"] == (712.60 * 500 + 712.49 * 300) / 800
    assert m["classification"]["microprice"] == "DERIVED"


def test_one_sided_book_fails_closed():
    """With one side of the book empty, depth imbalance cannot be computed and must be None.

    Fail closed, rather than fabricated from the single populated side.
    """
    one = {
        "content": [
            {"BIDS": [], "ASKS": [{"ASK_PRICE": 712.49, "TOTAL_VOLUME": 960}], "BOOK_TIME": 1}
        ],
        "top": StreamedTop(ask=712.49, ask_size=500),
    }
    m = _micro(one, now_ts=2.0)
    for n in ("1", "3", "5"):
        assert m["depth"][n]["imbalance"] is None


def test_a_one_sided_book_schwab_sent_is_the_latest_book_never_the_older_two_sided_one():
    """A book message with asks and no bids is the latest book.

    As Schwab sends a side with no displayed orders. Its asks are served, and the previous
    two-sided book does not stand as current ("we use what schwab gives us and we display it").
    """
    st = OrderFlowState()
    snap = _book_snapshot()
    st.push_book("ONESIDE", snap, "NASDAQ_BOOK")
    st.push_book(
        "ONESIDE",
        {"ASKS": [{"ASK_PRICE": 713.10, "TOTAL_VOLUME": 77}], "BOOK_TIME": snap["BOOK_TIME"] + 1},
        "NASDAQ_BOOK",
    )
    m = _micro({"content": [st.newest_book("ONESIDE", "NASDAQ_BOOK")]}, now_ts=2.0)
    assert m["status"] == "ok"
    assert m["depth"]["1"]["ask_total"] == 77.0 and m["depth"]["1"]["bid_total"] is None
    assert m["crossed"] is None  # no bid: whether the book is crossed is unknown, not "no"


def test_route_serializes_carried_state_without_recomputing():
    """The book panel and the engine call the SAME producer, a pure one.

    Two serializations of the same unchanged book give the same values; only the wall-clock ages
    and stamps move with `now`.
    """
    data = _data()
    first = _micro(data, now_ts=100.0)
    second = _micro(data, now_ts=200.0)
    assert second["depth"] == first["depth"]
    assert second["top_of_book"] == first["top_of_book"]
    assert second["ages"]["book_age_sec"] != first["ages"]["book_age_sec"]
    assert second["provenance"]["server_received_ts"] == 200.0


def test_changed_ladder_under_same_book_time_is_not_served_stale():
    """CACHE INVALIDATION: the carry cache must key on canonical book CONTENT.

    Not BOOK_TIME alone. With the SAME ticker and the SAME BOOK_TIME but a MUTATED ladder, depth
    totals and imbalance must reflect the new book — never the prior cached state.
    """
    BT = 424242  # identical BOOK_TIME across both snapshots

    def _book(bids, asks) -> dict:
        return {
            "content": [
                {
                    "BIDS": [{"BID_PRICE": p, "TOTAL_VOLUME": v} for p, v in bids],
                    "ASKS": [{"ASK_PRICE": p, "TOTAL_VOLUME": v} for p, v in asks],
                    "BOOK_TIME": BT,
                }
            ],
            "top": StreamedTop(bid=bids[0][0], ask=asks[0][0], bid_size=100, ask_size=100),
        }

    # v1: heavy bid book, its largest size at the bid touch.
    v1 = _book(
        bids=[(712.47, 1000), (712.46, 40), (712.45, 40), (712.44, 80), (712.43, 200)],
        asks=[(712.49, 60), (712.51, 40), (712.53, 40), (712.75, 40), (713.00, 40)],
    )
    # v2: SAME BOOK_TIME, but the book has flipped — heavy ask book.
    v2 = _book(
        bids=[(712.47, 60), (712.46, 40), (712.45, 40), (712.44, 40), (712.43, 40)],
        asks=[(712.49, 1000), (712.51, 40), (712.53, 40), (712.75, 80), (713.00, 200)],
    )

    m1 = _micro(v1, now_ts=1.0)
    m2 = _micro(v2, now_ts=2.0)

    # Both snapshots genuinely carry the identical BOOK_TIME...
    assert m1["provenance"]["book_time_ms"] == m2["provenance"]["book_time_ms"] == float(BT)
    # ...yet the second read reflects the NEW ladder, not the cached first one.
    assert m1["depth"]["5"]["bid_total"] == 1360.0
    assert m2["depth"]["5"]["bid_total"] == 220.0  # not the stale 1360
    assert m1["depth"]["1"]["imbalance"] != m2["depth"]["1"]["imbalance"]
    assert m2["depth"]["1"]["imbalance"] < 0  # ask-heavy now

    # and an unchanged re-read of v2 gives v2's values again
    m2b = _micro(v2, now_ts=3.0)
    assert m2b["depth"] == m2["depth"]


def test_engine_and_route_read_the_same_canonical_state():
    """OrderFlowEngine.compute carries the SAME book_microstructure the route serializes.

    One faucet, not two producers.
    """
    data = _data()
    out = OrderFlowEngine().compute(_read(data), now=1787233772.0)
    route = _micro(data, now_ts=1787233772.0)
    assert out["book_microstructure"]["depth"] == route["depth"]


# ─────────────────────────────────────────────────────────────────────────────
# Top of book is carried, not resolved: the engine reads data["top"] (bid, ask, bid_size,
# ask_size, mark), supplied by the caller as Schwab last sent it -- the equity's price row, or
# an option contract's record on the bus (state.option_top). Per-field merge of Schwab's
# changed-fields-only ticks is the bus's job (the contract's record below; live_market_plane for
# equities).
# ─────────────────────────────────────────────────────────────────────────────


def test_top_prices_and_sizes_are_carried_exactly():
    data = _read({"content": [], "top": StreamedTop(bid=0.58, ask=0.59, bid_size=11, ask_size=23)})
    bid, ask = ofe._resolve_bid_ask_prices(data)
    assert (bid, ask) == (0.58, 0.59)
    assert ofe._extract_canonical_book(data)["mark"] is None
    assert ofe._compute_top_book_pressure(data) == (11 - 23) / (11 + 23)
    cb = ofe._extract_canonical_book(data)
    assert (cb["bid_size"], cb["ask_size"]) == (11, 23)


def test_zero_size_is_a_real_value_not_a_fallback_trigger():
    data = {
        "content": [_book_snapshot()],
        "top": StreamedTop(bid=0.10, ask=0.12, bid_size=0, ask_size=5),
    }
    assert ofe._compute_top_book_pressure(_read(data)) == (0 - 5) / (0 + 5), (
        "a real BID_SIZE=0 is not missing"
    )
    assert ofe._extract_canonical_book(_read(data))["bid_size"] == 0
    assert _micro(data, now_ts=1787233772.0)["top_of_book"]["bid_size"] == 0


def test_no_top_resolves_to_none():
    data = _read({"content": [{"LAST_PRICE": 0.55, "LAST_SIZE": 3}], "top": NO_TOP})  # print only
    assert ofe._resolve_bid_ask_prices(data) == (None, None)
    assert ofe._compute_top_book_pressure(data) is None


def test_a_contracts_record_merges_real_partial_ticks_per_field():
    """Real LEVELONE_OPTIONS ticks (tests/fixtures, TSLA 260831C00367500), on the bus.

    Schwab sends changed fields only -- the 4th tick carries BID_SIZE/ASK_SIZE and no price. The
    prices from earlier ticks stand, the sizes update. Stand-ins (named): the BID_SIZE 0 and
    ASK_PRICE -999 ticks are edits of the real tick, to pin a reported 0 kept and a not-a-number
    clearing.
    """
    samples = json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]
    tsla = next(c for c in samples if c["symbol"] == "TSLA  260831C00367500")
    qqq = next(c for c in samples if c["symbol"] == "QQQ   260904C00712500")
    tsla_l1 = [e["content"] for e in tsla["events"] if e["kind"] == "l1"]
    bus = MessageBus()

    def top(sym: str, tick: dict | None = None) -> StreamedTop:
        if tick is not None:
            on_the_bus(bus, OPT, {**tick, "key": sym}, 1.0)
        return streamed_record(bus.current.get(held_key(OPT, sym))).top

    for tick in tsla_l1[:4]:
        top(tsla["symbol"], tick)
    assert "BID_PRICE" not in tsla_l1[3] and "ASK_PRICE" not in tsla_l1[3]
    assert top(tsla["symbol"]) == StreamedTop(
        bid=0.56,
        ask=0.59,
        bid_size=83,
        ask_size=57,
        mark=0.575,
        quote_time_ms=tsla_l1[3]["QUOTE_TIME_MILLIS"],
        money_intrinsic=tsla_l1[3]["MONEY_INTRINSIC_VALUE"],
    )
    assert tsla_l1[3]["MONEY_INTRINSIC_VALUE"] == -1.65

    assert top(tsla["symbol"], dict(tsla_l1[3], BID_SIZE=0)).bid_size == 0

    cleared = top(tsla["symbol"], {"ASK_PRICE": -999})
    assert cleared.ask is None and cleared.bid == 0.56

    qqq_first = next(e["content"] for e in qqq["events"] if e["kind"] == "l1")
    assert top(qqq["symbol"], qqq_first) == StreamedTop(
        bid_size=272, ask_size=29, quote_time_ms=qqq_first["QUOTE_TIME_MILLIS"]
    )
    assert top(tsla["symbol"]).bid == 0.56


def test_an_equity_l1_quote_is_not_stored_a_second_time_in_order_flow_state():
    """An equity's Level-1 quote lives in live_market_plane only.

    push_level_one writes no
    top-of-book item beside the book and tape. Stand-in (named): a hand-built
    LEVELONE_EQUITIES tick.
    """
    ofls.clear_symbol("O01EQ")
    bus = MessageBus()
    ofls.bind_bus(bus.current)
    try:
        sent = {"key": "O01EQ", "BID_PRICE": 100.0, "ASK_PRICE": 100.02, "BID_SIZE": 3}
        record = on_the_bus(bus, EQ, {**sent, "ASK_SIZE": 4, "MARK": 100.01}, 1_000.0)
        apply_record(ofls._LIVE_STATE, EQ, record)
        assert not any("BID_PRICE" in row or "ASK_PRICE" in row for row in ofls.prints("O01EQ"))
        assert ofls.newest_book("O01EQ", "OPTIONS_BOOK") is None
        assert ofls.option_top("O01EQ") is NO_TOP
    finally:
        ofls.clear_symbol("O01EQ")


def test_size_g_the_live_push_seam_threads_each_messages_receive_time_into_push_level_one():
    """Each streamed field carries the receive time of the MESSAGE that brought it.

    For both equity (LEVELONE_EQUITIES) and option (LEVELONE_OPTIONS) messages, put on the bus by
    the daemon's stream handler and taken by the console's intake (_ingest_pushed) -- never the
    time the console processed it. Real data: GOOGL's TOTAL_VOLUME and SPY 2026-10-30 910 call's
    GAMMA as Schwab sent them 2026-10-05 14:00 CT
    (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json).
    """
    mix = json.loads(
        (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
            encoding="utf-8"
        )
    )["messages"]
    eq = next(m for m in mix if m["service"] == "LEVELONE_EQUITIES" and "TOTAL_VOLUME" in m["item"])
    opt = next(m for m in mix if m["service"] == "LEVELONE_OPTIONS" and "GAMMA" in m["item"])
    eq_sym, opt_sym = eq["item"]["key"], opt["item"]["key"]
    ofls.clear_symbol(eq_sym)
    ofls.clear_symbol(opt_sym)
    bus = MessageBus()
    ofls.bind_bus(bus.current)
    try:
        ofs._ingest_pushed(*on_the_bus(bus, EQ, eq["item"], eq["ts_recv"]))
        ofs._ingest_pushed(*on_the_bus(bus, OPT, opt["item"], opt["ts_recv"]))
        live = ofls._LIVE_STATE
        assert live.streamed(EQ, eq_sym).greeks.total_volume.ts_recv == eq["ts_recv"]
        assert live.streamed(OPT, opt_sym).greeks.gamma.ts_recv == opt["ts_recv"]
    finally:
        ofls.clear_symbol(eq_sym)
        ofls.clear_symbol(opt_sym)


def test_book_top_never_stands_in_for_a_missing_l1_price():
    """No fallbacks: the book's top level is a DIFFERENT feed (one venue's depth).

    It does not stand in when L1 carries no price -- bid/ask stay absent.
    # book shape fixture, not a SPY-only product claim.
    """
    items = [
        {
            "BIDS": [{"BID_PRICE": 0.02, "TOTAL_VOLUME": 10}],
            "ASKS": [{"ASK_PRICE": 0.03, "TOTAL_VOLUME": 12}],
            "BOOK_TIME": 1,
        }
    ]
    bid, ask = ofe._resolve_bid_ask_prices(
        _read({"content": items, "top": StreamedTop(ask_size=12)})
    )
    assert (bid, ask) == (None, None)


def test_an_option_contracts_top_is_what_schwab_sent_on_a_live_feed():
    """The option top of book is the newest value Schwab sent, merged per field.

    While the daemon holds the contract (a feed down: docs/DATA_FLOW.md §2 D5,
    tests/test_data_path_rules_v1.py). Real TSLA 260831C00367500 ticks (tests/fixtures), judged in
    regular hours, the option market open (RTH_INSTANT).
    """
    c = json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"][0]
    sym = c["symbol"]
    bus = MessageBus()
    ofls.bind_bus(bus.current)
    for ev in c["events"][:4]:
        if ev["kind"] == "l1":
            on_the_bus(bus, OPT, {**ev["content"], "key": sym}, ev["ts_recv"])
    try:
        lmp.record_feed_heartbeat(
            daemon_status(RTH_INSTANT, schwab_socket_open=True, held={"LEVELONE_OPTIONS": [sym]})
        )
        payload = options_live_payload(sym, RTH_INSTANT)  # a TSLA option
        assert payload["flow"]["top_book_pressure"] is not None and payload["top_outage"] is None
        # the option's price between bid and ask is Schwab's MARK as sent (LEVELONE_OPTIONS
        # field 37, the newest one sent); nothing computes a mid beside it
        sent = [ev["content"]["MARK"] for ev in c["events"][:4] if "MARK" in ev["content"]]
        assert sent and payload["mark"] == sent[-1]
        assert payload["classification"]["mark"] == "NATIVE" and "mid" not in payload
    finally:
        lmp.record_feed_down()
        ofls.clear_all_live_state()


def test_the_equity_book_reads_the_daemons_price_row_for_its_top_of_book():
    """The book panel takes the equity top of book from the daemon's price row.

    The price row is the header's: the newest quote Schwab sent, its feed live (a feed down:
    docs/DATA_FLOW.md §2 D5, tests/test_data_path_rules_v1.py). Stand-in quote (named): bid
    10.00 x 3, ask 10.02 x 5. Served in regular hours (RTH_INSTANT).
    """
    now = RTH_INSTANT
    mark_feed_live("ZZTB", now=now)
    try:
        lmp.record_from_level_one_equity(
            "ZZTB",
            {
                "LAST_PRICE": 10.01,
                "BID_PRICE": 10.0,
                "ASK_PRICE": 10.02,
                "BID_SIZE": 3,
                "ASK_SIZE": 5,
                "MARK": 10.01,
            },
            received_ts=now,
        )
        body = push_book.order_flow_microstructure("ZZTB", "NYSE_BOOK", now)
        top = body["top_of_book"]
        assert (top["bid_size"], top["ask_size"]) == (3, 5) and body["top_outage"] is None
        # the equity's MARK is served as the price row holds it; no mid is computed beside it
        assert body["mark"] == 10.01 and "mid" not in body
    finally:
        lmp._by_ticker.pop("ZZTB", None)
        lmp._fields_by_ticker.pop("ZZTB", None)
        lmp.record_feed_down()
