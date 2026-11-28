"""The open-gap record, EXPERIMENTAL, as the operator's approved design shows it (2026-11-15).

Real data: TSLA's two Schwab /pricehistory answers of 2026-11-15, 5-minute bars a year back, the
regular session alone (5m365r) and with extended hours (5m365), as production recorded them
(tests/fixtures/real_tsla_5m365_answers_2026_11_15.json). Schwab's regular series marks each
day's session (AGENTS.md rule 8): its first bar of every one of its 180 days is 09:30 ET.

The expected values were worked outside this code, by a script of their own over production's
record the same day (the design's numbers): 85 of 139 opens called; up gaps followed 43 of 74,
down gaps 42 of 65; the last 10 opens below. The interval is Wilson's formula, worked by hand.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import live_market_plane as lmp
import server
import time_et
from calc.liquidity_value_engine import wilson_interval
from calc.micro_structure import Candle
from open_gap import open_gap_record, today_open
from push import experimental as push_experimental
from state import bar_store
from tests.conftest import MARKETS_ANSWERS
from tests.page_on_socket import pages
from tests.shared_helpers import et_ts
from time_et import record_markets, session

TSLA = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_5m365_answers_2026_11_15.json").read_text(
        encoding="utf-8"
    )
)
#: TSLA's last 10 opens to 2026-11-13: (day, gap, first five, called), from the script above
LAST_10 = [
    ("Fri Nov 13", "▲ +1.10%", "▼ -1.11%", False),
    ("Thu Nov 12", "▼ -1.17%", "▲ +1.49%", False),
    ("Wed Nov 11", "▲ +1.80%", "▲ +1.14%", True),
    ("Tue Nov 10", "▼ -1.97%", "▲ +1.64%", False),
    ("Mon Nov 09", "▲ +0.52%", "▲ +2.06%", True),
    ("Fri Nov 06", "▲ +1.65%", "▼ -0.06%", False),
    ("Thu Nov 05", "▼ -2.94%", "▼ -2.37%", True),
    ("Wed Nov 04", "▼ -4.57%", "▼ -0.85%", True),
    ("Tue Nov 03", "▲ +0.60%", "▼ -0.94%", False),
    ("Mon Nov 02", "▲ +1.22%", "▲ +0.96%", True),
]


def test_the_record_splits_the_opens_by_the_gaps_direction():
    record = open_gap_record(TSLA["regular"], TSLA["extended"])
    assert (len(record.opens), sum(o.called for o in record.opens)) == (139, 85)
    assert (record.opens[0].day, record.opens[-1].day) == (date(2026, 4, 29), date(2026, 11, 13))
    assert (record.up.opens, record.up.matched) == (74, 43)
    assert (record.down.opens, record.down.matched) == (65, 42)
    p, n, z = 43 / 74, 74, 1.959963984540054  # the two-sided 95% normal quantile
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert (record.up.low, record.up.high) == (centre - half, centre + half)
    assert wilson_interval(42, 65) == (record.down.low, record.down.high)


def test_no_counted_open_is_no_record():
    """Without the extended-hours bars there is no pre-market, so no gap: absent, never 0."""
    assert open_gap_record(TSLA["regular"], []) is None


def test_today_s_open_from_schwab_s_bars_is_the_record_s_own_once_its_bar_has_closed():
    """2026-10-07, a day whose /markets answer tests/conftest.py holds, and 2026-10-06 before it.

    Schwab's 5-minute bars with extended hours as the console's `5m` series holds them: the open
    read from them equals the record's own for that day, and is absent until the bar has closed.
    """
    candles = [
        Candle(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
        for c in TSLA["extended"]
    ]
    today, prior = session("2026-10-07"), session("2026-10-06")
    (recorded,) = [
        o
        for o in open_gap_record(TSLA["regular"], TSLA["extended"]).opens
        if o.day == date(2026, 10, 7)
    ]
    assert today_open(candles, today, prior, et_ts("2026-10-07 09:40")) == recorded
    assert today_open(candles, today, prior, et_ts("2026-10-07 09:33")) is None, "bar not closed"


def answer(series: str, candles: list) -> dict:
    """TSLA's /pricehistory answer of `series` as the daemon publishes it."""
    return {
        "src": "schwab_pricehistory",
        "symbol": "TSLA",
        "series": series,
        "ts_recv": 1794806000.0,
        "answer": {"candles": candles},
    }


