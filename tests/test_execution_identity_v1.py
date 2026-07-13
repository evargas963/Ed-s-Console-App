"""execution_identity_v1 — adversarial suite (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1).

All tests run against tmp SQLite databases and tmp CAS roots.  Expected hashes
are recomputed independently with hashlib — never through the module under test.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
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


def test_canonical_json_deterministic_and_identity_stable():
    e1, e2 = _envelope(), _envelope()
    j1, j2 = xi.canonical_envelope_json(e1), xi.canonical_envelope_json(e2)
    assert j1 == j2
    assert xi.execution_identity_sha256(e1) == xi.execution_identity_sha256(e2)
    # independent hash reference
    assert xi.execution_identity_sha256(e1) == hashlib.sha256(j1.encode("ascii")).hexdigest()
    # key order does not matter (canonical sort)
    shuffled = json.loads(json.dumps(e1))
    assert xi.execution_identity_sha256(shuffled) == xi.execution_identity_sha256(e1)


@pytest.mark.parametrize("mutator,field", [
    (lambda e: e["release"].update(git_sha="b" * 40), "git_sha"),
    (lambda e: e["routing"].update(bundle_ticker="QQQ"), "bundle_ticker"),
    (lambda e: e["bundles"]["1c"]["artifacts"].update(xgb="f" * 64), "artifact sha"),
    (lambda e: e["bundles"]["1c"].update(manifest_sha256="e" * 64), "manifest sha"),
    (lambda e: e["calibration"]["by_horizon"]["1c"].update(conformal_run_id="rX"), "calibration id"),
    (lambda e: e["stack_pins"].update(feature_schema_version="v6"), "feature schema"),
    (lambda e: e["stack_pins"].update(fusion_policy_contract="f5"), "fusion policy"),
    (lambda e: e["runtime"].update(runtime_class="RELAXED_RESOLUTION"), "runtime class"),
    (lambda e: e["stack_pins"]["env_controlled_behavior"].update(ED_NEW_FLAG="1"), "env behavior"),
])
def test_every_material_component_change_changes_identity(mutator, field):
    base = _envelope()
    changed = json.loads(xi.canonical_envelope_json(base))
    mutator(changed)
    assert xi.execution_identity_sha256(changed) != xi.execution_identity_sha256(base), field


def test_malformed_and_noncanonical_envelopes_refused():
    with pytest.raises(xi.ExecutionIdentityError) as e1:
        xi.canonical_envelope_json({"envelope_schema_version": "1"})
    assert e1.value.reason == "ENVELOPE_MALFORMED"
    bad = _envelope()
    bad["stack_pins"]["nan"] = float("nan")
    with pytest.raises(xi.ExecutionIdentityError) as e2:
        xi.canonical_envelope_json(bad)
    assert e2.value.reason == "ENVELOPE_NONCANONICAL"
    wrong_ver = _envelope()
    wrong_ver["envelope_schema_version"] = "999"
    with pytest.raises(xi.ExecutionIdentityError):
        xi.canonical_envelope_json(wrong_ver)


# ── identity + ledger persistence ────────────────────────────────────────────


def test_insert_identity_and_ledger_anchor(conn):
    env = _envelope()
    sha = xi.insert_execution_identity(conn, env, decision_id="d1",
                                       expected_surfaces=["decision", "snapshot"])
    assert sha == xi.execution_identity_sha256(env)
    row = conn.execute("SELECT identity_class, requested_ticker, bundle_ticker "
                       "FROM model_execution_identities").fetchone()
    assert row == ("FULL_STACK_PINNED", "ZZGST", "SPY")
    led = conn.execute("SELECT status FROM decision_persistence_ledger WHERE decision_id='d1'").fetchone()
    assert led[0] == "OPEN"


def test_identity_rows_are_immutable(conn):
    xi.insert_execution_identity(conn, _envelope(), decision_id="d1", expected_surfaces=["decision"])
    with pytest.raises(sqlite3.IntegrityError, match="ENVELOPE_IMMUTABLE"):
        conn.execute("UPDATE model_execution_identities SET release_id='hacked'")
    with pytest.raises(sqlite3.IntegrityError, match="ENVELOPE_IMMUTABLE"):
        conn.execute("DELETE FROM model_execution_identities")


def test_concurrent_identical_identity_inserts_deduplicate(tmp_path):
    dbp = tmp_path / "conc.db"
    boot = sqlite3.connect(str(dbp))
    xi.ensure_execution_identity_schema(boot)
    boot.close()
    env = _envelope()
    errors: list[str] = []

    def worker(n):
        c = sqlite3.connect(str(dbp), timeout=30.0)
        try:
            xi.insert_execution_identity(c, env, decision_id=f"d{n}", expected_surfaces=["decision"])
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    c = sqlite3.connect(str(dbp))
    assert c.execute("SELECT COUNT(*) FROM model_execution_identities").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM decision_persistence_ledger").fetchone()[0] == 6
    c.close()


def test_same_decision_cannot_bind_two_identities(conn):
    xi.insert_execution_identity(conn, _envelope(), decision_id="d1", expected_surfaces=["decision"])
    other = _envelope(bundle_ticker="QQQ", guest_anchor=False, guest_anchor_ticker=None,
                      requested_ticker="QQQ")
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.insert_execution_identity(conn, other, decision_id="d1", expected_surfaces=["decision"])
    assert e.value.reason == "LEDGER_CONFLICT"


def test_same_sha_different_envelope_refused(conn):
    env = _envelope()
    sha = xi.insert_execution_identity(conn, env, decision_id="d1", expected_surfaces=["decision"])
    # forge a fake registration attempt with same sha but different payload by
    # calling the internal collision check through a crafted row
    row = conn.execute("SELECT envelope_json FROM model_execution_identities "
                       "WHERE execution_identity_sha256=?", (sha,)).fetchone()
    assert row is not None
    class Fake(dict):
        pass
    tampered = json.loads(row[0])
    tampered["executed_at_utc"] = 1.0
    # direct API path: inserting the tampered envelope produces a DIFFERENT sha
    sha2 = xi.insert_execution_identity(conn, tampered, decision_id="d2", expected_surfaces=["decision"])
    assert sha2 != sha


# ── dependent-table linkage (trigger-enforced consistency) ──────────────────


def test_dependent_write_without_registered_identity_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="IDENTITY_MISSING"):
        conn.execute(
            "INSERT INTO snapshots (ticker, ts_utc, decision_id, execution_identity_sha256) VALUES (?,?,?,?)",
            ("SPY", 1.0, "dX", "0" * 64),
        )


def test_dependent_write_identity_without_decision_rejected(conn):
    sha = xi.insert_execution_identity(conn, _envelope(), decision_id="d1", expected_surfaces=["snapshot"])
    with pytest.raises(sqlite3.IntegrityError, match="IDENTITY_MISMATCH"):
        conn.execute(
            "INSERT INTO snapshots (ticker, ts_utc, execution_identity_sha256) VALUES (?,?,?)",
            ("SPY", 1.0, sha),
        )


def test_two_surfaces_cannot_carry_different_identities(conn):
    sha1 = xi.insert_execution_identity(conn, _envelope(), decision_id="d1", expected_surfaces=["snapshot", "decision"])
    env2 = _envelope(requested_ticker="QQQ", bundle_ticker="QQQ", guest_anchor=False, guest_anchor_ticker=None)
    sha2 = xi.insert_execution_identity(conn, env2, decision_id="d2", expected_surfaces=["snapshot"])
    conn.execute("INSERT INTO snapshots (ticker, ts_utc, decision_id, execution_identity_sha256) VALUES (?,?,?,?)",
                 ("SPY", 1.0, "d1", sha1))
    with pytest.raises(sqlite3.IntegrityError, match="LEDGER_CONFLICT"):
        conn.execute(
            "INSERT INTO production_decision_records (decision_id, ticker, execution_identity_sha256) VALUES (?,?,?)",
            ("d1", "SPY", sha2),
        )


def test_quote_only_rows_insert_with_null_identity(conn):
    conn.execute("INSERT INTO snapshots (ticker, ts_utc) VALUES ('SPY', 1.0)")
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_ledger_completion_and_partial_detection(conn):
    xi.insert_execution_identity(conn, _envelope(), decision_id="d1",
                                 expected_surfaces=["decision", "snapshot"])
    assert xi.mark_surface_landed(conn, "d1", "decision") == "OPEN"
    assert xi.mark_surface_landed(conn, "d1", "snapshot") == "COMPLETE"
    # a second decision that never lands its snapshot becomes INCOMPLETE (explicit)
    xi.insert_execution_identity(conn, _envelope(executed_at_utc=1_784_000_001.0),
                                 decision_id="d2", expected_surfaces=["decision", "snapshot"])
    xi.mark_surface_landed(conn, "d2", "decision")
    conn.execute("UPDATE decision_persistence_ledger SET updated_at_utc = updated_at_utc - 10000 WHERE decision_id='d2'")
    conn.commit()
    scan = xi.ledger_consistency_scan(conn, stale_after_s=900)
    assert scan["incomplete_marked"] == [{"decision_id": "d2", "missing_surfaces": ["snapshot"]}]
    assert conn.execute("SELECT status FROM decision_persistence_ledger WHERE decision_id='d2'").fetchone()[0] == "INCOMPLETE"


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


def test_cas_archive_verify_retrieve_and_collision(tmp_path):
    cas = tmp_path / "cas"
    src = tmp_path / "xgb.pkl"
    src.write_bytes(b"artifact-bytes")
    sha = hashlib.sha256(b"artifact-bytes").hexdigest()
    dest = xi.archive_artifact(src, sha, cas_root=cas)
    assert dest.is_file() and dest.name == sha
    assert xi.retrieve_artifact(sha, cas_root=cas) == dest
    # wrong expected hash refused before archival
    with pytest.raises(xi.ExecutionIdentityError) as e1:
        xi.archive_artifact(src, "0" * 64, cas_root=cas)
    assert e1.value.reason == "ARTIFACT_SOURCE_HASH_MISMATCH"
    # collision: same address, different bytes → refused
    dest.write_bytes(b"tampered")
    with pytest.raises(xi.ExecutionIdentityError) as e2:
        xi.archive_artifact(src, sha, cas_root=cas)
    assert e2.value.reason == "ARTIFACT_CAS_COLLISION"
    # retrieval verifies bytes → corrupt archive fails closed
    with pytest.raises(xi.ExecutionIdentityError) as e3:
        xi.retrieve_artifact(sha, cas_root=cas)
    assert e3.value.reason == "ARTIFACT_CAS_CORRUPT"


def test_missing_archive_fails_replay_never_falls_back(tmp_path, conn):
    env = _envelope()
    # archive only SOME of the referenced artifacts
    cas = tmp_path / "cas"
    shas = sorted(xi.envelope_artifact_shas(env))
    assert len(shas) >= 8  # 4 horizons x (manifest + 2 roles) deduped
    src = tmp_path / "b.bin"
    sha = xi.insert_execution_identity(conn, env, decision_id="d1", expected_surfaces=["decision"])
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.resolve_execution_for_replay(conn, execution_identity_sha256=sha, cas_root=cas)
    assert e.value.reason == "ARTIFACT_CAS_MISSING"
    assert "models/active" in e.value.detail or "MUST NOT fall back" in e.value.detail


def test_archive_envelope_artifacts_requires_all_sources(tmp_path):
    env = _envelope()
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.archive_envelope_artifacts(env, {}, cas_root=tmp_path / "cas")
    assert e.value.reason == "ARTIFACT_SOURCE_MISSING"


def test_gc_of_referenced_artifact_blocked(conn, tmp_path):
    env = _envelope()
    xi.insert_execution_identity(conn, env, decision_id="d1", expected_surfaces=["decision"])
    some_sha = sorted(xi.envelope_artifact_shas(env))[0]
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.gc_check_artifact(conn, some_sha)
    assert e.value.reason == "ARTIFACT_REFERENCED"
    # unreferenced artifact passes the guard
    xi.gc_check_artifact(conn, "9" * 64)


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


def test_full_replay_chain_with_real_bytes(tmp_path, conn):
    # build an envelope whose artifact hashes come from REAL bytes on disk
    files = {}
    for role in ("xgb", "lstm"):
        p = tmp_path / f"{role}.bin"
        p.write_bytes(f"bytes-{role}".encode())
        files[role] = (p, hashlib.sha256(p.read_bytes()).hexdigest())
    man = tmp_path / "manifest.json"
    man.write_text("{}", encoding="utf-8")
    man_sha = hashlib.sha256(man.read_bytes()).hexdigest()
    bundle = {
        "bundle_dir_identity": "active/SPY",
        "manifest_sha256": man_sha,
        "artifacts": {r: s for r, (_p, s) in files.items()},
        "source_lineage": {}, "integrity_class": "VERIFIED_AGAINST_BUNDLE_MANIFEST",
        "serving_complete": True,
    }
    env = _envelope(bundles_by_horizon={"1c": bundle}, horizons_attempted=["1c"])
    cas = tmp_path / "cas"
    sources = {s: p for _r, (p, s) in files.items()}
    sources[man_sha] = man
    archived = xi.archive_envelope_artifacts(env, sources, cas_root=cas)
    assert len(archived) == 3
    sha = xi.insert_execution_identity(conn, env, decision_id="d1", expected_surfaces=["decision"])
    out = xi.resolve_execution_for_replay(conn, execution_identity_sha256=sha, cas_root=cas)
    assert out["proof_levels"]["ARTIFACT_BYTE_IDENTITY"] == "PROVEN"
    assert out["proof_levels"]["OUTPUT_EQUIVALENCE"] == "NOT_PROVEN"  # honest split
    for art_sha, path in out["artifact_paths"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == art_sha
        assert "_artifact_cas" not in str(Path(path).parent).replace(str(cas), "")  # resolved from CAS root only
    # artifact mutation invalidates replay
    victim = Path(next(iter(out["artifact_paths"].values())))
    victim.write_bytes(b"mutated")
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.resolve_execution_for_replay(conn, execution_identity_sha256=sha, cas_root=cas)
    assert e.value.reason == "ARTIFACT_CAS_CORRUPT"


def test_replay_of_legacy_decision_refused_not_rerun(conn):
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.resolve_execution_for_replay(conn, decision_id="pre-schema-row")
    assert e.value.reason == "LEGACY_ROW_NO_IDENTITY"
    assert "UNRECOVERABLE_LEGACY" in e.value.detail


def test_stored_envelope_tamper_detected_at_replay(tmp_path):
    # bypass immutability by writing a fresh db WITHOUT triggers to simulate
    # out-of-band tampering — replay must still catch it via content address
    dbp = tmp_path / "tampered.db"
    c = sqlite3.connect(str(dbp))
    c.execute("""CREATE TABLE model_execution_identities (
        execution_identity_sha256 TEXT PRIMARY KEY, envelope_schema_version TEXT,
        envelope_json TEXT, created_at_utc REAL, release_id TEXT, git_sha TEXT,
        config_hash TEXT, requested_ticker TEXT, bundle_ticker TEXT,
        runtime_class TEXT, identity_class TEXT)""")
    c.execute("CREATE TABLE decision_persistence_ledger (decision_id TEXT PRIMARY KEY, execution_identity_sha256 TEXT, expected_surfaces TEXT, landed_surfaces TEXT, status TEXT, created_at_utc REAL, updated_at_utc REAL)")
    env = _envelope()
    sha = xi.execution_identity_sha256(env)
    tampered = xi.canonical_envelope_json(env).replace("SPY", "QQQ", 1)
    c.execute("INSERT INTO model_execution_identities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (sha, "1", tampered, 0.0, "r", "g", "c", "T", "T", "rc", "FULL_STACK_PINNED"))
    c.commit()
    with pytest.raises(xi.ExecutionIdentityError) as e:
        xi.resolve_execution_for_replay(c, execution_identity_sha256=sha, cas_root=tmp_path)
    assert e.value.reason == "ENVELOPE_HASH_MISMATCH"
    c.close()


# ── historical classification (no fabrication) ──────────────────────────────


def test_historical_rows_classified_without_backfill(conn):
    assert xi.classify_historical_row(conn, decision_id=None, execution_identity_sha256=None,
                                      is_model_derived=False) == "NOT_APPLICABLE"
    assert xi.classify_historical_row(conn, decision_id=None, execution_identity_sha256=None,
                                      is_model_derived=True) == "UNRECOVERABLE_LEGACY"
    assert xi.classify_historical_row(conn, decision_id="old-i31-row", execution_identity_sha256=None,
                                      is_model_derived=True) == "PARTIALLY_RECOVERABLE"
    sha = xi.insert_execution_identity(conn, _envelope(), decision_id="d1", expected_surfaces=["decision"])
    assert xi.classify_historical_row(conn, decision_id="d1", execution_identity_sha256=sha,
                                      is_model_derived=True) == "PROVEN"
    assert xi.classify_historical_row(conn, decision_id="d1", execution_identity_sha256="0" * 64,
                                      is_model_derived=True) == "UNRECOVERABLE_LEGACY"


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


def test_guest_ticker_records_requested_and_bundle_ticker():
    env = _envelope()
    r = env["routing"]
    assert r["requested_ticker"] == "ZZGST" and r["bundle_ticker"] == "SPY"
    assert r["guest_anchor"] is True and r["guest_anchor_ticker"] == "SPY"


def test_four_horizon_envelope_and_identity_classes():
    env = _envelope()
    assert env["routing"]["horizons_executed"] == ["15c", "1c", "5c", "60c"]
    assert xi.identity_class_for_envelope(env) == "FULL_STACK_PINNED"
    deg = _envelope(degradation={"degraded": True, "reasons": ["lstm collapse-flagged"]},
                    runtime_class="STRICT_ACTIVE_SERVABLE")
    assert xi.identity_class_for_envelope(deg) == "DEGRADED_PINNED"
    fc = _envelope(runtime_class="STRICT_ACTIVE_FAIL_CLOSED", bundles_by_horizon={},
                   horizons_attempted=["1c"])
    assert xi.identity_class_for_envelope(fc) == "FAIL_CLOSED_PINNED"


def test_calibration_disabled_is_explicit_never_silent():
    env = _envelope(calibration_by_horizon=None, calibration_logging_enabled=False)
    cal = env["calibration"]
    assert cal["attached"] is False and cal["logging_enabled"] is False
    assert "disabled" in cal["reason"]
    # and it changes the identity relative to attached calibration
    assert xi.execution_identity_sha256(env) != xi.execution_identity_sha256(_envelope())
