"""AUDIT-CAND-SERVER-PY-FULL-READ — FIND-SERVERPY-1..19 regression guards."""

from __future__ import annotations

import ast
import builtins
import inspect
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "server.py"


def _server_src() -> str:
    return SERVER_PY.read_text(encoding="utf-8", errors="replace")


def _fn_src(name: str) -> str:
    import server

    return inspect.getsource(getattr(server, name))


def _unresolved_free_names_in_module(source: str) -> list[tuple[str, int]]:
    """Load names with no binding in module globals or enclosing function scopes."""
    tree = ast.parse(source)
    builtin_names = {n for n in dir(builtins) if not n.startswith("_")} | {
        "Exception",
        "BaseException",
        "StopIteration",
        "GeneratorExit",
        "__file__",
        "__name__",
        "__doc__",
    }
    typing_names = {
        "Any",
        "Callable",
        "Dict",
        "Iterable",
        "List",
        "Literal",
        "Mapping",
        "Optional",
        "Sequence",
        "Set",
        "Tuple",
        "Union",
    }
    globals_defined: set[str] = set(builtin_names) | typing_names

    def _add_target_names(node: ast.AST, into: set[str]) -> None:
        if isinstance(node, ast.Name):
            into.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                _add_target_names(elt, into)

    def _register_module_stmt(stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Try):
            for child in (*stmt.body, *stmt.orelse, *stmt.finalbody):
                _register_module_stmt(child)
            for handler in stmt.handlers:
                for child in handler.body:
                    _register_module_stmt(child)
            return
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                globals_defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                _add_target_names(tgt, globals_defined)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            globals_defined.add(stmt.target.id)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            globals_defined.add(stmt.name)

    for node in tree.body:
        _register_module_stmt(node)

    class _Scope:
        __slots__ = ("names", "parent", "global_decls")

        def __init__(self, parent: _Scope | None = None) -> None:
            self.parent = parent
            self.names: set[str] = set()
            self.global_decls: set[str] = set()

        def resolve(self, name: str) -> bool:
            if name in self.names or name in self.global_decls:
                return True
            if self.parent is not None:
                return self.parent.resolve(name)
            return name in globals_defined

    def _collect_local_defs(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        local: set[str] = set()
        for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
            local.add(arg.arg)
        if fn.args.vararg:
            local.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            local.add(fn.args.kwarg.arg)
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local.add(node.id)
            elif isinstance(node, ast.arg):
                local.add(node.arg)
            elif isinstance(node, ast.Global):
                local.update(node.names)
            elif isinstance(node, ast.Nonlocal):
                local.update(node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    local.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    _add_target_names(tgt, local)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                local.add(node.target.id)
        return local

    unresolved: list[tuple[str, int]] = []

    def _check_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, parent: _Scope) -> None:
        scope = _Scope(parent)
        scope.names.update(_collect_local_defs(fn))
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if not scope.resolve(node.id):
                    unresolved.append((node.id, node.lineno))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, _Scope())
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_scope = _Scope()
                    method_scope.names.add("self")
                    method_scope.names.update(_collect_local_defs(child))
                    for sub in ast.walk(child):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                            if not method_scope.resolve(sub.id):
                                unresolved.append((sub.id, sub.lineno))

    for node in tree.body:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in globals_defined:
                unresolved.append((node.id, node.lineno))

    return unresolved


# FIND-SERVERPY-1
# FIND-SERVERPY-2


# FIND-SERVERPY-3


# FIND-SERVERPY-4
def test_rth_open_mins_constant_exists_and_used():
    import server

    assert server.RTH_OPEN_MINS == 570
    # (_update_rest_cum_delta, the function this read, is deleted -- REST fallback.) The
    # literal must not reappear anywhere in server.py.
    assert "9 * 60 + 30" not in (ROOT / "server.py").read_text(encoding="utf-8")


# FIND-SERVERPY-5


# FIND-SERVERPY-6


# FIND-SERVERPY-7


# FIND-SERVERPY-8




# FIND-SERVERPY-9


# FIND-SERVERPY-11
def test_r_units_none_default_not_zero_float():
    src = _server_src()
    assert 'getattr(ms, "r_units", 0.0)' not in src
    assert 'getattr(ms, \'r_units\', 0.0)' not in src


# FIND-SERVERPY-12
def test_no_mc_em_pre_bms_warning_log():
    assert "MC_EM_PRE_BMS" not in _server_src()


# FIND-SERVERPY-13


# FIND-SERVERPY-14
def test_no_underscore_json_references():
    src = _server_src()
    assert "_json.loads" not in src
    assert "_json.dumps" not in src


# FIND-SERVERPY-15


# FIND-SERVERPY-17
# FIND-SERVERPY-18
def test_tradeable_score_calls_liquidity_engine_authority():
    src = _fn_src("_liquidity_zone_tradeable_fields")
    assert "liquidity_zone_tradeable_score" in src
    assert "3.0 * len(tags)" not in src


# FIND-SERVERPY-19
# FIND-SERVERPY-20 / cross-cutting
def test_server_module_imports_with_strict_name_resolution():
    src = _server_src()
    tree = ast.parse(src)
    assert isinstance(tree, ast.Module)
    compile(src, str(SERVER_PY), "exec")
    import server  # noqa: F401

    unresolved = _unresolved_free_names_in_module(src)
    assert unresolved == [], f"unresolved free names: {unresolved[:20]}"


def test_liquidity_zone_tradeable_score_authority_roundtrip():
    from liquidity_value_engine import liquidity_zone_tradeable_score

    assert liquidity_zone_tradeable_score(n_tags=1, n_opt=1, inside=False, dist_pen=0.0, spot=None) == 5.5


def test_vwap_failed_log_demoted_to_debug_for_index_symbols():
    """Operator scan flagged: 'WARNING: VWAP failed for $SPX: price_levels=None bars=390 — writing NULL'.

    Schwab index symbols ($SPX, $VIX, $NDX) don't carry intraday volume data;
    VWAP can't compute by definition → steady-state DEBUG, not WARNING. Real
    ticker (SPY etc.) with bars-present + VWAP-failed remains WARNING (data
    quality issue).
    """
    from pathlib import Path

    # RC-371 re-anchor: Phase 2A deleted the second VWAP implementation ALONG WITH its
    # 'VWAP failed for' log site — the WARN-spam this test suppressed cannot recur
    # because the block no longer exists. The lock now holds two things: the deleted
    # log site stays deleted, and the one-VWAP deletion record remains in place.
    src = Path(__file__).resolve().parents[1].joinpath("server.py").read_text(encoding="utf-8")
    assert "VWAP failed for" not in src, (
        "the deleted VWAP-failed log block is back in server.py — a second VWAP "
        "path (and its index-symbol WARN spam) is reopening"
    )
    assert "It was a second, independent VWAP implementation" in src, (
        "the Phase 2A one-VWAP deletion record left server.py — re-derive where the "
        "VWAP authority lives before trusting this lock"
    )
