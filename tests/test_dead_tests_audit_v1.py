"""dead_tests_audit_v1 classifier contracts."""
from __future__ import annotations

import ast

from tools.dead_tests_audit_v1 import classify_test, scan


def test_presence_only_classified():
    src = '''
def test_lock():
    src = Path("x").read_text(encoding="utf-8")
    assert "hello" in src
'''
    tree = ast.parse(src)
    fn = tree.body[0]
    # Path not imported — body still matches heuristic
    row = classify_test(src, fn)
    assert row["presence_class"] == "PRESENCE_ONLY"


def test_runtime_call_not_presence_only():
    src = '''
def test_runtime():
    from research.tcn_eval_v1.runner import session_safe_log_returns
    import numpy as np
    r = session_safe_log_returns(np.array([1.0]), np.array([1.0]))
    assert r is not None
'''
    tree = ast.parse(src)
    row = classify_test(src, tree.body[0])
    assert row["presence_class"] == "NONE"
    assert row["assert_free"] is False


def test_scan_reports_live_counts():
    """RC-524: the scan classifies the living suite only. It used to pin `archive_test_functions
    >= 1`, a presence pin on tests/archive/, which the bedrock program deleted on purpose
    (498897ce) — a control that fails because landfill was removed protects the landfill."""
    rep = scan()
    assert rep["schema"] == "dead_tests_audit_v1"
    c = rep["counts"]
    assert c["live_test_functions"] >= 1
    assert "archive_test_functions" not in c
    assert "archive_files" not in rep
    assert "presence_only" in c


def test_scan_counts_a_constructed_suite_exactly(tmp_path, monkeypatch):
    """The `> 1000` pin this replaced (RC-549/RC-550 class) measured the tree's size, not the
    scanner: a constructed suite of two tests, one assert-free, must count as exactly that."""
    import tools.dead_tests_audit_v1 as mod
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_two.py").write_text(
        "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    x = 1\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "TESTS", tests)
    c = mod.scan()["counts"]
    assert c["live_test_functions"] == 2 and c["assert_free"] == 1
