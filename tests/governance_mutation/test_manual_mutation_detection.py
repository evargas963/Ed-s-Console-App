"""Governance mutation detection — manifest tampering visibility."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_build_and_verify_manifest_roundtrip(tmp_path, monkeypatch):
    from tools import governance_mutation_detection as gmd

    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    sample = art / "UNIVERSAL_BYPASS_REGISTER.json"
    sample.write_text('{"x": 1}\n', encoding="utf-8")

    monkeypatch.setattr(gmd, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gmd, "ART", art)
    monkeypatch.setattr(gmd, "MANIFEST_PATH", art / "GOVERNANCE_ARTIFACT_MANIFEST.json")
    monkeypatch.setattr(
        gmd,
        "GOVERNANCE_ARTIFACT_PATHS",
        ("governance/artifacts/UNIVERSAL_BYPASS_REGISTER.json",),
    )

    manifest = gmd.build_governance_manifest()
    assert manifest["entries"][0]["sha256"]
    gmd.MANIFEST_PATH.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    assert gmd.verify_governance_manifest()["ok"] is True

    sample.write_text('{"x": 2}\n', encoding="utf-8")
    result = gmd.verify_governance_manifest(manifest)
    assert result["ok"] is False
    assert any("UNIVERSAL_BYPASS_REGISTER.json" in p for p in result["tampered"])


def test_decision_record_integrity_detects_incomplete(tmp_path):
    import sqlite3

    from decision_record import ensure_production_decision_schema, new_decision_id
    from tools.governance_mutation_detection import verify_decision_record_integrity

    db = tmp_path / "dec.db"
    conn = sqlite3.connect(str(db))
    try:
        ensure_production_decision_schema(conn)
        did = new_decision_id()
        conn.execute(
            """
            INSERT INTO production_decision_records (
                decision_id, decision_ts_utc, ticker, route, release_id, release_json,
                reconstruction_json, created_at_utc
            ) VALUES (?, 1.0, 'SPY', 'server._fetch_state', 'rel', '{}', '{}', 1.0)
            """,
            (did,),
        )
        conn.commit()
    finally:
        conn.close()
    result = verify_decision_record_integrity(db)
    assert result["ok"] is False
    assert result["incomplete"]
