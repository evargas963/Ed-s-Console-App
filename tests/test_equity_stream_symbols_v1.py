"""Every symbol a screen shows a live price for is streamed on request.

The capture daemon has no built-in symbol list (operator 2026-09-23: universality). With spot
= streamed LAST_PRICE only (no REST fallback), a symbol nobody asked the daemon to stream
would read UNAVAILABLE forever. The console now ranks the symbols it shows (active
ticker, watchlist, gamma board), writes them to stream_equity_symbols.json, and the daemon
ADDs/UNSUBSes LEVELONE_EQUITIES to match.
"""
from __future__ import annotations

import asyncio

import pytest

import app.options.order_flow.streaming as ofs
import stream_spine
from app.market_data.schwab.streaming import capture


# ── console: ranking ──────────────────────────────────────────────────────────────────

def test_ranking_is_active_then_watchlist_then_board_each_once():
    admitted, not_admitted = ofs.rank_equity_symbols(
        "tsla", {"watchlist": ["AAPL", "TSLA", "spy"], "board": ["NVDA", "AAPL", "SPX"]}, budget=10)
    assert admitted == ["TSLA", "AAPL", "SPY", "NVDA", "$SPX"]
    assert not_admitted == {}


def test_everything_past_the_budget_is_named_never_silently_cut():
    admitted, not_admitted = ofs.rank_equity_symbols(
        "TSLA", {"watchlist": ["AAPL", "MSFT"], "board": ["NVDA", "AMD"]}, budget=3)
    assert admitted == ["TSLA", "AAPL", "MSFT"]
    assert set(not_admitted) == {"NVDA", "AMD"}
    assert all("outside the live equity budget (3)" in r for r in not_admitted.values())


def test_declare_writes_the_ranked_list_for_the_daemon(monkeypatch):
    written = []
    monkeypatch.setattr(ofs, "write_equity_symbols_signal", lambda syms: written.append(list(syms)))
    monkeypatch.setattr(ofs, "_active_ticker", "TSLA")
    monkeypatch.setattr(ofs, "_equity_demand", {"watchlist": [], "board": []})
    monkeypatch.setattr(ofs, "_equity_last_written", None)
    ofs.declare_equity_symbols("watchlist", ["AAPL", "MSFT"])
    ofs.declare_equity_symbols("board", ["SPY", "NVDA"])
    ofs.declare_equity_symbols("board", ["NVDA", "SPY"])          # same set: no rewrite
    assert written == [["TSLA", "AAPL", "MSFT"], ["TSLA", "AAPL", "MSFT", "SPY", "NVDA"]]
    with pytest.raises(ValueError):
        ofs.declare_equity_symbols("nonsense", ["X"])


def test_the_signal_round_trips_through_the_file(tmp_path):
    p = tmp_path / "stream_equity_symbols.json"
    stream_spine.write_equity_symbols_signal(["tsla", "AAPL", ""], path=p)
    assert stream_spine.read_equity_symbols_signal(path=p) == ["AAPL", "TSLA"]
    p.write_text("[1, 2", encoding="utf-8")
    assert stream_spine.read_equity_symbols_signal(path=p) == []      # malformed: none


# ── daemon: add/drop to match ─────────────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, fail_add=False):
        self.calls = []
        self.fail_add = fail_add

    async def level_one_equity_add(self, syms):
        if self.fail_add:
            raise RuntimeError("vendor said no")
        self.calls.append(("add", list(syms)))

    async def level_one_equity_unsubs(self, syms):
        self.calls.append(("unsubs", list(syms)))

    async def chart_equity_add(self, syms):
        self.calls.append(("chart_add", list(syms)))

    async def chart_equity_unsubs(self, syms):
        self.calls.append(("chart_unsubs", list(syms)))


def _apply(monkeypatch, requested, held, stream, roster=("BOOT1", "BOOT2")):
    monkeypatch.setattr(capture, "read_equity_symbols_signal", lambda: list(requested))
    status: dict = {}
    out = asyncio.run(capture._apply_equity_symbol_subs(stream, list(roster), frozenset(held), status))
    return out, status


def test_daemon_adds_new_symbols_and_skips_its_boot_set(monkeypatch):
    st = _FakeStream()
    held, status = _apply(monkeypatch, ["AAPL", "BOOT1", "TSLA"], set(), st)
    assert held == {"AAPL", "TSLA"}
    assert st.calls == [("add", ["AAPL", "TSLA"]), ("chart_add", ["AAPL", "TSLA"])]
    assert status == {"refused": None, "held": ["AAPL", "TSLA"]}


def test_daemon_unsubs_what_the_console_dropped(monkeypatch):
    st = _FakeStream()
    held, _ = _apply(monkeypatch, ["TSLA"], {"AAPL", "TSLA"}, st)
    assert held == {"TSLA"}
    assert st.calls == [("unsubs", ["AAPL"]), ("chart_unsubs", ["AAPL"])]


def test_a_vendor_error_leaves_held_as_it_truly_is(monkeypatch):
    held, _ = _apply(monkeypatch, ["AAPL"], set(), _FakeStream(fail_add=True))
    assert held == frozenset(), "an ADD that failed is not held -- the next tick retries it"


def test_an_over_budget_request_is_refused_whole(monkeypatch):
    monkeypatch.setattr(capture, "EQUITY_SYMBOLS_MAX_HELD", 2)
    st = _FakeStream()
    held, status = _apply(monkeypatch, ["A1", "A2", "A3"], {"A1"}, st)
    assert held == frozenset()
    assert st.calls == [("unsubs", ["A1"]), ("chart_unsubs", ["A1"])]
    assert "exceeds the equity budget (2)" in status["refused"]


# ── route ─────────────────────────────────────────────────────────────────────────────

def test_watchlist_route_declares_and_names_the_unstreamed(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    seen = {}

    def _declare(kind, syms):
        seen[kind] = syms
        return {"ZZZ": "not streamed: outside the live equity budget (150)"}
    monkeypatch.setattr(ofs, "declare_equity_symbols", _declare)
    client = TestClient(server.app)
    r = client.post("/api/streaming/watchlist-symbols", json={"symbols": ["AAPL", "ZZZ"]})
    assert r.status_code == 200
    assert seen == {"watchlist": ["AAPL", "ZZZ"]}
    assert r.json()["not_streamed"] == {"ZZZ": "not streamed: outside the live equity budget (150)"}
    assert client.post("/api/streaming/watchlist-symbols", json={"symbols": "AAPL"}).status_code == 400


def test_the_daemon_has_no_built_in_symbol_list(monkeypatch):
    """Universality (operator 2026-09-23): no ticker is streamed by default; every symbol
    arrives the same way, by console request."""
    import sys

    seen = {}

    async def _run(syms, dur):
        seen["syms"] = syms
        return 0
    monkeypatch.setattr(sys, "argv", ["capture"])
    monkeypatch.setattr(capture, "run", _run)
    assert capture.main() == 0
    assert seen["syms"] == []
