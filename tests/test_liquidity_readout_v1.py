"""The Desk Liquidity card's order-imbalance readout (engine.book_readout, engine.readout_card,
server.liquidity_readout), on Schwab's real books.

Books: SPY's NYSE_BOOK and NASDAQ_BOOK as sent on 2026-09-25 at 10:30 ET, one of each
(tests/fixtures/real_spy_nyse_nasdaq_books.json), and every SPY NYSE_BOOK and NASDAQ_BOOK message
Schwab sent on 2026-11-02 from 10:00:00 to 10:02:30 ET, in receive order
(tests/fixtures/real_spy_books_2026_11_02.json, read from production's stream_capture.db). The
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
#: 2026-11-02 10:02:30 ET, the end of the captured window: regular hours in Schwab's answer
_END = datetime.fromisoformat("2026-11-02T10:02:30-05:00").timestamp()
#: 2026-11-02 15:55 ET: inside the closing auction of a normal day
_CLOSE_AUCTION = datetime.fromisoformat("2026-11-02T15:55:00-05:00").timestamp()
_HELD = {"LEVELONE_EQUITIES": ["SPY"], "NYSE_BOOK": ["SPY"], "NASDAQ_BOOK": ["SPY"]}


def _pair_readout() -> dict:
    return e.book_readout({v: [b["content"]] for v, b in _PAIR.items()})


def _replay() -> tuple[dict, list]:
    """Every captured 2026-11-02 book through the readout, as the console's intake records it:
    the readout of the newest book of each venue at each receipt."""
    newest: dict = {v: [] for v in e.BOOK_VENUES}
    points = []
    for ts, svc, content in _ROWS:
        newest[svc] = [content]
        points.append((ts, e.lean_point(e.book_readout(newest))))
    return e.book_readout(newest), points


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
        [(1.0, e.lean_point(_pair_readout()))],
        {v: 2.0 for v in (*e.BOOK_VENUES, e.COMPOSITE)},
    )
    assert card["venues"]["NASDAQ_BOOK"]["views"]["weighted"]["divergence"] == (
        "Touch and deeper book disagree"
    )
    assert card["venues"]["NASDAQ_BOOK"]["views"]["5"]["divergence"] is None
    assert card["venues"]["NYSE_BOOK"]["views"]["weighted"]["divergence"] is None


# ── the composite: each exchange counted once ────────────────────────────────────────────────


def test_the_composite_counts_nasdaqs_quote_once_from_the_newer_book():
    """NSDQ's quote is in both books, at different prices: NYSE_BOOK (BOOK_TIME ...097) shows it
    at 767.39 x 80 bid and 767.41 x 120 ask, NASDAQ_BOOK (...528, newer) at 767.41 x 100 bid and
    767.42 x 70 ask. The composite takes the newer and leaves the older out; summing the books
    would count those 80 and 120 shares twice."""
    comp = _pair_readout()["COMPOSITE"]
    v5 = comp["views"]["5"]
    # bids 767.41 NSDQ 100, 767.39 ARCX 80 (NSDQ's 80 left out), 767.38 120, 767.37 120,
    # 767.36 360; asks 767.41 BATX 40 + ARCX 40 (NSDQ's 120 left out), 767.42 320 + NSDQ 70,
    # 767.43 1560, 767.44 40, 767.60 40
    assert (v5["bid_total"], v5["ask_total"]) == (780, 2110)
    assert v5["counted_twice"] == {"bid": 80, "ask": 120}
    # summing the two books' TOTAL_VOLUMEs at the composite's five prices counts NSDQ in both
    naive_bid = sum(
        lv["TOTAL_VOLUME"]
        for b in _PAIR.values()
        for lv in b["content"]["BIDS"]
        if lv["BID_PRICE"] in (767.41, 767.39, 767.38, 767.37, 767.36)
    )
    naive_ask = sum(
        lv["TOTAL_VOLUME"]
        for b in _PAIR.values()
        for lv in b["content"]["ASKS"]
        if lv["ASK_PRICE"] in (767.41, 767.42, 767.43, 767.44, 767.6)
    )
    assert (naive_bid, naive_ask) == (780 + 80, 2110 + 120)
    assert comp["books"] == ["NYSE_BOOK", "NASDAQ_BOOK"] and comp["dedup_partial"] is False
    assert comp["touch_state"] == "LOCKED"  # best bid 767.41 = best ask 767.41
    assert comp["book_time_ms"] == _PAIR["NYSE_BOOK"]["content"]["BOOK_TIME"]  # the older book
    assert comp["views"]["1"]["counted_twice"] == {"bid": 0, "ask": 120}


def test_a_level_without_per_exchange_rows_is_taken_whole_and_the_dedup_marked_partial():
    """A level as Schwab sent it, its own rows removed: its TOTAL_VOLUME is counted once, and the
    composite says its dedup is partial."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    del nyse["BIDS"][1]["BIDS"]  # 767.38: BATX 80 + NYSE 40, TOTAL_VOLUME 120
    comp = e.book_readout({"NYSE_BOOK": [nyse], "NASDAQ_BOOK": [_PAIR["NASDAQ_BOOK"]["content"]]})
    assert comp["COMPOSITE"]["dedup_partial"] is True
    assert comp["COMPOSITE"]["views"]["5"]["bid_total"] == 780


