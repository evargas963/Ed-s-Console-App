"""Contract tests: ticker_storage_key, anchor load, DB query normalization, pin_neutral repair."""
from __future__ import annotations


import server
from instrument_identity import ticker_storage_key
from tests.feed_live_helper import daemon_bars, stream_daemon_bars


def test_recorded_index_bars_are_held_and_served_under_the_index_key():
    """Schwab keys an index as "$SPX" (tests/fixtures/real_schwab_index_identity_2026_09_28.json:
    only the "$" form answers). Schwab's $SPX bars of 2026-10-01/02 as the capture daemon recorded
    them, streamed to the console: held under $SPX, and the bare "SPX" a page asks for serves
    exactly them (Issue 19 rehydration)."""
    rows = daemon_bars("real_daemon_bars_spy_tsla_spx_2026_10_01_02.json", "$SPX")
    newest = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        newest[r["bar_start_ms"]] = r
    server._bars.pop("$SPX", None)
    try:
        stream_daemon_bars(rows)
        held = [b for b in server._bars_1m("$SPX", server.BARS_KEPT) if b.ts * 1000 in newest]
        asked_bare = [b for b in server._bars_1m("spx", server.BARS_KEPT) if b.ts * 1000 in newest]
    finally:
        server._bars.pop("$SPX", None)
    want = [(ms / 1000, r["open"], r["high"], r["low"], r["close"], r["volume"]) for ms, r in sorted(newest.items())]
    assert [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in held] == want
    assert asked_bare == held




def test_ticker_storage_key_preserves_spx_prefix():
    assert ticker_storage_key("spy") == "SPY"
    assert ticker_storage_key("spx") == "$SPX"
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$spx") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    assert ticker_storage_key("  $spx  ") == "$SPX"
    assert ticker_storage_key("vix") == "$VIX"


def test_ticker_storage_key_vxn_rvx_broker_index_roots():
    """Vol-index lane V1: VXN/RVX bare roots map to broker $ prefix (same as VIX/SPX)."""
    assert ticker_storage_key("VXN") == "$VXN"
    assert ticker_storage_key("vxn") == "$VXN"
    assert ticker_storage_key("$VXN") == "$VXN"
    assert ticker_storage_key("RVX") == "$RVX"
    assert ticker_storage_key("rvx") == "$RVX"
    assert ticker_storage_key("$RVX") == "$RVX"
    assert ticker_storage_key("VIX") == "$VIX"
    assert ticker_storage_key("$VIX") == "$VIX"










# ── RC-126: levels for ALL tickers — the query boundary uses the ONE identity authority ─────

def test_index_roots_resolve_to_dollar_form():
    """Typing a bare index root anywhere must reach Schwab in its dollar form — $SPX stayed
    dark for a session because the endpoints skipped this authority."""
    from instrument_identity import ticker_storage_key
    for bare, dollar in (("SPX", "$SPX"), ("spx", "$SPX"), ("NDX", "$NDX"), ("rut", "$RUT"),
                         ("DJX", "$DJX"), ("XSP", "$XSP"), ("OEX", "$OEX"), ("VIX", "$VIX")):
        assert ticker_storage_key(bare) == dollar
    assert ticker_storage_key("SPY") == "SPY", "equities must pass through untouched"
    assert ticker_storage_key("$SPX") == "$SPX", "already-canonical must be idempotent"


def test_every_bare_index_root_is_what_schwab_names_an_index_with_dollar():
    """TICK-01 (2026-09-28 audit): the typed-shorthand list BROKER_INDEX_BARE_ROOTS is held to
    Schwab's own answer (tests/fixtures/real_schwab_index_identity_2026_09_28.json): Schwab
    names each index only with "$" (instruments symbol-search: assetType INDEX; quoted), knows
    no bare root, and no equity or ETF uses those letters -- so mapping a bare root to its "$"
    form never misroutes, and a root cannot join the list without Schwab's evidence."""
    import json
    from pathlib import Path

    from instrument_identity import BROKER_INDEX_BARE_ROOTS
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_schwab_index_identity_2026_09_28.json")
                    .read_text(encoding="utf-8"))
    search, quoted = fx["instruments_symbol_search"], fx["quotes_asset_main_type"]
    assert fx["bare_roots_quoted"] == []
    for root in BROKER_INDEX_BARE_ROOTS:
        assert search[root] == [], f"Schwab knows bare {root}"
        assert search["$" + root] == [["$" + root, "INDEX"]], root
        assert quoted["$" + root] == "INDEX", root
        assert ticker_storage_key(root) == "$" + root
    assert search["SPY"] == [["SPY", "ETF"]] and search["MU"] == [["MU", "EQUITY"]]   # others untouched
