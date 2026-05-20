"""REPO_SWEEP #1 — error-propagation baseline guards (bare except + silent pass)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__", "tests"}
)

# Repo-wide silent ``except Exception: pass`` after sweep #1 (production tree excl. tests).
_BASELINE_SILENT_EXCEPTION_PASS = 43

_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*", re.MULTILINE)
_SILENT_PASS = re.compile(
    r"except\s+Exception\s*:\s*(?:\n\s*)+pass\s*(?:\n|$)",
    re.MULTILINE,
)

_CRITICAL_SILENT_PASS_FILES = frozenset(
    {
        "live_decision_bundle.py",
        "market_state.py",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_production_py(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield path, rel


def _scan_patterns() -> tuple[list[str], list[str], dict[str, int]]:
    root = _repo_root()
    bare: list[str] = []
    silent: list[str] = []
    per_file: dict[str, int] = {}
    for path, rel in _iter_production_py(root):
        src = path.read_text(encoding="utf-8")
        rel_s = str(rel).replace("\\", "/")
        for m in _BARE_EXCEPT.finditer(src):
            line = src[: m.start()].count("\n") + 1
            bare.append(f"{rel_s}:{line}")
        for m in _SILENT_PASS.finditer(src):
            line = src[: m.start()].count("\n") + 1
            silent.append(f"{rel_s}:{line}")
            per_file[rel_s] = per_file.get(rel_s, 0) + 1
    return bare, silent, per_file


def test_no_bare_except_in_production_tree():
    bare, _, _ = _scan_patterns()
    assert not bare, f"bare except: clauses remain: {bare}"


def test_silent_exception_pass_at_or_below_baseline():
    _, silent, per_file = _scan_patterns()
    assert len(silent) <= _BASELINE_SILENT_EXCEPTION_PASS, (
        f"silent except Exception: pass count {len(silent)} > baseline {_BASELINE_SILENT_EXCEPTION_PASS}; "
        f"new hits: {silent[:20]}"
    )


def test_critical_paths_have_no_silent_exception_pass():
    _, silent, _ = _scan_patterns()
    critical_hits = [s for s in silent if s.split(":")[0] in _CRITICAL_SILENT_PASS_FILES]
    assert not critical_hits, critical_hits


def test_error_propagation_audit_artifact_exists():
    audit = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v1_20260520.json"
    assert audit.is_file(), "governance audit artifact missing"
