"""execution_identity_v1 — adversarial suite (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1).

All tests run against tmp SQLite databases and tmp CAS roots.  Expected hashes
are recomputed independently with hashlib — never through the module under test.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import execution_identity as xi


def _release():
    return {"release_id": "rel-1", "git_sha": "a" * 40, "config_hash": "c" * 64,
            "build_generation": "g1"}


def _bundle_entry(seed: str = "x"):
    return {
        "bundle_dir_identity": f"active/{seed}",
        "manifest_sha256": hashlib.sha256(f"manifest-{seed}".encode()).hexdigest(),
        "artifacts": {
            "xgb": hashlib.sha256(f"xgb-{seed}".encode()).hexdigest(),
            "lstm": hashlib.sha256(f"lstm-{seed}".encode()).hexdigest(),
        },
        "source_lineage": {"trained_at": "2026-07-01T00:00:00Z"},
        "integrity_class": "VERIFIED_AGAINST_BUNDLE_MANIFEST",
        "serving_complete": True,
    }


def _envelope(**over):
    env = xi.build_execution_envelope(
        release=_release(),
        requested_ticker=over.pop("requested_ticker", "ZZGST"),
        bundle_ticker=over.pop("bundle_ticker", "SPY"),
        guest_anchor=over.pop("guest_anchor", True),
        guest_anchor_ticker=over.pop("guest_anchor_ticker", "SPY"),
        horizons_attempted=over.pop("horizons_attempted", ["1c", "5c", "15c", "60c"]),
        bundles_by_horizon=over.pop("bundles_by_horizon", {
            "1c": _bundle_entry("1c"), "5c": _bundle_entry("5c"),
            "15c": _bundle_entry("15c"), "60c": _bundle_entry("60c"),
        }),
        calibration_by_horizon=over.pop("calibration_by_horizon",
                                        {"1c": {"conformal_run_id": "r1", "isotonic_run_id": "r2"}}),
        calibration_logging_enabled=over.pop("calibration_logging_enabled", True),
        stack_pins=over.pop("stack_pins", {
            "feature_schema_version": "v5", "preprocessing_version": "p3",
            "label_definition_version": "l2", "fusion_policy_contract": "f4",
            "regime_engine_version": "r1", "monte_carlo_config_hash": "m" * 8,
            "rules_policy_version": "rp1", "ablation_survivor_generation": "s7",
            "meta_learner": "meta_SPY_1c.pkl", "movement_heads": None,
            "env_controlled_behavior": {"ED_APPLY_ABLATION_SURVIVORS": "1"},
        }),
        runtime_class=over.pop("runtime_class", "STRICT_ACTIVE_SERVABLE"),
        degradation=over.pop("degradation", None),
        tradeable_policy=over.pop("tradeable_policy", {"evaluated": True, "tradeable": False}),
        executed_at_utc=over.pop("executed_at_utc", 1_784_000_000.0),
    )
    assert not over, f"unused overrides: {over}"
    return env


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


# ── canonicalization + identity determinism ─────────────────────────────────








# ── identity + ledger persistence ────────────────────────────────────────────












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


# ── CAS ──────────────────────────────────────────────────────────────────────










# ── replay resolution ────────────────────────────────────────────────────────


def _fully_archived(tmp_path, conn, env):
    cas = tmp_path / "cas"
    sources = {}
    for i, sha in enumerate(sorted(xi.envelope_artifact_shas(env))):
        # test-only: CAS addresses are honored by constructing bytes per sha slot
        p = tmp_path / f"src{i}.bin"
        # we cannot invert sha; instead build envelope from REAL bytes below
        sources[sha] = p
    return cas, sources








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


# ── envelope semantics ───────────────────────────────────────────────────────








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

_SERVER_PY = Path(__file__).resolve().parent.parent / "server.py"


def _server_text() -> str:
    return _SERVER_PY.read_text(encoding="utf-8", errors="replace")




def _dependent_tables(conn):
    """Production-shaped dependent tables + real linkage triggers."""
    from decision_record import ensure_production_decision_schema

    conn.executescript(
        """
        CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (id INTEGER PRIMARY KEY, ticker TEXT);
        """
    )
    ensure_production_decision_schema(conn)
    xi.ensure_execution_identity_schema(conn)


def _minimal_release():
    return {"release_id": "rel-ord", "git_sha": "b" * 40, "config_hash": "d" * 64,
            "build_generation": "g-ord"}


def _persist_decision(conn_path, decision_id, identity_sha):
    from decision_record import persist_production_decision

    ms = {
        "decision_id": decision_id,
        "decision_generation_id": 1,
        "decision_timestamp_utc": 1_784_000_100.0,
        "ticker": "SPY",
        "call_signal": "wait",
        "call_conviction": "low",
        "fusion_available": True,
        "dominant_dir": "up",
    }
    return persist_production_decision(
        ms, route="server._fetch_state", release=_minimal_release(),
        db_path=conn_path, execution_identity_sha256=identity_sha,
    )










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
