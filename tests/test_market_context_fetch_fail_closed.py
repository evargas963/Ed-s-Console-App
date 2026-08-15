"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations

import inspect
from pathlib import Path

from market_context import fetch_market_context, fetch_price_levels

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _MockQuoteResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _quote_fn(*, fail: frozenset[str] = frozenset(), prices: dict[str, float] | None = None):
    """Minimal safe_get_quote stub: fail-closed per symbol."""

    def _quote(_client, sym: str):
        if sym in fail:
            raise RuntimeError(f"{sym} unavailable")
        if prices and sym in prices:
            return _MockQuoteResponse({sym: {"quote": {"lastPrice": prices[sym]}}})
        return _MockQuoteResponse({})

    return _quote


def test_fetch_market_context_quote_failure_returns_partial_context() -> None:
    def _fail_quote(_client, _sym):
        raise RuntimeError("quote unavailable")

    ctx = fetch_market_context(None, _fail_quote)
    assert ctx.vix is None
    assert ctx.vxn is None
    assert ctx.rvx is None
    assert ctx.spy_last is None
    assert ctx.error


def test_extract_quote_returns_none_on_bad_payload() -> None:
    from market_context import _extract_quote

    last, pct = _extract_quote("SPY", {"SPY": {"quote": {}}})
    assert last is None
    assert pct is None


def test_fetch_price_levels_uses_rth_open_mins_authority() -> None:
    """FIND-MC-1: market_context.fetch_price_levels imports time_et RTH authority
    (RTH_OPEN_MINS / RTH_END_MINS) rather than inlining RTH_OPEN_HOUR / RTH_OPEN_MIN /
    RTH_CLOSE_HOUR. 5th consumer of the time_et minute-of-day authority after
    order_flow_live_state (STACK-WIRE-5 FIND-WIRE5-1)."""
    src = inspect.getsource(fetch_price_levels)
    assert "RTH_OPEN_HOUR" not in src
    assert "RTH_OPEN_MIN " not in src
    assert "RTH_CLOSE_HOUR" not in src
    assert "9 * 60 + 30" not in src
    assert "RTH_OPEN_MINS" in src
    assert "RTH_END_MINS" in src


def test_prior_day_family_single_session_dual_faucet_agreement(monkeypatch) -> None:
    """RC-213 seam test (mission levels-faucet-v1): drives BOTH real producers of the
    prior-day family on the same two-prior-session tape and asserts they agree on the
    SINGLE most recent prior RTH session — the multi-session union answer is dead.

    Tape: Thu 2026-07-30 holds BOTH extremes (high 110 / low 90), Fri 2026-07-31 is the
    most recent prior session (high 105 / low 95, close 102). The pre-fix defect merged
    both days, so any union value (110 / 90) appearing is the regression."""
    from datetime import datetime as _dt

    from liquidity_value_engine import PlaybookConfig, get_previous_day_levels
    from time_et import ET
    import market_context as mc

    def _ms(y, mo, d, h, mi):
        return _dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000.0

    def _candle(ts_ms, o, h, lo, c, v=1000.0):
        return {"datetime": ts_ms, "open": o, "high": h, "low": lo, "close": c, "volume": v}

    candles = [
        # Thursday 2026-07-30 (older prior session — holds BOTH extremes)
        _candle(_ms(2026, 7, 30, 10, 0), 100, 110, 90, 100),
        _candle(_ms(2026, 7, 30, 14, 0), 100, 101, 99, 100),
        # Friday 2026-07-31 (most recent prior RTH session)
        _candle(_ms(2026, 7, 31, 10, 0), 96, 105, 95, 97),
        _candle(_ms(2026, 7, 31, 15, 59), 101, 103, 100, 102),
        # "today" 2026-08-03
        _candle(_ms(2026, 8, 3, 9, 45), 103, 104, 102, 103),
    ]

    class _HistClient:
        def get_price_history(self, symbol, **kw):
            return _MockQuoteResponse({"candles": candles})

    monkeypatch.setattr(mc, "now_et", lambda: _dt(2026, 8, 3, 10, 0, tzinfo=ET), raising=False)
    # fetch_price_levels imports now_et from time_et inside the function body:
    import time_et as te
    real_now_et = te.now_et
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 3, 10, 0, tzinfo=ET))
    try:
        # Quote closePrice 999.0 proves the RC-213 PDC reconciliation: bar-basis wins.
        quote_raw = {"SPY": {"quote": {"closePrice": 999.0}}}
        pl = mc.fetch_price_levels(_HistClient(), "SPY", quote_raw=quote_raw)
    finally:
        monkeypatch.setattr(te, "now_et", real_now_et)

    engine_bars = [
        {"timestamp": c["datetime"] / 1000.0, "open": c["open"], "high": c["high"],
         "low": c["low"], "close": c["close"], "volume": c["volume"]}
        for c in candles
    ]
    eng = get_previous_day_levels(engine_bars, _dt(2026, 8, 3).date(), PlaybookConfig())

    # Agreement across the former dual faucets, level by level:
    assert pl.pdh == eng["pdh"] == 105, (pl.pdh, eng.get("pdh"))
    assert pl.pdl == eng["pdl"] == 95, (pl.pdl, eng.get("pdl"))
    assert pl.pdc == eng["pdc"] == 102, (pl.pdc, eng.get("pdc"))
    # The union answers are DEAD: 110/90 belong to the merged-session defect.
    assert pl.pdh != 110 and pl.pdl != 90
    # Quote closePrice did not override the bar-basis PDC.
    assert pl.pdc != 999.0


