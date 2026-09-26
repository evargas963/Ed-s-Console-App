"""Contract tests: ticker_storage_key, anchor load, DB query normalization, pin_neutral repair."""
from __future__ import annotations


from db import EdDB
from instrument_identity import ticker_storage_key


def _in_window_ts(hour: int = 10, minute: int = 0) -> float:
    """A bar timestamp the COLLECT-WINDOW LAW admits: RTH, on a real trading day.

    RC-306, third file. These fixtures used literal epochs — 1_700_000_040 (2023-11-14
    17:14 ET, after the close, in a year the calendar authority does not even cover) and
    1_771_848_000_000 ms (2026-02-23 07:00 ET, before the open). Both were admissible when
    written. RC-183/RC-214 then narrowed the writer's domain to the collect window, so
    `upsert_1m_bars` began refusing them and three tests measured the law instead of the
    identity behaviour they exist to pin. The timestamp now comes from the same calendar the
    seam validates against, at an ET minute inside the window.

    2026-08-17: this was a SECOND copy of the shared `tests.conftest.in_window_ts`, and
    the copy is why it kept a defect the original had lost — it anchored to
    `most_recent_trading_day_et`, i.e. to TODAY, so whenever the suite ran before the
    collect window closed the bars below described a session that had not happened yet and
    `outcome_1c` came back None. It now delegates to the one authority, which anchors to
    the most recent COMPLETED session; there is no local re-encoding left to drift.
    """
    from tests.conftest import in_window_ts

    return in_window_ts(hour, minute)






def test_upsert_1m_bars_uses_ticker_storage_key_for_spx_family(tmp_path):
    """Bars must persist under $SPX when caller passes bare SPX (Issue 19 rehydration)."""
    dbp = tmp_path / "bars_id.db"
    db = EdDB(dbp)
    # Canonical 60s UTC grid (BAR_ANCHOR_V1); upsert snaps near-grid floats to the minute open.
    ts = _in_window_ts()
    bars = [
        {
            "datetime": ts * 1000.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
        }
    ]
    db.upsert_1m_bars("spx", bars)
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT ticker, bar_start_ts_utc FROM price_bars_1m WHERE bar_start_ts_utc = ?",
            (ts,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "$SPX"




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


def test_query_endpoints_canonicalize_through_the_authority():
    """Structural: every UI query endpoint normalizes via ticker_storage_key, and the raw
    upper/strip form is gone from those entry lines — one authority, swept consumers
    (the RC-122/RC-126 root: an SSOT nobody routed through)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert src.count("ticker_storage_key(_required_ticker(ticker))") >= 4, (
        "the terrain/spot/bars endpoints no longer canonicalize the typed symbol"
    )
    assert "DEFAULT_TICKER" not in src, "a default ticker is back (universality, 2026-09-23)"
    assert "tk = (ticker or DEFAULT_TICKER).upper().strip()" not in src, (
        "a raw upper/strip endpoint boundary is back — bare index symbols will go dark again"
    )
    # the producer canonicalizes too: background callers don't pass the endpoints
    assert "tk = ticker_storage_key(ticker)   # RC-126" in src
