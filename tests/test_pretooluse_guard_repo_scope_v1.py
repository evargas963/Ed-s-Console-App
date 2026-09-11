"""RC-259 — the path authority must not govern another repository.

WHAT WAS MEASURED (2026-08-05, deepened 2026-08-06). The guard classified an edit target by
file suffix alone, with no repository-root predicate: an Edit to <other-checkout>/ieos/
__init__.py was refused as a PRODUCTION file, and `_rel()` fell back to the ABSOLUTE path,
which matches NO entry in ALWAYS_ALLOWED_PREFIXES — so a foreign tests/ file was refused too.

KEEP/MERGE/DELETE 2026-09-10: the inert hook shape (`decide`/`main`, returning 0 for every
event) and the `is_foreign_path` accessor are gone; `classify_path(...).governed` is the ONE
predicate and these controls drive it directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pretooluse_guard as G  # noqa: E402


def test_paths_inside_this_repository_are_ours():
    for rel in ("server.py", "tools/pretooluse_guard.py", "tests/conftest.py",
                "static/index.html", "governance/root_cause_log.md"):
        assert G.classify_path(str(REPO / rel)).governed, rel


def test_paths_in_another_checkout_are_foreign(tmp_path):
    other = tmp_path / "OtherRepo"
    (other / "src").mkdir(parents=True)
    target = other / "src" / "module.py"
    target.write_text("x = 1\n", encoding="utf-8")
    facts = G.classify_path(str(target))
    assert not facts.governed and not facts.production


def test_unresolvable_paths_fail_closed_as_ours(monkeypatch):
    """An unresolvable path must stay governed, never be waved through."""
    monkeypatch.setattr(
        G.Path, "resolve",
        lambda self, *a, **k: (_ for _ in ()).throw(OSError("boom")),
        raising=True)
    facts = G.classify_path("anything")
    assert facts.governed and facts.production and not facts.rc66_exempt


def test_foreign_test_file_is_not_our_compliance_lane_either(tmp_path):
    """The compounding defect: the tests/ escape hatch was void for foreign paths. A foreign
    path is simply not ours — neither production nor an RC-66 lane."""
    other = tmp_path / "OtherRepo" / "tests"
    other.mkdir(parents=True)
    target = other / "test_something.py"
    target.write_text("", encoding="utf-8")
    facts = G.classify_path(str(target))
    assert not facts.governed and not facts.production and not facts.rc66_exempt


def test_the_library_carries_no_hook_entrypoint():
    """A file that judged nothing (every event -> 0, an unreadable payload -> 0) is off the
    rosters and no longer shaped like a guard."""
    for gone in ("main", "decide", "is_foreign_path", "_git", "_rel"):
        assert not hasattr(G, gone), gone
    src = Path(G.__file__).read_text(encoding="utf-8")
    assert "sys.stdin" not in src and "__main__" not in src
