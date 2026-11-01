"""The one-way locks: no pull request may raise a count, so the repository only gets simpler.

Each count is taken on the base and on the head under one set of rules, the base's when it has
them, so a change cannot weaken what judges it. A count at 0 is an absolute ban. No number is kept
by hand and nothing is exempt.

CI runs the base's copy of this file, from the repository root, so a change cannot edit its judge.

    python tools/check_locks.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

RULES = "locks.ruff.toml"
COUNTED_RULES = ".locks-counted.toml"
CODE = (".py", ".js", ".mjs", ".html", ".css", ".bat", ".ps1", ".sh")
SKIP = ("tests/fixtures/", "static/vendor/", "research/")
OPEN_ROW = re.compile(
    r"^\| [A-Z][A-Z0-9-]* \| (?:NEXT|QUEUED|IN PROGRESS|ACTIVE|OPERATOR|BLOCKED) \|", re.M
)
PATCH = re.compile(r"\bmonkeypatch\b|\bmock\.patch\b|\bpin_clock\b|\bunittest\.mock\b")


def _run(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout


def _part(name: str) -> str:
    if name.startswith("tests/"):
        return "lines of tests"
    if name.startswith("tools/"):
        return "lines of check tools"
    return "lines of product code"


def counts(tree: Path, rules: str) -> Counter:
    """Return every lock's count in `tree` under `rules`.

    The counts are its lines of code, tests and tools, its open work rows, its patching lines in
    tests, its fields with a second reader and each rule's findings.
    """
    found: Counter = Counter()
    for name in _run("git", "ls-files", cwd=tree).splitlines():
        if name.endswith(CODE) and not name.startswith(SKIP):
            text = (tree / name).read_text(encoding="utf-8", errors="replace")
            found[_part(name)] += sum(1 for line in text.splitlines() if line.strip())
            if name.startswith("tests/"):
                found["patching lines in tests"] += len(PATCH.findall(text))
    work_list = (tree / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")
    found["open work rows"] = len(OPEN_ROW.findall(work_list))
    listed = _run(sys.executable, "-m", "tools.check_one_reader", "--list", cwd=tree)
    found["fields with a second reader"] = sum(1 for line in listed.splitlines() if line.strip())
    (tree / COUNTED_RULES).write_text(rules, encoding="utf-8")
    try:
        ruff = _run(
            sys.executable, "-m", "ruff", "check", ".", "--config", COUNTED_RULES,
            "--ignore-noqa", "--output-format", "json", "--no-cache", "--exit-zero",
            cwd=tree,
        )  # fmt: skip
    finally:
        (tree / COUNTED_RULES).unlink()
    found.update(f"ruff {item['code']}" for item in json.loads(ruff))
    return found


def rises(base: Counter, head: Counter) -> list[str]:
    """Each count the head raised."""
    return [
        f"{name}: {base[name]} -> {head[name]}" for name in sorted(head) if head[name] > base[name]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    base_ref = parser.parse_args().base
    root = Path.cwd()
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / "base"
        _run("git", "worktree", "add", "--detach", "--quiet", str(tree), base_ref, cwd=root)
        try:
            held = tree / RULES
            rules = (held if held.is_file() else root / RULES).read_text(encoding="utf-8")
            base = counts(tree, rules)
            head = counts(root, rules)
        finally:
            _run("git", "worktree", "remove", "--force", str(tree), cwd=root)
    for name in sorted(head | base):
        print(f"{name}: {base[name]} -> {head[name]}")
    refused = rises(base, head)
    if refused:
        print("REFUSED, a lock may only fall:", *refused, sep="\n  ")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
