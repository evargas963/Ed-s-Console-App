"""Find & Prove mechanical lock helpers (RC-205/RC-209/RC-210).

Institutional sources mapped to detectable artifacts (research 7c2d87a8, 28 sources):
  Harvey, Liu, Zhu (2016) — multiple testing / t≈3 hurdle;
  Bailey & López de Prado (2014) DSR — n_trials + deflated Sharpe;
  López de Prado AFML (2018) — purged/embargoed CV, not plain KFold;
  Arnott, Harvey, Markowitz (2019) — prereg before confirmatory results;
  Nosek et al. TOP/COS (2015) — confirmatory vs exploratory;
  Fed/OCC SR 11-7 (2011) — admission evidence must resolve.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_CONFIRMATORY = re.compile(r"\bCONFIRMATORY\b")
_PREREG_PATH = re.compile(r"\bprereg_path\s*[:=]\s*['\"]([^'\"]+)['\"]", re.I)
_LEAKAGE_OK = re.compile(r"#\s*leakage-ok:", re.I)
_PURGE_MARKERS = re.compile(
    r"expanding_window_oof|purged|embargo|PurgedKFold|CPCV|walk_forward",
    re.I,
)
_BANNED_CV = frozenset({
    "KFold", "StratifiedKFold", "train_test_split",
    "ShuffleSplit", "StratifiedShuffleSplit", "GroupKFold",
})


_PATH_TOKEN = re.compile(
    r"(?:^|[\s`\"'(])((?:[\w.-]+/)+[\w.-]+\.(?:py|md|html|js|ts|tsx|jsx|css|sql|json))"
)


def _path_resolves(ref: str) -> bool:
    """A research/evidence reference resolves when it is a URL or names an existing repo file.

    Inlined 2026-09-06 (bedrock) from tools/plus_player_locks.py, whose catalog
    (governance/plus_player_attributes.json) no longer existed — this helper was the module's
    only live caller.
    """
    r = (ref or "").strip()
    if not r:
        return False
    if "http://" in r or "https://" in r:
        return True
    for m in _PATH_TOKEN.finditer(r):
        rel = m.group(1).replace("\\", "/")
        if (REPO / rel).is_file():
            return True
    first = r.split()[0].strip("`\"'")
    if "/" in first and (REPO / first.replace("\\", "/")).is_file():
        return True
    return False


def admission_evidence_resolves_violations(doc: dict | None = None) -> list[str]:
    """SR 11-7: ADMITTED registry rows — every evidence ref must resolve to a repo file."""
    if doc is None:
        p = REPO / "config" / "decision_path_admissions.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            return [f"decision_path_admissions.json unreadable: {e}"]
    admissions = doc.get("admissions") or []
    if not admissions:
        return []
    out: list[str] = []
    for rec in admissions:
        if not isinstance(rec, dict) or str(rec.get("status") or "").strip() != "ADMITTED":
            continue
        comp = rec.get("component", "?")
        evidence = rec.get("evidence")
        if not isinstance(evidence, dict):
            out.append(f"{comp}: evidence block missing for ADMITTED row")
            continue
        for field, val in evidence.items():
            s = str(val or "").strip()
            if not s or s.startswith("http://") or s.startswith("https://"):
                continue
            if not _path_resolves(s):
                out.append(
                    f"{comp}: evidence.{field}={s!r} does not resolve — ADMITTED paths must "
                    f"exist (SR 11-7 / RSK-02)",
                )
    return out


def prereg_confirmatory_violations(text: str, *, rel: str = "", file_dir: Path | None = None) -> list[str]:
    """Arnott/Harvey/Markowitz 2019 + COS prereg: CONFIRMATORY claims need resolvable prereg_path."""
    if not text or not _CONFIRMATORY.search(text):
        return []
    m = _PREREG_PATH.search(text)
    if m:
        pr = m.group(1).strip()
        if _path_resolves(pr):
            return []
    if file_dir is not None:
        for name in ("prereg_v1.json", "prereg.json"):
            if (file_dir / name).is_file():
                return []
    prefix = f"{rel}: " if rel else ""
    return [
        f"{prefix}CONFIRMATORY claim without resolvable prereg_path or prereg_v1.json "
        f"(Arnott/Harvey/Markowitz 2019; Nosek TOP/COS 2015)",
    ]


def purged_cv_violations(source: str, *, rel: str = "") -> list[str]:
    """AFML Ch.7: plain sklearn KFold/train_test_split on financial research paths → BLOCK."""
    if _LEAKAGE_OK.search(source) or _PURGE_MARKERS.search(source):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    banned_used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sklearn"):
            for alias in node.names:
                if alias.name in _BANNED_CV:
                    banned_used.add(alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[-1]
                if base in _BANNED_CV:
                    banned_used.add(base)
        if isinstance(node, ast.Call):
            fn = node.func
            name = ""
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name in _BANNED_CV:
                banned_used.add(name)
    if not banned_used:
        return []
    prefix = f"{rel}: " if rel else ""
    return [
        f"{prefix}uses {', '.join(sorted(banned_used))} without purge/embargo marker or "
        f"# leakage-ok: waiver (López de Prado AFML 2018)",
    ]


def decision_path_wired_violations(source: str | None = None) -> list[str]:
    """SR 11-7 fail-closed: compute_call must call evaluate_decision_path_admission before TRADE."""
    p = REPO / "call_engine.py"
    if source is None:
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ["call_engine.py missing — decision path gate unwired"]
    if not re.search(r"\bevaluate_decision_path_admission\s*\(", source):
        return ["call_engine.py does not call evaluate_decision_path_admission() (SR 11-7 WAIT gate)"]
    if "WAIT_BLOCKER_REASON_ADMISSION" not in source:
        return ["call_engine.py missing WAIT_BLOCKER_REASON_ADMISSION — admission WAIT not surfaced"]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "compute_call":
            fn_src = ast.get_source_segment(source, node) or ""
            if not re.search(r"\bevaluate_decision_path_admission\s*\(", fn_src):
                return [
                    "compute_call() does not invoke evaluate_decision_path_admission() — "
                    "unadmitted TRADE path possible (SR 11-7)",
                ]
            break
    return []


# claude_cursor_parity_violations RETIRED with check_claude_cursor_guard_parity
# (governance/retired_checks.md 2026-08-24): guard-wiring parity is an operator
# merge-review property (RC-475 superseded the CODEOWNERS equivalence).


_DATASHEET_REQUIRED = frozenset({"motivation", "composition", "collection", "recommended_uses"})


def new_table_names_in_diff(diff_lines: list[str]) -> set[str]:
    names: set[str] = set()
    for ln in diff_lines:
        if not ln.startswith("+") or ln.startswith("+++"):
            continue
        m = re.search(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", ln, re.I)
        if m:
            names.add(m.group(1).lower())
    return names


def collect_datasheet_violations(table: str, yaml_text: str | None) -> list[str]:
    """Gebru et al. (2021) Datasheets for Datasets — staged new tables need YAML sections."""
    if yaml_text is None:
        return [
            f"new Collect table {table!r} staged without governance/datasheets/{table}.yaml "
            f"(Gebru et al. 2021)",
        ]
    missing = [k for k in _DATASHEET_REQUIRED if k not in yaml_text.lower()]
    if missing:
        return [
            f"governance/datasheets/{table}.yaml missing sections {missing} "
            f"(Gebru et al. 2021 Datasheets for Datasets)",
        ]
    return []
