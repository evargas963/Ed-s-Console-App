"""Snapshot-collection eligibility — quote panel ≠ snapshot enrollment.

A permanently vendor-refused symbol stays quotable for confluence and must not
re-enter panel_auto, must not burn a chain-gate slot after restart, and must
not trip F6 PARTIAL-DARK off a leftover last_background_log clock.

# universal-scope-ok: SATS / $TNX appear only as established quote-panel examples
# of valid-but-not-snapshot-collectable symbols. Product code has no ticker
# special-case; these names are fixtures for the existing panel tables.
"""
from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

from app.market_data import snapshot_eligibility as se
from instrument_identity import ticker_storage_key


def _ledger(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_eligibility_is_one_computation_that_consumes_ledger():
    sig = inspect.signature(se.snapshot_collection_eligible)
    assert "refused" not in sig.parameters
    assert "ledger_path" in sig.parameters
    assert not hasattr(se, "enrollable_panel_auto")
    assert not hasattr(se, "permanent_cache_entry")


def test_ledger_replay_last_admission_wins(tmp_path):
    p = _ledger(
        tmp_path / "q.jsonl",
        [
            {"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3},
            {"event": "backoff", "ticker": "ZZDE", "failures": 4},  # must not clear
            {"event": "quarantine_permanent", "ticker": "ZZOK", "failures": 3},
            {"event": "operator_release", "ticker": "ZZOK"},
        ],
    )
    refused = se.permanent_refusals_from_ledger(p)
    assert ticker_storage_key("ZZDE") in refused
    assert ticker_storage_key("ZZOK") not in refused
    out = se.snapshot_collection_eligible(["CDE", "zzde", "KTOS", "CDE"], ledger_path=p)
    assert out == ["CDE", "KTOS"]


def test_missing_or_junk_ledger_is_empty_refused(tmp_path):
    assert se.permanent_refusals_from_ledger(None) == frozenset()
    assert se.permanent_refusals_from_ledger(tmp_path / "nope.jsonl") == frozenset()
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not-json\n{bad\n", encoding="utf-8")
    assert se.permanent_refusals_from_ledger(junk) == frozenset()
    assert se.snapshot_collection_eligible(["CDE"], ledger_path=junk) == ["CDE"]


def test_quote_panel_still_lists_refused_holdings(tmp_path):
    """IWM holdings stay on the quote panel; eligibility is a different function."""
    import market_context as mc

    panel = mc.market_context_panel_symbols_excluding_core(frozenset())
    assert "SATS" in panel, "EchoStar remains a quote-panel holding"
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "SATS", "failures": 3}],
    )
    eligible = se.snapshot_collection_eligible(panel, ledger_path=ledger)
    assert ticker_storage_key("SATS") not in eligible
    assert "SATS" in panel


def test_valid_symbol_is_not_automatically_snapshot_collectable(tmp_path):
    from production_universe import is_valid_production_ticker

    assert is_valid_production_ticker("SATS") is True
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "SATS", "failures": 3}],
    )
    assert "SATS" not in se.snapshot_collection_eligible(["SATS", "CDE"], ledger_path=ledger)
    assert "CDE" in se.snapshot_collection_eligible(["SATS", "CDE"], ledger_path=ledger)


def test_tnx_stays_quote_only_not_snapshot_candidate():
    import market_context as mc
    from market_context import market_context_panel_symbols_excluding_core

    panel = market_context_panel_symbols_excluding_core(frozenset(["SPY", "QQQ", "IWM"]))
    assert "$TNX" not in panel
    assert "$TNX" not in se.snapshot_collection_eligible(panel, ledger_path=None)
    src = Path(mc.__file__).read_text(encoding="utf-8")
    assert '_fetch("$TNX")' in src


def test_stale_historical_clock_cannot_restore_eligibility(tmp_path):
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3}],
    )
    # A leftover last_background_log is not an input to eligibility.
    out = se.snapshot_collection_eligible(["ZZDE", "CDE"], ledger_path=ledger)
    assert out == ["CDE"]


