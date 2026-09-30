"""/api/levels and /api/terrain/strikes: what the level routes serve."""
from __future__ import annotations

# ── RC-213 B1: /api/levels read-adapter contract (mission levels-faucet-v1) ──────────


def test_api_levels_b1_contract_single_session_prior_day(monkeypatch):
    """The B1 read-adapter serves the prior_day family from the RC-153 single-session
    authority, with per-level provenance naming the window, unique ids, honest
    families_absent — and never the multi-session union values (the RC-213 defect)."""
    import json
    from datetime import datetime as _dt

    import server as srv
    from time_et import ET

    def _bar(y, mo, d, h, mi, o, hi, lo, c):
        return {"timestamp": int(_dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
                "open": o, "high": hi, "low": lo, "close": c, "volume": 1000.0}

    tape = [
        _bar(2026, 7, 30, 10, 0, 100, 110, 90, 100),   # older prior session: both extremes
        _bar(2026, 7, 30, 14, 0, 100, 101, 99, 100),
        _bar(2026, 7, 31, 10, 0, 96, 105, 95, 97),     # most recent prior session
        _bar(2026, 7, 31, 15, 59, 101, 103, 100, 102),
        _bar(2026, 8, 3, 9, 35, 103, 104, 102, 103),   # today inside ORB window
        _bar(2026, 8, 3, 9, 45, 103, 104, 102, 103),   # today post-ORB
    ]
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda t: tape)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (103.5, "schwab_quote_last", 1.0))
    # This fixture tests WINDOW SELECTION with tiny sessions; the t12 coverage floor is
    # exercised by its own dedicated test below.
    import liquidity_value_engine as lve
    monkeypatch.setattr(lve, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 3, 10, 0, tzinfo=ET))

    srv._publish_price_levels("SPY")                  # as the bar writer does
    resp = srv.get_levels(ticker="SPY")
    payload = json.loads(bytes(resp.body))

    assert payload["schema_version"] == 1
    assert payload["spot"] == 103.5 and payload["spot_source"] == "schwab_quote_last"

    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload (RC-88)"
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95, (
        "prior_day must be the SINGLE most recent prior RTH session"
    )
    # the prior close is Schwab's CLOSE_PRICE, never a bar's close (tests/test_zones_v1.py); no
    # quote streams in this test, so it is absent with its reason
    assert "PDC" not in by_id
    assert {"family": "PDC", "reason": srv.PRIOR_CLOSE_ABSENT_REASON} in payload["families_absent"]
    for lv in payload["levels"]:
        assert lv["price"] not in (110, 90), "multi-session union value served — RC-213 reopened"
        assert "as_of_ts_utc" in lv["staleness"] and "age_sec" in lv["staleness"]
        if lv["family"] == "prior_day":
            assert lv["provenance"]["session_scope"] == "RTH"
            assert "2026-07-31" in lv["provenance"]["window"], (
                "provenance.window must name the literal session used (RC-153)"
            )

    fams = {f["family"] for f in payload["families_absent"]}
    # 2026-09-27: the gamma family is CARRIED from the terrain (one ranked list of levels for the
    # Trade Desk chart), never computed by Tier-B: every gamma row says so in its provenance.
    for lv in payload["levels"]:
        if lv["family"] == "gamma":
            assert lv["provenance"] == {"producer": "terrain_engine.compute_terrain", "carried": True}
    # Tier-B (levels-tierb-session-collapse-v1): session families are served from the engine
    # when today bars exist — not left as soft B1-absent placeholders.
    by_fam = {}
    for lv in payload["levels"]:
        by_fam.setdefault(lv["family"], []).append(lv["id"])
    assert "VWAP" in by_id and by_id["VWAP"]["family"] == "vwap"
    assert "ORB_HIGH" in by_id and by_id["ORB_HIGH"]["family"] == "opening_range"
    assert "TODAY_POC" in by_id and by_id["TODAY_POC"]["family"] == "value_area"
    assert all(f.get("reason") for f in payload["families_absent"])
    assert "vwap" not in fams, "vwap must be served by Tier-B, not declared absent when bars exist"


# ── RC-227: one-faucet closeout locks (mission one-faucet-closeout-v1) ────────────────


def test_api_levels_prior_day_low_is_the_full_session_min_of_price_bars_1m(monkeypatch, tmp_path):
    """t12 (RC-227 residual): the PDL must be the min of the WHOLE prior session. Measured
    live: a truncated in-memory tape served PDL 756.84 vs the true 749.59 while PDH
    matched. price_bars_1m (written only from Schwab's streamed bars) is now the one bar
    source, so the full prior session there must set every prior-day level."""
    import json
    import sqlite3
    from datetime import datetime as _dt

    import server as srv
    from time_et import ET

    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (758.0, "schwab_quote_last", 1.0))
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 4, 10, 0, tzinfo=ET))

    # The FULL prior session (390 bars) with the true low 749.59 mid-session.
    dbf = tmp_path / "bars.db"
    con = sqlite3.connect(str(dbf))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    t0 = _dt(2026, 8, 3, 9, 30, tzinfo=ET).timestamp()
    for i in range(390):
        lo = 749.59 if i == 100 else 755.0
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("SPY", t0 + i * 60, t0 + i * 60 + 60, 756, 758.58 if i == 200 else 757,
                     lo, 757.67 if i == 389 else 756, 100.0, "schwab_chart"))
    con.commit(); con.close()

    class _Db:
        db_path = str(dbf)
    monkeypatch.setattr(srv, "get_db", lambda: _Db())

    srv._publish_price_levels("SPY")                  # as the bar writer does
    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, "PDL is not the full prior session's min"
    assert by_id["PDH"]["price"] == 758.58
    assert "price_bars_1m" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the one bar source"
    )


