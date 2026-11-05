"""AGENTS.md rule 14: what a change may not take from its tests, and the review it must carry.

Run from the base by `.github/workflows/locks.yml`; the head is read as data, none of its code runs.

Test integrity, every pull request:
   - an assertion of a test that survives is not lost. A test is its function name in Python and
     its title in a Playwright spec, across every changed test file, so a moved test is the same
     test and a rewritten one may restate its assertions; a test gone under its old name is the
     one new test holding more than half of its assertions, the same test renamed. An assertion
     gone with a test that has no such match, or with a function it calls that this change
     deleted, is the review's to judge, as is a test disabled with its assertions kept;
   - no test is another test again: the same code, arguments and decorators, in a file that
     imports the same names (every test file at the head);
   - no line added to code skips a test or leaves a deferred-work marker.

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
from pathlib import Path

CODE_SUFFIXES = (".py", ".js", ".mjs", ".html", ".yml")
PYTHON_TESTS = re.compile(r"^tests/.*\.py$")
JS_TESTS = re.compile(r"^tests/e2e/.*\.spec\.js$")
MARKERS = re.compile(
    r"pytest\.mark\.skip|skipif|\bskip\(|unittest\.skip|importorskip|xfail"
    r"|\b(?:test|describe|it)\.(?:skip|fixme|fail)\b|\bx(?:it|describe)\b|\bTODO\b|\bFIXME\b"
)
GOVERNING = re.compile(
    r"^(AGENTS\.md|CLAUDE\.md|docs/DATA_FLOW\.md|ACTIVE_PROGRAM\.md|locks\.\w+\.toml"
    r"|pyproject\.toml|\.pre-commit-config\.yaml|\.gitattributes"
    r"|requirements-dev\.txt|package-lock\.json"
    r"|\.github/.*|\.claude/.*|\.cursor/.*"
    r"|tools/.*"
    r"|tests/test_(check_\w+|governing_docs|test_rules|hook_chain|\w+_guard\w*)_v\d+\.py)$"
)
CALLED = re.compile(r"(\w+)\(")
JS_TEST = re.compile(r"""\btest(?:\.\w+)?\(\s*(['"`])(.*?)(?<!\\)\1""", re.S)
JS_EXPECT = re.compile(r"\bexpect(?:\.\w+)?\([^;]*;")
REVIEW = re.compile(r"^## Review[ \t]*$(.*?)(?=^## |\Z)", re.M | re.S)
# bold or a trailing word does not take a line out of the record
COMMIT = re.compile(r"^[^\w\n]*Commit[^\w\n]*(.*)$", re.M | re.I)
VERDICT = re.compile(r"^[^\w\n]*Verdict[^\w\n]*(.*)$", re.M | re.I)
EVIDENCE = re.compile(r"^[^\w\n]*Evidence[^\w\n]*\w", re.M | re.I)
#: the head's own attributes and drivers do not decide what the diff shows
DIFF = ("diff", "-U0", "--text", "--no-ext-diff", "--no-textconv")


class ToolError(Exception):
    def __init__(self, what: str, why: Exception) -> None:
        super().__init__(f"{what} failed: {why}")


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args], cwd=root, check=True, capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(" ".join(args), e) from e
    # bytes: text mode would break a line at a bare CR, and --text prints a binary file's bytes
    return done.stdout.decode("utf-8", "replace")


def changed(root: Path, base: str) -> list[str]:
    out = _git(root, "diff", "--name-only", "-z", "--no-renames", f"{base}...HEAD")
    return [name for name in out.split("\0") if name]


def _at(root: Path, rev: str, path: str) -> str | None:
    """`path` at `rev`, or None where it does not exist."""
    held = _git(root, "ls-tree", "--name-only", rev, "--", path)
    return _git(root, "show", f"{rev}:{path}") if held else None


def _test_functions(source: str):
    """Each test function of a Python test file, as its syntax tree reads it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            yield node


def python_assertions(source: str) -> dict[str, set[str]]:
    """{test name: its assertions, as the syntax tree reads them}."""
    found: dict[str, set[str]] = {}
    for node in _test_functions(source):
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


def _assertions(
    root: Path, rev: str, names: list[str], where: dict[str, str] | None = None
) -> dict[str, set[str]]:
    """{test: its assertions} over `names` at `rev`; `where`, when given, gets each test's file."""
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
            if where is not None:
                where[test] = name
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
    """Return each assertion a surviving test lost on net.

    A test is known by what it asserts, not only by its name: a test gone under its old name is
    the one new test that is it renamed, judged like one that kept its name. A test with no such
    match was deleted, the review's to judge. An assertion of a function the change deleted goes
    with it.
    """
    tests = [f for f in files if PYTHON_TESTS.match(f) or JS_TESTS.match(f)]
    product = [f for f in files if f.endswith(".py") and not f.startswith("tests/")]
    deleted = _definitions(root, base, product) - _definitions(root, "HEAD", product)
    was_in: dict[str, str] = {}
    now_in: dict[str, str] = {}
    before = _assertions(root, base, tests, was_in)
    after = _assertions(root, "HEAD", tests, now_in)
    new = sorted(after.keys() - before.keys())
    pairs = [(test, test) for test in sorted(before.keys() & after.keys())]
    for test in sorted(before.keys() - after.keys()):
        # renamed: a new test in its own file sharing an assertion, or one in another file holding
        # more than half of them; one common line (`r.returncode == 0`) elsewhere is not the test
        same = [
            n
            for n in new
            if before[test] & after[n]
            and (now_in[n] == was_in[test] or 2 * len(before[test] & after[n]) > len(before[test]))
        ]
        if len(same) == 1:
            pairs.append((test, same[0]))
    out = []
    for test, now in pairs:
        lost = [
            a
            for a in sorted(before[test] - after[now])
            if not deleted.intersection(CALLED.findall(a))
        ]
        # an assertion corrected or strengthened is one for one; only a net loss is a loss
        if len(lost) > len(after[now] - before[test]):
            out.extend(f"{test}: assertion lost: {a}" for a in lost)
    return out


def added_markers(root: Path, base: str) -> list[str]:
    out = []
    path, in_hunk = "", False
    for line in _git(root, *DIFF, "--no-renames", f"{base}...HEAD").split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@ "):
            in_hunk = True
        elif not in_hunk and line.startswith("+++ "):
            path = line.removeprefix("+++ b/").removesuffix("\t").strip('"')
        elif in_hunk and line.startswith("+") and path.endswith(CODE_SUFFIXES):
            if MARKERS.search(line):
                out.append(f"{path}: skip or deferred-work marker added: {line[1:].strip()[:90]}")
    return out


def review_violations(body: str, head_sha: str, files: list[str]) -> list[str]:
    governing = [f for f in files if GOVERNING.match(f)]
    section = REVIEW.search(re.sub(r"<!--.*?-->", "", body, flags=re.S))
    commits = COMMIT.findall(section.group(1)) if section else []
    verdicts = VERDICT.findall(section.group(1)) if section else []
    if not commits and not verdicts:
        return [f"no ## Review record, and the change touches {governing[0]}"] if governing else []
    out = []
    if {c.strip(" *`") for c in commits} != {head_sha}:
        out.append(f"the ## Review record does not name the head {head_sha}")
    if {v.strip(" *`") for v in verdicts} != {"PASS"}:
        out.append("the ## Review record's Verdict is not PASS")
    if not EVIDENCE.search(section.group(1)):
        out.append("the ## Review record gives no Evidence")
    return out


def duplicate_tests(root: Path) -> list[str]:
    """Return each Python test of the head that is another one again.

    The same code, arguments and decorators once its name and docstring are set aside, in a file
    importing the same names, over every test file.
    """
    seen: dict[str, list[str]] = {}
    for name in _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0"):
        if not PYTHON_TESTS.match(name):
            continue
        source = _git(root, "show", f"HEAD:{name}")
        # the same body tests different code when the names it calls come from elsewhere
        imports = "".join(
            ast.dump(n)
            for n in ast.parse(source).body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        )
        for node in _test_functions(source):
            body = node.body[1:] if ast.get_docstring(node) else node.body
            key = imports + ast.dump(ast.Module(body=body, type_ignores=[]))
            key += "".join(ast.dump(part) for part in (node.args, *node.decorator_list))
            seen.setdefault(key, []).append(f"{name}::{node.name}")
    return [f"a test duplicated: {', '.join(same)}" for same in seen.values() if len(same) > 1]


def violations(root: Path, base: str, body: str, head_sha: str) -> list[str]:
    files = changed(root, base)
    return [
        *lost_assertions(root, base, files),
        *duplicate_tests(root),
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
    except (ToolError, OSError, SyntaxError) as e:  # a test file that does not parse: exit 2
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
