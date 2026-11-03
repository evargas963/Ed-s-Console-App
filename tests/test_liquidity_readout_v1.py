"""The Desk Liquidity card's order-imbalance readout (engine.book_readout, engine.readout_card,
server.liquidity_readout), on Schwab's real books.

Books: SPY's NYSE_BOOK and NASDAQ_BOOK as sent on 2026-09-25 at 10:30 ET, one of each
(tests/fixtures/real_spy_nyse_nasdaq_books.json), and every SPY NYSE_BOOK and NASDAQ_BOOK message
Schwab sent on 2026-11-02 from 10:00:00 to 10:02:30 ET, in receive order
(tests/fixtures/real_spy_books_2026_11_02.json, read from production's stream_capture.db), and the
two books held when the composite was first locked and first crossed after 10:00 ET that day
(tests/fixtures/real_spy_crossed_locked_books_2026_11_02.json, from the same database). The
price row is the daemon's own, built from SPY's real LEVELONE_EQUITIES messages of 2026-10-23
(tests/fixtures/real_spy_level_one_2026_10_23.json): a different day's quote, named here; the card
reads no field of it but the book's live verdict. STAND-IN (named): the daemon's status, its Schwab
socket open and holding SPY on both books; no status message is captured.

The Playwright fixtures the card's browser tests draw are this route's answers
(write_readout_e2e_fixtures), never hand written:
  python -c "import tests.test_liquidity_readout_v1 as t; t.write_readout_e2e_fixtures()"
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import server
from app.options.order_flow import engine as e
from app.options.order_flow import history
from app.options.order_flow import streaming as ofs
from stream_spine import book_msg
from tests.conftest import MARKETS_ANSWERS
from tests.feed_live_helper import publish_daemon_rows
from tests.test_order_flow_book_payload_v1 import _same
from time_et import auction, record_markets

_FX = Path(__file__).resolve().parent / "fixtures"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures"
_PAIR = json.loads((_FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]
_ROWS = json.loads((_FX / "real_spy_books_2026_11_02.json").read_text(encoding="utf-8"))["rows"]
#: the books held when the composite was first locked and first crossed after 10:00 ET, 2026-11-02
_TOUCHING = json.loads(
    (_FX / "real_spy_crossed_locked_books_2026_11_02.json").read_text(encoding="utf-8")
)
_CROSSED = _TOUCHING["CROSSED"]
#: 2026-11-02 10:02:30 ET, the end of the captured window: regular hours in Schwab's answer
_END = datetime.fromisoformat("2026-11-02T10:02:30-05:00").timestamp()
#: 2026-11-02 15:55 ET: inside the closing auction of a normal day
_CLOSE_AUCTION = datetime.fromisoformat("2026-11-02T15:55:00-05:00").timestamp()
_HELD = {"LEVELONE_EQUITIES": ["SPY"], "NYSE_BOOK": ["SPY"], "NASDAQ_BOOK": ["SPY"]}
#: every venue with no book
_NO_BOOK = e.book_readout(dict.fromkeys(e.BOOK_VENUES))


def _pair_readout() -> dict:
    return e.book_readout({v: b["content"] for v, b in _PAIR.items()})


def _replay() -> tuple[dict, list]:
    """Every captured 2026-11-02 book through the readout, as the console's intake records it:
    the readout of the newest book of each venue at each receipt."""
    newest: dict = dict.fromkeys(e.BOOK_VENUES)
    points = []
    for ts, svc, content in _ROWS:
        newest[svc] = content
        points.append((ts, e.book_readout(newest)))
    return points[-1][1], points


def build_readout_payload(now: float = _END, feed_down: bool = False, rows=None) -> dict:
    """The route's payload for SPY at `now` after Schwab's books `rows` (every captured book when
    None), each through the console's own intake: the daemon holding both books, or its
    connection ended (`feed_down`)."""
    quotes = json.loads((_FX / "real_spy_level_one_2026_10_23.json").read_text(encoding="utf-8"))[
        "messages"
    ]
    ofls.clear_all_live_state()
    history.LEAN.forget("SPY")
    try:
        lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "held": _HELD})
        for m in sorted(quotes, key=lambda m: m["ts_recv"]):
            lmp.record_from_level_one_equity("SPY", m["item"], received_ts=m["ts_recv"])
        publish_daemon_rows("SPY", now=now)
        for ts, svc, content in _ROWS if rows is None else rows:
            ofs._ingest_pushed(
                "book.SPY",
                book_msg(symbol="SPY", service=svc, content=content, src="schwab_book", ts_recv=ts),
            )
        if feed_down:
            lmp.record_feed_down()
        return json.loads(json.dumps(server.order_flow_microstructure("SPY", "NYSE_BOOK", now)))
    finally:
        ofs._price_rows.pop("SPY", None)
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop("SPY", None)
        lmp.record_feed_down()
        ofls.clear_all_live_state()
        history.LEAN.forget("SPY")


# ── one book: the weighted headline and the flat views ───────────────────────────────────────


def test_the_level_weights_fall_from_the_touch_and_sum_to_one():
    w = e.OF_LEVEL_WEIGHTS
    assert math.isclose(sum(w), 1.0)
    assert [round(x, 2) for x in w] == [0.43, 0.26, 0.16, 0.10, 0.06]
    assert all(math.isclose(w[k + 1] / w[k], math.exp(-0.5)) for k in range(4))


def test_the_weighted_headline_and_the_flat_views_of_schwabs_nyse_book():
    """NYSE_BOOK's best five bids 160, 120, 120, 360, 40 and asks 200, 320, 1560, 40, 40 shares:
    the headline weighs each level, the flat views sum the shares, and the weighted view's bars
    are the flat top five."""
    nyse = _pair_readout()["NYSE_BOOK"]["views"]
    bids, asks = [160, 120, 120, 360, 40], [200, 320, 1560, 40, 40]
    wb = sum(w * b for w, b in zip(e.OF_LEVEL_WEIGHTS, bids, strict=True))
    wa = sum(w * a for w, a in zip(e.OF_LEVEL_WEIGHTS, asks, strict=True))
    assert nyse["weighted"]["pct"] == pytest.approx((wb - wa) / (wb + wa) * 100)
    assert (nyse["weighted"]["bid_total"], nyse["weighted"]["ask_total"]) == (800, 2160)
    assert nyse["weighted"]["flat_pct"] == pytest.approx((800 - 2160) / 2960 * 100)
    for view, (b, a) in {"1": (160, 200), "3": (400, 2080), "5": (800, 2160)}.items():
        v = nyse[view]
        assert (v["bid_total"], v["ask_total"]) == (b, a)
        assert v["pct"] == v["flat_pct"] == pytest.approx((b - a) / (b + a) * 100)
        assert (v["difference"], v["total_depth"]) == (abs(b - a), b + a)


def test_the_weighted_headline_is_not_the_flat_top_five():
    """Schwab's NASDAQ_BOOK: the touch leans to the bids (+17.6%) while the flat top five leans
    to the offers (-5.5%); the weighted headline follows the touch, and says the two disagree."""
    nq = _pair_readout()["NASDAQ_BOOK"]["views"]
    assert nq["1"]["pct"] > 0 > nq["5"]["pct"]
    assert nq["weighted"]["pct"] > 0 > nq["weighted"]["flat_pct"]
    card = e.readout_card(
        _pair_readout(),
        [(1.0, _pair_readout())],
        {v: 2.0 for v in (*e.BOOK_VENUES, e.COMPOSITE)},
    )
    assert card["venues"]["NASDAQ_BOOK"]["views"]["weighted"]["divergence"] == (
        "Touch and deeper book disagree"
    )
    assert card["venues"]["NASDAQ_BOOK"]["views"]["5"]["divergence"] is None
    assert card["venues"]["NYSE_BOOK"]["views"]["weighted"]["divergence"] is None


# ── the composite: NSDQ once, from NYSE_BOOK ─────────────────────────────────────────────────


def test_the_composite_counts_nasdaqs_quote_once_from_nyse_book():
    """NSDQ's quote is in both books, at different prices: NYSE_BOOK (BOOK_TIME ...097) shows it
    at 767.39 x 80 bid and 767.41 x 120 ask, NASDAQ_BOOK (...528, newer) at 767.41 x 100 bid and
    767.42 x 70 ask. The composite takes NYSE_BOOK's, though NASDAQ_BOOK's is newer, and every
    market maker of NASDAQ_BOOK; summing the books' level totals would count NSDQ twice."""
    comp = _pair_readout()["COMPOSITE"]
    v5 = comp["views"]["5"]
    # bids NYSE_BOOK's 767.39 160, 767.38 120, 767.37 120, 767.36 360, 767.35 40 (NASDAQ_BOOK's
    # market makers bid lower); asks 767.41 200, 767.42 320, 767.43 1560, 767.44 40, 767.60 40
    assert (v5["bid_total"], v5["ask_total"]) == (800, 2160)
    # the newer book's NSDQ (newer-wins) would make them 780 and 2110: it is the other value
    assert v5["nsdq_other_pct"] == pytest.approx((780 - 2110) / (780 + 2110) * 100)
    asks, _partial = e._composite_side(
        {v: b["content"] for v, b in _PAIR.items()}, "ASKS", "NYSE_BOOK"
    )
    # 767.42: NYSE_BOOK's IEXG, NYSE, EDGX (320); NASDAQ_BOOK's NSDQ 70 left out, not averaged
    assert dict(asks)[767.42] == 320
    assert (
        sum(
            lv["TOTAL_VOLUME"]
            for b in _PAIR.values()
            for lv in b["content"]["ASKS"]
            if lv["ASK_PRICE"] == 767.42
        )
        == 320 + 70
    )
    # NASDAQ_BOOK's market makers are in it, each at its own price
    assert dict(asks)[769.09] == 40 and dict(asks)[790.46] == 40
    # the merged ladder: distinct prices, best first
    prices = [p for p, _s in asks]
    assert prices == sorted(set(prices))
    assert comp["dedup_partial"] is False and comp["touch_state"] is None
    assert comp["book_time_ms"] == _PAIR["NYSE_BOOK"]["content"]["BOOK_TIME"]  # the older book


