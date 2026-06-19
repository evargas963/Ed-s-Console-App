#!/usr/bin/env python3
"""Source-control hygiene — local runtime artifacts must not clutter git status.

Mechanical lock: untracked paths matching forbidden runtime categories fail the check
after .gitignore is applied. Governed source paths and explicitly tracked baselines are
allowlisted — see governance/docs/SOURCE_CONTROL_HYGIENE.md.
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIT_PATH = REPO / "governance" / "artifacts" / "SOURCE_CONTROL_HYGIENE_AUDIT.json"
POLICY_MD = REPO / "governance" / "docs" / "SOURCE_CONTROL_HYGIENE.md"

# Each entry: gitignore substring that must appear (conservative — not full pattern parse).
REQUIRED_GITIGNORE_MARKERS: tuple[str, ...] = (
    "_schwab_auth_url.txt",
    "backups/db/*",
    "calibration/trading_data.db",
    "logs/",
    "reports/daily_scoreboard/",
    "models/active/",
    "models/active_5c/",
    "models/active_15c/",
    "models/active_60c/",
    "feature_ablation_universe.xlsx",
    "feature_analysis.xlsx",
    "feature_consolidated_full.xlsx",
    "enforce_all_out.txt",
    "timing_probe.py",
    "timing_probe2.py",
    "static/redesign_mockup.html",
)

# Untracked paths matching these rules should never appear once .gitignore is correct.
_FORBIDDEN_UNTRACKED_EXACT: frozenset[str] = frozenset(
    {
        "_schwab_auth_url.txt",
        "calibration/trading_data.db",
        "enforce_all_out.txt",
        "feature_ablation_universe.xlsx",
        "feature_analysis.xlsx",
        "feature_consolidated_full.xlsx",
        "timing_probe.py",
        "timing_probe2.py",
        "static/redesign_mockup.html",
    }
)

_FORBIDDEN_UNTRACKED_PREFIXES: tuple[str, ...] = (
    "backups/db/",
    "logs/",
    "reports/daily_scoreboard/",
    "models/active/",
    "models/active_5c/",
    "models/active_15c/",
    "models/active_60c/",
)

_FORBIDDEN_UNTRACKED_GLOBS: tuple[str, ...] = (
    "timing_probe*.py",
)

# Repo-root extension patterns — only at depth 1 (not nested governed paths).
_FORBIDDEN_ROOT_EXTENSIONS: frozenset[str] = frozenset({".db", ".sqlite", ".pkl", ".xlsx"})

# Paths that may legitimately appear untracked (governed new source, not runtime clutter).
_UNTRACKED_ALLOWLIST_EXACT: frozenset[str] = frozenset()
_UNTRACKED_ALLOWLIST_PREFIXES: tuple[str, ...] = ()


def _norm_rel(path: str) -> str:
    return Path(path.replace("\\", "/")).as_posix()


def _git_untracked_paths(*, repo: Path | None = None) -> list[str]:
    root = repo or REPO
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return [f"__git_error__:{exc}"]
    if proc.returncode != 0:
        return [f"__git_error__:{proc.stderr.strip() or proc.returncode}"]
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4 or not line.startswith("??"):
            continue
        rel = _norm_rel(line[3:].strip())
        if rel.startswith('"') and rel.endswith('"'):
            rel = rel[1:-1]
        out.append(rel)
    return out


def _is_allowlisted_untracked(rel: str) -> bool:
    if rel in _UNTRACKED_ALLOWLIST_EXACT:
        return True
    return any(rel.startswith(p) for p in _UNTRACKED_ALLOWLIST_PREFIXES)


def classify_untracked_path(rel: str) -> str | None:
    """Return hygiene category when rel is a forbidden runtime artifact; else None."""
    if _is_allowlisted_untracked(rel):
        return None
    if rel in _FORBIDDEN_UNTRACKED_EXACT:
        return _category_for_exact(rel)
    for prefix in _FORBIDDEN_UNTRACKED_PREFIXES:
        if rel == prefix.rstrip("/") or rel.startswith(prefix):
            return _category_for_prefix(prefix)
    for pattern in _FORBIDDEN_UNTRACKED_GLOBS:
        if fnmatch.fnmatch(Path(rel).name, pattern):
            return "scratch_probe"
    parts = Path(rel).parts
    if len(parts) == 1:
        ext = Path(rel).suffix.lower()
        if ext in _FORBIDDEN_ROOT_EXTENSIONS:
            return {
                ".db": "generated_runtime_artifact",
                ".sqlite": "generated_runtime_artifact",
                ".pkl": "model_binary_output",
                ".xlsx": "analysis_output",
            }[ext]
    return None


def _category_for_exact(rel: str) -> str:
    mapping = {
        "_schwab_auth_url.txt": "local_secret_or_auth",
        "calibration/trading_data.db": "generated_runtime_artifact",
        "enforce_all_out.txt": "analysis_output",
        "feature_ablation_universe.xlsx": "analysis_output",
        "feature_analysis.xlsx": "analysis_output",
        "feature_consolidated_full.xlsx": "analysis_output",
        "timing_probe.py": "scratch_probe",
        "timing_probe2.py": "scratch_probe",
        "static/redesign_mockup.html": "scratch_probe",
    }
    return mapping.get(rel, "generated_runtime_artifact")


def _category_for_prefix(prefix: str) -> str:
    if prefix.startswith("backups/db/"):
        return "database_backup"
    if prefix.startswith("logs/"):
        return "generated_runtime_artifact"
    if prefix.startswith("reports/daily_scoreboard/"):
        return "local_report"
    if prefix.startswith("models/active"):
        return "model_binary_output"
    return "generated_runtime_artifact"


def forbidden_untracked_paths(*, repo: Path | None = None) -> list[tuple[str, str]]:
    """(path, category) pairs that should be gitignored but appear untracked."""
    hits: list[tuple[str, str]] = []
    for rel in _git_untracked_paths(repo=repo):
        if rel.startswith("__git_error__:"):
            hits.append((rel, "git_error"))
            continue
        cat = classify_untracked_path(rel)
        if cat:
            hits.append((rel, cat))
    return hits


def check_gitignore_markers() -> list[str]:
    errors: list[str] = []
    gi = REPO / ".gitignore"
    if not gi.is_file():
        return [".gitignore: missing"]
    text = gi.read_text(encoding="utf-8", errors="replace")
    for marker in REQUIRED_GITIGNORE_MARKERS:
        if marker not in text:
            errors.append(f".gitignore: missing required marker {marker!r}")
    if "!backups/db/.gitkeep" not in text:
        errors.append(".gitignore: missing !backups/db/.gitkeep (directory placeholder)")
    return errors


def check_audit_artifact() -> list[str]:
    errors: list[str] = []
    if not POLICY_MD.is_file():
        errors.append(f"{POLICY_MD.relative_to(REPO).as_posix()}: missing")
    if not AUDIT_PATH.is_file():
        errors.append(f"{AUDIT_PATH.relative_to(REPO).as_posix()}: missing")
        return errors
    try:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"SOURCE_CONTROL_HYGIENE_AUDIT.json: unreadable ({exc})")
        return errors
    if audit.get("schema_version") != 1:
        errors.append("SOURCE_CONTROL_HYGIENE_AUDIT.json: schema_version must be 1")
    if not isinstance(audit.get("classifications"), list):
        errors.append("SOURCE_CONTROL_HYGIENE_AUDIT.json: classifications must be a list")
    elif not audit["classifications"]:
        errors.append("SOURCE_CONTROL_HYGIENE_AUDIT.json: classifications empty")
    for key in ("policy_doc", "checker_module", "required_gitignore_markers"):
        if key not in audit:
            errors.append(f"SOURCE_CONTROL_HYGIENE_AUDIT.json: missing key {key!r}")
    return errors


def check_source_control_hygiene(*, repo: Path | None = None) -> list[str]:
    """Full hygiene check — gitignore markers + no forbidden untracked paths + audit artifact."""
    errors: list[str] = []
    errors.extend(check_gitignore_markers())
    errors.extend(check_audit_artifact())
    for rel, cat in forbidden_untracked_paths(repo=repo):
        if cat == "git_error":
            errors.append(f"source-control hygiene: cannot run git ({rel})")
        else:
            errors.append(
                f"source-control hygiene: untracked {cat} {rel!r} — add to .gitignore or remove"
            )
    return errors


def build_audit_snapshot(*, repo: Path | None = None) -> dict:
    """Regenerate audit JSON body (classifications + live untracked scan)."""
    forbidden = forbidden_untracked_paths(repo=repo)
    return {
        "schema_version": 1,
        "policy_doc": "governance/docs/SOURCE_CONTROL_HYGIENE.md",
        "checker_module": "tools/check_source_control_hygiene.py",
        "required_gitignore_markers": list(REQUIRED_GITIGNORE_MARKERS),
        "forbidden_untracked_count": len(forbidden),
        "forbidden_untracked_sample": [{"path": p, "category": c} for p, c in forbidden[:20]],
        "git_status_clean": len(forbidden) == 0,
    }


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--write-audit":
        body = build_audit_snapshot()
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {AUDIT_PATH.relative_to(REPO)}")
        return 0
    errs = check_source_control_hygiene()
    if errs:
        print("check_source_control_hygiene: FAIL\n- " + "\n- ".join(errs))
        return 1
    print("check_source_control_hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
