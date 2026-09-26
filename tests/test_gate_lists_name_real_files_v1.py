"""Every file a gate lists (an exemption, a scope, a registration) exists. A list entry naming a
deleted file exempts nothing and scopes nothing -- it is fat that reads like coverage. Reads every
.py under tools/ and governance/ from the shared repo_index; a path is a string element of a list,
tuple, set or dict key (or the first item of a tuple element) shaped like a repo file."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_PATH = re.compile(r"^[\w./-]+\.(?:py|js|mjs|bat|ps1|html|css)$")


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return set(out.splitlines())


def _entry(e):
    if isinstance(e, ast.Tuple) and e.elts:
        e = e.elts[0]
    return e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None


def _listed_paths(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            elts = node.elts
        elif isinstance(node, ast.Dict):
            elts = [k for k in node.keys if k is not None]
        else:
            continue
        for e in elts:
            s = _entry(e)
            if s and _PATH.match(s) and ("/" in s or s.endswith(".py")):
                yield e.lineno, s.lstrip("./")


def test_every_file_a_gate_lists_exists(repo_index):
    tracked = _tracked()
    names = {p.rsplit("/", 1)[-1] for p in tracked}
    gates = [(rel.as_posix(), tree) for rel, _text, tree in repo_index.items()
             if rel.parts[0] in ("tools", "governance")]
    assert gates, "no gate files found -- the scan would pass vacuously"
    stale = []
    for rel, tree in gates:
        assert tree is not None, f"{rel} does not parse"
        for line, path in _listed_paths(tree):
            if path in tracked or ("/" not in path and path in names):
                continue
            stale.append(f"{rel}:{line}: {path}")
    assert not stale, "gate lists name files the repo no longer has:\n" + "\n".join(stale)