def test_the_composite_takes_nsdq_from_nyse_book_whatever_its_quote_time():
    """Schwab's books at 10:00:08 ET on 2026-11-02: NASDAQ_BOOK's NSDQ bid (row 15), 760.58 x 20,
    was quoted after NYSE_BOOK's NSDQ bid (row 16), 760.56 x 80. The composite still counts
    NYSE_BOOK's and leaves NASDAQ_BOOK's out; with NSDQ taken from NASDAQ_BOOK instead, the
    whole row moves: 20 at 760.58, nothing of NSDQ at 760.56."""
    (_t16, svc16, nyse), (_t15, svc15, nq) = _ROWS[16], _ROWS[15]
    assert (svc16, svc15) == ("NYSE_BOOK", "NASDAQ_BOOK")
    books = {"NYSE_BOOK": nyse, "NASDAQ_BOOK": nq}
    levels, partial = e._composite_side(books, "BIDS", "NYSE_BOOK")
    other, _ = e._composite_side(books, "BIDS", "NASDAQ_BOOK")
    nyse_at = {lv["BID_PRICE"]: lv["TOTAL_VOLUME"] for lv in nyse["BIDS"]}
    assert 760.58 not in dict(levels) and dict(levels)[760.56] == nyse_at[760.56] == 200
    assert dict(other)[760.58] == 20 and dict(other)[760.56] == 200 - 80
    assert partial is False


