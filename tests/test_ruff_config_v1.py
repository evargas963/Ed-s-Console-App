"""The one ruff selection (pyproject.toml), run as the commit hook and the hardening job run it,
refuses every file CPython's compiler refuses, so no separate compile pass is needed, and passes
ordinary code."""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ruff(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--config", str(ROOT / "pyproject.toml"),
                           str(path)], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.parametrize("source", [
    "x = 1 +\n",                                            # a syntax error
    "return 1\n",                                           # return outside a function
    "break\n",                                              # break outside a loop
    "x = (yield)\n",                                        # yield outside a function
    "def f(x, x):\n    pass\n",                             # a repeated argument
    "nonlocal y\n",                                         # nonlocal at module level
    "def f():\n    x = 1\n    global x\n",                  # a name used before its global
    "async def f():\n    pass\ndef g():\n    await f()\n",  # await outside an async function
    "f(**k, *a)\n",                                         # * after **
    "import os\n",                                          # an unused import
    "print(undefined_name)\n",                              # an undefined name
])
def test_the_ruff_selection_refuses_what_the_compiler_or_the_rules_refuse(tmp_path, source):
    path = tmp_path / "case.py"
    path.write_text(source, encoding="utf-8")
    if "import os" not in source and "undefined_name" not in source:
        with pytest.raises(py_compile.PyCompileError):
            py_compile.compile(str(path), doraise=True)
    assert _ruff(path).returncode == 1, source


def test_the_ruff_selection_passes_ordinary_code(tmp_path):
    path = tmp_path / "clean.py"
    path.write_text("import os\n\n\ndef here():\n    return os.getcwd()\n", encoding="utf-8")
    assert _ruff(path).returncode == 0