def test_an_exchange_code_matches_without_regard_to_case():
    """Schwab has spelled exchanges in lower case in NASDAQ_BOOK (TSLA's arcx, edgx and batx on
    2026-09-25, tests/fixtures/real_tsla_book_rows.json) where NYSE_BOOK spells them ARCX, EDGX,
    BATX. INDUCED: that real book, and the same book a millisecond older with its codes in upper
    case, as NYSE_BOOK spells them (no captured pair of the two spellings is held: none in
    2026-11-02's SPY or TSLA books): each exchange counted once."""
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
    comp = e.book_readout({"NYSE_BOOK": [as_nyse], "NASDAQ_BOOK": [newer]})["COMPOSITE"]
    one = e.book_readout({"NYSE_BOOK": [], "NASDAQ_BOOK": [newer]})["NASDAQ_BOOK"]
    assert comp["views"]["5"]["bid_total"] == one["views"]["5"]["bid_total"]
    assert comp["views"]["5"]["ask_total"] == one["views"]["5"]["ask_total"]


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
    assert e._zone(pct) == zone


def test_the_sentence_four_cases_from_the_flat_shares():
    """Schwab's own totals: NYSE_BOOK's top 1 (160 bid, 200 ask: 40 apart) and the composite's
    top five (780 bid, 2110 ask)."""
    assert e._sentence("BALANCED", 160, 160) == "Balanced — no shares needed to balance."
    assert e._sentence("BALANCED", 160, 200) == "Nearly balanced — 40 shares would even the book."
    assert e._sentence("OFFER_HEAVY", 780, 2110) == "To balance, market makers buy 1,330 shares."
    assert e._sentence("VERY_BID", 2110, 780) == "To balance, market makers sell 1,330 shares."
    assert e._sentence(None, 780, 2110) is None
    assert e._sentence("BID_HEAVY", 780, None) is None


# ── over time: smoothing, the zone's hold, flips, the lean windows ───────────────────────────


def test_a_zone_changes_only_after_it_has_stood_three_seconds():
    """One second across the line is not a change; three are, dated from the first of them."""
    assert e._dwelled([5, 5, 15, 5, 5], 100) == ("BALANCED", 100)
    assert e._dwelled([5, 5, 15, 15, 5], 100) == ("BALANCED", 100)
    assert e._dwelled([5, 5, 15, 15, 15, 15], 100) == ("BID_HEAVY", 102)
    assert e._dwelled([5, None, 5], 100) == ("BALANCED", 102)


def test_on_schwabs_books_every_zone_the_card_shows_stood_three_seconds():
    readout, points = _replay()
    last = int(points[-1][0])
    first = last - e.OF_LEAN_KEPT_SEC
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        for view in e.READOUT_VIEWS:
            sm = e._smoothed(e._standing(points, f"{v}|{view}", first, last))
            zone, since = e._dwelled(sm, first)
            assert zone is not None, (v, view)
            if since > first:  # a change inside the values kept: it stood its three seconds
                run = sm[since - first : since - first + e.OF_ZONE_DWELL_SEC]
                assert [e._zone(s) for s in run] == [zone] * e.OF_ZONE_DWELL_SEC, (v, view)


