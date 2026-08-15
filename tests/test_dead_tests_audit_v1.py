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


def test_scan_reports_archive_and_live_counts():
    rep = scan()
    assert rep["schema"] == "dead_tests_audit_v1"
    c = rep["counts"]
    assert c["live_test_functions"] > 1000
    assert c["archive_test_functions"] >= 1
    assert "presence_only" in c
