"""A pytest plugin that records each patch a test run applies, for tools/check_no_new_patches.py.

    ED_PATCH_RECORD=<dir> python -m pytest -p tools.patch_record

Every pytest `MonkeyPatch` change and every unittest.mock patch (`patch` in any form, `patch.dict`,
started, entered or as a decorator; pytest-mock's `mocker` is built on them) is wrapped. Each
process appends to <dir>/<xdist worker or "main">.jsonl one line per patch applied, and one per
test that starts its call with a patch still applied: {"test": the node id, or null outside a
test, "sites": [[path, line], ...]}, the sites being the test code that applied each patch (the
frames under the rootdir's tests/). A patch with no test code on its stack (pytest's own set-up)
is not recorded. Without ED_PATCH_RECORD the plugin records nothing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from _pytest.monkeypatch import MonkeyPatch

APPLY = {MonkeyPatch: ("setattr", "delattr", "setitem", "delitem", "setenv", "delenv", "syspath_prepend", "chdir"),
         mock._patch: ("__enter__",), mock._patch_dict: ("_patch_dict",)}
UNDO = {MonkeyPatch: "undo", mock._patch: "__exit__", mock._patch_dict: "_unpatch_dict"}

_tests: Path | None = None
_out = None
_test: str | None = None
_active: dict[int, list[list]] = {}


def _sites() -> list[list]:
    """The test code applying a patch: each frame under tests/, and the test a mock decorator wraps
    (its own frame is not yet on the stack)."""
    out, frame = [], sys._getframe()
    while frame is not None:
        code, line = frame.f_code, frame.f_lineno
        if code.co_filename == mock.__file__ and code.co_name == "patched" and hasattr(frame.f_locals.get("func"), "__code__"):
            code = frame.f_locals["func"].__code__
            line = code.co_firstlineno
        p = Path(code.co_filename)
        if p.is_relative_to(_tests):
            out.append([p.relative_to(_tests.parent).as_posix(), line])
        frame = frame.f_back
    return out


def _write(sites: list[list]) -> None:
    _out.write(json.dumps({"test": _test, "sites": sites}) + "\n")
    _out.flush()


def _applying(real):
    def wrapper(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        sites = _sites()
        if sites:                       # pytest's own set-up patches its config, not code under test
            _active.setdefault(id(self), []).extend(sites)
            _write(sites)
        return result
    return wrapper


def _undoing(real):
    def wrapper(self, *args, **kwargs):
        _active.pop(id(self), None)
        return real(self, *args, **kwargs)
    return wrapper


def pytest_configure(config: pytest.Config) -> None:
    global _tests, _out
    where = os.environ.get("ED_PATCH_RECORD")
    if not where:
        return
    _tests = Path(config.rootpath).resolve() / "tests"
    where = Path(where)
    where.mkdir(parents=True, exist_ok=True)
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is None:                  # the main process starts before any xdist worker
        for old in where.glob("*.jsonl"):
            old.unlink()
    _out = open(where / f"{worker or 'main'}.jsonl", "w", encoding="utf-8")
    for cls, names in APPLY.items():
        for name in names:
            setattr(cls, name, _applying(getattr(cls, name)))
        setattr(cls, UNDO[cls], _undoing(getattr(cls, UNDO[cls])))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    global _test
    _test = item.nodeid
    try:
        return (yield)
    finally:
        _test = None


def pytest_runtest_call(item: pytest.Item) -> None:
    if _out is not None and _active:
        _write([s for sites in _active.values() for s in sites])
