"""Perf proof harness — schema validation only (no network; no scanner)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf_proof.validate import load_and_validate, validate_perf_proof

ROOT = Path(__file__).resolve().parents[1]
REPLACEMENTS = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"


def test_validate_minimal_good():
    doc = {
        "schema_version": "1.0",
        "perf_proof_id": "pp_test_minimal",
        "landed_batch": "test",
        "replacement_scope": "unit test fixture",
        "code_paths": ["foo.py"],
        "evidence": {"pytest_args": ["tests/test_perf_proof_harness.py::test_validate_minimal_good"]},
        "benchmark": {
            "command": ["python", "-m", "pytest", "tests/test_perf_proof_harness.py::test_validate_minimal_good", "-q"],
            "iterations": 1,
            "timings_ms": [1.0],
            "median_ms": 1.0,
            "platform_note": "synthetic",
        },
        "register_link": {"status": "not_applicable", "replaced_register_ids": []},
    }
    assert validate_perf_proof(doc) == []


def test_validate_rejects_bad_schema_version():
    doc = {
        "schema_version": "0.9",
        "perf_proof_id": "x",
        "replacement_scope": "x",
        "code_paths": ["x"],
        "evidence": {"pytest_args": ["x"]},
        "benchmark": {
            "command": [],
            "iterations": 1,
            "timings_ms": [1.0],
            "median_ms": 1.0,
        },
    }
    assert any("schema_version" in e for e in validate_perf_proof(doc))


@pytest.mark.skipif(not REPLACEMENTS.is_dir(), reason="replacements dir absent")
def test_committed_replacement_proofs_validate():
    errors: list[str] = []
    for p in sorted(REPLACEMENTS.glob("*.json")):
        _doc, errs = load_and_validate(p)
        if errs:
            errors.append(f"{p.name}: {errs}")
    assert not errors, "\n".join(errors)


def test_replacements_index_matches_glob():
    """index.json P_count must equal valid JSON files on disk (excluding index)."""
    index_path = REPLACEMENTS.parent / "index.json"
    if not index_path.is_file():
        pytest.skip("index.json not yet created")
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    n_disk = len(list(REPLACEMENTS.glob("pp_*.json")))
    assert idx.get("P_count") == n_disk
