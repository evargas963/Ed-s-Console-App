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
    monkeypatch.setattr(srv, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 3, 10, 0, tzinfo=ET))

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
    assert by_id["PDC"]["price"] == 102
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


def test_strikes_payload_carries_server_side_sums(monkeypatch):
    """STRIP server half: /api/terrain/strikes serves today_side_sums computed against the
    payload's own spot — the one aggregator."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "terrain_cache_get", lambda tk: {
        "_per_strike": {"all": [[95.0, 10.0, 100], [105.0, -4.0, 50]],
                        "near": [], "far": []},
        "spot": 100.0, "computed_ts_utc": 1.0,
    })
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **kw: (100.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(srv, "last_capture_per_day", lambda *a, **k: [])   # no prior day
    resp = srv.get_terrain_strikes(ticker="SPY")
    payload = json.loads(bytes(resp.body))
    ss = payload["today_side_sums"]
    assert ss["gex_below"] == 10.0 and ss["gex_above"] == -4.0
    assert ss["vol_below"] == 100 and ss["vol_above"] == 50
    assert ss["spot_basis"] == 100.0, "sums must be computed against the payload's own spot"


def test_api_levels_prior_day_low_is_the_full_session_min_of_price_bars_1m(monkeypatch, tmp_path):
    """t12 (RC-227 residual): the PDL must be the min of the WHOLE prior session. Measured
    live: a truncated in-memory tape served PDL 756.84 vs the true 749.59 while PDH/PDC
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
        bars_written: dict = {}
    monkeypatch.setattr(srv, "get_db", lambda: _Db())

    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, "PDL is not the full prior session's min"
    assert by_id["PDH"]["price"] == 758.58
    assert by_id["PDC"]["price"] == 757.67
    assert "price_bars_1m" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the one bar source"
    )


def test_levels_are_served_as_produced_until_the_bar_writer_writes_a_bar(monkeypatch, tmp_path):
    """2026-09-29 RTH: every /api/levels request re-read 2,500 bars and re-fingerprinted them
    (1-3 s each inside the live console; a timeframe switch took 6.8 s). The price-level snapshot
    is rebuilt only when the bar writer (EdDB.upsert_1m_bars) has written the ticker's bars since
    it was built; otherwise it is served as produced. Real Schwab SPY bars, 2026-09-24/25."""
    import json
    from datetime import datetime as _dt
    from pathlib import Path

    import server as srv
    import time_et as te
    from db import EdDB
    from micro_structure import Candle
    from time_et import ET

    fx = Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json"
    now = _dt(2026, 9, 25, 15, 0, tzinfo=ET)
    bars = [Candle(ts=b["timestamp"] / 1000.0, open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                   volume=b["volume"]) for b in json.loads(fx.read_text(encoding="utf-8"))["bars"]
            if b["timestamp"] / 1000.0 < now.timestamp() - 120]
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    monkeypatch.setattr(te, "now_et", lambda: now)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (None, "none", None))
    assert db.upsert_1m_bars("SPY", bars[:-1]) == len(bars) - 1
    reads = []
    real_read = srv._read_bars_1m
    monkeypatch.setattr(srv, "_read_bars_1m", lambda tk, limit: reads.append(tk) or real_read(tk, limit))

    first = json.loads(srv.get_levels(ticker="SPY").body)
    again = json.loads(srv.get_levels(ticker="SPY", tf="15").body)
    assert len(reads) == 1, "a request with no new bar re-read the bars"
    assert again["generation"] == first["generation"]

    assert db.upsert_1m_bars("SPY", bars[-1:]) == 1        # the bar writer writes the next bar
    after = json.loads(srv.get_levels(ticker="SPY").body)
    assert len(reads) == 2 and after["generation"] == first["generation"] + 1
    assert after["snapshot_as_of_ts_utc"] > first["snapshot_as_of_ts_utc"]

    # a new session date is a new snapshot with no bar written: 09-25's bars are its prior day
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 9, 26, 9, 0, tzinfo=ET))
    nextday = json.loads(srv.get_levels(ticker="SPY").body)
    assert len(reads) == 3
    pdh = {lv["id"]: lv["price"] for lv in nextday["levels"]}["PDH"]
    assert pdh == max(b.high for b in bars if _dt.fromtimestamp(b.ts, ET).date().isoformat() == "2026-09-25"
                      and 570 <= _dt.fromtimestamp(b.ts, ET).hour * 60 + _dt.fromtimestamp(b.ts, ET).minute < 960)

