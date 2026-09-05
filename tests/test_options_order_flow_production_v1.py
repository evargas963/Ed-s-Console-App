"""Options/order-flow production path: default contract, live payload, history, stream lock.

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
    from app.options.contracts.default import pick_atm_call_symbol

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
    from app.options.contracts.default import default_option_contract, pick_atm_call_symbol
    from calibration.complete_chain_capture import persist_complete_chain_capture

    fx = _cde_fixture_chain()
    monkeypatch.setattr("app.options.contracts.default._expiry_cutoff_et", lambda: fx["expiry"])
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
    import app.options.order_flow.state as ofls
    from app.options.order_flow.live_payload import options_live_payload

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
    from app.options.order_flow.history import hydrate_option_content
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
    from app.options.order_flow.live_payload import options_live_payload
    payload = options_live_payload(sym, content=items)
    assert payload["status"] == "ok"


def _isolated_stream_env(db_path):
    """Child env: tmp DB wins over the live STREAM_CAPTURE_DB_PATH, Schwab is blocked."""
    import os
    env = os.environ.copy()
    env["STREAM_CAPTURE_DB_PATH"] = str(db_path.resolve())
    env["ED_CI_OFFLINE"] = "1"
    env["SCHWAB_API_KEY"] = "ci-placeholder-key"
    env["SCHWAB_APP_SECRET"] = "ci-placeholder-secret"
    return env


def test_real_subprocess_second_daemon_cannot_own_lock(tmp_path):
    """Real process boundary: a held DB-adjacent lock refuses a second daemon.

    Does not mock Popen. The second process is the real tools/run_stream_capture.py
    entry point. It must exit non-zero and must not be reported as started.
    """
    import subprocess
    import sys
    import time
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parents[1]
    db = tmp_path / "stream_capture.db"
    lock = tmp_path / "stream_capture.lock"
    env = _isolated_stream_env(db)
    holder_src = (
        "import os, sys, time\n"
        f"sys.path.insert(0, r'{repo}')\n"
        "from app.market_data.schwab.streaming.capture import acquire_owner_lock, owner_lock_path\n"
        f"db = r'{db}'\n"
        "os.environ['STREAM_CAPTURE_DB_PATH'] = db\n"
        "fd, held = acquire_owner_lock(db)\n"
        "print('LOCK_HELD', held, flush=True)\n"
        "time.sleep(90)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_src],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.time() + 20
        saw_lock = False
        while time.time() < deadline:
            if lock.exists():
                saw_lock = True
                break
            if holder.poll() is not None:
                out, err = holder.communicate()
                raise AssertionError(
                    f"lock holder died rc={holder.returncode} stdout={out!r} stderr={err!r}"
                )
            time.sleep(0.05)
        assert saw_lock, "holder never created the DB-adjacent lock"
        second = subprocess.run(
            [
                sys.executable,
                "-m", "app.market_data.schwab.streaming.capture",
                "--symbols",
                "SPY",
                "--duration-min",
                "0",
                "--db",
                str(db),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
        combined = (second.stdout or "") + (second.stderr or "")
        assert second.returncode != 0, combined
        assert "another stream-capture owner" in combined, combined
        assert '"started"' not in combined
    finally:
        holder.kill()
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            holder.terminate()


def test_real_subprocess_failed_schwab_is_not_started(tmp_path):
    """Schwab/session failure is exit 2 and releases the lock. Not a success."""
    import subprocess
    import sys
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parents[1]
    db = tmp_path / "stream_capture.db"
    lock = tmp_path / "stream_capture.lock"
    env = _isolated_stream_env(db)
    result = subprocess.run(
        [
            sys.executable,
            "-m", "app.market_data.schwab.streaming.capture",
            "--symbols",
            "SPY",
            "--duration-min",
            "0",
            "--db",
            str(db),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=45,
        env=env,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2, combined
    assert "FATAL: Schwab client init failed" in combined, combined
    assert not lock.exists(), "failed start leaked the owner lock"
    assert '"started"' not in combined


def test_real_subprocess_dead_owner_lock_is_reclaimed(tmp_path):
    """After the owner process dies, the next real daemon can take the lock.

    It then fails Schwab honestly (exit 2) — reclaim is not a false start.
    """
    import subprocess
    import sys
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parents[1]
    db = tmp_path / "stream_capture.db"
    lock = tmp_path / "stream_capture.lock"
    env = _isolated_stream_env(db)
    holder_src = (
        "import os, sys\n"
        f"sys.path.insert(0, r'{repo}')\n"
        "from app.market_data.schwab.streaming.capture import acquire_owner_lock\n"
        f"db = r'{db}'\n"
        "os.environ['STREAM_CAPTURE_DB_PATH'] = db\n"
        "fd, held = acquire_owner_lock(db)\n"
        "os._exit(0)\n"
    )
    died = subprocess.run(
        [sys.executable, "-c", holder_src],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert died.returncode == 0, died.stdout + died.stderr
    assert lock.exists(), "crash must leave the lock file for the next owner to reclaim"
    result = subprocess.run(
        [
            sys.executable,
            "-m", "app.market_data.schwab.streaming.capture",
            "--symbols",
            "SPY",
            "--duration-min",
            "0",
            "--db",
            str(db),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=45,
        env=env,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2, combined
    assert "another stream-capture owner" not in combined, combined
    assert "FATAL: Schwab client init failed" in combined, combined
    assert not lock.exists()


def test_options_api_carries_flow_block():
    import json
    import app.options.order_flow.state as ofls
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
