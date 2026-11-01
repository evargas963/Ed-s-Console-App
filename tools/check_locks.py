"""The one-way locks: no pull request may raise a count, so the repository only gets simpler.

`.github/workflows/locks.yml` runs this file from the base, on `pull_request_target`, so a change
cannot edit its judge, and reads the change only as data: it runs no code of the head. Every count
is taken on the base and the head under the base's rules. A count at 0 is an absolute ban. A lock
file changes only on the operator's approval in GitHub (the `operator-locks` environment).

    python tools/check_locks.py --base <sha>           from the head's root
    python tools/check_locks.py --changed <sha> <ref>  prints the lock files a change touches
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

RULES = "locks.ruff.toml"
COUNTED_RULES = ".locks-counted.toml"
DATA = (
    ".json", ".md", ".mdc", ".csv", ".txt", ".png", ".ico", ".pdf", ".webmanifest", ".lock",
)  # fmt: skip
PYTHON = (".py", ".pyi", ".pyw", ".ipynb")
LOCK_FILES = (
    RULES, "AGENTS.md", "CLAUDE.md", "pyproject.toml", "requirements-dev.txt", "package.json",
    "package-lock.json", ".pre-commit-config.yaml", ".gitattributes", ".gitignore",
    ".github/", ".claude/", "tools/",
)  # fmt: skip
ROW = re.compile(r"^\| (?!ID \|)(?!-)[^|\n]+ \|", re.M)
ITEM = re.compile(r"^- [A-Z]+-\d+", re.M)
PATCH = re.compile(
    r"monkeypatch|mock\.|\bmock\b|mocker|\bMagicMock\b|\bMock\(|\bpatch\(|\bpatch\.|\bpin_clock\b",
    re.I,
)


def _run(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout


def _names(*args: str, cwd: Path) -> list[str]:
    return [name for name in _run("git", *args, "-z", cwd=cwd).split("\0") if name]


def _part(name: str) -> str:
    if name.startswith("tests/"):
        return "tests"
    return "tools" if name.startswith("tools/") else "product code"


def _ruff(tree: Path, names: list[str]) -> list[dict]:
    """Ruff's findings on exactly `names`, so no ignore file or exclusion hides one."""
    found: list[dict] = []
    for start in range(0, len(names), 200):
        report = _run(
            sys.executable, "-P", "-m", "ruff", "check", *names[start : start + 200],
            "--config", COUNTED_RULES, "--ignore-noqa", "--output-format", "json",
            "--no-cache", "--exit-zero",
            cwd=tree,
        )  # fmt: skip
        found.extend(json.loads(report))
    return found


def counts(tree: Path, rules: str) -> Counter:
    """Return every lock's count in `tree` under `rules`.

    The counts are the lines and bytes of everything that is not data, the open work items, the
    patching lines in tests, and each rule's findings. A banned name counts per product file, so
    removing it from one module buys no use in another.
    """
    found: Counter = Counter()
    names = [n for n in _names("ls-files", cwd=tree) if (tree / n).is_file()]
    for name in names:
        if not name.endswith(DATA):
            text = (tree / name).read_text(encoding="utf-8", errors="replace")
            lines = [line for line in text.splitlines() if line.strip()]
            found[f"lines of {_part(name)}"] += len(lines)
            found[f"bytes of {_part(name)}"] += len(text.encode("utf-8"))
            if name.startswith("tests/"):
                found["patching lines in tests"] += sum(1 for ln in lines if PATCH.search(ln))
    work_list = (tree / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")
    found["open work items"] = len(ROW.findall(work_list)) + len(ITEM.findall(work_list))
    (tree / COUNTED_RULES).write_text(rules, encoding="utf-8")
    try:
        for item in _ruff(tree, [n for n in names if n.endswith(PYTHON)]):
            name = Path(item["filename"]).relative_to(tree.resolve()).as_posix()
            if item["code"] == "TID251":
                where = name if _part(name) == "product code" else _part(name)
                found[f"banned in {where}: {item['message']}"] += 1
            else:
                found[f"ruff {item['code']}"] += 1
    finally:
        (tree / COUNTED_RULES).unlink()
    return found


def rises(base: Counter, head: Counter) -> list[str]:
    """Each count the head raised."""
    return [
        f"{name}: {base[name]} -> {head[name]}" for name in sorted(head) if head[name] > base[name]
    ]


def locked(names: list[str]) -> list[str]:
    """The lock files among `names`."""
    return [n for n in names if n.startswith(LOCK_FILES)]


def judge(root: Path, base_ref: str, approved: bool) -> list[str]:
    """Why the head at `root` is refused against `base_ref`; empty when it passes."""
    rules = _run("git", "show", f"{base_ref}:{RULES}", cwd=root)
    changed = _names("diff", "--name-only", base_ref, "HEAD", cwd=root)
    refused = [] if approved else [f"lock file: {name}" for name in locked(changed)]
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / "base"
        _run("git", "worktree", "add", "--detach", "--quiet", str(tree), base_ref, cwd=root)
        try:
            base = counts(tree, rules)
            head = counts(root, rules)
        finally:
            _run("git", "worktree", "remove", "--force", str(tree), cwd=root)
    for name in sorted(head | base):
        print(f"{name}: {base[name]} -> {head[name]}")
    return refused + rises(base, head)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--changed", nargs=2)
    args = parser.parse_args()
    root = Path.cwd()
    if args.changed:
        print("\n".join(locked(_names("diff", "--name-only", *args.changed, cwd=root))))
        return 0
    refused = judge(root, args.base, os.environ.get("LOCK_FILES_APPROVED") == "true")
    if refused:
        print("REFUSED:", *refused, sep="\n  ")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
