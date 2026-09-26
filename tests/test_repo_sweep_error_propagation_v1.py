"""REPO_SWEEP error-propagation baseline guards (bare except + silent pass)."""

from __future__ import annotations

import json
import re
from pathlib import Path


#: RC-244: `scratchpad` joins the skip set. These tests declare their scope in their own
#: names — "in_production_tree" — and scratchpad is throwaway analysis, which repo policy
#: already treats as non-production: the ENFORCED gate's forward-only grandfather filters
#: scratchpad paths out of the same no_silent_swallow rule, so a commit passes while this
#: test failed on the identical six hits. A control that disagrees with the gate it mirrors
#: cries wolf on debris and trains the reader to ignore a real production regression.
_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__", "tests", "scratchpad"}
)

# Repo-wide silent ``except Exception: pass`` after sweep #3 (production tree).
_BASELINE_SILENT_EXCEPTION_PASS = 0

_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*", re.MULTILINE)
_SILENT_PASS = re.compile(
    r"except\s+Exception\s*:\s*(?:\n\s*)+pass\s*(?:\n|$)",
    re.MULTILINE,
)

# Decision pipeline modules: zero tolerance for ``except Exception: pass`` (rule #25).
_CRITICAL_SILENT_PASS_FILES = frozenset(
    {
        "signals.py",
        "call_engine.py",
        "prediction_engine.py",
        "realized_contract_eval.py",
        "bayesian_fusion.py",
        "mc_fusion_adjustment.py",
        "market_state.py",
        "live_decision_bundle.py",
        "features/signal_layer_v1.py",
        "features/inference_snapshot.py",
        "features/fusion_policy_contract.py",
        "server.py",
        "ml_scheduler.py",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/scratchpad and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text


def _scan_patterns(repo_index) -> tuple[list[str], list[str], dict[str, int]]:
    bare: list[str] = []
    silent: list[str] = []
    per_file: dict[str, int] = {}
    for rel, src in _iter_production_py(repo_index):
        rel_s = str(rel).replace("\\", "/")
        for m in _BARE_EXCEPT.finditer(src):
            line = src[: m.start()].count("\n") + 1
            bare.append(f"{rel_s}:{line}")
        for m in _SILENT_PASS.finditer(src):
            line = src[: m.start()].count("\n") + 1
            silent.append(f"{rel_s}:{line}")
            per_file[rel_s] = per_file.get(rel_s, 0) + 1
    return bare, silent, per_file


def test_no_bare_except_in_production_tree(repo_index):
    bare, _, _ = _scan_patterns(repo_index)
    assert not bare, f"bare except: clauses remain: {bare}"


def test_no_silent_exception_pass_in_production_tree(repo_index):
    _, silent, per_file = _scan_patterns(repo_index)
    assert len(silent) == _BASELINE_SILENT_EXCEPTION_PASS, (
        f"silent except Exception: pass count {len(silent)} != baseline {_BASELINE_SILENT_EXCEPTION_PASS}; "
        f"hits: {silent[:30]}; per_file={per_file}"
    )


def test_critical_paths_have_no_silent_exception_pass(repo_index):
    _, silent, _ = _scan_patterns(repo_index)
    critical_hits = [s for s in silent if s.split(":")[0] in _CRITICAL_SILENT_PASS_FILES]
    assert not critical_hits, critical_hits


def test_error_propagation_audit_artifact_exists():
    audit = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v1_20260520.json"
    assert audit.is_file(), "governance audit artifact missing"


def test_audit_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v1_20260520.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries), (
        f"summary.class_c_fixed_count={count} != len(class_c_fixed)={len(entries)}"
    )


def test_error_propagation_audit_v2_artifact_exists():
    audit = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v2_20260518.json"
    assert audit.is_file(), "governance sweep #2 audit artifact missing"


def test_audit_v2_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v2_20260518.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries), (
        f"v2 summary.class_c_fixed_count={count} != len(class_c_fixed)={len(entries)}"
    )
    assert summary.get("silent_exception_pass_after") == 27


def test_error_propagation_audit_v3_artifact_exists():
    audit = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v3_20260520.json"
    assert audit.is_file(), "governance sweep #3 audit artifact missing"


def test_audit_v3_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "reports" / "audits" / "repo_sweep_error_propagation_v3_20260520.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries) == 27
    assert summary.get("silent_exception_pass_after") == _BASELINE_SILENT_EXCEPTION_PASS




