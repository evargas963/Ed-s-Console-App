"""The shared Schwab socket's option budget, and what happens when the socket dies.

MEASURED 2026-09-23 (stream_capture.db): holding ~850-5,200 additional LEVELONE_OPTIONS
contracts on the ONE Schwab socket that also carries LEVELONE_EQUITIES killed the whole
socket 42 times in one session (SPY live-price gaps up to 1,341 s); on 9/15, with 10 option
subscriptions, there were 0 recycles and no SPY gap over 24 s. Each death was then
compounded: subscribe bisection kept running on the dead socket and stamped 3,223 healthy
contracts "rejected: no close frame". And the console served a 20 s REST refresh as
spot_source=streaming_plane / live. These tests lock each repair at its real seam.
"""
from __future__ import annotations

import asyncio
import sys
import time

import pytest

import app.market_data.schwab.streaming.capture as rsc
import live_market_plane as L
import stream_spine
from stream_spine import OPTION_CONTRACTS_MAX_HELD, prioritize_option_contracts


def _sym(root: str, exp: str, cp: str, strike: float) -> str:
    return f"{root:<6}{exp}{cp}{int(round(strike * 1000)):08d}"


# ── the shared budget and its ranking ───────────────────────────────────────────────────

def test_budget_admits_nearest_expiry_then_nearest_the_money_first():
    near = [_sym("SPY", "260924", "C", k) for k in range(700, 841)]      # 141 strikes, centre 770
    far = [_sym("SPY", "261030", "P", k) for k in range(700, 841)]
    admitted, over = prioritize_option_contracts(near + far, budget=150)
    assert len(admitted) == 150 and len(over) == 132
    assert set(near) <= set(admitted), "the nearest expiry fills the budget first"
    far_in = [s for s in admitted if "261030" in s]
    strikes = sorted(int(s[-8:]) / 1000 for s in far_in)
    assert strikes and max(abs(k - 770) for k in strikes) <= 5, (
        "within an expiry, contracts closest to the middle of the request win")


def test_budget_ranking_is_deterministic_and_order_free():
    syms = [_sym("SPY", "260924", "C", k) for k in range(600, 900)]
    a1, _ = prioritize_option_contracts(syms, budget=40)
    a2, _ = prioritize_option_contracts(list(reversed(syms)), budget=40)
    assert a1 == a2


def test_budget_default_is_the_measured_constant_and_below_the_dying_load():
    assert OPTION_CONTRACTS_MAX_HELD < 850, (
        "~850 held contracts still killed the socket every 4-20 min on 2026-09-23")
    admitted, over = prioritize_option_contracts([_sym("SPY", "260924", "C", k)
                                                  for k in range(1000)])
    assert len(admitted) == OPTION_CONTRACTS_MAX_HELD
    assert len(over) == 1000 - OPTION_CONTRACTS_MAX_HELD


# ── the daemon enforces the budget and reports the rest honestly ────────────────────────

class _Stream:
    def __init__(self, die_after: int | None = None):
        self.calls: list[tuple[str, int]] = []
        self.held: set[str] = set()
        self._die_after = die_after

    async def _op(self, name, syms):
        self.calls.append((name, len(syms)))
        if self._die_after is not None and len(self.calls) > self._die_after:
            raise ConnectionError("no close frame received or sent")

    async def level_one_option_subs(self, syms):
        await self._op("subs", syms)
        self.held |= set(syms)

    async def level_one_option_add(self, syms):
        await self._op("add", syms)
        self.held |= set(syms)

    async def level_one_option_unsubs(self, syms):
        await self._op("unsubs", syms)
        self.held -= set(syms)

    async def options_book_subs(self, syms):
        await self._op("book_subs", syms)

    async def options_book_unsubs(self, syms):
        await self._op("book_unsubs", syms)


def _apply(stream, rejected, monkeypatch, symbols):
    monkeypatch.setattr(rsc, "read_active_option_contract_signal", lambda: None)
    monkeypatch.setattr(rsc, "read_active_option_contracts_signal", lambda: list(symbols))
    state: dict = {}
    return asyncio.run(rsc._apply_active_option_contract_subs(
        stream, state, rejected_state=rejected, rejection_backoff={}))


def test_daemon_holds_at_most_the_budget_and_marks_the_rest_not_admitted(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 50)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 820)]
    stream, rejected = _Stream(), {}
    _apply(stream, rejected, monkeypatch, syms)
    assert len(stream.held) == 50
    over = {s for s, why in rejected.items() if why == rsc.OPTION_OVER_BUDGET_REASON}
    assert len(over) == len(syms) - 50 and not (over & stream.held)
    assert all("not admitted" in rejected[s] for s in over), (
        "a capacity decision must never read as a vendor rejection")


def test_over_budget_marks_clear_when_the_request_shrinks(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 10)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 730)]
    rejected: dict = {}
    _apply(_Stream(), rejected, monkeypatch, syms)
    assert sum(v == rsc.OPTION_OVER_BUDGET_REASON for v in rejected.values()) == 20
    _apply(_Stream(), rejected, monkeypatch, syms[:5])
    assert not any(v == rsc.OPTION_OVER_BUDGET_REASON for v in rejected.values())


# ── a dead socket stops the subscribe at once: no false rejections, one recycle ─────────

def test_connection_death_is_recognised():
    class ConnectionClosedError(Exception):
        pass
    assert rsc._is_connection_death(ConnectionClosedError("x"))
    assert rsc._is_connection_death(RuntimeError("received 1009 (message too big)"))
    assert rsc._is_connection_death(RuntimeError("no close frame received or sent"))
    assert not rsc._is_connection_death(RuntimeError("symbol not entitled"))


