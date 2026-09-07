"""RC-259 — pretooluse_guard must not govern another repository.

WHAT WAS MEASURED (2026-08-05, deepened 2026-08-06). The guard classified an
edit target by file suffix alone, with no repository-root predicate:

  * An Edit to <other-checkout>/ieos/__init__.py was refused with "You are
    editing PRODUCTION file", demanding a root-cause row in THIS repository's
    ledger as the price of editing a file this repository does not own.
  * Worse than over-reach: `_rel()` returns the ABSOLUTE path when
    `relative_to(REPO)` raises, and an absolute path starts with a drive
    letter, so it matches NO entry in ALWAYS_ALLOWED_PREFIXES. The guard
    therefore applied its strictest rule to a foreign tree while silently
    voiding the tests/, governance/, docs/, reports/, .claude/ and
    calibration/ escape hatches that make the rule survivable. An edit to
    <other-checkout>/tests/test_x.py -- pure compliance work -- was refused.

These tests fail against the pre-fix tree: before `is_foreign_path` existed
there was no repository predicate at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pretooluse_guard as G  # noqa: E402


# ------------------------------------------------------ the predicate ----

def test_paths_inside_this_repository_are_ours():
    for rel in ("server.py", "tools/pretooluse_guard.py", "tests/conftest.py",
                "static/index.html", "governance/root_cause_log.md"):
        assert not G.is_foreign_path(str(REPO / rel)), rel


def test_paths_in_another_checkout_are_foreign(tmp_path):
    other = tmp_path / "OtherRepo"
    (other / "src").mkdir(parents=True)
    target = other / "src" / "module.py"
    target.write_text("x = 1\n", encoding="utf-8")
    assert G.is_foreign_path(str(target))


def test_unresolvable_paths_fail_closed_as_ours(monkeypatch):
    """An unresolvable path must stay governed, never be waved through."""
    monkeypatch.setattr(
        G.Path, "resolve",
        lambda self, *a, **k: (_ for _ in ()).throw(OSError("boom")),
        raising=True)
    assert G.is_foreign_path("anything") is False


# --------------------------------------------------- negative controls ----

def _payload(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path}}


def test_negative_control_foreign_production_file_is_allowed(tmp_path, capsys):
    """The exact over-reach: a .py in another checkout must NOT be blocked."""
    other = tmp_path / "OtherRepo" / "pkg"
    other.mkdir(parents=True)
    target = other / "__init__.py"
    target.write_text("", encoding="utf-8")
    assert G.decide(_payload(str(target))) == 0
    assert "PRODUCTION file" not in capsys.readouterr().err


def test_negative_control_foreign_test_file_is_allowed(tmp_path, capsys):
    """The compounding defect: the tests/ escape hatch was void for foreign paths."""
    other = tmp_path / "OtherRepo" / "tests"
    other.mkdir(parents=True)
    target = other / "test_something.py"
    target.write_text("", encoding="utf-8")
    assert G.decide(_payload(str(target))) == 0
    assert "PRODUCTION file" not in capsys.readouterr().err


# RC-470: the RC-66 production-file-needs-a-row lane is retired with its commit-time
# twin (governance/retired_checks.md), and the four blocking-behavior negative controls
# left with it. The repo-scope predicate and the foreign-path controls above are this
# file's surviving subject; in-repo edits are now ALLOWED regardless of ledger state:


# SUPERSEDED, and named rather than quietly deleted. RC-470 retired the RC-66 lane, which
# demanded a row before editing ANY production file -- a row per edited FILE, correctly judged
# sprawl; that retirement stands. RC-498 (operator 2026-09-01) reinstates a NARROWER rule: ONE
# row for the session's mission. So the answer to "may an in-repo production edit proceed with
# no ledger state at all" is now no.
#
# The assertion below replaced one that read the LIVE ledger, so it passed or failed according
# to whether the checkout happened to carry an active row -- green on my branch because my own
# mission rows were open, red in CI where they were not. Both replacements are hermetic.


def test_our_production_file_is_not_gated_by_a_mission_row(capsys):
    """BEDROCK 2026-09-06: the RC-498 mutation-side latch is gone. Work identity is the branch
    and PR; a defect gets a row by doctrine; the Stop seam holds an unfinished row. A production
    edit is judged by the path facts alone here and passes."""
    assert G.decide(_payload(str(REPO / "server.py"))) == 0
    assert capsys.readouterr().err == ""


def test_negative_control_our_allowlisted_paths_never_block():
    for rel in ("tests/test_x.py", "governance/root_cause_log.md",
                "docs/readme.md", "reports/x.md"):
        assert G.decide(_payload(str(REPO / rel))) == 0, rel
