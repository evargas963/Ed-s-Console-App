"""The Desk Liquidity card's order-imbalance readout, on Schwab's real books.

The readout is engine.book_readout, engine.readout_card and server.liquidity_readout.

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
  python -c "import tests.conftest, tests.test_liquidity_readout_v1 as t
  t.write_readout_e2e_fixtures()"
"""

from __future__ import annotations

import functools
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
from tests.feed_live_helper import daemon_status
from tests.test_order_flow_book_payload_v1 import _same
from time_et import age_text, auction, ct_label, record_markets

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


def _readout(sent: dict) -> dict:
    """engine.book_readout of each venue's book as Schwab sent it.

    `sent`: venue -> its message content, or None; each read by the one reader,
    engine.read_book, as the console's intake reads it.
    """
    return e.book_readout({v: None if c is None else e.read_book(c, v) for v, c in sent.items()})


#: every venue with no book
_NO_BOOK = _readout(dict.fromkeys(e.BOOK_VENUES))


def _pair_readout() -> dict:
    return _readout({v: b["content"] for v, b in _PAIR.items()})


def _replay(rows: list = _ROWS) -> tuple[dict, list]:
    """Every captured 2026-11-02 book (or `rows`) through the readout.

    As the console's intake records it: the readout of the newest book of each venue at each
    receipt.
    """
    newest: dict = dict.fromkeys(e.BOOK_VENUES)
    points = []
    for ts, svc, content in rows:
        newest[svc] = content
        points.append((ts, _readout(newest)))
    return points[-1][1], points


def build_readout_payload(
    now: float = _END, feed_down: bool = False, rows=None, held_after: dict | None = None
) -> dict:
    """Build the route's payload for SPY at `now` after Schwab's books `rows`.

    `rows` is every captured book when None, each through the console's own intake: the daemon
    holding both books, then holding only the services `held_after` when given, or its
    connection ended (`feed_down`).
    """
    quotes = json.loads((_FX / "real_spy_level_one_2026_10_23.json").read_text(encoding="utf-8"))[
        "messages"
    ]
    ofls.clear_all_live_state()
    history.LEAN.forget("SPY")
    try:
        lmp.record_feed_heartbeat(daemon_status(now, schwab_socket_open=True, held=_HELD))
        for m in sorted(quotes, key=lambda m: m["ts_recv"]):
            lmp.record_from_level_one_equity("SPY", m["item"], received_ts=m["ts_recv"])
        for ts, svc, content in _ROWS if rows is None else rows:
            ofs._ingest_pushed(
                "book.SPY",
                book_msg(symbol="SPY", service=svc, content=content, src="schwab_book", ts_recv=ts),
            )
        if held_after is not None:
            lmp.record_feed_heartbeat(daemon_status(now, schwab_socket_open=True, held=held_after))
        if feed_down:
            lmp.record_feed_down()
        return json.loads(json.dumps(server.order_flow_microstructure("SPY", "NYSE_BOOK", now)))
    finally:
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
    """NYSE_BOOK's best five bids 160, 120, 120, 360, 40 and asks 200, 320, 1560, 40, 40 shares.

    The headline weighs each level, the flat views sum the shares, and the weighted view's bars
    are the flat top five.
    """
    nyse = _pair_readout()["NYSE_BOOK"]["views"]
    bids, asks = [160, 120, 120, 360, 40], [200, 320, 1560, 40, 40]
    wb = sum(w * b for w, b in zip(e.OF_LEVEL_WEIGHTS, bids, strict=True))
    wa = sum(w * a for w, a in zip(e.OF_LEVEL_WEIGHTS, asks, strict=True))
    assert nyse["weighted"]["pct"] == pytest.approx((wb - wa) / (wb + wa) * 100)
    assert (nyse["weighted"]["bid_total"], nyse["weighted"]["ask_total"]) == (800, 2160)
    assert nyse["weighted"]["imbalance"] * 100 == pytest.approx((800 - 2160) / 2960 * 100)
    for view, (b, a) in {"1": (160, 200), "3": (400, 2080), "5": (800, 2160)}.items():
        v = nyse[view]
        assert (v["bid_total"], v["ask_total"]) == (b, a)
        assert v["pct"] == v["imbalance"] * 100 == pytest.approx((b - a) / (b + a) * 100)
        assert (v["difference"], v["total_depth"]) == (abs(b - a), b + a)


def test_the_weighted_headline_is_not_the_flat_top_five():
    """Schwab's NASDAQ_BOOK: the touch leans to the bids, the flat top five to the offers.

    The touch leans to the bids (+17.6%) while the flat top five leans to the offers (-5.5%);
    the weighted headline follows the touch, and says the two disagree.
    """
    nq = _pair_readout()["NASDAQ_BOOK"]["views"]
    assert nq["1"]["pct"] > 0 > nq["5"]["pct"]
    assert nq["weighted"]["pct"] > 0 > nq["weighted"]["imbalance"]
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


# ── the composite: each exchange once, its newest quote ──────────────────────────────────────


def _merged(books: dict) -> dict:
    """Recompute the composite from the books as Schwab sent them, with no engine code.

    Each side's quotes, every code once (any case), from the book whose copy carries the newer
    quote time (SEQUENCE; an equal time keeps NYSE_BOOK's), summed at each price, best first.
    """
    out = {}
    for side, pk, sk in (("BIDS", "BID_PRICE", "BID_VOLUME"), ("ASKS", "ASK_PRICE", "ASK_VOLUME")):
        newest: dict = {}
        # each venue's levels on this side (Schwab leaves an empty side out), NYSE_BOOK first:
        # an equal quote time keeps its copy
        sent = [
            (venue, book[side])
            for venue, book in sorted(books.items(), key=lambda vb: vb[0] != "NYSE_BOOK")
            if side in book
        ]
        for venue, levels in sent:
            for lv in levels:
                for x in lv[side]:
                    code = x["EXCHANGE"].upper()
                    if code not in newest or x["SEQUENCE"] > newest[code][0]:
                        newest[code] = (x["SEQUENCE"], venue)
        at: dict = {}
        for venue, levels in sent:
            for lv in levels:
                for x in lv[side]:
                    if newest[x["EXCHANGE"].upper()][1] == venue:
                        at[lv[pk]] = at.get(lv[pk], 0) + x[sk]
        out[side] = sorted(at.items(), reverse=side == "BIDS")
    return out


