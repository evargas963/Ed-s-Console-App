#!/usr/bin/env python3
"""PYTEST_TRUST_REBUILD_V1 — collect-only census + AST proof-type classification.

Not a second obligation authority. Writes reports/pytest_trust_census_latest.json
(gitignored). A test is proof only if breaking the claimed invariant fails it.

# next-rth-ok: census is not a live-session residual
# universal-scope-ok: collected suite is the enrolled test estate, not a ticker sample
# chart-intent-ok: does not claim Chart Done
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "pytest_trust_census_latest.json"

_TEXT_READERS = frozenset({"read_text", "getsource", "getdoc", "getcomments", "readlines"})
_MOCK_NAMES = frozenset({
    "monkeypatch", "MagicMock", "Mock", "patch", "AsyncMock",
    "setattr", "delattr",
})
_PROD_HINTS = (
    "server", "db", "order_flow", "l1_trade", "schwab", "call_engine",
    "decision_gate", "terrain", "math_", "market_state", "time_et",
    "multi_horizon", "liquidity",
)
_CI_OFFLINE_CANNOT_PROVE = (
    "authenticated Schwab LEVELONE receipts (ED_CI_OFFLINE=1 + placeholder keys)",
    "live RTH session behavior",
    "operator fusion_temperature.json / live skill weights (conftest autouse hermetic)",
    "production EMPTY decision-path registry on the default pytest path "
    "(conftest autouse admits the path; test_decision_gate.py overrides)",
)

_MASTER_BOX_RE = re.compile(
    r"^\s*[-*]\s+\[[ xX]\]\s+`(?P<id>[^`]+)`\s+—\s+STATUS=(?P<status>[A-Z_]+)",
    re.MULTILINE,
)


def _tracked_test_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/*.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed: " + proc.stderr)
    return [ROOT / p for p in proc.stdout.split("\0") if p]


def collect_nodeids(*, ignore_playwright_must_run: bool = False) -> dict[str, Any]:
    """pytest --collect-only. Same estate CI runs (optional ignore matching pytest.yml)."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if ignore_playwright_must_run:
        cmd.append("--ignore=tests/test_playwright_must_run.py")
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    nodeids: list[str] = []
    errors: list[str] = []
    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if not s or s.startswith("=") or s.startswith("no tests"):
            continue
        if s.startswith("ERROR "):
            errors.append(s)
            continue
        if "::" in s or (s.endswith(".py") and not s.startswith("ERROR")):
            nodeids.append(s)
    return {
        "returncode": proc.returncode,
        "nodeids": nodeids,
        "count": len(nodeids),
        "errors": errors,
        "stderr_tail": (proc.stderr or "")[-2000:],
        "ignore_playwright_must_run": ignore_playwright_must_run,
    }


def _fn_calls(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _asserts(fn: ast.AST) -> list[ast.Assert]:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]


def _is_len_gt_zero(node: ast.Assert) -> bool:
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1):
        return False
    if not isinstance(t.ops[0], (ast.Gt, ast.GtE)):
        return False
    if not (isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value in (0, 0.0)):
        return False
    left = t.left
    return isinstance(left, ast.Call) and (
        (isinstance(left.func, ast.Name) and left.func.id == "len")
        or (isinstance(left.func, ast.Attribute) and left.func.attr == "len")
    )


def _is_weak_assert(node: ast.Assert) -> bool:
    t = node.test
    if isinstance(t, ast.Compare) and len(t.ops) == 1:
        op = t.ops[0]
        if isinstance(op, ast.IsNot) and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value is None:
            return True
        if isinstance(op, ast.Eq) and isinstance(t.comparators[0], ast.Constant):
            if t.comparators[0].value in (200, True):
                return True
        if _is_len_gt_zero(node):
            return True
        return False
    if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
        return False
    if isinstance(t, (ast.Name, ast.Attribute)):
        return True  # assert payload / assert ok — truthiness
    return False


def _names_holding_file_text(fn: ast.AST) -> set[str]:
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            if name in tainted:
                continue
            hit = any(isinstance(s, ast.Attribute) and s.attr in _TEXT_READERS
                      for s in ast.walk(node.value))
            if not hit:
                hit = any(isinstance(s, ast.Name) and s.id in tainted
                          for s in ast.walk(node.value))
            if hit:
                tainted.add(name)
                changed = True
    return tainted


def _asserts_on_text(node: ast.Assert, tainted: set[str]) -> bool:
    for sub in ast.walk(node.test):
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _TEXT_READERS:
            return True
    return False


