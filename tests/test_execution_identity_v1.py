"""execution_identity_v1 — adversarial suite (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1).

All tests run against tmp SQLite databases and tmp CAS roots.  Expected hashes
are recomputed independently with hashlib — never through the module under test.
"""
from __future__ import annotations

import sqlite3

import pytest

import execution_identity as xi


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "exec.db"))
    # minimal dependent tables (production shapes are wider; linkage columns added by migration)
    c.executescript("""
        CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, ts_utc REAL);
        CREATE TABLE production_decision_records (decision_id TEXT PRIMARY KEY, ticker TEXT);
        CREATE TABLE calibration_decision_log (id INTEGER PRIMARY KEY, ticker TEXT);
    """)
    xi.ensure_execution_identity_schema(c)
    yield c
    c.close()


# ── dependent-table linkage (trigger-enforced consistency) ──────────────────


def test_dependent_write_without_registered_identity_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="IDENTITY_MISSING"):
        conn.execute(
            "INSERT INTO snapshots (ticker, ts_utc, decision_id, execution_identity_sha256) VALUES (?,?,?,?)",
            ("SPY", 1.0, "dX", "0" * 64),
        )


def test_quote_only_rows_insert_with_null_identity(conn):
    conn.execute("INSERT INTO snapshots (ticker, ts_utc) VALUES ('SPY', 1.0)")
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


# ── write-path guard ─────────────────────────────────────────────────────────


def test_model_derived_write_without_identity_refused():
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.require_identity_for_model_derived_write(
            is_model_derived=True, decision_id=None, execution_identity_sha256=None,
            surface="snapshots",
        )
    assert e.value.reason == "WRITE_WITHOUT_IDENTITY"


def test_quote_only_write_must_not_carry_identity():
    assert xi.require_identity_for_model_derived_write(
        is_model_derived=False, decision_id=None, execution_identity_sha256=None,
        surface="snapshots",
    ) == "NOT_APPLICABLE"
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.require_identity_for_model_derived_write(
            is_model_derived=False, decision_id="d1", execution_identity_sha256="s",
            surface="snapshots",
        )
    assert e.value.reason == "QUOTE_ONLY_NOT_MODEL_DERIVED"


# ── historical classification (no fabrication) ──────────────────────────────


def test_migration_is_additive_and_preserves_rows(tmp_path):
    dbp = tmp_path / "legacy.db"
    c = sqlite3.connect(str(dbp))
    c.executescript("""
        CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, ts_utc REAL);
        CREATE TABLE production_decision_records (decision_id TEXT PRIMARY KEY, ticker TEXT);
        CREATE TABLE calibration_decision_log (id INTEGER PRIMARY KEY, ticker TEXT);
        INSERT INTO snapshots (ticker, ts_utc) VALUES ('SPY', 1.0), ('QQQ', 2.0);
        INSERT INTO production_decision_records VALUES ('legacy-d', 'SPY');
    """)
    c.commit()
    xi.ensure_execution_identity_schema(c)
    xi.ensure_execution_identity_schema(c)  # idempotent second run
    rows = c.execute("SELECT ticker, decision_id, execution_identity_sha256 FROM snapshots ORDER BY ts_utc").fetchall()
    assert rows == [("SPY", None, None), ("QQQ", None, None)]  # preserved, NULL identity
    assert c.execute("SELECT decision_id, execution_identity_sha256 FROM production_decision_records").fetchone() == ("legacy-d", None)
    c.close()


# ── live-cycle wiring locks (server persist tail) ───────────────────────────


def test_write_path_universe_inventory(repo_index):
    """Recurrence lock: every repo-root production writer to the three linked
    tables is known.  A NEW writer file appearing in this scan means the
    identity system must be extended — this test fails until it is."""
    # TEST_SYSTEM_REHAB_V2: was an independent root.glob("*.py") +
    # (root/"calibration").glob("*.py") + per-file read_text -- now sources from the
    # shared `repo_index` corpus, filtered to the same two top-level scopes.
    writers: set[str] = set()
    for rel, text, _tree in repo_index.items():
        in_root = len(rel.parts) == 1
        in_calibration = len(rel.parts) == 2 and rel.parts[0] == "calibration"
        if not (in_root or in_calibration):
            continue
        if ("INSERT INTO snapshots" in text or "insert_snapshot(" in text
                or "INSERT INTO production_decision_records" in text
                or "INSERT INTO calibration_decision_log" in text):
            if rel.name.startswith("test_") or "backfill" in rel.name or "analyze" in rel.name:
                continue
            writers.add(rel.name if in_root else f"calibration/{rel.name}")
    known = {
        "db.py",                      # insert_snapshot (guarded; quote-only N/A)
        "server.py",                  # anchored model-derived + quote-only paths
        "decision_record.py",         # identity-carrying decision records
        "live_decision_bundle.py",    # stamp + persist passthrough
        "calibration/writer.py",      # identity-carrying calibration rows
        "calibration/schema.py",      # schema DDL only (appears via table token)
        "calibration/v2_live_logging.py",  # live calibration caller (passthrough site)
        "execution_identity.py",      # the identity system itself
        "snapshot_normalizer.py",     # derives snapshots_1m_normalized FROM existing
                                       # snapshot rows (identity travels with the source
                                       # row; no new model execution occurs)
        # Offline validation/proof harnesses writing to NON-production copies —
        # not live decision cycles; identities are neither created nor faked:
        "calibration/build_trusted_anchor_proof_dataset.py",
        "calibration/run_production_accumulation_validation.py",
        "calibration/validate_logging_e2e.py",
    }
    unknown = writers - known
    assert not unknown, (
        f"NEW production write path(s) {sorted(unknown)} must be wired into "
        "execution_identity_v1 (anchor + linkage) before landing"
    )


# ══════════════════════════════════════════════════════════════════════════════
# EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1 — 2026-07-13 RTH contradiction
# (255/258 ledgers OPEN missing "decision"; every production-decision persist
# refused IDENTITY_MISMATCH because the anchor lived in the post-publish tail
# while _finalize_production_decision ran earlier in the same cycle).
# ══════════════════════════════════════════════════════════════════════════════


def test_fresh_database_gets_all_linkage_triggers(tmp_path, monkeypatch):
    """Fresh-DB regression (noncanonical runtime proof 2026-07-13): EdDB init
    must create production_decision_records + calibration_decision_log BEFORE
    the identity schema so ALL THREE linkage triggers exist — an identity-less
    governed write on a brand-new database must be refused, never ungoverned."""
    monkeypatch.setenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
    from db import EdDB

    db = EdDB(db_path=str(tmp_path / "fresh.db"))
    with db._connect() as conn:
        trigs = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
        for table in ("snapshots", "production_decision_records", "calibration_decision_log"):
            assert f"trg_{table}_exec_identity_link" in trigs, table
        # and the trigger actually bites on a fresh DB:
        import pytest as _pytest
        with _pytest.raises(sqlite3.IntegrityError, match="IDENTITY_MISMATCH"):
            conn.execute(
                "INSERT INTO production_decision_records (decision_id, decision_ts_utc,"
                " ticker, route, release_id, created_at_utc) VALUES (?,?,?,?,?,?)",
                ("fresh-did", 1.0, "SPY", "r", "rel", 1.0),
            )
