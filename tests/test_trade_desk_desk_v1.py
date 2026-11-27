"""Trade Desk > Desk: the server contract it reads.

- the `bars` panel rolls 1m bars to the one global timeframe, 30m included, and serves up to
  12,000 1m rows.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from calc.micro_structure import Candle
from push import bars as push_bars
from tests.feed_live_helper import RTH_INSTANT, spy_minutes
from time_et import ET

ROOT = Path(__file__).resolve().parents[1]
#: Schwab's own AMD candles of one thin half hour, each series as sent (its `source` says where
#: they were read)
_THIN = json.loads(
    (
        ROOT / "tests" / "fixtures" / "real_amd_pricehistory_thin_half_hour_2026_11_11.json"
    ).read_text(encoding="utf-8")
)["candles"]


def _thin_bars(series: str) -> list[Candle]:
    """Schwab's candles of `series` in that half hour, each as the chart holds a bar."""
    return [
        Candle(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
        for c in _THIN[series]
    ]


def test_thirty_minute_rollup_is_first_open_max_high_min_low_last_close():
    hour = spy_minutes()[:60]
    out = push_bars.aggregate_bars(hour, "30")
    assert len(out) == 2
    first, second = out
    opening, next_half = hour[:30], hour[30:]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        opening[0].open,
        max(m.high for m in opening),
        min(m.low for m in opening),
        opening[-1].close,
        sum(m.volume for m in opening),
    )
    assert (second.open, second.close) == (next_half[0].open, next_half[-1].close)
    assert second.ts - first.ts == 1800
    assert datetime.fromtimestamp(first.ts, ET).isoformat() == "2026-09-24T09:30:00-04:00"


@pytest.mark.parametrize("tf", ["5", "15", "30"])
def test_a_rolled_up_bar_carries_its_steps_start_as_schwabs_own_bar_does(tf):
    """A bar rolled up from 1-minute bars is stamped as Schwab stamps its own bar of that step.

    AMD, Wednesday 2026-11-11, the half hour from 05:30 ET (real_amd_pricehistory_thin_half_hour):
    no trade printed in the minute of 05:30, so Schwab's first 1-minute candle is 05:31, and its
    own 5-, 15- and 30-minute bars of that step are stamped 05:30. The roll-up of the 1-minute
    candles has Schwab's bars at Schwab's times, with its open, high, low and close; the VWAP
    curve's rows are stamped the same (here each minute's close stands for its value: only the
    times are read).
    """
    minutes, own = _thin_bars("1m"), _thin_bars(push_bars.SCHWAB_SERIES[tf])
    assert datetime.fromtimestamp(own[0].ts, ET).strftime("%H:%M") == "05:30"
    assert minutes[0].ts - own[0].ts == 60  # the step's first minute has no candle
    rolled = push_bars.aggregate_bars(minutes, tf)
    assert [b.ts for b in rolled] == [b.ts for b in own]
    assert [(b.open, b.high, b.low, b.close) for b in rolled] == [
        (b.open, b.high, b.low, b.close) for b in own
    ]
    curve = push_bars.aggregate_vwap([[m.ts, m.close] for m in minutes], tf)
    assert [row[0] for row in curve] == [b.ts for b in own]


def test_the_bars_panel_accepts_30m_and_twelve_thousand_rows_and_nothing_beyond():
    now = RTH_INSTANT
    assert push_bars.bars("SPY", now, {"tf": "30", "limit": 12000})["tf"] == "30"
    with pytest.raises(ValueError, match="tf '31'"):
        push_bars.bars("SPY", now, {"tf": "31", "limit": 12000})
    with pytest.raises(ValueError, match="limit 12001"):
        push_bars.bars("SPY", now, {"tf": "30", "limit": 12001})


def test_every_shipped_page_script_parses():
    """Every script the console serves must parse.

    Measured 2026-09-25: a Python-side edit un-escaped an apostrophe inside a single-quoted JS
    string in ed-trade-desk-map.js -- a syntax error that would have stopped the whole Desk page
    from loading, and no Python test noticed. Every script the console serves must parse.
    """
    node = shutil.which("node")
    assert node is not None, "Node parses the page's scripts; it is installed wherever tests run"
    for js in sorted((ROOT / "static" / "js").glob("*.js")):
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{js.name}: {r.stderr[:400]}"
