"""
Issue 22 — durable logging_universe enrollment (EdDB) and bounded user cap semantics.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB


def _tickers_by_cat(db: EdDB) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"core": set(), "pinned": set(), "user_persisted": set()}
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
                if r.get("category") in ("user_persisted", "pinned"):
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
    edb.logging_universe_upsert_pinned("PINNED", "s", t0 + 0.5)
    edb.logging_universe_upsert_user_persisted("UOLD", "s", t0 + 1)
    edb.logging_universe_upsert_user_persisted("UMID", "s", t0 + 2)
    srv._hydrate_logger_tickers_from_db()
    assert srv._add_logger_ticker("UINCOMING", enrollment_source="test") is True
    by_cat = _tickers_by_cat(edb)
    assert "UOLD" not in by_cat["user_persisted"]
    assert "UINCOMING" in by_cat["user_persisted"]
    assert "UMID" in by_cat["user_persisted"]
    assert "PINNED" in by_cat["pinned"]
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
    assert srv._add_logger_ticker("UINCOMING", enrollment_source="test") is True
    by_cat = _tickers_by_cat(edb)
    assert "UOLD" in by_cat["user_persisted"]
    assert "UMID" in by_cat["user_persisted"]
    assert "UINCOMING" in by_cat["user_persisted"]
