"""tools.check_tests_serve_app names a test file that runs no app code of its own."""

from __future__ import annotations

import pytest

from tools.check_tests_serve_app import serving_nothing

pytestmark = pytest.mark.rail

SETUP = {("live_market_plane.py", 230), ("live_market_plane.py", 231)}


def test_a_test_file_running_only_the_shared_setup_is_named():
    by_file = {
        "tests/test_levels.py": SETUP | {("calc/math_levels.py", 40)},
        "tests/test_docs.py": set(SETUP),
    }
    assert serving_nothing(by_file, set()) == ["tests/test_docs.py"]


def test_a_rail_is_not_named():
    by_file = {
        "tests/test_levels.py": SETUP | {("calc/math_levels.py", 40)},
        "tests/test_guard.py": set(SETUP),
    }
    assert serving_nothing(by_file, {"tests/test_guard.py"}) == []


def test_a_test_file_that_ran_no_app_line_at_all_is_named():
    by_file = {
        "tests/test_levels.py": SETUP | {("calc/math_levels.py", 40)},
        "tests/test_flow.py": SETUP | {("calc/order_flow.py", 12)},
        "tests/x.py": set(),
    }
    assert serving_nothing(by_file, set()) == ["tests/x.py"]
