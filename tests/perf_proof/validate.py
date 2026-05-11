"""Validate perf_proof JSON documents (schema v1.0)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.perf_proof import PERF_PROOF_SCHEMA_VERSION


def validate_perf_proof(doc: dict[str, Any]) -> list[str]:
    """Return a list of validation errors; empty means OK."""
    errs: list[str] = []
    if doc.get("schema_version") != PERF_PROOF_SCHEMA_VERSION:
        errs.append(f"schema_version must be {PERF_PROOF_SCHEMA_VERSION!r}")
    for k in ("perf_proof_id", "replacement_scope", "code_paths", "evidence", "benchmark", "register_link"):
        if k not in doc:
            errs.append(f"missing required key: {k}")
    rl = doc.get("register_link")
    if rl is not None and not isinstance(rl, dict):
        errs.append("register_link must be an object when present")
    elif isinstance(rl, dict) and "status" not in rl:
        errs.append("register_link.status required")
    if errs:
        return errs
    if not isinstance(doc["code_paths"], list) or not doc["code_paths"]:
        errs.append("code_paths must be a non-empty list")
    ev = doc["evidence"]
    if not isinstance(ev, dict) or not ev.get("pytest_args"):
        errs.append("evidence.pytest_args required (list of pytest path strings)")
    elif not isinstance(ev["pytest_args"], list) or not ev["pytest_args"]:
        errs.append("evidence.pytest_args must be a non-empty list")
    bench = doc["benchmark"]
    if not isinstance(bench, dict):
        errs.append("benchmark must be an object")
        return errs
    for bk in ("command", "iterations", "timings_ms", "median_ms"):
        if bk not in bench:
            errs.append(f"benchmark.{bk} required")
    if bench.get("iterations", 0) < 1:
        errs.append("benchmark.iterations must be >= 1")
    tms = bench.get("timings_ms")
    if not isinstance(tms, list) or len(tms) != bench.get("iterations"):
        errs.append("benchmark.timings_ms length must equal benchmark.iterations")
    return errs


def load_and_validate(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, [str(e)]
    if not isinstance(doc, dict):
        return None, ["root must be a JSON object"]
    return doc, validate_perf_proof(doc)
