"""SQL scan — V3; token hits from CSV vocabulary only (V3-A)."""

from __future__ import annotations

import re

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms

# Structural SQL concatenation / format — no market-token literals (V3-A).
_CONCAT = re.compile(r"\+|%\s*\(|\.format\s*\(")


def scan_sql_file(rel: str, text: str, idx: SchwabCsvIndex, syn: dict) -> list[RegisterRow]:
    rows: list[RegisterRow] = []
    vocab = idx.vocabulary
    for i, line in enumerate(text.splitlines(), start=1):
        hits = vocab.words_in_line(line)
        if not hits:
            continue
        etoks = expand_tokens_with_synonyms(hits, syn)
        if _CONCAT.search(line):
            kind = "DYNAMIC_SQL_BUILD"
            trace = "V3 G2 SQL dynamic build"
        else:
            kind = "SQL_STATIC_MARKET_TOKEN"
            trace = "V3 G1 SQL"
        rows.append(
            RegisterRow(
                register_id=RegisterRow.make_id(rel, i, 0, kind, "sql"),
                language="sql",
                path=rel,
                line=i,
                col=0,
                pattern_kind=kind,
                surface_form=line[:400],
                tokens=" ".join(etoks),
                csv_candidates=";".join(idx.candidates_token(etoks)),
                csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(line[:512], k=3)),
                v2_trace=trace,
            )
        )
    return rows
