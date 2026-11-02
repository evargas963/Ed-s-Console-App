"""AGENTS.md rule 14: what a change may not take from its tests, and the review it must carry.

Run from the base by `.github/workflows/locks.yml`; the head is read as data, none of its code runs.

Test integrity, every pull request:
   - an assertion of a test that survives is not lost. A test is its function name in Python and
     its title in a Playwright spec, across every changed test file, so a moved test is the same
     test and a rewritten one may restate its assertions. An assertion gone with its test, or
     with a function it names that this change deleted, is the review's to judge;
   - no line added to code skips a test or leaves a deferred-work marker. A line moved is not added.

Review record, in the description's `## Review` section (`Commit:` the head, `Verdict:` PASS or
FAIL): required when the change touches what governs changes, and when present it must name the
head and not be a FAIL. This proves the record's presence and commit only, never who wrote it.

    python tools/check_integrity.py --base <rev> --body-file <file> --head-sha <sha>

Exit 0: clean. Exit 1: each violation on its own line. Exit 2: the check itself failed.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

CODE_SUFFIXES = (".py", ".js", ".mjs", ".html", ".yml")
PYTHON_TESTS = re.compile(r"^tests/.*\.py$")
JS_TESTS = re.compile(r"^tests/e2e/.*\.spec\.js$")
# spelled in pieces so that this file and its test add no line the check refuses
MARKERS = re.compile(
    "|".join(
        (
            r"@pytest\.mark\." "skip",
            "skipif",
            r"pytest\." r"skip\(",
            r"unittest\." "skip",
            "importorskip",
            "xfail",
            r"\b(?:test|describe|it)\." r"(?:skip|fixme|fail)\b",
            r"\bx" r"(?:it|describe)\b",
            r"\bTO" r"DO\b",
            r"\bFIX" r"ME\b",
        )
    )
)
GOVERNING = re.compile(
    r"^(AGENTS\.md|docs/DATA_FLOW\.md|ACTIVE_PROGRAM\.md|locks\.ruff\.toml"
    r"|\.github/.*|\.claude/.*|\.cursor/.*"
    r"|tools/(hook_chain|check_\w+|after_deploy_check)\.py"
    r"|tests/test_(governing_docs|test_rules|hook_chain)_v1\.py)$"
)
NAME = re.compile(r"\w+")
JS_TEST = re.compile(r"""\btest(?:\.\w+)?\(\s*(['"`])(.*?)(?<!\\)\1""", re.S)
JS_EXPECT = re.compile(r"\bexpect(?:\.\w+)?\([^;]*;")
REVIEW = re.compile(r"^## Review[ \t]*$(.*?)(?=^## |\Z)", re.M | re.S)
COMMIT = re.compile(r"^Commit:[ \t]*(\S+)[ \t]*$", re.M)
VERDICT = re.compile(r"^Verdict:[ \t]*(\S+)[ \t]*$", re.M)


class ToolError(Exception):
    def __init__(self, what: str, why: Exception) -> None:
        super().__init__(f"{what} failed: {why}")


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, encoding="utf-8"
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(" ".join(args), e) from e
    return done.stdout


def changed(root: Path, base: str) -> list[str]:
    return _git(root, "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines()


def _at(root: Path, rev: str, path: str) -> str | None:
    """`path` at `rev`, or None where it does not exist."""
    held = _git(root, "ls-tree", "--name-only", rev, "--", path)
    return _git(root, "show", f"{rev}:{path}") if held else None


def python_assertions(source: str) -> dict[str, set[str]]:
    """{test name: its assertions, as the syntax tree reads them}."""
    found: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            held = found.setdefault(node.name, set())
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assert):
                    held.add(ast.unparse(inner.test))
                elif (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr.startswith("assert")
                ):
                    held.add(ast.unparse(inner))
    return found


def js_assertions(source: str) -> dict[str, set[str]]:
    """{test title: its expect statements, spacing aside}. Best effort: a test runs to the next."""
    tests = list(JS_TEST.finditer(source))
    found: dict[str, set[str]] = {}
    for i, test in enumerate(tests):
        end = tests[i + 1].start() if i + 1 < len(tests) else len(source)
        held = found.setdefault(test.group(2), set())
        held.update(
            " ".join(m.group().split()) for m in JS_EXPECT.finditer(source, test.end(), end)
        )
    return found


def _assertions(root: Path, rev: str, names: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name in names:
        source = _at(root, rev, name)
        if source is None:
            continue
        reader = js_assertions if JS_TESTS.match(name) else python_assertions
        try:
            read = reader(source)
        except SyntaxError as e:
            raise ToolError(f"{rev}:{name}", e) from e
        for test, held in read.items():
            found.setdefault(test, set()).update(held)
    return found


def _definitions(root: Path, rev: str, names: list[str]) -> set[str]:
    found: set[str] = set()
    for name in names:
        source = _at(root, rev, name)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ToolError(f"{rev}:{name}", e) from e
        found.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
    return found


def lost_assertions(root: Path, base: str, files: list[str]) -> list[str]:
    tests = [f for f in files if PYTHON_TESTS.match(f) or JS_TESTS.match(f)]
    product = [f for f in files if f.endswith(".py") and not f.startswith("tests/")]
    deleted = _definitions(root, base, product) - _definitions(root, "HEAD", product)
    before = _assertions(root, base, tests)
    after = _assertions(root, "HEAD", tests)
    return [
        f"{test}: assertion lost: {assertion}"
        for test in sorted(before.keys() & after.keys())
        for assertion in sorted(before[test] - after[test])
        if not deleted.intersection(NAME.findall(assertion))
    ]


def added_markers(root: Path, base: str) -> list[str]:
    added: Counter = Counter()
    removed: Counter = Counter()
    path = ""
    for line in _git(root, "diff", "-U0", "--no-renames", f"{base}...HEAD").splitlines():
        if line.startswith("+++ "):
            path = line.removeprefix("+++ b/")
        elif line.startswith("--- "):
            pass
        elif line.startswith("+"):
            added[(path, line[1:].strip())] += 1
        elif line.startswith("-"):
            removed[line[1:].strip()] += 1
    out = []
    for (where, text), count in sorted(added.items()):
        new = count - removed[text]
        if new > 0 and where.endswith(CODE_SUFFIXES) and MARKERS.search(text):
            out.append(f"{where}: skip or deferred-work marker added: {text[:90]}")
    return out


def review_violations(body: str, head_sha: str, files: list[str]) -> list[str]:
    governing = [f for f in files if GOVERNING.match(f)]
    section = REVIEW.search(body)
    if section is None:
        return [f"no ## Review record, and the change touches {governing[0]}"] if governing else []
    commit = COMMIT.search(section.group(1))
    verdict = VERDICT.search(section.group(1))
    out = []
    if commit is None or commit.group(1) != head_sha:
        out.append(f"the ## Review record does not name the head {head_sha}")
    if verdict is None or verdict.group(1) != "PASS":
        out.append("the ## Review record's Verdict is not PASS")
    return out


def violations(root: Path, base: str, body: str, head_sha: str) -> list[str]:
    files = changed(root, base)
    return [
        *lost_assertions(root, base, files),
        *added_markers(root, base),
        *review_violations(body, head_sha, files),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--head-sha", required=True)
    a = ap.parse_args(argv)
    try:
        body = Path(a.body_file).read_text(encoding="utf-8")
        found = violations(Path.cwd(), a.base, body, a.head_sha)
    except (ToolError, OSError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
