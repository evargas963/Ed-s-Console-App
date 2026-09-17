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
