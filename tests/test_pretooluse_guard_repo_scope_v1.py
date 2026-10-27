"""The path authority does not govern another repository: `classify_path(...).governed`, the
one predicate, is false for a path outside this checkout, whatever its suffix or folder (a
foreign tests/ file is neither production nor a compliance surface here)."""

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


def test_foreign_test_file_is_not_our_compliance_lane_either(tmp_path):
    """A foreign path is not ours — neither production nor a compliance surface."""
    other = tmp_path / "OtherRepo" / "tests"
    other.mkdir(parents=True)
    target = other / "test_something.py"
    target.write_text("", encoding="utf-8")
    facts = G.classify_path(str(target))
    assert not facts.governed and not facts.production and not facts.compliance_surface