def test_fetch_price_levels_window_delegates_to_rc153_authority() -> None:
    """RC-213 lock: the prior-day window in fetch_price_levels comes from the RC-153
    authority (prior_trading_session_date) — reintroducing an inline multi-session
    sweep is the regression this string lock screams on."""
    src = inspect.getsource(fetch_price_levels)
    assert "prior_trading_session_date" in src, (
        "fetch_price_levels no longer delegates its prior-day window to the RC-153 "
        "authority — the dual-faucet defect (RC-213) is reopening"
    )


def test_fetch_market_context_vol_indices_all_present() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(prices={"$VIX": 18.5, "$VXN": 22.1, "$RVX": 24.3}),
    )
    assert ctx.vix == 18.5
    assert ctx.vxn == 22.1
    assert ctx.rvx == 24.3
    assert ctx.vix_regime != "—"


def test_fetch_market_context_vxn_failure_vix_unchanged() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(fail=frozenset({"$VXN"}), prices={"$VIX": 17.0, "$RVX": 23.0}),
    )
    assert ctx.vix == 17.0
    assert ctx.vxn is None
    assert ctx.rvx == 23.0


def test_fetch_market_context_rvx_failure_vix_unchanged() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(fail=frozenset({"$RVX"}), prices={"$VIX": 16.0, "$VXN": 21.0}),
    )
    assert ctx.vix == 16.0
    assert ctx.vxn == 21.0
    assert ctx.rvx is None


def test_fetch_market_context_missing_vol_index_leaves_none_no_exception() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(prices={"$VIX": 15.0}),
    )
    assert ctx.vix == 15.0
    assert ctx.vxn is None
    assert ctx.rvx is None


def test_vol_index_lane_v1_no_consumer_wiring() -> None:
    """Negative scope: V1 lane must not wire ctx.vxn/ctx.rvx into money-path consumers."""
    refs = ("ctx.vxn", "ctx.rvx", "mkt_ctx.vxn", "mkt_ctx.rvx", "native_vol_")
    forbidden = (
        "market_state.py",
        "server.py",
        "signal_types.py",
        "volatility_regime.py",
        "signals.py",
        "call_engine.py",
        "static/index.html",
    )
    for rel in forbidden:
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        for ref in refs:
            assert ref not in src, f"{rel} must not reference {ref} in V1 lane"


def test_signalinput_vix_still_macro_vix_only() -> None:
    """SignalInput vix stays macro $VIX only. Post VOL_INPUT_CONTRACT 1.0.0 the
    stamp routes through the per-cycle context (whose market_iv_level IS the
    macro $VIX quote), with mkt_ctx.vix as the vol_ctx=None fallback — the
    macro-only intent of this lock is unchanged; no native VXN/RVX routing."""
    from market_state import build_market_state

    src = inspect.getsource(build_market_state)
    assert "vix_level=(vol_ctx.market_iv_level if vol_ctx is not None else mkt_ctx.vix)" in src
    assert "vxn_level" not in src
    assert "rvx_level" not in src


# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — per-cycle context + stamp parity ────

import ast as _ast
import dataclasses as _dc
from pathlib import Path as _Path

import pytest as _pytest

from market_state import MarketVolContextV1, VOL_INPUT_CONTRACT_VERSION

_REPO = _Path(__file__).resolve().parent.parent


def test_vol_context_struct_contract():
    ctx = MarketVolContextV1(
        market_iv_level=26.0, market_iv_change=3.5,
        market_iv_direction="rising", quality_status="VALID", as_of_ts=1.0,
    )
    assert ctx.contract_version == VOL_INPUT_CONTRACT_VERSION == "1.0.0"
    assert ctx.route_identity == "live"
    assert ctx.source_symbol == "$VIX"
    with _pytest.raises(_dc.FrozenInstanceError):
        ctx.market_iv_level = 30.0  # type: ignore[misc]


def test_vol_context_absence_is_explicit_not_directional():
    ctx = MarketVolContextV1(
        market_iv_level=None, market_iv_change=None,
        market_iv_direction=None, quality_status="UNAVAILABLE",
    )
    assert ctx.market_iv_change is None      # never 0
    assert ctx.market_iv_direction is None   # never "flat" by default


def test_single_tracker_tick_site_lock():
    """Exactly ONE _vix_tracker.tick site may exist in server.py — the
    per-cycle vol-context computation. Extra per-surface ticks re-tick the
    same value and force direction to flat (pre-fix defect class)."""
    server_src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert server_src.count("_vix_tracker.tick(") == 1


