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

_SIGNIFICANCE_CLAIM = re.compile(
    r"\b(significant|significance|Sharpe|sharpe|alpha|p[\-\s]?value|deflated_sharpe|DSR|PBO)\b",
    re.I,
)
_UNVERIFIED_TAG = re.compile(r"\[UNVERIFIED\]|\[HYPOTHESIS\]|UNPROVEN", re.I)
_N_TRIALS = re.compile(r"\bn_trials\s*[:=]\s*\d+", re.I)
_MULT_TEST = re.compile(
    r"\bmultiple_testing_method\s*[:=]\s*['\"]?(bonferroni|bh|dsr|hlz|fdr|bonferroni-holm)['\"]?",
    re.I,
)
_JSON_N_TRIALS = re.compile(r'"n_trials"\s*:\s*[1-9]\d*')
_JSON_MULT = re.compile(
    r'"multiple_testing_method"\s*:\s*"(bonferroni|bh|dsr|hlz|fdr|bonferroni-holm)"',
    re.I,
)
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
_PATH_LIKE = re.compile(r"^[\w./\\-]+\.(?:py|md|json|html|sql)$")


def _path_resolves(ref: str) -> bool:
    try:
        from tools.plus_player_locks import research_path_resolves
    except ImportError:
        from plus_player_locks import research_path_resolves  # type: ignore
    return research_path_resolves(ref)


def significance_substance_violations(text: str, *, rel: str = "") -> list[str]:
    """Harvey–Liu–Zhu / Bailey–LdP DSR: significance claims need n_trials + method or [UNVERIFIED]."""
    if not text or not _SIGNIFICANCE_CLAIM.search(text):
        return []
    if _UNVERIFIED_TAG.search(text):
        return []
    has_trials = bool(_N_TRIALS.search(text) or _JSON_N_TRIALS.search(text))
    has_method = bool(_MULT_TEST.search(text) or _JSON_MULT.search(text))
    if has_trials and has_method:
        return []
    prefix = f"{rel}: " if rel else ""
    return [
        f"{prefix}significance/Sharpe/alpha claim without n_trials + multiple_testing_method "
        f"(bonferroni|bh|dsr|hlz) — tag [UNVERIFIED] or add trial ledger (Harvey–Liu–Zhu 2016; "
        f"Bailey & López de Prado DSR 2014)",
    ]


def admission_evidence_resolves_violations(doc: dict | None = None) -> list[str]:
    """SR 11-7: ADMITTED registry rows — every evidence ref must resolve to a repo file."""
    if doc is None:
        p = REPO / "governance" / "decision_path_admissions.json"
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


def claude_cursor_parity_violations(
    cursor_text: str | None = None,
    claude_text: str | None = None,
) -> list[str]:
    """RC-205/209 continuum: Claude Stop/PreToolUse must invoke the same .py guards as Cursor."""
    need = (
        "operator_law_guard.py",
        "pretooluse_guard.py",
        "stop_guard.py",
        "proof_only_guard.py",
        "honesty_guard.py",
        "process_lock_guard.py",  # RC-217: operating-process lock fires on BOTH agents or neither counts
    )
    out: list[str] = []
    cp = REPO / ".cursor" / "hooks.json"
    sp = REPO / ".claude" / "settings.json"
    if cursor_text is None:
        try:
            cursor_text = cp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out.append(".cursor/hooks.json missing")
            cursor_text = ""
    if claude_text is None:
        try:
            claude_text = sp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out.append(".claude/settings.json missing")
            claude_text = ""
    for n in need:
        if n not in cursor_text:
            out.append(f".cursor/hooks.json missing {n}")
        if n not in claude_text:
            out.append(f".claude/settings.json missing {n} (Cursor parity RC-205/209)")
    return out


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