def _forget_tsla() -> None:
    for key in [k for k in bar_store._open_gap_answers if k[0] == "TSLA"]:
        del bar_store._open_gap_answers[key]
    bar_store._open_gap.pop("TSLA", None)
    bar_store._series.pop(("TSLA", "5m"), None)


#: the Trade Desk's Experimental view's browser fixture: the panel as the server answers it
E2E_EXPERIMENTAL = Path(__file__).parent / "e2e" / "fixtures" / "experimental_tsla.json"


def experimental_after_the_open() -> dict:
    """TSLA's Experimental panel at 2026-10-07 09:40 ET: its record and its open's bar closed."""
    _forget_tsla()
    try:
        server._write_price_history(answer("5m365", TSLA["extended"]))
        server._write_price_history(answer("5m365r", TSLA["regular"]))
        bar_store.put_series(
            "TSLA",
            "5m",
            [
                Candle(
                    c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"]
                )
                for c in TSLA["extended"]
            ],
        )
        return push_experimental.experimental("TSLA", et_ts("2026-10-07 09:40"))
    finally:
        _forget_tsla()


def write_experimental_e2e() -> None:
    """Regeneration utility (never called by a test).

    python -c "import tests.conftest, tests.test_open_gap_v1 as t; t.write_experimental_e2e()"

    Schwab's /markets answers held as the tests hold them (tests/conftest.py) first.
    """
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            record_markets(json.loads(a["body"]))
    body = {"type": "experimental", **experimental_after_the_open()}
    E2E_EXPERIMENTAL.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", "utf-8")


def test_the_browser_tests_experimental_panel_is_the_producers_own():
    stored = json.loads(E2E_EXPERIMENTAL.read_text(encoding="utf-8"))
    assert stored == {"type": "experimental", **experimental_after_the_open()}, (
        "the browser test's file drifted from the server; regenerate with write_experimental_e2e()"
    )
    assert stored["today"]["gap_text"] == "▼ -0.58%" and len(stored["records"]) == 1


def test_a_record_is_pushed_to_the_pages_showing_its_ticker_and_served_as_designed():
    _forget_tsla()
    try:
        with pages() as on_socket:
            page = on_socket.open("TSLA", "experimental")
            other = on_socket.open("SPY", "experimental")
            assert server._write_price_history(answer("5m365", TSLA["extended"])) is None
            assert on_socket.told(page) == set(), "one answer is not the record"
            assert server._write_price_history(answer("5m365r", TSLA["regular"])) is None
            assert on_socket.told(page, 0.5) == {"experimental"}, "the page is told at once"
            assert on_socket.told(other) == set(), "a page showing another ticker is not"
            assert server._write_price_history(answer("5m365r", TSLA["regular"])) is None
            assert on_socket.told(page, 0.2) == set(), "the same answer again tells nothing"
        assert ("TSLA", "5m365") not in bar_store._series  # their candles are not held as series
        weekend = push_experimental.experimental("TSLA", et_ts("2026-10-10 12:00"))
        before_open = push_experimental.experimental("TSLA", et_ts("2026-10-07 09:00"))
        spy = push_experimental.experimental("SPY", et_ts("2026-10-07 09:00"))
    finally:
        _forget_tsla()
    assert server.PAGE_PANELS["experimental"]
    assert weekend["today"]["when_text"] == "no regular session today in Schwab's market hours"
    assert before_open["today"]["label"] == "Today's gap · before the open"
    (rec,) = before_open["records"]
    # no gap yet today: up gaps first, down gaps for reference
    assert (rec["main"]["share_text"], rec["main"]["count_text"]) == ("58%", "43 of 74 opens")
    assert rec["main"]["range_text"] == "95% range 47%-69%"
    (down,) = rec["others"]
    assert down["line"] == "Down gaps, for reference: down 42 of 65 (65%, range 52%-75%)"
    assert [
        (o["day_text"], o["gap_text"], o["five_text"], o["called"]) for o in rec["last"]
    ] == LAST_10
    assert rec["last_title"] == "Last 10 opens · the gap called 5 of 10"
    assert spy["records"] == [] and spy["ticker"] == "SPY"  # each ticker its own


