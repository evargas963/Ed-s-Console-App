"""The one-way locks: no pull request may raise a count, but for those in FREE, which are reported.

`.github/workflows/locks.yml` runs this file from the base, on `pull_request_target`, so a change
cannot edit its judge, and reads the change only as data: it runs no code of the head. Every count
is taken on the base and the head under the base's rules. A count at 0 is an absolute ban. A change
this refuses cannot merge: `locks` is a required check, and nothing approves past it.

    python tools/check_locks.py --base <sha>      from the head's root; exit 3 is refused
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
REFUSED = 3
#: the counts that may rise above 0, reported and never judged: size and work items (operator
#: 2026-11-04: "i am not going to set some arbitrary number")
FREE = ("bytes of", "lines of", "open work items")
DATA = (".json", ".md", ".mdc", ".csv", ".txt", ".png", ".ico", ".pdf", ".webmanifest", ".lock")
PYTHON = (".py", ".pyi", ".pyw", ".ipynb")
#: what Python can load, by any case of its suffix on Windows
LOADABLE = (*PYTHON, ".pyc", ".pyd", ".so")
ROW = re.compile(r"^\|(?!\s*(?:ID|#)\s*\|)(?!\s*:?-)", re.M)
ITEM = re.compile(r"^- [A-Z]+-\d+", re.M)
PATCH = re.compile(
    r"monkeypatch|mock\.|\bmock\b|mocker|\bMagicMock\b|\bMock\(|\bpatch\(|\bpatch\.|\bpin_clock\b",
    re.I,
)
FORMAT_OFF = re.compile(r"#\s*(?:ruff:\s*)?(?:fmt|yapf|isort):\s*(?:off|skip|disable)")


def _run(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout


def _names(*args: str, cwd: Path) -> list[str]:
    return [name for name in _run("git", *args, "-z", cwd=cwd).split("\0") if name]


def _part(name: str) -> str:
    if name.lower().startswith("tests/"):
        return "tests"
    return "tools" if name.lower().startswith("tools/") else "product code"


def _outside_the_contracts(tree: Path, name: str) -> bool:
    """Return whether `name`, a file Python can load, is not one import-linter is sure to read.

    import-linter is sure to read a `.py` named as a module, in folders that are packages. grimp
    also reads a folder with no `__init__.py` at the top, until a root `__init__.py` stops it, so
    this is the stricter rule.
    """
    parts = name.removesuffix(".py").split("/")
    return not (
        name.endswith(".py")
        and all(part.isidentifier() for part in parts)
        and all((tree / Path(*parts[:i]) / "__init__.py").is_file() for i in range(1, len(parts)))
    )


def _ruff(tree: Path, names: list[str]) -> list[dict]:
    """Ruff's findings on exactly `names`, so no ignore file or exclusion hides one."""
    found: list[dict] = []
    for start in range(0, len(names), 200):
        report = _run(
            sys.executable,
            "-P",
            "-m",
            "ruff",
            "check",
            "--config",
            COUNTED_RULES,
            "--ignore-noqa",
            "--output-format",
            "json",
            "--no-cache",
            "--exit-zero",
            "--",
            *names[start : start + 200],
            cwd=tree,
        )
        found.extend(json.loads(report))
    return found


def counts(tree: Path, rules: str) -> Counter:
    """Return every lock's count in `tree` under `rules`.

    The counts are the lines and bytes of everything that is not data, the open work items, the
    patching lines in tests, the format suppressions, the files Python can load that the import
    contracts may not read, and each rule's findings. A banned name counts per product file, so
    removing it from one module buys no use in another.
    """
    found: Counter = Counter()
    names = [n for n in _names("ls-files", cwd=tree) if (tree / n).is_file()]
    for name in names:
        if name.lower().endswith(LOADABLE) and _outside_the_contracts(tree, name):
            found["files outside the import contracts"] += 1
        if not name.endswith(DATA):
            text = (tree / name).read_text(encoding="utf-8", errors="replace")
            lines = [line for line in text.splitlines() if line.strip()]
            found[f"lines of {_part(name)}"] += len(lines)
            found[f"bytes of {_part(name)}"] += len(text.encode("utf-8"))
            found["format suppressions"] += sum(1 for ln in lines if FORMAT_OFF.search(ln))
            if _part(name) == "tests":
                found["patching lines in tests"] += sum(1 for ln in lines if PATCH.search(ln))
    work_list = (tree / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")
    found["open work items"] = len(ROW.findall(work_list)) + len(ITEM.findall(work_list))
    (tree / COUNTED_RULES).write_text(rules, encoding="utf-8")
    try:
        for item in _ruff(tree, [n for n in names if n.endswith(PYTHON)]):
            name = Path(item["filename"]).resolve().relative_to(tree.resolve()).as_posix()
            if item["code"] == "TID251":
                where = name if _part(name) == "product code" else _part(name)
                found[f"banned in {where}: {item['message']}"] += 1
            else:
                found[f"ruff {item['code']}"] += 1
    finally:
        (tree / COUNTED_RULES).unlink()
    return found


def rises(base: Counter, head: Counter) -> list[str]:
    """Each count the head raised that may not rise."""
    return [
        f"{name}: {base[name]} -> {head[name]}"
        for name in sorted(head)
        if head[name] > base[name] and not (base[name] and name.startswith(FREE))
    ]


def judge(root: Path, base_ref: str) -> list[str]:
    """Why the head at `root` is refused against `base_ref`; empty when it passes."""
    rules = _run("git", "show", f"{base_ref}:{RULES}", cwd=root)
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch).resolve() / "base"
        _run("git", "worktree", "add", "--detach", "--quiet", str(tree), base_ref, cwd=root)
        try:
            base = counts(tree, rules)
            head = counts(root, rules)
        finally:
            _run("git", "worktree", "remove", "--force", str(tree), cwd=root)
    for name in sorted(head | base):
        print(f"{name}: {base[name]} -> {head[name]}")
    return rises(base, head)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    refused = judge(Path.cwd(), parser.parse_args().base)
    if refused:
        print("REFUSED:", *refused, sep="\n  ")
        return REFUSED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
