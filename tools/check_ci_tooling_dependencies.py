#!/usr/bin/env python3
"""Verify CI / objective-audit imports and requirements pins."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO / "requirements.txt"
REQUIREMENTS_DEV = REPO / "requirements-dev.txt"
SCHWAB_CSV_FIRST_WORKFLOW = REPO / ".github/workflows/schwab-csv-first.yml"

# Scanner v3 imports (PR register generation in schwab-csv-first.yml).
CI_SCHWAB_SCANNER_IMPORT_MODULES: tuple[str, ...] = (
    "tools.schwab_universal_coverage_scanner_v3.schwab_csv",
)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# (requirements-dev.txt package name substring, import module to verify in CI)
CI_TOOLING_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("openpyxl", "openpyxl"),
    ("pytest", "pytest"),
    ("pyyaml", "yaml"),
)

# Runtime deps from requirements.txt (server / Schwab client path).
CI_RUNTIME_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("schwab-py", "schwab"),
)

# Governance modules imported during enforce_all_rules --objective-audit static locks.
CI_GOVERNANCE_IMPORT_MODULES: tuple[str, ...] = (
    "tools.build_feature_assignment_matrix_v2",
)

# App modules adversarial / objective-audit jobs import without live Schwab credentials.
CI_APP_IMPORT_MODULES: tuple[str, ...] = (
    "schwab_client",
    "server",
)


def _requirements_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _ensure_ci_schwab_env() -> None:
    """Placeholder secrets so ``import server`` is CI-safe (no live auth at import)."""
    os.environ.setdefault("SCHWAB_API_KEY", "ci-placeholder-key")
    os.environ.setdefault("SCHWAB_APP_SECRET", "ci-placeholder-secret")


def check_schwab_csv_first_workflow_installs_scanner_deps() -> list[str]:
    """PR register-gen step needs requirements-dev (numpy) — push path skips scanner."""
    errors: list[str] = []
    if not SCHWAB_CSV_FIRST_WORKFLOW.is_file():
        errors.append(".github/workflows/schwab-csv-first.yml: missing")
        return errors
    text = SCHWAB_CSV_FIRST_WORKFLOW.read_text(encoding="utf-8", errors="replace")
    scanner_marker = "schwab_universal_coverage_scanner_v3"
    idx = text.find(scanner_marker)
    if idx < 0:
        return errors
    prefix = text[:idx]
    if "pip install -r requirements-dev.txt" not in prefix:
        errors.append(
            "schwab-csv-first.yml: must run `pip install -r requirements-dev.txt` "
            "before schwab_universal_coverage_scanner_v3 (PR register generation needs numpy)"
        )
    if "numpy" not in _requirements_text(REQUIREMENTS_DEV).lower():
        errors.append("requirements-dev.txt: missing numpy pin for schwab scanner v3")
    return errors


def check_ci_tooling_dependencies() -> list[str]:
    errors: list[str] = []
    req_dev_text = _requirements_text(REQUIREMENTS_DEV)
    req_runtime_text = _requirements_text(REQUIREMENTS)
    if not req_dev_text.strip():
        errors.append("requirements-dev.txt: missing")
    if not req_runtime_text.strip():
        errors.append("requirements.txt: missing")

    for pkg_name, import_name in CI_TOOLING_DEPENDENCIES:
        if pkg_name.lower() not in req_dev_text.lower():
            errors.append(f"requirements-dev.txt: missing package pin for {pkg_name!r}")
        try:
            importlib.import_module(import_name)
        except ImportError as exc:
            errors.append(
                f"CI tooling import {import_name!r} failed ({exc}) — "
                f"install via requirements-dev.txt ({pkg_name})"
            )

    for pkg_name, import_name in CI_RUNTIME_DEPENDENCIES:
        if pkg_name.lower() not in req_runtime_text.lower():
            errors.append(f"requirements.txt: missing package pin for {pkg_name!r}")
        try:
            importlib.import_module(import_name)
        except ImportError as exc:
            errors.append(
                f"CI runtime import {import_name!r} failed ({exc}) — "
                f"install via requirements.txt ({pkg_name})"
            )

    for mod in CI_GOVERNANCE_IMPORT_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            errors.append(
                f"CI governance import {mod!r} failed ({exc}) — "
                "ensure requirements-dev.txt lists all tooling deps"
            )

    _ensure_ci_schwab_env()
    for mod in CI_APP_IMPORT_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            errors.append(
                f"CI app import {mod!r} failed ({exc}) — "
                "ensure requirements.txt includes runtime deps (schwab-py) "
                "and SCHWAB_* placeholder env is set"
            )

    errors.extend(check_schwab_csv_first_workflow_installs_scanner_deps())

    for mod in CI_SCHWAB_SCANNER_IMPORT_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            errors.append(
                f"Schwab scanner import {mod!r} failed ({exc}) — "
                "install requirements-dev.txt before CI scanner step"
            )

    return errors


def main() -> int:
    errs = check_ci_tooling_dependencies()
    if errs:
        print("check_ci_tooling_dependencies: FAIL\n- " + "\n- ".join(errs))
        return 1
    print("check_ci_tooling_dependencies: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