def test_socket_death_mid_subscribe_raises_once_and_rejects_nothing(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 100_000)
    monkeypatch.setattr(rsc, "OPTION_SUBSCRIBE_MAX_BATCH_SYMBOLS", 10)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 760)]      # 6 chunks
    stream, rejected = _Stream(die_after=2), {}
    with pytest.raises(rsc.OptionStreamConnectionLost):
        _apply(stream, rejected, monkeypatch, syms)
    assert len(stream.calls) == 3, "no further chunk and no bisection after the socket died"
    assert not rejected, "a dead socket must not stamp healthy contracts rejected"


def test_connection_lost_takes_the_existing_recycle_path():
    assert issubclass(rsc.OptionStreamConnectionLost, rsc.OptionCoverageCompensationError), (
        "the poll loop's one escalation for this class requests a stream recycle")


def test_a_genuinely_refused_symbol_is_still_bisected_and_rejected():
    refused = _sym("SPY", "260924", "C", 999)

    async def op(symbols):
        if refused in symbols:
            raise RuntimeError("vendor refused one symbol")

    good = [_sym("SPY", "260924", "C", k) for k in range(700, 707)]
    admitted: list = []
    rej = asyncio.run(rsc._batch_subscribe_with_bisection(
        op, good + [refused], on_admitted=admitted.extend))
    assert [s for s, _ in rej] == [refused] and sorted(admitted) == sorted(good)


# ── the console: honest spot identity, budgeted demand ─────────────────────────────────

def _row(ingestion, age_sec):
    return {"spot": 700.42, "server_received_ts": time.time() - age_sec,
            "exchange_quote_ts": time.time() - age_sec,
            "quote_source_detail": {"spot": "LAST_PRICE"}, "quote_ingestion": ingestion}


def _no_rest(monkeypatch, server):
    monkeypatch.setattr(server, "_spot_from_quote", lambda _tk: (None, None))


def test_rest_written_plane_row_is_labelled_rest_not_streaming(monkeypatch):
    import server
    _no_rest(monkeypatch, server)
    tk = "ZZRESTROW"
    L._by_ticker[tk] = _row("rest_anchor_lane_refresher", 1.0)
    try:
        spot, source, _ = server.resolve_spot(tk)
        assert spot == 700.42 and source == server.SPOT_SOURCE_QUOTE
        assert source != server.SPOT_SOURCE_PLANE
    finally:
        L._by_ticker.pop(tk, None)


def test_streamed_plane_row_keeps_streaming_identity(monkeypatch):
    import server
    _no_rest(monkeypatch, server)
    tk = "ZZSTREAMROW"
    L._by_ticker[tk] = _row("schwab_streaming_level_one", 1.0)
    try:
        _, source, _ = server.resolve_spot(tk)
        assert source == server.SPOT_SOURCE_PLANE
        assert server.current_spot_state(source, tk) == "live"
    finally:
        L._by_ticker.pop(tk, None)


def test_a_stale_rest_row_is_never_promoted_to_spot(monkeypatch):
    import server
    _no_rest(monkeypatch, server)
    tk = "ZZSTALEREST"
    L._by_ticker[tk] = _row("rest_anchor_lane_refresher", L.PLANE_QUOTE_STALE_SEC + 30)
    try:
        spot, source, _ = server.resolve_spot(tk)
        assert spot is None and source == "none"
    finally:
        L._by_ticker.pop(tk, None)


def test_console_publishes_only_the_budget_and_reports_the_rest(monkeypatch, tmp_path):
    import app.options.order_flow.streaming as st
    written: list = []
    monkeypatch.setattr(st, "write_active_option_contracts_signal", lambda syms: written.append(list(syms)))
    monkeypatch.setattr(st, "_active_option_contracts", [])
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 700 + OPTION_CONTRACTS_MAX_HELD + 37)]
    assert st.set_active_option_contracts(syms) is True
    assert len(written[-1]) == OPTION_CONTRACTS_MAX_HELD
    state = st.get_option_contracts_budget_state()
    assert state == {"admitted_count": OPTION_CONTRACTS_MAX_HELD, "over_budget_count": 37,
                     "budget": OPTION_CONTRACTS_MAX_HELD}


# ── the daemon's own output is recorded when it runs windowless ─────────────────────────

def test_windowless_daemon_output_goes_to_a_timestamped_log(monkeypatch, tmp_path):
    import runtime_layout
    monkeypatch.setattr(runtime_layout, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = rsc._ensure_daemon_output_is_recorded()
    print("stream: socket closed (no close frame)")
    sys.stdout.flush()
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "stream_capture.log"
    assert "socket closed" in text and text[:4].isdigit(), "each line carries its wall time"


def test_a_console_run_keeps_its_console(monkeypatch):
    assert sys.stdout is not None
    assert rsc._ensure_daemon_output_is_recorded() is None


def test_shared_budget_is_one_constant():
    assert rsc.OPTION_CONTRACTS_MAX_HELD is stream_spine.OPTION_CONTRACTS_MAX_HELD


def test_admission_summary_reports_over_budget_contracts_as_not_admitted(monkeypatch):
    import server
    import app.options.order_flow.streaming as st
    sym = _sym("SPY", "260924", "C", 900)
    monkeypatch.setattr(st, "_option_contracts_over_budget", [sym])
    out = server._option_contract_admission_summary("SPY")
    assert out["not_admitted"] == [sym], "the heatmap must be able to say why the cell has no stream"
    assert sym not in out["pending"] and sym not in out["rejected"]
