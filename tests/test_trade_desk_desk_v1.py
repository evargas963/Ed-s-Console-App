"""Trade Desk > Desk: the server contract it reads.

  - /api/bars1m rolls 1m bars to the one global timeframe, now including 30m, and serves up to
    12,000 1m rows -- measured 2026-09-25 at ~400 banked SPY rows per session, so the old
    3,000 cap gave the D timeframe seven daily bars instead of the 20 sessions it shows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import server as srv

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")


def _bars(start: datetime, minutes: int) -> list[dict]:
    t0 = start.astimezone(timezone.utc).timestamp()
    return [{"t": t0 + 60 * i, "o": 100 + i, "h": 100.5 + i, "l": 99.5 + i, "c": 100.25 + i, "v": 10}
            for i in range(minutes)]


def test_thirty_minute_rollup_is_first_open_max_high_min_low_last_close():
    out = srv.aggregate_bars(_bars(datetime(2026, 9, 25, 9, 30, tzinfo=ET), 60), "30")
    assert len(out) == 2
    first, second = out
    assert (first["o"], first["h"], first["l"], first["c"], first["v"]) == (100, 129.5, 99.5, 129.25, 300)
    assert (second["o"], second["c"]) == (130, 159.25)
    assert second["t"] - first["t"] == 1800


def test_bars_route_accepts_30m_and_twelve_thousand_rows_and_nothing_beyond():
    client = TestClient(srv.app)
    ok = client.get("/api/bars1m", params={"ticker": "SPY", "tf": "30", "limit": 12000})
    assert ok.status_code == 200, ok.text
    assert ok.json()["tf"] == "30"
    assert client.get("/api/bars1m", params={"ticker": "SPY", "tf": "31"}).status_code == 422
    assert client.get("/api/bars1m", params={"ticker": "SPY", "limit": 12001}).status_code == 422


def test_market_context_indices_are_always_requested_and_subscribed():
    """Measured 2026-09-25: SPX/NDX/VIX read "—" all session on a page whose watchlist did not
    hold them -- nobody asked the daemon to stream them. They are standing demand now, ranked
    right after the active ticker."""
    from app.options.order_flow import streaming as ofs
    assert ofs.MARKET_CONTEXT_SYMBOLS == ("$SPX", "$NDX", "$VIX")
    assert ofs._equity_demand["context"] == list(ofs.MARKET_CONTEXT_SYMBOLS)
    admitted, _ = ofs.rank_equity_symbols("NVDA", {**ofs._equity_demand, "watchlist": ["AAPL"]})
    assert admitted[:5] == ["NVDA", "$SPX", "$NDX", "$VIX", "AAPL"]


def test_equity_microstructure_serves_the_engines_tick_rule_flow_labelled_proxy():
    client = TestClient(srv.app)
    d = client.get("/api/order-flow/microstructure", params={"ticker": "SPY"}).json()
    flow = d["flow"]
    assert set(flow) >= {"tape_pressure_30s", "tape_pressure_2m", "tape_pressure_5m", "cum_delta_proxy"}
    assert flow["classification"]["tape_pressure_5m"] == "PROXY"
    assert flow["native_aggressor_available"] is False


def test_every_shipped_page_script_parses():
    """Measured 2026-09-25: a Python-side edit un-escaped an apostrophe inside a single-quoted
    JS string in ed-trade-desk-map.js -- a syntax error that would have stopped the whole Desk
    page from loading, and no Python test noticed. Every script the console serves must parse."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for js in sorted((ROOT / "static" / "js").glob("*.js")):
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{js.name}: {r.stderr[:400]}"
