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
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda t: tape)
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


def test_terrain_strikes_registers_viewing_demand(monkeypatch):
    """Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
    viewing"): _note_gamma_surface_demand was only ever called from get_options_gamma_surface
    (the Heatmap grid's own route). GEX-by-Strike, the Trade Desk Positioning Migration panel,
    and the Chart view all read /api/terrain/strikes instead and never registered that anyone
    was watching -- a ticker viewed only through one of those three screens could never reach
    _terrain_loop's viewed-ticker set (see test_terrain_surface_gate_v1.py's companion test),
    so it never got a live refresh attempt regardless of enrollment. Every screen that shows a
    ticker's live terrain-derived data must register the same demand signal."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "terrain_cache_get", lambda tk: {
        "_per_strike": {"all": [], "near": [], "far": []}, "spot": 100.0, "computed_ts_utc": 1.0,
    })
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **kw: (100.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(srv, "last_capture_per_day", lambda *a, **k: [])
    tk = srv.ticker_storage_key("ZZDEMANDONLY")
    srv._gamma_surface_demand.pop(tk, None)
    try:
        assert srv._gamma_surface_wanted(tk) is False, "must start with no recorded demand"
        resp = srv.get_terrain_strikes(ticker="ZZDEMANDONLY")
        json.loads(bytes(resp.body))   # a real, well-formed response — not the point of this test
        assert srv._gamma_surface_wanted(tk) is True, (
            "GET /api/terrain/strikes must register viewing demand for its ticker, the same as "
            "/api/options/gamma-surface already does -- otherwise the terrain loop never learns "
            "anyone is watching a ticker that only this route serves")
    finally:
        srv._gamma_surface_demand.pop(tk, None)


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

    monkeypatch.setattr(srv._lpr, "forming_bar", lambda t: None)   # no forming minute
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

    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, "PDL is not the full prior session's min"
    assert by_id["PDH"]["price"] == 758.58
    assert by_id["PDC"]["price"] == 757.67
    assert "price_bars_1m" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the one bar source"
    )

