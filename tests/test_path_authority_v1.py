"""One path authority: governance and product surface from one resolve-and-compare
(tools/pretooluse_guard.classify_path). A relative-prefix `startswith` test can never match an
absolute path, so it would class `<tmp>/scratchpad/x.py` as production; these controls pin the
answers for absolute and relative paths alike.

The oracle is independent of the implementation: the expectations are literal path/answer
pairs, not recomputed from the prefix tuples the implementation reads.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

G = importlib.import_module("tools.pretooluse_guard")

REPO = Path(G.__file__).resolve().parent.parent


# --------------------------------------------------------------------------- required controls
def test_legitimate_control_absolute_repo_production_path():
    """GOOD: absolute repo production .py -> governed + production."""
    facts = G.classify_path(str(REPO / "tools" / "operator_law_guard.py"))
    assert facts.governed is True
    assert facts.production is True


def test_legitimate_control_relative_repo_production_path():
    """GOOD: relative repo production .py -> governed + production."""
    facts = G.classify_path("tools/operator_law_guard.py")
    assert facts.governed is True
    assert facts.production is True
    assert facts.rel == "tools/operator_law_guard.py"


@pytest.mark.parametrize("rel", [
    "tests/test_path_authority_v1.py",
    "governance/root_cause_log.md",
    "docs/anything.py",
    "reports/anything.py",
    ".claude/settings.json",
    "calibration/anything.py",
])
def test_legitimate_control_repo_non_production_paths(rel):
    """GOOD: repo compliance-lane paths -> governed + NON-production."""
    facts = G.classify_path(rel)
    assert facts.governed is True, rel
    assert facts.production is False, rel


def test_fail_closed_unresolvable_path_is_not_silently_ungoverned(monkeypatch):
    """FAIL-CLOSED: a purported repo path that cannot be resolved stays ours AND production.

    Unmeasurable is never ungoverned. Resolution is forced to raise so the branch is
    exercised for real rather than asserted about.
    """
    real_resolve = Path.resolve

    def boom(self, *a, **k):
        raise OSError("resolution unavailable")

    monkeypatch.setattr(Path, "resolve", boom)
    try:
        facts = G.classify_path("tools/server.py")
    finally:
        monkeypatch.setattr(Path, "resolve", real_resolve)

    assert facts.governed is True, "unresolvable must not become ungoverned"
    assert facts.production is True, "unresolvable must not become non-production"
    assert facts.rc66_exempt is False, "unresolvable must not acquire a compliance exemption"


def test_the_compliance_surface_and_the_product_surface_are_distinct_questions():
    """scratchpad/ is NOT the product, but writing scratch is not complying either.

    Guards the deliberate divergence between the two prefix lists: collapsing them would either
    let every product file be edited as a compliance surface or widen the product surface.
    """
    facts = G.classify_path("scratchpad/_probe.py")
    assert facts.governed is True
    assert facts.production is False, "scratchpad is not the product surface"
    assert facts.rc66_exempt is False, "scratchpad is not a compliance surface"

    lane = G.classify_path("tests/test_x.py")
    assert lane.production is False and lane.rc66_exempt is True