def test_operator_release_restores_only_through_canonical_lifecycle(monkeypatch, tmp_path):
    import db as edb
    import server as srv

    database = edb.EdDB(str(tmp_path / "u.db"))
    now = time.time()
    database.logging_universe_sync_panel_auto(["ZZDE", "CDE"], now)
    ledger = tmp_path / "q.jsonl"
    ledger.write_text("", encoding="utf-8")
    monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER", ledger)
    monkeypatch.setattr(srv, "get_db", lambda: database)
    monkeypatch.setattr(srv, "_logger_tickers", ["ZZDE", "CDE"])
    tk = ticker_storage_key("ZZDE")
    srv._terrain_quarantine.pop(tk, None)
    srv._terrain_consecutive_fails.pop(tk, None)
    for _ in range(srv.TERRAIN_QUARANTINE_HARD_FAILS):
        srv._note_terrain_failure(tk, "chain fetch failed (HTTP 400)", "hard")
    assert tk in se.permanent_refusals_from_ledger(ledger)
    assert "ZZDE" not in se.snapshot_collection_eligible(["ZZDE", "CDE"], ledger_path=ledger)
    # Leftover clock after drop cannot restore: row is gone and eligibility still refuses.
    tickers = {r["ticker"].upper() for r in database.logging_universe_list_rows()
               if r.get("category") == "panel_auto"}
    assert "ZZDE" not in tickers
    released = srv.terrain_quarantine_release("ZZDE")
    assert released["ticker"] == tk
    assert tk not in se.permanent_refusals_from_ledger(ledger)
    assert se.snapshot_collection_eligible(["ZZDE", "CDE"], ledger_path=ledger) == ["ZZDE", "CDE"]
    monkeypatch.setattr(srv, "_market_context_panel_auto_candidates", lambda: ["CDE", "ZZDE"])
    srv._sync_market_context_panel_into_logging_universe(database, now + 2)
    tickers2 = {r["ticker"].upper() for r in database.logging_universe_list_rows()
                if r.get("category") == "panel_auto"}
    assert "ZZDE" in tickers2
    assert "CDE" in tickers2


def test_f6_excludes_ledger_refused_from_partial_dark(monkeypatch, tmp_path):
    import tools.console_liveness_check as liv

    now = time.time()
    dbp = tmp_path / "live.db"
    import sqlite3

    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.execute("INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)", (now - 5, "paths"))
    con.execute(
        "CREATE TABLE logging_universe ("
        "ticker TEXT PRIMARY KEY, category TEXT NOT NULL, enrollment_source TEXT, "
        "enrolled_ts_utc REAL NOT NULL, last_seen_ts_utc REAL NOT NULL, "
        "last_background_log_ts_utc REAL)"
    )
    con.executemany(
        "INSERT INTO logging_universe VALUES (?,?,?,?,?,?)",
        [
            ("SPY", "core", "test", 1.0, 1.0, now - 5),
            ("ZZDE", "panel_auto", "test", 1.0, 1.0, now - 8_000_000),
        ],
    )
    con.commit()
    con.close()
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3}],
    )
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(liv, "quarantine_ledger_path", lambda: ledger)
    assert liv.check(str(dbp)) == 0


def test_panel_sync_does_not_reinsert_refused(monkeypatch, tmp_path):
    import db as edb
    db_path = tmp_path / "u.db"
    database = edb.EdDB(str(db_path))
    now = time.time()
    database.logging_universe_sync_panel_auto(["CDE", "ZZDE"], now)
    assert {r["ticker"].upper() for r in database.logging_universe_list_rows()} >= {"CDE", "ZZDE"}
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3}],
    )
    import server as srv

    monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER", ledger)
    monkeypatch.setattr(
        srv,
        "_market_context_panel_auto_candidates",
        lambda: ["CDE", "ZZDE"],
    )
    srv._sync_market_context_panel_into_logging_universe(database, now + 1)
    tickers = {r["ticker"].upper() for r in database.logging_universe_list_rows()
               if r.get("category") == "panel_auto"}
    assert "CDE" in tickers
    assert "ZZDE" not in tickers


