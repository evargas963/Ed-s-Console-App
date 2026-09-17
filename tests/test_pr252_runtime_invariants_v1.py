"""Regression proofs for the 2026-09-17 current-heatmap / identity FAIL list."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_current_gamma_never_serves_banked_morning_cells(tmp_path, monkeypatch):
    import sqlite3
    import time

    import server
    from instrument_identity import ticker_storage_key
    from time_et import now_et

    class _FakeDB:
        def __init__(self, path):
            self.db_path = str(path)

    def _seed(path, ticker, et_date, ts_utc, spot):
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS option_chain_morning_full ("
            "ticker TEXT, et_date TEXT, ts_utc REAL, spot REAL, n_contracts INT, "
            "n_expiries INT, max_dte REAL, chain_json TEXT, source TEXT)"
        )
        con.execute(
            "INSERT INTO option_chain_morning_full "
            "(ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ticker, et_date, ts_utc, spot, 0, 0, None, "[]", "test"),
        )
        con.commit()
        con.close()

    tk = ticker_storage_key("ZZBANKEDNOW")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)
    db = tmp_path / "morning.db"
    today_et = now_et().strftime("%Y-%m-%d")
    _seed(db, "ZZBANKEDNOW", today_et, time.time() - 1800.0, 101.5)
    monkeypatch.setattr(server, "get_db", lambda: _FakeDB(db))
    try:
        body = json.loads(server.get_options_gamma_surface(ticker="ZZBANKEDNOW").body)
        assert body["source"] != "banked_morning_reference"
        assert body["available"] is False
        assert body.get("cells") in (None, [])
        assert "UNAVAILABLE" in (body.get("reason") or "")
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_selected_contracts_match_cell_identities_and_reject_bad_schema():
    import server

    surface = {
        "cells": [
            {"strike": 100, "contracts": [{"call": "C100", "put": "P100"}, {"call": "C100b", "put": None}]},
            {"strike": 101, "contracts": [{"call": "C101", "put": "P101"}]},
        ]
    }
    got = server._selected_contracts_from_surface(surface)
    assert got == ["C100", "P100", "C100b", "C101", "P101"]
    with pytest.raises(TypeError):
        server._selected_contracts_from_surface({"cells": {"nope": True}})
    with pytest.raises(TypeError):
        server._selected_contracts_from_surface({"cells": [{"contracts": {"call": "C"}}]})


def test_missing_contract_array_is_not_an_empty_success():
    import server

    with pytest.raises(TypeError):
        server._selected_contracts_from_surface({"cells": [{"strike": 1, "contracts": "C1"}]})


def test_daemon_sha_mismatch_is_not_identity_match(tmp_path, monkeypatch):
    import time as _time

    import app.options.order_flow.streaming as ofs
    from stream_spine import CaptureWriter, quote_msg

    db = tmp_path / "data" / "stream_capture.db"
    db.parent.mkdir(parents=True)
    native = {"key": "SPY", "BID_PRICE": 1, "ASK_PRICE": 2, "LAST_PRICE": 1.5,
              "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 1, "TOTAL_VOLUME": 1}
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1, ask=2, last=1.5,
                                    src="schwab_l1", ts_recv=_time.time(), native=native))
    w.commit()
    w.write_heartbeat(producer_git_sha="not-this-checkout")
    w.close()
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    st = ofs._stream_db_identity_status()
    assert st["sha_match"] is False
    assert st["identity_match"] is not True
    assert st["daemon_git_sha"] == "not-this-checkout"
    assert ofs.is_option_producer_daemon_available() is False


def test_chain_live_failure_is_not_cached_success(monkeypatch, tmp_path):
    import server as srv

    class _FakeDB:
        def __init__(self, path):
            self.db_path = str(path)

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "get_db", lambda: _FakeDB(tmp_path / "chain.db"))
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: ["2026-09-18"])

    def _boom(*_a, **_k):
        raise TimeoutError("simulated chain stall")

    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    body = json.loads(srv.get_chain(ticker="SPY", expiry=None).body)
    assert body["status"] == "live_fetch_failed"
    assert body["available"] is False
    assert body["contracts"] == []
    assert body["scope"]["kind"] == "live_fetch_failed"


def test_options_html_m_spot_is_independent_of_chain():
    src = (ROOT / "static" / "options.html").read_text(encoding="utf-8")
    assert "function paintSpot(" in src
    assert "function loadSpot(" in src
    assert "el.textContent = 'UNAVAILABLE'" in src
    assert "Promise.all([" not in src
    assert "current_spot_from_resolve" not in src
    assert "#m-spot is owned by paintSpot" in src


def test_runtime_inventory_cannot_mark_failed_surfaces_live():
    inv = json.loads((ROOT / "reports" / "whole_ui_live_inventory_v1.json").read_text(encoding="utf-8"))
    for row in inv["instances"]:
        if row.get("runtime_failure") or row["status"] in {"UNAVAILABLE", "FAIL"}:
            assert row["runtime_status"] != "LIVE", row["id"]
        if row["runtime_status"] == "LIVE":
            assert row.get("runtime_evidence"), row["id"]
        if row["id"] == "morning_gamma_reference":
            assert row["status"] == "HISTORICAL_REFERENCE"
            assert row["runtime_status"] != "LIVE"
    assert inv["runtime_summary"]["LIVE"] == 0
    assert inv["api_surfaces"]["/api/terrain/scorecard"]["status"] != "NOT_PROVEN"
    assert inv["api_surfaces"]["/api/vol-observability"]["status"] != "NOT_PROVEN"


def _cell_ct(strike, side, oi, *, gamma=0.04, delta=0.5, exp="2026-09-18T20:00:00.000+00:00"):
    # institutional-synthetic-ok: adversarial cell-state proof needs controlled OI/gamma.
    payload = {
        "strikePrice": strike, "putCall": side, "multiplier": 100,
        "delta": delta if side == "CALL" else -abs(delta), "gamma": gamma,
        "volatility": 20.0, "totalVolume": 0, "bidSize": 1, "askSize": 1,
        "daysToExpiration": 5, "expirationDate": exp,
        "symbol": f"TEST  260918{'C' if side == 'CALL' else 'P'}{int(strike * 1000):08d}",
    }
    if oi is not None:
        payload["openInterest"] = oi
    return payload


def test_current_spot_absent_never_reads_surface_spot():
    src = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert "surface.current_spot != null ? surface.current_spot : surface.spot" not in src
    assert "canonicalCurrentSpot(surface)" in src
    assert "current LAST_PRICE is UNAVAILABLE" in src
    import tools.spot_binding_lock as L
    files = {"static/js/ed-gamma.js": src}
    assert L.ed_js_dual_spot_fallback_violations(files) == []


def test_cell_states_are_distinct_and_reconcile_exactly():
    from server import (
        VALUE_STATE_COMPUTED,
        VALUE_STATE_GAMMA_UNAVAILABLE,
        VALUE_STATE_NO_CONTRACT,
        VALUE_STATE_OI_UNAVAILABLE,
        VALUE_STATE_ZERO_OI,
        project_gamma_surface,
    )

    exp_a = "2026-09-18T20:00:00.000+00:00"
    exp_b = "2026-10-16T20:00:00.000+00:00"
    chain = [
        _cell_ct(95.0, "CALL", 0, exp=exp_a), _cell_ct(95.0, "PUT", 0, exp=exp_a),
        _cell_ct(100.0, "CALL", None, exp=exp_a), _cell_ct(100.0, "PUT", None, exp=exp_a),
        _cell_ct(105.0, "CALL", 400, gamma=None, delta=-1.0, exp=exp_a),
        _cell_ct(105.0, "PUT", 400, gamma=None, delta=-1.0, exp=exp_a),
        _cell_ct(100.0, "CALL", 500, exp=exp_b), _cell_ct(100.0, "PUT", 500, exp=exp_b),
    ]
    surface = project_gamma_surface(chain, 100.0)
    by = {(row["strike"], i): row["value_states"][i]
          for row in surface["cells"]
          for i, _exp in enumerate(surface["expirations"])}
    exp_index = {e["expiry"]: i for i, e in enumerate(surface["expirations"])}
    ia, ib = exp_index["2026-09-18"], exp_index["2026-10-16"]
    assert by[(95.0, ia)] == VALUE_STATE_ZERO_OI
    assert by[(100.0, ia)] == VALUE_STATE_OI_UNAVAILABLE
    assert by[(105.0, ia)] == VALUE_STATE_GAMMA_UNAVAILABLE
    assert by[(100.0, ib)] == VALUE_STATE_COMPUTED
    assert by[(95.0, ib)] == VALUE_STATE_NO_CONTRACT
    assert by[(105.0, ib)] == VALUE_STATE_NO_CONTRACT
    row95 = [r for r in surface["cells"] if r["strike"] == 95.0][0]
    assert row95["gex"][ia] == 0
    counts = surface["value_state_counts"]
    assert counts["total"] == surface["cells_total"] == 6
    assert counts["zero_oi"] == 1
    assert counts["oi_unavailable"] == 1
    assert counts["gamma_unavailable"] == 1
    assert counts["computed"] == 1
    assert counts["no_contract"] == 2
    assert sum(counts[k] for k in (
        "no_contract", "zero_oi", "oi_unavailable", "gamma_unavailable", "computed"
    )) == 6


def test_null_gex_alone_is_not_no_contract_or_no_oi():
    from server import classify_gamma_cell_value_state, VALUE_STATE_NO_CONTRACT
    state = classify_gamma_cell_value_state(
        {"has_oi": False, "oi_absent": True, "call_oi": None, "put_oi": None,
         "has_valid_gamma": False},
        {"call": "C100", "put": "P100"},
    )
    assert state == "oi_unavailable"
    assert state != VALUE_STATE_NO_CONTRACT
    assert state != "no_oi"


def test_selected_contracts_equal_listed_cells():
    import server
    from server import project_gamma_surface

    chain = [
        _cell_ct(100.0, "CALL", 10), _cell_ct(100.0, "PUT", 0),
        _cell_ct(105.0, "CALL", None),
    ]
    surface = project_gamma_surface(chain, 100.0)
    selected = server._selected_contracts_from_surface(surface)
    listed = []
    for row in surface["cells"]:
        for pair in row["contracts"]:
            if pair.get("call"):
                listed.append(pair["call"])
            if pair.get("put"):
                listed.append(pair["put"])
    assert selected == listed
    assert selected, "listed contracts must be demanded"
