"""Contract tests: ticker_storage_key, anchor load, DB query normalization, pin_neutral repair."""
from __future__ import annotations

import inspect

from adaptive_shadow_v2_calibration import load_survivorship_anchors_v1
from db import EdDB, CANONICAL_TIMEFRAME, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, get_snapshot_sql
from timeframe_config import DERIVED_TIMEFRAME
from instrument_identity import ticker_storage_key
from market_data_adapter import schwab_candles_to_bars



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


def test_get_similar_setups_issue19_uses_zone_not_regime_primary():
    """Hardening: tier SQL must not silently conflate regime_primary with structural zone."""
    src = inspect.getsource(EdDB.get_similar_setups)
    assert "regime_primary" not in src


def test_pin_neutral_backfill_bar_low_uses_wide_lookback():
    """Gap >5000s between last bar and snapshot must not drop anchor bars (Issue 19 repair)."""
    src = inspect.getsource(EdDB.fill_outcomes_pin_neutral_backfill_v1)
    assert "120.0 * 86400.0" in src or "120.0 * 86400" in src


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


def test_schwab_candles_to_bars_round_trips_through_upsert_1m(tmp_path):
    """Adapter must emit fields upsert_1m_bars reads (regression: missing datetime skipped all rows)."""
    dbp = tmp_path / "schwab_bars.db"
    db = EdDB(dbp)
    ms = _in_window_ts(11, 0) * 1000.0
    candles = [{"datetime": int(ms), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}]
    bars = schwab_candles_to_bars(candles)
    n = db.upsert_1m_bars("COP", bars)
    assert n == 1
    exp_start = ms / 1000.0
    with db._connect() as conn:
        row = conn.execute(
            "SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m WHERE bar_start_ts_utc = ?",
            (exp_start,),
        ).fetchone()
    assert row["ticker"] == "COP"
    assert row["close"] == 1.5


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


def test_survivorship_anchor_ticker_matches_snapshots_row(tmp_path):
    """Regression: anchors must use same key as snapshots for $SPX (no SPX-only form)."""
    p = tmp_path / "surv.json"
    p.write_text(
        '{"anchors_used":[{"ticker":"$SPX","timeframe":"1m","zone":"breakout","vwap_side":"above",'
        '"nearest_above_dist":1.0,"nearest_below_dist":1.0}]}',
        encoding="utf-8",
    )
    anchors = load_survivorship_anchors_v1(path=p)
    assert anchors[0]["ticker"] == "$SPX"


def test_get_similar_setups_normalizes_spx_alias(tmp_path):
    dbp = tmp_path / "t.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                zone, vwap_side, outcome_1c,
                nearest_above_dist, nearest_below_dist,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "$SPX",
                CANONICAL_TIMEFRAME,
                1000.0,
                "test_et",
                5000.0,
                "breakout",
                "above",
                "up",
                1.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    rows = db.get_similar_setups(
        ticker="SPX",
        timeframe=CANONICAL_TIMEFRAME,
        zone="breakout",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=50,
    )
    assert len(rows) >= 1
    assert rows[0].get("ticker") == "$SPX"


def test_pin_neutral_backfill_writes_when_bars_exist(tmp_path):
    dbp = tmp_path / "t2.db"
    db = EdDB(dbp)
    # RC-306: the snapshot row below declares et_hour=10, et_minute=30, and the bars run from
    # t_snap-30min to t_snap+200min. Off the wall clock that span leaves the collect window
    # whenever the suite runs outside a narrow slice of the day — and leaves the market
    # calendar entirely on a weekend — so `upsert_1m_bars` wrote nothing and the outcome came
    # back None. Anchored to the same calendar the write seam validates against.
    t_snap = _in_window_ts(10, 30)

    with db._connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                zone, vwap_side, horizon_outcome_schema_version, outcome_filled
            )
            VALUES ('SPY', ?, ?, 'x', 10, 30, 'rth', 100.0,
                    'pin_neutral', 'above', ?, 0)
            """,
            (CANONICAL_TIMEFRAME, t_snap, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        sid = int(cur.lastrowid)
    bars = []
    for i in range(-30, 200):
        bs = t_snap + i * 60.0
        c = 100.0 + i * 0.01
        bars.append(
            {"datetime": bs, "open": c, "high": c + 0.02, "low": c - 0.02, "close": c, "volume": 100.0}
        )
    db.upsert_1m_bars("SPY", bars)

    with db._connect() as conn:
        o1 = conn.execute(
            get_snapshot_sql("tests/test_instrument_identity_and_repair_v1.py:167"),
            (sid,),
        ).fetchone()
    assert o1["outcome_1c"] in ("up", "down", "flat")

    audit = db.fill_outcomes_pin_neutral_backfill_v1(dry_run=False)
    assert audit["snapshots_scanned"] == 0
    assert audit["updates_executed"] == 0


def test_pin_neutral_backfill_excludes_legacy_5m_timeframe(tmp_path):
    """Canonical repair is 1m-only; legacy 5m rows are counted as excluded, not updated."""
    dbp = tmp_path / "t5m.db"
    db = EdDB(dbp)
    # RC-306: same clock-derived span as the test above. This one stayed green because it
    # asserts EXCLUSION, which holds whether or not the bars were written — a latent version
    # of the same defect, and fixing only the red one would be the fix-the-instance failure
    # this row exists to stop.
    t_snap = _in_window_ts(10, 30)

    with db._connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                zone, vwap_side, horizon_outcome_schema_version, outcome_filled
            )
            VALUES ('SPY', ?, ?, 'x', 10, 30, 'rth', 100.0,
                    'pin_neutral', 'above', ?, 0)
            """,
            (DERIVED_TIMEFRAME, t_snap, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        sid = int(cur.lastrowid)
    bars = []
    for i in range(-30, 200):
        bs = t_snap + i * 60.0
        c = 100.0 + i * 0.01
        bars.append(
            {"datetime": bs, "open": c, "high": c + 0.02, "low": c - 0.02, "close": c, "volume": 100.0}
        )
    db.upsert_1m_bars("SPY", bars)

    audit = db.fill_outcomes_pin_neutral_backfill_v1(dry_run=False)
    assert audit["snapshots_scanned"] == 0
    assert audit["legacy_timeframe_rows_excluded"] == 1
    assert audit["updates_executed"] == 0

    with db._connect() as conn:
        o1 = conn.execute(
            get_snapshot_sql("tests/test_instrument_identity_and_repair_v1.py:208"),
            (sid,),
        ).fetchone()
    assert o1["outcome_1c"] is None
    assert o1["timeframe"] == DERIVED_TIMEFRAME


def test_get_similar_setups_rejects_non_canonical_timeframe(tmp_path):
    """Issue 19 production similarity must not mix legacy snapshot timeframes."""
    dbp = tmp_path / "tnc.db"
    db = EdDB(dbp)
    similar, tr = db.get_similar_setups(
        ticker="SPY",
        timeframe=DERIVED_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        return_trace=True,
    )
    assert similar == []
    assert tr.get("rejected") is True
    assert tr.get("reject_reason") == "non_canonical_timeframe_for_issue19"


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
    assert src.count("ticker_storage_key(ticker or DEFAULT_TICKER)") >= 4, (
        "the terrain/spot/bars endpoints no longer canonicalize the typed symbol"
    )
    assert "tk = (ticker or DEFAULT_TICKER).upper().strip()" not in src, (
        "a raw upper/strip endpoint boundary is back — bare index symbols will go dark again"
    )
    # the producer canonicalizes too: background callers don't pass the endpoints
    assert "tk = ticker_storage_key(ticker)   # RC-126" in src