def _decorator_markers(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    markers: list[str] = []
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Attribute):
            markers.append(dec.attr)
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            markers.append(dec.func.attr)
        elif isinstance(dec, ast.Name):
            markers.append(dec.id)
    return markers


def classify_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, *, rel: str) -> dict[str, Any]:
    calls = _fn_calls(fn)
    asserts = _asserts(fn)
    tainted = _names_holding_file_text(fn)
    source_text = bool(asserts) and all(_asserts_on_text(a, tainted) for a in asserts)
    mock_heavy = bool(calls & _MOCK_NAMES) or any(
        isinstance(a, ast.arg) and a.arg == "monkeypatch" for a in fn.args.args
    )
    weak = sum(1 for a in asserts if _is_weak_assert(a))
    markers = _decorator_markers(fn)
    name = fn.name
    overbroad = bool(re.search(
        r"(live|end_to_end|e2e|universal|production_path|integration)", name, re.I
    )) and source_text

    ptype = "SMOKE"
    if source_text:
        ptype = "SOURCE_TEXT"
    elif "ast" in calls or "walk" in calls:
        ptype = "STRUCTURAL_AST"
    elif re.search(r"(guard|lock|gate|hook|process|rc_|find_it)", rel):
        ptype = "META_GOVERNANCE"
    elif re.search(r"(mutate|mutation)", name, re.I):
        ptype = "MUTATION"
    elif re.search(r"(fault|inject)", name, re.I):
        ptype = "FAULT_INJECTION"
    elif "playwright" in rel or name.startswith("test_e2e"):
        ptype = "E2E"
    elif re.search(r"live_(schwab|rth|receipt|vendor)", name, re.I):
        ptype = "LIVE_EMPIRICAL"
    elif re.search(r"(rth|replay|lookahead|embargo|purge|causal|leak)", name, re.I):
        ptype = "TEMPORAL_CAUSAL"
    elif re.search(r"(golden|formula|bs_|gex|charm)", name, re.I):
        ptype = "SEMANTIC_GOLDEN"
    elif any(c in calls for c in (
        "compute_call", "OrderFlowEngine", "push_level_one",
        "evaluate_decision_path_admission", "is_tradable_session_ts_utc",
        "gex_0dte_from_chain",
    )):
        ptype = "PRODUCTION_PATH"
    elif mock_heavy and any(h in rel for h in ("decision", "order_flow", "l1_", "server", "db")):
        ptype = "INTEGRATION"
    elif asserts and not source_text:
        if sum(1 for h in _PROD_HINTS if h in rel) >= 2:
            ptype = "INTEGRATION"
        else:
            ptype = "BEHAVIORAL"

    return {
        "name": name,
        "lineno": fn.lineno,
        "file": rel,
        "proof_type": ptype,
        "n_asserts": len(asserts),
        "weak_asserts": weak,
        "source_text_only": source_text,
        "mock_heavy": mock_heavy,
        "overbroad_name": overbroad,
        "markers": markers,
        "calls": sorted(calls)[:40],
        "skipped": "skip" in markers or "skipif" in markers,
        "xfail": "xfail" in markers,
    }


def classify_repo() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _tracked_test_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            rows.append(classify_function(fn, rel=rel))
    return rows


def ci_parity_facts() -> dict[str, bool | str]:
    """Facts about CI vs local collection — called by tests, not grepped in chat."""
    yml = (ROOT / ".github/workflows/pytest.yml").read_text(encoding="utf-8")
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    archive = (ROOT / "tests/archive/conftest.py").read_text(encoding="utf-8")
    return {
        "ci_offline": 'ED_CI_OFFLINE: "1"' in yml,
        "ci_noncanonical_db": "ED_CONSOLE_ALLOW_NONCANONICAL_DB" in yml,
        "ci_placeholder_schwab": "ci-not-live-placeholder" in yml,
        "xdist_ignores_playwright_must_run": "--ignore=tests/test_playwright_must_run.py" in yml,
        "after_e2e_runs_playwright_must_run": "python -m pytest tests/test_playwright_must_run.py" in yml,
        "ci_xdist_nproc": '-n "$(nproc)"' in yml or "-n \"$(nproc)\"" in yml,
        "local_make_runs_e2e_then_pytest": "npm run test:e2e" in mk and "python -m pytest" in mk,
        "local_make_does_not_drop_playwright_must_run": "--ignore=tests/test_playwright_must_run.py" not in mk,
        "archive_legacy_collect_ignore": 'collect_ignore = ["legacy_section_audits_v1"]' in archive,
    }


