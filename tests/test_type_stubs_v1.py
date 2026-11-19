"""The type stubs (typings/) state what schwab-py and authlib export, and their enums, as installed.

stubtest (hardening) checks each function, class and attribute the stubs state against the
installed libraries, but not a name a stub re-exports (`from .base import BaseClient as
BaseClient`: stubtest skips the stub's imported names), nor an enum member of a class nested in a
class (its check of a stated attribute missing at runtime stops at module.Class.attribute:
mypy/stubtest.py verify_var), nor any member's value (it compares the value's type). Schwab's
stream field numbers are such members (StreamClient.LevelOneOptionFields.GAMMA = 29). Checked:
every name a stub states at its top is in the installed module, and every enum class a stub
states has the installed class's members, each name with its value, aliases included.
"""

import ast
import enum
import sys
from pathlib import Path
from typing import Any

import feed.schwab_client
import feed.stream

TYPINGS = Path(__file__).resolve().parent.parent / "typings"
#: Feed's modules that load schwab-py and authlib, as the daemon does
FEED = (feed.schwab_client, feed.stream)


def _enums(body: list[ast.stmt], path: list[str]) -> list[tuple[list[str], dict[str, Any]]]:
    """Each class in `body` that states members (NAME = value), by its path, with them."""
    found: list[tuple[list[str], dict[str, Any]]] = []
    for node in body:
        if isinstance(node, ast.ClassDef):
            members = {
                t.id: ast.literal_eval(s.value)
                for s in node.body
                if isinstance(s, ast.Assign)
                for t in s.targets
                if isinstance(t, ast.Name)
            }
            if members:
                found.append(([*path, node.name], members))
            found.extend(_enums(node.body, [*path, node.name]))
    return found


def _stated(body: list[ast.stmt]) -> set[str]:
    """The names a stub states at its top: its classes, functions, variables and re-exports.

    A class marked @type_check_only exists for the type checker alone, as its name says.
    """
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            marks = [d.id for d in node.decorator_list if isinstance(d, ast.Name)]
            if "type_check_only" not in marks:
                names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update(a.asname for a in node.names if a.asname == a.name.rpartition(".")[2])
    return names


def _stubs() -> list[tuple[Path, Any, ast.Module]]:
    """Each stub, the installed module it states as Feed loaded it, and its parsed text."""
    found: list[tuple[Path, Any, ast.Module]] = []
    for stub in sorted(TYPINGS.rglob("*.pyi")):
        parts = stub.relative_to(TYPINGS).with_suffix("").parts
        name = ".".join(p for p in parts if p != "__init__")
        assert name in sys.modules, f"{name}: a stub of a module Feed does not load"
        found.append((stub, sys.modules[name], ast.parse(stub.read_text(encoding="utf-8"))))
    return found


def test_every_name_a_stub_states_is_in_the_installed_module():
    for stub, module, tree in _stubs():
        missing = sorted(n for n in _stated(tree.body) if not hasattr(module, n))
        assert missing == [], (stub.relative_to(TYPINGS).as_posix(), missing)


def test_every_enum_a_stub_states_is_the_installed_librarys():
    compared: list[str] = []
    for stub, module, tree in _stubs():
        for path, members in _enums(tree.body, []):
            cls: Any = module
            for name in path:
                cls = getattr(cls, name)
            assert issubclass(cls, enum.Enum), path
            installed = {name: member.value for name, member in cls.__members__.items()}
            assert members == installed, (stub.name, path)
            compared.append(".".join(path))
    assert "StreamClient.LevelOneOptionFields" in compared
    assert "BaseClient.MarketHours.Market" in compared
