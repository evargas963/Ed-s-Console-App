"""The open-gap record, EXPERIMENTAL, as the operator's approved mock-up shows it (2026-11-15).

Real data: TSLA's two Schwab /pricehistory answers of 2026-11-15, 5-minute bars a year back, the
regular session alone (5m365r) and with extended hours (5m365), as production recorded them
(tests/fixtures/real_tsla_5m365_answers_2026_11_15.json). Schwab's regular series marks each
day's session (AGENTS.md rule 8): its first bar of every one of its 180 days is 09:30 ET.

The expected values were worked outside this code, by a script of their own over production's
record the same day (the mock-up's numbers): 85 of 139 opens called; up gaps followed 43 of 74,
down gaps 42 of 65; the last 10 opens below. The interval is Wilson's formula, worked by hand.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import server
from micro_structure import Candle
from open_gap import open_gap_record, today_open, wilson
from tests.page_on_socket import pages
from time_et import ET, session

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


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def test_the_record_splits_the_opens_by_the_gaps_direction():
    record = open_gap_record(TSLA["regular"], TSLA["extended"])
    assert (len(record.opens), sum(o.called for o in record.opens)) == (139, 85)
    assert (record.opens[0].day, record.opens[-1].day) == (date(2026, 4, 29), date(2026, 11, 13))
    assert (record.up.opens, record.up.matched) == (74, 43)
    assert (record.down.opens, record.down.matched) == (65, 42)
    p, n, z = 43 / 74, 74, 1.959964
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert (record.up.low, record.up.high) == (centre - half, centre + half)
    assert wilson(42, 65) == (record.down.low, record.down.high)


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
    assert today_open(candles, today, prior, _et("2026-10-07 09:40")) == recorded
    assert today_open(candles, today, prior, _et("2026-10-07 09:33")) is None, "bar not closed"


def test_a_record_is_pushed_to_the_pages_showing_its_ticker_and_served_as_the_mock_up():
    def answer(series: str, candles: list) -> dict:
        return {
            "src": "schwab_pricehistory",
            "symbol": "TSLA",
            "series": series,
            "ts_recv": 1794806000.0,
            "answer": {"candles": candles},
        }

    for key in [k for k in server._open_gap_answers if k[0] == "TSLA"]:
        del server._open_gap_answers[key]
    server._open_gap.pop("TSLA", None)
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
        assert ("TSLA", "5m365") not in server._series  # their candles are not held as series
        weekend = server.experimental("TSLA", _et("2026-10-10 12:00"))
        before_open = server.experimental("TSLA", _et("2026-10-07 09:00"))
        spy = server.experimental("SPY", _et("2026-10-07 09:00"))
    finally:
        for key in [k for k in server._open_gap_answers if k[0] == "TSLA"]:
            del server._open_gap_answers[key]
        server._open_gap.pop("TSLA", None)
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