def archive_legacy_test_count() -> int:
    return sum(1 for r in classify_repo() if r["file"].startswith("tests/archive/legacy"))


def master_pass_ids() -> list[str]:
    text = (ROOT / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md").read_text(
        encoding="utf-8", errors="replace"
    )
    return [m.group("id") for m in _MASTER_BOX_RE.finditer(text) if m.group("status") == "PASS"]


def summarize(rows: list[dict[str, Any]], collected: dict[str, Any]) -> dict[str, Any]:
    types = Counter(r["proof_type"] for r in rows)
    files = sorted({r["file"] for r in rows if not r["file"].startswith("tests/archive/")})
    ast_names = {
        (r["file"], r["name"]) for r in rows
        if not r["file"].startswith("tests/archive/")
    }
    collected_pairs: set[tuple[str, str]] = set()
    for nid in collected.get("nodeids") or []:
        if "::" not in nid:
            continue
        file, rest = nid.split("::", 1)
        fn = rest.split("::")[-1].split("[")[0]
        collected_pairs.add((file.replace("\\", "/"), fn))
    uncollected = sorted(f"{f}::{n}" for f, n in ast_names if (f, n) not in collected_pairs)
    return {
        "schema": "pytest_trust_census_v1",
        "COLLECTED_TESTS": collected.get("count"),
        "collect_returncode": collected.get("returncode"),
        "TEST_FILES": len(files),
        "AST_TEST_FUNCTIONS": len(rows),
        "BEHAVIORAL": types.get("BEHAVIORAL", 0),
        "INTEGRATION": types.get("INTEGRATION", 0),
        "PRODUCTION_PATH": types.get("PRODUCTION_PATH", 0),
        "FAULT_INJECTION": types.get("FAULT_INJECTION", 0),
        "MUTATION": types.get("MUTATION", 0),
        "TEMPORAL_CAUSAL": types.get("TEMPORAL_CAUSAL", 0),
        "SEMANTIC_GOLDEN": types.get("SEMANTIC_GOLDEN", 0),
        "LIVE_EMPIRICAL": types.get("LIVE_EMPIRICAL", 0),
        "E2E": types.get("E2E", 0),
        "STRUCTURAL_AST": types.get("STRUCTURAL_AST", 0),
        "SOURCE_TEXT": types.get("SOURCE_TEXT", 0),
        "META_GOVERNANCE": types.get("META_GOVERNANCE", 0),
        "SMOKE_ONLY": types.get("SMOKE", 0),
        "SKIPPED": sum(1 for r in rows if r["skipped"]),
        "XFAIL": sum(1 for r in rows if r["xfail"]),
        "SOURCE_TEXT_ONLY_FUNCS": sum(1 for r in rows if r["source_text_only"]),
        "MOCK_HEAVY": sum(1 for r in rows if r["mock_heavy"]),
        "WEAK_ASSERT_FUNCS": sum(1 for r in rows if r["weak_asserts"] and r["n_asserts"] <= r["weak_asserts"]),
        "OVERBROAD_NAME_SOURCE_TEXT": sum(1 for r in rows if r["overbroad_name"]),
        "AST_NOT_IN_COLLECT": uncollected[:80],
        "AST_NOT_IN_COLLECT_N": len(uncollected),
        "collect_errors": collected.get("errors") or [],
        "master_pass_ids": master_pass_ids(),
        "ci_cannot_prove": list(_CI_OFFLINE_CANNOT_PROVE),
        "intentional_uncollected": [
            "tests/archive/legacy_section_audits_v1 (tests/archive/conftest.py collect_ignore)",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--ignore-playwright-must-run", action="store_true")
    args = ap.parse_args(argv)
    if args.skip_collect:
        collected: dict[str, Any] = {
            "returncode": None, "nodeids": [], "count": None, "errors": [],
            "ignore_playwright_must_run": args.ignore_playwright_must_run,
        }
    else:
        collected = collect_nodeids(
            ignore_playwright_must_run=args.ignore_playwright_must_run
        )
    rows = classify_repo()
    summary = summarize(rows, collected)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "n_rows": len(rows)}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if args.skip_collect:
        return 0
    return 0 if collected.get("returncode") in (0, None) else 2


if __name__ == "__main__":
    raise SystemExit(main())