def test_the_headline_is_the_median_of_the_last_five_seconds():
    _readout, points = _replay()
    last = int(points[-1][0])
    vals = e._standing(points, "COMPOSITE|weighted", last - 10, last)
    sm = e._smoothed(vals)
    assert sm[-1] == pytest.approx(sorted(vals[-5:])[2])


def test_the_lean_windows_are_two_and_five_minutes_and_none_is_one():
    assert [(n, s) for n, s, _step in e.OF_LEAN_WINDOWS] == [("2m", 120), ("5m", 300)]
    readout, points = _replay()
    card = e.readout_card(readout, points, {v: points[-1][0] for v in readout})
    lean = card["venues"]["COMPOSITE"]["views"]["weighted"]["lean"]
    assert set(lean) == {"2m", "5m"}
    assert (len(lean["2m"]["values"]), len(lean["5m"]["values"])) == (121, 61)


def test_flips_count_the_sign_changes_of_the_smoothed_value_in_two_minutes():
    readout, points = _replay()
    last = int(points[-1][0])
    card = e.readout_card(readout, points, {v: points[-1][0] for v in readout})
    for v in (*e.BOOK_VENUES, e.COMPOSITE):
        w = card["venues"][v]["views"]["weighted"]
        kept = e._standing(points, f"{v}|weighted", last - e.OF_LEAN_KEPT_SEC, last)
        sm = e._smoothed(kept)[-121:]
        signs = [s > 0 for s in sm if s is not None and s != 0]
        assert w["flips_2m"] == sum(a != b for a, b in zip(signs, signs[1:], strict=False))
        assert w["flips_word"] == ("CHOPPY" if w["flips_2m"] >= 5 else "STEADY")


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


def test_no_book_serves_no_number():
    p = build_readout_payload(rows=[])
    for got in p["readout"]["venues"].values():
        assert got["status"] == "no_book" and got["touch_pct"] is None
        assert all(v["pct"] is None for v in got["views"].values())


def test_a_one_sided_book_shows_the_side_it_has_and_no_percentage():
    """Schwab's NYSE_BOOK with its asks as Schwab sends a side it has no level for (an empty
    list)."""
    nyse = json.loads(json.dumps(_PAIR["NYSE_BOOK"]["content"]))
    nyse["ASKS"] = []
    r = e.book_readout({"NYSE_BOOK": [nyse], "NASDAQ_BOOK": []})["NYSE_BOOK"]
    assert r["status"] == "one_sided"
    assert all(v["pct"] is None and v["ask_total"] is None for v in r["views"].values())
    assert r["views"]["5"]["bid_total"] == 800


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


def test_the_closing_auction_replaces_the_continuous_number():
    p = build_readout_payload(now=_CLOSE_AUCTION)
    assert p["readout"]["auction"] == "CLOSE"
    assert p["readout"]["auction_text"] == (
        "Auction — the continuous book number is replaced during the closing auction; auction"
        " imbalance is a different number"
    )


def test_the_intake_keeps_one_value_a_second_for_the_windows_and_no_longer():
    history.LEAN.forget("SPY")
    try:
        for ts, _svc, _c in _ROWS:
            history.LEAN.record("SPY", ts, {})
        kept = history.LEAN.points("SPY")
        assert len({int(t) for t, _v in kept}) == len(kept)
        assert kept[-1][0] - kept[0][0] <= e.OF_LEAN_KEPT_SEC
    finally:
        history.LEAN.forget("SPY")


# ── the browser tests' fixtures are the route's answers ──────────────────────────────────────

_E2E_FILES = {
    "liquidity_readout_live.json": {},
    "liquidity_readout_offline.json": {"feed_down": True},
    "liquidity_readout_no_book.json": {"rows": []},
    "liquidity_readout_close_auction.json": {"now": _CLOSE_AUCTION},
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
