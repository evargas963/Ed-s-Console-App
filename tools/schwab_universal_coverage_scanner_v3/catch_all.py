"""Universal text line scan — V3-B minimum path for every text file (V3-A vocabulary)."""

from __future__ import annotations

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex
from .synonyms import expand_tokens_with_synonyms


def scan_catch_all_lines(
    rel: str,
    text: str,
    idx: SchwabCsvIndex,
    syn: dict,
    *,
    language: str,
) -> list[RegisterRow]:
    rows: list[RegisterRow] = []
    vocab = idx.vocabulary
    for ln, line in enumerate(text.splitlines(), start=1):
        hits = vocab.words_in_line(line)
        if not hits:
            continue
        etoks = expand_tokens_with_synonyms(hits, syn)
        rows.append(
            RegisterRow(
                register_id=RegisterRow.make_id(rel, ln, 0, "TEXT_LINE_MARKET_TOKEN", language),
                language=language,
                path=rel,
                line=ln,
                col=0,
                pattern_kind="TEXT_LINE_MARKET_TOKEN",
                surface_form=line[:400],
                tokens=" ".join(etoks),
                csv_candidates=";".join(idx.candidates_token(etoks)),
                csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(line[:512], k=3)),
                v2_trace="V3-B universal catch-all (CSV-derived vocabulary)",
                notes="",
            )
        )
    return rows
