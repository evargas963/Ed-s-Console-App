"""Trade Desk > Desk (operator mockup, 2026-09-25): the server contract it reads, the vendored
chart engine it runs on, and the page wiring.

  - /api/bars1m rolls 1m bars to the one global timeframe, now including 30m, and serves up to
    12,000 1m rows -- measured 2026-09-25 at ~400 banked SPY rows per session, so the old
    3,000 cap gave the D timeframe seven daily bars instead of the 20 sessions it shows.
  - The chart engine is TradingView Lightweight Charts 5.2.1, vendored unmodified from the npm
    tarball whose sha512 matched the registry. Its Apache-2.0 license and the attribution link
    its README requires (attributionLogo) are held here so neither can silently drop.
  - Every endpoint the Desk calls is a real route, and the engine loads before the modules that
    use it.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import server as srv

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "static" / "vendor" / "lightweight-charts"
LWC = VENDOR / "lightweight-charts.standalone.production.js"
DESK_JS = ROOT / "static" / "js" / "ed-trade-desk-map.js"
CHART_JS = ROOT / "static" / "js" / "ed-tv-chart.js"
INDEX = ROOT / "static" / "index.html"
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


def test_vendored_chart_engine_is_the_verified_release_with_its_license():
    # sha256 of the file extracted from lightweight-charts-5.2.1.tgz (tarball sha512 matched npm)
    assert hashlib.sha256(LWC.read_bytes()).hexdigest() == \
        "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf"
    assert "Lightweight Charts™ v5.2.1" in LWC.read_text(encoding="utf-8")[:300]
    assert "Apache License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")


def test_every_chart_shows_the_tradingview_attribution_link():
    src = CHART_JS.read_text(encoding="utf-8")
    assert "attributionLogo: true" in src
    assert "attributionLogo: false" not in src


def test_engine_loads_before_the_modules_that_use_it():
    html = INDEX.read_text(encoding="utf-8")
    order = [html.index(s) for s in (
        "/static/vendor/lightweight-charts/lightweight-charts.standalone.production.js",
        "/static/js/ed-tv-chart.js",
        "/static/js/ed-trade-desk-map.js")]
    assert order == sorted(order)
    assert 'data-sub-pane="desk"' in html


def test_every_endpoint_the_desk_calls_is_a_served_route():
    called = set(re.findall(r"'(/api/[a-z0-9_/-]+)\?", DESK_JS.read_text(encoding="utf-8")))
    assert {"/api/bars1m", "/api/levels", "/api/terrain", "/api/level_crosses",
            "/api/order-flow/microstructure", "/api/analytics/state", "/api/liquidity-snapshot"} <= called
    served = {getattr(r, "path", None) for r in srv.app.routes}
    missing = sorted(called - served)
    assert not missing, missing


def test_desk_timeframes_are_the_ones_the_server_rolls():
    pattern = next(r for r in srv.app.routes if getattr(r, "path", None) == "/api/bars1m")
    src = DESK_JS.read_text(encoding="utf-8")
    tfs = re.findall(r"\{ id: '(\w+)', lbl: '[^']+' \}", src.split("var TFS", 1)[1].split(";", 1)[0])
    assert tfs == ["1", "5", "15", "30", "60", "D"]
    client = TestClient(srv.app)
    for tf in tfs:
        assert client.get(pattern.path, params={"ticker": "SPY", "tf": tf, "limit": 5}).status_code == 200, tf


def test_market_context_indices_are_always_requested_and_subscribed():
    """Measured 2026-09-25: SPX/NDX/VIX read "—" all session on a page whose watchlist did not
    hold them -- nobody asked the daemon to stream them. They are standing demand now, ranked
    right after the active ticker, and every page subscribes to them on the price socket."""
    from app.options.order_flow import streaming as ofs
    assert ofs.MARKET_CONTEXT_SYMBOLS == ("$SPX", "$NDX", "$VIX")
    assert ofs._equity_demand["context"] == list(ofs.MARKET_CONTEXT_SYMBOLS)
    admitted, _ = ofs.rank_equity_symbols("NVDA", {**ofs._equity_demand, "watchlist": ["AAPL"]})
    assert admitted[:5] == ["NVDA", "$SPX", "$NDX", "$VIX", "AAPL"]
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    page = re.search(r"var MARKET_CONTEXT = \[([^\]]*)\]", core).group(1)
    assert ["$" + s.strip().strip("'") for s in page.split(",")] == list(ofs.MARKET_CONTEXT_SYMBOLS)
    body = core.split("function priceSymbols()", 1)[1].split("function subscribePrices()", 1)[0]
    assert "MARKET_CONTEXT.forEach" in body, "the socket subscription must include the context"


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
