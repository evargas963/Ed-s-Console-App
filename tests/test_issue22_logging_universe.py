"""
Issue 22 — durable logging_universe enrollment (EdDB) and bounded user cap semantics.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

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


def test_issue22_user_enrollment_persists_across_db_instances(tmp_path):
    dbp = tmp_path / "i22.db"
    now = time.time()
    db1 = EdDB(dbp)
    db1.logging_universe_sync_core(["SPY", "QQQ"], now)
    db1.logging_universe_upsert_user_persisted("XLF", "test_enroll_src", now + 1)

    db2 = EdDB(dbp)
    rows = {r["ticker"].upper(): r for r in db2.logging_universe_list_rows()}
    assert rows["SPY"]["category"] == "core"
    assert rows["XLF"]["category"] == "user_persisted"
    assert rows["XLF"]["enrollment_source"] == "test_enroll_src"


def test_issue22_remove_user_not_core(tmp_path):
    dbp = tmp_path / "i22b.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], now)
    db.logging_universe_upsert_user_persisted("XLE", "t", now)
    assert db.logging_universe_remove_user_persisted("XLE")
    assert not db.logging_universe_remove_user_persisted("SPY")
    tickers = [r["ticker"].upper() for r in db.logging_universe_list_rows()]
    assert "XLE" not in tickers
    assert "SPY" in tickers


def test_issue22_cap_oldest_user_eviction_order(tmp_path):
    dbp = tmp_path / "i22c.db"
    t0 = 1_000_000.0
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], t0)
    db.logging_universe_upsert_user_persisted("AAA", "a", t0 + 1)
    db.logging_universe_upsert_user_persisted("BBB", "b", t0 + 2)
    assert db.logging_universe_oldest_user_persisted_ticker() == "AAA"
    db.logging_universe_remove_user_persisted("AAA")
    assert db.logging_universe_oldest_user_persisted_ticker() == "BBB"


def test_issue22_fifo_tiebreak_matches_oldest_enrolled_ts(tmp_path):
    """Same enrolled_ts: FIFO uses ticker tie-break; oldest must equal fifo head."""
    db = EdDB(tmp_path / "i22tie.db")
    ts = 42.0
    db.logging_universe_sync_core(["SPY"], ts)
    db.logging_universe_upsert_user_persisted("ZZZ", "z", ts)
    db.logging_universe_upsert_user_persisted("AAA", "a", ts)
    assert db.logging_universe_eviction_candidates_fifo() == ["AAA", "ZZZ"]
    assert db.logging_universe_oldest_user_persisted_ticker() == "AAA"


def test_issue22_background_log_timestamp_updates(tmp_path):
    dbp = tmp_path / "i22d.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["IWM"], now)
    db.logging_universe_touch_background_log("IWM", now + 100)
    rows = {r["ticker"].upper(): r for r in db.logging_universe_list_rows()}
    assert rows["IWM"]["last_background_log_ts_utc"] == pytest.approx(now + 100)


def test_issue22_user_persisted_count(tmp_path):
    dbp = tmp_path / "i22e.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY", "QQQ"], now)
    assert db.logging_universe_user_persisted_count() == 0
    db.logging_universe_upsert_user_persisted("XOP", "x", now)
    assert db.logging_universe_user_persisted_count() == 1


def test_issue22_core_and_pinned_never_eviction_candidates(tmp_path):
    dbp = tmp_path / "i22prot.db"
    t0 = 1_000_000.0
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], t0)
    db.logging_universe_upsert_user_persisted("U1", "s", t0 + 1)
    db.logging_universe_upsert_user_persisted("U2", "s", t0 + 2)
    db.logging_universe_upsert_pinned("PIN1", "s", t0 + 3)
    fifo = db.logging_universe_eviction_candidates_fifo()
    assert fifo == ["U1", "U2"]
    prot = db.logging_universe_protected_tickers()
    assert "SPY" in prot and "PIN1" in prot
    for r in db.logging_universe_list_rows_audit():
        cat = r.get("category")
        if cat in ("core", "pinned"):
            assert r.get("eviction_status") == "protected"
        elif cat == "user_persisted":
            assert r.get("eviction_status") == "eligible"


def test_issue22_eviction_only_user_persisted_remove(tmp_path):
    dbp = tmp_path / "i22ev.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], now)
    db.logging_universe_upsert_pinned("PINX", "s", now)
    db.logging_universe_upsert_user_persisted("USRX", "s", now)
    assert not db.logging_universe_remove_user_persisted("PINX")
    assert db.logging_universe_remove_user_persisted("USRX")
    assert not db.logging_universe_remove_user_persisted("SPY")
    by_cat = _tickers_by_cat(db)
    assert "USRX" not in by_cat["user_persisted"]
    assert "PINX" in by_cat["pinned"]


def test_issue22_fifo_eviction_order(tmp_path):
    dbp = tmp_path / "i22fifo.db"
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], 1.0)
    db.logging_universe_upsert_user_persisted("AAA", "a", 10.0)
    db.logging_universe_upsert_user_persisted("BBB", "b", 20.0)
    db.logging_universe_upsert_user_persisted("CCC", "c", 30.0)
    assert db.logging_universe_eviction_candidates_fifo() == ["AAA", "BBB", "CCC"]
    assert db.logging_universe_oldest_user_persisted_ticker() == "AAA"
    db.logging_universe_record_eviction(
        evicted_ticker="AAA",
        evicted_ts_utc=99.0,
        reason="test_fifo",
        cap_limit=48,
        incoming_ticker="NEW",
        incoming_enrollment_source="test",
    )
    assert db.logging_universe_remove_user_persisted("AAA")
    assert db.logging_universe_eviction_candidates_fifo() == ["BBB", "CCC"]
    ev = db.logging_universe_recent_evictions(limit=1)
    assert ev and ev[0]["evicted_ticker"] == "AAA"
    assert ev[0]["reason"] == "test_fifo"
    assert ev[0]["incoming_ticker"] == "NEW"


def test_issue22_remove_non_core_covers_pinned(tmp_path):
    dbp = tmp_path / "i22rm.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY"], now)
    db.logging_universe_upsert_pinned("PINZ", "s", now)
    assert db.logging_universe_remove_non_core("PINZ")
    assert "PINZ" not in [r["ticker"].upper() for r in db.logging_universe_list_rows()]


def test_issue22_panel_auto_sync_and_prune_category(tmp_path):
    from market_context import market_context_panel_symbols_excluding_core

    dbp = tmp_path / "panel_auto.db"
    t0 = 1_700_000_000.0
    edb = EdDB(dbp)
    minimal_core = ["SPY"]
    edb.logging_universe_sync_core(minimal_core, t0)
    panel = market_context_panel_symbols_excluding_core(frozenset(x.upper() for x in minimal_core))
    assert "WMT" in panel
    assert "NVDA" in panel  # SPY_TOP member; excluded only when present in core_upper
    r1 = edb.logging_universe_sync_panel_auto(panel, t0 + 1.0)
    assert r1["desired"] == len(panel)
    by_t = {row["ticker"].upper(): row["category"] for row in edb.logging_universe_list_rows()}
    assert by_t["SPY"] == "core"
    assert by_t.get("WMT") == "panel_auto"
    auth = edb.logging_universe_authoritative_tickers()
    assert "WMT" in auth and "SPY" in auth

    r2 = edb.logging_universe_sync_panel_auto(["WMT", "FN"], t0 + 2.0)
    assert r2["desired"] == 2
    panel_rows = {row["ticker"].upper() for row in edb.logging_universe_list_rows() if row["category"] == "panel_auto"}
    assert panel_rows == {"WMT", "FN"}

    removed = edb.logging_universe_prune_invalid_enrollments()
    assert isinstance(removed, list)


def test_issue22_scheduler_tickers_match_logging_universe(tmp_path):
    dbp = tmp_path / "i22sched.db"
    now = time.time()
    db = EdDB(dbp)
    db.logging_universe_sync_core(["SPY", "QQQ"], now)
    db.logging_universe_upsert_user_persisted("ZZU", "s", now)
    db.logging_universe_upsert_pinned("ZZP", "s", now + 1)
    auth = db.logging_universe_authoritative_tickers()
    sched = db.logging_universe_scheduler_tickers()
    assert auth == sched
    assert set(auth) == {"SPY", "QQQ", "ZZU", "ZZP"}


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


def test_api_logger_universe_audit_v2_shape(monkeypatch, tmp_path):
    import db as dbmod
    import server as srv

    dbp = tmp_path / "apiu.db"
    now = time.time()
    edb = EdDB(dbp)
    edb.logging_universe_sync_core(["SPY"], now)
    edb.logging_universe_upsert_user_persisted("AUD1", "api_test", now + 1)
    edb.logging_universe_upsert_pinned("AUDP", "api_test", now + 2)
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    prev_core = list(srv.CORE_TICKERS)
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        with srv._logger_lock:
            merged = list(srv.CORE_TICKERS)
            for r in edb.logging_universe_list_rows():
                if r.get("category") in ("user_persisted", "pinned", "panel_auto"):
                    t = (r.get("ticker") or "").upper().strip()
                    if t and t not in merged:
                        merged.append(t)
            srv._logger_tickers[:] = merged

        from starlette.testclient import TestClient

        with TestClient(srv.app) as client:
            r = client.get("/api/logger/universe")
            assert r.status_code == 200
            body = r.json()
            assert body.get("schema") == "logging_universe_audit_v2"
            assert "protected_symbols" in body
            assert "eviction_candidates_fifo_user_persisted" in body
            assert "recent_evictions" in body
            assert "logging_universe_rows" in body
            rows = body["logging_universe_rows"]
            assert isinstance(rows, list) and len(rows) >= 3
            by_t = {(x["ticker"] or "").upper(): x for x in rows}
            assert by_t["SPY"]["eviction_status"] == "protected"
            assert by_t["AUDP"]["eviction_status"] == "protected"
            assert by_t["AUD1"]["eviction_status"] == "eligible"
            for key in ("category", "enrollment_source", "enrolled_ts_utc", "last_seen_ts_utc"):
                assert key in by_t["AUD1"]
            rcat = client.get("/api/logger/universe/by-category", params={"category": "pinned"})
            assert rcat.status_code == 200
            assert rcat.json()["count"] == 1
            assert rcat.json()["rows"][0]["ticker"].upper() == "AUDP"
    finally:
        srv.CORE_TICKERS[:] = prev_core


def test_issue22_add_logger_evicts_only_oldest_user_persisted(monkeypatch, tmp_path):
    """FIFO eviction runs only when ED_LOGGING_UNIVERSE_FIFO_EVICTION=1 (legacy opt-in)."""
    import db as dbmod
    import server as srv

    dbp = tmp_path / "evsrv.db"
    edb = EdDB(dbp)
    t0 = 1000.0
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "MAX_USER_PERSISTED_LOGGING_TICKERS", 2)
    monkeypatch.setenv("ED_LOGGING_UNIVERSE_FIFO_EVICTION", "1")
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    edb.logging_universe_sync_core(["SPY"], t0)
    edb.logging_universe_upsert_pinned("PINK", "s", t0 + 0.5)
    edb.logging_universe_upsert_user_persisted("UOLD", "s", t0 + 1)
    edb.logging_universe_upsert_user_persisted("UMID", "s", t0 + 2)
    srv._hydrate_logger_tickers_from_db()
    assert srv._add_logger_ticker("UNEWO", enrollment_source="test") is True
    by_cat = _tickers_by_cat(edb)
    assert "UOLD" not in by_cat["user_persisted"]
    assert "UNEWO" in by_cat["user_persisted"]
    assert "UMID" in by_cat["user_persisted"]
    assert "PINK" in by_cat["pinned"]
    assert "SPY" in by_cat["core"]
    ev = edb.logging_universe_recent_evictions(limit=3)
    assert any(e.get("evicted_ticker") == "UOLD" for e in ev)


def test_issue22_add_logger_no_eviction_when_fifo_disabled(monkeypatch, tmp_path):
    """Without ED_LOGGING_UNIVERSE_FIFO_EVICTION, cap is ignored — no silent eviction."""
    import db as dbmod
    import server as srv

    dbp = tmp_path / "noev.db"
    edb = EdDB(dbp)
    t0 = 1000.0
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "MAX_USER_PERSISTED_LOGGING_TICKERS", 2)
    monkeypatch.delenv("ED_LOGGING_UNIVERSE_FIFO_EVICTION", raising=False)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    edb.logging_universe_sync_core(["SPY"], t0)
    edb.logging_universe_upsert_user_persisted("UOLD", "s", t0 + 1)
    edb.logging_universe_upsert_user_persisted("UMID", "s", t0 + 2)
    srv._hydrate_logger_tickers_from_db()
    assert srv._add_logger_ticker("UNEWO", enrollment_source="test") is True
    by_cat = _tickers_by_cat(edb)
    assert "UOLD" in by_cat["user_persisted"]
    assert "UMID" in by_cat["user_persisted"]
    assert "UNEWO" in by_cat["user_persisted"]


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


def test_db_write_path_d_lifespan_loader_populates_and_counts(monkeypatch, tmp_path):
    """DB-WRITE-PATH-FIXES (d): the loader the lifespan calls (start_logger ->
    _hydrate_logger_tickers_from_db) still performs the full DB load — it populates user_persisted
    tickers AND increments the import-defer guard counter. Proves the heavy work was MOVED, not
    dropped."""
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "deferd.db")
    now = time.time()
    edb.logging_universe_sync_core(["SPY"], now)
    edb.logging_universe_upsert_user_persisted("XLF", "test_src", now + 1)
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    prev_core = list(srv.CORE_TICKERS)
    before = srv._LOGGING_UNIVERSE_DB_LOAD_COUNT
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        srv._hydrate_logger_tickers_from_db()
        assert srv._LOGGING_UNIVERSE_DB_LOAD_COUNT == before + 1
        with srv._logger_lock:
            assert "XLF" in srv._logger_tickers
            assert "SPY" in srv._logger_tickers
    finally:
        srv.CORE_TICKERS[:] = prev_core


# ─────────────────────────────────────────────────────────────────────────────
# TICKER-PREVIEW-NO-ENROLL — viewing a symbol must not enroll it (operator 2026-05-31)
# ─────────────────────────────────────────────────────────────────────────────
def test_ticker_preview_view_touch_never_enrolls(monkeypatch, tmp_path):
    """TICKER-PREVIEW-NO-ENROLL: _touch_tracked_ticker_view enrolls NOTHING. For an un-enrolled
    symbol it is a pure no-op (no logging_universe row, no in-memory append); for an already-
    enrolled symbol it only refreshes last_seen."""
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "view.db")
    now = time.time()
    edb.logging_universe_sync_core(["SPY"], now)
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)

    prev = None
    with srv._logger_lock:
        prev = list(srv._logger_tickers)
        srv._logger_tickers[:] = ["SPY"]
    try:
        # Un-enrolled symbol: viewing must NOT create a row or append in memory.
        srv._touch_tracked_ticker_view("ZVQ")
        users = {r["ticker"].upper() for r in edb.logging_universe_list_rows()
                 if r["category"] == "user_persisted"}
        assert "ZVQ" not in users
        with srv._logger_lock:
            assert "ZVQ" not in srv._logger_tickers

        # Already-enrolled symbol: touch refreshes last_seen, creates no new enrollment.
        edb.logging_universe_upsert_user_persisted("XLF", "pretest", now)
        with srv._logger_lock:
            srv._logger_tickers.append("XLF")
        ls0 = {r["ticker"].upper(): r for r in edb.logging_universe_list_rows()}["XLF"]["last_seen_ts_utc"]
        srv._touch_tracked_ticker_view("XLF")
        rows1 = {r["ticker"].upper(): r for r in edb.logging_universe_list_rows()}
        users1 = {t for t, r in rows1.items() if r["category"] == "user_persisted"}
        assert users1 == {"XLF"}, "no new user_persisted enrollment from a view-touch"
        assert rows1["XLF"]["last_seen_ts_utc"] >= ls0
    finally:
        with srv._logger_lock:
            srv._logger_tickers[:] = prev


def test_ticker_preview_view_endpoint_no_enroll_track_enrolls(monkeypatch, tmp_path):
    """TICKER-PREVIEW-NO-ENROLL: a VIEW endpoint (/api/accuracy) does NOT enroll an arbitrary
    symbol; the explicit TRACK endpoint (/api/logger/add) DOES. Route functions are called
    directly (sync handlers) to avoid full-lifespan flakiness while still exercising the real
    enroll/no-enroll branch."""
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "previewapi.db")
    now = time.time()
    edb.logging_universe_sync_core(["SPY"], now)
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.delenv("ED_LOGGING_UNIVERSE_FIFO_EVICTION", raising=False)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)

    prev_core = list(srv.CORE_TICKERS)
    prev = None
    with srv._logger_lock:
        prev = list(srv._logger_tickers)
        srv._logger_tickers[:] = ["SPY"]
    try:
        srv.CORE_TICKERS[:] = ["SPY"]

        # VIEW: peek accuracy for an un-enrolled ticker → no enrollment.
        srv.get_accuracy(ticker="ZVQ")
        users = {r["ticker"].upper() for r in edb.logging_universe_list_rows()
                 if r["category"] == "user_persisted"}
        assert "ZVQ" not in users, "VIEW endpoint /api/accuracy must not enroll"

        # TRACK: explicit add → enrolls.
        srv.logger_add(ticker="ZTK")
        users2 = {r["ticker"].upper() for r in edb.logging_universe_list_rows()
                  if r["category"] == "user_persisted"}
        assert "ZTK" in users2, "explicit track /api/logger/add must enroll"
    finally:
        srv.CORE_TICKERS[:] = prev_core
        with srv._logger_lock:
            srv._logger_tickers[:] = prev


def test_step3_fetch_state_does_not_enroll_viewed_ticker():
    """LIVE_OPERATOR_MODE_RESET_V1 Step 3: a Tier C recompute (_fetch_state) is a VIEW —
    it touches last-seen only (no-op for un-enrolled symbols, proven by
    test_ticker_preview_view_touch_never_enrolls). Enrollment stays explicit via
    /api/logger/add | /api/logger/pin."""
    import inspect

    import server as srv

    src = inspect.getsource(srv._fetch_state)
    assert "_register_tracked_ticker(" not in src, "_fetch_state must not auto-enroll viewed tickers"
    assert "_touch_tracked_ticker_view(ticker)" in src
    add_src = inspect.getsource(srv.logger_add)
    assert "_register_tracked_ticker(" in add_src, "explicit track route remains the enrollment path"


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


def test_f25_lu_enroll_index_alias_is_one_identity(tmp_path):
    """A + B + C: enroll via any alias, the row IS the canonical '$SPX'; the reverse alias hits it;
    enrolling both aliases yields ONE semantic instrument (no duplicate)."""
    now = time.time()
    db = EdDB(tmp_path / "f25a.db")
    db.logging_universe_upsert_user_persisted("SPX", "t", now)          # A: enroll bare
    assert _lu_rows(tmp_path / "f25a.db") == ["$SPX"], "enroll('SPX') must store canonical $SPX"
    # C: enrolling the $-alias must not create a second instrument row
    db.logging_universe_upsert_user_persisted("$SPX", "t", now + 1)
    idx_rows = [r for r in _lu_rows(tmp_path / "f25a.db") if r in ("SPX", "$SPX", "spx", "$spx")]
    assert idx_rows == ["$SPX"], f"SPX/$SPX collapsed to one row expected, got {idx_rows}"


def test_f25_lu_delete_and_touch_via_alternate_alias(tmp_path):
    """E: a row enrolled as '$SPX' is removable/updatable through the bare 'SPX' alias."""
    now = time.time()
    db = EdDB(tmp_path / "f25e.db")
    db.logging_universe_upsert_user_persisted("$SPX", "t", now)
    assert "$SPX" in _lu_rows(tmp_path / "f25e.db")
    # touch via bare alias updates the canonical row (no error, no new row)
    db.logging_universe_touch_seen("SPX", now + 5)
    assert _lu_rows(tmp_path / "f25e.db").count("$SPX") == 1
    # delete via bare alias removes the canonical row
    assert db.logging_universe_remove_user_persisted("SPX") is True
    assert "$SPX" not in _lu_rows(tmp_path / "f25e.db")


def test_f25_lu_reads_and_membership_are_canonical(tmp_path):
    """D: authoritative/scheduler reads and protection membership return canonical identity;
    equities (SPY/QQQ/IWM) are unchanged."""
    now = time.time()
    db = EdDB(tmp_path / "f25d.db")
    db.logging_universe_sync_core(["SPY", "QQQ", "IWM"], now)
    db.logging_universe_upsert_pinned("SPX", "t", now)
    auth = db.logging_universe_authoritative_tickers()
    assert "$SPX" in auth and "SPX" not in auth
    for eq in ("SPY", "QQQ", "IWM"):
        assert eq in auth, f"equity {eq} must remain unchanged"
    prot = set(db.logging_universe_protected_tickers())
    assert "$SPX" in prot  # pinned is protected, under canonical identity


def test_f25_lu_migration_renames_legacy_bare_row(tmp_path):
    """F + H: a persisted legacy 'SPX' row migrates to '$SPX'; a re-run is a no-op (idempotent).
    dry-run mutates nothing."""
    dbp = tmp_path / "f25f.db"
    db = EdDB(dbp)
    db._ensure_logging_universe_table()
    _insert_legacy_lu_row(dbp, "SPX", "user_persisted", 100.0)
    assert "SPX" in _lu_rows(dbp)

    dry = db.logging_universe_migrate_canonical_ticker_identity(dry_run=True)
    assert dry["renames"] == [{"legacy": "SPX", "canonical": "$SPX"}]
    assert "SPX" in _lu_rows(dbp), "dry-run must NOT mutate the DB"

    real = db.logging_universe_migrate_canonical_ticker_identity(dry_run=False)
    assert real["renames"] == [{"legacy": "SPX", "canonical": "$SPX"}]
    assert _lu_rows(dbp) == ["$SPX"]

    again = db.logging_universe_migrate_canonical_ticker_identity(dry_run=False)
    assert again["renames"] == [] and again["merges"] == [], "migration must be idempotent"
    assert again["unchanged"] >= 1


def test_f25_lu_migration_merges_collision_deterministically(tmp_path):
    """G: legacy 'SPX' (user_persisted) + canonical '$SPX' (pinned) already coexist. The migration
    folds them into ONE '$SPX' row, keeping the STRONGER category (pinned), earliest enroll, latest
    seen — deterministic, no silent loss, and the row count drops by exactly one."""
    dbp = tmp_path / "f25g.db"
    db = EdDB(dbp)
    db._ensure_logging_universe_table()
    _insert_legacy_lu_row(dbp, "SPX", "user_persisted", 100.0)   # earlier enroll, weaker cat
    _insert_legacy_lu_row(dbp, "$SPX", "pinned", 200.0)          # later enroll, stronger cat
    assert set(_lu_rows(dbp)) == {"SPX", "$SPX"}

    rep = db.logging_universe_migrate_canonical_ticker_identity(dry_run=False)
    assert rep["merges"] == [{"legacy": "SPX", "canonical": "$SPX", "category": "pinned"}]
    assert _lu_rows(dbp) == ["$SPX"], "collision folded to a single canonical row"
    assert rep["rows_after"] == rep["rows_before"] - 1

    con = _sqlite3.connect(str(dbp))
    try:
        cat, enr, seen = con.execute(
            "SELECT category, enrolled_ts_utc, last_seen_ts_utc FROM logging_universe "
            "WHERE ticker = '$SPX'").fetchone()
    finally:
        con.close()
    assert cat == "pinned"          # stronger category survives
    assert enr == 100.0             # earliest enrollment preserved
    assert seen == 200.0            # latest activity preserved


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
