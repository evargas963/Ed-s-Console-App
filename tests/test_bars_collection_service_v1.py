"""RC-69: bar collection is a SERVICE, and price_bars_1m has exactly ONE writer.

Bars used to be persisted only inside `_fetch_state` — the render path — so a ticker's chart
decayed to whenever it was last looked at. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag
3.1 min vs QQQ 19.1 and IWM 19.1 (off screen), while all three had ~1.0 min SNAPSHOT lag. The
quotes were current; the bars were not. 39.8% of snapshots (122,795/308,796) carry unfilled
outcomes because fill_outcomes reads price_bars_1m for the forward price and it was never written.

These lock the architecture, not the symptom: collection independent of the viewport, and a
single faucet for the bars table.
"""
from __future__ import annotations

import ast
from pathlib import Path

SERVER_PATH = Path(__file__).resolve().parent.parent / "server.py"
SERVER_SRC = SERVER_PATH.read_text(encoding="utf-8")
SERVER_TREE = ast.parse(SERVER_SRC)


def _fn_src(name: str) -> str:
    for node in ast.walk(SERVER_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SERVER_SRC, node) or ""
    raise AssertionError(f"{name} not found in server.py")


def test_price_bars_has_exactly_one_writer():
    """THE single-faucet contract. A second writer is how collection drifted into the render
    path in the first place."""
    n = SERVER_SRC.count("upsert_1m_bars(")
    assert n == 1, (
        f"price_bars_1m has {n} writers in server.py; RC-69 requires exactly ONE "
        f"(the bar collection service). A render path must never persist bars."
    )


def test_the_one_writer_lives_in_the_collection_service():
    seg = _fn_src("_bars_collect_one")
    assert "upsert_1m_bars(" in seg, "the single bar writer must be the collection service"


def test_render_path_does_not_persist_bars():
    """_fetch_state may tick the accumulator for its own forming candle, but must not WRITE."""
    seg = _fn_src("_fetch_state")
    assert "upsert_1m_bars(" not in seg, (
        "RC-69 regression: the render path persists bars again, so collection is once more a "
        "side-effect of what the operator happens to be looking at"
    )


def test_collection_covers_the_whole_enrolled_universe_not_a_fixed_list():
    """The loop must read the live enrolled set. A hardcoded tuple is how bars ended up covering
    3 of 57 tickers."""
    seg = _fn_src("_bars_loop")
    assert "_logger_tickers" in seg, "bar collection must iterate the enrolled universe"
    assert "BASE_MONEY_PATH_TICKERS" not in seg, "bar collection must not be sentinel-scoped"


def test_collection_is_session_gated_and_never_ticks_a_closed_market():
    """RC-48: a market-closed tick would persist a frozen bar and bias every study built on it."""
    seg = _fn_src("_bars_loop")
    assert "_is_loggable_session()" in seg


def test_collect_one_treats_a_missing_price_as_absence():
    """Absence must read as absence — never a fabricated tick into the bar series."""
    seg = _fn_src("_bars_collect_one")
    assert "skip:no_price" in seg
    assert "never raises" in seg.lower() or "except Exception" in seg


def test_loop_refuses_to_start_under_pytest():
    """A production collection thread inside the test process mutates shared state no test
    controls — the RC-5 failure class."""
    seg = _fn_src("start_bars_loop")
    assert "PYTEST_CURRENT_TEST" in seg


def test_loop_is_wired_into_the_app_lifespan():
    assert "start_bars_loop()" in SERVER_SRC, "collection service is never started"
    assert "stop_bars_loop()" in SERVER_SRC, "collection service is never stopped on shutdown"
