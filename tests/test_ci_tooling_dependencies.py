"""CI dependency coverage — governance tooling and runtime app imports required by objective audit."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_ci_tooling_dependencies import (  # noqa: E402
    CI_APP_IMPORT_MODULES,
    CI_GOVERNANCE_IMPORT_MODULES,
    CI_RUNTIME_DEPENDENCIES,
    CI_SCHWAB_SCANNER_IMPORT_MODULES,
    CI_TOOLING_DEPENDENCIES,
    check_ci_tooling_dependencies,
    check_schwab_csv_first_workflow_installs_scanner_deps,
)


@pytest.mark.parametrize("pkg_name,import_name", CI_TOOLING_DEPENDENCIES)
def test_ci_tooling_dependency_importable(pkg_name: str, import_name: str) -> None:
    req = (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    assert pkg_name.lower() in req.lower(), f"{pkg_name} must be pinned in requirements-dev.txt"
    importlib.import_module(import_name)


@pytest.mark.parametrize("pkg_name,import_name", CI_RUNTIME_DEPENDENCIES)
def test_ci_runtime_dependency_importable(pkg_name: str, import_name: str) -> None:
    req = (REPO / "requirements.txt").read_text(encoding="utf-8")
    assert pkg_name.lower() in req.lower(), f"{pkg_name} must be pinned in requirements.txt"
    importlib.import_module(import_name)


@pytest.mark.parametrize("module", CI_GOVERNANCE_IMPORT_MODULES)
def test_ci_governance_module_importable(module: str) -> None:
    importlib.import_module(module)


@pytest.mark.parametrize("module", CI_APP_IMPORT_MODULES)
def test_ci_app_module_importable(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHWAB_API_KEY", "ci-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "ci-test-secret-not-live")
    importlib.import_module(module)


def test_build_feature_assignment_matrix_v2_imports_openpyxl() -> None:
    importlib.import_module("tools.build_feature_assignment_matrix_v2")
    importlib.import_module("openpyxl")


def test_pytest_conftest_sets_ci_schwab_placeholders() -> None:
    """Adversarial server imports rely on tests/conftest.py module-level placeholders."""
    from config import schwab_credentials_are_ci_placeholders

    conftest = (REPO / "tests/conftest.py").read_text(encoding="utf-8")
    assert "ci-placeholder-api-key" in conftest
    assert "ci-placeholder-app-secret" in conftest
    assert schwab_credentials_are_ci_placeholders(
        "ci-placeholder-api-key", "ci-placeholder-app-secret"
    )
    assert schwab_credentials_are_ci_placeholders(
        "ci-not-live-placeholder", "ci-not-live-placeholder"
    )


def test_check_ci_tooling_dependencies_passes_on_current_repo() -> None:
    errs = check_ci_tooling_dependencies()
    assert errs == [], errs


def test_schwab_csv_first_workflow_installs_scanner_deps_before_register_gen() -> None:
    wf = REPO / ".github/workflows/schwab-csv-first.yml"
    text = wf.read_text(encoding="utf-8")
    scanner_idx = text.index("schwab_universal_coverage_scanner_v3")
    assert "pip install -r requirements-dev.txt" in text[:scanner_idx]
    assert check_schwab_csv_first_workflow_installs_scanner_deps() == []


@pytest.mark.parametrize("module", CI_SCHWAB_SCANNER_IMPORT_MODULES)
def test_schwab_scanner_module_importable(module: str) -> None:
    importlib.import_module(module)