def _expected(merged: dict, view: str) -> tuple[float, float, float]:
    """(bid total, ask total, percentage) of a recomputed composite's view."""
    bids, asks = ([s for _p, s in merged[side][:5]] for side in ("BIDS", "ASKS"))
    depth = 5 if view == "weighted" else int(view)
    bt, at = sum(bids[:depth]), sum(asks[:depth])
    if view == "weighted":
        w = e.OF_LEVEL_WEIGHTS
        b = sum(x * s for x, s in zip(w, bids, strict=False)) / sum(w[: len(bids)])
        a = sum(x * s for x, s in zip(w, asks, strict=False)) / sum(w[: len(asks)])
        return bt, at, (b - a) / (b + a) * 100
    return bt, at, (bt - at) / (bt + at) * 100


_COMPOSITE_BOOKS = {
    # 2026-09-25 10:30 ET: NSDQ in NYSE_BOOK at 767.39 x 80 bid, 767.41 x 120 ask; in NASDAQ_BOOK
    # (431 ms newer) at 767.41 x 100 bid, 767.42 x 70 ask
    "pair": {v: b["content"] for v, b in _PAIR.items()},
    # 2026-11-02 10:00:08 ET: NASDAQ_BOOK's NSDQ bid 760.58 x 20, quoted after NYSE_BOOK's
    # 760.56 x 80
    "rows_15_16": {_ROWS[16][1]: _ROWS[16][2], _ROWS[15][1]: _ROWS[15][2]},
    "locked": {svc: c for _ts, svc, c in _TOUCHING["LOCKED"]},
    "crossed": {svc: c for _ts, svc, c in _TOUCHING["CROSSED"]},
}


@pytest.mark.parametrize("name", sorted(_COMPOSITE_BOOKS))
def test_the_composite_is_every_quote_once_its_newest_copy(name):
    """Schwab's books, each composite recomputed from them as sent.

    Every exchange and market maker once, NSDQ (in both books) from the book whose copy carries
    the newer quote time, the shares summed at each distinct price.
    """
    books = _COMPOSITE_BOOKS[name]
    comp = _readout(books)["COMPOSITE"]
    for view in e.READOUT_VIEWS:
        bt, at, pct = _expected(_merged(books), view)
        v = comp["views"][view]
        assert (v["bid_total"], v["ask_total"]) == (bt, at), view
        assert v["pct"] == pytest.approx(pct), view
    assert comp["dedup_partial"] is False
    assert comp["books"] == ["NYSE_BOOK", "NASDAQ_BOOK"]
    times = [b["BOOK_TIME"] for b in books.values()]
    assert comp["book_time_ms"] == min(times)  # the older book's


def test_the_newer_nsdq_quote_counts_and_the_older_copy_does_not():
    """Schwab's pair of 2026-09-25 10:30 ET: NASDAQ_BOOK's newer NSDQ copy counts.

    NSDQ in NYSE_BOOK at 767.39 x 80 bid and 767.41 x 120 ask; in NASDAQ_BOOK, quoted later on
    both sides, at 767.41 x 100 bid and 767.42 x 70 ask. NASDAQ_BOOK's copy counts: the best
    bid is Nasdaq's 767.41, which meets the other exchanges' 767.41 ask (the composite is
    locked), and the top five hold 780 bid and 2110 ask shares (NYSE_BOOK's older copy would
    give a 767.39 best bid, 800 and 2160).
    """
    nyse, nq = (_PAIR[v]["content"] for v in ("NYSE_BOOK", "NASDAQ_BOOK"))
    for side in ("BIDS", "ASKS"):
        seq = {
            v: {x["SEQUENCE"] for lv in b[side] for x in lv[side] if x["EXCHANGE"] == "NSDQ"}
            for v, b in (("NYSE_BOOK", nyse), ("NASDAQ_BOOK", nq))
        }
        assert min(seq["NASDAQ_BOOK"]) > max(seq["NYSE_BOOK"]), side
    comp = _pair_readout()["COMPOSITE"]
    assert (comp["views"]["5"]["bid_total"], comp["views"]["5"]["ask_total"]) == (780, 2110)
    assert comp["views"]["1"]["bid_total"] == 100  # Nasdaq's own 767.41 bid
    assert comp["touch_state"] == "LOCKED"


def test_the_composite_never_sums_the_books_level_totals():
    """Schwab's pair: the composite's best three asks are each contributor's newest quote once.

    Never the two books' TOTAL_VOLUMEs summed at those prices (2150) and never an average of
    NSDQ's two sizes.
    """
    comp = _pair_readout()["COMPOSITE"]
    bt, at, _pct = _expected(_merged({v: b["content"] for v, b in _PAIR.items()}), "3")
    assert (comp["views"]["3"]["bid_total"], comp["views"]["3"]["ask_total"]) == (bt, at)
    assert (
        sum(
            lv["TOTAL_VOLUME"]
            for b in _PAIR.values()
            for lv in b["content"]["ASKS"]
            if lv["ASK_PRICE"] in (767.41, 767.42, 767.43)
        )
        == 2080 + 70
    )
    assert comp["views"]["3"]["ask_total"] == 80 + 390 + 1560 != 2080 + 70