def test_a_level_without_per_exchange_rows_is_taken_whole_and_the_dedup_marked_partial():
    """A level as Schwab sent it, its own rows removed: its TOTAL_VOLUME is counted once, and the
    composite says its dedup is partial."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    del nyse["BIDS"][1]["BIDS"]  # 767.38: BATX 80 + NYSE 40, TOTAL_VOLUME 120
    comp = e.book_readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": _PAIR["NASDAQ_BOOK"]["content"]})
    assert comp["COMPOSITE"]["dedup_partial"] is True
    assert comp["COMPOSITE"]["views"]["5"]["bid_total"] == 800


def test_an_exchange_code_other_than_nsdq_in_both_books_leaves_the_composite_without_a_number():
    """Schwab has spelled exchanges in lower case in NASDAQ_BOOK (TSLA's arcx, edgx and batx on
    2026-09-25, tests/fixtures/real_tsla_book_rows.json) where NYSE_BOOK spells them ARCX, EDGX,
    BATX. INDUCED: that real book, and the same book a millisecond older with its codes in upper
    case, as NYSE_BOOK spells them (no captured pair of the two spellings is held: SPY's and IWM's
    books of 2026-11-02 share NSDQ only). Matched without regard to case, ARCX and the others are
    in both books: which copy counts is not decided, so the composite has words, not a number."""
    tsla = json.loads((_FX / "real_tsla_book_rows.json").read_text(encoding="utf-8"))["rows"]
    lower = {
        x["EXCHANGE"]
        for _ts, _svc, c in tsla
        for side in ("BIDS", "ASKS")
        for lv in c.get(side, [])
        for x in lv.get(side, [])
    }
    assert {"arcx", "edgx", "batx", "NSDQ"} <= lower
    newer = tsla[0][2]
    as_nyse = json.loads(json.dumps(newer))
    as_nyse["BOOK_TIME"] -= 1
    for side in ("BIDS", "ASKS"):
        for lv in as_nyse[side]:
            for x in lv[side]:
                x["EXCHANGE"] = x["EXCHANGE"].upper()
    comp = e.book_readout({"NYSE_BOOK": as_nyse, "NASDAQ_BOOK": newer})["COMPOSITE"]
    assert comp["status"] == "shared_code" and "views" not in comp
    assert {"ARCX", "EDGX", "BATX"} <= set(comp["shared"]) and "NSDQ" not in comp["shared"]
    assert server._no_number(comp)[1].endswith(
        "quote in both books: which copy counts is not decided, so the composite has no number"
    )


def test_the_composite_needs_both_books():
    """Schwab's NASDAQ_BOOK alone: the composite has words, not a number."""
    r = e.book_readout({"NYSE_BOOK": None, "NASDAQ_BOOK": _PAIR["NASDAQ_BOOK"]["content"]})
    assert r["COMPOSITE"] == {"status": "one_book", "book_time_ms": None, "books": ["NASDAQ_BOOK"]}
    assert server._no_number(r["COMPOSITE"])[1] == (
        "Composite needs both books — only NASDAQ_BOOK is captured for this symbol right now"
    )
    assert r["NASDAQ_BOOK"]["status"] == "ok"
    card = e.readout_card(r, [(1.0, r)], dict.fromkeys(r, 1.0))["venues"][e.COMPOSITE]
    assert all(v["pct"] is None and v["sentence"] is None for v in card["views"].values())


