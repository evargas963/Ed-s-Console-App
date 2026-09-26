"""Every symbol a screen shows a live price for is streamed on request.

The capture daemon has no built-in symbol list (operator 2026-09-23: universality). With spot
= streamed LAST_PRICE only (no REST fallback), a symbol nobody asked the daemon to stream
would read UNAVAILABLE forever. The console now ranks the symbols it shows (active
ticker, watchlist, gamma board), writes them to stream_equity_symbols.json, and the daemon
ADDs/UNSUBSes LEVELONE_EQUITIES to match.
"""
from __future__ import annotations

import asyncio


import app.options.order_flow.streaming as ofs
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


