"""One path authority: product surface from one resolve-and-compare against the repository root.

A relative-prefix `startswith` exemption can never match an absolute path, so an absolute
`<tmp>/scratchpad/x.py` was once classified production. The expectations are literal
path/answer pairs, not recomputed from the prefix tuples the implementation reads.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

G = importlib.import_module("tools.pretooluse_guard")

REPO = Path(G.__file__).resolve().parent.parent


def test_negative_control_absolute_scratchpad_is_not_production(tmp_path):
    """An absolute scratchpad .py outside the repository is not this repository's product."""
    p = tmp_path / "scratchpad" / "post_bundle.py"
    p.parent.mkdir(parents=True)
    p.write_text("x = 1\n", encoding="utf-8")

    assert G.is_production_path(str(p)) is False


def test_a_path_in_another_checkout_is_not_production(tmp_path):
    target = tmp_path / "OtherRepo" / "src" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")
    assert G.is_production_path(str(target)) is False


def test_legitimate_control_absolute_repo_production_path():
    assert G.is_production_path(str(REPO / "tools" / "operator_law_guard.py")) is True


def test_legitimate_control_relative_repo_production_path():
    assert G.is_production_path("tools/operator_law_guard.py") is True


@pytest.mark.parametrize("rel", [
    "tests/test_path_authority_v1.py",
    "governance/root_cause_log.md",
    "docs/anything.py",
    "reports/anything.py",
    ".claude/settings.json",
    "calibration/anything.py",
    "scratchpad/_probe.py",
])
def test_legitimate_control_repo_non_production_paths(rel):
    """In-repository paths that are not the product."""
    assert G.is_production_path(rel) is False, rel


def test_fail_closed_unresolvable_path_is_production(monkeypatch):
    """A purported repo path that cannot be resolved is production: unmeasurable is never
    waved through. Resolution is forced to raise so the branch is exercised for real."""
    real_resolve = Path.resolve

    def boom(self, *a, **k):
        raise OSError("resolution unavailable")

    monkeypatch.setattr(Path, "resolve", boom)
    try:
        production = G.is_production_path("tools/server.py")
    finally:
        monkeypatch.setattr(Path, "resolve", real_resolve)

    assert production is True