def _rows_without(book: dict, key: str, code: str) -> dict:
    """Copy a book as sent, with `key` taken from (or `code` spelled into) NSDQ's rows."""
    out = json.loads(json.dumps(book))
    for side in ("BIDS", "ASKS"):
        for lv in out[side]:
            for x in lv[side]:
                if x["EXCHANGE"] == "NSDQ":
                    x.pop(key, None)
                    x["EXCHANGE"] = code
    return out


def test_nsdq_is_one_contributor_however_spelled():
    """INDUCED: Schwab's NASDAQ_BOOK of the pair with NSDQ spelled in lower case.

    Schwab spells other exchanges so there (tests/fixtures/real_tsla_book_rows.json): the
    composite is the same, its dedup whole.
    """
    want = _pair_readout()["COMPOSITE"]["views"]
    nq = _rows_without(_PAIR["NASDAQ_BOOK"]["content"], "nothing", "nsdq")
    comp = _readout({"NYSE_BOOK": _PAIR["NYSE_BOOK"]["content"], "NASDAQ_BOOK": nq})
    assert comp["COMPOSITE"]["dedup_partial"] is False
    for view in e.READOUT_VIEWS:
        got = comp["COMPOSITE"]["views"][view]
        assert (got["bid_total"], got["ask_total"]) == (
            want[view]["bid_total"],
            want[view]["ask_total"],
        )


def test_a_copy_without_its_quote_time_is_never_the_newer():
    """INDUCED: Schwab's pair with NASDAQ_BOOK's NSDQ rows sent without their quote time.

    Every row of SPY's and IWM's 2026-11-02 books carries one. NYSE_BOOK's timed NSDQ counts,
    once, at its 767.39 bid and 767.41 ask (the top five 800 bid and 2,160 ask, NASDAQ_BOOK's
    own book unchanged), and the composite says its dedup is partial, and why.
    """
    nq = _rows_without(_PAIR["NASDAQ_BOOK"]["content"], "SEQUENCE", "NSDQ")
    comp = _readout({"NYSE_BOOK": _PAIR["NYSE_BOOK"]["content"], "NASDAQ_BOOK": nq})
    assert comp["COMPOSITE"]["dedup_partial"] is True
    five = comp["COMPOSITE"]["views"]["5"]
    assert (five["bid_total"], five["ask_total"]) == (800, 2160)
    assert comp["COMPOSITE"]["views"]["1"]["bid_total"] == 160  # ARCX 80 + NSDQ 80 at 767.39
    assert comp["NASDAQ_BOOK"] == _pair_readout()["NASDAQ_BOOK"]
    assert _served(comp)[e.COMPOSITE]["dedup_partial_text"] == (
        "Dedup partial: a level came without per-exchange sizes (its total taken whole), or a"
        " quote in both books without its quote time (a timed copy counts over it)"
    )


def test_on_an_equal_quote_time_nyse_books_copy_counts():
    """INDUCED: Schwab's pair with NASDAQ_BOOK's NSDQ rows given NYSE_BOOK's NSDQ quote times.

    The times are bid 37799874, ask 37800006: an equal time keeps NYSE_BOOK's copy (767.39 x 80
    bid, 767.41 x 120 ask), never NASDAQ_BOOK's (767.41 x 100, 767.42 x 70), never both.
    """
    nyse = _PAIR["NYSE_BOOK"]["content"]
    nq = json.loads(json.dumps(_PAIR["NASDAQ_BOOK"]["content"]))
    for side in ("BIDS", "ASKS"):
        (same,) = {x["SEQUENCE"] for lv in nyse[side] for x in lv[side] if x["EXCHANGE"] == "NSDQ"}
        for lv in nq[side]:
            for x in lv[side]:
                if x["EXCHANGE"] == "NSDQ":
                    x["SEQUENCE"] = same
    comp = _readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": nq})["COMPOSITE"]
    assert comp["dedup_partial"] is False
    assert (comp["views"]["5"]["bid_total"], comp["views"]["5"]["ask_total"]) == (800, 2160)
    assert comp["views"]["1"]["bid_total"] == 160


def _served(readout: dict) -> dict:
    """Return the route's card for that one readout, recorded by the intake at _END - 1."""
    history.LEAN.forget("SPY")
    try:
        history.LEAN.record("SPY", _END - 1, readout)
        return server.liquidity_readout("SPY", _END)["venues"]
    finally:
        history.LEAN.forget("SPY")


def test_a_level_without_per_exchange_rows_is_taken_whole_and_the_dedup_marked_partial():
    """A level as Schwab sent it, its own rows removed: its TOTAL_VOLUME is counted once.

    The composite says its dedup is partial.
    """
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    del nyse["BIDS"][1]["BIDS"]  # 767.38: BATX 80 + NYSE 40, TOTAL_VOLUME 120
    comp = _readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": _PAIR["NASDAQ_BOOK"]["content"]})
    assert comp["COMPOSITE"]["dedup_partial"] is True
    assert comp["COMPOSITE"]["views"]["5"]["bid_total"] == 780  # 120 whole, as its rows summed


def test_any_code_in_both_books_counts_once():
    """Schwab has spelled exchanges in lower case in NASDAQ_BOOK where NYSE_BOOK uses upper case.

    TSLA's arcx, edgx and batx on 2026-09-25 (tests/fixtures/real_tsla_book_rows.json), where
    NYSE_BOOK spells them ARCX, EDGX, BATX. INDUCED: that real book, and the same book with its
    codes in upper case, as NYSE_BOOK spells them (no captured pair of the two spellings is
    held: SPY's and IWM's books of 2026-11-02 share NSDQ only). Matched without regard to case,
    every code is in both books with the same quote time: each counts once, so the composite is
    the one book, never doubled.
    """
    tsla = json.loads((_FX / "real_tsla_book_rows.json").read_text(encoding="utf-8"))["rows"]
    lower = {
        x["EXCHANGE"]
        for _ts, _svc, c in tsla
        for side in ("BIDS", "ASKS")
        if side in c  # Schwab leaves an empty side out
        for lv in c[side]
        for x in lv[side]
    }
    assert {"arcx", "edgx", "batx", "NSDQ"} <= lower
    newer = tsla[0][2]
    as_nyse = json.loads(json.dumps(newer))
    as_nyse["BOOK_TIME"] -= 1
    for side in ("BIDS", "ASKS"):
        for lv in as_nyse[side]:
            for x in lv[side]:
                x["EXCHANGE"] = x["EXCHANGE"].upper()
    r = _readout({"NYSE_BOOK": as_nyse, "NASDAQ_BOOK": newer})
    alone = _readout({"NYSE_BOOK": None, "NASDAQ_BOOK": newer})
    assert r["COMPOSITE"]["status"] == "ok"
    for view in e.READOUT_VIEWS:
        got, one = r["COMPOSITE"]["views"][view], alone["COMPOSITE"]["views"][view]
        assert (got["bid_total"], got["ask_total"]) == (one["bid_total"], one["ask_total"]), view