def test_nsdq_sizes_disagree_when_the_two_nsdq_composites_read_different_zones():
    """Schwab's pair: at the touch, NSDQ from NYSE_BOOK reads 160 bid / 200 ask (-11%, OFFER
    HEAVY), from NASDAQ_BOOK 100 / 80 (+11%, BID HEAVY): the flag shows, with both percentages.
    Over the top five both read OFFER HEAVY (-46%): no flag."""
    card = e.readout_card(
        _pair_readout(), [(1.0, _pair_readout())], dict.fromkeys(_pair_readout(), 1.0)
    )
    comp = card["venues"]["COMPOSITE"]["views"]
    assert comp["1"]["nsdq_disagree"] is True
    assert comp["1"]["nsdq_text"] == "NSDQ from NYSE_BOOK: -11% · NSDQ from NASDAQ_BOOK: +11%"
    assert comp["5"]["nsdq_disagree"] is False
    assert card["venues"]["NYSE_BOOK"]["views"]["1"]["nsdq_disagree"] is False


def test_crossed_withholds_the_sentence_and_locked_keeps_it():
    """Schwab's books when the composite was first locked (NYSE_BOOK's 760.25 bid and ask) and
    first crossed (NYSE_BOOK's 757.58 bid over its 757.57 ask) after 10:00 ET on 2026-11-02."""
    for state, flag in (("LOCKED", "BOOK LOCKED"), ("CROSSED", "BOOK CROSSED")):
        readout = e.book_readout({svc: content for _ts, svc, content in _TOUCHING[state]})
        card = e.readout_card(readout, [(1.0, readout)], dict.fromkeys(readout, 1.0))
        for venue in ("NYSE_BOOK", e.COMPOSITE):
            got = card["venues"][venue]
            assert (got["touch_state"], got["touch_flag"]) == (state, flag), venue
            for v in got["views"].values():
                assert v["pct"] is not None and v["bid_total"] is not None
                if state == "CROSSED":
                    assert (
                        v["sentence"]
                        == "Book crossed — bid and ask overlap, no balancing sentence."
                    )
                else:
                    assert v["sentence"] == e._sentence(v["zone"], v["bid_total"], v["ask_total"])
        assert card["venues"]["NASDAQ_BOOK"]["touch_flag"] is None


# ── spans and thin ladders ───────────────────────────────────────────────────────────────────


def test_the_spans_run_from_the_touch_to_the_depths_last_level():
    """Schwab's pair: NYSE_BOOK bids 767.39 to 767.35 and asks 767.41 to 767.60 over five levels;
    NASDAQ_BOOK bids 767.41 to 753.40; a one-level span is 0."""
    card = e.readout_card(
        _pair_readout(), [(1.0, _pair_readout())], dict.fromkeys(_pair_readout(), 1.0)
    )
    nyse, nq = card["venues"]["NYSE_BOOK"]["views"], card["venues"]["NASDAQ_BOOK"]["views"]
    assert (nyse["5"]["span_bid_text"], nyse["5"]["span_ask_text"]) == ("0.04", "0.19")
    assert nyse["weighted"]["span_bid_text"] == nyse["5"]["span_bid_text"]
    assert (nyse["3"]["span_bid_text"], nyse["1"]["span_bid_text"]) == ("0.02", "0.00")
    assert nq["5"]["span_bid_text"] == f"{767.41 - 753.40:.2f}"


def test_a_thin_side_is_read_over_the_levels_it_has_with_the_weights_renormalized():
    """Schwab's NYSE_BOOK at 10:00:34 ET on 2026-11-02 (row 66): seven bid levels and four ask
    levels. The asks' top five is its four, the weights renormalized over four, no level
    invented; the counts line says so."""
    _ts, svc, content = _ROWS[66]
    r = e.book_readout({v: content if v == svc else None for v in e.BOOK_VENUES})[svc]
    bids = [lv["TOTAL_VOLUME"] for lv in content["BIDS"]][:5]
    asks = [lv["TOTAL_VOLUME"] for lv in content["ASKS"]]
    assert (len(content["BIDS"]), len(asks)) == (7, 4)
    w = e.OF_LEVEL_WEIGHTS
    wb = sum(x * b for x, b in zip(w, bids, strict=True))
    wa = sum(x * a for x, a in zip(w[:4], asks, strict=True)) / sum(w[:4])
    assert r["views"]["weighted"]["pct"] == pytest.approx((wb - wa) / (wb + wa) * 100)
    assert r["views"]["5"]["ask_total"] == sum(asks)
    span = max(lv["ASK_PRICE"] for lv in content["ASKS"]) - min(
        lv["ASK_PRICE"] for lv in content["ASKS"]
    )
    assert r["views"]["5"]["span_ask"] == pytest.approx(span)
    card = e.readout_card({**_NO_BOOK, svc: r}, [(1.0, {**_NO_BOOK, svc: r})], {svc: 1.0})
    assert card["venues"][svc]["levels_text"] == "Levels available: bids 7 · asks 4"
    full = e.readout_card(
        _pair_readout(), [(1.0, _pair_readout())], dict.fromkeys(_pair_readout(), 1.0)
    )
    assert full["venues"]["NYSE_BOOK"]["levels_text"] is None


