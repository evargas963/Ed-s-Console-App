"""A pytest plugin that records each patch a test run applies, for tools/check_no_new_patches.py.

    ED_PATCH_RECORD=<dir> python -m pytest -p tools.patch_record

Every pytest `MonkeyPatch` change and every unittest.mock patch (`patch` in any form, `patch.dict`,
started, entered or as a decorator; pytest-mock's `mocker` is built on them) is wrapped before the
first conftest.py is imported. Each process writes <dir>/<xdist worker or "main">.jsonl, one Event
per line: each patch APPLIED, the patches still ACTIVE when a test's call starts, and each test
SKIPPED. A patch with no test code on its stack (pytest's own set-up) is not recorded. Without
ED_PATCH_RECORD the plugin records nothing.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest
from _pytest.monkeypatch import MonkeyPatch

APPLIED, ACTIVE, SKIPPED = "applied", "active", "skipped"
APPLY = {MonkeyPatch: ("setattr", "delattr", "setitem", "delitem", "setenv", "delenv", "syspath_prepend", "chdir"),
         mock._patch: ("__enter__",), mock._patch_dict: ("_patch_dict",)}
UNDO = {MonkeyPatch: "undo", mock._patch: "__exit__", mock._patch_dict: "_unpatch_dict"}


@dataclass(frozen=True)
class Event:
    """One line of the record: its kind (APPLIED, ACTIVE or SKIPPED), the test's node id (None
    outside a test) and the test code that applied the patches, as (path, line)."""
    kind: str
    test: str | None
    sites: tuple[tuple[str, int], ...]


def read(where: Path) -> list[Event]:
    """Every Event a run recorded in `where`; FileNotFoundError when no run recorded there."""
    files = sorted(where.glob("*.jsonl")) if where.is_dir() else []
    if not files:
        raise FileNotFoundError(f"no patch record in {where}: run the suite with ED_PATCH_RECORD={where} "
                                "python -m pytest -p tools.patch_record")
    return [Event(d["kind"], d["test"], tuple((p, n) for p, n in d["sites"]))
            for f in files for line in f.read_text(encoding="utf-8").splitlines() if line
            for d in [json.loads(line)]]


_tests: Path | None = None
_out = None
_test: str | None = None
_active: dict[object, list[tuple[str, int]]] = {}


def _sites() -> list[tuple[str, int]]:
    """The test code applying a patch: each frame under tests/, and the test a mock decorator wraps
    (mock's wrapper holds it as `func` or `f`; its own frame is not yet on the stack)."""
    out, frame = [], sys._getframe()
    while frame is not None:
        code, line = frame.f_code, frame.f_lineno
        if code.co_filename == mock.__file__:
            wrapped = frame.f_locals.get("func") or frame.f_locals.get("f")
            if callable(wrapped) and hasattr(inspect.unwrap(wrapped), "__code__"):
                code = inspect.unwrap(wrapped).__code__
                line = code.co_firstlineno
        p = Path(code.co_filename)
        if p.is_relative_to(_tests):
            out.append((p.relative_to(_tests.parent).as_posix(), line))
        frame = frame.f_back
    return out


def _write(kind: str, test: str | None, sites: list[tuple[str, int]]) -> None:
    _out.write(json.dumps({"kind": kind, "test": test, "sites": sites}) + "\n")
    _out.flush()


def _applying(real):
    def wrapper(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        sites = _sites()
        if sites:                       # pytest's own set-up patches its config, not code under test
            _active.setdefault(self, []).extend(sites)
            _write(APPLIED, _test, sites)
        return result
    return wrapper


def _undoing(real):
    def wrapper(self, *args, **kwargs):
        _active.pop(self, None)
        return real(self, *args, **kwargs)
    return wrapper


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config: pytest.Config, parser, args) -> None:
    global _tests, _out
    where = os.environ.get("ED_PATCH_RECORD")
    if not where:
        return
    _tests = Path(early_config.rootpath).resolve() / "tests"
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


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> None:
    """xdist's workers have started with ED_PATCH_RECORD; a pytest a test starts does not inherit it."""
    os.environ.pop("ED_PATCH_RECORD", None)


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
        _write(ACTIVE, item.nodeid, [s for sites in _active.values() for s in sites])


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _out is not None and report.skipped and not hasattr(report, "wasxfail"):
        _write(SKIPPED, report.nodeid, [])