def test_with_one_book_the_composite_is_that_book():
    """Schwab's NASDAQ_BOOK alone, as for a Nasdaq-listed ticker Schwab sends no NYSE_BOOK for.

    The composite is NASDAQ_BOOK's numbers, its source names that book.
    """
    r = _readout({"NYSE_BOOK": None, "NASDAQ_BOOK": _PAIR["NASDAQ_BOOK"]["content"]})
    assert r["COMPOSITE"]["books"] == ["NASDAQ_BOOK"]
    for view in e.READOUT_VIEWS:
        comp, nq = r["COMPOSITE"]["views"][view], r["NASDAQ_BOOK"]["views"][view]
        assert (comp["bid_total"], comp["ask_total"], comp["pct"]) == (
            nq["bid_total"],
            nq["ask_total"],
            nq["pct"],
        ), view
    got = _served(r)
    assert got["NYSE_BOOK"]["no_number_head"] == "NO BOOK"
    assert got[e.COMPOSITE]["no_number_text"] is None
    assert got[e.COMPOSITE]["source_text"].startswith(
        "Schwab NASDAQ_BOOK · composite, newest quote of each exchange"
    )


def test_a_nasdaq_only_composite_is_live_while_the_feed_holds_both_books():
    """Schwab's NASDAQ_BOOK messages of 2026-11-02 alone, the daemon holding SPY on both books.

    As it holds every watchlist ticker: its status of 2026-11-04 holds 10 symbols on each. The
    composite is NASDAQ_BOOK's book, live, its source naming that one book.
    """
    rows = [r for r in _ROWS if r[1] == "NASDAQ_BOOK"]
    comp = build_readout_payload(rows=rows)["readout"]["venues"][e.COMPOSITE]
    assert (comp["live"], comp["feed_label"], comp["books"]) == (True, "LIVE", ["NASDAQ_BOOK"])
    assert comp["source_text"] == "Schwab NASDAQ_BOOK · composite, newest quote of each exchange"
    assert comp["views"]["weighted"]["pct"] is not None


def test_with_no_book_the_composite_names_the_two_books_it_reads():
    got = _served(_NO_BOOK)[e.COMPOSITE]
    assert got["no_number_head"] == "NO BOOK"
    assert got["source_text"].startswith(
        "Schwab NYSE_BOOK + NASDAQ_BOOK · composite, newest quote of each exchange · no book"
    )


def test_a_book_with_no_levels_adds_nothing_to_the_composite():
    """INDUCED: Schwab's pair with NASDAQ_BOOK as Schwab sends a book after the close.

    No levels (tests/test_order_flow_served_v1.py): the composite is NYSE_BOOK's quotes alone.
    With NYSE_BOOK's asks so, the composite's asks are NASDAQ_BOOK's and its bids both books'.
    """
    nyse, nq = _PAIR["NYSE_BOOK"]["content"], _PAIR["NASDAQ_BOOK"]["content"]
    r = _readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": {**nq, "BIDS": [], "ASKS": []}})
    for view in e.READOUT_VIEWS:
        comp, one = r[e.COMPOSITE]["views"][view], r["NYSE_BOOK"]["views"][view]
        assert (comp["bid_total"], comp["ask_total"]) == (one["bid_total"], one["ask_total"])
    books = {"NYSE_BOOK": {**nyse, "ASKS": []}, "NASDAQ_BOOK": nq}
    r = _readout(books)
    assert r[e.COMPOSITE]["status"] == "ok"
    for view in e.READOUT_VIEWS:
        bt, at, _pct = _expected(_merged(books), view)
        got = r[e.COMPOSITE]["views"][view]
        assert (got["bid_total"], got["ask_total"]) == (bt, at), view


def test_crossed_withholds_the_sentence_and_locked_keeps_it():
    """Schwab's books when the composite was first locked and first crossed on 2026-11-02.

    First locked (NYSE_BOOK's 760.25 bid and ask) and first crossed (NYSE_BOOK's 757.58 bid
    over its 757.57 ask) after 10:00 ET on 2026-11-02.
    """
    for state, flag in (("LOCKED", "BOOK LOCKED"), ("CROSSED", "BOOK CROSSED")):
        readout = _readout({svc: content for _ts, svc, content in _TOUCHING[state]})
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
                    diff = abs(v["bid_total"] - v["ask_total"])
                    assert v["sentence"] == (
                        "Balanced — no shares needed to balance."
                        if diff == 0
                        else f"Nearly balanced — {diff:,.0f} shares would even the book."
                        if v["zone"] == "BALANCED"
                        else "To balance, market makers"
                        f" {'sell' if v['bid_total'] > v['ask_total'] else 'buy'}"
                        f" {diff:,.0f} shares."
                    )
        assert card["venues"]["NASDAQ_BOOK"]["touch_flag"] is None


# ── spans and thin ladders ───────────────────────────────────────────────────────────────────