# ── words: zones, sentence ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pct", "zone"),
    [
        (0.0, "BALANCED"),
        (9.999, "BALANCED"),
        (-9.999, "BALANCED"),
        (10.0, "BID_HEAVY"),
        (-10.0, "OFFER_HEAVY"),
        (69.999, "BID_HEAVY"),
        (70.0, "VERY_BID"),
        (-70.0, "VERY_OFFER"),
        (None, None),
    ],
)
def test_the_zones_turn_at_10_and_70_percent(pct, zone):
    """INDUCED: percentages at each side of the zone lines, the definition's own boundaries."""
    assert e._zone(pct) == zone


def _book_at(row: int) -> dict:
    ts, svc, content = _ROWS[row]
    return e.book_readout({v: content if v == svc else None for v in e.BOOK_VENUES})[svc]


def test_the_sentence_four_cases_from_the_flat_shares():
    """Schwab's own books: NYSE_BOOK's touch at 10:00:08 ET on 2026-11-02 (80 bid, 80 ask),
    NYSE_BOOK's touch on 2026-09-25 (160 bid, 200 ask), NASDAQ_BOOK's touch then (100 bid, 70 ask)
    and the composite's top five then (780 bid, 2110 ask)."""
    even = _book_at(16)["views"]["1"]
    assert (even["bid_total"], even["ask_total"]) == (80, 80)
    pair = _pair_readout()
    nyse, nq = pair["NYSE_BOOK"]["views"]["1"], pair["NASDAQ_BOOK"]["views"]["1"]
    comp = pair["COMPOSITE"]["views"]["5"]
    assert e._sentence("BALANCED", 80, 80) == "Balanced — no shares needed to balance."
    assert (
        e._sentence(e._zone(nyse["pct"]), nyse["bid_total"], nyse["ask_total"])
        == "To balance, market makers buy 40 shares."
    )
    # INDUCED: those 160/200 shares read in the BALANCED zone (their own zone is OFFER_HEAVY)
    assert e._sentence("BALANCED", 160, 200) == "Nearly balanced — 40 shares would even the book."
    assert e._sentence(e._zone(comp["pct"]), 780, 2110) == (
        "To balance, market makers buy 1,330 shares."
    )
    assert e._sentence(e._zone(nq["pct"]), nq["bid_total"], nq["ask_total"]) == (
        "To balance, market makers sell 30 shares."
    )
    assert e._sentence(None, 780, 2110) is None
    assert e._sentence("BID_HEAVY", 780, None) is None


# ── over time: smoothing, the zone's hold, flips, the lean windows ───────────────────────────


def test_a_zone_changes_only_after_it_has_stood_three_seconds():
    """INDUCED: smoothed values on each side of the lines. One or two seconds out of the shown
    zone is not a change; three seconds out of it are, whichever zones they cross, the zone it
    then stands in dated from the second it entered it."""
    assert e._dwelled([5, 5, 15, 5, 5], 100)[-1] == ("BALANCED", 100)
    assert e._dwelled([5, 5, 15, 15, 5], 100)[-1] == ("BALANCED", 100)
    assert e._dwelled([5, 5, 15, 15, 15, 15], 100)[-1] == ("BID_HEAVY", 102)
    assert e._dwelled([5, None, 5], 100)[-1] == ("BALANCED", 102)
    # out of BID_HEAVY across two zones, the value crossing -10% each second
    assert e._dwelled([15, 15, 15, -12, -8, -12, -8], 0)[-1] == ("OFFER_HEAVY", 5)
    # out of BID_HEAVY through BALANCED: OFFER_HEAVY dated from when the value entered it
    assert e._dwelled([15, 15, 15, -8, -8, -12], 0)[-1] == ("OFFER_HEAVY", 5)
    # BALANCED left, the value then crossing the 70% line each second: out three seconds, it
    # stands in BID_HEAVY then (69), dated from the second it entered it
    assert e._dwelled([5, 69, 71, 69, 71], 0)[-1] == ("BID_HEAVY", 3)
    # a steady rise through two lines changes three seconds after it left
    assert e._dwelled([9, 11, 15, 72, 75], 0)[-1] == ("VERY_BID", 3)
    # each second's zone shown: a single print out of it changes nothing
    assert e._dwelled([5, 15, 5, 5], 0) == [("BALANCED", 0)] * 4


