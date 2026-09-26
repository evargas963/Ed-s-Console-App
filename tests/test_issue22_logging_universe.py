"""
Issue 22 — durable logging_universe enrollment (EdDB) and bounded user cap semantics.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB


def _tickers_by_cat(db: EdDB) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {
        "core": set(),
        "pinned": set(),
        "panel_auto": set(),
        "user_persisted": set(),
    }
    for r in db.logging_universe_list_rows():
        c = (r.get("category") or "").lower()
        t = (r.get("ticker") or "").upper().strip()
        if c in out:
            out[c].add(t)
    return out






























def test_issue22_legacy_migration_idempotent_no_duplicate_rows(tmp_path):
    primary = tmp_path / "legacy_tickers.json"
    archive = tmp_path / "legacy_tickers.json.migrated_issue22"
    primary.write_text(json.dumps(["dda", "DDA", "ddb", "DDC"]), encoding="utf-8")
    dbp = tmp_path / "i22mig.db"
    edb = EdDB(dbp)
    r1 = edb.logging_universe_migrate_legacy_json_file(
        primary_path=primary,
        archive_path=archive,
        core_tickers=["SPY"],
    )
    assert r1["status"] == "imported"
    users = [r["ticker"].upper() for r in edb.logging_universe_list_rows() if r["category"] == "user_persisted"]
    assert sorted(set(users)) == ["DDA", "DDB", "DDC"]
    assert len(users) == len(set(users))
    r2 = edb.logging_universe_migrate_legacy_json_file(
        primary_path=primary,
        archive_path=archive,
        core_tickers=["SPY"],
    )
    assert r2["status"] == "already_completed"








# ─────────────────────────────────────────────────────────────────────────────
# DB-WRITE-PATH-FIXES (d) — defer the heavy logging-universe DB load off module import
# ─────────────────────────────────────────────────────────────────────────────
def test_db_write_path_d_import_does_not_trigger_db_universe_load():
    """DB-WRITE-PATH-FIXES (d), 2026-05-31: `import server` must NOT run the heavy DB-backed
    logging-universe load (migrations / sync_core / prune / panel-sync). That work moves to
    the FastAPI lifespan (start_logger -> _hydrate_logger_tickers_from_db). Verified in a CLEAN
    subprocess so prior in-process lifespan/hydrate calls cannot pollute the guard counter."""
    code = (
        "import server;"
        "assert server._LOGGING_UNIVERSE_DB_LOAD_COUNT == 0, server._LOGGING_UNIVERSE_DB_LOAD_COUNT;"
        "assert server._logger_tickers == list(server.CORE_TICKERS),"
        " server._logger_tickers;"
        "print('IMPORT_DEFER_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "IMPORT_DEFER_OK" in proc.stdout




# ─────────────────────────────────────────────────────────────────────────────
# TICKER-PREVIEW-NO-ENROLL — viewing a symbol must not enroll it (operator 2026-05-31)
# ─────────────────────────────────────────────────────────────────────────────






# ─────────────────────────────────────────────────────────────────────────────
# RC-345 / F25 — logging_universe canonical ticker identity (SPX == $SPX == "$SPX").
# The PK is COLLATE NOCASE (case folds) but "SPX" and "$SPX" are distinct rows; the enrollment
# semantic must resolve every alias to ONE canonical instrument identity across write/read/dedup/
# membership/update/delete, and a migration must fold legacy bare-root rows onto the canonical key.
# ─────────────────────────────────────────────────────────────────────────────
import sqlite3 as _sqlite3


def _lu_rows(dbp) -> list[str]:
    con = _sqlite3.connect(str(dbp))
    try:
        return [r[0] for r in con.execute("SELECT ticker FROM logging_universe").fetchall()]
    finally:
        con.close()


def _insert_legacy_lu_row(dbp, ticker, category, ts):
    """Insert a raw (possibly non-canonical) enrollment row, bypassing the canonical upsert —
    simulates persisted legacy state (e.g. a bare 'SPX' enrolled before the F25 fix)."""
    con = _sqlite3.connect(str(dbp))
    try:
        con.execute(
            "INSERT INTO logging_universe (ticker, category, enrollment_source, "
            "enrolled_ts_utc, last_seen_ts_utc) VALUES (?,?,?,?,?)",
            (ticker, category, "legacy", ts, ts),
        )
        con.commit()
    finally:
        con.close()