def test_roster_uses_authoritative_enrollment_after_hydrate(monkeypatch, tmp_path):
    """Logger roster is logging_universe_authoritative_tickers, not a second set."""
    import db as edb
    import server as srv

    database = edb.EdDB(str(tmp_path / "u.db"))
    now = time.time()
    database.logging_universe_sync_core(["SPY"], now)
    database.logging_universe_sync_panel_auto(["ZZDE", "CDE"], now)
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3}],
    )
    monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER", ledger)
    monkeypatch.setattr(srv, "get_db", lambda: database)
    monkeypatch.setattr(srv, "CORE_TICKERS", ["SPY"])
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_market_context_panel_auto_candidates", lambda: ["CDE", "ZZDE"])
    srv._terrain_quarantine.pop(ticker_storage_key("ZZDE"), None)
    roster = srv._load_persisted_tickers()
    keyed = {ticker_storage_key(t) for t in roster}
    assert ticker_storage_key("ZZDE") not in keyed
    assert ticker_storage_key("CDE") in keyed
    assert ticker_storage_key("SPY") in keyed
    auth = {ticker_storage_key(t) for t in database.logging_universe_authoritative_tickers()}
    assert keyed == auth


def test_f6_stale_collectable_still_alarms(monkeypatch, tmp_path):
    """A collectable ticker that went dark must still PARTIAL-DARK."""
    import tools.console_liveness_check as liv

    now = time.time()
    dbp = tmp_path / "stale.db"
    import sqlite3

    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.execute("INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)", (now - 5, "paths"))
    con.execute(
        "CREATE TABLE logging_universe ("
        "ticker TEXT PRIMARY KEY, category TEXT NOT NULL, enrollment_source TEXT, "
        "enrolled_ts_utc REAL NOT NULL, last_seen_ts_utc REAL NOT NULL, "
        "last_background_log_ts_utc REAL)"
    )
    con.executemany(
        "INSERT INTO logging_universe VALUES (?,?,?,?,?,?)",
        [
            ("SPY", "core", "test", 1.0, 1.0, now - 5),
            ("ZZSTALE", "user_persisted", "test", 1.0, 1.0, now - 8_000_000),
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(liv, "quarantine_ledger_path", lambda: None)
    assert liv.check(str(dbp)) == 1


def test_f6_healthy_roster_ok(monkeypatch, tmp_path):
    import tools.console_liveness_check as liv

    now = time.time()
    dbp = tmp_path / "ok.db"
    import sqlite3

    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.execute("INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)", (now - 5, "paths"))
    con.execute(
        "CREATE TABLE logging_universe ("
        "ticker TEXT PRIMARY KEY, category TEXT NOT NULL, enrollment_source TEXT, "
        "enrolled_ts_utc REAL NOT NULL, last_seen_ts_utc REAL NOT NULL, "
        "last_background_log_ts_utc REAL)"
    )
    con.executemany(
        "INSERT INTO logging_universe VALUES (?,?,?,?,?,?)",
        [
            ("SPY", "core", "test", 1.0, 1.0, now - 5),
            ("CDE", "panel_auto", "test", 1.0, 1.0, now - 8),
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(liv, "quarantine_ledger_path", lambda: None)
    assert liv.check(str(dbp)) == 0


def test_f6_transient_soft_backoff_still_alarms(monkeypatch, tmp_path):
    """Soft backoff is venue weather — a stale collectable clock still PARTIAL-DARK."""
    import tools.console_liveness_check as liv

    now = time.time()
    dbp = tmp_path / "soft.db"
    import sqlite3

    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.execute("INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)", (now - 5, "paths"))
    con.execute(
        "CREATE TABLE logging_universe ("
        "ticker TEXT PRIMARY KEY, category TEXT NOT NULL, enrollment_source TEXT, "
        "enrolled_ts_utc REAL NOT NULL, last_seen_ts_utc REAL NOT NULL, "
        "last_background_log_ts_utc REAL)"
    )
    con.executemany(
        "INSERT INTO logging_universe VALUES (?,?,?,?,?,?)",
        [
            ("SPY", "core", "test", 1.0, 1.0, now - 5),
            ("ZTRN", "panel_auto", "test", 1.0, 1.0, now - 8_000_000),
        ],
    )
    con.commit()
    con.close()
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "backoff", "ticker": "ZTRN", "failures": 3, "wait_sec": 60}],
    )
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(liv, "quarantine_ledger_path", lambda: ledger)
    assert liv.check(str(dbp)) == 1


def test_hard_quarantine_writes_ledger_and_drops_panel_auto(monkeypatch, tmp_path):
    import db as edb
    import server as srv

    database = edb.EdDB(str(tmp_path / "u.db"))
    now = time.time()
    database.logging_universe_sync_panel_auto(["ZZDE", "CDE"], now)
    ledger = tmp_path / "q.jsonl"
    ledger.write_text("", encoding="utf-8")
    monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER", ledger)
    monkeypatch.setattr(srv, "get_db", lambda: database)
    monkeypatch.setattr(srv, "_logger_tickers", ["ZZDE", "CDE"])
    tk = ticker_storage_key("ZZDE")
    srv._terrain_quarantine.pop(tk, None)
    srv._terrain_consecutive_fails.pop(tk, None)
    for _ in range(srv.TERRAIN_QUARANTINE_HARD_FAILS):
        srv._note_terrain_failure(tk, "chain fetch failed (HTTP 400)", "hard")
    tickers = {r["ticker"].upper() for r in database.logging_universe_list_rows()
               if r.get("category") == "panel_auto"}
    assert "ZZDE" not in tickers
    assert "CDE" in tickers
    refused = se.permanent_refusals_from_ledger(ledger)
    assert tk in refused
    assert srv._terrain_quarantine.get(tk, {}).get("permanent") is True


def test_hydrate_drops_leftover_panel_auto_row(monkeypatch, tmp_path):
    import db as edb
    import server as srv

    database = edb.EdDB(str(tmp_path / "u.db"))
    now = time.time()
    database.logging_universe_sync_panel_auto(["ZZDE", "CDE"], now)
    ledger = _ledger(
        tmp_path / "q.jsonl",
        [{"event": "quarantine_permanent", "ticker": "ZZDE", "failures": 3}],
    )
    monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER", ledger)
    monkeypatch.setattr(srv, "get_db", lambda: database)
    monkeypatch.setattr(srv, "_logger_tickers", ["ZZDE", "CDE"])
    tk = ticker_storage_key("ZZDE")
    srv._terrain_quarantine.pop(tk, None)
    srv._terrain_consecutive_fails.pop(tk, None)
    n = srv._hydrate_permanent_quarantine_from_ledger()
    assert n >= 1
    tickers = {r["ticker"].upper() for r in database.logging_universe_list_rows()
               if r.get("category") == "panel_auto"}
    assert "ZZDE" not in tickers
    assert "CDE" in tickers


def test_remove_panel_auto_never_touches_core(tmp_path):
    import db as edb

    database = edb.EdDB(str(tmp_path / "u.db"))
    now = time.time()
    database.logging_universe_sync_core(["SPY"], now)
    database.logging_universe_sync_panel_auto(["ZZDE"], now)
    assert database.logging_universe_remove_panel_auto("SPY") is False
    cats = {r["ticker"].upper(): r["category"] for r in database.logging_universe_list_rows()}
    assert cats.get("SPY") == "core"
    assert database.logging_universe_remove_panel_auto("ZZDE") is True
