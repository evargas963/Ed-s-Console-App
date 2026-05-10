"""JS/TS/JSX/TSX AST — V3 G2 (tree-sitter); tokens from CSV vocabulary (V3-A)."""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_typescript as tsm
from tree_sitter import Language, Parser, Node

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms


@lru_cache(maxsize=1)
def _tsx_parser() -> Parser:
    return Parser(Language(tsm.language_tsx()))


def _line_col(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.start_point.column


def _is_static_computed_member_index(index_node: Node | None) -> bool:
    if index_node is None:
        return True
    t = index_node.type
    if t == "string":
        return True
    if t in ("number", "regex"):
        return True
    if t == "template_string":
        for c in index_node.named_children:
            if c.type == "template_substitution":
                return False
        return True
    return False


def _emit(
    rel: str,
    language: str,
    node: Node,
    kind: str,
    idx: SchwabCsvIndex,
    syn: dict,
) -> RegisterRow:
    surface = bytes(node.text).decode("utf-8", errors="replace")[:400]
    toks = idx.vocabulary.words_in_line(surface)
    etoks = expand_tokens_with_synonyms(toks, syn)
    token_key = etoks if etoks else [kind.lower()]
    line, col = _line_col(node)
    return RegisterRow(
        register_id=RegisterRow.make_id(rel, line, col, kind, language),
        language=language,
        path=rel,
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface,
        tokens=" ".join(etoks) if etoks else kind,
        csv_candidates=";".join(idx.candidates_token(token_key)),
        csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(surface[:512], k=3)),
        v2_trace="V3 G2 JS/TS tree-sitter",
        notes="",
    )


def _is_string_keyed_object_literal(node: Node) -> bool:
    if node.type != "object":
        return False
    pairs = [c for c in node.named_children if c.type == "pair"]
    if not pairs:
        return False
    for pr in pairs:
        k = pr.child_by_field_name("key")
        if k is None or k.type not in ("property_identifier", "string", "number"):
            return False
    return True


def _pattern_for_node(node: Node) -> str | None:
    if node.type == "object" and _is_string_keyed_object_literal(node):
        return "REGISTRY_DISPATCH"

    if node.type == "subscript_expression":
        idxn = node.child_by_field_name("index")
        if not _is_static_computed_member_index(idxn):
            return "COMPUTED_PROPERTY"
        return None

    if node.type == "new_expression":
        ctor = node.child_by_field_name("constructor")
        if ctor is None:
            return None
        if ctor.type == "identifier" and bytes(ctor.text) == b"Proxy":
            return "PROXY_TRAP"
        if ctor.type == "identifier" and bytes(ctor.text) == b"Function":
            return "DYNAMIC_EVAL"
        return None

    if node.type == "call_expression":
        fn = node.child_by_field_name("function")
        if fn is None:
            return None
        if fn.type == "import":
            return "DYNAMIC_IMPORT"
        if fn.type == "identifier" and bytes(fn.text) == b"eval":
            return "DYNAMIC_EVAL"
        if fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            prop = fn.child_by_field_name("property")
            if (
                obj
                and prop
                and obj.type == "identifier"
                and bytes(obj.text) == b"Reflect"
                and prop.type == "property_identifier"
            ):
                name = bytes(prop.text).decode("utf-8", errors="replace")
                if name in {"get", "set", "has", "ownKeys"}:
                    return "REFLECT_API"
            if prop and prop.type == "property_identifier":
                n = bytes(prop.text).decode("utf-8", errors="replace")
                if n == "defineProperty":
                    args = node.child_by_field_name("arguments")
                    if args is None:
                        return None
                    parts = list(args.named_children)
                    if len(parts) < 2:
                        return None
                    key_arg = parts[1]
                    if _is_static_computed_member_index(key_arg):
                        return None
                    return "COMPUTED_DEFINE_PROPERTY"
                if n == "defineProperties":
                    return "COMPUTED_DEFINE_PROPERTY"
        return None

    return None


def scan_js_ts_text(
    rel: str,
    text: str,
    idx: SchwabCsvIndex,
    syn: dict,
    language: str,
) -> tuple[list[RegisterRow], bool]:
    parser = _tsx_parser()
    try:
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return [], False
    if tree.root_node.has_error:
        return [], False
    rows: list[RegisterRow] = []
    stack: list[Node] = [tree.root_node]
    while stack:
        node = stack.pop()
        kind = _pattern_for_node(node)
        if kind:
            rows.append(_emit(rel, language, node, kind, idx, syn))
        for child in reversed(node.children):
            stack.append(child)
    return rows, True