def test_three_surfaces_consume_the_one_context():
    """SignalInput stamp, snapshot row, and ms_dict must all read
    vol_ctx.market_iv_* — no surface recomputes vs-prev or re-reads the
    tracker independently (MSD-001 route parity by construction)."""
    server_src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    ms_src = (_REPO / "market_state.py").read_text(encoding="utf-8", errors="replace")
    assert 'ms_dict["vix"] = vol_ctx.market_iv_level' in server_src
    assert 'ms_dict["vix_direction"] = vol_ctx.market_iv_direction' in server_src
    assert 'ms_dict["vix_vs_prev"] = vol_ctx.market_iv_change' in server_src
    assert "_vix_vs_prev = vol_ctx.market_iv_change" in server_src   # snapshot row
    assert "vix_level=vol_ctx.market_iv_level" in server_src         # snapshot row
    assert "vol_ctx=vol_ctx" in server_src                           # build_market_state call
    assert "vix_vs_prev=(vol_ctx.market_iv_change if vol_ctx is not None else None)" in ms_src
    assert "vix_direction=(vol_ctx.market_iv_direction if vol_ctx is not None else None)" in ms_src
    # [REAL-GATE:VOL-CTX-SINGLE-SOURCE] closure lock: zero raw mkt_ctx.vix
    # attribute reads outside the canonical conversion site. server.py may
    # read mkt_ctx.vix exactly ONCE (the float() conversion feeding vol_ctx);
    # market_state.py exactly TWICE, both as the ratified vol_ctx=None
    # rollback fallbacks (vix_level stamp + vix_bucket source).
    def _raw_vix_reads(src: str) -> list[int]:
        tree = _ast.parse(src)
        return sorted(
            n.lineno for n in _ast.walk(tree)
            if isinstance(n, _ast.Attribute) and n.attr == "vix"
            and isinstance(n.value, _ast.Name) and n.value.id == "mkt_ctx"
        )
    server_reads = _raw_vix_reads(server_src)
    assert len(server_reads) == 1, (
        f"raw mkt_ctx.vix reads in server.py at {server_reads} — only the "
        f"canonical vol_ctx conversion site may read the raw quote"
    )
    ms_reads = _raw_vix_reads(ms_src)
    assert len(ms_reads) == 2, (
        f"raw mkt_ctx.vix reads in market_state.py at {ms_reads} — only the "
        f"two vol_ctx=None rollback fallbacks may read the raw quote"
    )
    ms_lines = ms_src.splitlines()
    for ln in ms_reads:
        assert "vol_ctx is not None else mkt_ctx.vix" in ms_lines[ln - 1], (
            f"market_state.py:{ln} raw read is not a vol_ctx=None fallback"
        )


def test_vol_context_bound_outside_any_try():
    """vol_ctx must be bound unconditionally in _fetch_state — never inside a
    try whose handler swallows and continues. Caught 2026-07-10: the binding
    lived inside the envelope/density/sector try (except Exception:
    log.debug), so any swallowed exception there left vol_ctx unbound and the
    later build_market_state(vol_ctx=vol_ctx) call died with NameError."""
    tree = _ast.parse((_REPO / "server.py").read_text(encoding="utf-8", errors="replace"))
    parents: dict[_ast.AST, _ast.AST] = {}
    for node in _ast.walk(tree):
        for child in _ast.iter_child_nodes(node):
            parents[child] = node
    bindings = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Name) and n.id == "vol_ctx" and isinstance(n.ctx, _ast.Store)
    ]
    assert len(bindings) == 1, f"expected exactly one vol_ctx binding, got {len(bindings)}"
    cur: _ast.AST = bindings[0]
    enclosing: list[str] = []
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (_ast.Try, _ast.If, _ast.For, _ast.While)):
            enclosing.append(f"{type(cur).__name__}@{cur.lineno}")
    assert enclosing == [], (
        f"vol_ctx binding is conditional/swallowable (inside {enclosing}) — "
        f"it must execute on every path that reaches its consumers"
    )


def test_canonical_signal_input_construction_lock():
    """Money-path SignalInput construction happens only in the two canonical
    builders (market_state live stamp; replay builder). Production code must
    not bypass the vol boundary with an independent SignalInput(...)."""
    allowed = {"market_state.py", "features/replay_signal_input_v1.py", "signal_types.py"}
    offenders: list[str] = []
    for path in _REPO.glob("*.py"):
        rel = path.name
        if rel in allowed or rel.startswith("test_"):
            continue
        tree = _ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, _ast.Name) else (
                    fn.attr if isinstance(fn, _ast.Attribute) else ""
                )
                if name == "SignalInput":
                    offenders.append(f"{rel}:{node.lineno}")
    fdir = _REPO / "features"
    for path in fdir.glob("*.py"):
        rel = f"features/{path.name}"
        if rel in allowed:
            continue
        tree = _ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, _ast.Name) else (
                    fn.attr if isinstance(fn, _ast.Attribute) else ""
                )
                if name == "SignalInput":
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"SignalInput constructed outside canonical builders: {offenders}"