def test_a_page_showing_the_tab_is_told_again_with_each_price_row_of_its_ticker():
    """Today's card is the live gap before the open and the open's bar after it.

    Both change with the ticker's price, not with the record, so a page left open is sent the
    tab again with each of its ticker's price rows (live_ui.on_row), as the levels are.
    """
    with pages() as on_socket:
        page = on_socket.open("TSLA", "experimental")
        other = on_socket.open("SPY", "experimental")
        on_socket.server.on_row("TSLA")
        assert on_socket.told(page) == {"experimental"}
        assert on_socket.told(other) == set(), "a page showing another ticker is not"


def test_today_s_card_before_the_open_is_schwabs_live_change_with_its_trade_time():
    """2026-11-11 before the open: TSLA's trades as Schwab streamed them.

    tests/fixtures/real_premarket_first_prints_2026_11_11.json, with /markets for that date as
    sent: the evening's last trade, then the day's first, 04:00:01 ET. The card is Schwab's
    NET_CHANGE_PERCENT as sent with the newest (1.71415, against the prior close) and that
    trade's time in Central Time.
    """
    sent = Path(__file__).parent / "fixtures" / "real_premarket_first_prints_2026_11_11.json"
    fx = json.loads(sent.read_text(encoding="utf-8"))
    taken = [m for m in fx["messages"] if m["ticker"] == "TSLA"]
    held = time_et.HELD.sessions
    try:
        record_markets(fx["markets"])
        for m in taken:
            lmp.record_from_level_one_equity("TSLA", m["item"], received_ts=m["ts_recv"])
        card = push_experimental.experimental("TSLA", et_ts("2026-11-11 08:00"))["today"]
    finally:
        time_et.HELD.sessions = held
        time_et.HELD.first_trade = {}
        lmp._by_ticker.pop("TSLA", None)
        lmp._fields_by_ticker.pop("TSLA", None)
    assert taken[-1]["item"]["NET_CHANGE_PERCENT"] == 1.71415
    assert card == {
        "label": "Today's gap · before the open",
        "gap_text": "▲ +1.71%",
        "gap_up": True,
        "when_text": "vs. prior close · Schwab, live · Wed 11/11 03:00 AM CT",
        "results": [],
    }


def test_today_s_card_after_the_open_waits_for_the_bar_then_serves_its_result():
    """2026-10-07, after 09:30 ET: Schwab's 5-minute bars as the console's `5m` series holds them.

    Until the 09:30 bar has closed the card says it waits; after, it serves the gap and the first
    five minutes the record holds for that day: a -0.58% gap, a +0.35% first five minutes.
    """
    candles = [
        Candle(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
        for c in TSLA["extended"]
    ]
    try:
        bar_store.put_series("TSLA", "5m", candles)
        waiting = push_experimental.experimental("TSLA", et_ts("2026-10-07 09:33"))
        closed = push_experimental.experimental("TSLA", et_ts("2026-10-07 09:40"))
    finally:
        bar_store._series.pop(("TSLA", "5m"), None)
    assert waiting["today"]["when_text"] == "waiting for Schwab's open bar to close"
    today = closed["today"]
    assert (today["gap_text"], today["gap_up"]) == ("▼ -0.58%", False)
    (result,) = today["results"]
    assert result["label"] == "Today 08:30 AM CT–08:35 AM CT"  # the 09:30 ET bar, as shown
    assert (result["five_text"], result["called"]) == ("▲ +0.35%", False)
    assert result["called_text"] == "✗ the gap pointed down, the open went up"
