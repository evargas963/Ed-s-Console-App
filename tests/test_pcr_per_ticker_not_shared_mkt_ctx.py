"""No-fallback lock repair (2026-09-18, PR #254 point 2): "MarketContext is not a
coherent immutable observation. A newer PCR value can be written into an older cached
MarketContext while retaining the older timestamp and generation."

Root cause traced to server.py's per-ticker request loop: `pcr_val` is computed from
THIS TICKER's own option-chain totals (totals[0].pcr_oi) but was written onto the
shared, cached MarketContext object (`mkt_ctx.pcr = pcr_val` / `_cached_mkt_ctx.pcr =
pcr`) -- the exact object server.py's own comment says holds data "IDENTICAL
regardless of which ticker we're processing". Whichever ticker's request cycle ran
last within the cache TTL silently overwrote every other ticker's displayed PCR, and
the object's (timestamp, generation) never changed to reflect the mutation.

Fixed by removing pcr/pcr_arrow/pcr_color/pcr_label from MarketContext entirely (it was
never legitimately shared data) and threading PCR through server.py -> build_market_state
as explicit per-ticker parameters, exactly like charm already flows. These tests prove
the fix structurally: the dead pcr/prev_pcr parameter chain is gone (not just unused),
MarketContext genuinely has no pcr fields, no source-level mutation site remains, and
the extracted pcr_trend() pure function reproduces the original trend-label behavior.
"""
from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_context import MarketContext, fetch_market_context, pcr_trend  # noqa: E402


def test_market_context_has_no_pcr_fields():
    names = {f.name for f in dataclasses.fields(MarketContext)}
    assert not (names & {"pcr", "pcr_arrow", "pcr_color", "pcr_label"}), (
        "PCR is per-ticker data (this ticker's own option-chain totals) and must "
        "never live on MarketContext, which every consumer treats as identical "
        "across all tickers"
    )


def test_fetch_market_context_no_longer_accepts_pcr():
    params = inspect.signature(fetch_market_context).parameters
    assert "pcr" not in params and "prev_pcr" not in params, (
        "the pcr/prev_pcr parameter chain was always None in the real server flow "
        "(fetch_market_context's only real caller never passed one) -- dead "
        "machinery that existed only to be bypassed by the mutation bug"
    )


def test_server_mkt_ctx_functions_no_longer_accept_pcr():
    import server as srv

    for fn in (
        srv._fetch_and_store_mkt_ctx,
        srv._mkt_ctx_background_refresh,
        srv._get_mkt_ctx,
        srv._ensure_mkt_ctx_confluence_complete,
    ):
        params = inspect.signature(fn).parameters
        assert "pcr" not in params and "prev_pcr" not in params, (
            f"{fn.__name__} must not accept pcr/prev_pcr -- PCR flows to "
            f"build_market_state directly, never through the shared mkt_ctx cache"
        )


def test_no_source_level_pcr_mutation_of_the_shared_cache():
    """Positive structural proof, not just an absent parameter: no line anywhere in
    server.py assigns into `.pcr` on a MarketContext-typed object."""
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    banned = ("_cached_mkt_ctx.pcr =", "mkt_ctx.pcr =", "mkt_ctx.pcr_arrow =")
    code_only = "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith("#")
    )
    for pattern in banned:
        assert pattern not in code_only, f"mutation of the shared cache reappeared: {pattern!r}"


def test_pcr_trend_reproduces_original_thresholds():
    assert pcr_trend(None, None) == ("→", "#9ca3af", "")
    assert pcr_trend(1.0, None) == ("→", "#9ca3af", "baseline")
    assert pcr_trend(1.10, 1.0) == ("↑", "#991b1b", "put pressure building")
    assert pcr_trend(0.90, 1.0) == ("↓", "#166534", "hedges unwinding")
    assert pcr_trend(1.02, 1.0) == ("→", "#92400e", "flat")


def test_pcr_trend_is_a_pure_function_of_its_two_arguments():
    """No hidden state, no shared-object mutation -- calling it twice with the same
    (pcr, prev_pcr) must be side-effect-free and deterministic, unlike the old
    in-place mutation of a cached object."""
    a = pcr_trend(1.2, 1.0)
    b = pcr_trend(1.2, 1.0)
    assert a == b