def test_the_spans_run_from_the_touch_to_the_depths_last_level():
    """Schwab's pair: NYSE_BOOK bids 767.39 to 767.35 and asks 767.41 to 767.60 over five levels.

    NASDAQ_BOOK bids 767.41 to 753.40; a one-level span is 0.
    """
    card = e.readout_card(
        _pair_readout(), [(1.0, _pair_readout())], dict.fromkeys(_pair_readout(), 1.0)
    )
    nyse, nq = card["venues"]["NYSE_BOOK"]["views"], card["venues"]["NASDAQ_BOOK"]["views"]
    assert (nyse["5"]["span_bid_text"], nyse["5"]["span_ask_text"]) == ("0.04", "0.19")
    assert nyse["weighted"]["span_bid_text"] == nyse["5"]["span_bid_text"]
    assert (nyse["3"]["span_bid_text"], nyse["1"]["span_bid_text"]) == ("0.02", "0.00")
    assert nq["5"]["span_bid_text"] == f"{767.41 - 753.40:.2f}"


def test_a_thin_side_is_read_over_the_levels_it_has_with_the_weights_renormalized():
    """Schwab's NYSE_BOOK at 10:00:34 ET on 2026-11-02 (row 66): seven bid and four ask levels.

    The asks' top five is its four, the weights renormalized over four, no level invented; the
    counts line says so.
    """
    _ts, svc, content = _ROWS[66]
    r = _readout({v: content if v == svc else None for v in e.BOOK_VENUES})[svc]
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


def _steady(readout: dict, venue: str, view: str) -> dict:
    """INDUCED times: one of Schwab's readouts standing ten seconds; the card's view of it."""
    points = [(1000.0 + k, readout) for k in range(10)]
    card = e.readout_card(readout, points, dict.fromkeys(readout, points[-1][0]))
    return card["venues"][venue]["views"][view]


@pytest.mark.parametrize(
    ("row", "venue", "view", "pct", "zone"),
    [
        (16, "NYSE_BOOK", "1", 0.0, "BALANCED"),
        (16, "NYSE_BOOK", "weighted", 9.524, "BALANCED"),
        (14, "NYSE_BOOK", "5", -9.474, "BALANCED"),
        (8, "NYSE_BOOK", "5", 10.0, "BID_HEAVY"),
        (2, "NYSE_BOOK", "5", -10.0, "OFFER_HEAVY"),
        (69, "NASDAQ_BOOK", "1", 69.231, "BID_HEAVY"),
        (123, "NASDAQ_BOOK", "1", -69.231, "OFFER_HEAVY"),
        (82, "NYSE_BOOK", "1", 70.0, "BID_HEAVY"),
        (18, "NYSE_BOOK", "1", -76.190, "OFFER_HEAVY"),
    ],
)
def test_the_zone_turns_at_10_percent(row, venue, view, pct, zone):
    """Schwab's readouts of 2026-11-02 10:00-10:02:30 ET on each side of the 10% line.

    Held ten seconds: 10% exactly (NYSE_BOOK's 1,760 / 1,440 shares) is the side's zone, and
    so is every value past it.
    """
    w = _steady(_replayed()[1][row][1], venue, view)
    assert w["pct"] == pytest.approx(pct, abs=5e-4)
    assert (w["zone"], w["side_word"]) == (zone, e.ZONE_WORDS[zone])


_LINES = json.loads((_FX / "real_spy_zone_line_books_2026_11_02.json").read_text(encoding="utf-8"))[
    "cases"
]


@pytest.mark.parametrize(
    ("case", "line", "zone"),
    [
        ("under 10", 10.0, "BALANCED"),
        ("under -10", -10.0, "BALANCED"),
    ],
)
def test_the_zones_on_the_books_nearest_the_line(case, line, zone):
    """The two books held, over SPY's whole 2026-11-02 session, nearest the 10% line.

    When a venue and view read nearest inside it (9.996%, -9.989%), held ten seconds: just
    inside the line is not past it.
    """
    c = _LINES[case]
    readout = _readout({svc: content for _ts, svc, content in c["books"]})
    w = _steady(readout, c["venue"], c["view"])
    assert w["pct"] == pytest.approx(line, abs=0.02)
    assert abs(w["pct"]) < abs(line)
    assert (w["zone"], w["side_word"]) == (zone, e.ZONE_WORDS[zone])


def test_no_value_has_no_zone():
    w = _steady(_NO_BOOK, "NYSE_BOOK", "weighted")
    assert (w["pct"], w["zone"]) == (None, None)


def test_the_sentence_four_cases_from_the_flat_shares():
    """Schwab's own books, each held ten seconds.

    NYSE_BOOK's touch at 10:00:08 ET on 2026-11-02 (80 bid, 80 ask), its weighted view then
    (+1.5%, 240 shares apart), NYSE_BOOK's touch on 2026-09-25 (160 bid, 200 ask),
    NASDAQ_BOOK's then (100 bid, 70 ask) and the composite's top five then (780 bid, 2,110 ask).
    """
    rows, pair = _replayed()[1], _pair_readout()
    assert _steady(rows[16][1], "NYSE_BOOK", "1")["sentence"] == (
        "Balanced — no shares needed to balance."
    )
    assert _steady(rows[2][1], "NYSE_BOOK", "weighted")["sentence"] == (
        "Nearly balanced — 240 shares would even the book."
    )
    assert _steady(pair, "NYSE_BOOK", "1")["sentence"] == "To balance, market makers buy 40 shares."
    assert _steady(pair, e.COMPOSITE, "5")["sentence"] == (
        "To balance, market makers buy 1,330 shares."
    )
    assert _steady(pair, "NASDAQ_BOOK", "1")["sentence"] == (
        "To balance, market makers sell 30 shares."
    )
    assert _steady(_NO_BOOK, "NYSE_BOOK", "1")["sentence"] is None


# ── over time: the zone's hold, flips, the lean windows ──────────────────────────────────────


