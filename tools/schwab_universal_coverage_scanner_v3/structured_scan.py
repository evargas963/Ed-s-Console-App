"""JSON / YAML / TOML / INI — V3 G1; vocabulary-driven (V3-A)."""

from __future__ import annotations

import configparser
import json
import tomllib
from pathlib import Path
from typing import Any

import yaml

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms
from .vocabulary import CsvVocabulary, tokenize_for_vocabulary


def _key_string_hits_vocab(ks: str, vocab: CsvVocabulary) -> list[str]:
    toks = tokenize_for_vocabulary(ks, min_len=vocab.min_len)
    return sorted(toks & set(vocab.tokens))


def _emit(
    rel: str,
    lang: str,
    line: int,
    col: int,
    kind: str,
    surface: str,
    tokens: list[str],
    idx: SchwabCsvIndex,
    syn: dict,
    trace: str,
) -> RegisterRow:
    etoks = expand_tokens_with_synonyms(tokens, syn)
    return RegisterRow(
        register_id=RegisterRow.make_id(rel, line, col, kind, lang),
        language=lang,
        path=rel,
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface[:400],
        tokens=" ".join(tokens),
        csv_candidates=";".join(idx.candidates_token(etoks)),
        csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(" ".join(tokens), k=3)),
        v2_trace=trace,
    )


def walk_tree(
    rel: str,
    lang: str,
    obj: Any,
    idx: SchwabCsvIndex,
    syn: dict,
    rows: list[RegisterRow],
    *,
    key_kind: str,
    str_kind: str,
    trace: str,
    line_hint: int = 1,
) -> None:
    vocab = idx.vocabulary
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            kh = _key_string_hits_vocab(ks, vocab)
            if kh:
                rows.append(
                    _emit(
                        rel,
                        lang,
                        line_hint,
                        0,
                        key_kind,
                        ks,
                        kh,
                        idx,
                        syn,
                        trace,
                    )
                )
            walk_tree(rel, lang, v, idx, syn, rows, key_kind=key_kind, str_kind=str_kind, trace=trace, line_hint=line_hint)
    elif isinstance(obj, list):
        for item in obj:
            walk_tree(rel, lang, item, idx, syn, rows, key_kind=key_kind, str_kind=str_kind, trace=trace, line_hint=line_hint)
    elif isinstance(obj, str):
        hits = vocab.words_in_line(obj)
        if hits:
            rows.append(
                _emit(
                    rel,
                    lang,
                    line_hint,
                    0,
                    str_kind,
                    obj[:200],
                    hits,
                    idx,
                    syn,
                    trace,
                )
            )


def scan_json_file(rel: str, path: Path, idx: SchwabCsvIndex, syn: dict) -> tuple[list[RegisterRow], bool]:
    rows: list[RegisterRow] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return rows, False
    walk_tree(
        rel,
        "json",
        data,
        idx,
        syn,
        rows,
        key_kind="JSON_KEY_MARKET_TOKEN",
        str_kind="JSON_STRING_MARKET_TOKEN",
        trace="V3 G1 JSON walk",
    )
    return rows, True


def scan_yaml_file(rel: str, path: Path, idx: SchwabCsvIndex, syn: dict) -> tuple[list[RegisterRow], bool]:
    rows: list[RegisterRow] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return rows, False
    if data is None:
        return rows, True
    walk_tree(
        rel,
        "yaml",
        data,
        idx,
        syn,
        rows,
        key_kind="YAML_KEY_MARKET_TOKEN",
        str_kind="YAML_STRING_MARKET_TOKEN",
        trace="V3 G1 YAML walk",
    )
    return rows, True


def scan_toml_file(rel: str, path: Path, idx: SchwabCsvIndex, syn: dict) -> tuple[list[RegisterRow], bool]:
    rows: list[RegisterRow] = []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return rows, False
    walk_tree(
        rel,
        "toml",
        data,
        idx,
        syn,
        rows,
        key_kind="TOML_KEY_MARKET_TOKEN",
        str_kind="TOML_STRING_MARKET_TOKEN",
        trace="V3 G1 TOML walk",
    )
    return rows, True


def scan_ini_file(rel: str, path: Path, idx: SchwabCsvIndex, syn: dict) -> tuple[list[RegisterRow], bool]:
    rows: list[RegisterRow] = []
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read_string(path.read_text(encoding="utf-8"), source=str(path))
    except Exception:
        return rows, False
    vocab = idx.vocabulary

    def handle_kv(section_name: str, key: str, val: str) -> None:
        fqk = f"{section_name}.{key}" if section_name != "DEFAULT" else key
        kh = _key_string_hits_vocab(key, vocab) + _key_string_hits_vocab(fqk, vocab)
        kh = sorted(set(kh))
        if kh:
            rows.append(
                _emit(
                    rel,
                    "ini",
                    1,
                    0,
                    "INI_KEY_MARKET_TOKEN",
                    fqk,
                    kh,
                    idx,
                    syn,
                    "V3 G1 INI walk",
                )
            )
        hits = vocab.words_in_line(val)
        if hits:
            rows.append(
                _emit(
                    rel,
                    "ini",
                    1,
                    0,
                    "INI_STRING_MARKET_TOKEN",
                    val[:200],
                    hits,
                    idx,
                    syn,
                    "V3 G1 INI walk",
                )
            )

    for key, val in cp.defaults().items():
        handle_kv("DEFAULT", key, val)
    for section in cp.sections():
        for key, val in cp.items(section):
            handle_kv(section, key, val)
    return rows, True