def test_on_schwabs_books_the_zone_changes_three_seconds_after_the_value_leaves_it():
    """Every venue and view of the captured books: the zone shown never stands while the value
    has been out of it three seconds or more, never changes sooner, and is dated from the second
    the value entered it."""
    _readout, points = _replay()
    last = int(points[-1][0])
    first = last - e.OF_LEAN_KEPT_SEC
    dwell = e.OF_ZONE_DWELL_SEC
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        for view in e.READOUT_VIEWS:
            sm = e._smoothed(e._standing(points, v, view, first, last))
            before = None
            for k in range(dwell, len(sm)):
                zone, since = e._dwelled(sm[: k + 1], first)[-1]
                out = [e._zone(s) != zone for s in sm[k - dwell + 1 : k + 1]]
                assert zone is None or not all(out), (v, view, k)
                if before is not None and zone is not None and zone != before:
                    # it changed: the value had stood out of the zone before for three seconds
                    assert all(e._zone(s) != before for s in sm[k - dwell + 1 : k + 1]), (v, k)
                    assert e._zone(sm[since - first]) == zone, (v, view, k)
                    assert since == first or e._zone(sm[since - first - 1]) != zone, (v, k)
                before = zone


def test_held_is_at_least_when_the_zone_stood_from_the_first_value_kept():
    """INDUCED: one of Schwab's books, recorded again 400 s later with nothing between (a quiet
    ticker): the first still stands at the window's start, so the zone has held at least the
    window, and says so."""
    history.LEAN.forget("SPY")
    try:
        for ts, svc, content in (_ROWS[0], [_ROWS[0][0] + 400, _ROWS[0][1], _ROWS[0][2]]):
            history.LEAN.record(
                "SPY", ts, e.book_readout({v: content if v == svc else None for v in e.BOOK_VENUES})
            )
        points = history.LEAN.points("SPY")
        assert len(points) == 2
        card = e.readout_card(points[-1][1], points, {_ROWS[0][1]: points[-1][0]})
        w = card["venues"][_ROWS[0][1]]["views"]["5"]
        assert w["held_open"] is True and w["held_sec"] == e.OF_LEAN_KEPT_SEC
        assert None not in w["lean"]["5m"]["values"]
    finally:
        history.LEAN.forget("SPY")


def test_held_is_at_least_when_the_values_began_inside_the_window():
    """The console started inside the window: the zone standing since the first value known has
    held at least that long, never exactly."""
    _readout, points = _replay()
    card = e.readout_card(points[-1][1], points[:20], {v: points[19][0] for v in points[-1][1]})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        w = card["venues"][v]["views"]["weighted"]
        sm = e._smoothed(
            e._standing(points[:20], v, "weighted", int(points[19][0]) - 308, int(points[19][0]))
        )
        zone, since = e._dwelled(sm, int(points[19][0]) - 308)[-1]
        known = next(int(points[19][0]) - 308 + k for k, s in enumerate(sm) if s is not None)
        assert w["held_open"] is (since == known), v


def test_the_headline_is_the_median_of_the_last_five_seconds():
    _readout, points = _replay()
    last = int(points[-1][0])
    vals = e._standing(points, "COMPOSITE", "weighted", last - 10, last)
    sm = e._smoothed(vals)
    assert sm[-1] == pytest.approx(sorted(vals[-5:])[2])


def test_the_lean_windows_are_two_and_five_minutes_and_none_is_one():
    assert [(n, s) for n, s, _step in e.OF_LEAN_WINDOWS] == [("2m", 120), ("5m", 300)]
    readout, points = _replay()
    card = e.readout_card(readout, points, {v: points[-1][0] for v in readout})
    lean = card["venues"]["COMPOSITE"]["views"]["weighted"]["lean"]
    assert set(lean) == {"2m", "5m"}
    assert (len(lean["2m"]["values"]), len(lean["5m"]["values"])) == (121, 61)


def _flips_of(values: list, first: int = 0) -> int:
    return e._flips(e._dwelled(values, first), first, first + len(values) - 1)


def test_a_flip_is_a_change_of_side_held_three_seconds():
    """INDUCED: smoothed values across the zone lines, the definition's own cases."""
    bid, offer, bal = [20] * 4, [-20] * 4, [0] * 4
    # the first lean from BALANCED is no flip
    assert _flips_of(bal + bid) == 0
    # bid to offer, held: one flip; a single print across is none
    assert _flips_of(bid + offer) == 1
    assert _flips_of(bid + [-20] + bid) == 0
    # bid, BALANCED, offer: one flip, counted on arrival at the offer side
    assert _flips_of(bid + bal) == 0
    assert _flips_of(bid + bal + offer) == 1
    # VERY ONE-SIDED counts as its side
    assert _flips_of(bid + [80] * 4) == 0
    assert _flips_of([80] * 4 + offer + [-80] * 4 + bid) == 2
    # an unknown value starts the count of sides over
    assert _flips_of(bid + [None] + offer) == 0
    # only flips arriving in the last two minutes count
    assert _flips_of(bid + offer + [-20] * 130) == 0
    assert _flips_of(bid + offer + [-20] * 100) == 1