@pytest.mark.parametrize(
    ("runs", "zone", "held"),
    [
        # two seconds of bid heavy books are shown as they are; BALANCED again from 1012: at
        # 1021 it has held 9 seconds
        ((("bal", 10), ("bid", 2), ("bal", 10)), "BALANCED", 9),
        # bid heavy from second 1010: the zone changes that second; at 1019 it has held 9
        ((("bal", 10), ("bid", 10)), "BID_HEAVY", 9),
        # through BALANCED (1010-1012) to offer heavy from 1013: held 9 at 1022
        ((("bid", 10), ("bal", 3), ("offer", 10)), "OFFER_HEAVY", 9),
        # a single second across and back is shown: bid heavy again from 1011, held 9 at 1020
        ((("bid", 10), ("offer", 1), ("bid", 10)), "BID_HEAVY", 9),
        # past 70% is still its side's zone, dated from when the value entered the side (1010)
        ((("bal", 10), ("bid", 3), ("very_bid", 10)), "BID_HEAVY", 12),
    ],
)
def test_a_zone_is_the_values_own_dated_from_the_second_it_entered(runs, zone, held):
    """INDUCED times: Schwab's readouts of 2026-11-02 by the zone of NYSE_BOOK's touch.

    One a second from second 1000.
    """
    w = _touch_card(*runs)
    assert (w["zone"], w["held_sec"]) == (zone, held)


def test_an_unknown_value_starts_the_zone_over():
    """INDUCED times: BALANCED books 1000-1004, no book 1005-1014, BALANCED again from 1015.

    The zone is dated from 1015, not from the first value known, and says so (held 9 at 1024).
    """
    w = _touch_card(("bal", 5), ("none", 10), ("bal", 10))
    assert (w["zone"], w["held_sec"], w["held_open"]) == ("BALANCED", 9, False)


def _zone_of(pct: float | None) -> str | None:
    """Return a percentage's zone by its definition (the register's line, OF_ZONE_LEANING_PCT)."""
    if pct is None:
        return None
    if abs(pct) < e.OF_ZONE_LEANING_PCT:
        return "BALANCED"
    return "BID_HEAVY" if pct > 0 else "OFFER_HEAVY"


def test_on_schwabs_books_the_zone_is_the_headlines_own_dated_from_when_it_entered():
    """Every venue and view of the captured books, read at each second.

    The zone shown is the zone of the headline (the 2-minute series' last value) that second,
    and is dated from the second the headline entered it.
    """
    readout, points = _replayed()
    for s in range(int(points[0][0]), int(points[-1][0]) + 1):
        card = e.readout_card(readout, points, dict.fromkeys(readout, float(s)))
        for v in (*e.BOOK_VENUES, e.COMPOSITE):
            for view in e.READOUT_VIEWS:
                w = card["venues"][v]["views"][view]
                series, zone = w["lean"]["2m"]["values"], w["zone"]
                assert series[-1] == w["pct"]
                assert zone == _zone_of(w["pct"]), (v, view, s)
                at = None if zone is None else len(series) - 1 - w["held_sec"]
                if at is not None and at >= 0:
                    assert _zone_of(series[at]) == zone, (v, view, s)
                    assert at == 0 or _zone_of(series[at - 1]) != zone, (v, view, s)


