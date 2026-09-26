"""RC-69: bar collection is a SERVICE, and price_bars_1m has exactly ONE writer.

Bars used to be persisted only inside `_fetch_state` — the render path — so a ticker's chart
decayed to whenever it was last looked at. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag
3.1 min vs QQQ 19.1 and IWM 19.1 (off screen), while all three had ~1.0 min SNAPSHOT lag. The
quotes were current; the bars were not. 39.8% of snapshots (122,795/308,796) carry unfilled
outcomes because fill_outcomes reads price_bars_1m for the forward price and it was never written.

These lock the architecture, not the symptom: collection independent of the viewport, and a
single faucet for the bars table. Since the bars-from-the-stream change the ONLY producer is
Schwab's streamed CHART_EQUITY 1-minute bar (capture daemon -> `bar1m.SYM` push ->
`streamed_bars` -> `_bar_writer` -> `_write_streamed_bar` -> `_persist_1m_bars`); the REST quote
poll and the price-history seeds that used to write here are deleted.
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


def _call_sites(name: str) -> set[str]:
    """Names of the server.py functions that call `name(...)` directly."""
    out: set[str] = set()
    for node in ast.walk(SERVER_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == name):
                    out.add(node.name)
    return out


def test_the_one_writer_is_the_single_faucet_and_the_stream_is_its_only_producer():
    """RC-69 single faucet: the ONE ``upsert_1m_bars(`` call lives in ``_persist_1m_bars``, whose
    only caller is the streamed-bar writer. That write seam also carries the RC-183 collect-window
    law (tests/test_collect_window_law_v1.py), so a closed-market bar is never persisted."""
    assert "upsert_1m_bars(" in _fn_src("_persist_1m_bars"),         "the single bar writer must be _persist_1m_bars"
    assert _call_sites("_persist_1m_bars") == {"_write_streamed_bar"}, (
        "price_bars_1m has a producer other than Schwab's streamed bars: "
        f"{sorted(_call_sites('_persist_1m_bars'))}")
    assert _call_sites("_write_streamed_bar") == {"_bar_writer"}
    assert "streamed_bars.get()" in _fn_src("_bar_writer")




def test_collection_covers_every_streamed_symbol_not_a_fixed_list(monkeypatch):
    """The writer persists whatever symbol the stream delivers -- no roster, sentinel or viewport
    filter. A hardcoded tuple is how bars once covered 3 of 57 tickers."""
    import server as srv

    written: list[tuple] = []
    monkeypatch.setattr(srv, "_persist_1m_bars", lambda tk, bars: written.append((tk, bars)) or 1)
    for sym in ("ZZA", "ZZB", "QQQ"):
        assert srv._write_streamed_bar({"symbol": sym, "open": 10.0, "high": 11.0, "low": 9.5,
                                        "close": 10.5, "volume": 1200.0,
                                        "bar_start_ms": 1_785_168_000_000}) is True
    assert [tk for tk, _ in written] == ["ZZA", "ZZB", "QQQ"]
    bar = written[0][1][0]
    assert (bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        1_785_168_000.0, 10.0, 11.0, 9.5, 10.5, 1200.0), "ms bar start must land as epoch seconds"


def test_a_streamed_bar_missing_a_field_is_absence_not_a_bar(monkeypatch):
    """Absence must read as absence -- a bar with no open/high/low/close/start is not written,
    never completed from anything else."""
    import server as srv

    written: list = []
    monkeypatch.setattr(srv, "_persist_1m_bars", lambda tk, bars: written.append(tk) or 1)
    full = {"symbol": "ZZG", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
            "volume": 5.0, "bar_start_ms": 1_785_168_000_000}
    for k in ("open", "high", "low", "close", "bar_start_ms"):
        msg = dict(full)
        msg[k] = None
        assert srv._write_streamed_bar(msg) is False, f"a bar without {k} was written"
    assert written == []
    # positive control: the complete bar IS written, so the guard is not refusing everything
    assert srv._write_streamed_bar(full) is True and written == ["ZZG"]


def test_writer_refuses_to_start_under_pytest():
    """A production writer thread inside the test process mutates shared state no test
    controls — the RC-5 failure class."""
    seg = _fn_src("start_bar_writer")
    assert "PYTEST_CURRENT_TEST" in seg


def test_writer_is_wired_into_the_app_lifespan():
    assert _call_sites("start_bar_writer") == {"_app_lifespan"}, (
        f"the bar writer is not started by the app lifespan: {sorted(_call_sites('start_bar_writer'))}")
