"""A restart prices the stored chains on Schwab's stored /markets answers. $SPX's AM-settled monthly
contracts of 2026-10-16 as captured 2026-09-28, and Schwab's answers of 2026-10-07 as the daemon
stores them, in a fresh process, as a console holds no answer when it starts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import server
from stream_spine import STREAM_SCHEMA_SQL

FX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent

FRESH_CONSOLE = """
import json
import sys
from datetime import datetime
from pathlib import Path

import server
from math_levels import compute_charm_by_strike
from time_et import ET, INDEX_OPTIONS

fx = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
now = datetime.fromtimestamp(fx["ts_utc"], ET)


def walls_known():
    book = compute_charm_by_strike(fx["contracts"], fx["spot"], now=now, product=INDEX_OPTIONS)
    return all(b["net_charm"] is not None for b in book.values())


before = walls_known()
server._load_stored_sessions(Path(sys.argv[1]))
print(json.dumps([before, walls_known()]))
"""


def test_a_stored_chain_is_priced_on_the_stored_market_answers(tmp_path):
    db = tmp_path / "stream_capture.db"
    answers = json.loads((FX / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))
    with sqlite3.connect(db) as conn:
        conn.executescript(STREAM_SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) "
            "VALUES(?,?,?,?,'test')",
            [
                (float(n), day, a["status"], a["body"])
                for n, (day, a) in enumerate(answers["answers"].items())
            ],
        )
    conn.close()
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            FRESH_CONSOLE,
            str(db),
            str(FX / "real_spx_chain_contracts_2026_09_28.json"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "ED_CI_OFFLINE": "1"},
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.splitlines()[-1]) == [False, True]


def test_no_stored_answers_is_no_answer(tmp_path):
    """No database yet, as on the first start: nothing is held and nothing fails."""
    server._load_stored_sessions(tmp_path / "stream_capture.db")
