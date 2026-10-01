"""/api/levels and /api/terrain/strikes: what the level routes serve."""
from __future__ import annotations

# ── RC-213 B1: /api/levels read-adapter contract (mission levels-faucet-v1) ──────────


def test_api_levels_b1_contract_single_session_prior_day(monkeypatch):
    """The B1 read-adapter serves the prior_day family from the RC-153 single-session
    authority, with per-level provenance naming the window, unique ids, honest
    families_absent — and never the multi-session union values (the RC-213 defect)."""
    import json
    from datetime import datetime as _dt
    from pathlib import Path

    import server as srv
    from time_et import ET

    # Real Schwab SPY 1-minute bars: all of 2026-09-24 and 2026-09-25, served at 10:00 ET on the 25th
    now = _dt(2026, 9, 25, 10, 0, tzinfo=ET)
    bars = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                      .read_text(encoding="utf-8"))["bars"]
    tape = [b for b in bars if b["timestamp"] / 1000.0 < now.timestamp() - 60]
    et = lambda b: _dt.fromtimestamp(b["timestamp"] / 1000.0, ET)   # noqa: E731
    prior = [b for b in tape if et(b).day == 24 and 570 <= et(b).hour * 60 + et(b).minute < 960]
    today = [b for b in tape if et(b).day == 25]
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda t: tape)
    # stand-in (named): the live price
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (today[-1]["close"], srv.SPOT_SOURCE_PLANE, 1.0))
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: now)

    srv._publish_price_levels("SPY")                  # as the bar writer does
    resp = srv.get_levels(ticker="SPY")
    payload = json.loads(bytes(resp.body))

    assert payload["schema_version"] == 1
    assert payload["spot"] == today[-1]["close"] and payload["spot_source"] == srv.SPOT_SOURCE_PLANE

    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload (RC-88)"
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert len(prior) == 390
    # the prior day's high and low are Schwab's daily candle, never its minutes' range (operator
    # 2026-10-01): no daily candle has come from the daemon here, so they are absent with the reason
    assert "PDH" not in by_id and "PDL" not in by_id
    assert {"family": "prior_day_range", "reason": "Schwab's daily candles have not come from the capture daemon"} \
        in payload["families_absent"]
    # the prior close is Schwab's CLOSE_PRICE, never a bar's close (tests/test_zones_v1.py); no
    # quote streams in this test, so it is absent with its reason (no price row from the daemon)
    assert "PDC" not in by_id
    assert {"family": "PDC", "reason": srv.NO_PRICE_ROW_REASON} in payload["families_absent"]
    for lv in payload["levels"]:
        assert "as_of_ts_utc" in lv["staleness"] and "age_sec" in lv["staleness"]
        if lv["family"] == "prior_day":
            assert lv["provenance"]["session_scope"] == "RTH"
            assert "2026-09-24" in lv["provenance"]["window"], (
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
    monkeypatch.setattr(srv, "terrain_cache_get", lambda t, now: {})
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
    monkeypatch.setattr(db, "upsert_1m_bars", lambda tk, bars, **kw: order.append(("bar", tk)) or upsert(tk, bars, **kw))
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
    poc = {lv["id"]: lv for lv in nextday["levels"]}["PD_POC"]
    assert "2026-09-25" in poc["provenance"]["window"]

