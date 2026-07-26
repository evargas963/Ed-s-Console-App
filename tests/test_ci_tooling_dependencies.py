"""CI dependency coverage — the tooling / runtime / governance / app imports the
required CI jobs (Hardening quality + pytest-full) need must be pinned and importable,
so CI never fails on a missing dependency.

Self-contained after the ED CONSOLE SLIMMING register retirement: the Schwab-scanner
dependency + workflow-ordering checks (and their tool, tools/check_ci_tooling_dependencies.py)
were removed with the scanner. The generic import coverage is inlined here.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# (requirements-dev.txt package substring, import module) — CI tooling deps.
CI_TOOLING_DEPENDENCIES = (
    ("openpyxl", "openpyxl"),
    ("pytest", "pytest"),
    ("pyyaml", "yaml"),
)
# Runtime deps from requirements.txt (server / Schwab client path).
CI_RUNTIME_DEPENDENCIES = (("schwab-py", "schwab"),)
# Governance modules imported by CI jobs.
CI_GOVERNANCE_IMPORT_MODULES = ("tools.build_feature_assignment_matrix_v2",)
# App modules CI jobs import without live Schwab credentials.
CI_APP_IMPORT_MODULES = ("schwab_client", "server")


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
    assert importlib.import_module(module).__name__ == module


@pytest.mark.parametrize("module", CI_APP_IMPORT_MODULES)
def test_ci_app_module_importable(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHWAB_API_KEY", "ci-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "ci-test-secret-not-live")
    assert importlib.import_module(module).__name__ == module


def test_build_feature_assignment_matrix_v2_imports_openpyxl() -> None:
    assert importlib.import_module("tools.build_feature_assignment_matrix_v2").__name__ == "tools.build_feature_assignment_matrix_v2"
    assert importlib.import_module("openpyxl").__name__ == "openpyxl"


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
