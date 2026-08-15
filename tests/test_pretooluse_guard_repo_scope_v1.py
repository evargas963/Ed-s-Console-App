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

import pytest

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


def test_negative_control_our_production_file_still_blocks_without_a_row(monkeypatch, capsys):
    """The rule this guard exists for must survive the fix.

    Without this, 'stop over-reaching' would silently become 'stop enforcing'.
    """
    monkeypatch.setattr(G, "_has_new_rc_row", lambda: False, raising=True)
    code = G.decide(_payload(str(REPO / "server.py")))
    assert code == 2, "an in-repo production edit with no RC row must still BLOCK"
    assert "PRODUCTION file" in capsys.readouterr().err


def test_negative_control_our_production_file_allowed_with_a_row(monkeypatch):
    monkeypatch.setattr(G, "_has_new_rc_row", lambda: True, raising=True)
    assert G.decide(_payload(str(REPO / "server.py"))) == 0


def test_negative_control_our_allowlisted_paths_never_block(monkeypatch):
    """Editing tests/ and governance/ is HOW you comply -- always permitted."""
    monkeypatch.setattr(G, "_has_new_rc_row", lambda: False, raising=True)
    for rel in ("tests/test_x.py", "governance/root_cause_log.md",
                "docs/readme.md", "reports/x.md"):
        assert G.decide(_payload(str(REPO / rel))) == 0, rel


@pytest.mark.parametrize("suffix", [".py", ".html", ".js", ".css", ".sql"])
def test_negative_control_every_production_suffix_still_governed_in_repo(
        monkeypatch, capsys, suffix):
    """The fix is scoped by REPOSITORY, never by file type."""
    monkeypatch.setattr(G, "_has_new_rc_row", lambda: False, raising=True)
    assert G.decide(_payload(str(REPO / f"someplace/thing{suffix}"))) == 2
    capsys.readouterr()