def test_flips_on_schwabs_books_are_the_held_zone_changing_side():
    readout, points = _replay()
    last = int(points[-1][0])
    first = last - e.OF_LEAN_KEPT_SEC
    card = e.readout_card(readout, points, {v: points[-1][0] for v in readout})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        w = card["venues"][v]["views"]["weighted"]
        shown = e._dwelled(e._smoothed(e._standing(points, v, "weighted", first, last)), first)
        sides = [(first + k, e._SIDE[z]) for k, (z, _s) in enumerate(shown) if z in e._SIDE]
        arrivals = [t for (_t0, a), (t, b) in zip(sides, sides[1:], strict=False) if a != b]
        assert w["flips_2m"] == sum(1 for t in arrivals if t > last - 120), v
        assert w["flips_word"] == ("CHOPPY" if w["flips_2m"] >= 5 else "STEADY")


@pytest.mark.parametrize(
    ("values", "lean"),
    [
        ([1, 2, 3], "BUYERS"),
        ([-1, -2], "SELLERS"),
        ([1, 0, 2], "MIXED"),
        ([1, -1], "MIXED"),
        ([None, 2], "BUYERS"),
        ([None], None),
    ],
)
def test_a_sparkline_is_green_or_red_only_when_every_value_is_on_one_side(values, lean):
    """INDUCED: a window touching zero is gold (MIXED); an unknown value is not drawn."""
    assert e._lean(values) == lean


# ── the route, end to end through the console's intake ───────────────────────────────────────


def test_the_route_serves_the_readout_of_both_books_and_the_composite_live():
    """Every captured book through the console's intake: the route's readout is the readout of the
    newest book of each venue, read over the one-second values the intake kept; each venue LIVE;
    in regular hours, outside the auctions."""
    p = build_readout_payload()
    rd = p["readout"]
    readout, points = _replay()
    expected = e.readout_card(readout, points, {v: _END for v in readout})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        got = rd["venues"][v]
        assert (got["live"], got["feed_label"], got["not_live_text"]) == (True, "LIVE", None)
        assert got["views"] == expected["venues"][v]["views"], v
    assert rd["disagree"] == expected["disagree"]
    assert (rd["auction"], rd["auction_text"]) == ("NONE", None)
    assert [rd["venues"][v]["source_text"] for v in (*e.BOOK_VENUES, e.COMPOSITE)] == [
        "Schwab NYSE_BOOK · live book",
        "Schwab NASDAQ_BOOK · live book",
        "Schwab NYSE_BOOK + NASDAQ_BOOK · deduped composite · NSDQ from NYSE_BOOK",
    ]
    assert rd["detail"] == e.READOUT_DETAIL
    # the readout served is the one the intake computed on the newest book, not a second one
    assert rd["venues"]["COMPOSITE"]["book_time_ms"] == readout["COMPOSITE"]["book_time_ms"]
    # the payload's own book fields stay the one venue asked for
    assert p["venue"] == "NYSE_BOOK" and p["provenance"]["book_source"] == "NYSE_BOOK"


def test_a_book_that_stops_keeps_its_last_numbers_marked_not_live():
    """The daemon's connection ended: every venue OFFLINE, its last values standing with their
    time, read to the last value's second, never blanked."""
    p = build_readout_payload(feed_down=True)
    for v, got in p["readout"]["venues"].items():
        assert (got["live"], got["feed_label"]) == (False, "OFFLINE"), v
        assert got["not_live_text"] == (
            f"Book from {got['book_time_ct']}, not live — these are the last numbers, not current"
        )
        assert got["views"]["weighted"]["pct"] is not None
        assert got["views"]["weighted"]["bid_total"] is not None
        assert got["source_text"].endswith(f"book {got['book_time_ct']} · not live")


def test_a_book_without_its_time_says_not_live_and_that_no_time_was_sent():
    """INDUCED: a venue not live whose book came with no BOOK_TIME (the composite's when either
    book's is unknown). It keeps its words, with "-" never a blank."""
    r = {"live": False, "status": "ok", "book_time_ct": None}
    assert server._not_live_text(r) == (
        "Not live, no book time sent — these are the last numbers, not current"
    )
    assert server._source_text("COMPOSITE", r, "NONE") == (
        "Schwab NYSE_BOOK + NASDAQ_BOOK · deduped composite · NSDQ from NYSE_BOOK · not live, no"
        " book time sent"
    )


def test_no_book_serves_no_number():
    p = build_readout_payload(rows=[])
    for got in p["readout"]["venues"].values():
        assert got["status"] == "no_book" and got["touch_pct"] is None
        assert all(v["pct"] is None for v in got["views"].values())
        assert got["no_number_text"] == "No book for this symbol right now"
        assert got["source_text"].endswith("no book for this symbol right now")


