"""HTML — V3 G1 (tree-sitter); vocabulary for attributes (V3-A)."""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_html as tsh
from tree_sitter import Language, Parser, Node

from .js_ts_scanner import scan_js_ts_text
from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms


@lru_cache(maxsize=1)
def _html_parser() -> Parser:
    return Parser(Language(tsh.language()))


def _emit_attr(
    rel: str,
    name: str,
    value: str,
    idx: SchwabCsvIndex,
    syn: dict,
    line: int,
) -> RegisterRow | None:
    vocab = idx.vocabulary
    toks = list(dict.fromkeys(vocab.words_in_line(name) + vocab.words_in_line(value)))
    if not toks:
        return None
    etoks = expand_tokens_with_synonyms(toks, syn)
    blob = f"{name}={value}"[:400]
    return RegisterRow(
        register_id=RegisterRow.make_id(rel, line, 0, "HTML_ATTR_MARKET_TOKEN", "html"),
        language="html",
        path=rel,
        line=line,
        col=0,
        pattern_kind="HTML_ATTR_MARKET_TOKEN",
        surface_form=blob,
        tokens=" ".join(toks),
        csv_candidates=";".join(idx.candidates_token(etoks)),
        csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(blob[:512], k=3)),
        v2_trace="V3 G1 HTML attributes",
        notes="",
    )


def _walk_html(
    node: Node,
    rel: str,
    idx: SchwabCsvIndex,
    syn: dict,
    rows: list[RegisterRow],
) -> None:
    if node.type == "script_element":
        raw = None
        for c in node.named_children:
            if c.type == "raw_text":
                raw = bytes(c.text).decode("utf-8", errors="replace")
                break
        if raw and raw.strip():
            inner = f"{rel}::script"
            js_rows, _ = scan_js_ts_text(inner, raw, idx, syn, "javascript")
            rows.extend(js_rows)
        return

    if node.type == "attribute":
        aname = aval = None
        for c in node.named_children:
            if c.type == "attribute_name":
                aname = bytes(c.text).decode("utf-8", errors="replace")
            elif c.type == "quoted_attribute_value":
                raw = bytes(c.text).decode("utf-8", errors="replace")
                aval = raw.strip().strip('"').strip("'")
            elif c.type == "attribute_value":
                aval = bytes(c.text).decode("utf-8", errors="replace")
        if aname:
            line = node.start_point.row + 1
            row = _emit_attr(rel, aname, aval or "", idx, syn, line)
            if row:
                rows.append(row)

    for child in node.children:
        _walk_html(child, rel, idx, syn, rows)


def scan_html_file(rel: str, text: str, idx: SchwabCsvIndex, syn: dict) -> tuple[list[RegisterRow], bool]:
    try:
        tree = _html_parser().parse(text.encode("utf-8"))
    except Exception:
        return [], False
    if tree.root_node.has_error:
        return [], False
    rows: list[RegisterRow] = []
    _walk_html(tree.root_node, rel, idx, syn, rows)
    return rows, True
