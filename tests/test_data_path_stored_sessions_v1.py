"""A restart prices the stored chains on Schwab's stored /markets answers. $SPX's AM-settled monthly
contracts of 2026-10-16 as captured 2026-09-28, and Schwab's answers of 2026-10-07 as the daemon
stores them, in a fresh console process, which holds no answer when it starts."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from math_levels import compute_charm_by_strike, pick_charm_wall_strikes
from stream_spine import STREAM_SCHEMA_SQL
from time_et import ET, INDEX_OPTIONS, valuation_instant

FX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent
ANSWERS = json.loads((FX / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))[
    "answers"
]
CHAIN = FX / "real_spx_chain_contracts_2026_09_28.json"
EXPIRY = "2026-10-16"


def _record_answers(path: Path) -> int:
    """Schwab's answers as the daemon's writer stores them, each with a later time; before them,
    inserted last, an older answer for the expiry with no option session (induced test condition:
    two answers for one date, as the daemon's asks of two days are, the older cut). Returns how
    many are 200s."""
    path.parent.mkdir(parents=True)
    rows = [(n + 1.0, d, a["status"], a["body"]) for n, (d, a) in enumerate(ANSWERS.items())]
    day = json.loads(ANSWERS[EXPIRY]["body"])
    rows.append((0.0, EXPIRY, 200, json.dumps({**day, "option": {}})))
    with sqlite3.connect(path) as conn:
        conn.executescript(STREAM_SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) "
            "VALUES(?,?,?,?,'test')",
            rows,
        )
    conn.close()
    return sum(r[2] == 200 for r in rows)


FRESH_CONSOLE = """
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import server
from calibration.complete_chain_capture import CAPTURE_BASIS
from tests.capture_store import store_capture

chain = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
store_capture(
    server.get_db().db_path,
    ticker=chain["ticker"],
    expiry=sys.argv[2],
    contracts=chain["contracts"],
    spot=chain["spot"],
    completeness_basis=CAPTURE_BASIS,
    ts_utc=chain["ts_utc"],
)
with TestClient(server.app) as client:
    server._load_stored_levels([chain["ticker"]])
    while True:
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        with server._chains_waiting_lock:
            if not server._chains_waiting:
                break
    served = client.get("/api/terrain", params={"ticker": chain["ticker"]}).json()
print(json.dumps([served["call_charm_wall"], served["put_charm_wall"]]))
"""


def _env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "ED_RUNTIME_ROOT": str(tmp_path),
        "ED_ARTIFACTS_ROOT": str(tmp_path / "artifacts"),
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_schwab_token.json"),
        "PYTHONIOENCODING": "utf-8",
    }


def test_a_stored_chain_is_priced_on_the_stored_market_answers(tmp_path):
    _record_answers(tmp_path / "data" / "stream_capture.db")
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            FRESH_CONSOLE,
            str(CHAIN),
            EXPIRY,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=_env(tmp_path),
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    chain = json.loads(CHAIN.read_text(encoding="utf-8"))
    now = valuation_instant(datetime.fromtimestamp(chain["ts_utc"], ET), INDEX_OPTIONS)
    book = compute_charm_by_strike(
        chain["contracts"], chain["spot"], now=now, product=INDEX_OPTIONS
    )
    assert book and all(b["net_charm"] is not None for b in book.values())
    assert json.loads(run.stdout.splitlines()[-1]) == list(pick_charm_wall_strikes(book))


@pytest.mark.parametrize("store", ["answers", "no table"])
def test_the_console_holds_the_answers_before_its_loops_and_its_feed(tmp_path, store):
    """The real console (uvicorn server:app), its window as Ed sees it, with no daemon to reach."""
    path = tmp_path / "data" / "stream_capture.db"
    if store == "answers":
        held = _record_answers(path)
    else:
        path.parent.mkdir(parents=True)
        sqlite3.connect(path).close()
        held = None
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in _env(tmp_path).items() if k != "PYTEST_CURRENT_TEST"}  # loops start
    console = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list = []
    threading.Thread(target=lambda: lines.extend(console.stdout), daemon=True).start()
    waited, fed = "waiting for the capture daemon's heartbeat", "Live-plane feed started"
    try:
        end = time.monotonic() + 120
        while not (any(waited in ln for ln in lines) and any(fed in ln for ln in lines)):
            assert console.poll() is None and time.monotonic() < end, "".join(lines)
            time.sleep(0.25)
    finally:
        console.kill()
        console.wait(30)
    text = "".join(lines)
    if held is None:
        assert "Recorded market answers held" not in text
    else:
        at = text.index(f"Recorded market answers held: {held}")
        assert at < text.index(waited) and at < text.index(fed)