def test_a_one_sided_book_shows_the_side_it_has_and_no_percentage():
    """INDUCED: Schwab's NYSE_BOOK with its asks as Schwab sends a side it has no level for (an
    empty list)."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    nyse["ASKS"] = []
    r = e.book_readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": None})["NYSE_BOOK"]
    assert r["status"] == "one_sided"
    assert all(v["pct"] is None and v["ask_total"] is None for v in r["views"].values())
    assert r["views"]["5"]["bid_total"] == 800
    assert r["one_sided_text"] == "Only the bid side has levels in this book: no percentage."


def test_a_book_with_no_levels_says_so_in_words():
    """INDUCED: Schwab's NYSE_BOOK with both sides as Schwab sends a side it has no level for."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    nyse["BIDS"] = nyse["ASKS"] = []
    r = e.book_readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": None})["NYSE_BOOK"]
    assert r["status"] == "empty"
    assert server._no_number(r) == (
        "the book Schwab sent has no levels",
        "The book Schwab sent has no levels",
    )


@pytest.mark.parametrize(
    ("at", "window"),
    [
        ("2026-11-25T09:24:59-05:00", "NONE"),
        ("2026-11-25T09:25:00-05:00", "OPEN"),
        ("2026-11-25T09:29:59-05:00", "OPEN"),
        ("2026-11-25T09:30:00-05:00", "NONE"),
        ("2026-11-25T15:49:59-05:00", "NONE"),
        ("2026-11-25T15:50:00-05:00", "CLOSE"),
        ("2026-11-25T16:00:00-05:00", "NONE"),
        # 2026-11-27: Schwab's regular window ends at 13:00 ET
        ("2026-11-27T12:49:59-05:00", "NONE"),
        ("2026-11-27T12:50:00-05:00", "CLOSE"),
        ("2026-11-27T13:00:00-05:00", "NONE"),
        ("2026-11-27T15:55:00-05:00", "NONE"),
        # Thanksgiving: Schwab says closed
        ("2026-11-26T09:27:00-05:00", "NONE"),
    ],
)
def test_the_auction_windows_come_from_schwabs_regular_window(at, window):
    assert auction(datetime.fromisoformat(at)) == window


def test_the_closing_auction_keeps_the_number_and_adds_its_line():
    """Continuous trading runs through the closing auction window: the book's number stands, and
    a line says the auction imbalance is a different number."""
    p = build_readout_payload(now=_CLOSE_AUCTION)
    assert p["readout"]["auction"] == "CLOSE"
    assert p["readout"]["auction_text"] == (
        "Closing auction window — auction imbalance is a different number, not shown here."
    )
    for got in p["readout"]["venues"].values():
        assert got["views"]["weighted"]["pct"] is not None and got["no_number_text"] is None


def test_the_opening_auction_line():
    assert server._AUCTION_TEXT[auction(datetime.fromisoformat("2026-11-25T09:27:00-05:00"))] == (
        "Opening auction window — auction imbalance is a different number, not shown here."
    )


def test_a_ticker_without_readouts_has_an_empty_series():
    history.LEAN.forget("SPY")
    assert history.LEAN.points("SPY") == []


def test_the_intake_keeps_one_value_a_second_for_the_windows_and_no_longer():
    history.LEAN.forget("SPY")
    try:
        _readout, points = _replay()
        for ts, readout in points:
            history.LEAN.record("SPY", ts, readout)
        kept = history.LEAN.points("SPY")
        assert len({int(t) for t, _v in kept}) == len(kept)
        # the window and the one value before it, which still stands at its start
        assert kept[-1][0] - kept[1][0] <= e.OF_LEAN_KEPT_SEC
    finally:
        history.LEAN.forget("SPY")


# ── the browser tests' fixtures are the route's answers ──────────────────────────────────────

_E2E_FILES = {
    "liquidity_readout_live.json": {},
    "liquidity_readout_offline.json": {"feed_down": True},
    "liquidity_readout_no_book.json": {"rows": []},
    # the first books held after 10:00 ET in which the composite is crossed, read inside the
    # closing auction window: the number stands, crossed, with the auction line
    "liquidity_readout_close_auction.json": {"now": _CLOSE_AUCTION, "rows": _CROSSED},
}


def write_readout_e2e_fixtures() -> None:
    """Regeneration utility (never called by a test): Schwab's /markets answers held as the tests
    hold them (tests/conftest.py), then each route payload written to its e2e fixture."""
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            record_markets(json.loads(a["body"]))
    for name, kw in _E2E_FILES.items():
        (_E2E / name).write_text(
            json.dumps(build_readout_payload(**kw), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("name", sorted(_E2E_FILES))
def test_each_browser_fixture_is_the_routes_answer(name):
    fixture = json.loads((_E2E / name).read_text(encoding="utf-8"))
    assert _same(fixture, build_readout_payload(**_E2E_FILES[name])), (
        f"{name} drifted from the route; regenerate with write_readout_e2e_fixtures()"
    )
