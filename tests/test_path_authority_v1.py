"""FC-13 — one path authority: governance and product-surface from one resolve-and-compare.

These tests fail against the pre-fix tree. Before `classify_path` existed,
`turn_self_audit.is_production_path` normalised only a leading "./" and then applied a
RELATIVE-prefix `startswith` exemption, which an absolute path can never match. So
`<tmp>/scratchpad/x.py` was classified PRODUCTION even though "scratchpad/" was already in
the exemption list, and the governance question ("is this path even ours") was never asked.

The oracle here is deliberately independent of the implementation: the expectations are
stated as literal path/answer pairs derived from the mission's required controls, not
recomputed from the same prefix tuples the implementation reads.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

G = importlib.import_module("tools.pretooluse_guard")
# BEDROCK 2026-09-06: tools/turn_self_audit.py (the consumer these controls compared against
# the authority) is deleted; the controls below pin the authority alone.

REPO = Path(G.__file__).resolve().parent.parent


# --------------------------------------------------------------------------- required controls
def test_negative_control_absolute_scratchpad_is_not_governed_production(tmp_path):
    """BAD: absolute scratchpad .py outside the repo -> NOT governed production.

    This is the exact 2026-08-16 case: session scratch scripts were reported as
    'changed production code' and pulled a typed-audit obligation onto files that are not
    the product and are not even in the tree.
    """
    p = tmp_path / "scratchpad" / "post_bundle.py"
    p.parent.mkdir(parents=True)
    p.write_text("x = 1\n", encoding="utf-8")

    facts = G.classify_path(str(p))
    assert facts.governed is False, "a path outside the repository is not ours to govern"
    assert facts.production is False, "not governed cannot be production"


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


# --------------------------------------------------------------------------- one producer
def test_single_producer_no_module_redefines_the_geometry(repo_index):
    """ONE FAUCET: no module outside the authority may define its own suffix/prefix tuples.

    Independent oracle: read the tools/ sources as TEXT and look for a second definition.
    A grep-free scan, because the rule being protected is about definitions existing at all.

    TEST_SYSTEM_REHAB_V2: was an independent (REPO/"tools").glob("*.py") + per-file
    read_text -- now sources from the shared `repo_index` corpus, filtered to the
    same top-level tools/ scope.
    """
    banned_defs = ("PROD_SUFFIXES = (", "PRODUCTION_SUFFIXES = (", "NON_PROD_PREFIXES = (",
                   "NOT_PRODUCT_PREFIXES = (", "ALWAYS_ALLOWED_PREFIXES = (",
                   "_RESEARCH_PROD_SUFFIXES = (", "_RESEARCH_EXEMPT_PREFIXES = (",
                   "_PRODUCTION_SUFFIX = (", "_NON_PRODUCTION = (")
    offenders: list[str] = []
    for rel, text, _tree in sorted(repo_index.items()):
        if len(rel.parts) != 2 or rel.parts[0] != "tools":
            continue
        if rel.name == "pretooluse_guard.py":
            continue                      # the authority is allowed to define them
        for token in banned_defs:
            if token in text:
                offenders.append(f"{rel.name}: {token.strip(' =(')}")
    assert offenders == [], (
        "a second producer of the path geometry exists — one semantic truth, one computation: "
        + "; ".join(offenders)
    )


def test_rc66_lane_and_product_surface_are_distinct_questions():
    """scratchpad/ is NOT the product, but writing scratch is NOT RC-66 compliance either.

    Guards the deliberate divergence between the two prefix lists. Collapsing them would
    either loosen RC-66 over 3000+ in-repo files or widen the product surface; this test
    fails if a later change quietly does the collapse.
    """
    facts = G.classify_path("scratchpad/_probe.py")
    assert facts.governed is True
    assert facts.production is False, "scratchpad is not the product surface"
    assert facts.rc66_exempt is False, "scratchpad is not an RC-66 compliance lane"

    lane = G.classify_path("tests/test_x.py")
    assert lane.production is False and lane.rc66_exempt is True
