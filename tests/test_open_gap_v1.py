"""The open-gap record, EXPERIMENTAL (operator 2026-11-15; docs/derived_register.md).

Real data: TSLA's Schwab /pricehistory answer of series 5m365 (5-minute bars with extended
hours) as production recorded it on 2026-11-15 (tests/fixtures/real_tsla_5m365_answer_2026_11_
15.json). The expected counts were computed outside this code, by the study of the open run on
production's record the same day (TSLA: 84 of 138 opens), and the interval is Wilson's formula
worked by hand below.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import server
from open_gap import open_gap_record, wilson

TSLA = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_5m365_answer_2026_11_15.json").read_text(
        encoding="utf-8"
    )
)


def test_the_record_counts_the_opens_the_gap_called_as_the_study_did():
    record = open_gap_record(TSLA["candles"])
    assert (record.opens, record.matched) == (138, 84)
    assert (record.first_day, record.last_day) == (date(2026, 4, 30), date(2026, 11, 13))
    p, n, z = 84 / 138, 138, 1.959964
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert (record.low, record.high) == (centre - half, centre + half)
    assert wilson(84, 138) == (record.low, record.high)


def test_no_counted_open_is_no_record():
    """The pre-market alone (no 09:30 bar, no prior session) counts no open: absent, never 0."""
    pre = [c for c in TSLA["candles"][:40]]
    assert open_gap_record(pre) is None


def test_the_console_keeps_the_record_from_the_daily_answer_and_serves_it_experimental():
    msg = {
        "src": "schwab_pricehistory",
        "symbol": "TSLA",
        "series": "5m365",
        "ts_recv": 1794800399.0,
        "answer": {"candles": TSLA["candles"]},
    }
    server._open_gap.pop("TSLA", None)
    try:
        assert server.open_gap("TSLA")["line"] == "-"
        assert server._write_price_history(msg) == "TSLA"
        assert server._write_price_history(msg) is None  # the same answer again changes nothing
        assert ("TSLA", "5m365") not in server._series  # its candles are not held
        served = server.open_gap("TSLA")
    finally:
        server._open_gap.pop("TSLA", None)
    assert served["record"]["opens"] == 138 and served["record"]["matched"] == 84
    assert served["line"] == (
        "EXPERIMENTAL · the overnight gap pointed the way the first 5 minutes went on 84 of "
        "138 opens (61%; 95% 53%-69%), Apr 30 to Nov 13"
    )
    assert server.PAGE_PANELS["opengap"]
