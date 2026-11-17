"""Every test file serves the app: it runs app code of its own, or it is a rail.

Reads coverage.py's per-test record of a pytest run (`--cov-context=test`). A test file runs app
code of its own when it runs an app line (not under tools/ or tests/) that not every test file
runs (conftest's autouse fixture runs a few for all). A rail guards production or the credentials
and is marked `pytestmark = pytest.mark.rail`. Any other test file is named and the check fails.

    python -m tools.check_tests_serve_app .coverage
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from coverage import CoverageData

RAIL = "pytestmark = pytest.mark.rail"


def app_lines_by_test_file(data: CoverageData) -> dict[str, set[tuple[str, int]]]:
    """Return each test file the run ran with its app lines, from the per-test contexts."""
    out: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for context in data.measured_contexts():
        if context:
            out[context.split("::")[0]] = set()
    for path in data.measured_files():
        rel = Path(path).as_posix()
        if rel.startswith(("tools/", "tests/")):
            continue
        for line, contexts in data.contexts_by_lineno(path).items():
            for context in contexts:
                if context:
                    out[context.split("::")[0]].add((rel, line))
    return out


def serving_nothing(by_file: dict[str, set[tuple[str, int]]], rails: set[str]) -> list[str]:
    """Return the test files that are not rails and run no app line of their own."""
    ran = [lines for lines in by_file.values() if lines]
    every = set.intersection(*ran) if ran else set()
    return sorted(f for f, lines in by_file.items() if f not in rails and not lines - every)


def main(argv: list[str]) -> str | None:
    """Return the failure message naming each test file that serves nothing, else None."""
    data = CoverageData(argv[0])
    data.read()
    tests = Path("tests")
    rails = {p.as_posix() for p in tests.glob("test_*.py") if RAIL in p.read_text("utf-8")}
    bad = serving_nothing(app_lines_by_test_file(data), rails)
    return "\n".join(f"{n}: runs no app code of its own and is not a rail" for n in bad) or None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