def test_held_is_at_least_when_the_zone_stood_from_the_first_value_kept():
    """INDUCED: one of Schwab's books, recorded again 400 s later with nothing between.

    A quiet ticker: the first still stands at the window's start, so the zone has held at least
    the window, and says so.
    """
    history.LEAN.forget("SPY")
    try:
        for ts, svc, content in (_ROWS[0], [_ROWS[0][0] + 400, _ROWS[0][1], _ROWS[0][2]]):
            history.LEAN.record(
                "SPY", ts, _readout({v: content if v == svc else None for v in e.BOOK_VENUES})
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
    """The console started inside the window.

    The zone standing since the first value known has held at least that long, never exactly.
    """
    _readout, points = _replayed()
    end = int(points[19][0])
    card = e.readout_card(points[-1][1], points[:20], {v: points[19][0] for v in points[-1][1]})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        w = card["venues"][v]["views"]["weighted"]
        series = w["lean"]["2m"]["values"]
        known = end - (len(series) - 1) + next(k for k, x in enumerate(series) if x is not None)
        assert w["held_open"] is (end - w["held_sec"] == known), v
        assert w["held_text"] == f"HELD {'≥' if w['held_open'] else ''}{w['held_sec']}s"


def test_the_headline_is_the_value_standing_at_the_last_second():
    """The composite's weighted headline at the last captured second.

    It is the newest readout's own value received by that second's end, as it is.
    """
    readout, points = _replayed()
    card = e.readout_card(readout, points, dict.fromkeys(readout, points[-1][0]))
    assert (
        card["venues"][e.COMPOSITE]["views"]["weighted"]["pct"]
        == points[-1][1][e.COMPOSITE]["views"]["weighted"]["pct"]
    )


def test_the_lean_windows_are_two_and_five_minutes_and_none_is_one():
    assert [(n, s) for n, s, _step in e.OF_LEAN_WINDOWS] == [("2m", 120), ("5m", 300)]
    readout, points = _replay()
    card = e.readout_card(readout, points, {v: points[-1][0] for v in readout})
    lean = card["venues"]["COMPOSITE"]["views"]["weighted"]["lean"]
    assert set(lean) == {"2m", "5m"}
    assert (len(lean["2m"]["values"]), len(lean["5m"]["values"])) == (121, 61)


#: Schwab's readouts of 2026-11-02 (replay index) by the zone of NYSE_BOOK's touch: +33% bid
#: heavy, -33% offer heavy, 0% balanced (80 / 80), +71% and -76% very one-sided
_TOUCH = {"bid": 2, "offer": 0, "bal": 16, "very_bid": 4, "very_offer": 18}


@functools.cache
def _replayed() -> tuple[dict, list]:
    return _replay()


def _touch_card(*runs: tuple[str, int]) -> dict:
    """INDUCED times: Schwab's readouts named by the zone of NYSE_BOOK's touch.

    Each run of them one a second (`none`: no book); the card's NYSE_BOOK touch view after the
    last.
    """
    pts = _replayed()[1]
    seq = [_NO_BOOK if n == "none" else pts[_TOUCH[n]][1] for n, k in runs for _ in range(k)]
    points = [(1000.0 + i, r) for i, r in enumerate(seq)]
    card = e.readout_card(seq[-1], points, dict.fromkeys(seq[-1], points[-1][0]))
    return card["venues"]["NYSE_BOOK"]["views"]["1"]


@pytest.mark.parametrize(
    ("runs", "flips"),
    [
        # the first lean from BALANCED is no flip
        ((("bal", 10), ("bid", 10)), 0),
        # bid to offer: one flip; a single second across and back is two
        ((("bid", 10), ("offer", 10)), 1),
        ((("bid", 10), ("offer", 1), ("bid", 10)), 2),
        # bid, BALANCED, offer: one flip, counted on arrival at the offer side
        ((("bid", 10), ("bal", 10)), 0),
        ((("bid", 10), ("bal", 10), ("offer", 10)), 1),
        # past 70% is still its side
        ((("bid", 10), ("very_bid", 10)), 0),
        ((("very_bid", 10), ("offer", 10), ("very_offer", 10), ("bid", 10)), 2),
        # an unknown value starts the count of sides over
        ((("bid", 10), ("none", 10), ("offer", 10)), 0),
        # only flips arriving in the last two minutes count
        ((("bid", 10), ("offer", 140)), 0),
        ((("bid", 10), ("offer", 100)), 1),
        # six runs, side to side: five flips
        (tuple((side, 10) for side in ("bid", "offer") * 3), 5),
    ],
)
def test_a_flip_is_a_change_of_side(runs, flips):
    w = _touch_card(*runs)
    assert w["flips_2m"] == flips


@pytest.mark.parametrize(
    ("runs", "lean"),
    [
        ((("bid", 10),), "BUYERS"),
        ((("offer", 10),), "SELLERS"),
        # a window touching zero is gold
        ((("bid", 10), ("bal", 10)), "MIXED"),
        ((("bid", 10), ("offer", 10)), "MIXED"),
        # an unknown value is not drawn
        ((("none", 5), ("bid", 10)), "BUYERS"),
        ((("none", 5),), None),
    ],
)
def test_a_sparkline_is_green_or_red_only_when_every_value_is_on_one_side(runs, lean):
    assert _touch_card(*runs)["lean"]["2m"]["lean"] == lean


# ── the route, end to end through the console's intake ───────────────────────────────────────


def test_the_route_serves_the_readout_of_both_books_and_the_composite_live():
    """Every captured book through the console's intake.

    The route's readout is the readout of the newest book of each venue, read over the
    one-second values the intake kept; each venue LIVE; in regular hours, outside the auctions.
    """
    p = build_readout_payload()
    rd = p["readout"]
    readout, points = _replay()
    expected = e.readout_card(readout, points, {v: _END for v in readout})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        got = rd["venues"][v]
        assert (got["live"], got["feed_label"]) == (True, "LIVE")
        assert got["views"] == expected["venues"][v]["views"], v
    assert rd["disagree"] == expected["disagree"]
    assert (rd["auction"], rd["auction_text"]) == ("NONE", None)
    assert [rd["venues"][v]["source_text"] for v in (*e.BOOK_VENUES, e.COMPOSITE)] == [
        "Schwab NYSE_BOOK · live book",
        "Schwab NASDAQ_BOOK · live book",
        "Schwab NYSE_BOOK + NASDAQ_BOOK · composite, newest quote of each exchange",
    ]
    assert rd["detail"] == e.READOUT_DETAIL
    # the readout served is the one the intake computed on the newest book, not a second one
    assert rd["venues"]["COMPOSITE"]["book_time_ms"] == readout["COMPOSITE"]["book_time_ms"]
    # the payload's own book fields stay the one venue asked for
    assert p["venue"] == "NYSE_BOOK" and p["provenance"]["book_source"] == "NYSE_BOOK"


def test_a_book_that_stops_keeps_its_last_numbers_marked_not_live():
    """The daemon's connection ended: every venue OFFLINE.

    Its last values stand with their time, read to the last value's second, never blanked.
    """
    p = build_readout_payload(feed_down=True)
    for v, got in p["readout"]["venues"].items():
        assert (got["live"], got["feed_label"]) == (False, "OFFLINE"), v
        age = age_text(_END - got["book_time_ms"] / 1000.0)
        assert got["book_age_text"] == age
        assert got["book_time_ct"] == ct_label(got["book_time_ms"] / 1000.0)
        assert got["views"]["weighted"]["pct"] is not None
        assert got["views"]["weighted"]["bid_total"] is not None
        assert got["source_text"].endswith(f"book {got['book_time_ct']} · {age} old · not live")
        # said once, on the source line, as every other card says it
        words = [t for k, t in got.items() if k.endswith("_text") and isinstance(t, str)]
        assert sum("not live" in t.lower() for t in words) == 1, words


def test_a_book_without_its_time_says_not_live_and_that_no_time_was_sent():
    """INDUCED: Schwab's pair with NYSE_BOOK's BOOK_TIME removed, read with no feed (not live).

    It and the composite keep their words, with "-" never a blank.
    """
    nyse = {k: v for k, v in _PAIR["NYSE_BOOK"]["content"].items() if k != "BOOK_TIME"}
    got = _served(_readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": _PAIR["NASDAQ_BOOK"]["content"]}))
    assert got["NYSE_BOOK"]["source_text"].startswith(
        "Schwab NYSE_BOOK · not live, no book time sent"
    )
    assert got[e.COMPOSITE]["source_text"].startswith(
        "Schwab NYSE_BOOK + NASDAQ_BOOK · composite, newest quote of each exchange · not live, no"
        " book time sent"
    )


def test_a_book_that_stopped_is_read_to_its_own_last_book_while_the_other_runs():
    """INDUCED: the captured books with NASDAQ_BOOK's after 10:01:30 ET left out.

    As if it stopped then, through the intake, the daemon then holding NYSE_BOOK only:
    NASDAQ_BOOK is not live, and its held time and flips are read to the second its last book
    arrived, not on with NYSE_BOOK's. The composite, not live either, still moves with
    NYSE_BOOK: its headline is read to its own last change, the same moment as its bars and
    sentence.
    """
    cut = datetime.fromisoformat("2026-11-02T10:01:30-05:00").timestamp()
    rows = [r for r in _ROWS if r[1] == "NYSE_BOOK" or r[0] < cut]
    p = build_readout_payload(
        rows=rows, held_after={"LEVELONE_EQUITIES": ["SPY"], "NYSE_BOOK": ["SPY"]}
    )
    rd = p["readout"]["venues"]
    assert (rd["NYSE_BOOK"]["live"], rd["NASDAQ_BOOK"]["live"]) == (True, False)
    assert rd[e.COMPOSITE]["live"] is False
    readout, points = _replay(rows)
    last_nq = max(ts for ts, svc, _c in rows if svc == "NASDAQ_BOOK")
    own = e.readout_card(readout, points, {"NASDAQ_BOOK": last_nq})["venues"]["NASDAQ_BOOK"]
    on = e.readout_card(readout, points, {"NASDAQ_BOOK": _END})["venues"]["NASDAQ_BOOK"]
    assert rd["NASDAQ_BOOK"]["views"] == own["views"]
    assert own["views"]["weighted"]["held_sec"] < on["views"]["weighted"]["held_sec"]
    # the composite changed after NASDAQ_BOOK's last book: it is read to its own last change
    changed = [
        ts
        for (ts, r), (_t, q) in zip(points[1:], points, strict=False)
        if r[e.COMPOSITE] != q[e.COMPOSITE]
    ]
    assert int(changed[-1]) > int(last_nq)
    comp = e.readout_card(readout, points, {e.COMPOSITE: changed[-1]})["venues"][e.COMPOSITE]
    assert rd[e.COMPOSITE]["views"] == comp["views"]


def test_no_book_serves_no_number():
    p = build_readout_payload(rows=[])
    for got in p["readout"]["venues"].values():
        assert got["status"] == "no_book" and got["touch_pct"] is None
        assert all(v["pct"] is None for v in got["views"].values())
        assert got["no_number_text"] == "No book for this symbol right now"
        assert got["no_number_head"] == "NO BOOK"
        assert got["source_text"].endswith("no book for this symbol right now")


def test_a_one_sided_book_shows_the_side_it_has_and_no_percentage():
    """INDUCED: Schwab's NYSE_BOOK with its asks as Schwab sends a side it has no level for.

    That is an empty list.
    """
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    nyse["ASKS"] = []
    r = _readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": None})["NYSE_BOOK"]
    assert r["status"] == "one_sided"
    assert all(v["pct"] is None and v["ask_total"] is None for v in r["views"].values())
    assert r["views"]["5"]["bid_total"] == 800
    assert r["one_sided_text"] == "Only the bid side has levels in this book: no percentage."


def test_a_book_with_no_levels_says_so_in_words():
    """INDUCED: Schwab's NYSE_BOOK with both sides as Schwab sends a side it has no level for."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    nyse["BIDS"] = nyse["ASKS"] = []
    r = _readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": None})["NYSE_BOOK"]
    assert r["status"] == "empty"
    got = _served(_readout({"NYSE_BOOK": nyse, "NASDAQ_BOOK": None}))["NYSE_BOOK"]
    assert (got["no_number_head"], got["no_number_text"]) == (
        "NO LEVELS",
        "The book Schwab sent has no levels",
    )
    assert "the book Schwab sent has no levels" in got["source_text"]


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
    """Continuous trading runs through the closing auction window: the book's number stands.

    A line says the auction imbalance is a different number.
    """
    p = build_readout_payload(now=_CLOSE_AUCTION)
    assert p["readout"]["auction"] == "CLOSE"
    assert p["readout"]["auction_text"] == (
        "Closing auction window — auction imbalance is a different number, not shown here."
    )
    for got in p["readout"]["venues"].values():
        assert got["views"]["weighted"]["pct"] is not None and got["no_number_text"] is None


def test_the_opening_auction_line():
    """The route at 09:27 ET on 2026-11-25, inside Schwab's opening window's five minutes."""
    p = build_readout_payload(now=datetime.fromisoformat("2026-11-25T09:27:00-05:00").timestamp())
    assert p["readout"]["auction"] == "OPEN"
    assert p["readout"]["auction_text"] == (
        "Opening auction window — auction imbalance is a different number, not shown here."
    )
    assert p["readout"]["venues"][e.COMPOSITE]["views"]["weighted"]["pct"] is not None


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
    # INDUCED: those crossed books with NASDAQ_BOOK's NSDQ rows sent without their quote time,
    # read inside the closing auction after the feed went down: five of the card's added lines at
    # once (crossed, BOOK OFFLINE, the auction line, the not-live words, the dedup note)
    "liquidity_readout_every_line.json": {
        "now": _CLOSE_AUCTION,
        "feed_down": True,
        "rows": [
            (ts, svc, _rows_without(c, "SEQUENCE", "NSDQ") if svc == "NASDAQ_BOOK" else c)
            for ts, svc, c in _CROSSED
        ],
    },
}


def write_readout_e2e_fixtures() -> None:
    """Regeneration utility (never called by a test).

    Schwab's /markets answers held as the tests hold them (tests/conftest.py), then each route
    payload written to its e2e fixture.
    """
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
