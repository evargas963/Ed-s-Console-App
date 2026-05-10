"""Python AST scan — V3 G1 + G2; triggers use CSV vocabulary only (V3-A)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms
from .vocabulary import CsvVocabulary, tokenize_for_vocabulary

# Structural filter: Python builtins / core helpers — not market tokens (V3-A).
_PY_CORE_CALLABLES = frozenset(
    {
        "print",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "tuple",
        "set",
        "frozenset",
        "open",
        "range",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "enumerate",
        "zip",
        "map",
        "filter",
        "iter",
        "next",
        "isinstance",
        "issubclass",
        "type",
        "super",
        "object",
        "property",
        "staticmethod",
        "classmethod",
        "hasattr",
        "hash",
        "repr",
        "format",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "callable",
        "id",
        "ord",
        "chr",
        "bin",
        "hex",
        "oct",
        "pow",
        "divmod",
        "sorted",
        "reversed",
        "any",
        "all",
        "slice",
    }
)


def _string_key_hits_vocab(s: str, vocab: CsvVocabulary) -> bool:
    toks = tokenize_for_vocabulary(s, min_len=vocab.min_len)
    return bool(toks & set(vocab.tokens))


def _name_hits_vocab(name: str, vocab: CsvVocabulary) -> bool:
    toks = tokenize_for_vocabulary(name, min_len=vocab.min_len)
    return bool(toks & set(vocab.tokens))


@dataclass
class _PyCtx:
    rel_path: str
    rows: list[RegisterRow]
    idx: SchwabCsvIndex
    syn: dict

    @property
    def vocab(self) -> CsvVocabulary:
        return self.idx.vocabulary


def _toks(*parts: str) -> list[str]:
    return [p for p in parts if p]


def _emit(ctx: _PyCtx, node: ast.AST, kind: str, surface: str, tokens: list[str], trace: str) -> None:
    line = getattr(node, "lineno", 0) or 0
    col = getattr(node, "col_offset", 0) or 0
    etoks = expand_tokens_with_synonyms(tokens, ctx.syn)
    cands = ";".join(ctx.idx.candidates_token(etoks))
    lex = ctx.idx.candidates_embedding_topk(" ".join(tokens), k=3)
    lex_note = ";".join(lex) if lex else ""
    rid = RegisterRow.make_id(ctx.rel_path, line, col, kind, "python")
    ctx.rows.append(
        RegisterRow(
            register_id=rid,
            language="python",
            path=ctx.rel_path,
            line=line,
            col=col,
            pattern_kind=kind,
            surface_form=surface[:400],
            tokens=" ".join(tokens),
            csv_candidates=cands,
            csv_lexical_topk_note=lex_note,
            v2_trace=trace,
            notes="",
        )
    )


def _collect_idents(node: ast.AST, out: set[str]) -> None:
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, ast.Attribute):
        out.add(node.attr)
        _collect_idents(node.value, out)
    elif isinstance(node, ast.BinOp):
        _collect_idents(node.left, out)
        _collect_idents(node.right, out)
    elif isinstance(node, ast.UnaryOp):
        _collect_idents(node.operand, out)
    elif isinstance(node, ast.Call):
        _collect_idents(node.func, out)
        for a in node.args:
            _collect_idents(a, out)
        for kw in node.keywords:
            if kw.value:
                _collect_idents(kw.value, out)


def _is_zeroish(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value in (0, 0.0, None):
        return True
    return False


def _str_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class UniversalPythonVisitor(ast.NodeVisitor):
    def __init__(self, ctx: _PyCtx) -> None:
        self.ctx = ctx

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        key = None
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            key = node.slice.value
        if key and _string_key_hits_vocab(key, self.ctx.vocab):
            _emit(
                self.ctx,
                node,
                "SUBSCRIPT_MARKET_KEY",
                f'subscript[... "{key}"]',
                _toks(key),
                "V3 G1 Python",
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if self.ctx.vocab.contains_word(node.attr):
            _emit(
                self.ctx,
                node,
                "ATTRIBUTE_MARKET",
                f"attr .{node.attr}",
                _toks(node.attr),
                "V3 G1 Python",
            )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> Any:
        for k in node.keys:
            if k is None:
                continue
            sk = _str_key(k)
            if sk and _string_key_hits_vocab(sk, self.ctx.vocab):
                _emit(
                    self.ctx,
                    k,
                    "DICT_LITERAL_MARKET_KEY",
                    f"dict key {sk!r}",
                    _toks(sk),
                    "V3 G1 Python",
                )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        idents: set[str] = set()
        _collect_idents(node, idents)
        hit = self.ctx.vocab.id_intersects_vocab(idents)
        if hit:
            _emit(
                self.ctx,
                node,
                "BINOP_MARKET_IDENT",
                "BinOp with CSV-vocabulary identifiers",
                sorted(hit),
                "V3 G1 Python",
            )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.Or) and len(node.values) >= 2:
            for fb in node.values[1:]:
                if _is_zeroish(fb):
                    left = node.values[0]
                    idents: set[str] = set()
                    _collect_idents(left, idents)
                    hit = self.ctx.vocab.id_intersects_vocab(idents)
                    if hit:
                        _emit(
                            self.ctx,
                            node,
                            "BOOL_OR_DEFAULT_ZERO",
                            "`a or 0`-style with vocabulary idents",
                            sorted(hit),
                            "V3 G1 Python",
                        )
                    break
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        if _is_zeroish(node.orelse):
            idents: set[str] = set()
            _collect_idents(node.body, idents)
            _collect_idents(node.test, idents)
            hit = self.ctx.vocab.id_intersects_vocab(idents)
            if hit:
                _emit(
                    self.ctx,
                    node,
                    "IFEXP_ZERO_DEFAULT",
                    "conditional with zeroish else",
                    sorted(hit),
                    "V3 G1 Python",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        v = self.ctx.vocab
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            sk = _str_key(node.args[0])
            if sk and _string_key_hits_vocab(sk, v) and len(node.args) >= 2:
                _emit(
                    self.ctx,
                    node,
                    "DICT_GET_MARKET_DEFAULT",
                    f".get({sk!r}, default)",
                    _toks(sk, "get"),
                    "V3 G1 Python",
                )
        if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
            an = _str_key(node.args[1])
            if an and _string_key_hits_vocab(an, v):
                _emit(
                    self.ctx,
                    node,
                    "GETATTR_MARKET_LITERAL",
                    f'getattr(..., "{an}", ...)',
                    _toks(an, "getattr"),
                    "V3 G1 Python",
                )

        if isinstance(node.func, ast.Name) and node.func.id in {"float", "int"} and node.args:

            def _coerce_default_pattern(n: ast.AST) -> bool:
                if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
                    return any(_is_zeroish(x) for x in n.values[1:])
                if isinstance(n, ast.IfExp) and _is_zeroish(n.orelse):
                    return True
                return False

            if _coerce_default_pattern(node.args[0]):
                _emit(
                    self.ctx,
                    node,
                    "COERCE_OR_ZERO",
                    f"{node.func.id}(...) with inner default pattern",
                    _toks(node.func.id),
                    "V3 G1 Python",
                )

        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "time":
                if node.func.attr in {"time", "monotonic"}:
                    _emit(
                        self.ctx,
                        node,
                        "TIME_MONOTONIC" if node.func.attr == "monotonic" else "TIME_TIME",
                        f"time.{node.func.attr}()",
                        _toks("time", node.func.attr),
                        "V3 G1 time",
                    )
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "datetime":
                if node.func.attr == "now":
                    _emit(
                        self.ctx,
                        node,
                        "DATETIME_NOW",
                        "datetime.now()",
                        _toks("datetime", "now"),
                        "V3 G1 time",
                    )

        if (
            isinstance(node.func, ast.Name)
            and node.func.id not in _PY_CORE_CALLABLES
            and v.contains_word(node.func.id)
        ):
            _emit(
                self.ctx,
                node,
                "CALL_NAMED_DERIVATION",
                f"call {node.func.id}",
                _toks(node.func.id),
                "V3 G1 call name in CSV vocabulary",
            )

        if isinstance(node.func, ast.Name) and node.func.id == "eval":
            _emit(self.ctx, node, "DYNAMIC_EVAL", "eval(...)", _toks("eval"), "V3 G2 Python")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        for dec in node.decorator_list:
            surf = "decorator"
            if hasattr(ast, "unparse"):
                try:
                    surf = ast.unparse(dec)[:80]
                except Exception:
                    surf = "decorator"
            _emit(
                self.ctx,
                dec,
                "DECORATOR_SITE",
                f"decorator on {node.name}",
                _toks(surf),
                "V3 G2 decorator sweep",
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        for dec in node.decorator_list:
            _emit(
                self.ctx,
                dec,
                "DECORATOR_SITE",
                f"decorator on async {node.name}",
                _toks("async", "decorator"),
                "V3 G2 decorator sweep",
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        for dec in node.decorator_list:
            _emit(
                self.ctx,
                dec,
                "DECORATOR_SITE",
                f"decorator on class {node.name}",
                _toks("class"),
                "V3 G2 decorator sweep",
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        if isinstance(node.value, ast.Dict) and node.value.keys:
            all_str = True
            keys: list[str] = []
            for k in node.value.keys:
                if k is None:
                    all_str = False
                    break
                sk = _str_key(k)
                if not sk:
                    all_str = False
                    break
                keys.append(sk)
            if all_str and keys:
                _emit(
                    self.ctx,
                    node.value,
                    "REGISTRY_DISPATCH",
                    f"string-keyed dict len={len(keys)}",
                    keys[:15],
                    "V3 G2 registry sweep",
                )
        for t in node.targets:
            if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, (int, float)) and not isinstance(node.value.value, bool):
                    if _name_hits_vocab(t.id, self.ctx.vocab):
                        _emit(
                            self.ctx,
                            node,
                            "MAGIC_NUMERIC_DEFAULT",
                            f"{t.id} = {node.value.value!r}",
                            _toks(t.id),
                            "V3 G1 imputation (name intersects CSV vocabulary)",
                        )
        self.generic_visit(node)


def scan_python_source(
    rel_path: str,
    source: str,
    idx: SchwabCsvIndex,
    syn: dict,
) -> list[RegisterRow]:
    rows: list[RegisterRow] = []
    ctx = _PyCtx(rel_path, rows, idx, syn)
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return rows
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr"}:
                _emit(
                    ctx,
                    node,
                    "PYTHON_GETATTR_SETATTR",
                    f"{node.func.id}(...)",
                    _toks(node.func.id),
                    "V3 G2 dynamic dispatch",
                )
    v = UniversalPythonVisitor(ctx)
    v.visit(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"__getattr__", "__setattr__"}:
            _emit(ctx, node, "DYNAMIC_DISPATCH", f"def {node.name}", _toks(node.name), "V3 G2 dynamic dispatch")
    return rows


def scan_python_complete(
    rel_path: str,
    source: str,
    idx: SchwabCsvIndex,
    syn: dict,
) -> tuple[list[RegisterRow], bool]:
    """Parse + AST + cross-validator; returns ([], False) on syntax error."""
    try:
        ast.parse(source)
    except SyntaxError:
        return [], False
    from .cross_validate import cross_validate_python_file

    rows = scan_python_source(rel_path, source, idx, syn)
    rows.extend(cross_validate_python_file(rel_path, source, rows, idx))
    return rows, True
