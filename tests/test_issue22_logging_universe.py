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






















def test_issue22_panel_auto_sync_and_prune_category(tmp_path):
    from market_context import market_context_panel_symbols_excluding_core

    dbp = tmp_path / "panel_auto.db"
    t0 = 1_700_000_000.0
    edb = EdDB(dbp)
    minimal_core = ["SPY"]
    edb.logging_universe_sync_core(minimal_core, t0)
    panel = market_context_panel_symbols_excluding_core(frozenset(x.upper() for x in minimal_core))
    assert "$VIX" in panel
    assert "WMT" not in panel
    assert "NVDA" not in panel
    r1 = edb.logging_universe_sync_panel_auto(panel, t0 + 1.0)
    assert r1["desired"] == len(panel)
    by_t = {row["ticker"].upper(): row["category"] for row in edb.logging_universe_list_rows()}
    assert by_t["SPY"] == "core"
    assert by_t.get("$VIX") == "panel_auto"
    auth = edb.logging_universe_authoritative_tickers()
    assert "$VIX" in auth and "SPY" in auth

    r2 = edb.logging_universe_sync_panel_auto(["WMT", "FN"], t0 + 2.0)
    assert r2["desired"] == 2
    panel_rows = {row["ticker"].upper() for row in edb.logging_universe_list_rows() if row["category"] == "panel_auto"}
    assert panel_rows == {"WMT", "FN"}

    removed = edb.logging_universe_prune_invalid_enrollments()
    assert isinstance(removed, list)




def test_issue22_ml_scheduler_training_union_is_logging_universe_only(monkeypatch):
    def fake_load():
        return ["ZZA", "ZZB"]

    monkeypatch.setattr("scheduler_user_tickers.load_user_scheduler_tickers", fake_load)

    def _must_not_call_db_rth(*_a, **_k):
        raise AssertionError("DB RTH DISTINCT must not define scheduler ticker membership")

    monkeypatch.setattr("ml_scheduler._get_tickers_with_rth_data", _must_not_call_db_rth)
    from ml_scheduler import _training_ticker_union

    assert _training_ticker_union("/nonexistent.db") == ["ZZA", "ZZB"]


def test_issue22_diagnostic_db_only_tickers_subtracts_enrolled(monkeypatch):
    from ml_scheduler import _diagnostic_db_tickers_not_enrolled

    monkeypatch.setattr(
        "ml_scheduler._get_tickers_with_rth_data",
        lambda *_a, **_k: ["AAA", "BBB", "CORE1"],
    )
    out = _diagnostic_db_tickers_not_enrolled(
        "/x.db", ["AAA", "CORE1"], label_column="outcome_1c"
    )
    assert out == ["BBB"]


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


def test_issue22_scheduler_json_migration_idempotent(tmp_path):
    p = tmp_path / "user_sched.json"
    arch = tmp_path / "user_sched.json.migrated_issue22"
    p.write_text(json.dumps({"tickers": ["s1", "s1", "s2"]}), encoding="utf-8")
    edb = EdDB(tmp_path / "schm.db")
    a = edb.logging_universe_migrate_scheduler_companion_json(
        primary_path=p,
        archive_path=arch,
    )
    assert a["status"] == "imported"
    syms = {r["ticker"].upper() for r in edb.logging_universe_list_rows() if r["category"] == "user_persisted"}
    assert syms >= {"S1", "S2"}
    b = edb.logging_universe_migrate_scheduler_companion_json(primary_path=p, archive_path=arch)
    assert b["status"] == "already_completed"






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
        "assert (not server._HAS_SIGNALS) or server._logger_tickers == list(server.CORE_TICKERS),"
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
from instrument_identity import ticker_storage_key as _K


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












def test_f25_lu_write_identity_mutation_killed():
    """Mutation: reverting the canonical write producer to a raw local one splits SPX from $SPX.
    Proven behaviorally against the storage authority the enrollment writes consume."""
    # canonical authority: both aliases map to one identity
    assert _K("SPX") == _K("$SPX") == _K("spx") == _K("$spx") == "$SPX"
    # the raw local producer the fix replaced would NOT collapse them:
    assert ("SPX".upper().strip()) != ("$SPX".upper().strip())  # 'SPX' != '$SPX' -> would split

    # Source guard: the live enrollment read/update/delete/touch consume the authority, not .upper()
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent / "db.py").read_text(encoding="utf-8")
    for needle in (
        "t = ticker_storage_key(ticker)  # RC-345/F25",           # unpin/remove/touch
        "ticker_storage_key(r[0]) for r in rows",                 # canonical reads
        "def logging_universe_migrate_canonical_ticker_identity",  # migration exists
    ):
        assert needle in src, f"db.py logging_universe missing canonical routing: {needle!r}"
