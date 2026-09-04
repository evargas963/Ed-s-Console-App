"""Options/order-flow production path: default contract, live payload, history, watchdog.

# universal-scope-ok: fixtures use banked CDE/SPY contract rows as vendor-symbol
# examples of the enrolled-universe capture path, not a SPY-only product claim.
"""
from __future__ import annotations

import json
import sqlite3
import time
from stream_spine import STREAM_SCHEMA_SQL


def _cde_fixture_chain():
    from pathlib import Path

    fx_path = Path(__file__).resolve().parent / "fixtures" / "real_cde_complete_chain_half_dollar.json"
    return json.loads(fx_path.read_text(encoding="utf-8"))


def test_pick_atm_call_uses_vendor_symbol_not_constructed():
    from app.options.default_contract import pick_atm_call_symbol

    fx = _cde_fixture_chain()
    contracts = fx["chain"]
    calls = [c for c in contracts if str(c.get("putCall") or "").upper() == "CALL"]
    assert calls, "real CDE fixture must include CALL rows"
    spot = float(calls[0]["strikePrice"]) + 0.1
    picked = pick_atm_call_symbol(contracts, spot)
    assert picked is not None
    row = next(c for c in contracts if c.get("symbol") == picked)
    assert str(row.get("putCall") or "").upper() == "CALL"
    assert picked == row["symbol"]
    assert pick_atm_call_symbol(contracts, None) is None


def test_default_contract_from_banked_chain(tmp_path, monkeypatch):
    from app.options.default_contract import default_option_contract, pick_atm_call_symbol
    from calibration.complete_chain_capture import persist_complete_chain_capture

    fx = _cde_fixture_chain()
    monkeypatch.setattr("app.options.default_contract._expiry_cutoff_et", lambda: fx["expiry"])
    db = tmp_path / "ed.db"
    persist_complete_chain_capture(
        db,
        ticker=fx["ticker"],
        expiry=fx["expiry"],
        contracts=fx["chain"],
        spot=16.1,
        completeness_basis=fx["completeness_basis"],
    )
    assert default_option_contract(fx["ticker"], chain_db_path=db) == pick_atm_call_symbol(fx["chain"], 16.1)


def test_live_payload_one_compute_includes_proxy_flow():
    import order_flow_live_state as ofls
    from app.options.live_payload import options_live_payload

    contract = "CDE   260904C00013000"
    ofls.clear_all_live_state()
    ofls.push_book(contract, {
        "key": contract,
        "BOOK_TIME": int(time.time() * 1000),
        "BIDS": [{"BID_PRICE": 1.10, "TOTAL_VOLUME": 40}],
        "ASKS": [{"ASK_PRICE": 1.20, "TOTAL_VOLUME": 50}],
    })
    ofls.push_level_one(contract, {
        "key": contract,
        "BID_PRICE": 1.10, "ASK_PRICE": 1.20,
        "LAST_PRICE": 1.15, "LAST_SIZE": 3,
        "TRADE_TIME_MILLIS": int(time.time() * 1000),
    })
    payload = options_live_payload(contract)
    assert payload["status"] == "ok"
    assert "flow" in payload
    assert payload["flow"]["classification"]["cum_delta_proxy"] == "PROXY"
    assert payload["flow"]["native_aggressor_available"] is False
    ofls.clear_all_live_state()


def test_history_hydrates_from_stream_capture_only(tmp_path, monkeypatch):
    from app.options.history import hydrate_option_content
    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(str(db))
    con.executescript(STREAM_SCHEMA_SQL)
    now = time.time()
    sym = "CDE   260904C00013000"
    con.execute(
        "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
        (now, sym, json.dumps({"LAST_PRICE": 1.15, "LAST_SIZE": 2, "TRADE_TIME_MILLIS": 1}), "test"),
    )
    con.execute(
        "INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
        (now, sym, "OPTIONS_BOOK",
         json.dumps({"BIDS": [{"BID_PRICE": 1.1, "TOTAL_VOLUME": 1}],
                     "ASKS": [{"ASK_PRICE": 1.2, "TOTAL_VOLUME": 1}],
                     "BOOK_TIME": int(now * 1000)}), "test"),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db.resolve()))
    # resolve_stream_db_path reads env fresh
    items = hydrate_option_content(sym, since_ts=now - 10, db_path=db)
    assert items
    assert any("LAST_PRICE" in x for x in items)
    assert any("BIDS" in x for x in items)
    from app.options.live_payload import options_live_payload
    payload = options_live_payload(sym, content=items)
    assert payload["status"] == "ok"


def test_watchdog_does_not_start_when_heartbeat_fresh(tmp_path, monkeypatch):
    from app.market_data.stream_watchdog import ensure_stream_capture_running
    from stream_spine import STREAM_SCHEMA_SQL, PRODUCER_CLAIM_TTL_SEC

    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(str(db))
    con.executescript(STREAM_SCHEMA_SQL)
    con.execute(
        "INSERT INTO stream_producer_heartbeat(id, daemon_pid, heartbeat_ts, resolved_db_path) "
        "VALUES(1, 1, ?, ?)",
        (time.time(), str(db)),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db.resolve()))
    started = []
    monkeypatch.setattr(
        "app.market_data.stream_watchdog.start_durable_daemon",
        lambda **k: started.append(k) or {"started": True},
    )
    out = ensure_stream_capture_running(db_path=db)
    assert out["action"] == "already_running"
    assert started == []
    assert PRODUCER_CLAIM_TTL_SEC == 30.0


def test_watchdog_starts_duration_zero_when_stale(tmp_path, monkeypatch):
    from app.market_data.stream_watchdog import ensure_stream_capture_running

    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(str(db))
    con.executescript(STREAM_SCHEMA_SQL)
    con.execute(
        "INSERT INTO stream_producer_heartbeat(id, daemon_pid, heartbeat_ts, resolved_db_path) "
        "VALUES(1, 1, ?, ?)",
        (time.time() - 120.0, str(db)),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db.resolve()))
    monkeypatch.setattr(
        "app.market_data.stream_watchdog.start_durable_daemon",
        lambda **k: {"started": True, "pid": 9, "duration_min": 0},
    )
    out = ensure_stream_capture_running(db_path=db)
    assert out["action"] == "started"
    assert out["duration_min"] == 0


def test_options_api_carries_flow_block():
    import json
    import order_flow_live_state as ofls
    import server as srv

    contract = "SPY   260820C00767000"
    ofls.clear_all_live_state()
    ofls.push_book(contract, {
        "key": contract, "BOOK_TIME": int(time.time() * 1000),
        "BIDS": [{"BID_PRICE": 1.28, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 1.30, "TOTAL_VOLUME": 12}],
    })
    body = json.loads(srv.api_order_flow_options_microstructure(contract=contract).body)
    assert body["status"] == "ok"
    assert body["flow"]["classification"]["tape_pressure_30s"] == "PROXY"
    ofls.clear_all_live_state()
