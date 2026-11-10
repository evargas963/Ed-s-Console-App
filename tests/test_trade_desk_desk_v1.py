"""Trade Desk > Desk: the server contract it reads.

- the `bars` panel rolls 1m bars to the one global timeframe, 30m included, and serves up to
  12,000 1m rows.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import server as srv
import time_et
from tests.feed_live_helper import spy_minutes
from time_et import ET

ROOT = Path(__file__).resolve().parents[1]


def test_thirty_minute_rollup_is_first_open_max_high_min_low_last_close():
    hour = spy_minutes()[:60]
    out = srv.aggregate_bars(hour, "30")
    assert len(out) == 2
    first, second = out
    opening, next_half = hour[:30], hour[30:]
    assert (first["o"], first["h"], first["l"], first["c"], first["v"]) == (
        opening[0]["o"],
        max(m["h"] for m in opening),
        min(m["l"] for m in opening),
        opening[-1]["c"],
        sum(m["v"] for m in opening),
    )
    assert (second["o"], second["c"]) == (next_half[0]["o"], next_half[-1]["c"])
    assert second["t"] - first["t"] == 1800
    assert datetime.fromtimestamp(first["t"], ET).isoformat() == "2026-09-24T09:30:00-04:00"


def test_the_bars_panel_accepts_30m_and_twelve_thousand_rows_and_nothing_beyond():
    now = time_et.now()
    assert srv.bars("SPY", now, {"tf": "30", "limit": 12000})["tf"] == "30"
    with pytest.raises(ValueError, match="tf '31'"):
        srv.bars("SPY", now, {"tf": "31", "limit": 12000})
    with pytest.raises(ValueError, match="limit 12001"):
        srv.bars("SPY", now, {"tf": "30", "limit": 12001})


def test_equity_microstructure_serves_the_engines_tick_rule_flow_labelled_proxy():
    flow = srv.book("SPY", time_et.now(), {"venue": "NYSE_BOOK"})["flow"]
    assert set(flow) >= {
        "tape_pressure_30s",
        "tape_pressure_2m",
        "tape_pressure_5m",
        "cum_delta_proxy",
    }
    assert flow["classification"]["tape_pressure_5m"] == "PROXY"
    assert flow["native_aggressor_available"] is False


def test_every_shipped_page_script_parses():
    """Every script the console serves must parse.

    Measured 2026-09-25: a Python-side edit un-escaped an apostrophe inside a single-quoted JS
    string in ed-trade-desk-map.js -- a syntax error that would have stopped the whole Desk page
    from loading, and no Python test noticed. Every script the console serves must parse.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for js in sorted((ROOT / "static" / "js").glob("*.js")):
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{js.name}: {r.stderr[:400]}"
