#!/usr/bin/env python3
"""Verify CI / objective-audit governance tooling imports and requirements-dev pins."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQUIREMENTS_DEV = REPO / "requirements-dev.txt"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# (requirements-dev.txt package name substring, import module to verify in CI)
CI_TOOLING_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("openpyxl", "openpyxl"),
    ("pytest", "pytest"),
    ("pyyaml", "yaml"),
)

# Governance modules imported during enforce_all_rules --objective-audit static locks.
CI_GOVERNANCE_IMPORT_MODULES: tuple[str, ...] = (
    "tools.build_feature_assignment_matrix_v2",
)


def _requirements_dev_text() -> str:
    if not REQUIREMENTS_DEV.is_file():
        return ""
    return REQUIREMENTS_DEV.read_text(encoding="utf-8", errors="replace")


def check_ci_tooling_dependencies() -> list[str]:
    errors: list[str] = []
    req_text = _requirements_dev_text()
    if not req_text.strip():
        errors.append("requirements-dev.txt: missing")
        return errors

    for pkg_name, import_name in CI_TOOLING_DEPENDENCIES:
        if pkg_name.lower() not in req_text.lower():
            errors.append(f"requirements-dev.txt: missing package pin for {pkg_name!r}")
        try:
            importlib.import_module(import_name)
        except ImportError as exc:
            errors.append(
                f"CI tooling import {import_name!r} failed ({exc}) — "
                f"install via requirements-dev.txt ({pkg_name})"
            )

    for mod in CI_GOVERNANCE_IMPORT_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            errors.append(
                f"CI governance import {mod!r} failed ({exc}) — "
                "ensure requirements-dev.txt lists all tooling deps"
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
