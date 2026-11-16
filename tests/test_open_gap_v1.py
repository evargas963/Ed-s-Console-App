"""The open-gap record, EXPERIMENTAL (operator 2026-11-15; docs/derived_register.md).

Real data: TSLA's two Schwab /pricehistory answers of 2026-11-15, 5-minute bars a year back, the
regular session alone (5m365r) and with extended hours (5m365), as production recorded them
(tests/fixtures/real_tsla_5m365_answers_2026_11_15.json). Schwab's regular series marks each
day's session (AGENTS.md rule 8): its first bar of every one of its 180 days is 09:30 ET. The
expected counts were worked outside this code: the study of the open on production's record the
same day counted 84 of 138 from 04-30 with the session typed; Schwab's regular series also holds
04-28, so 04-29 counts too, and matched: 85 of 139. The interval is Wilson's formula, worked by
hand below.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import server
from open_gap import open_gap_record, wilson

TSLA = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_5m365_answers_2026_11_15.json").read_text(
        encoding="utf-8"
    )
)


def test_the_record_counts_the_opens_the_gap_called_from_schwabs_own_sessions():
    record = open_gap_record(TSLA["regular"], TSLA["extended"])
    assert (record.opens, record.matched) == (139, 85)
    assert (record.first_day, record.last_day) == (date(2026, 4, 29), date(2026, 11, 13))
    p, n, z = 85 / 139, 139, 1.959964
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert (record.low, record.high) == (centre - half, centre + half)
    assert wilson(85, 139) == (record.low, record.high)


def test_no_counted_open_is_no_record():
    """Without the extended-hours bars there is no pre-market, so no gap: absent, never 0."""
    assert open_gap_record(TSLA["regular"], []) is None


def test_the_console_keeps_the_record_once_both_answers_are_in_and_serves_it_experimental():
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
        assert server.open_gap("TSLA")["records"] == []  # absent until both answers arrive
        assert server._write_price_history(answer("5m365", TSLA["extended"])) is None
        assert server.open_gap("TSLA")["records"] == []  # one answer is not the record
        assert server._write_price_history(answer("5m365r", TSLA["regular"])) == "TSLA"
        assert server._write_price_history(answer("5m365r", TSLA["regular"])) is None  # same
        assert ("TSLA", "5m365") not in server._series  # their candles are not held as series
        (served,) = server.open_gap("TSLA")["records"]
    finally:
        for key in [k for k in server._open_gap_answers if k[0] == "TSLA"]:
            del server._open_gap_answers[key]
        server._open_gap.pop("TSLA", None)
    assert served["opens"] == 139 and served["matched"] == 85
    assert served["line"] == (
        "EXPERIMENTAL · the overnight gap pointed the way the first 5 minutes went on 85 of "
        "139 opens (61%; 95% 53%-69%), Apr 29 to Nov 13"
    )
    assert server.PAGE_PANELS["opengap"]
