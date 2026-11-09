"""A restart prices the stored chains on Schwab's stored /markets answers.

$SPX's AM-settled monthly
contracts of 2026-10-16 as captured 2026-09-28, and Schwab's answers of 2026-10-07 as the daemon
stores them, in a fresh console process, which holds no answer when it starts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from math_levels import compute_charm_by_strike, pick_charm_wall_strikes
from option_contract import read_chain
from stream_spine import STREAM_SCHEMA_SQL
from tests.test_console_startup_waits_v1 import program_env, run_until
from time_et import ET, INDEX_OPTIONS, valuation_instant

FX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent
ANSWERS = json.loads((FX / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))[
    "answers"
]
CHAIN = FX / "real_spx_chain_contracts_2026_09_28.json"
EXPIRY = "2026-10-16"


def _record_answers(path: Path) -> int:
    """Store Schwab's answers as the daemon's writer stores them, each with a later time.

    Before them, inserted last, an older answer for the expiry with no option session (induced
    test condition: two answers for one date, as the daemon's asks of two days are, the older
    cut). Returns how many are 200s.
    """
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
import time_et
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
with TestClient(server.app):
    server._load_stored_levels([chain["ticker"]])
    while True:
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        with server._chains_waiting_lock:
            if not server._chains_waiting:
                break
    tk = server.ticker_storage_key(chain["ticker"])
    served = server.terrain(tk, time_et.now(), {})
print(json.dumps([served["call_charm_wall"], served["put_charm_wall"]]))
"""


def _env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "ED_RUNTIME_ROOT": str(tmp_path),
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
        read_chain(chain["contracts"]), chain["spot"], now=now, product=INDEX_OPTIONS
    )
    assert book and all(b["net_charm"] is not None for b in book.values())
    assert json.loads(run.stdout.splitlines()[-1]) == list(pick_charm_wall_strikes(book))


@pytest.mark.parametrize("store", ["answers", "none yet"])
def test_the_console_holds_the_answers_before_its_loops_and_its_feed(tmp_path, store):
    """The real program, its window as Ed sees it, with no Schwab token.

    capture_main: the daemon and the console's pages in one process. The answers the daemon
    recorded are held before the console's loop and its feed start; with none recorded yet (the
    program's writer makes the tables at its start), it holds 0.
    """
    path = tmp_path / "data" / "stream_capture.db"
    held = _record_answers(path) if store == "answers" else 0
    env = program_env(tmp_path)
    waited, fed = "waiting for the capture daemon's heartbeat", "Live-plane feed started"
    text = run_until(env, lambda t: waited in t and fed in t)
    at = text.index(f"Recorded market answers held: {held}")
    assert at < text.index(waited) and at < text.index(fed)
    assert text.count("Recorded market answers held:") == 1, "the answers are loaded once"
    assert "no capture daemon runs in this program" not in text, "the console found its daemon"