def test_the_bar_writer_publishes_the_levels_and_the_route_only_serves_them(monkeypatch, tmp_path):
    """The bar writer publishes a ticker's price levels after each of its bars -- every ticker,
    viewed or not, so a page switching to it finds them current; a new session date is built by
    the levels loop; the route reads what was published and reads no bar. Real Schwab SPY bars,
    2026-09-24/25."""
    import json
    from datetime import datetime as _dt
    from pathlib import Path

    import push_changes
    import server as srv
    import time_et as te
    from db import EdDB
    from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
    from micro_structure import Candle
    from time_et import ET

    fx = Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json"
    now = _dt(2026, 9, 25, 15, 0, tzinfo=ET)
    raw = [b for b in json.loads(fx.read_text(encoding="utf-8"))["bars"] if b["timestamp"] / 1000.0 < now.timestamp() - 120]
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    monkeypatch.setattr(te, "now_et", lambda: now)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (None, "none", None))
    monkeypatch.setattr(srv, "terrain_cache_get", lambda t: {})
    monkeypatch.setattr(push_changes, "watched", lambda: set())            # no page is open
    monkeypatch.delitem(_MATERIALIZED_SNAPSHOTS, ("SPY", "2026-09-25"), raising=False)
    monkeypatch.delitem(_MATERIALIZED_SNAPSHOTS, ("QQQ", "2026-09-25"), raising=False)
    db.upsert_1m_bars("SPY", [Candle(ts=b["timestamp"] / 1000.0, open=b["open"], high=b["high"], low=b["low"],
                                     close=b["close"], volume=b["volume"]) for b in raw[:-1]])
    reads = []
    real_read = srv._read_bars_1m
    monkeypatch.setattr(srv, "_read_bars_1m", lambda tk, limit: reads.append(tk) or real_read(tk, limit))

    # nothing published yet: the levels are absent with their reason, and the route read no bar
    none_yet = json.loads(srv.get_levels(ticker="SPY").body)
    assert none_yet["generation"] is None and not reads
    assert {"family": "price_levels", "reason": srv.NO_PRICE_LEVELS_REASON} in none_yet["families_absent"]

    # a minute's bars arrive together (SPY, and QQQ that no page views): every bar is written
    # first, then each ticker's levels are published from its bars
    last = raw[-1]
    order, upsert, publish = [], db.upsert_1m_bars, srv._publish_price_levels
    monkeypatch.setattr(db, "upsert_1m_bars", lambda tk, bars: order.append(("bar", tk)) or upsert(tk, bars))
    monkeypatch.setattr(srv, "_publish_price_levels", lambda tk: order.append(("levels", tk)) or publish(tk))
    srv._write_streamed_bars([
        {"symbol": "SPY", "bar_start_ms": last["timestamp"], "open": last["open"], "high": last["high"],
         "low": last["low"], "close": last["close"], "volume": last["volume"]},
        {"symbol": "QQQ", "bar_start_ms": last["timestamp"], "open": 600.0, "high": 601.0, "low": 599.0,
         "close": 600.5, "volume": 1000}])
    assert order == [("bar", "SPY"), ("bar", "QQQ"), ("levels", "SPY"), ("levels", "QQQ")]
    built = len(reads)
    served = json.loads(srv.get_levels(ticker="SPY").body)
    again = json.loads(srv.get_levels(ticker="SPY", tf="15").body)
    assert built >= 1 and len(reads) == built, "the route read bars"
    assert served["generation"] == again["generation"] is not None
    # as of the end of the newest bar
    assert served["snapshot_as_of_ts_utc"] == last["timestamp"] / 1000.0 + 60.0
    assert srv.canonical_price_level_snapshot("QQQ").as_of_ts_utc == last["timestamp"] / 1000.0 + 60.0

    # a new session date: the levels loop builds that date's levels (09-25's bars are its prior day)
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 26, 9, 0, tzinfo=ET))
    srv._publish_missing_price_levels(["SPY"])
    nextday = json.loads(srv.get_levels(ticker="SPY").body)
    pdh = {lv["id"]: lv["price"] for lv in nextday["levels"]}["PDH"]
    assert pdh == max(b["high"] for b in raw if _dt.fromtimestamp(b["timestamp"] / 1000.0, ET).date().isoformat() == "2026-09-25"
                      and 570 <= _dt.fromtimestamp(b["timestamp"] / 1000.0, ET).hour * 60
                      + _dt.fromtimestamp(b["timestamp"] / 1000.0, ET).minute < 960)

