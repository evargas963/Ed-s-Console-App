"""A pytest plugin that records each patch a test run applies, for tools/check_no_new_patches.py.

    ED_PATCH_RECORD=<dir> python -m pytest -p tools.patch_record

Every pytest `MonkeyPatch` change and every unittest.mock patch (`patch` in any form, `patch.dict`,
started, entered or as a decorator; pytest-mock's `mocker` is built on them) is wrapped before the
first conftest.py is imported. Each process writes <dir>/<xdist worker or "main">.jsonl, one Event
per line: each test pytest COLLECTED (before any deselection), each patch APPLIED, and each test that RAN (pytest reported its call
other than as skipped) with the patches still applied that reach it: one applied while modules were imported, by a fixture the test requests, or
from its own file or a conftest.py above it. A patch with no test code on its stack (pytest's own
set-up) is not recorded. Without ED_PATCH_RECORD the plugin records nothing.
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

APPLIED, RAN, COLLECTED = "applied", "ran", "collected"
APPLY = {MonkeyPatch: ("setattr", "delattr", "setitem", "delitem", "setenv", "delenv", "syspath_prepend", "chdir"),
         mock._patch: ("__enter__",), mock._patch_dict: ("_patch_dict",)}
UNDO = {MonkeyPatch: "undo", mock._patch: "__exit__", mock._patch_dict: "_unpatch_dict"}


@dataclass(frozen=True)
class Event:
    """One line of the record: its kind (APPLIED, RAN or COLLECTED), the test's identities (see
    `_unit`; None outside a test) and the test code that applied the patches, as (path, line)."""
    kind: str
    test: tuple[tuple[str, str | int], ...] | None
    sites: tuple[tuple[str, int], ...]


def read(where: Path) -> list[Event]:
    """Every Event a run recorded in `where`; FileNotFoundError when no run recorded there."""
    files = sorted(where.glob("*.jsonl")) if where.is_dir() else []
    if not files:
        raise FileNotFoundError(f"no patch record in {where}: run the suite with ED_PATCH_RECORD={where} "
                                "python -m pytest -p tools.patch_record")
    return [Event(d["kind"], tuple((p, at) for p, at in d["test"]) if d["test"] else None,
                  tuple((p, n) for p, n in d["sites"]))
            for f in files for line in f.read_text(encoding="utf-8").splitlines() if line
            for d in [json.loads(line)]]


@dataclass
class _Applied:
    """A patch still applied: the test running when it was applied (None while modules were
    imported), the fixture being set up then (None outside one), and the test code that applied it."""
    test: tuple[tuple[str, str | int], ...] | None
    fixture: str | None
    sites: list[tuple[str, int]]


_tests: Path | None = None
_out = None
_test: tuple[tuple[str, str | int], ...] | None = None
_fixtures: list[str] = []
_active: dict[object, _Applied] = {}
_calls: dict[str, tuple[tuple[tuple[str, str | int], ...], list[tuple[str, int]]]] = {}


def _unit(item: pytest.Item) -> tuple[tuple[str, str | int], ...]:
    """A test item's two identities: (its file, the name pytest collected it under, Class.name),
    and (the file, the line) where the code it runs starts, when under tests/ (an inherited test's
    base, a test made inside another function, a test under a decorator that does not wrap)."""
    path, _, name = item.nodeid.partition("::")
    out: list[tuple[str, str | int]] = [(path, name.split("[")[0].replace("::", "."))]
    obj = getattr(item, "obj", None)
    code = getattr(inspect.unwrap(getattr(obj, "__func__", obj)), "__code__", None) if callable(obj) else None
    if code is not None and Path(code.co_filename).is_relative_to(_tests):
        out.append((Path(code.co_filename).relative_to(_tests.parent).as_posix(), code.co_firstlineno))
    return tuple(out)


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


def _write(kind: str, test: tuple[tuple[str, str | int], ...] | None, sites: list[tuple[str, int]]) -> None:
    _out.write(json.dumps({"kind": kind, "test": test, "sites": sites}) + "\n")
    _out.flush()


def _applying(real):
    def wrapper(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        sites = _sites()
        if sites:                       # pytest's own set-up patches its config, not code under test
            _active.setdefault(self, _Applied(_test, _fixtures[-1] if _fixtures else None, [])).sites.extend(sites)
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
    _test = _unit(item) if _out is not None else None
    try:
        return (yield)
    finally:
        _test = None


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef, request):
    _fixtures.append(fixturedef.argname)
    try:
        return (yield)
    finally:
        _fixtures.pop()


def _reaches(applied: _Applied, item: pytest.Item) -> bool:
    """Whether a patch still applied reaches `item`: applied while modules were imported, by a
    fixture it requests (pytest's own closure, autouse included), or from its file or a conftest.py
    above it. A patch another file's test left applied reaches it only by the order its worker runs
    files in, and is judged where it was applied."""
    path = item.nodeid.split("::")[0]
    return applied.test is None or applied.fixture in item.fixturenames or any(
        site == path or (site.rsplit("/", 1)[-1] == "conftest.py" and path.startswith(site[:-len("conftest.py")]))
        for site, _ in applied.sites)


def pytest_itemcollected(item: pytest.Item) -> None:
    if _out is not None:
        _write(COLLECTED, _unit(item), [])


def pytest_runtest_call(item: pytest.Item) -> None:
    if _out is not None:
        _calls[item.nodeid] = (_unit(item), [s for a in _active.values() if _reaches(a, item) for s in a.sites])


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """A test RAN when pytest reports its call other than as skipped (a skip in any form, or an
    xfail, stops it partway), with the patches that reached it when the call began."""
    if report.when == "call" and report.nodeid in _calls:
        unit, sites = _calls.pop(report.nodeid)
        if not report.skipped:
            _write(RAN, unit, sites)
