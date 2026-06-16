"""CI dependency coverage — governance tooling imports required by objective audit."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_ci_tooling_dependencies import (  # noqa: E402
    CI_GOVERNANCE_IMPORT_MODULES,
    CI_TOOLING_DEPENDENCIES,
    check_ci_tooling_dependencies,
)


@pytest.mark.parametrize("pkg_name,import_name", CI_TOOLING_DEPENDENCIES)
def test_ci_tooling_dependency_importable(pkg_name: str, import_name: str) -> None:
    req = (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    assert pkg_name.lower() in req.lower(), f"{pkg_name} must be pinned in requirements-dev.txt"
    importlib.import_module(import_name)


@pytest.mark.parametrize("module", CI_GOVERNANCE_IMPORT_MODULES)
def test_ci_governance_module_importable(module: str) -> None:
    importlib.import_module(module)


def test_build_feature_assignment_matrix_v2_imports_openpyxl() -> None:
    importlib.import_module("tools.build_feature_assignment_matrix_v2")
    importlib.import_module("openpyxl")


def test_check_ci_tooling_dependencies_passes_on_current_repo() -> None:
    errs = check_ci_tooling_dependencies()
    assert errs == [], errs
