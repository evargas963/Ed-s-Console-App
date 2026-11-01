"""A restart prices the stored chains on Schwab's stored /markets answers. $SPX's AM-settled monthly
contracts of 2026-10-16 as captured 2026-09-28, and Schwab's answers of 2026-10-07 as the daemon
stores them, in a fresh console process, which holds no answer when it starts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import server
import time_et

FX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent

FRESH_CONSOLE = """
import json
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import server
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from db_authority import canonical_stream_db_path
from stream_spine import STREAM_SCHEMA_SQL

answers = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["answers"]
chain = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
path = canonical_stream_db_path()
path.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(path)
conn.executescript(STREAM_SCHEMA_SQL)
conn.executemany(
    "INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) VALUES(?,?,?,?,'test')",
    [(float(n), d, a["status"], a["body"]) for n, (d, a) in enumerate(answers.items())],
)
conn.commit()
conn.close()
persist_complete_chain_capture(
    server.get_db().db_path,
    ticker=chain["ticker"],
    expiry="2026-10-16",
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
    with server._terrain_cache_lock:
        book = server._terrain_cache[chain["ticker"]]["_charm_by_expiry"]["2026-10-16"]
print(json.dumps(sorted(b["net_charm"] is not None for b in book.values())))
"""


def test_a_stored_chain_is_priced_on_the_stored_market_answers(tmp_path):
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            FRESH_CONSOLE,
            str(FX / "real_schwab_markets_2026_10_07.json"),
            str(FX / "real_spx_chain_contracts_2026_09_28.json"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={
            **os.environ,
            "ED_RUNTIME_ROOT": str(tmp_path),
            "ED_ARTIFACTS_ROOT": str(tmp_path / "artifacts"),
            "ED_LIVE_PUSH_PORT": "1",
            "ED_LIVE_UI_PORT": "1",
        },
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    known = json.loads(run.stdout.splitlines()[-1])
    assert known and all(known)


@pytest.mark.parametrize("table", [False, True], ids=["no database", "no table"])
def test_no_stored_answers_holds_nothing(tmp_path, table):
    """The console's first start, before the daemon's."""
    path = tmp_path / "stream_capture.db"
    if table:
        sqlite3.connect(path).close()
    held = time_et._sessions
    server._load_stored_sessions(path)
    assert time_et._sessions is held
